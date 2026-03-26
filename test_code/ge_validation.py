from great_expectations.dataset import PandasDataset
import pandas as pd
import sqlite3
import os

try:
    from dependent_code.config import TABLE_ARTICLE  # 本地開發環境
except ImportError:
    from config import TABLE_ARTICLE  # cron /tmp 環境

_here = os.path.dirname(os.path.abspath(__file__))
_candidate1 = os.path.join(_here, '..', 'dependent_code', 'ptt_stock.db')  # 本地
_candidate2 = os.path.join(_here, 'ptt_stock.db')                           # cron /tmp
DB_PATH = _candidate1 if os.path.exists(_candidate1) else _candidate2

# 讀取資料
conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query(f"SELECT * FROM {TABLE_ARTICLE}", conn)
conn.close()

# 轉型
# coerce: 將無法轉換的值轉換為 NaN
df['Push_count'] = pd.to_numeric(df['Push_count'], errors='coerce')

# 建立 GE DataFrame
ge_df = PandasDataset(df)

# 定義規則
results = []
results.append(ge_df.expect_column_values_to_not_be_null('Title'))
results.append(ge_df.expect_column_values_to_not_be_null('Url'))
results.append(ge_df.expect_column_values_to_be_between('Push_count', -100, 100))
#規範網址=>bbs/stock or Stock/任意字元
results.append(ge_df.expect_column_values_to_match_regex('Url', r'/bbs/[Ss]tock/.*'))

# 印出結果
for r in results:
    status = "✅ PASS" if r.success else "❌ FAIL"
    col = r.expectation_config.kwargs.get("column")
    rule = r.expectation_config.expectation_type
    element_count = r.result.get("element_count", 0)
    unexpected_count = r.result.get("unexpected_count", 0)
    unexpected_percent = r.result.get("unexpected_percent", 0.0)
    print(f"{status} | 欄位: {col} | 規則: {rule} | 總筆數: {element_count} | 違規: {unexpected_count} 筆 ({unexpected_percent:.2f}%)")
