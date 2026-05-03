"""
PostgreSQL Schema 建立腳本
執行方式：python scripts/schema.py
"""

import os
import logging
import psycopg2
from dotenv import load_dotenv
from config import PG_CONFIG, ARTICLE_LABELS_TABLE

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

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
    author     VARCHAR(100) NOT NULL,
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

CREATE_LABEL_TABLE = """
CREATE TABLE IF NOT EXISTS article_labels (
    label_id   SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES articles(article_id) UNIQUE,
    label      VARCHAR(10)  NOT NULL CHECK (label IN ('positive', 'neutral', 'negative')),
    labeled_at TIMESTAMP    DEFAULT NOW()
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


CREATE_ROLES = """
-- DO $$ ... END $$：PostgreSQL 匿名程式區塊，讓 SQL 可以用 IF/THEN 邏輯
DO $$
BEGIN
    -- API 唯讀角色（FastAPI 用，只有 SELECT）
    -- pg_roles：PostgreSQL 內建系統表，存放所有角色資訊
    -- IF NOT EXISTS：角色不存在才建，避免重複執行報錯
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{api_user}') THEN
        -- CREATE ROLE：建立 DB 帳號；LOGIN：允許此帳號連線登入
        CREATE ROLE {api_user} LOGIN PASSWORD '{api_pw}';
    END IF;

    -- ETL 讀寫角色（Pipeline 用，有 INSERT/UPDATE/DELETE）
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{etl_user}') THEN
        CREATE ROLE {etl_user} LOGIN PASSWORD '{etl_pw}';
    END IF;
END $$;

-- ── API 唯讀：CONNECT + USAGE + SELECT 成對授權 ──
GRANT CONNECT ON DATABASE {dbname} TO {api_user};           -- 允許連線到此 database
GRANT USAGE ON SCHEMA public TO {api_user};                 -- 允許看到 table（與 SELECT 成對，缺一不可）
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {api_user};  -- 允許讀 table 資料（與 USAGE 成對，缺一不可）
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {api_user};  -- 未來新建的 table 也自動授權

-- ── ETL 讀寫：CONNECT + USAGE + CRUD + SEQUENCE 成對授權 ──
GRANT CONNECT ON DATABASE {dbname} TO {etl_user};
GRANT USAGE ON SCHEMA public TO {etl_user};                 -- 與下行成對
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {etl_user};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {etl_user};  -- SERIAL 自動遞增需要，USAGE + SELECT 成對
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {etl_user};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {etl_user};

-- 防禦性 REVOKE：明確收回 API 的寫入權限，防止未來有人誤下 GRANT ALL
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM {api_user};
"""


def create_schema() -> None:
    """建立 PostgreSQL 所有資料表、Index 與角色權限"""
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES)
            logging.info("Tables created (or already exist)")
            cur.execute(CREATE_LABEL_TABLE)
            logging.info("%s table created (or already exists)", ARTICLE_LABELS_TABLE)
            cur.execute(CREATE_STOCK_PRICES)
            logging.info("stock_prices table created (or already exists)")
            cur.execute(CREATE_INDEXES)
            logging.info("Indexes created (or already exist)")

            # 建立 DB 角色（GRANT / REVOKE）
            api_user = os.environ.get("PG_API_USER",      "api_user")
            api_pw   = os.environ.get("PG_API_PASSWORD",  "api_readonly_2026")
            etl_user = os.environ.get("PG_ETL_USER",      "etl_user")
            etl_pw   = os.environ.get("PG_ETL_PASSWORD",  "etl_write_2026")
            dbname   = os.environ.get("PG_DBNAME",      "stock_analysis_db")

            cur.execute(CREATE_ROLES.format(
                api_user=api_user, api_pw=api_pw,
                etl_user=etl_user, etl_pw=etl_pw,
                dbname=dbname,
            ))
            logging.info("Roles created: %s (readonly), %s (readwrite)", api_user, etl_user)

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
