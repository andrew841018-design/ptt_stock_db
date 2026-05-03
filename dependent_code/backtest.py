"""
回測系統設計（p5-label-5）

流程：
  1. 從 DB 取每日情緒聚合（avg_sentiment, article_count）
  2. 從 DB 讀股價（stock_prices / us_stock_prices，由爬蟲階段填入）
  3. 計算隔日漲跌方向（next_day_up：1 漲 / 0 跌）
  4. 特徵工程：sentiment_yesterday / sentiment_3day_avg / push_count_3day_avg
  5. RandomForest Walk-Forward Validation（每季擴展訓練集）
  6. 輸出：Accuracy / F1 / Precision / Recall + 累積報酬曲線

"""

import logging
import os
import sys
from datetime import date, timedelta

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    ARTICLES_TABLE,
    SENTIMENT_SCORES_TABLE,
    STOCK_PRICES_TABLE,
    US_STOCK_PRICES_TABLE,
)
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── 設定 ──────────────────────────────────────────────────────────────────────

MARKET_CONFIG = {
    "tw": {
        "prices_table": STOCK_PRICES_TABLE,
        "sources":      ["ptt", "cnyes"],
        "display_name": "0050 元大台灣50",
    },
    "us": {
        "prices_table": US_STOCK_PRICES_TABLE,
        "sources":      ["reddit"],
        "display_name": "VOO Vanguard S&P 500 ETF",
    },
}

WALK_FORWARD_MONTHS = 3   # 每次往前推進 N 個月
MIN_TRAIN_MONTHS   = 3    # 最少需要 N 個月訓練資料才起跑
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backtest_output")


# ─── 資料抓取 ──────────────────────────────────────────────────────────────────

def fetch_sentiment(sources: list[str]) -> pd.DataFrame:
    """
    從 DB 撈每日情緒聚合。
    回傳 DataFrame：date / avg_sentiment / article_count / avg_push_count
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    a.published_at::date          AS date,
                    AVG(ss.score)                 AS avg_sentiment,
                    COUNT(a.article_id)           AS article_count,
                    AVG(COALESCE(a.push_count,0)) AS avg_push_count
                FROM {ARTICLES_TABLE} a
                JOIN sources s           ON s.source_id  = a.source_id
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
    """
    從 DB 讀股價（由爬蟲階段 tw_stock_fetcher / us_stock_fetcher 填入），
    計算隔日漲跌幅（next_return）與二元方向（next_day_up：1 漲 / 0 跌）。
    回傳 DataFrame：date / close / next_return / next_day_up
    end 為 exclusive（與 yfinance 原語意一致）。
    """
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
        logging.warning("[Backtest] %s 無股價資料 %s ~ %s", prices_table, start, end)
        return df

    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)   # NUMERIC → Decimal，轉 float 供 sklearn 使用

    # 隔日報酬 = (明日 close - 今日 close) / 今日 close
    next_close = df["close"].shift(-1)
    df["next_return"] = (next_close - df["close"]) / df["close"]
    df["next_day_up"] = (df["next_return"] > 0).astype(int)   # 1 漲，0 跌
    df = df.dropna(subset=["next_return"])# drop rows with missing next_return=>the last day doesn't have tomorrow
    return df


# ─── 特徵工程 ──────────────────────────────────────────────────────────────────

def merge_and_add_features(sent_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
    """
    merge：按 date 把情緒 df 和股價 df 合併。
    add features：加 lag-1 情緒、3 日移動平均（情緒/推文數/文章數）。
    最後 dropna 清掉 shift/rolling 產生的前幾筆 NaN。
    """
    df = price_df.merge(sent_df, on="date", how="inner")

    # 昨日情緒（昨日情緒對今日漲跌的預測力）
    df["sentiment_yesterday"] = df["avg_sentiment"].shift(1)

    # 3 日移動平均
    #shift(1)->yesterday,rolling(3)->以昨天為基準（包含昨天）往前推3天,mean()->平均
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


# ─── Walk-Forward Validation ───────────────────────────────────────────────────

def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """
    Walk-Forward（擴展窗口）：
      - 每次以「所有歷史資料」訓練，預測下一季
      - 每 WALK_FORWARD_MONTHS 個月前進一步
    回傳每一步的預測 DataFrame（date / true / pred / next_return）
    """
    df = df.sort_values("date").reset_index(drop=True)
    results = []

    min_date = df["date"].min()
    max_date = df["date"].max()

    # 起始訓練截止日
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

        step_df = test_df[["date", "next_return"]].copy()
        step_df["true"] = y_test.values
        step_df["pred"] = y_pred
        results.append(step_df)

        train_end = test_end

    if not results:
        return pd.DataFrame()
    return pd.concat(results, ignore_index=True)


# ─── 績效評估 ──────────────────────────────────────────────────────────────────

def evaluate(result_df: pd.DataFrame, display_name: str) -> None:
    """輸出準確率、分類報告，並計算「只做多頭信號」的累積報酬"""
    y_true = result_df["true"]
    y_pred = result_df["pred"]

    accuracy = accuracy_score(y_true, y_pred)
    logging.info("\n%s", "=" * 55)
    logging.info("[%s] Walk-Forward 回測結果", display_name)
    logging.info("  樣本數   : %d 天", len(result_df))
    logging.info("  Accuracy : %.4f", accuracy)
    logging.info("\n%s", classification_report(y_true, y_pred,
                                               target_names=["跌(0)", "漲(1)"]))

    # 策略報酬：模型預測漲才進場(拿到真實 next_return)，否則空倉(0 報酬)
    # vectorized：布林 × 數值 → True=1、False=0，逐元素相乘
    result_df = result_df.copy()
    result_df["strategy_return"]         = result_df["next_return"] * (result_df["pred"] == 1)
    result_df["cumulative_strategy"]     = (1 + result_df["strategy_return"]).cumprod()
    result_df["cumulative_buy_and_hold"] = (1 + result_df["next_return"]).cumprod()

    final_strategy     = result_df["cumulative_strategy"].iloc[-1]
    final_buy_and_hold = result_df["cumulative_buy_and_hold"].iloc[-1]
    logging.info("  策略累積報酬    : %.2f%%", (final_strategy - 1) * 100)
    logging.info("  Buy-and-Hold   : %.2f%%", (final_buy_and_hold - 1) * 100)
    logging.info("  相對超額報酬    : %.2f%%", (final_strategy - final_buy_and_hold) * 100)
    logging.info("%s\n", "=" * 55)

    # 儲存結果 CSV（加日期後綴，保留歷史供 Streamlit 讀取 + model drift 分析）
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str = date.today().strftime("%Y%m%d")
    out_path = os.path.join(OUTPUT_DIR, f"backtest_{display_name.split()[0]}_{today_str}.csv")
    result_df.to_csv(out_path, index=False)
    logging.info("[Backtest] 結果已儲存至 %s", out_path)


# ─── 主流程 ────────────────────────────────────────────────────────────────────

def run_backtest(market: str) -> None:
    cfg = MARKET_CONFIG[market]
    logging.info("[Backtest] 開始回測：%s", cfg["display_name"])

    # 1. 情緒資料
    sent_df = fetch_sentiment(cfg["sources"])
    if sent_df.empty:
        logging.warning("[Backtest] 無情緒資料，跳過 %s", market)
        return

    # BERT 推論未完成 → 自動觸發 run_batch_inference() 補資料，完成後重查一次
    if sent_df["avg_sentiment"].isna().all():
        logging.warning("[Backtest] sentiment_scores 全為 NULL，自動觸發 BERT 推論...")
        from bert_sentiment import run_batch_inference
        run_batch_inference()
        sent_df = fetch_sentiment(cfg["sources"])
        if sent_df["avg_sentiment"].isna().all():
            logging.warning("[Backtest] BERT 推論後仍無情緒資料，跳過 %s", market)
            return

    start = sent_df["date"].min().strftime("%Y-%m-%d")
    end   = (date.today() + timedelta(days=1)).isoformat()

    # 2. 股價資料
    price_df = fetch_price(cfg["prices_table"], start, end)
    if price_df.empty:
        logging.warning("[Backtest] 無股價資料，跳過 %s", market)
        return

    # 3. 合併 + 特徵工程
    df = merge_and_add_features(sent_df, price_df)
    logging.info("[Backtest] 合併後資料 %d 天", len(df))
    if len(df) < MIN_TRAIN_MONTHS * 20:   # 粗估每月 20 個交易日
        logging.warning("[Backtest] 資料量不足（%d 天），至少需要 %d 天",
                        len(df), MIN_TRAIN_MONTHS * 20)
        return

    # 4. Walk-Forward 回測
    result_df = walk_forward(df)
    if result_df.empty:
        logging.warning("[Backtest] walk_forward 無法產生預測結果")
        return

    # 5. 評估
    evaluate(result_df, cfg["display_name"])


