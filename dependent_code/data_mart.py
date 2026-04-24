"""
Data Mart（Phase 4）

Data Mart = DW 的子集，針對特定用途預先彙整：
  - mart_daily_summary ：每日情緒摘要（供儀表板 + API sentiment endpoints 用）

架構比較：
  ┌──────────────────┬───────────────────────────────────────────────┐
  │                  │  Materialized View          Data Mart Table   │
  ├──────────────────┼───────────────────────────────────────────────┤
  │ 儲存位置          │  PostgreSQL MV 物件          標準 table        │
  │ 更新方式          │  REFRESH MATERIALIZED VIEW   ETL TRUNCATE+INSERT│
  │ 可移植性          │  PostgreSQL 限定              任何 DB           │
  │ 本專案使用        │  mv_market_summary           mart_daily_summary│
  │ 粒度             │  market（TW/US）              source（ptt/cnyes/reddit/cnn/wsj/marketwatch）│
  └──────────────────┴───────────────────────────────────────────────┘
  兩者互補：MV 跑市場層級聚合（Snowflake 三表 JOIN），Mart 跑 source 層級細粒度。
  MV 定義在 dw_schema.py，由 dw_etl.refresh_mv() 呼叫 REFRESH 更新。

"""

import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─── Stored Procedure / Function schema loader ────────────────────────────────
# SQL 邏輯集中在 scripts/init_marts.sql（移植自 btc_pipeline 的 SP/Function pattern）。
# 此處 loader 負責幂等套用，新環境或舊 DB 均可重複執行。
#
# 路徑候選：
#   - 專案 repo 結構下 data_mart.py 在 dependent_code/，init_marts.sql 在 ../scripts/
#   - 若未來 COPY 進 container，可補一個 /app/init_marts.sql fallback
_INIT_MARTS_SQL_CANDIDATES = [
    # resolve() 取絕對路徑，防止相對路徑因工作目錄不同而算錯
    # parent.parent = dependent_code/ → project/，再往下找 scripts/init_marts.sql
    Path(__file__).resolve().parent.parent / "scripts" / "init_marts.sql",  # dev / repo
    # Dockerfile 把 scripts/init_marts.sql COPY 到 /app/（和 data_mart.py 同層）
    Path(__file__).resolve().parent / "init_marts.sql",                     # container fallback
]


def _find_init_sql() -> Path:
    for candidate in _INIT_MARTS_SQL_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"init_marts.sql not found, tried: {[str(p) for p in _INIT_MARTS_SQL_CANDIDATES]}"
    )


def ensure_sp_schema() -> None:
    """幂等套用 init_marts.sql（SP + Function 定義）。

    在 dw_schema.create_dw_schema() 建好 table 之後呼叫，確保 SP/Function
    存在。CREATE OR REPLACE 讓此函式可重複執行不會報錯。
    """
    init_sql = _find_init_sql()
    sql = init_sql.read_text()
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    logging.info("[DataMart] init_marts.sql applied (idempotent) from %s", init_sql)


# ─── mart_daily_summary ────────────────────────────────────────────────────────

def refresh_mart_daily_summary() -> int:
    """
    每日情緒摘要刷新：呼叫 PostgreSQL Stored Procedure sp_refresh_mart_daily_summary()。
    SP 內部執行 TRUNCATE + INSERT FROM fact_sentiment。
    SQL 邏輯封裝在 DB 端，Python 只負責 CALL。
    回傳：寫入筆數
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("CALL sp_refresh_mart_daily_summary()")
            cur.execute("SELECT COUNT(*) FROM mart_daily_summary")
            count = cur.fetchone()[0]
    logging.info("[DataMart] mart_daily_summary 刷新完成，%d 筆", count)
    return count


# ─── 查詢介面（供 API / Dashboard 呼叫）──────────────────────────────────────

def get_daily_sentiment(days: int) -> list[dict]:
    """
    取近 N 天的每日加權平均情緒分數（跨來源聚合）。
    呼叫 PostgreSQL Stored Function fn_get_daily_sentiment(target_date, days)。
    多來源用 total_articles 做加權，避免「平均的平均」失準。
    供 API sentiment endpoints 使用。

    注意：SQL 函式簽名為 (target_date DATE DEFAULT CURRENT_DATE, days INT DEFAULT 30)，
    Python 端必須用 named argument `days := %s` 指定第二個參數，
    否則 positional 會把 Python 的 days（int）誤對到 SQL 的 target_date（DATE）。
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fn_get_daily_sentiment(days := %s)", (days,))
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── 全刷 ──────────────────────────────────────────────────────────────────────

def refresh_all() -> None:
    """刷新所有 Data Mart（每日 ETL 跑完後呼叫）。

    先 ensure_sp_schema()（幂等）確保 SP/Function 最新，再 CALL 刷新。
    """
    ensure_sp_schema()
    refresh_mart_daily_summary()
    logging.info("[DataMart] 所有 Data Mart 刷新完成")


