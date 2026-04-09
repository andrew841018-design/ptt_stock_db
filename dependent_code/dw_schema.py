"""
Data Warehouse Schema（Star Schema + Snowflake 延伸）

Star Schema（核心）：
  fact_sentiment → dim_source / dim_stock

Snowflake 延伸（dim_source 多一層正規化）：
  dim_source → dim_market（TW / US 市場）
  好處：可直接按市場聚合，不需知道個別來源名稱
  代價：查詢需多一個 JOIN（dim_source JOIN dim_market）

- dim_market  : 市場維度（Snowflake 新增）
- dim_source  : 來源維度（FK → dim_market）
- dim_stock   : 股票維度（追蹤標的：0050、VOO）
- fact_sentiment : 每日每來源情緒聚合事實表
  └ source_name 直接 denormalize 進 fact（DW 讀多寫少，避免 JOIN）

Data Mart（獨立 table，非 Materialized View）：
- mart_daily_summary : 每日情緒摘要（儀表板用）
- mart_hot_stocks    : 熱門股票排行（API 用）
  
"""

import logging
import psycopg2
from config import PG_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── Dimension Tables ──────────────────────────────────────────────────────────

# Snowflake 延伸：dim_market 是 dim_source 的上層維度
CREATE_DIM_MARKET = """
CREATE TABLE IF NOT EXISTS dim_market (
    market_id   SERIAL      PRIMARY KEY,
    market_code VARCHAR(10) NOT NULL UNIQUE   -- 'TW' / 'US'
);
"""

CREATE_DIM_SOURCE = """
CREATE TABLE IF NOT EXISTS dim_source (
    source_id     INTEGER PRIMARY KEY,   -- 直接沿用 OLTP sources.source_id
    source_name   VARCHAR(100) NOT NULL,
    url           TEXT         NOT NULL,
    market_id     INTEGER      REFERENCES dim_market(market_id),  -- Snowflake FK
    tracked_stock VARCHAR(20)            -- 該來源追蹤的股票代號（0050 / VOO）
);
"""

CREATE_DIM_STOCK = """
CREATE TABLE IF NOT EXISTS dim_stock (
    stock_id    SERIAL       PRIMARY KEY,
    symbol      VARCHAR(20)  NOT NULL UNIQUE,
    name        VARCHAR(100) NOT NULL
);
"""

# ─── Fact Table ────────────────────────────────────────────────────────────────

CREATE_FACT_SENTIMENT = """
CREATE TABLE IF NOT EXISTS fact_sentiment (
    fact_id         SERIAL       PRIMARY KEY,
    fact_date       DATE         NOT NULL,
    source_id       INTEGER      NOT NULL REFERENCES dim_source(source_id),
    stock_symbol    VARCHAR(20),                     -- denormalized，直接存代號（0050 / VOO）
    source_name     VARCHAR(100) NOT NULL,           -- denormalized，避免查詢時 JOIN dim_source
    article_count   INTEGER      NOT NULL,
    avg_sentiment   NUMERIC(6,4),
    avg_push_count  NUMERIC(8,2),
    UNIQUE (fact_date, source_id)
);
"""

# ─── Indexes ───────────────────────────────────────────────────────────────────

CREATE_DW_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fact_date      ON fact_sentiment(fact_date);
CREATE INDEX IF NOT EXISTS idx_fact_source    ON fact_sentiment(source_id);
"""


# ─── Data Mart Tables ──────────────────────────────────────────────────────────
# Data Mart = DW 的子集，針對特定用途預先彙整，讓儀表板 / API 直接查表，
# 不用每次去掃 fact_sentiment + JOIN dim_date（大表的 aggregation 非常慢）。
# 與 Materialized View 差異：
#   MV：PostgreSQL 特有，由 REFRESH MATERIALIZED VIEW 更新
#   Mart：標準 table，由 ETL INSERT/TRUNCATE+INSERT 更新，可跨 DB 移植

CREATE_MART_DAILY_SUMMARY = """
CREATE TABLE IF NOT EXISTS mart_daily_summary (
    summary_date  DATE         NOT NULL,
    source_name   VARCHAR(100) NOT NULL,
    total_articles INTEGER     NOT NULL DEFAULT 0,
    avg_sentiment  NUMERIC(6,4),
    avg_push_count NUMERIC(8,2),
    PRIMARY KEY (summary_date, source_name)
);
"""

CREATE_MART_HOT_STOCKS = """
CREATE TABLE IF NOT EXISTS mart_hot_stocks (
    report_date   DATE         NOT NULL,
    source_name   VARCHAR(100) NOT NULL,
    push_count    INTEGER      NOT NULL DEFAULT 0,
    article_count INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (report_date, source_name)
);
"""

CREATE_MART_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_mart_daily_date
    ON mart_daily_summary(summary_date);
"""


def create_dw_schema() -> None:
    """建立 DW 所有資料表、Index 和 Materialized View"""
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            cur.execute(CREATE_DIM_MARKET)
            logging.info("dim_market created (or already exists)")
            cur.execute(CREATE_DIM_SOURCE)
            # 幂等補欄位：dim_source 已存在時加入 market_id FK
            cur.execute("""
                ALTER TABLE dim_source
                ADD COLUMN IF NOT EXISTS market_id INTEGER REFERENCES dim_market(market_id)
            """)
            logging.info("dim_source created (or already exists)")
            cur.execute(CREATE_DIM_STOCK)
            logging.info("dim_stock created (or already exists)")
            cur.execute(CREATE_FACT_SENTIMENT)
            logging.info("fact_sentiment created (or already exists)")
            cur.execute(CREATE_DW_INDEXES)
            logging.info("DW indexes created (or already exist)")
            # Data Mart tables
            cur.execute(CREATE_MART_DAILY_SUMMARY)
            logging.info("mart_daily_summary created (or already exists)")
            cur.execute(CREATE_MART_HOT_STOCKS)
            logging.info("mart_hot_stocks created (or already exists)")
            cur.execute(CREATE_MART_INDEXES)
            logging.info("Data Mart indexes created (or already exist)")
        conn.commit()
        logging.info("DW schema setup complete")
    except psycopg2.Error as e:
        logging.error("Failed to create DW schema: %s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
