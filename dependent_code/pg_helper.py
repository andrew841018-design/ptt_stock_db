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
    """API 唯讀連線（api_user，只有 SELECT 權限）"""
    conn = psycopg2.connect(**PG_API_CONFIG)
    try:
        yield conn
    finally:
        # 與 get_pg() 對稱：server 主動斷線時 close 也會 raise InterfaceError，吞掉避免覆蓋業務例外
        try:
            conn.close()
        except Exception:
            pass

