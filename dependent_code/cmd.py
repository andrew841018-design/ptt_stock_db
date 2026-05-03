"""
統一 CLI 入口 — 供本機測試與手動觸發各功能

用法：
  # Pipeline 各步驟（可單獨執行，也可跑完整流程）
  python cmd.py schema
  python cmd.py extract
  python cmd.py transform
  python cmd.py pii
  python cmd.py bert train|evaluate|infer
  python cmd.py match
  python cmd.py dw-etl
  python cmd.py looker
  python cmd.py backup
  python cmd.py pipeline                           # Step 0~9 全跑

  # QA / 診斷
  python cmd.py qa
  python cmd.py ge
  python cmd.py reparse
  python cmd.py mongo

  # Backtest（分層測試）
  python cmd.py backtest fetch-sentiment tw        # 只測情緒 DB 查詢
  python cmd.py backtest fetch-sentiment us
  python cmd.py backtest fetch-price tw            # 只測股價 DB 讀取
  python cmd.py backtest fetch-price us
  python cmd.py backtest run tw|us|all             # 完整回測

  # Reddit 歷史批次載入
  python cmd.py reddit-batch                       # 全歷史
  python cmd.py reddit-batch 2024-01-01 2024-03-01 # 指定區間
"""

import argparse
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from config import STOCK_PRICES_TABLE, US_STOCK_PRICES_TABLE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ─── Pipeline Steps ────────────────────────────────────────────────────────────

def _cmd_pipeline(_args):
    from pipeline import run_pipeline
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


def _cmd_match(_args):
    from fetch_etf_holdings import run as run_fetch_etf
    from stock_matcher import run_matcher
    run_fetch_etf()
    run_matcher()


def _cmd_dw_etl(_args):
    from dw_etl import run_etl
    run_etl()


def _cmd_looker(_args):
    from looker_export import main as run_looker_export
    run_looker_export()


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


# ─── Backtest（分層） ──────────────────────────────────────────────────────────

_MARKET_SOURCES = {
    "tw": ["ptt", "cnyes"],
    "us": ["reddit"],
}

_MARKET_PRICES_TABLE = {
    "tw": STOCK_PRICES_TABLE,
    "us": US_STOCK_PRICES_TABLE,
}


def _cmd_backtest(args):
    from backtest import fetch_sentiment, fetch_price, run_backtest
    from datetime import date, timedelta

    action = args.action
    market = getattr(args, "market", None)

    if action == "fetch-sentiment":
        sources = _MARKET_SOURCES[market]
        df = fetch_sentiment(sources)
        logging.info("[Backtest] fetch-sentiment %s：%d 天，avg_sentiment 非 NULL %d 筆",
                     market, len(df), df["avg_sentiment"].notna().sum())

    elif action == "fetch-price":
        prices_table = _MARKET_PRICES_TABLE[market]
        end = (date.today() + timedelta(days=1)).isoformat()
        df = fetch_price(prices_table, "2023-01-01", end)
        logging.info("[Backtest] fetch-price %s（%s）：%d 天", market, prices_table, len(df))

    elif action == "run":
        if market == "all":
            run_backtest("tw")
            run_backtest("us")
        else:
            run_backtest(market)


# ─── Reddit 批次 ───────────────────────────────────────────────────────────────

def _cmd_reddit_batch(args):
    from scrapers.reddit_batch_loader import RedditBatchLoader
    from config import REDDIT_BATCH_HISTORY_START

    if args.after and args.before:
        after_dt  = datetime.strptime(args.after,  "%Y-%m-%d")
        before_dt = datetime.strptime(args.before, "%Y-%m-%d")
    else:
        before_dt = datetime.utcnow()
        after_dt  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
        logging.info("[Reddit] 未指定日期，預設全歷史：%s ～ %s",
                     after_dt.date(), before_dt.date())

    RedditBatchLoader().run_range(after_dt, before_dt)


# ─── Argparse ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PTT 情緒分析系統 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Pipeline steps
    sub.add_parser("pipeline",  help="完整 pipeline（Step 0~9）")
    sub.add_parser("schema",    help="建立 DB schema")
    sub.add_parser("extract",   help="爬蟲抓取所有來源")
    sub.add_parser("transform", help="QA + 自動修復 + GE 驗證")
    sub.add_parser("pii",       help="PII 遮蔽（author hash 化）")
    sub.add_parser("match",     help="更新 ETF 持股 + 股票代號比對")
    sub.add_parser("dw-etl",    help="OLTP → DW ETL + 刷新 Data Mart")
    sub.add_parser("looker",    help="匯出 CSV 給 Looker Studio")
    sub.add_parser("backup",    help="S3 備份")

    p_bert = sub.add_parser("bert", help="BERT 操作")
    p_bert.add_argument("action", choices=["train", "evaluate", "infer"])

    # QA / 診斷
    sub.add_parser("qa",      help="QA 資料品質檢查")
    sub.add_parser("ge",      help="Great Expectations 驗證")
    sub.add_parser("reparse", help="從 MongoDB re-parse 修復資料")
    sub.add_parser("mongo",   help="MongoDB 連線測試")

    # Backtest
    p_bt = sub.add_parser("backtest", help="Walk-Forward 回測（可分層測試）")
    p_bt.add_argument(
        "action",
        choices=["fetch-sentiment", "fetch-price", "run"],
        help="fetch-sentiment / fetch-price：單層測試；run：完整回測",
    )
    p_bt.add_argument(
        "market",
        nargs="?",
        choices=["tw", "us", "all"],
        default="all",
        help="tw / us / all（run 時有效，fetch-* 需填 tw 或 us）",
    )

    # Reddit 批次
    p_rb = sub.add_parser("reddit-batch", help="Reddit 歷史大量載入")
    p_rb.add_argument("after",  nargs="?", metavar="YYYY-MM-DD", help="起始日期")
    p_rb.add_argument("before", nargs="?", metavar="YYYY-MM-DD", help="結束日期")

    args = parser.parse_args()

    dispatch = {
        "pipeline":  _cmd_pipeline,
        "schema":    _cmd_schema,
        "extract":   _cmd_extract,
        "transform": _cmd_transform,
        "pii":       _cmd_pii,
        "bert":      _cmd_bert,
        "match":     _cmd_match,
        "dw-etl":    _cmd_dw_etl,
        "looker":    _cmd_looker,
        "backup":    _cmd_backup,
        "qa":        _cmd_qa,
        "ge":        _cmd_ge,
        "reparse":   _cmd_reparse,
        "mongo":     _cmd_mongo,
        "backtest":  _cmd_backtest,
        "reddit-batch": _cmd_reddit_batch,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
