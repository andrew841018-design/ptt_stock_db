import sys
import json
import logging
import re
import subprocess
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from schema import create_schema
# ── Prometheus metrics（真實接線，非擺設）──────────────────────────────────
# etl_step_duration_seconds：量每個 step 耗時（label: step name）
# etl_runs_total：整體 pipeline success / failure 次數
# articles_scraped_total：每來源累計爬取 article 數（讓 Grafana 看到 rate）
from metrics import (
    etl_step_duration_seconds,
    etl_runs_total,
    articles_scraped_total,
)
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
from bert_sentiment import run_batch_inference, train as bert_train, evaluate as bert_evaluate, should_finetune
from dw_etl import run_etl
from backup import backup_database
from ai_model_prediction import run_ai_model_prediction
from mongo_helper import ensure_indexes

# stream=sys.stdout：logging 寫 stdout，tqdm 保持 stderr，redirect 時乾淨分離
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

_REQUIREMENTS_PATH = Path(__file__).resolve().parent / "requirements.txt"
_DEPS_STAMP_PATH   = Path(__file__).resolve().parent.parent / "logs" / ".deps_last_checked"
_DEPS_CHECK_INTERVAL = timedelta(days=7)


def update_dependencies() -> None:
    """每週檢查一次非 pin 套件，有新版則自動升級。
    pin 版本（含 ==）一律跳過，避免破壞已知相容性。
    """
    if _DEPS_STAMP_PATH.exists():
        last = datetime.fromisoformat(_DEPS_STAMP_PATH.read_text().strip())
        if datetime.now() - last < _DEPS_CHECK_INTERVAL:
            logging.info("[Deps] 本週已檢查過，跳過")
            return

    logging.info("[Deps] 開始檢查套件版本")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logging.warning(f"[Deps] pip list --outdated 失敗：{result.stderr.strip()}")
        return

    outdated = {pkg["name"].lower(): pkg["latest_version"] for pkg in json.loads(result.stdout)}

    # 找出 requirements.txt 中無任何版本約束且有新版的套件
    # ==, <, >, !=, ~=, >= 都跳過，避免破壞已知相容性（例如 numpy<2 保護 torch）
    upgradable = []
    for line in _REQUIREMENTS_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(op in stripped for op in ("==", "<", ">", "!=", "~=")):
            continue
        pkg_name = re.split(r"[>=<\[\s]", stripped)[0].lower()
        if pkg_name in outdated:
            upgradable.append((pkg_name, outdated[pkg_name]))

    if not upgradable:
        logging.info("[Deps] 無可升級套件")
        _DEPS_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEPS_STAMP_PATH.write_text(datetime.now().isoformat())
        return

    updated, failed = [], []
    for pkg_name, latest in upgradable:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", pkg_name],
            capture_output=True, text=True,
        )
        if res.returncode == 0:
            updated.append(f"{pkg_name}=={latest}")
        else:
            failed.append(pkg_name)
            logging.warning(f"[Deps] 升級 {pkg_name} 失敗：{res.stderr.strip()}")

    if updated:
        logging.info(f"[Deps] 已升級：{', '.join(updated)}")
    if failed:
        logging.warning(f"[Deps] 升級失敗：{', '.join(failed)}")

    _DEPS_STAMP_PATH.parent.mkdir(exist_ok=True)
    _DEPS_STAMP_PATH.write_text(datetime.now().isoformat())

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _ensure_auth_configured() -> None:
    """若 auth 金鑰未設定，互動式引導生成並寫入 .env（對應 auth.py 的三個 env var）。
    非 TTY 環境（launchd / CI）只印 warning，不阻塞 pipeline。
    """
    import os
    import getpass
    import secrets as _secrets

    missing = [k for k in ("JWT_SECRET_KEY", "ADMIN_PW_HASH", "VIEWER_PW_HASH")
               if not os.environ.get(k)]

    if not missing:
        return

    if not sys.stdin.isatty():
        return

    print("\n[Auth] 偵測到以下 env var 未設定，開始互動式金鑰設定：")
    print("  " + ", ".join(missing))
    print("（直接 Enter 略過該項，pipeline 繼續執行）\n")

    from passlib.hash import bcrypt as _bcrypt

    updates: dict[str, str] = {}

    if "JWT_SECRET_KEY" in missing:
        key = _secrets.token_hex(32)
        updates["JWT_SECRET_KEY"] = key
        os.environ["JWT_SECRET_KEY"] = key
        print(f"  ✔ JWT_SECRET_KEY 自動產生完成")

    for username, env_key in [("admin", "ADMIN_PW_HASH"), ("viewer", "VIEWER_PW_HASH")]:
        if env_key not in missing:
            continue
        pw = getpass.getpass(f"  請輸入 {username} 密碼（Enter 略過）：")
        if pw:
            h = _bcrypt.hash(pw)
            updates[env_key] = h
            os.environ[env_key] = h
            print(f"  ✔ {env_key} 產生完成")

    if not updates:
        print()
        return

    # 讀取現有 .env，更新對應 key，整個寫回
    existing: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, v = stripped.partition("=")
                existing[k.strip()] = v.strip()

    existing.update(updates)
    _ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n"
    )
    print(f"\n  ✔ 已寫入 {_ENV_PATH}\n")


# 新增來源只需在此加入對應 class
_ARTICLE_SOURCES = [PttScraper, CnyesScraper, RedditScraper, CnnScraper, WsjScraper, MarketWatchScraper]
_STOCK_SOURCES   = [TwseFetcher, UsStockFetcher]  # 股價類，不繼承 BaseScraper，單獨呼叫


def _run_source(scraper_cls) -> str:
    """執行單一來源，供 ThreadPoolExecutor 呼叫 + Prometheus metric"""
    name = scraper_cls.__name__ # class name. ex:"PttScraper"
    logging.info(f"[Extract] 開始：{name}")
    # scraper 內部 run() 回傳 None 但有 self.inserted_count 屬性記本次 insert 數
    scraper = scraper_cls()
    scraper.run()
    inserted = getattr(scraper, "inserted_count", None)
    # 用 scraper class 推導 source key（小寫去掉 "Scraper" / "Fetcher" 尾巴）
    source_label = name.replace("Scraper", "").replace("Fetcher", "").lower()
    if isinstance(inserted, int) and inserted > 0:
        articles_scraped_total.labels(source=source_label).inc(inserted)
    else:
        # 沒回傳 count 就 +1 表示本輪跑過（rate_over_time 看得到）
        articles_scraped_total.labels(source=source_label).inc(0)
    return name


@contextmanager
def _step(step_name: str):
    """timing context manager：寫入 etl_step_duration_seconds histogram"""
    with etl_step_duration_seconds.labels(step=step_name).time():
        yield


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
    # Auth 金鑰前置檢查：TTY 互動式生成並寫入 .env；非 TTY 只 warning
    _ensure_auth_configured()

    try:
        # Step -1：每週檢查並升級非 pin 套件（失敗不中止 pipeline）
        with _step("deps"):
            try:
                update_dependencies()
            except Exception as e:
                logging.warning(f"[Deps] 失敗（不中止 pipeline）：{e}")

        # Step 0：確保 OLTP 表（PostgreSQL）與 MongoDB index 存在（IF NOT EXISTS，幂等）
        with _step("schema"):
            create_schema()
            ensure_indexes()

        # Step 1：爬蟲寫入 OLTP
        with _step("extract"):
            extract()

        # Step 2：QA + 自動修復 + GE 驗證
        with _step("transform"):
            transform()

        # Step 3：PII 遮蔽（repair 完再遮蔽，避免 repair 拿到已遮蔽的資料）
        with _step("pii"):
            try:
                run_pii()
            except Exception as e:
                logging.warning(f"[PII] 失敗（不中止 pipeline）：{e}")

        # Step 4：BERT 情緒推論（article_labels 夠 + 無 fine-tuned model 時自動先訓練一次）
        with _step("bert"):
            try:
                if should_finetune():
                    logging.info("[BERT] 偵測到 article_labels 足夠且尚無 fine-tuned model，自動執行 fine-tuning")
                    bert_train()
                    bert_evaluate()
                run_batch_inference()
            except Exception as e:
                logging.warning(f"[BERT] 失敗（不中止 pipeline）：{e}")

        # Step 5：DW ETL（建表 → 填維度 → 填事實 → 刷新 Data Mart）
        with _step("dw_etl"):
            run_etl()

        # Step 6：S3 備份（最後一步，備份完整狀態）
        with _step("backup"):
            try:
                backup_database()
            except Exception as e:
                logging.warning(f"[Backup] 失敗（不中止 pipeline）：{e}")

        # Step 7：AI 模型預測（情緒 vs 隔日漲跌，Walk-Forward Validation）
        with _step("ai_predict"):
            try:
                run_ai_model_prediction("tw")
                run_ai_model_prediction("us")
            except Exception as e:
                logging.warning(f"[AI Prediction] 失敗（不中止 pipeline）：{e}")

        etl_runs_total.labels(status="success").inc()
        logging.info("[Pipeline] 全部完成")
    except Exception:
        etl_runs_total.labels(status="failure").inc()
        raise


if __name__ == "__main__":
    run_pipeline()
