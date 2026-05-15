
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
MONGO_TIMEOUT_MS = 5000
MONGO_DB         = "stock_analysis_db"
RAW_RESPONSES    = "raw_responses"


@contextmanager
def get_mongo():
    client = MongoClient(MONGO_HOST, MONGO_PORT, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
    try:
        yield client[MONGO_DB]
    finally:
        client.close()



def ensure_indexes() -> None:
    with get_mongo() as db:
        col = db[RAW_RESPONSES]
        col.create_index([("url", 1)], unique=True)
        col.create_index([("source", 1)])
        col.create_index([("fetched_at", -1)])
        logging.info("[MongoDB] indexes ready on %s", RAW_RESPONSES)


def save_raw_response(source: str, url: str, raw_content: str,
                      content_type: str = "html",
                      http_status: int = 200,
                      extra: Optional[dict] = None) -> None:
    doc = {
        "source":      source,
        "url":         url,
        "fetched_at":  datetime.utcnow().isoformat(),
        "http_status": http_status,
    }

    if content_type == "html":
        doc["raw_html"] = raw_content
    else:
        doc["raw_json"] = raw_content

    if extra:
        doc.update(extra)

    try:
        with get_mongo() as db:
            db[RAW_RESPONSES].update_one(
                {"url": url},
                {"$set": doc},
                upsert=True,
            )
    except PyMongoError as e:
        logging.warning("[MongoDB] save_raw_response 失敗（降級跳過）：%s", e)

