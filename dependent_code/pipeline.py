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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

_REQUIREMENTS_PATH = Path(__file__).resolve().parent / "requirements.txt"
_DEPS_STAMP_PATH   = Path(__file__).resolve().parent.parent / "logs" / ".deps_last_checked"
_DEPS_CHECK_INTERVAL = timedelta(days=7)


def update_dependencies() -> None:
    if _DEPS_STAMP_PATH.exists():
        last = datetime.fromisoformat(_DEPS_STAMP_PATH.read_text().strip())
        if datetime.utcnow() - last < _DEPS_CHECK_INTERVAL:
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
        _DEPS_STAMP_PATH.write_text(datetime.utcnow().isoformat())
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

    _DEPS_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DEPS_STAMP_PATH.write_text(datetime.utcnow().isoformat())

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _ensure_auth_configured() -> None:
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
        print("  ✔ JWT_SECRET_KEY 自動產生完成")

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


_ARTICLE_SOURCES = [PttScraper, CnyesScraper, RedditScraper, CnnScraper, WsjScraper, MarketWatchScraper]
_STOCK_SOURCES   = [TwseFetcher, UsStockFetcher]


def _run_source(scraper_cls) -> str:
    name = scraper_cls.__name__
    logging.info(f"[Extract] 開始：{name}")
    scraper = scraper_cls()
    scraper.run()
    inserted = getattr(scraper, "inserted_count", None)
    source_label = name.replace("Scraper", "").replace("Fetcher", "").lower()
    if isinstance(inserted, int) and inserted > 0:
        articles_scraped_total.labels(source=source_label).inc(inserted)
    else:
        articles_scraped_total.labels(source=source_label).inc(0)
    return name


@contextmanager
def _step(step_name: str):
    with etl_step_duration_seconds.labels(step=step_name).time():
        yield


def extract() -> None:
    all_sources = _ARTICLE_SOURCES + _STOCK_SOURCES
    logging.info(f"[Extract] 並行啟動 {len(all_sources)} 個來源")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(_run_source, cls): cls.__name__ for cls in all_sources}
        for key in concurrent.futures.as_completed(futures):
            name = futures[key]
            try:
                key.result()
                logging.info(f"[Extract] 完成：{name}")
            except Exception as e:
                logging.error(f"[Extract] 失敗：{name} — {e}")


def transform() -> None:
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
            raise qa_err

        if result["repaired"] > 0:
            logging.info(f"[Transform] 修復 {result['repaired']} 筆，重跑 QA")
            QA_checks()
        else:
            logging.warning("[Transform] 無法修復任何資料（無 raw 或 re-parse 全失敗）")
            raise qa_err

    logging.info("[Transform] GE 驗證")
    try:
        ge_validate()
    except Exception as e:
        logging.warning(f"[Transform] GE 驗證失敗：{e}")


def run_pipeline() -> None:
    _ensure_auth_configured()

    try:
        with _step("deps"):
            try:
                update_dependencies()
            except Exception as e:
                logging.warning(f"[Deps] 失敗（不中止 pipeline）：{e}")

        with _step("schema"):
            create_schema()
            try:
                ensure_indexes()
            except Exception as e:
                logging.warning(f"[Mongo] ensure_indexes 失敗（不中止 pipeline）：{e}")

        with _step("extract"):
            extract()

        with _step("transform"):
            transform()

        with _step("pii"):
            try:
                run_pii()
            except Exception as e:
                logging.warning(f"[PII] 失敗（不中止 pipeline）：{e}")

        with _step("bert"):
            try:
                if should_finetune():
                    logging.info("[BERT] 偵測到 article_labels 足夠且尚無 fine-tuned model，自動執行 fine-tuning")
                    bert_train()
                    bert_evaluate()
                run_batch_inference()
            except Exception as e:
                logging.warning(f"[BERT] 失敗（不中止 pipeline）：{e}")

        with _step("dw_etl"):
            run_etl()

        with _step("backup"):
            try:
                backup_database()
            except Exception as e:
                logging.warning(f"[Backup] 失敗（不中止 pipeline）：{e}")

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
