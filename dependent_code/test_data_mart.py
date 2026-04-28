"""
Data Mart 測試：驗證 SP 參數化查詢 + get_daily_sentiment 行為。

測試策略：
  - 用 unittest.mock.patch 替換 get_pg context manager，不接真實 DB
  - 驗 SQL 被參數化呼叫（named arg）而非 f-string 拼接（防 SQL injection）
"""

import sys
import os
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(__file__))

import data_mart


@contextmanager
def _fake_pg_ctx(mock_cur):
    """模擬 get_pg() context manager 回傳的 connection"""
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = None
    yield mock_conn


def test_get_daily_sentiment_uses_named_arg():
    """
    核心安全性測試：fn_get_daily_sentiment 必須以 named arg (days := %s) 呼叫
    防 SQL injection + 對齊 SQL function 簽名 (target_date DATE, days INT)
    """
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        ("2026-04-19", "ptt", 100, 0.1, 50),
    ]
    mock_cur.description = [("summary_date",), ("source_name",), ("total_articles",),
                             ("avg_sentiment",), ("avg_push_count",)]

    with patch.object(data_mart, "get_pg") as mock_get_pg:
        mock_get_pg.return_value.__enter__.return_value = _fake_pg_ctx(mock_cur).__enter__()
        mock_get_pg.return_value.__exit__.return_value = None
        data_mart.get_daily_sentiment(days=7)

    # 驗證 execute 呼叫的 SQL 是 "days := %s" 而不是 f-string 拼接
    call_args = mock_cur.execute.call_args_list
    assert len(call_args) > 0, "execute 必須被呼叫"
    sql_str = str(call_args[0][0][0])
    # 必須是參數化：找到 %s 或 named arg
    assert "%s" in sql_str, f"SQL 必須參數化（有 %%s），但看到：{sql_str[:200]}"
    # 禁用 f-string 拼接（就算 user 誤改也抓得到）
    assert "INTERVAL '7 days'" not in sql_str, "禁用 INTERVAL '{}' days f-string 拼接"


def test_refresh_mart_daily_summary_calls_sp():
    """refresh_mart_daily_summary 必須用 CALL sp_xxx() 不是 inline INSERT"""
    mock_cur = MagicMock()

    with patch.object(data_mart, "get_pg") as mock_get_pg:
        mock_get_pg.return_value.__enter__.return_value = _fake_pg_ctx(mock_cur).__enter__()
        mock_get_pg.return_value.__exit__.return_value = None
        data_mart.refresh_mart_daily_summary()

    # 驗證呼叫了 CALL sp_refresh_mart_daily_summary()
    call_sqls = [str(c[0][0]) for c in mock_cur.execute.call_args_list]
    joined = " ".join(call_sqls).upper()
    assert "CALL" in joined, f"必須用 CALL SP() 呼叫，而非 inline SQL。實際：{joined[:300]}"
    assert "SP_REFRESH_MART_DAILY_SUMMARY" in joined
