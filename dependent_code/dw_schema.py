
import logging
import psycopg2
from config import PG_ADMIN_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


CREATE_DIM_MARKET = """
CREATE TABLE IF NOT EXISTS dim_market (
    market_id   SERIAL      PRIMARY KEY,
    market_code VARCHAR(10) NOT NULL UNIQUE,  -- 'TW' / 'US'
    market_name VARCHAR(50),
    currency    VARCHAR(10),
    timezone    VARCHAR(50)
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


CREATE_FACT_SENTIMENT = """
CREATE TABLE IF NOT EXISTS fact_sentiment (
    fact_id          SERIAL       PRIMARY KEY,
    fact_date        DATE         NOT NULL,
    source_id        INTEGER      NOT NULL REFERENCES dim_source(source_id),
    stock_symbol     VARCHAR(20),                     -- denormalized，直接存代號（0050 / VOO）
    source_name      VARCHAR(100) NOT NULL,           -- denormalized，避免查詢時 JOIN dim_source
    article_count    INTEGER      NOT NULL,           -- 該 (date, source) 總文章數（含未 scored，dashboard 直觀顯示）
    scored_articles  INTEGER      NOT NULL DEFAULT 0, -- 已被 BERT scored 的文章數，用於加權平均（避免 wayback BERT 落後期間 article_count 失真）
    avg_sentiment    NUMERIC(6,4),
    avg_push_count   NUMERIC(8,2),
    UNIQUE (fact_date, source_id)
);
"""


CREATE_DW_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fact_date      ON fact_sentiment(fact_date);
CREATE INDEX IF NOT EXISTS idx_fact_source    ON fact_sentiment(source_id);
"""



CREATE_MART_DAILY_SUMMARY = """
CREATE TABLE IF NOT EXISTS mart_daily_summary (
    summary_date    DATE         NOT NULL,
    source_name     VARCHAR(100) NOT NULL,
    total_articles  INTEGER      NOT NULL DEFAULT 0,  -- dashboard 顯示「篇數」
    scored_articles INTEGER      NOT NULL DEFAULT 0,  -- 加權平均的真實 weight
    avg_sentiment   NUMERIC(6,4),
    avg_push_count  NUMERIC(8,2),
    PRIMARY KEY (summary_date, source_name)
);
"""

CREATE_MART_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_mart_daily_date
    ON mart_daily_summary(summary_date);
"""



CREATE_MART_MARKET_SUMMARY = """
CREATE TABLE IF NOT EXISTS mart_market_summary (
    fact_date       DATE NOT NULL,
    market_code     VARCHAR(10) NOT NULL,
    source_count    INTEGER,
    total_articles  BIGINT,                           -- dashboard 顯示「篇數」
    scored_articles BIGINT,                           -- 加權平均的真實 weight
    avg_sentiment   NUMERIC(5,4),
    avg_push_count  NUMERIC(8,2),
    PRIMARY KEY (fact_date, market_code)
);
"""

CREATE_MART_MARKET_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_mart_market_date
    ON mart_market_summary(fact_date);
"""




def create_dw_schema() -> None:
    conn = None
    try:
        conn = psycopg2.connect(**PG_ADMIN_CONFIG)
        with conn.cursor() as cur:
            cur.execute(CREATE_DIM_MARKET)
            cur.execute("""
                ALTER TABLE dim_market
                ADD COLUMN IF NOT EXISTS market_name VARCHAR(50) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS currency VARCHAR(10) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) NOT NULL DEFAULT ''
            """)
            logging.info("dim_market created (or already exists)")
            cur.execute(CREATE_DIM_SOURCE)
            cur.execute("""
                ALTER TABLE dim_source
                ADD COLUMN IF NOT EXISTS market_id INTEGER REFERENCES dim_market(market_id)
            """)
            logging.info("dim_source created (or already exists)")
            cur.execute(CREATE_DIM_STOCK)
            logging.info("dim_stock created (or already exists)")
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='fact_sentiment'
                               AND column_name='avg_score') THEN
                        DROP TABLE fact_sentiment;
                    END IF;
                END $$;
            """)
            cur.execute(CREATE_FACT_SENTIMENT)
            cur.execute("""
                ALTER TABLE fact_sentiment
                ADD COLUMN IF NOT EXISTS scored_articles INTEGER NOT NULL DEFAULT 0
            """)
            logging.info("fact_sentiment created (or already exists)")
            cur.execute(CREATE_DW_INDEXES)
            logging.info("DW indexes created (or already exist)")
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_name='mart_daily_summary')
                       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                                       WHERE table_name='mart_daily_summary'
                                       AND column_name='summary_date') THEN
                        DROP TABLE mart_daily_summary;
                    END IF;
                END $$;
            """)
            cur.execute(CREATE_MART_DAILY_SUMMARY)
            cur.execute("""
                ALTER TABLE mart_daily_summary
                ADD COLUMN IF NOT EXISTS total_articles INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS scored_articles INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS avg_sentiment NUMERIC(6,4),
                ADD COLUMN IF NOT EXISTS avg_push_count NUMERIC(8,2)
            """)
            logging.info("mart_daily_summary created (or already exists)")
            cur.execute(CREATE_MART_INDEXES)
            logging.info("Data Mart indexes created (or already exist)")
            cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_market_summary CASCADE")
            cur.execute(CREATE_MART_MARKET_SUMMARY)
            cur.execute("""
                ALTER TABLE mart_market_summary
                ADD COLUMN IF NOT EXISTS scored_articles BIGINT
            """)
            logging.info("mart_market_summary created (or already exists)")
            cur.execute(CREATE_MART_MARKET_INDEXES)
            logging.info("mart_market_summary indexes created (or already exist)")

            cur.execute("""
                ALTER TABLE dim_source
                ADD COLUMN IF NOT EXISTS tracked_stock VARCHAR(20)
            """)
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
