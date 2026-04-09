import os
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

# PostgreSQL 連線設定（管理員，建表 / 建角色用）
PG_CONFIG = {
    "host":     os.environ.get("PG_HOST",     "localhost"),
    "port":     int(os.environ.get("PG_PORT",  "5432")),
    "dbname":   os.environ.get("PG_DBNAME",   "stock_analysis_db"),
    "user":     os.environ.get("PG_USER",     "postgres"),
    "password": os.environ.get("PG_PASSWORD", ""),
}

# PostgreSQL API 唯讀角色（FastAPI 用，只有 SELECT 權限）
PG_API_CONFIG = {
    **PG_CONFIG,
    "user":     os.environ.get("PG_API_USER",     "api_user"),
    "password": os.environ.get("PG_API_PASSWORD", ""),
}

# PostgreSQL ETL 讀寫角色（Pipeline 用，有 INSERT/UPDATE/DELETE 權限）
PG_ETL_CONFIG = {
    **PG_CONFIG,
    "user":     os.environ.get("PG_ETL_USER",     "etl_user"),
    "password": os.environ.get("PG_ETL_PASSWORD", ""),
}

# JWT 認證設定
JWT_SECRET_KEY     = os.environ.get("JWT_SECRET_KEY",     "change-me-in-production")
JWT_ALGORITHM      = os.environ.get("JWT_ALGORITHM",      "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# PII 設定（author hash 用）
PII_HASH_SALT = os.environ.get("PII_HASH_SALT", "change-me-in-production")

# 各來源設定（新增來源只需在這裡加一組）
# 每個來源包含：
#   name      → 寫入 sources 表的顯示名稱
#   url       → 來源首頁（同時作為 sources 表的唯一識別）
#   num_pages → 每次爬取的頁數（各來源節奏不同，分開控制）
#
SOURCES = {
    "ptt": {
        "name":      "ptt",
        "url":       "https://www.ptt.cc/bbs/Stock",
        "num_pages": 10000,
    },
    "cnyes": {
        "name":      "cnyes",
        "url":       "https://news.cnyes.com/news/cat/tw_stock",
        "num_pages": 1000,
        "page_size": 30,
    },
    "reddit": {
        "name":       "reddit",
        "url":        "https://www.reddit.com/r/investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        "subreddits": "investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        # subreddit 本身即財經分類，不需額外 keyword 過濾
        # 每頁 100 筆，連續重複頁停止
        "num_pages":  1000,
    },
}

# 爬蟲共用設定
MAX_RETRY = 5

# 資料庫資料表名稱
ARTICLES_TABLE = "articles"
COMMENTS_TABLE = "comments"
SENTIMENT_SCORES_TABLE = "sentiment_scores"
SOURCES_TABLE = "sources"
STOCK_PRICES_TABLE    = "stock_prices"     # 追蹤標的：0050（元大台灣50），詳見 schema.py
US_STOCK_PRICES_TABLE = "us_stock_prices"  # 追蹤標的：VOO（Vanguard S&P 500 ETF），詳見 schema.py
ARTICLE_LABELS_TABLE  = "article_labels"   # 人工標注情緒（labeling_tool.py → bert_sentiment.py fine-tune 用）

