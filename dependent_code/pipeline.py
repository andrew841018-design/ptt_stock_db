import sys
import logging
import concurrent.futures

from schema import create_schema
from scrapers.ptt_scraper import PttScraper
from scrapers.cnyes_scraper import CnyesScraper
from scrapers.reddit_scraper import RedditScraper
from scrapers.tw_stock_fetcher import TwseFetcher
from scrapers.us_stock_fetcher import UsStockFetcher
from QA import QA_checks
from ge_validation import ge_validate
from reparse import repair
from pii_masking import run as run_pii
from bert_sentiment import run_batch_inference
from fetch_etf_holdings import run as run_fetch_etf
from stock_matcher import run_matcher
from dw_etl import run_etl
from looker_export import main as run_looker_export
from backup import backup_database
from backtest import run_backtest
from mongo_helper import ensure_indexes

# stream=sys.stdout：logging 寫 stdout，tqdm 保持 stderr，redirect 時乾淨分離
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# 新增來源只需在此加入對應 class
_ARTICLE_SOURCES = [PttScraper, CnyesScraper, RedditScraper]
_STOCK_SOURCES   = [TwseFetcher, UsStockFetcher]  # 股價類，不繼承 BaseScraper，單獨呼叫


def _run_source(scraper_cls) -> str:
    """執行單一來源，供 ThreadPoolExecutor 呼叫"""
    name = scraper_cls.__name__ # class name. ex:"ptt_scraper"
    logging.info(f"[Extract] 開始：{name}")
    scraper_cls().run()
    return name


def extract() -> None:
    """Extract：並行爬取所有來源（I/O bound，用 thread）
    Pydantic 驗證在各爬蟲 fetch_articles() 內完成（Transform 第一層）
    Load（_save_to_db）在各爬蟲 run() 內批次寫入 PostgreSQL
    """
    all_sources = _ARTICLE_SOURCES + _STOCK_SOURCES
    logging.info(f"[Extract] 並行啟動 {len(all_sources)} 個來源")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # dict comprehension：對每個 cls 呼叫 submit()
        # submit() 把任務丟進 thread pool 立刻回傳 Future object（不等結果）
        # futures[key]=value.
        # → key   = Future 物件（代表該 thread 任務）
        # → value = cls.__name__（來源名稱，供之後 log 用）
        # 5 個 submit() 幾乎同時發出，5 個 thread 一起跑
        futures = {executor.submit(_run_source, cls): cls.__name__ for cls in all_sources}
        # as_completed：阻塞等待，誰先跑完誰先 yield 出 key，不照原始順序
        for key in concurrent.futures.as_completed(futures):
            name = futures[key]
            try:
                key.result() #key=任務，所以要看結果是用key.result()
                logging.info(f"[Extract] 完成：{name}")
            except Exception as e:
                logging.error(f"[Extract] 失敗：{name} — {e}")


def transform() -> None:
    """
    Transform：QA 資料品質檢查 + 自動修復 + GE 驗證

    流程：
      1. 跑 QA_checks()
      2. 若 QA 失敗 → 呼叫 repair()（從 MongoDB raw_responses re-parse 修復 PostgreSQL）
      3. 修復後重跑 QA（若仍失敗，raise 中止 pipeline）
      4. GE 驗證（失敗只 warning，不中止）
    """
    logging.info("[Transform] QA 檢查")
    try:
        QA_checks()
    except ValueError as qa_err:
        logging.warning(f"[Transform] QA 失敗：{qa_err}")
        logging.info("[Transform] 啟動自動修復（reparse from MongoDB raw_responses）")

        try:
            result = repair()
        except Exception as repair_err:
            logging.error(f"[Transform] 修復過程出錯：{repair_err}")
            raise qa_err  # 修復本身出錯 → 拋出原始 QA 錯誤

        if result["repaired"] > 0:
            logging.info(f"[Transform] 修復 {result['repaired']} 筆，重跑 QA")
            QA_checks()  # 修復後重跑，若仍失敗則 raise 中止 pipeline
        else:
            logging.warning("[Transform] 無法修復任何資料（無 raw 或 re-parse 全失敗）")
            raise qa_err  # 無法修 → 拋出原始 QA 錯誤

    logging.info("[Transform] GE 驗證")
    try:
        ge_validate()
    except Exception as e:
        logging.warning(f"[Transform] GE 驗證失敗：{e}")


def run_pipeline() -> None:
    # Step 0：確保 OLTP 表（PostgreSQL）與 MongoDB index 存在（IF NOT EXISTS，幂等）
    create_schema()
    ensure_indexes()

    # Step 1：爬蟲寫入 OLTP
    extract()

    # Step 2：QA + 自動修復 + GE 驗證
    transform()

    # Step 3：PII 遮蔽（repair 完再遮蔽，避免 repair 拿到已遮蔽的資料）
    try:
        run_pii()
    except Exception as e:
        logging.warning(f"[PII] 失敗（不中止 pipeline）：{e}")

    # Step 4：BERT 情緒推論（只跑尚未打分的文章）
    try:
        run_batch_inference()
    except Exception as e:
        logging.warning(f"[BERT] 失敗（不中止 pipeline）：{e}")

    # Step 5：更新 stock_dict + 標記文章中的股票提及
    try:
        run_fetch_etf()
        run_matcher()
    except Exception as e:
        logging.warning(f"[Match] 失敗（不中止 pipeline）：{e}")

    # Step 6：DW ETL（建表 → 填維度 → 填事實 → 刷新 Data Mart）
    run_etl()

    # Step 7：匯出 CSV 給 Looker Studio
    try:
        run_looker_export()
    except Exception as e:
        logging.warning(f"[Looker] 失敗（不中止 pipeline）：{e}")

    # Step 8：S3 備份（最後一步，備份完整狀態）
    try:
        backup_database()
    except Exception as e:
        logging.warning(f"[Backup] 失敗（不中止 pipeline）：{e}")

    # Step 9：回測（情緒 vs 隔日漲跌，Walk-Forward Validation）
    try:
        run_backtest("tw")
        run_backtest("us")
    except Exception as e:
        logging.warning(f"[Backtest] 失敗（不中止 pipeline）：{e}")

    logging.info("[Pipeline] 全部完成")


if __name__ == "__main__":
    run_pipeline()
