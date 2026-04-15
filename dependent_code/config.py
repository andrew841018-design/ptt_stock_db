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

# JWT authentication
JWT_SECRET_KEY     = os.environ.get("JWT_SECRET_KEY",     "change-me-in-production")
JWT_ALGORITHM      = os.environ.get("JWT_ALGORITHM",      "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# PII settings (author hash)
PII_HASH_SALT = os.environ.get("PII_HASH_SALT", "change-me-in-production")

# Source configuration — 唯一 source of truth
#
# 新增來源只需在 SOURCES 加一筆 entry，其他模組全部從這裡衍生。
#
# 必填欄位：
#   name           -> sources 表的 source_name
#   url            -> sources 表的 url（唯一識別）
#   num_pages      -> 每次爬取的頁數上限
#   market         -> "TW" / "US"（決定對應哪個股價表、AI 模型、DW 維度）
#   lang           -> "zh" / "en"（決定標注工具的 UI 語言）
#   stock          -> 追蹤標的代號（"0050" / "VOO"）
#
# 選填欄位（有預設值）：
#   url_pattern    -> GE 驗證用的 URL regex（預設 None = 不做 URL 格式檢查）
#   has_push_count -> 是否有推文數（預設 False）
#   color          -> 視覺化圖表配色（預設自動分配）
#   page_size      -> 每頁筆數（來源特有，如 cnyes）
#   subreddits     -> Reddit 專用
#
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
        "url_pattern":    r"cnn\.com/",
        "color":          "#d62728",
    },
    "wsj": {
        "name":           "wsj",
        "url":            "https://www.wsj.com/news/markets",
        "num_pages":      10000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"wsj\.com/",
        "color":          "#9467bd",
    },
    "marketwatch": {
        "name":           "marketwatch",
        "url":            "https://www.marketwatch.com",
        "num_pages":      10000,
        "market":         "US",
        "lang":           "en",
        "stock":          "VOO",
        "url_pattern":    r"marketwatch\.com/",
        "color":          "#8c564b",
    },
}

# ─── 衍生 helpers（其他模組 import 這些，不要自己 hardcode 來源清單）─────────

def sources_by_market(market: str) -> list:
    """回傳指定市場的來源 name list。e.g. sources_by_market("TW") → ["ptt", "cnyes"]"""
    return [v["name"] for v in SOURCES.values() if v["market"] == market]

def sources_by_lang(lang: str) -> list:
    """回傳指定語言的來源 name list。e.g. sources_by_lang("en") → ["reddit", "cnn", ...]"""
    return [v["name"] for v in SOURCES.values() if v["lang"] == lang]

# dw_etl.py / stock_matcher.py 用：來源 → 市場 & 追蹤標的
SOURCE_META = {
    key: {"market": src["market"], "stock": src["stock"]}
    for key, src in SOURCES.items()
}

# visualization.py / ai_model_prediction.py 用：來源 → 市場碼
SOURCE_MARKET_MAP = {v["name"]: v["market"] for v in SOURCES.values()}

# plt_function.py 用：來源 → 圖表配色
SOURCE_COLORS = {v["name"]: v.get("color") for v in SOURCES.values() if v.get("color")}

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
AI_MODEL_PREDICTION_RUNS_TABLE = "ai_model_prediction_runs"  # Walk-Forward AI model prediction run history (model drift analysis)

