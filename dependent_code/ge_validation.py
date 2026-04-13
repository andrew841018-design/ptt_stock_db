import logging
import pandas as pd
from great_expectations.dataset import PandasDataset
from pg_helper import get_pg
from config import ARTICLES_TABLE, SOURCES_TABLE, SOURCES, US_STOCK_PRICES_TABLE

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _log_result(r) -> None:
    status            = "✅ PASS" if r.success else "❌ FAIL"
    col               = r.expectation_config.kwargs.get("column")
    rule              = r.expectation_config.expectation_type
    element_count     = r.result.get("element_count", 0)
    unexpected_count  = r.result.get("unexpected_count", 0)
    unexpected_percent = r.result.get("unexpected_percent", 0.0)
    msg = f"{status} | 欄位: {col} | 規則: {rule} | 總筆數: {element_count} | 違規: {unexpected_count} 筆 ({unexpected_percent:.2f}%)"
    logging.warning(msg) if not r.success else logging.info(msg)


def ge_validate():
    with get_pg() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                a.title        AS "Title",
                a.url          AS "Url",
                a.push_count   AS "Push_count",
                s.source_name  AS "Source"
            FROM {ARTICLES_TABLE} a
            JOIN {SOURCES_TABLE} s ON s.source_id = a.source_id
        """, conn)

    # ── 全來源共用檢查 ─────────────────────────────────────────────────────────
    ge_all = PandasDataset(df)
    _log_result(ge_all.expect_column_values_to_not_be_null('Title'))
    _log_result(ge_all.expect_column_values_to_not_be_null('Url'))

    # ── PTT 專屬檢查 ───────────────────────────────────────────────────────────
    ptt_df = df[df['Source'] == SOURCES["ptt"]["name"]]
    ge_ptt = PandasDataset(ptt_df)
    _log_result(ge_ptt.expect_column_values_to_not_be_null('Push_count'))
    _log_result(ge_ptt.expect_column_values_to_be_between('Push_count', -100, 100))
    _log_result(ge_ptt.expect_column_values_to_match_regex('Url', r'/bbs/[Ss]tock/.*'))

    # ── 鉅亨網專屬檢查 ─────────────────────────────────────────────────────────
    cnyes_df = df[df['Source'] == SOURCES["cnyes"]["name"]]
    ge_cnyes = PandasDataset(cnyes_df)
    _log_result(ge_cnyes.expect_column_values_to_match_regex('Url', r'news\.cnyes\.com/news/id/\d+'))

    # ── Reddit 專屬檢查 ────────────────────────────────────────────────────────
    reddit_df = df[df['Source'] == SOURCES["reddit"]["name"]]
    if not reddit_df.empty:
        ge_reddit = PandasDataset(reddit_df)
        # URL 格式：https://www.reddit.com/r/{subreddit}/comments/{id}/...
        _log_result(ge_reddit.expect_column_values_to_match_regex(
            'Url', r'reddit\.com/r/\w+/comments/'))
        # push_count 應在 -100~100（Reddit score clamp 過）
        _log_result(ge_reddit.expect_column_values_to_be_between('Push_count', -100, 100))
    else:
        logging.info("GE SKIP：Reddit 無資料（尚未爬取）")

    # ── us_stock_prices 檢查 ───────────────────────────────────────────────────
    with get_pg() as conn:
        us_df = pd.read_sql_query(
            f"SELECT trade_date, close, change FROM {US_STOCK_PRICES_TABLE}", conn)

    if not us_df.empty:
        ge_us = PandasDataset(us_df)
        _log_result(ge_us.expect_column_values_to_not_be_null('trade_date'))
        _log_result(ge_us.expect_column_values_to_not_be_null('close'))
        _log_result(ge_us.expect_column_values_to_be_between('close', 1, 10000))
        # change 每支 ETF 第一筆允許 NULL（無前一日收盤價）；非 NULL 的值應在合理範圍
        _log_result(ge_us.expect_column_values_to_be_between('change', -100, 100, mostly=0.99))
    else:
        logging.warning("GE WARN：us_stock_prices 無資料")

