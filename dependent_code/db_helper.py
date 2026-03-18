import sqlite3
from contextlib import contextmanager
from config import DB_PATH

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn#return the connection to the context manager
        conn.commit()#commit the transaction after with finish
    finally:
        conn.close()#close the connection after with finish
