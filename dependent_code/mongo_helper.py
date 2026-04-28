"""
MongoDB helper — raw_responses collection

架構：
  HTTP response → MongoDB（raw_responses）→ parse → PostgreSQL
  MongoDB 是原始資料的 source of truth，PostgreSQL 是結構化分析用。

raw_responses document 結構（每個來源不同，這才是 schema-less 的真正意義）：
  PTT     → {"source": "ptt",   "url": "...", "raw_html": "<html>...", ...}
  鉅亨網  → {"source": "cnyes", "url": "...", "raw_json": {...}, ...}
  Reddit  → {"source": "reddit","url": "...", "raw_json": {"data": {"children": [...]}}, ...}

使用範例：
    from mongo_helper import save_raw_response, get_mongo
"""

import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MONGO_HOST       = os.environ.get("MONGO_HOST", "localhost")
MONGO_PORT       = int(os.environ.get("MONGO_PORT", "27017"))
MONGO_TIMEOUT_MS = 5000              # MongoDB 連線 timeout（毫秒）
MONGO_DB         = "stock_analysis_db"
# collection 名稱：改名不會刪舊的，MongoDB 會靜默建新 collection，舊資料留在原處
# 如果真要改名，用 db["舊名"].rename("新名")，再改這裡的常數
RAW_RESPONSES    = "raw_responses"     # 原始 HTTP 回應（HTML / JSON）


@contextmanager
def get_mongo():
    """MongoDB context manager，用完自動關閉"""
    client = MongoClient(MONGO_HOST, MONGO_PORT, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
    try:
        yield client[MONGO_DB]
    finally:
        client.close()


# ─── raw_responses：原始 HTTP 回應 ────────────────────────────────────────────

def ensure_indexes() -> None:
    """建立 raw_responses 的 index"""
    with get_mongo() as db:
        # 取得 collection（不存在就自動建立，跟 PostgreSQL 不同不需要先 CREATE TABLE）
        col = db[RAW_RESPONSES]
        col.create_index([("url", 1)], unique=True)
        col.create_index([("source", 1)])
        col.create_index([("fetched_at", -1)])   # -1 = 由新到舊
        logging.info("[MongoDB] indexes ready on %s", RAW_RESPONSES)


def save_raw_response(source: str, url: str, raw_content: str,
                      content_type: str = "html",
                      http_status: int = 200,
                      extra: Optional[dict] = None) -> None:
    """
    存一筆原始 HTTP 回應到 raw_responses。

    參數：
      source       : "ptt" / "cnyes" / "reddit"
      url          : 請求的 URL
      raw_content  : 原始回應內容（HTML 字串或 JSON 字串）
      content_type : "html" 或 "json"
      http_status  : HTTP status code
      extra        : 額外欄位（來源特有的 metadata）

    document 結構隨來源不同（schema-less 的真正價值）：
      PTT   : raw_html 欄位
      其他  : raw_json 欄位（存原始 JSON 字串，避免 MongoDB 對特殊 key 報錯）
    """
    # 基本欄位：每個來源都會有的共用資料
    doc = {
        "source":      source,
        "url":         url,
        "fetched_at":  datetime.utcnow().isoformat(),
        "http_status": http_status,
    }

    # 依來源格式選 key 名稱：PTT 存 raw_html，鉅亨網/Reddit 存 raw_json
    # dict 可以直接用 doc["新key"] = value 新增不存在的欄位
    if content_type == "html":
        doc["raw_html"] = raw_content
    else:
        doc["raw_json"] = raw_content

    # extra 是呼叫端傳入的 dict，把裡面的 key-value 整包合併進 doc
    # 例如 cnyes 傳 {"news_id": 12345}，合併後 doc 就多一個 news_id 欄位
    # extra 為 None 時跳過（不呼叫 update 避免 TypeError）
    if extra:
        doc.update(extra)

    try:
        with get_mongo() as db:
            # db[RAW_RESPONSES] = 取得 collection（不存在就自動建立，不會報錯）
            # 這跟 PostgreSQL 不同：PG 沒有 CREATE TABLE 會直接報錯
            db[RAW_RESPONSES].update_one(
                {"url": url},          # WHERE：用 url 找到「這一筆」document
                {"$set": doc},         # 把dick拆開，裡面的欄位和value一對一存進去，等同一次update多個欄位
                upsert=True,           # 找不到 → INSERT 新的一筆；找到 → UPDATE 該筆的欄位
            )
    except PyMongoError as e:
        # MongoDB 掛掉不應阻斷爬蟲，降級處理
        logging.warning("[MongoDB] save_raw_response 失敗（降級跳過）：%s", e)

