"""
wayback_historical_daily — Wayback Machine 較舊年份回填（CNN 2015-2021）

每天 13:00 (Asia/Taipei) 觸發。對應 launchd job：
  com.andrew.wayback-historical (legacy, 遷移後 unload)

只跑 CNN：Wayback 對 WSJ 付費牆 2022 前幾乎無快照。
"""

import logging
import sys
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

_DAG_DIR = os.path.dirname(__file__)
for _levels in [os.path.join("..", ".."), ".."]:
    _candidate = os.path.abspath(os.path.join(_DAG_DIR, _levels, "dependent_code"))
    if os.path.isdir(_candidate):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

logger = logging.getLogger("airflow.task")


def task_cnn_historical(**kwargs) -> None:
    from scrapers.wayback_backfill import WaybackBackfillScraper
    logger.info("[Wayback] CNN backfill 2015-2021, max=3000")
    WaybackBackfillScraper(
        source="cnn",
        start_year=2015,
        end_year=2021,
        max_articles=3000,
    ).run()
    logger.info("[Wayback] CNN 歷史回填完成")


default_args = {
    "owner": "andrew",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="wayback_historical_daily",
    default_args=default_args,
    description="Wayback 2015-2021 CNN historical backfill",
    schedule_interval="0 13 * * *",
    start_date=datetime(2026, 5, 7),
    catchup=False,
    tags=["wayback", "backfill", "historical"],
) as dag:

    PythonOperator(
        task_id="cnn_backfill_historical",
        python_callable=task_cnn_historical,
        execution_timeout=timedelta(hours=6),
    )
