import psycopg2
from contextlib import contextmanager
from config import PG_CONFIG, PG_API_CONFIG

@contextmanager
def get_pg(config=None):
    """PostgreSQL 連線 context manager，可指定角色的 config dict"""
    conn = psycopg2.connect(**(config or PG_CONFIG))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@contextmanager
def get_pg_readonly():
    """API 唯讀連線（api_user，只有 SELECT 權限）"""
    conn = psycopg2.connect(**PG_API_CONFIG)
    try:
        yield conn
    finally:
        conn.close()

