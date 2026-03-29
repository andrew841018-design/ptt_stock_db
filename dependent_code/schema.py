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
    title        TEXT,
    push_count   INTEGER      DEFAULT 0,
    author       VARCHAR(100),
    url          TEXT         UNIQUE,
    content      TEXT,
    published_at TIMESTAMP,
    scraped_at   TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES articles(article_id),
    user_id    VARCHAR(100),
    push_tag   VARCHAR(10),
    message    TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    score_id      SERIAL PRIMARY KEY,
    target_type   VARCHAR(10) NOT NULL CHECK (target_type IN ('article', 'comment')),
    target_id     INTEGER     NOT NULL,
    method        VARCHAR(50) NOT NULL,
    score         REAL        NOT NULL,
    calculated_at TIMESTAMP   DEFAULT NOW(),
    UNIQUE (target_type, target_id, method)
);
"""

# ─── DDL：建 Index ─────────────────────────────────────────────────────────────
CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source_id    ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_comments_article_id   ON comments(article_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_target      ON sentiment_scores(target_type, target_id);
"""


def create_schema() -> None:
    """建立 PostgreSQL 所有資料表與 Index"""
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES)
            logging.info("Tables created (or already exist)")
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
