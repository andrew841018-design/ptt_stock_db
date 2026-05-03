"""
Data Warehouse ETL：OLTP → Star Schema（incremental）

流程：
  1. populate_dim_market()     - 種入市場維度（TW / US）
  2. populate_dim_source()     - 從 OLTP sources 同步來源維度
  3. populate_dim_stock()      - 預設種入 0050 / VOO（幂等）
  4. populate_fact()           - 每日每來源情緒聚合，ON CONFLICT DO UPDATE（upsert）
  5. refresh_all()             - 刷新 Data Mart（mart_daily_summary / mart_hot_stocks）
  6. refresh_mv()              - 刷新 Materialized View（mv_market_summary，市場層級聚合）

支援增量：每次只處理自上次 ETL 以來有新文章的日期（不全量重算）
"""

import logging
import psycopg2
from config import PG_CONFIG
from dw_schema import create_dw_schema
from data_mart import refresh_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 來源屬性對應表（populate_dim_source 用）
SOURCE_META: dict[str, dict] = {
    "ptt":    {"market": "TW", "stock": "0050"},
    "cnyes":  {"market": "TW", "stock": "0050"},
    "reddit": {"market": "US", "stock": "VOO"},
}


# ─── Step 0：dim_market（市場維度，Snowflake 最上層）─────────────────────────────
# dim = dimension（維度表），存描述性屬性，回答「是什麼」
# Star Schema 命名慣例：dim_ 前綴 = 維度表、fact_ 前綴 = 事實表

def populate_dim_market(cur) -> None:
    """
    種入市場維度（幂等）。
    populate = 把整張表的資料準備好（ETL 術語，比 insert 更高層級）。
    ON CONFLICT DO NOTHING = 已存在就跳過，不報錯（幂等設計，重複執行不會壞）。
    """
    markets = [
        ("TW",),
        ("US",),
    ]
    # dim_market is table,market_code is column
    cur.executemany("""
        INSERT INTO dim_market (market_code)
        VALUES (%s)
        ON CONFLICT (market_code) DO NOTHING
    """, markets)
    logging.info("[DW ETL] dim_market ready (%d markets)", len(markets))


# ─── Step 2：dim_source（來源維度）────────────────────────────────────────────
# 從 OLTP sources 表同步，額外填入 market_id（Snowflake FK，連結到 dim_market）

def populate_dim_source(cur) -> None:
    """從 OLTP sources 同步至 dim_source，同時填入 market_id 和 tracked_stock"""
    # market_code → market_id 的 lookup
    cur.execute("SELECT market_id, market_code FROM dim_market")
    market_map = {market_code: market_id for market_id, market_code in cur.fetchall()}

    # 取 OLTP sources 清單
    cur.execute("SELECT source_id, source_name, url FROM sources")
    sources = cur.fetchall()

    for source_id, source_name, url in sources:
        meta          = SOURCE_META.get(source_name, {})
        market_id     = market_map.get(meta.get("market", "TW"))
        tracked_stock = meta.get("stock")  # '0050' / 'VOO' / None
        cur.execute("""
            INSERT INTO dim_source (source_id, source_name, url, market_id, tracked_stock)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE
                SET source_name   = EXCLUDED.source_name,
                    url           = EXCLUDED.url,
                    market_id     = EXCLUDED.market_id,
                    tracked_stock = EXCLUDED.tracked_stock
        """, (source_id, source_name, url, market_id, tracked_stock))

    logging.info("[DW ETL] dim_source upserted: %d rows", len(sources))


# ─── Step 3：dim_stock（股票維度）─────────────────────────────────────────────

def populate_dim_stock(cur) -> None:
    """種入追蹤標的（幂等）"""
    stocks = [
        ("0050", "元大台灣50"),           # 台股 ETF
        ("VOO",  "Vanguard S&P 500 ETF"), # 美股 ETF
    ]
    cur.executemany("""
        INSERT INTO dim_stock (symbol, name)
        VALUES (%s, %s)
        ON CONFLICT (symbol) DO NOTHING  -- 已存在就跳過
    """, stocks)
    logging.info("[DW ETL] dim_stock ready (%d stocks)", len(stocks))


# ─── Step 4：fact_sentiment（事實表，Star Schema 的核心）───────────────────────
# fact = 事實表，存數值/度量（幾篇、幾分），透過 FK 指向各維度表
# 粒度：每日 × 每來源 = 一筆

def populate_fact(cur) -> None:
    """
    每日每來源情緒聚合 → fact_sentiment（upsert）

    聚合邏輯：
      - avg_sentiment  : 平均情緒分數（來自 sentiment_scores，可能部分文章尚未跑分）
      - avg_push_count : 平均推噓數
      - article_count  : 當日文章數
    source_name 直接 denormalize 進 fact，查詢時不需再 JOIN dim_source。
    """
    cur.execute("""
        INSERT INTO fact_sentiment
            (fact_date, source_id, stock_symbol, source_name, article_count, avg_sentiment, avg_push_count)
        SELECT
            a.published_at::DATE                            AS fact_date,
            a.source_id,
            ds.tracked_stock                                AS stock_symbol,   -- 從 dim_source 直接拿
            s.source_name,
            COUNT(a.article_id)                             AS article_count,
            AVG(ss.score)                                   AS avg_sentiment,
            AVG(a.push_count)                               AS avg_push_count
        FROM articles a
        JOIN sources s ON s.source_id = a.source_id
        JOIN dim_source ds ON ds.source_id = a.source_id   -- 拿 tracked_stock
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
                stock_symbol   = EXCLUDED.stock_symbol
    """)
    logging.info("[DW ETL] fact_sentiment upserted: %d rows", cur.rowcount)


# ─── Step 6：Materialized View 刷新 ────────────────────────────────────────────
# mv_market_summary 是 PostgreSQL 特有的 MV，第一次 CREATE 時用 `WITH NO DATA`
# 不填資料，由 ETL 跑完 fact 之後 REFRESH 一次性填滿。
# 與 Data Mart 的 TRUNCATE+INSERT 比，MV 的 REFRESH 是 PostgreSQL 內建原子操作。

def refresh_mv(cur) -> None:
    """刷新 mv_market_summary（市場層級聚合，利用 Snowflake 三表 JOIN）"""
    cur.execute("REFRESH MATERIALIZED VIEW mv_market_summary")
    logging.info("[DW ETL] mv_market_summary refreshed")


# ─── CLUSTER（讓 fact 資料實體上按 date_id 排序，加速日期範圍查詢）─────────────

def cluster_fact(cur) -> None:
    """
    CLUSTER = 按指定 index 重新排列資料在磁碟上的物理順序。
    範圍查詢（WHERE date_id BETWEEN x AND y）時連續讀取，不用跳來跳去。
    注意：會鎖表，排程在離峰時段執行。
    """
    cur.execute("CLUSTER fact_sentiment USING idx_fact_date")  # fact_date 上的 index
    logging.info("[DW ETL] fact_sentiment CLUSTERed on idx_fact_date")


# ─── Main ──────────────────────────────────────────────────────────────────────
# 完整流程：填維度 → 填事實 → 刷新 Data Mart → API 讀到最新資料

def run_etl(do_cluster: bool = False) -> None:
    create_dw_schema()                     # Step 0：確保 DW 所有表存在（幂等）
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            populate_dim_market(cur)   # Step 1：市場維度
            populate_dim_source(cur)   # Step 2：來源維度
            populate_dim_stock(cur)    # Step 3：股票維度
            populate_fact(cur)         # Step 4：事實表（聚合 OLTP 資料）
        if do_cluster:
            with conn.cursor() as cur:
                cluster_fact(cur)
        conn.commit()
        refresh_all()                  # Step 5：刷新 Data Mart（mart_daily_summary + mart_hot_stocks）
        # Step 6：刷新 Materialized View（需要自己的 connection，REFRESH 不能在剛 rollback 的 cursor 上跑）
        with psycopg2.connect(**PG_CONFIG) as mv_conn:
            with mv_conn.cursor() as mv_cur:
                refresh_mv(mv_cur)
            mv_conn.commit()
        logging.info("[DW ETL] 完成")
    except psycopg2.Error as e:
        logging.error("[DW ETL] 失敗：%s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
