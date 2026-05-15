import os
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

_PG_BASE = {
    "host":   os.environ.get("PG_HOST",   "localhost"),
    "port":   int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DBNAME", "ptt_stock"),
}

PG_ADMIN_CONFIG = {**_PG_BASE, "user": os.environ.get("PG_ADMIN_USER", "postgres"),  "password": os.environ.get("PG_ADMIN_PASSWORD", "")}
PG_CONFIG       = {**_PG_BASE, "user": os.environ.get("PG_USER",       "etl_user"),  "password": os.environ.get("PG_PASSWORD",       "etl_write_2026")}
PG_API_CONFIG   = {**_PG_BASE, "user": os.environ.get("PG_API_USER",   "api_user"),  "password": os.environ.get("PG_API_PASSWORD",   "")}

JWT_SECRET_KEY     = os.environ.get("JWT_SECRET_KEY",     "change-me-in-production")
JWT_ALGORITHM      = os.environ.get("JWT_ALGORITHM",      "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

PII_HASH_SALT = os.environ.get("PII_HASH_SALT", "change-me-in-production")

if os.environ.get("ENV", "").lower() == "production":
    if JWT_SECRET_KEY == "change-me-in-production":
        raise RuntimeError("ENV=production 但 JWT_SECRET_KEY 未設定（仍是 placeholder）— 拒絕啟動以防 token 偽造")
    if PII_HASH_SALT == "change-me-in-production":
        raise RuntimeError("ENV=production 但 PII_HASH_SALT 未設定（仍是 placeholder）— 拒絕啟動以防 hash 預先映射攻擊")

SOURCES = {
    "ptt": {
        "name":           "ptt",
        "url":            "https://www.ptt.cc/bbs/Stock",
        "num_pages":      10000,
        "market":         "TW",
        "lang":           "zh",
        "stock":          "0050",
        "url_pattern":    r"/bbs/[Ss]tock/.*",
        "has_push_count": True,
        "color":          "#1f77b4",
    },
    "cnyes": {
        "name":           "cnyes",
        "url":            "https://news.cnyes.com/news/cat/tw_stock",
        "categories":     ["tw_stock", "wd_stock", "headline", "us_stock", "future", "forex"],
        "num_pages":      1000,
        "page_size":      30,
        "market":         "TW",
        "lang":           "zh",
        "stock":          "0050",
        "url_pattern":    r"news\.cnyes\.com/news/id/\d+",
        "color":          "#ff7f0e",
    },
    "reddit": {
        "name":           "reddit",
        "url":            "https://www.reddit.com/r/investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        "subreddits":     "investing+stocks+wallstreetbets+Bogleheads+personalfinance+financialindependence",
        "num_pages":      1000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"reddit\.com/r/\w+/comments/",
        "has_push_count": True,
        "color":          "#2ca02c",
    },
    "cnn": {
        "name":           "cnn",
        "url":            "https://edition.cnn.com/business",
        "num_pages":      10000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"(cnn\.com/|news\.google\.com/rss/articles/)",
        "color":          "#d62728",
    },
    "wsj": {
        "name":           "wsj",
        "url":            "https://www.wsj.com/news/markets",
        "num_pages":      10000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"(wsj\.com/|news\.google\.com/rss/articles/)",
        "color":          "#9467bd",
    },
    "marketwatch": {
        "name":           "marketwatch",
        "url":            "https://www.marketwatch.com",
        "num_pages":      10000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"(marketwatch\.com/|news\.google\.com/rss/articles/)",
        "color":          "#8c564b",
    },
}


def sources_by_market(market: str) -> list:
    return [v["name"] for v in SOURCES.values() if v["market"] == market]

def sources_by_lang(lang: str) -> list:
    return [v["name"] for v in SOURCES.values() if v["lang"] == lang]

SOURCE_META = {
    key: {"market": src["market"], "stock": src["stock"]}
    for key, src in SOURCES.items()
}
SOURCE_META["wayback_cnn"] = {"market": "US", "stock": "VOO"}
SOURCE_META["wayback_wsj"] = {"market": "US", "stock": "VOO"}

SOURCE_COLORS = {v["name"]: v.get("color") for v in SOURCES.values() if v.get("color")}

MAX_RETRY       = 5
REQUEST_DELAY   = 0.3
TWSE_DELAY      = 3
EARLY_STOP_EMPTY_PAGES = 3

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

ARTICLES_TABLE = "articles"
COMMENTS_TABLE = "comments"
SENTIMENT_SCORES_TABLE = "sentiment_scores"
SOURCES_TABLE = "sources"
STOCK_PRICES_TABLE    = "stock_prices"
US_STOCK_PRICES_TABLE = "us_stock_prices"
ARTICLE_LABELS_TABLE  = "article_labels"
AI_MODEL_PREDICTION_RUNS_TABLE = "ai_model_prediction_runs"

