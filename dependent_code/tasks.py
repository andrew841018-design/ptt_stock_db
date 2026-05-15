
import time
import logging

from celery_app import app

from schema import create_schema
from mongo_helper import ensure_indexes
from scrapers.ptt_scraper import PttScraper
from scrapers.cnyes_scraper import CnyesScraper
from scrapers.reddit_scraper import RedditScraper
from scrapers.cnn_scraper import CnnScraper
from scrapers.wsj_scraper import WsjScraper
from scrapers.marketwatch_scraper import MarketWatchScraper
from scrapers.tw_stock_fetcher import TwseFetcher
from scrapers.us_stock_fetcher import UsStockFetcher
from QA import QA_checks
from ge_validation import ge_validate
from reparse import repair
from pii_masking import run as run_pii
from bert_sentiment import run_batch_inference
from dw_etl import run_etl
from backup import backup_database
from ai_model_prediction import run_ai_model_prediction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)



def _timed(task_name, func, *args, **kwargs):
    logging.info(f"[Celery] {task_name} 開始")
    start = time.time()
    result = func(*args, **kwargs)
    elapsed = time.time() - start
    logging.info(f"[Celery] {task_name} 完成（耗時 {elapsed:.1f} 秒）")
    return result



@app.task(bind=True, max_retries=3, name="init_schema")
def init_schema(self):
    try:
        _timed("create_schema", create_schema)
        _timed("ensure_indexes", ensure_indexes)
    except Exception as exc:
        logging.error(f"[Celery] init_schema 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="scrape_ptt")
def scrape_ptt(self):
    try:
        _timed("PttScraper", lambda: PttScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_ptt 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="scrape_cnyes")
def scrape_cnyes(self):
    try:
        _timed("CnyesScraper", lambda: CnyesScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_cnyes 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="scrape_reddit")
def scrape_reddit(self):
    try:
        _timed("RedditScraper", lambda: RedditScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_reddit 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="scrape_cnn")
def scrape_cnn(self):
    try:
        _timed("CnnScraper", lambda: CnnScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_cnn 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="scrape_wsj")
def scrape_wsj(self):
    try:
        _timed("WsjScraper", lambda: WsjScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_wsj 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="scrape_marketwatch")
def scrape_marketwatch(self):
    try:
        _timed("MarketWatchScraper", lambda: MarketWatchScraper().run())
    except Exception as exc:
        logging.error(f"[Celery] scrape_marketwatch 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="fetch_tw_stock")
def fetch_tw_stock(self):
    try:
        _timed("TwseFetcher", lambda: TwseFetcher().run())
    except Exception as exc:
        logging.error(f"[Celery] fetch_tw_stock 失敗：{exc}")
        self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=3, name="fetch_us_stock")
def fetch_us_stock(self):
    try:
        _timed("UsStockFetcher", lambda: UsStockFetcher().run())
    except Exception as exc:
        logging.error(f"[Celery] fetch_us_stock 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_transform")
def run_transform(self):
    try:
        logging.info("[Celery] QA 檢查開始")
        start = time.time()
        try:
            QA_checks()
        except ValueError as qa_err:
            logging.warning(f"[Celery] QA 失敗：{qa_err}，啟動自動修復")
            result = repair()
            if result["repaired"] > 0:
                logging.info(f"[Celery] 修復 {result['repaired']} 筆，重跑 QA")
                QA_checks()
            else:
                raise qa_err
        elapsed = time.time() - start
        logging.info(f"[Celery] QA 檢查完成（耗時 {elapsed:.1f} 秒）")

        try:
            _timed("GE 驗證", ge_validate)
        except Exception as e:
            logging.warning(f"[Celery] GE 驗證失敗（不中止）：{e}")

    except Exception as exc:
        logging.error(f"[Celery] run_transform 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_pii_masking")
def run_pii_masking(self):
    try:
        _timed("PII 遮蔽", run_pii)
    except Exception as exc:
        logging.error(f"[Celery] run_pii_masking 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_bert")
def run_bert(self):
    try:
        _timed("BERT 推論", run_batch_inference)
    except Exception as exc:
        logging.error(f"[Celery] run_bert 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_dw_etl")
def run_dw_etl(self):
    try:
        _timed("DW ETL", run_etl)
    except Exception as exc:
        logging.error(f"[Celery] run_dw_etl 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_backup")
def run_backup(self):
    try:
        _timed("S3 備份", backup_database)
    except Exception as exc:
        logging.error(f"[Celery] run_backup 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_ai_prediction")
def run_ai_prediction(self):
    try:
        _timed("AI 預測 (TW)", run_ai_model_prediction, "tw")
        _timed("AI 預測 (US)", run_ai_model_prediction, "us")
    except Exception as exc:
        logging.error(f"[Celery] run_ai_prediction 失敗：{exc}")
        self.retry(exc=exc, countdown=60)



@app.task(bind=True, max_retries=3, name="run_full_pipeline")
def run_full_pipeline(self):
    try:
        from pipeline import run_pipeline
        run_pipeline()
    except Exception as exc:
        logging.error(f"[Celery] run_full_pipeline 失敗：{exc}")
        self.retry(exc=exc, countdown=60)
