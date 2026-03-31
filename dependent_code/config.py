import os
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

# PostgreSQL 連線設定
PG_CONFIG = {
    "host":     os.environ.get("PG_HOST",     "localhost"),
    "port":     int(os.environ.get("PG_PORT",  "5432")),
    "dbname":   os.environ.get("PG_DBNAME",   "ptt_stock"),
    "user":     os.environ.get("PG_USER",     "postgres"),
    "password": os.environ.get("PG_PASSWORD", ""),
}

# PTT 來源資訊
PTT_SOURCE_NAME = "PTT Stock"
PTT_SOURCE_URL  = "https://www.ptt.cc/bbs/Stock"

# 爬蟲設定
MAX_RETRY = 5
SLEEP_INTERVAL = 0.5
NUM_OF_PAGES = 2000

# 爬蟲過濾關鍵字（這類文章不爬）
SKIP_KEYWORDS = ["公告", "盤後閒聊", "盤中閒聊", "情報"]

# Redis 快取設定
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))# 6379 is the default port for Redis
REDIS_TTL  = 86400  # 24 hours，unit is second

# 資料庫資料表名稱
ARTICLES_TABLE = "articles"
COMMENTS_TABLE = "comments"
SENTIMENT_SCORES_TABLE = "sentiment_scores"
SOURCES_TABLE = "sources"