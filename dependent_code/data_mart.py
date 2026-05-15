
import logging
import sys
import os
from pathlib import Path

import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
from pg_helper import get_pg
from config import PG_ADMIN_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


_INIT_MARTS_SQL_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "scripts" / "init_marts.sql",
    Path(__file__).resolve().parent / "init_marts.sql",
]


def _find_init_sql() -> Path:
    for candidate in _INIT_MARTS_SQL_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"init_marts.sql not found, tried: {[str(p) for p in _INIT_MARTS_SQL_CANDIDATES]}"
    )


def ensure_sp_schema() -> None:
    init_sql = _find_init_sql()
    sql = init_sql.read_text()
    conn = psycopg2.connect(**PG_ADMIN_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()
    logging.info("[DataMart] init_marts.sql applied (idempotent) from %s", init_sql)



def refresh_mart_daily_summary() -> int:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("CALL sp_refresh_mart_daily_summary()")
            cur.execute("SELECT COUNT(*) FROM mart_daily_summary")
            count = cur.fetchone()[0]
    logging.info("[DataMart] mart_daily_summary 刷新完成，%d 筆", count)
    return count



def get_daily_sentiment(days: int) -> list[dict]:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fn_get_daily_sentiment(days := %s)", (days,))
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]



def refresh_mart_market_summary() -> int:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("CALL sp_refresh_mart_market_summary()")
            cur.execute("SELECT COUNT(*) FROM mart_market_summary")
            count = cur.fetchone()[0]
    logging.info("[DataMart] mart_market_summary 刷新完成，%d 筆", count)
    return count



def refresh_all() -> None:
    ensure_sp_schema()
    refresh_mart_daily_summary()
    refresh_mart_market_summary()
    logging.info("[DataMart] 所有 Data Mart 刷新完成")


