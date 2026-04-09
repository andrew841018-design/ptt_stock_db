"""
Stock Matcher：從文章標題 + 內文比對股票代號與公司名稱

支援：
  - 台股：4 位數字代號（如 2330）+ 公司名（如 台積電）
  - 美股：大寫 ticker（如 NVDA）+ 公司名（如 NVIDIA）

結果存入 stock_mentions 表，供儀表板「熱門個股」排行使用。

由 pipeline.py 呼叫
"""

import json
import logging
import os
import re
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
from config import PG_CONFIG, ARTICLES_TABLE
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── 載入字典 ──────────────────────────────────────────────────────────────────

_DICT_PATH = os.path.join(os.path.dirname(__file__), "stock_dict.json")

with open(_DICT_PATH, encoding="utf-8") as f:
    _RAW = json.load(f)

# tw: {"2330": "台積電", ...}  + 反查 {"台積電": "2330", ...}
TW_CODE_TO_NAME: dict[str, str] = _RAW["tw"]
TW_NAME_TO_CODE: dict[str, str] = {name: code for code, name in _RAW["tw"].items()}

# us: {"NVDA": "NVIDIA", ...}  + 反查
US_CODE_TO_NAME: dict[str, str] = _RAW["us"]
US_NAME_TO_CODE: dict[str, str] = {name: code for code, name in _RAW["us"].items()}

# 台股代號 regex：4~5 位數字，前後不接字母或數字（避免抓到電話號碼）
_TW_REGEX = re.compile(r"(?<![A-Za-z0-9])(\d{4,5})(?![A-Za-z0-9])")

# 美股 ticker regex：2~5 大寫字母，前後不接小寫或數字
_US_REGEX = re.compile(r"(?<![A-Za-z])([A-Z]{2,5})(?!\.[A-Za-z])(?![a-z])")


# ─── 抽取函式 ──────────────────────────────────────────────────────────────────

def extract_stocks(text: str, market: str = "tw") -> list[dict]:
    """
    從文字中抽取股票提及，回傳 list[{"code": ..., "name": ..., "market": ...}]
    market: "tw" 或 "us"
    """
    mentions = []
    seen = set()

    if market == "tw":
        # 代號比對
        for m in _TW_REGEX.finditer(text):
            code = m.group(1)#group(1) => 第一個括號內的內容
            if code in TW_CODE_TO_NAME and code not in seen:
                mentions.append({"code": code, "name": TW_CODE_TO_NAME[code], "market": "TW"})
                seen.add(code)
        # 公司名比對（長名優先，避免短名誤抓，按照長度排序）
        for name in sorted(TW_NAME_TO_CODE, key=len, reverse=True):
            if name in text:
                code = TW_NAME_TO_CODE[name]
                if code not in seen:
                    mentions.append({"code": code, "name": name, "market": "TW"})
                    seen.add(code)

    else:  # us
        for m in _US_REGEX.finditer(text):
            code = m.group(1)
            if code in US_CODE_TO_NAME and code not in seen:
                mentions.append({"code": code, "name": US_CODE_TO_NAME[code], "market": "US"})
                seen.add(code)
        # 公司名比對
        for name in sorted(US_NAME_TO_CODE, key=len, reverse=True):
            if name in text:
                code = US_NAME_TO_CODE[name]
                if code not in seen:
                    mentions.append({"code": code, "name": name, "market": "US"})
                    seen.add(code)

    return mentions


# ─── Schema ───────────────────────────────────────────────────────────────────

CREATE_STOCK_MENTIONS = """
CREATE TABLE IF NOT EXISTS stock_mentions (
    mention_id  SERIAL      PRIMARY KEY,
    article_id  INTEGER     NOT NULL REFERENCES articles(article_id),
    stock_code  VARCHAR(20) NOT NULL,
    stock_name  VARCHAR(100),
    market      VARCHAR(10) NOT NULL,   -- 'TW' / 'US'
    UNIQUE (article_id, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_stock_mentions_code ON stock_mentions(stock_code);

-- 追蹤哪些文章已處理（包含無提及的文章），避免無限循環
CREATE TABLE IF NOT EXISTS match_done (
    article_id INTEGER PRIMARY KEY REFERENCES articles(article_id)
);
"""


def create_mentions_table() -> None:
    conn = psycopg2.connect(**PG_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_STOCK_MENTIONS)
        conn.commit()
        logging.info("[Match] stock_mentions table ready")
    finally:
        conn.close()


# ─── 批次抽取入庫 ──────────────────────────────────────────────────────────────

def run_matcher(batch_size: int = 1000) -> None:
    """
    對所有尚未處理的文章標記提及的股票，寫入 stock_mentions。
    以 match_done 追蹤已處理文章（含無提及者），避免 LEFT JOIN IS NULL 無限循環。
    """
    create_mentions_table()

    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) FROM {ARTICLES_TABLE} a
                WHERE a.article_id NOT IN (SELECT article_id FROM match_done)
            """)
            total = cur.fetchone()[0]

    if total == 0:
        logging.info("[Match] 所有文章已標記完成，跳過")
        return

    logging.info("[Match] 待處理：%d 篇文章", total)

    tw_sources = {"ptt", "cnyes"}
    processed  = 0

    while True:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT a.article_id, a.title, a.content, s.source_name
                    FROM {ARTICLES_TABLE} a
                    JOIN sources s ON s.source_id = a.source_id
                    WHERE a.article_id NOT IN (SELECT article_id FROM match_done)
                    ORDER BY a.article_id
                    LIMIT %s
                """, (batch_size,))
                rows = cur.fetchall()

        if not rows:
            break

        mention_records = []
        done_id        = []
        for article_id, title, content, source_name in rows:
            text    = title + ' ' + (content or '')
            market  = "tw" if source_name in tw_sources else "us"
            hits    = extract_stocks(text, market)
            for m in hits:
                mention_records.append((article_id, m["code"], m["name"], m["market"]))
            done_id.append((article_id,))

        conn = psycopg2.connect(**PG_CONFIG)
        try:
            with conn.cursor() as cur:
                if mention_records:
                    psycopg2.extras.execute_values(
                        cur,
                        """
                        INSERT INTO stock_mentions (article_id, stock_code, stock_name, market)
                        VALUES %s
                        ON CONFLICT (article_id, stock_code) DO NOTHING
                        """,
                        mention_records,
                    )
                # 標記已處理（無論有無提及）
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO match_done (article_id) VALUES %s ON CONFLICT DO NOTHING",
                    done_id,
                )
            conn.commit()
        finally:
            conn.close()

        processed += len(rows)
        logging.info("[Match] 進度：%d / %d（本批提及 %d 筆）", processed, total, len(mention_records))

    logging.info("[Match] 完成")


# ─── 熱門股票統計（給儀表板用）────────────────────────────────────────────────

def get_hot_stocks(market: str = "TW", top_n: int = 20) -> list[dict]:
    """回傳提及次數最多的前 N 支股票"""
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT stock_code, stock_name, COUNT(*) AS mention_count
                FROM stock_mentions
                WHERE market = %s
                GROUP BY stock_code, stock_name
                ORDER BY mention_count DESC
                LIMIT %s
            """, (market, top_n))
            rows = cur.fetchall()
    return [{"code": code, "name": name, "count": count} for code, name, count in rows]
