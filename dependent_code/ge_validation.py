import logging
import pandas as pd
from great_expectations.dataset import PandasDataset
from pg_helper import get_pg
from config import ARTICLES_TABLE

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 讀取資料
with get_pg() as conn:
    df = pd.read_sql_query(f"""
        SELECT
            a.title      AS "Title",
            a.url        AS "Url",
            a.push_count AS "Push_count"
        FROM {ARTICLES_TABLE} a
    """, conn)

# 建立 GE DataFrame
ge_df = PandasDataset(df)

# 定義規則
results = []
results.append(ge_df.expect_column_values_to_not_be_null('Title'))
results.append(ge_df.expect_column_values_to_not_be_null('Url'))
results.append(ge_df.expect_column_values_to_be_between('Push_count', -100, 100))
# 規範網址=>bbs/stock or Stock/任意字元
results.append(ge_df.expect_column_values_to_match_regex('Url', r'/bbs/[Ss]tock/.*'))

# 印出結果
for r in results:
    status            = "✅ PASS" if r.success else "❌ FAIL"
    col               = r.expectation_config.kwargs.get("column")
    rule              = r.expectation_config.expectation_type
    element_count     = r.result.get("element_count", 0)
    unexpected_count  = r.result.get("unexpected_count", 0)
    unexpected_percent = r.result.get("unexpected_percent", 0.0)
    if not r.success:
        logging.warning(f"{status} | 欄位: {col} | 規則: {rule} | 總筆數: {element_count} | 違規: {unexpected_count} 筆 ({unexpected_percent:.2f}%)")
    else:
        logging.info(f"{status} | 欄位: {col} | 規則: {rule} | 總筆數: {element_count} | 違規: {unexpected_count} 筆 ({unexpected_percent:.2f}%)")
