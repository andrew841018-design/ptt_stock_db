import psycopg2
from contextlib import contextmanager
from config import PG_CONFIG

@contextmanager
def get_pg():
    conn = psycopg2.connect(**PG_CONFIG)#展開PG_CONFIG
    try:
        yield conn#return the connection to the context manager
        conn.commit()#commit the transaction after with finish
    except Exception:
        conn.rollback()#rollback the transaction if an error occurs
        raise
    finally:
        conn.close()#close the connection after with finish
