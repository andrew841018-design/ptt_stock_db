"""
stock_sentiment_etl — PTT 股票情緒分析 ETL DAG

此 DAG 將 pipeline.py 的 8 步驟 ETL 流程拆成獨立的 Airflow task，
每小時執行一次（與原本的 launchd 排程一致）。

流程：
  t1 (create_schema)                        → Step 0：確保 PostgreSQL / MongoDB 表與索引存在
  t2a~t2h（8 個並行 extract tasks）          → Step 1：各來源獨立爬取（失敗互不影響）
  t3 (transform)                             → Step 2：QA 資料品質檢查 + 自動修復 + GE 驗證
  t4 (pii_masking)                           → Step 3：PII 遮蔽
  t5 (bert_inference)                        → Step 4：BERT 情緒推論
  t6 (dw_etl)                                → Step 5：OLTP → DW 增量 ETL + Data Mart 刷新
  t7 (backup)                                → Step 6：S3 備份
  t8 (ai_prediction)                         → Step 7：AI 模型預測

容錯策略：
  - t3 設定 trigger_rule='all_done'：所有爬蟲跑完（不管成敗）才做 transform，
    確保部分爬蟲失敗不阻斷後續步驟。
  - t4、t5、t6、t7、t8 同樣 trigger_rule='all_done'：fail-soft 步驟。
"""

import sys
import os
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ── 將 dependent_code 加入 Python path ───────────────────────────────────
# 本地 repo：dags/ 往上 2 層到 project/，再進 dependent_code/
# Docker：dags/ 往上 1 層到 /opt/airflow/，再進 dependent_code/
_DAG_DIR = os.path.dirname(__file__)
for _levels in [os.path.join("..", ".."), ".."]:
    _candidate = os.path.abspath(os.path.join(_DAG_DIR, _levels, "dependent_code"))
    if os.path.isdir(_candidate):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

# ── imports ───────────────────────────────────────────────────────────────
# 重模組（torch/transformers/mlflow/pandas）改 lazy import：
# 移到各 task function 內部，避免 DAG parse 時觸發
# Airflow dagbag_import_timeout（預設 30s，重模組首次 import 會超過）。

logger = logging.getLogger("airflow.task")


# ── 失敗回呼 ──────────────────────────────────────────────────────────────
def _on_task_failure(context: dict) -> None:
    ti = context.get("task_instance")
    exception = context.get("exception")
    logger.error(
        "[DAG] task '%s' 失敗 — %s",
        ti.task_id if ti else "unknown",
        exception,
    )


# ── Step 0 ────────────────────────────────────────────────────────────────
def task_create_schema(**kwargs) -> None:
    from schema import create_schema
    from mongo_helper import ensure_indexes

    logger.info("[DAG] 開始建立 Schema / Index")
    create_schema()
    ensure_indexes()
    logger.info("[DAG] Schema / Index 建立完成")


# ── Step 1：各來源獨立 task ───────────────────────────────────────────────
def task_extract_ptt(**kwargs) -> None:
    from scrapers.ptt_scraper import PttScraper

    logger.info("[DAG] Extract — PTT")
    PttScraper().run()


def task_extract_cnyes(**kwargs) -> None:
    from scrapers.cnyes_scraper import CnyesScraper

    logger.info("[DAG] Extract — 鉅亨網")
    CnyesScraper().run()


def task_extract_reddit(**kwargs) -> None:
    from scrapers.reddit_scraper import RedditScraper

    logger.info("[DAG] Extract — Reddit")
    RedditScraper().run()


def task_extract_cnn(**kwargs) -> None:
    from scrapers.cnn_scraper import CnnScraper

    logger.info("[DAG] Extract — CNN")
    CnnScraper().run()


def task_extract_wsj(**kwargs) -> None:
    from scrapers.wsj_scraper import WsjScraper

    logger.info("[DAG] Extract — WSJ")
    WsjScraper().run()


def task_extract_marketwatch(**kwargs) -> None:
    from scrapers.marketwatch_scraper import MarketWatchScraper

    logger.info("[DAG] Extract — MarketWatch")
    MarketWatchScraper().run()


def task_extract_tw_stock(**kwargs) -> None:
    from scrapers.tw_stock_fetcher import TwseFetcher

    logger.info("[DAG] Extract — TW 股價（0050）")
    TwseFetcher().run()


def task_extract_us_stock(**kwargs) -> None:
    from scrapers.us_stock_fetcher import UsStockFetcher

    logger.info("[DAG] Extract — US 股價（VOO）")
    UsStockFetcher().run()


# ── Step 2~8 ──────────────────────────────────────────────────────────────
def task_transform(**kwargs) -> None:
    from pipeline import transform

    logger.info("[DAG] 開始 Transform（QA + Repair + GE）")
    transform()
    logger.info("[DAG] Transform 完成")


def task_pii_masking(**kwargs) -> None:
    from pii_masking import run as run_pii

    logger.info("[DAG] 開始 PII 遮蔽")
    run_pii()
    logger.info("[DAG] PII 遮蔽完成")


def task_bert_inference(**kwargs) -> None:
    from bert_sentiment import run_batch_inference

    logger.info("[DAG] 開始 BERT 情緒推論")
    run_batch_inference()
    logger.info("[DAG] BERT 情緒推論完成")


def task_dw_etl(**kwargs) -> None:
    from dw_etl import run_etl

    logger.info("[DAG] 開始 DW ETL")
    run_etl()
    logger.info("[DAG] DW ETL 完成")


def task_backup(**kwargs) -> None:
    from backup import backup_database

    logger.info("[DAG] 開始 S3 備份")
    backup_database()
    logger.info("[DAG] S3 備份完成")


def task_ai_prediction(**kwargs) -> None:
    from ai_model_prediction import run_ai_model_prediction

    logger.info("[DAG] 開始 AI 模型預測")
    run_ai_model_prediction("tw")
    run_ai_model_prediction("us")
    logger.info("[DAG] AI 模型預測完成")


# ── DAG 定義 ──────────────────────────────────────────────────────────────
default_args = {
    "owner": "andrew",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": _on_task_failure,
}

with DAG(
    dag_id="stock_sentiment_etl",
    default_args=default_args,
    description="PTT 股票情緒分析系統 — 每小時 ETL pipeline",
    schedule_interval="25 * * * *",
    start_date=datetime(2026, 4, 15),
    catchup=False,
    max_active_runs=1,  # dw_etl 寫入 fact_sentiment + mart_*，多 run 並跑會 lock 互卡
    tags=["etl", "sentiment", "stock"],
) as dag:

    t1 = PythonOperator(
        task_id="create_schema",
        python_callable=task_create_schema,
        doc_md="確保 PostgreSQL OLTP 表和 MongoDB 索引存在（IF NOT EXISTS，冪等）",
    )

    # ── 8 個並行爬蟲 task ──
    t2a = PythonOperator(task_id="extract_ptt",         python_callable=task_extract_ptt)
    t2b = PythonOperator(task_id="extract_cnyes",       python_callable=task_extract_cnyes)
    t2c = PythonOperator(task_id="extract_reddit",      python_callable=task_extract_reddit)
    t2d = PythonOperator(task_id="extract_cnn",         python_callable=task_extract_cnn)
    t2e = PythonOperator(task_id="extract_wsj",         python_callable=task_extract_wsj)
    t2f = PythonOperator(task_id="extract_marketwatch", python_callable=task_extract_marketwatch)
    t2g = PythonOperator(task_id="extract_tw_stock",    python_callable=task_extract_tw_stock)
    t2h = PythonOperator(task_id="extract_us_stock",    python_callable=task_extract_us_stock)

    extract_tasks = [t2a, t2b, t2c, t2d, t2e, t2f, t2g, t2h]

    t3 = PythonOperator(
        task_id="transform",
        python_callable=task_transform,
        trigger_rule="all_done",
        doc_md="QA 資料品質檢查 → 自動修復（reparse from MongoDB）→ GE 驗證",
    )

    # fail-soft：t4-t8 都設 trigger_rule="all_done"（與檔案頂部 docstring 一致），
    # 上游失敗 / partial 仍跑，避免下游 SKIP 雪崩；dw_etl 維持 all_done 以便增量補齊
    t4 = PythonOperator(
        task_id="pii_masking",
        python_callable=task_pii_masking,
        trigger_rule="all_done",
        doc_md="PII 遮蔽：author hash 化（fail-soft）。",
    )

    t5 = PythonOperator(
        task_id="bert_inference",
        python_callable=task_bert_inference,
        trigger_rule="all_done",
        doc_md="BERT 情緒推論：只處理尚未打分的文章（fail-soft）。",
    )

    t6 = PythonOperator(
        task_id="dw_etl",
        python_callable=task_dw_etl,
        trigger_rule="all_done",
        doc_md="OLTP → DW 增量 ETL：填充維度表 + 事實表 + 刷新 Data Mart（all_done，bert 部分失敗仍可增量補齊）",
    )

    t7 = PythonOperator(
        task_id="backup",
        python_callable=task_backup,
        trigger_rule="all_done",
        doc_md="S3 備份：pg_dump → gzip → 上傳至 S3 bucket（fail-soft）",
    )

    t8 = PythonOperator(
        task_id="ai_prediction",
        python_callable=task_ai_prediction,
        trigger_rule="all_done",
        doc_md="AI 模型預測：情緒 vs 隔日漲跌（TW 0050 + US VOO，Walk-Forward Validation；fail-soft）",
    )

    # ── 依賴關係 ──
    # t1 → [8 個並行爬蟲] → t3 → t4 → t5 → t6 → t7 → t8
    t1 >> extract_tasks >> t3 >> t4 >> t5 >> t6 >> t7 >> t8
