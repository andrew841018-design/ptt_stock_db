import psycopg2
from psycopg2 import pool as pg_pool
from contextlib import contextmanager
from config import PG_CONFIG, PG_API_CONFIG

@contextmanager
def get_pg(config=None):
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
    conn = psycopg2.connect(**PG_API_CONFIG)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass



_api_pool = None


def init_pool(minconn: int = 2, maxconn: int = 10) -> None:
    global _api_pool
    _api_pool = pg_pool.ThreadedConnectionPool(minconn, maxconn, **PG_API_CONFIG)


@contextmanager
def get_pg_pooled():
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

