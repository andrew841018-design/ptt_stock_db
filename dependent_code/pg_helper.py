import psycopg2
from psycopg2 import pool as pg_pool
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
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

@contextmanager
def get_pg_readonly():
    """API 唯讀連線（api_user，只有 SELECT 權限）。單次連線，適合 CLI / 低頻呼叫。"""
    conn = psycopg2.connect(**PG_API_CONFIG)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Connection Pool（API 用）─────────────────────────────────────────────
# FastAPI lifespan 啟動時呼叫 init_pool()，之後所有 API handler 改用 get_pg_pooled()

_api_pool = None


def init_pool(minconn: int = 2, maxconn: int = 10) -> None:
    """建立 ThreadedConnectionPool，FastAPI lifespan 呼叫一次即可。"""
    global _api_pool
    _api_pool = pg_pool.ThreadedConnectionPool(minconn, maxconn, **PG_API_CONFIG)


@contextmanager
def get_pg_pooled():
    """從 pool 借連線；pool 未初始化時 fallback 到單次連線。"""
    if _api_pool is None:
        with get_pg_readonly() as conn:
            yield conn
        return
    conn = _api_pool.getconn()
    try:
        yield conn
    finally:
        try:
            conn.reset()
        except Exception:
            pass
        try:
            _api_pool.putconn(conn)
        except Exception:
            pass

