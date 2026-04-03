import logging
import pandas as pd
from great_expectations.dataset import PandasDataset
from pg_helper import get_pg
from config import ARTICLES_TABLE, SOURCES_TABLE, SOURCES

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


if __name__ == "__main__":
    ge_validate()
