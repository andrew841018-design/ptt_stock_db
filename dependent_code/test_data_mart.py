
import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import data_mart




@contextmanager
def _fake_pg_ctx(mock_cur):
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = None
    yield mock_conn


def test_get_daily_sentiment_uses_named_arg():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        ("2026-04-19", "ptt", 100, 0.1, 50),
    ]
    mock_cur.description = [
        ("summary_date",), ("source_name",), ("total_articles",),
        ("avg_sentiment",), ("avg_push_count",),
    ]

    with patch.object(data_mart, "get_pg") as mock_get_pg:
        mock_get_pg.return_value.__enter__.return_value = _fake_pg_ctx(mock_cur).__enter__()
        mock_get_pg.return_value.__exit__.return_value = None
        data_mart.get_daily_sentiment(days=7)

    call_args = mock_cur.execute.call_args_list
    assert len(call_args) > 0, "execute 必須被呼叫"
    sql_str = str(call_args[0][0][0])
    assert "%s" in sql_str, f"SQL 必須參數化（有 %%s）：{sql_str[:200]}"
    assert "INTERVAL '7 days'" not in sql_str, "禁用 INTERVAL '{}' days f-string 拼接"


def test_refresh_mart_daily_summary_calls_sp():
    mock_cur = MagicMock()

    with patch.object(data_mart, "get_pg") as mock_get_pg:
        mock_get_pg.return_value.__enter__.return_value = _fake_pg_ctx(mock_cur).__enter__()
        mock_get_pg.return_value.__exit__.return_value = None
        data_mart.refresh_mart_daily_summary()

    call_sqls = [str(c[0][0]) for c in mock_cur.execute.call_args_list]
    joined = " ".join(call_sqls).upper()
    assert "CALL" in joined, f"必須 CALL SP() 而非 inline SQL：{joined[:300]}"
    assert "SP_REFRESH_MART_DAILY_SUMMARY" in joined


def test_refresh_mart_market_summary_calls_sp():
    mock_cur = MagicMock()

    with patch.object(data_mart, "get_pg") as mock_get_pg:
        mock_get_pg.return_value.__enter__.return_value = _fake_pg_ctx(mock_cur).__enter__()
        mock_get_pg.return_value.__exit__.return_value = None
        data_mart.refresh_mart_market_summary()

    call_sqls = [str(c[0][0]) for c in mock_cur.execute.call_args_list]
    joined = " ".join(call_sqls).upper()
    assert "CALL" in joined
    assert "SP_REFRESH_MART_MARKET_SUMMARY" in joined




@pytest.mark.integration
def test_sp_objects_exist(real_pg):
    expected_procs = {
        "sp_refresh_mart_daily_summary",
        "sp_refresh_mart_market_summary",
        "sp_populate_fact_sentiment",
    }
    expected_funcs = {"fn_get_daily_sentiment"}

    with real_pg.cursor() as cur:
        cur.execute(
            """
            SELECT routine_name, routine_type
            FROM information_schema.routines
            WHERE routine_schema = 'public'
              AND routine_name IN %s
            """,
            (tuple(expected_procs | expected_funcs),),
        )
        found = {(name, kind) for name, kind in cur.fetchall()}

    found_names = {n for n, _ in found}
    assert expected_procs.issubset(found_names), \
        f"缺 SP：{expected_procs - found_names}"
    assert expected_funcs.issubset(found_names), \
        f"缺 Function：{expected_funcs - found_names}"


@pytest.mark.integration
def test_mart_tables_exist_with_correct_columns(real_pg):
    expected = {
        "mart_daily_summary": {
            "summary_date", "source_name", "total_articles",
            "scored_articles",
            "avg_sentiment", "avg_push_count",
        },
        "mart_market_summary": {
            "fact_date", "market_code", "source_count",
            "total_articles", "avg_sentiment", "avg_push_count",
        },
    }
    with real_pg.cursor() as cur:
        for table, cols in expected.items():
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                """,
                (table,),
            )
            actual = {row[0] for row in cur.fetchall()}
            assert cols.issubset(actual), \
                f"{table} 缺欄位：{cols - actual}"


@pytest.mark.integration
def test_old_mv_market_summary_dropped(real_pg):
    with real_pg.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_matviews
            WHERE schemaname='public' AND matviewname='mv_market_summary'
            """
        )
        count = cur.fetchone()[0]
    assert count == 0, "mv_market_summary MV 應已 DROP，但仍存在"


@pytest.mark.integration
def test_refresh_mart_daily_summary_real_run(real_pg):
    n = data_mart.refresh_mart_daily_summary()
    with real_pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM mart_daily_summary")
        actual = cur.fetchone()[0]
    assert n == actual, f"SP 回傳 {n}，但表內實際 {actual}"


@pytest.mark.integration
def test_refresh_mart_market_summary_real_run(real_pg):
    n = data_mart.refresh_mart_market_summary()
    with real_pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM mart_market_summary")
        actual = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT market_code FROM mart_market_summary")
        markets = {row[0] for row in cur.fetchall()}
    assert n == actual, f"SP 回傳 {n}，但表內實際 {actual}"
    if n > 0:
        assert markets.issubset({"TW", "US"}), \
            f"unexpected market_code: {markets - {'TW', 'US'}}"


@pytest.mark.integration
def test_get_daily_sentiment_real_shape(real_pg):
    rows = data_mart.get_daily_sentiment(days=7)
    assert isinstance(rows, list)
    if rows:
        required = {"summary_date", "source_name", "total_articles", "scored_articles", "avg_sentiment"}
        assert required.issubset(rows[0].keys()), \
            f"缺欄位：{required - set(rows[0].keys())}"


@pytest.mark.integration
def test_create_dw_schema_idempotent(real_pg):
    from dw_schema import create_dw_schema
    create_dw_schema()
    create_dw_schema()


@pytest.mark.integration
def test_ensure_sp_schema_idempotent(real_pg):
    data_mart.ensure_sp_schema()
    data_mart.ensure_sp_schema()
