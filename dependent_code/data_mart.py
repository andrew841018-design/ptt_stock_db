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

sys.path.insert(0, os.path.dirname(__file__))
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


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
    呼叫 PostgreSQL Stored Function fn_get_daily_sentiment(p_days)。
    多來源用 total_articles 做加權，避免「平均的平均」失準。
    供 API sentiment endpoints 使用。
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fn_get_daily_sentiment(%s)", (days,))
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── 全刷 ──────────────────────────────────────────────────────────────────────

def refresh_all() -> None:
    """刷新所有 Data Mart（每日 ETL 跑完後呼叫）"""
    refresh_mart_daily_summary()
    logging.info("[DataMart] 所有 Data Mart 刷新完成")


