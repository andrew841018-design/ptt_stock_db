"""
PostgreSQL Schema 建立腳本
執行方式：python scripts/schema.py
"""

import logging
import psycopg2
from config import PG_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── DDL：建表語法 ─────────────────────────────────────────────────────────────
CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sources (
    source_id   SERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    url         TEXT         NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS articles (
    article_id   SERIAL PRIMARY KEY,
    source_id    INTEGER      NOT NULL REFERENCES sources(source_id),
    title        TEXT         NOT NULL,
    push_count   INTEGER,
    author       VARCHAR(100),
    url          TEXT         NOT NULL UNIQUE,
    content      TEXT         NOT NULL,
    published_at TIMESTAMP    NOT NULL,
    scraped_at   TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES articles(article_id),
    user_id    VARCHAR(100) NOT NULL,
    push_tag   VARCHAR(10)  NOT NULL,
    message    TEXT         NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    score_id      SERIAL PRIMARY KEY,
    article_id    INTEGER NOT NULL REFERENCES articles(article_id),
    score         REAL    NOT NULL,
    calculated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (article_id)
);
"""

CREATE_STOCK_PRICES = """
-- 追蹤標的：0050（元大台灣50）
CREATE TABLE IF NOT EXISTS stock_prices (
    price_id   SERIAL  PRIMARY KEY,
    trade_date DATE         NOT NULL UNIQUE,
    close      NUMERIC(10,2),
    change     NUMERIC(10,2)
);

-- 追蹤標的：VOO（Vanguard S&P 500 ETF）
CREATE TABLE IF NOT EXISTS us_stock_prices (
    price_id   SERIAL PRIMARY KEY,
    trade_date DATE         NOT NULL UNIQUE,
    close      NUMERIC(10,2),
    change     NUMERIC(10,2)
);
"""

# ─── DDL：建 Index ─────────────────────────────────────────────────────────────
CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_articles_published_at    ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source_id       ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_comments_article_id      ON comments(article_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_article_id     ON sentiment_scores(article_id);
CREATE INDEX IF NOT EXISTS idx_stock_prices_trade_date  ON stock_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_us_stock_prices_trade_date ON us_stock_prices(trade_date);
"""


def create_schema() -> None:
    """建立 PostgreSQL 所有資料表與 Index"""
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES)
            logging.info("Tables created (or already exist)")
            cur.execute(CREATE_STOCK_PRICES)
            logging.info("stock_prices table created (or already exists)")
            cur.execute(CREATE_INDEXES)
            logging.info("Indexes created (or already exist)")
        conn.commit()
        logging.info("Schema setup complete")
    except psycopg2.Error as e:
        logging.error("Failed to create schema: %s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    create_schema()
