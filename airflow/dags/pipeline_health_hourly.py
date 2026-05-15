"""
pipeline_health_hourly — PTT pipeline 健康監測

每小時 :05 觸發（避開 :25 主 ETL）。對應 launchd job：
  com.andrew.ptt-pipeline-health-monitor (legacy, 遷移後 unload)

直接呼叫 project/scripts/ptt_pipeline_health_monitor.py 的 main()，
透過 env var 注入 LINE_BOT_DIR / PTT_HEALTH_STATE_FILE 適配容器路徑。
"""

import logging
import sys
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

_DAG_DIR = os.path.dirname(__file__)

# 5/10 ops/ 重整：monitor 從 project/scripts/ 搬到 ops/monitors/ptt_pipeline.py
# 容器內 mount：/opt/airflow/ops/monitors（需在 docker-compose 加 mount）
# 本地 fallback：相對 DAG 檔案三層往上的 Data_engineer/ops/monitors
_CANDIDATE_MONITORS = [
    "/opt/airflow/ops/monitors",
    os.path.abspath(os.path.join(_DAG_DIR, "..", "..", "..", "ops", "monitors")),
]
for _path in _CANDIDATE_MONITORS:
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
        break

_CANDIDATE_DEPS = ["/opt/airflow/dependent_code", os.path.abspath(os.path.join(_DAG_DIR, "..", "..", "dependent_code"))]
for _path in _CANDIDATE_DEPS:
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
        break

logger = logging.getLogger("airflow.task")


def task_run_health_check(**kwargs) -> None:
    """執行 ptt_pipeline_health_monitor.main()。

    main() 回傳 0 表全綠、1 表有 issue。issue 已寫進 Discord（透過
    notify_discord）並印到 stdout，因此這裡不 raise——讓 Airflow task 永遠成功，
    failure semantic 透過 Discord alert 表達（與 launchd 行為一致）。
    """
    from ptt_pipeline import main as run_health  # ops/monitors/ptt_pipeline.py (renamed 5/10)
    code = run_health()
    logger.info("[Health] 結束，回傳 code=%s", code)


default_args = {
    "owner": "andrew",
    "depends_on_past": False,
    "retries": 0,  # health check 不 retry，避免重複 Discord alert
}

with DAG(
    dag_id="pipeline_health_hourly",
    default_args=default_args,
    description="PTT pipeline 每小時健康檢查（log freshness + launchd + DB）",
    schedule_interval="5 * * * *",
    start_date=datetime(2026, 5, 7),
    catchup=False,
    tags=["health", "monitoring"],
) as dag:

    PythonOperator(
        task_id="run_health_check",
        python_callable=task_run_health_check,
        execution_timeout=timedelta(minutes=5),
    )
