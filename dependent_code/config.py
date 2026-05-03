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

# 各來源設定（新增來源只需在這裡加一組）
# 每個來源包含：
#   name      → 寫入 sources 表的顯示名稱
#   url       → 來源首頁（同時作為 sources 表的唯一識別）
#   num_pages → 每次爬取的頁數（各來源節奏不同，分開控制）
#
SOURCES = {
    "ptt": {
        "name":      "PTT Stock",
        "url":       "https://www.ptt.cc/bbs/Stock",
        "num_pages": 10000,
    },
    "cnyes": {
        "name":      "鉅亨網",
        "url":       "https://news.cnyes.com/news/cat/tw_stock",
        "num_pages": 1000,
        "page_size": 30,
    },
    "reddit": {
        "name":       "Reddit Finance",
        "url":        "https://www.reddit.com/r/investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        "subreddits": "investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        # subreddit 本身即財經分類，不需額外 keyword 過濾
        # 每頁 100 筆，連續重複頁停止
        "num_pages":  1000,
    },
}

# 爬蟲共用設定
MAX_RETRY = 5
PTT_SCRAPE_SLEEP = 0.3  # 文章內頁請求間隔（避免被封鎖）

# 爬蟲過濾關鍵字（這類文章不爬，目前只有 PTT 用到）
SKIP_KEYWORDS = ["公告", "盤後閒聊", "盤中閒聊", "情報"]


# TWSE 每次抓幾個月的歷史資料（1 = 只抓當月，12 = 抓一整年）
TWSE_MONTHS = 12
TWSE_SLEEP_INTERVAL = 3   # TWSE 限速：每次請求間隔至少 3 秒
TWSE_TIMEOUT        = 10  # TWSE API 請求 timeout（秒）

# Reddit batch 設定（Arctic Shift API）
REDDIT_BATCH_SLEEP_INTERVAL  = 0.3        # 建議每秒不超過 5 次請求（0.2s per request）
REDDIT_BATCH_HISTORY_START   = "2005-01-01"  # Reddit 創立年份，批量歷史抓取的起點

# US 股價設定（yfinance）
TWSE_STOCK_NO   = "0050"          # 追蹤標的股票代號
TWSE_STOCK_NAME = "元大台灣50"    # 顯示名稱（圖表標題用）
US_STOCK_MONTHS = 120  # 每次抓幾個月的歷史資料

# Redis 快取設定
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))# 6379 is the default port for Redis
REDIS_TTL  = 86400  # 24 hours，unit is second

# 資料庫資料表名稱
ARTICLES_TABLE = "articles"
COMMENTS_TABLE = "comments"
SENTIMENT_SCORES_TABLE = "sentiment_scores"
SOURCES_TABLE = "sources"
STOCK_PRICES_TABLE    = "stock_prices"     # 追蹤標的：0050（元大台灣50），詳見 schema.py
US_STOCK_PRICES_TABLE = "us_stock_prices"  # 追蹤標的：VOO（Vanguard S&P 500 ETF），詳見 schema.py

# Cache key
CACHE_KEY_ARTICLES = "articles_df"

# AWS S3 備份設定
S3_BUCKET = "ptt-sentiment-backup"
DOCKER_PATH = "/usr/local/bin/docker"
DB_CONTAINER = "ptt_stock_db"

# BERT 情緒分析設定
BERT_MODEL      = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
PUSH_TAG_WEIGHT = 0.3   # 推噓對留言情緒的加權幅度（應用標注資料集後調整）
TITLE_WEIGHT    = 0.3   # 標題情緒在綜合分數的比重
CONTENT_WEIGHT  = 0.4   # 內文情緒在綜合分數的比重
COMMENT_WEIGHT  = 0.3   # 留言情緒在綜合分數的比重