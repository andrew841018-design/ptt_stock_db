import os
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

# PostgreSQL connection (admin role: create tables / create roles)
PG_CONFIG = {
    "host":     os.environ.get("PG_HOST",     "localhost"),
    "port":     int(os.environ.get("PG_PORT",  "5432")),
    "dbname":   os.environ.get("PG_DBNAME",   "stock_analysis_db"),
    "user":     os.environ.get("PG_USER",     "postgres"),
    "password": os.environ.get("PG_PASSWORD", ""),
}

# PostgreSQL API read-only role (FastAPI, SELECT only)
PG_API_CONFIG = {
    **PG_CONFIG,
    "user":     os.environ.get("PG_API_USER",     "api_user"),
    "password": os.environ.get("PG_API_PASSWORD", ""),
}

# PostgreSQL ETL read-write role (Pipeline, INSERT/UPDATE/DELETE)
PG_ETL_CONFIG = {
    **PG_CONFIG,
    "user":     os.environ.get("PG_ETL_USER",     "etl_user"),
    "password": os.environ.get("PG_ETL_PASSWORD", ""),
}

# JWT authentication
JWT_SECRET_KEY     = os.environ.get("JWT_SECRET_KEY",     "change-me-in-production")
JWT_ALGORITHM      = os.environ.get("JWT_ALGORITHM",      "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# PII settings (author hash)
PII_HASH_SALT = os.environ.get("PII_HASH_SALT", "change-me-in-production")

# Source configuration (add a new source by adding an entry here)
# Each source contains:
#   name      -> display name written into the sources table
#   url       -> source homepage (also unique identifier in sources table)
#   num_pages -> pages per crawl (per-source pacing, controlled separately)
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
        # Subreddits are already finance-focused, no extra keyword filter needed.
        # 100 items per page, stop on consecutive duplicate pages.
        "num_pages":  1000,
    },
}

# Common crawler settings
MAX_RETRY       = 5
REQUEST_DELAY   = 0.3   # General request interval (seconds), prevents DDOS-style bans
TWSE_DELAY      = 3     # TWSE official rate limit: at least 3 seconds per request

# Database table names
ARTICLES_TABLE = "articles"
COMMENTS_TABLE = "comments"
SENTIMENT_SCORES_TABLE = "sentiment_scores"
SOURCES_TABLE = "sources"
STOCK_PRICES_TABLE    = "stock_prices"     # Tracked symbol: 0050 (Yuanta Taiwan 50); see schema.py
US_STOCK_PRICES_TABLE = "us_stock_prices"  # Tracked symbol: VOO (Vanguard S&P 500 ETF); see schema.py
ARTICLE_LABELS_TABLE  = "article_labels"   # Human-labeled sentiment (labeling_tool.py -> bert_sentiment.py fine-tune)

