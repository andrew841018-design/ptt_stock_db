"""
wayback_backfill_daily — Wayback Machine 近期年份回填（CNN + WSJ 2022-2025）

每天 03:00 (Asia/Taipei) 觸發。對應 launchd job：
  com.andrew.wayback-backfill (legacy, 遷移後 unload)

兩個 task 序列執行：
  cnn_backfill (7h timeout) → wsj_backfill (6h timeout)

trigger_rule="all_done"：CNN 失敗不阻斷 WSJ。
"""

import logging
import sys
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# 兼容本地 / Docker 兩種路徑
_DAG_DIR = os.path.dirname(__file__)
for _levels in [os.path.join("..", ".."), ".."]:
    _candidate = os.path.abspath(os.path.join(_DAG_DIR, _levels, "dependent_code"))
    if os.path.isdir(_candidate):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

logger = logging.getLogger("airflow.task")


def _run_wayback(source: str, min_year: int, max_year: int, max_articles: int) -> None:
    from scrapers.wayback_backfill import WaybackBackfillScraper
    logger.info(
        "[Wayback] %s backfill %d-%d, max=%d",
        source, min_year, max_year, max_articles,
    )
    WaybackBackfillScraper(
        source=source,
        start_year=min_year,
        end_year=max_year,
        max_articles=max_articles,
    ).run()
    logger.info("[Wayback] %s 完成", source)


def task_cnn_recent(**kwargs) -> None:
    _run_wayback("cnn", 2022, 2025, 3000)


def task_wsj_recent(**kwargs) -> None:
    _run_wayback("wsj", 2022, 2025, 3000)


default_args = {
    "owner": "andrew",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="wayback_backfill_daily",
    default_args=default_args,
    description="Wayback 2022-2025 CNN + WSJ daily backfill",
    schedule_interval="0 3 * * *",
    start_date=datetime(2026, 5, 7),
    catchup=False,
    tags=["wayback", "backfill"],
) as dag:

    cnn = PythonOperator(
        task_id="cnn_backfill_recent",
        python_callable=task_cnn_recent,
        execution_timeout=timedelta(hours=7),
    )

    wsj = PythonOperator(
        task_id="wsj_backfill_recent",
        python_callable=task_wsj_recent,
        execution_timeout=timedelta(hours=6),
        trigger_rule="all_done",
    )

    cnn >> wsj
