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

Data Mart（獨立 table，ETL TRUNCATE+INSERT 更新）：
- mart_daily_summary : 每日情緒摘要（儀表板用，source 粒度）

Materialized View（PostgreSQL 特有，REFRESH MATERIALIZED VIEW 更新）：
- mv_market_summary  : 市場層級聚合（TW vs US），示範 Snowflake 三表 JOIN
  └ 與 Data Mart 互補：Mart 是 source 粒度，MV 是 market 粒度
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

CREATE_MART_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_mart_daily_date
    ON mart_daily_summary(summary_date);
"""


# ─── Materialized View ─────────────────────────────────────────────────────────
# mv_market_summary：市場層級聚合（TW vs US）
#   - 展示 Snowflake schema 三表 JOIN（fact → dim_source → dim_market）
#   - 與 Data Mart 互補：Mart 是 source 粒度，MV 是 market 粒度
#   - CREATE 時自動填入資料；後續由 dw_etl.py 的 REFRESH MATERIALIZED VIEW 更新

CREATE_MV_MARKET_SUMMARY = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_market_summary AS
SELECT
    fs.fact_date,
    dm.market_code,
    COUNT(DISTINCT ds.source_id)  AS source_count,
    SUM(fs.article_count)         AS total_articles,
    AVG(fs.avg_sentiment)         AS avg_sentiment,
    AVG(fs.avg_push_count)        AS avg_push_count
FROM fact_sentiment fs
JOIN dim_source ds ON ds.source_id = fs.source_id
JOIN dim_market dm ON dm.market_id = ds.market_id
GROUP BY fs.fact_date, dm.market_code
WITH NO DATA;
"""

# REFRESH 前需要 UNIQUE index 才能用 CONCURRENTLY（目前先不用，但索引保留讓查詢更快）
CREATE_MV_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_market_summary_unique
    ON mv_market_summary(fact_date, market_code);
"""


# ─── Stored Procedures / Functions ────────────────────────────────────────────
# PROCEDURE：不回傳值，封裝資料操作（TRUNCATE + INSERT、UPSERT）
# FUNCTION ：回傳 TABLE，封裝複雜查詢邏輯
# 好處：SQL 邏輯留在 DB 端，Python 只負責 CALL / SELECT
# 缺點：版控不如 Python 直觀、跨 DB 不可移植、除錯較難
# CREATE OR REPLACE：幂等，重複執行只會覆蓋舊版本

CREATE_STORED_PROCEDURES = """
-- ── SP 1：刷新每日情緒摘要（TRUNCATE + INSERT FROM fact_sentiment）──
CREATE OR REPLACE PROCEDURE sp_refresh_mart_daily_summary()
LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE mart_daily_summary;
    INSERT INTO mart_daily_summary
        (summary_date, source_name, total_articles, avg_sentiment, avg_push_count)
    SELECT
        f.fact_date              AS summary_date,
        f.source_name,
        SUM(f.article_count)     AS total_articles,
        AVG(f.avg_sentiment)     AS avg_sentiment,
        AVG(f.avg_push_count)    AS avg_push_count
    FROM fact_sentiment f
    GROUP BY f.fact_date, f.source_name;
END;
$$;

-- ── SP 2：填充事實表（4 表 JOIN + UPSERT，ETL 核心邏輯）──
CREATE OR REPLACE PROCEDURE sp_populate_fact()
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO fact_sentiment
        (fact_date, source_id, stock_symbol, source_name,
         article_count, avg_sentiment, avg_push_count)
    SELECT
        a.published_at::DATE                AS fact_date,
        a.source_id,
        ds.tracked_stock                    AS stock_symbol,
        s.source_name,
        COUNT(a.article_id)                 AS article_count,
        AVG(ss.score)                       AS avg_sentiment,
        AVG(a.push_count)                   AS avg_push_count
    FROM articles a
    JOIN sources s          ON s.source_id  = a.source_id
    JOIN dim_source ds      ON ds.source_id = a.source_id
    LEFT JOIN sentiment_scores ss ON ss.article_id = a.article_id
    GROUP BY
        a.published_at::DATE,
        a.source_id,
        ds.tracked_stock,
        s.source_name
    ON CONFLICT (fact_date, source_id) DO UPDATE
        SET article_count  = EXCLUDED.article_count,
            avg_sentiment  = EXCLUDED.avg_sentiment,
            avg_push_count = EXCLUDED.avg_push_count,
            stock_symbol   = EXCLUDED.stock_symbol;
END;
$$;

-- ── FN 1：取近 N 天加權平均情緒（FUNCTION 回傳 TABLE）──
-- 多來源用 total_articles 做加權，避免「平均的平均」失準
-- 用法：SELECT * FROM fn_get_daily_sentiment(30)
CREATE OR REPLACE FUNCTION fn_get_daily_sentiment(p_days INTEGER)
RETURNS TABLE (
    summary_date   DATE,
    total_articles BIGINT,
    avg_sentiment  NUMERIC
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.summary_date,
        SUM(m.total_articles)::BIGINT                       AS total_articles,
        SUM(m.avg_sentiment * m.total_articles)
            / NULLIF(SUM(m.total_articles), 0)              AS avg_sentiment
    FROM mart_daily_summary m
    # || ' days' 是 PostgreSQL 的字串拼接語法，將 p_days 轉換為字串並拼接 ' days'
    WHERE m.summary_date >= CURRENT_DATE - (p_days || ' days')::INTERVAL
      AND m.avg_sentiment IS NOT NULL
    GROUP BY m.summary_date
    ORDER BY m.summary_date DESC;
END;
$$;
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
            cur.execute(CREATE_MART_INDEXES)
            logging.info("Data Mart indexes created (or already exist)")
            # Materialized View（Snowflake 三表 JOIN 的市場層級聚合）
            cur.execute(CREATE_MV_MARKET_SUMMARY)
            logging.info("mv_market_summary created (or already exists)")
            cur.execute(CREATE_MV_INDEXES)
            logging.info("MV indexes created (or already exist)")
            # Stored Procedures / Functions
            cur.execute(CREATE_STORED_PROCEDURES)
            logging.info("Stored Procedures / Functions created (or replaced)")
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
