
import logging
import os
import subprocess
import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    ARTICLES_TABLE,
    SENTIMENT_SCORES_TABLE,
    SOURCES_TABLE,
    STOCK_PRICES_TABLE,
    US_STOCK_PRICES_TABLE,
    AI_MODEL_PREDICTION_RUNS_TABLE,
)
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


from config import sources_by_market

MARKET_CONFIG = {
    "tw": {
        "prices_table": STOCK_PRICES_TABLE,
        "sources":      sources_by_market("TW"),
        "display_name": "0050 元大台灣50",
    },
    "us": {
        "prices_table": US_STOCK_PRICES_TABLE,
        "sources":      sources_by_market("US"),
        "display_name": "VOO Vanguard S&P 500 ETF",
    },
}

WALK_FORWARD_MONTHS = 3
MIN_TRAIN_MONTHS   = 3



def fetch_sentiment(sources: list[str]) -> pd.DataFrame:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    a.published_at::date          AS date,
                    AVG(ss.score)                 AS avg_sentiment,
                    COUNT(a.article_id)           AS article_count,
                    AVG(COALESCE(a.push_count,0)) AS avg_push_count
                FROM {ARTICLES_TABLE} a
                JOIN {SOURCES_TABLE} s    ON s.source_id  = a.source_id
                LEFT JOIN {SENTIMENT_SCORES_TABLE} ss ON ss.article_id = a.article_id
                WHERE s.source_name = ANY(%s)
                GROUP BY a.published_at::date
                ORDER BY date
            """, (sources,))
            cols = [desc[0] for desc in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)

    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_price(prices_table: str, start: str, end: str) -> pd.DataFrame:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT trade_date AS date, close
                FROM {prices_table}
                WHERE trade_date >= %s AND trade_date < %s
                ORDER BY trade_date
            """, (start, end))
            cols = [desc[0] for desc in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)

    if df.empty:
        logging.warning("[AI Prediction] %s 無股價資料 %s ~ %s", prices_table, start, end)
        return df

    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)

    next_close = df["close"].shift(-1)
    df["next_return"] = (next_close - df["close"]) / df["close"]
    df["next_day_up"] = (df["next_return"] > 0).astype(int)
    df = df.dropna(subset=["next_return"])
    return df



def merge_and_add_features(sent_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df.merge(sent_df, on="date", how="inner")

    df["sentiment_yesterday"] = df["avg_sentiment"].shift(1)

    df["sentiment_3day_avg"]     = df["avg_sentiment"].shift(1).rolling(3).mean()
    df["push_count_3day_avg"]    = df["avg_push_count"].shift(1).rolling(3).mean()
    df["article_count_3day_avg"] = df["article_count"].shift(1).rolling(3).mean()

    df = df.dropna()
    df = df.reset_index(drop=True)
    return df


FEATURES = [
    "avg_sentiment",
    "sentiment_yesterday",
    "sentiment_3day_avg",
    "avg_push_count",
    "push_count_3day_avg",
    "article_count",
    "article_count_3day_avg",
]



def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    results = []

    min_date = df["date"].min()
    max_date = df["date"].max()

    train_end = min_date + pd.DateOffset(months=MIN_TRAIN_MONTHS)

    while train_end < max_date:
        test_end = train_end + pd.DateOffset(months=WALK_FORWARD_MONTHS)

        train_df = df[df["date"] <  train_end]
        test_df  = df[(df["date"] >= train_end) & (df["date"] < test_end)]

        if train_df.empty or test_df.empty:
            train_end = test_end
            continue

        X_train = train_df[FEATURES]
        y_train = train_df["next_day_up"]
        X_test  = test_df[FEATURES]
        y_test  = test_df["next_day_up"]

        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)

        step_df = test_df[["date", "close", "next_return"]].copy()
        step_df["true"] = y_test.values
        step_df["pred"] = y_pred
        results.append(step_df)

        train_end = test_end

    if not results:
        return pd.DataFrame()
    return pd.concat(results, ignore_index=True)



def enrich_and_log(result_df: pd.DataFrame, display_name: str) -> pd.DataFrame:
    y_true = result_df["true"]
    y_pred = result_df["pred"]

    accuracy = accuracy_score(y_true, y_pred)
    logging.info("\n%s", "=" * 55)
    logging.info("[%s] Walk-Forward 預測結果", display_name)
    logging.info("  樣本數   : %d 天", len(result_df))
    logging.info("  Accuracy : %.4f", accuracy)
    logging.info("\n%s", classification_report(y_true, y_pred,
                                               target_names=["跌(0)", "漲(1)"]))

    result_df = result_df.copy()
    result_df["strategy_daily_return"]      = result_df["next_return"] * (result_df["pred"] == 1)
    result_df["strategy_cumulative_return"] = (1 + result_df["strategy_daily_return"]).cumprod()
    first_close = result_df["close"].iloc[0]
    result_df["buy_and_hold_return"]        = result_df["close"] / first_close

    final_strategy     = result_df["strategy_cumulative_return"].iloc[-1]
    final_buy_and_hold = result_df["buy_and_hold_return"].iloc[-1]
    logging.info("  策略累積報酬    : %.2f%%", (final_strategy - 1) * 100)
    logging.info("  Buy-and-Hold   : %.2f%%", (final_buy_and_hold - 1) * 100)
    logging.info("  相對超額報酬    : %.2f%%", (final_strategy - final_buy_and_hold) * 100)
    logging.info("%s\n", "=" * 55)

    return result_df



def _save_run_to_db(market: str, result_df: pd.DataFrame) -> None:
    accuracy           = float((result_df["true"] == result_df["pred"]).mean())
    strategy_final     = float(result_df["strategy_cumulative_return"].iloc[-1])
    buy_and_hold_final = float(result_df["buy_and_hold_return"].iloc[-1])
    sample_days        = len(result_df)

    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {AI_MODEL_PREDICTION_RUNS_TABLE}
                    (market, accuracy, strategy_cumulative_return, buy_and_hold_return, sample_days)
                VALUES (%s, %s, %s, %s, %s)
            """, (market, accuracy, strategy_final, buy_and_hold_final, sample_days))
    logging.info("[AI Prediction] 寫入 %s（market=%s）", AI_MODEL_PREDICTION_RUNS_TABLE, market)


def _log_to_mlflow(market: str, display_name: str, result_df: pd.DataFrame) -> None:
    try:
        import mlflow
    except ImportError:
        logging.warning("[AI Prediction] mlflow 未安裝，跳過 tracking（pip install mlflow）")
        return

    try:
        mlflow.set_experiment(f"ai_model_prediction_{market}")
        with mlflow.start_run(run_name=display_name):
            mlflow.log_params({
                "market":              market,
                "walk_forward_months": WALK_FORWARD_MONTHS,
                "min_train_months":    MIN_TRAIN_MONTHS,
                "n_estimators":        100,
                "features":            ",".join(FEATURES),
            })
            accuracy           = float((result_df["true"] == result_df["pred"]).mean())
            strategy_final     = float(result_df["strategy_cumulative_return"].iloc[-1])
            buy_and_hold_final = float(result_df["buy_and_hold_return"].iloc[-1])
            mlflow.log_metrics({
                "accuracy":                   accuracy,
                "strategy_cumulative_return": strategy_final - 1,
                "buy_and_hold_return":        buy_and_hold_final - 1,
                "excess_return":              strategy_final - buy_and_hold_final,
                "sample_days":                len(result_df),
            })
    except Exception as e:
        logging.warning("[AI Prediction] mlflow log 失敗：%s", e)


def _spawn_bert_inference_background() -> None:
    cwd = os.path.dirname(__file__)
    subprocess.Popen(
        [sys.executable, "-c",
         f"import sys, os; sys.path.insert(0, {cwd!r}); "
         "from bert_sentiment import run_batch_inference; run_batch_inference()"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logging.warning("[AI Prediction] 已在背景啟動 BERT 批次推論，請稍後再試。")


def run_ai_model_prediction(market: str) -> Optional[pd.DataFrame]:
    cfg = MARKET_CONFIG[market]
    logging.info("[AI Prediction] 開始預測：%s", cfg["display_name"])

    sent_df = fetch_sentiment(cfg["sources"])
    if sent_df.empty:
        logging.warning("[AI Prediction] 無情緒資料，跳過 %s", market)
        return None

    if sent_df["avg_sentiment"].isna().all():
        logging.warning("[AI Prediction] sentiment_scores 全為 NULL，跳過 %s", market)
        _spawn_bert_inference_background()
        return None

    start = sent_df["date"].min().strftime("%Y-%m-%d")
    end   = (date.today() + timedelta(days=1)).isoformat()

    price_df = fetch_price(cfg["prices_table"], start, end)
    if price_df.empty:
        logging.warning("[AI Prediction] 無股價資料，跳過 %s", market)
        return None

    df = merge_and_add_features(sent_df, price_df)
    logging.info("[AI Prediction] 合併後資料 %d 天", len(df))
    if len(df) < MIN_TRAIN_MONTHS * 20:
        logging.warning("[AI Prediction] 資料量不足（%d 天），至少需要 %d 天",
                        len(df), MIN_TRAIN_MONTHS * 20)
        return None

    result_df = walk_forward(df)
    if result_df.empty:
        logging.warning("[AI Prediction] walk_forward 無法產生預測結果")
        return None

    enriched = enrich_and_log(result_df, cfg["display_name"])

    try:
        _save_run_to_db(market, enriched)
    except Exception as e:
        logging.warning("[AI Prediction] 寫入 ai_model_prediction_runs 失敗：%s", e)
    _log_to_mlflow(market, cfg["display_name"], enriched)

    return enriched


