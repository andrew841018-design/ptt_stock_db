"""
Data Mart（Phase 4）

Data Mart = DW 的子集，針對特定用途預先彙整：
  - mart_daily_summary ：每日情緒摘要（供儀表板用）
  - mart_hot_stocks    ：熱門股票排行（供 API 用）

架構比較：
  ┌──────────────────┬───────────────────────────────────────────────┐
  │                  │  Materialized View          Data Mart Table   │
  ├──────────────────┼───────────────────────────────────────────────┤
  │ 儲存位置          │  PostgreSQL MV 物件          標準 table        │
  │ 更新方式          │  REFRESH MATERIALIZED VIEW   ETL TRUNCATE+INSERT│
  │ 可移植性          │  PostgreSQL 限定              任何 DB           │
  │ 本專案使用        │  mv_daily_summary / mv_hot_stocks 同步保留    │
  └──────────────────┴───────────────────────────────────────────────┘

執行方式：
  python data_mart.py          # 刷新兩個 Data Mart
  python data_mart.py summary  # 只刷新 mart_daily_summary
  python data_mart.py hot      # 只刷新 mart_hot_stocks
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
    每日情緒摘要刷新：TRUNCATE + INSERT FROM DW。
    資料來源：fact_sentiment（直接用 fact_date 欄位）
    供儀表板直接查 mart_daily_summary，不需掃 fact_sentiment 大表。
    回傳：寫入筆數
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE mart_daily_summary")
            cur.execute("""
                INSERT INTO mart_daily_summary
                    (summary_date, source_name, total_articles,
                     avg_sentiment, avg_push_count)
                SELECT
                    f.fact_date                    AS summary_date,
                    f.source_name,
                    SUM(f.article_count)           AS total_articles,
                    AVG(f.avg_sentiment)           AS avg_sentiment,
                    AVG(f.avg_push_count)          AS avg_push_count
                FROM fact_sentiment f
                GROUP BY f.fact_date, f.source_name
            """)
            count = cur.rowcount
        conn.commit()
    logging.info("[DataMart] mart_daily_summary 刷新完成，%d 筆", count)
    return count


# ─── mart_hot_stocks ───────────────────────────────────────────────────────────

def refresh_mart_hot_stocks() -> int:
    """
    熱門股票刷新：TRUNCATE + INSERT FROM DW。
    只保留有推文互動的資料（avg_push_count > 0）。
    Partial index idx_hot 對 push_count > 100 的查詢特別快。
    供 API /articles/top_push 端點直接查。
    回傳：寫入筆數
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE mart_hot_stocks")
            cur.execute("""
                INSERT INTO mart_hot_stocks
                    (report_date, source_name, push_count, article_count)
                SELECT
                    f.fact_date                         AS report_date,
                    f.source_name,
                    ROUND(f.avg_push_count)::INTEGER    AS push_count,
                    f.article_count
                FROM fact_sentiment f
                WHERE f.avg_push_count > 0
            """)
            count = cur.rowcount
        conn.commit()
    logging.info("[DataMart] mart_hot_stocks 刷新完成，%d 筆", count)
    return count


# ─── 查詢介面（供 API / Dashboard 呼叫）──────────────────────────────────────

def get_daily_summary(days: int = 30) -> list[dict]:
    """
    取近 N 天的每日情緒摘要（按來源分群）。
    直接查 mart_daily_summary，速度遠快於掃 fact_sentiment。
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary_date, source_name,
                       total_articles, avg_sentiment, avg_push_count
                FROM mart_daily_summary
                WHERE summary_date >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY summary_date DESC, source_name
            """, (days,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_daily_sentiment(days: int) -> list[dict]:
    """
    取近 N 天的每日加權平均情緒分數（跨來源聚合）。
    多來源用 total_articles 做加權，避免「平均的平均」失準。
    供 API sentiment endpoints 使用。
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    summary_date,
                    SUM(total_articles) AS total_articles,
                    SUM(avg_sentiment * total_articles)
                        / NULLIF(SUM(total_articles), 0) AS avg_sentiment
                FROM mart_daily_summary
                WHERE summary_date >= CURRENT_DATE - INTERVAL '%s days'
                  AND avg_sentiment IS NOT NULL
                GROUP BY summary_date
                ORDER BY summary_date DESC
            """, (days,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_hot_stocks_from_mart(min_push: int = 100, limit: int = 20) -> list[dict]:
    """
    取熱門股票排行（push_count > min_push）。
    Partial index idx_hot 在 min_push >= 100 時自動生效，查詢極快。
    """
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT report_date, source_name, push_count, article_count
                FROM mart_hot_stocks
                WHERE push_count > %s
                ORDER BY push_count DESC
                LIMIT %s
            """, (min_push, limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── 全刷 ──────────────────────────────────────────────────────────────────────

def refresh_all() -> None:
    """刷新所有 Data Mart（每日 ETL 跑完後呼叫）"""
    refresh_mart_daily_summary()
    refresh_mart_hot_stocks()
    logging.info("[DataMart] 所有 Data Mart 刷新完成")


