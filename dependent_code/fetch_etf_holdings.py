"""
抓取 ETF 持股並更新 stock_dict.json

台灣 0050（50支）：
  - 來源：TWSE openapi STOCK_DAY_ALL（全部上市股票收盤價）
  - 取市值前 50 支普通股（4 位數字，非 ETF）

美國 VOO（S&P 500，約 500 支）：
  - 來源：Wikipedia List of S&P 500 companies
  - VOO 追蹤 S&P 500，故成分股與 S&P 500 相同

執行方式：python fetch_etf_holdings.py
"""

import json
import logging
import os
import re
import time

import requests
from config import REQUEST_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DICT_PATH  = os.path.join(os.path.dirname(__file__), "stock_dict.json")
TWSE_API   = "https://openapi.twse.com.tw"
HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


# ─── 台灣 0050：上市普通股名稱清單 ───────────────────────────────────────────

def fetch_tw_top50() -> dict[str, str]:
    """
    從 TWSE 取得所有上市普通股（4 位數字代號），
    回傳 {代號: 名稱}，供 stock_matcher 標記文章中的股票提及。
    """
    logging.info("[TW] 抓取上市股票清單...")

    r = requests.get(f"{TWSE_API}/v1/exchangeReport/STOCK_DAY_ALL",
                     headers=HEADERS, timeout=15)
    data = r.json()

    result: dict[str, str] = {}
    for d in data:
        code = d.get("Code", "").strip()
        name = d.get("Name", "").strip()
        if re.fullmatch(r"[1-9]\d{3}", code) and name:
            result[code] = name

    logging.info("[TW] 取得上市普通股 %d 支", len(result))
    return result


# ─── 美國 VOO：S&P 500 全部成分股 ─────────────────────────────────────────────

def fetch_us_sp500() -> dict[str, str]:
    """
    從 Wikipedia 取得 S&P 500 全部成分股（VOO 追蹤 S&P 500）。
    回傳 {Ticker: 公司名稱}，例如 {"NVDA": "NVIDIA Corporation"}
    含雙股份類別（GOOGL / GOOG），實際約 503 支。
    """
    from io import StringIO
    import pandas as pd

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    logging.info("[US] 從 Wikipedia 抓取 S&P 500 成分股...")

    r = requests.get(url, headers=HEADERS, timeout=15)
    tables = pd.read_html(StringIO(r.text))
    df = tables[0]   # 第一張 table 是成分股清單

    result: dict[str, str] = {}
    for _, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().replace(".", "-")  # BRK.B → BRK-B
        name   = str(row["Security"]).strip()
        if symbol and name and symbol != "nan":
            result[symbol] = name

    logging.info("[US] 取得 S&P 500 成分股 %d 支（VOO）", len(result))
    return result


# ─── 更新 stock_dict.json ──────────────────────────────────────────────────────

def update_stock_dict(tw: dict[str, str], us: dict[str, str]) -> None:
    """
    載入現有 stock_dict.json，用新抓的資料覆蓋 tw / us，
    並保留手動維護的其他 key（如 ETF 本身 0050 / VOO 等）。
    """
    existing: dict = {}
    if os.path.exists(DICT_PATH):
        with open(DICT_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = {
        "tw": tw,   # 完全替換（0050 的 50 支）
        "us": us,   # 完全替換（S&P 500 的約 503 支）
    }

    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    logging.info("[Done] stock_dict.json 更新完成：TW %d 支、US %d 支",
                 len(merged["tw"]), len(merged["us"]))


# ─── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    tw = fetch_tw_top50()
    time.sleep(REQUEST_DELAY)
    us = fetch_us_sp500()
    update_stock_dict(tw, us)
