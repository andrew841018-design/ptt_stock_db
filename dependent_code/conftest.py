
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: 需要真實 PostgreSQL 的整合測試（PG 不存在時 skip）",
    )


@pytest.fixture(scope="session")
def _real_pg_session_conn():
    import psycopg2
    try:
        from config import PG_CONFIG
    except Exception as e:
        pytest.skip(f"config.PG_CONFIG 載不到，跳過 integration 測試: {e}")

    try:
        conn = psycopg2.connect(**PG_CONFIG)
    except psycopg2.OperationalError as e:
        pytest.skip(f"PostgreSQL 連不上，跳過 integration 測試: {e}")

    yield conn
    conn.close()


@pytest.fixture
def real_pg(_real_pg_session_conn):
    yield _real_pg_session_conn
    try:
        _real_pg_session_conn.rollback()
    except Exception:
        pass
