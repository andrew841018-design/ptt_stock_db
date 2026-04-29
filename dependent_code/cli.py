"""
統一 CLI 入口 — 所有操作的單一呼叫點。

📘 **完整指令速查表請看 `/COMMANDS.md`**（含用途、流程、面試 Demo 路徑）

快速發現：
  python cli.py --help              # 列出所有 subcommand
  python cli.py <sub> --help        # 看某 subcommand 的參數

常用捷徑：
  python cli.py pipeline            # 跑完整 9 步 ETL
  python cli.py services up         # docker-compose up -d
  python cli.py dev api             # uvicorn --reload
  python cli.py test                # pytest
  python cli.py k8s-apply-secrets   # 從 .env 同步 K8s Secret
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from config import STOCK_PRICES_TABLE, US_STOCK_PRICES_TABLE

_DEPENDENT_CODE = Path(__file__).resolve().parent
_PROJECT_ROOT   = _DEPENDENT_CODE.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ─── Pipeline Steps ────────────────────────────────────────────────────────────

def _cmd_pipeline(args):
    from pipeline import run_pipeline
    if args.background:
        import subprocess, sys
        log_path = _PROJECT_ROOT / "logs" / "pipeline_manual.log"
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "a") as log:
            proc = subprocess.Popen(
                [sys.executable, __file__, "pipeline"],
                stdout=log, stderr=log,
                start_new_session=True,
            )
        print(f"Pipeline 已在背景啟動，PID: {proc.pid}，log: {log_path}")
    else:
        run_pipeline()


def _cmd_schema(_args):
    from schema import create_schema
    create_schema()


def _cmd_extract(_args):
    from pipeline import extract
    extract()


def _cmd_transform(_args):
    from pipeline import transform
    transform()


def _cmd_pii(_args):
    from pii_masking import run as run_pii
    run_pii()


def _cmd_bert(args):
    if args.action == "train":
        from bert_sentiment import train
        train()
    elif args.action == "evaluate":
        from bert_sentiment import evaluate
        evaluate()
    elif args.action == "infer":
        from bert_sentiment import run_batch_inference
        run_batch_inference()
    elif args.action == "full-pipeline":
        _run_bert_full_pipeline(args)


def _run_bert_full_pipeline(args):
    """完整流程：LLM 標注 → BERT fine-tune → evaluate → 全量 inference"""
    from pg_helper import get_pg
    from config import ARTICLE_LABELS_TABLE
    from bert_sentiment import train, evaluate, run_batch_inference, MIN_SAMPLES

    # 目標標注總數：現有不足時自動補跑 LLM labeling 湊到此數
    target = getattr(args, "target_labels", 500)

    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {ARTICLE_LABELS_TABLE}")
            label_count = cur.fetchone()[0]

    logging.info("[BERT Pipeline] 目前 article_labels：%d 筆", label_count)

    # 1. LLM 標注（若不足 target）
    if label_count < target:
        needed = target - label_count
        batch_size = 50
        max_batches = (needed + batch_size - 1) // batch_size
        logging.info("[BERT Pipeline] 需補標注 %d 筆，啟動 LLM labeling（%d 批）", needed, max_batches)
        from llm_labeling import run_llm_labeling
        result = run_llm_labeling(batch_size=batch_size, max_batches=max_batches)
        label_count += result["total_saved"]
        logging.info("[BERT Pipeline] 標注後合計：%d 筆", label_count)

    if label_count < MIN_SAMPLES:
        logging.warning(
            "[BERT Pipeline] 標注仍不足 %d 筆（目前 %d 筆），無法 fine-tune。"
            "請確認 GEMINI_API_KEY 已設且 article_labels 表可寫入。",
            MIN_SAMPLES, label_count,
        )
        return

    # 2. Fine-tune
    logging.info("[BERT Pipeline] 開始 fine-tuning（共 %d 筆標注）", label_count)
    train()

    # 3. Evaluate
    logging.info("[BERT Pipeline] 評估 fine-tuned 模型")
    evaluate()

    # 4. 全量 inference（_load_model_and_tokenizer 自動選 fine-tuned model）
    logging.info("[BERT Pipeline] 以 fine-tuned 模型對所有文章重新推論")
    run_batch_inference()


def _cmd_dw_etl(_args):
    from dw_etl import run_etl
    run_etl()


def _cmd_backup(_args):
    from backup import backup_database
    backup_database()


# ─── QA / 診斷 ─────────────────────────────────────────────────────────────────

def _cmd_qa(_args):
    from QA import QA_checks
    QA_checks()


def _cmd_ge(_args):
    from ge_validation import ge_validate
    ge_validate()


def _cmd_reparse(_args):
    from reparse import repair
    result = repair()
    logging.info("[Reparse] 修復完成：%d 筆", result["repaired"])


def _cmd_mongo(_args):
    from mongo_helper import ensure_indexes, get_mongo, RAW_RESPONSES
    ensure_indexes()
    with get_mongo() as db:
        count = db[RAW_RESPONSES].count_documents({})
        logging.info("[MongoDB] 連線成功，raw_responses：%d 筆", count)


# ─── AI 模型預測（分層） ──────────────────────────────────────────────────────

from config import sources_by_market

_MARKET_SOURCES = {
    "tw": sources_by_market("TW"),
    "us": sources_by_market("US"),
}

_MARKET_PRICES_TABLE = {
    "tw": STOCK_PRICES_TABLE,
    "us": US_STOCK_PRICES_TABLE,
}


def _cmd_ai_predict(args):
    from ai_model_prediction import fetch_sentiment, fetch_price, run_ai_model_prediction
    from datetime import date, timedelta

    action = args.action
    market = args.market

    if action == "fetch-sentiment":
        sources = _MARKET_SOURCES[market]
        df = fetch_sentiment(sources)
        logging.info("[AI Prediction] fetch-sentiment %s：%d 天，avg_sentiment 非 NULL %d 筆",
                     market, len(df), df["avg_sentiment"].notna().sum())

    elif action == "fetch-price":
        prices_table = _MARKET_PRICES_TABLE[market]
        end = (date.today() + timedelta(days=1)).isoformat()
        df = fetch_price(prices_table, "2023-01-01", end)
        logging.info("[AI Prediction] fetch-price %s（%s）：%d 天", market, prices_table, len(df))

    elif action == "run":
        if market == "all":
            run_ai_model_prediction("tw")
            run_ai_model_prediction("us")
        else:
            run_ai_model_prediction(market)


# ─── LLM 輔助標注 ─────────────────────────────────────────────────────────────

def _cmd_llm_label(args):
    from llm_labeling import run_llm_labeling
    result = run_llm_labeling(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
    logging.info("[LLM] 完成：處理 %d 篇，儲存 %d 筆", result["total_processed"], result["total_saved"])


# ─── Reddit 批次 ───────────────────────────────────────────────────────────────

def _cmd_reddit_batch(args):
    from scrapers.reddit_batch_loader import RedditBatchLoader, REDDIT_BATCH_HISTORY_START

    if args.after and args.before:
        after_dt  = datetime.strptime(args.after,  "%Y-%m-%d")
        before_dt = datetime.strptime(args.before, "%Y-%m-%d")
    else:
        before_dt = datetime.utcnow()
        after_dt  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
        logging.info("[Reddit] 未指定日期，預設全歷史：%s ～ %s",
                     after_dt.date(), before_dt.date())

    RedditBatchLoader().run_range(after_dt, before_dt)


# ─── Wayback Machine 回填 ─────────────────────────────────────────────────────

def _cmd_wayback_backfill(args):
    from scrapers.wayback_backfill import WaybackBackfillScraper
    # 只把使用者實際傳入的參數傳下去，沒給的就讓 scraper 套自己的預設
    kwargs = {"source": args.source}
    if args.min_year     is not None: kwargs["start_year"]   = args.min_year
    if args.max_year     is not None: kwargs["end_year"]     = args.max_year
    if args.max_articles is not None: kwargs["max_articles"] = args.max_articles
    WaybackBackfillScraper(**kwargs).run()


# ─── Auth 金鑰產生 ────────────────────────────────────────────────────────────

def _cmd_gen_jwt_secret(_args):
    """產生 JWT_SECRET_KEY（256-bit 隨機 hex）並印出 .env 格式"""
    import secrets
    key = secrets.token_hex(32)
    print(f"JWT_SECRET_KEY={key}")


def _cmd_gen_pw_hash(args):
    """產生 bcrypt hash 並印出對應的 .env 格式"""
    from passlib.hash import bcrypt
    env_key = {"admin": "ADMIN_PW_HASH", "viewer": "VIEWER_PW_HASH"}[args.username]
    print(f"{env_key}={bcrypt.hash(args.password)}")


# ─── Services / Dev（subprocess 包裝） ────────────────────────────────────────

def _cmd_services(args):
    """docker-compose up -d / down / ps（cwd = project root）"""
    cmd_map = {
        "up":   ["docker-compose", "up", "-d"],
        "down": ["docker-compose", "down"],
        "ps":   ["docker-compose", "ps"],
    }
    subprocess.run(cmd_map[args.action], cwd=_PROJECT_ROOT, check=True)


def _cmd_logs(args):
    """docker-compose logs -f <service>（持續輸出，Ctrl-C 退出）"""
    os.chdir(_PROJECT_ROOT)
    os.execvp("docker-compose", ["docker-compose", "logs", "-f", args.service])


def _cmd_dev(args):
    """啟動本機 dev server（uvicorn / streamlit）"""
    os.chdir(_DEPENDENT_CODE)
    if args.service == "api":
        os.execvp("uvicorn", ["uvicorn", "api:app", "--reload", "--port", "8000"])
    elif args.service == "dashboard":
        os.execvp("streamlit", ["streamlit", "run", str(_DEPENDENT_CODE / "visualization.py")])
    elif args.service == "labeling":
        os.execvp("streamlit", ["streamlit", "run", str(_DEPENDENT_CODE / "labeling_tool.py")])


def _cmd_worker(_args):
    """啟動 Celery worker（tasks.py）"""
    os.chdir(_DEPENDENT_CODE)
    os.execvp("celery", ["celery", "-A", "tasks", "worker", "-l", "info", "-c", "4"])


def _cmd_celery_trigger(_args):
    """非同步觸發完整 pipeline（透過 Celery worker）"""
    os.chdir(_DEPENDENT_CODE)
    from tasks import run_full_pipeline
    result = run_full_pipeline.delay()
    print(f"Pipeline 已加入佇列，task_id: {result.id}")


def _cmd_test(args):
    """pytest（預設掃全部 test_*.py，可指定路徑）"""
    os.chdir(_DEPENDENT_CODE)
    target = args.path or "."
    os.execvp("pytest", ["pytest", target, "-v"])


def _cmd_k8s_apply_secrets(_args):
    """從 .env 產 K8s Secret 並 apply 到集群（idempotent upsert）"""
    script = _PROJECT_ROOT / "scripts" / "apply_k8s_secrets.sh"
    os.execvp(str(script), [str(script)])


def _cmd_k8s_debug(args):
    """臨時起一個 debug Pod（取代舊版 worker Deployment 的常駐模式）"""
    script = _PROJECT_ROOT / "scripts" / "k8s_debug_pod.sh"
    os.execvp(str(script), [str(script), *args.cmd])


def _cmd_validate(_args):
    """本機靜態驗證（Python syntax / YAML / dbt parse / docker build / pytest）"""
    script = _PROJECT_ROOT / "scripts" / "validate.sh"
    os.execvp(str(script), [str(script)])


# ─── Argparse ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PTT 情緒分析系統 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Pipeline steps
    p_pl = sub.add_parser("pipeline", help="完整 pipeline（Step 0~7）")
    p_pl.add_argument("--background", action="store_true", help="背景執行（nohup，log 寫入 logs/pipeline_manual.log）")
    sub.add_parser("schema",    help="建立 DB schema")
    sub.add_parser("extract",   help="爬蟲抓取所有來源")
    sub.add_parser("transform", help="QA + 自動修復 + GE 驗證")
    sub.add_parser("pii",       help="PII 遮蔽（author hash 化）")
    sub.add_parser("dw-etl",    help="OLTP → DW ETL + 刷新 Data Mart")
    sub.add_parser("backup",    help="S3 備份")

    p_bert = sub.add_parser("bert", help="BERT 操作")
    p_bert.add_argument("action", choices=["train", "evaluate", "infer", "full-pipeline"])
    p_bert.add_argument("--target-labels", type=int, default=500, dest="target_labels",
                        help="full-pipeline 目標標注總數；若現有標注不足此數，自動補跑 LLM labeling（預設 500）")

    # QA / 診斷
    sub.add_parser("qa",      help="QA 資料品質檢查")
    sub.add_parser("ge",      help="Great Expectations 驗證")
    sub.add_parser("reparse", help="從 MongoDB re-parse 修復資料")
    sub.add_parser("mongo",   help="MongoDB 連線測試")

    # AI 模型預測
    p_ai = sub.add_parser("ai-predict", help="Walk-Forward AI 模型預測（可分層測試）")
    p_ai.add_argument(
        "action",
        choices=["fetch-sentiment", "fetch-price", "run"],
        help="fetch-sentiment / fetch-price：單層測試；run：完整預測",
    )
    p_ai.add_argument(
        "market",
        nargs="?",
        choices=["tw", "us", "all"],
        default="all",
        help="tw / us / all（run 時有效，fetch-* 需填 tw 或 us）",
    )

    # LLM 輔助標注
    p_llm = sub.add_parser("llm-label", help="LLM 輔助情緒標注（Claude API）")
    p_llm.add_argument("--batch-size",  type=int, default=50,  dest="batch_size",  help="每批取幾篇（預設 50）")
    p_llm.add_argument("--max-batches", type=int, default=10,  dest="max_batches", help="最多跑幾批（預設 10）")

    # Reddit 批次
    p_rb = sub.add_parser("reddit-batch", help="Reddit 歷史大量載入")
    p_rb.add_argument("after",  nargs="?", metavar="YYYY-MM-DD", help="起始日期")
    p_rb.add_argument("before", nargs="?", metavar="YYYY-MM-DD", help="結束日期")

    # Wayback Machine 回填
    p_wb = sub.add_parser("wayback-backfill", help="Wayback Machine 歷史回填（CNN / WSJ）")
    p_wb.add_argument("source", choices=["cnn", "wsj"], help="要 backfill 的來源")
    p_wb.add_argument("--min-year",     type=int, default=None, dest="min_year", help="probe 起始年份（預設 scraper 內定）")
    p_wb.add_argument("--max-year",     type=int, default=None, dest="max_year", help="probe 結束年份（預設當年）")
    p_wb.add_argument("--max-articles", type=int, default=None, dest="max_articles", help="本次最多寫入幾篇（預設無限制）")

    # docker-compose 服務
    p_svc = sub.add_parser("services", help="docker-compose up / down / ps")
    p_svc.add_argument("action", choices=["up", "down", "ps"])

    p_logs = sub.add_parser("logs", help="docker-compose logs -f <service>")
    p_logs.add_argument("service", help="service 名稱（例：api、postgres、redis）")

    # 本機 dev servers
    p_dev = sub.add_parser("dev", help="啟動本機 dev server（uvicorn / streamlit）")
    p_dev.add_argument("service", choices=["api", "dashboard", "labeling"])

    sub.add_parser("worker", help="啟動 Celery worker（tasks.py）")
    sub.add_parser("celery-trigger", help="非同步觸發完整 pipeline（需要 worker 在跑）")

    p_test = sub.add_parser("test", help="pytest（預設掃全部 test_*.py）")
    p_test.add_argument("path", nargs="?", default=None, help="pytest 路徑（可省略，預設跑全部）")

    sub.add_parser("k8s-apply-secrets", help="從 .env 產 K8s Secret 並 apply（取代 k8s/secret.yaml 的 placeholder）")

    p_debug = sub.add_parser("k8s-debug", help="臨時起 debug Pod（取代常駐 worker Deployment）")
    p_debug.add_argument("cmd", nargs=argparse.REMAINDER, help="要在 Pod 裡跑的指令（省略則開 bash）")

    sub.add_parser("validate", help="本機靜態驗證（Python / YAML / dbt / Docker / pytest，對應 CI 的 validate.yml）")

    # Auth 金鑰產生
    sub.add_parser("gen-jwt-secret", help="產生 JWT_SECRET_KEY（256-bit 隨機 hex），輸出 .env 格式")

    p_pw = sub.add_parser("gen-pw-hash", help="產生 bcrypt hash，輸出 ADMIN_PW_HASH / VIEWER_PW_HASH .env 格式")
    p_pw.add_argument("username", choices=["admin", "viewer"], help="要設定的帳號")
    p_pw.add_argument("password", help="明文密碼")

    args = parser.parse_args()

    dispatch = {
        "pipeline":  _cmd_pipeline,
        "schema":    _cmd_schema,
        "extract":   _cmd_extract,
        "transform": _cmd_transform,
        "pii":       _cmd_pii,
        "bert":      _cmd_bert,
        "dw-etl":    _cmd_dw_etl,
        "backup":    _cmd_backup,
        "qa":         _cmd_qa,
        "ge":         _cmd_ge,
        "reparse":    _cmd_reparse,
        "mongo":      _cmd_mongo,
        "ai-predict": _cmd_ai_predict,
        "llm-label":  _cmd_llm_label,
        "reddit-batch":     _cmd_reddit_batch,
        "wayback-backfill": _cmd_wayback_backfill,
        "services": _cmd_services,
        "logs":     _cmd_logs,
        "dev":      _cmd_dev,
        "worker":          _cmd_worker,
        "celery-trigger":  _cmd_celery_trigger,
        "test":     _cmd_test,
        "k8s-apply-secrets": _cmd_k8s_apply_secrets,
        "k8s-debug":         _cmd_k8s_debug,
        "validate":          _cmd_validate,
        "gen-jwt-secret": _cmd_gen_jwt_secret,
        "gen-pw-hash":    _cmd_gen_pw_hash,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
