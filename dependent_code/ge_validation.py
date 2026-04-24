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

    # ── 各來源動態檢查（從 config.SOURCES 衍生，新增來源不需改這裡）──────────
    for key, src in SOURCES.items():
        name = src["name"]
        src_df = df[df['Source'] == name]

        if src_df.empty:
            logging.info(f"GE SKIP：{name} 無資料（尚未爬取）")
            continue

        ge_src = PandasDataset(src_df)

        # URL 格式檢查（只在 config 有設定 url_pattern 時執行）
        # GE 0.18.19 的 expect_column_values_to_match_regex 底層用 re.match（anchor 在字串開頭），
        # 但 config 的 url_pattern 是「URL 中某段子字串」語意（search），URL 開頭是 https://... 會 FAIL，
        # 所以補 .* 前綴讓 re.match 能從任意位置開始比對
        url_pattern = src.get("url_pattern")
        if url_pattern:
            _log_result(ge_src.expect_column_values_to_match_regex('Url', f".*{url_pattern}"))

        # push_count 檢查（只對有推文數的來源執行）
        if src.get("has_push_count"):
            _log_result(ge_src.expect_column_values_to_not_be_null('Push_count'))
            _log_result(ge_src.expect_column_values_to_be_between('Push_count', -100, 100))

    # ── us_stock_prices 檢查 ───────────────────────────────────────────────────
    with get_pg() as conn:
        us_df = pd.read_sql_query(
            f"SELECT trade_date, close, change FROM {US_STOCK_PRICES_TABLE}", conn)

    if not us_df.empty:
        ge_us = PandasDataset(us_df)
        _log_result(ge_us.expect_column_values_to_not_be_null('trade_date'))
        _log_result(ge_us.expect_column_values_to_not_be_null('close'))
        _log_result(ge_us.expect_column_values_to_be_between('close', 1, 10000))
        _log_result(ge_us.expect_column_values_to_be_between('change', -100, 100, mostly=0.99))
    else:
        logging.warning("GE WARN：us_stock_prices 無資料")
