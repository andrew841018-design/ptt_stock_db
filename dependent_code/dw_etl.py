"""
Data Warehouse ETL：OLTP → Star Schema（incremental）

流程：
  1. populate_dim_market()     - 種入市場維度（TW / US）
  2. populate_dim_source()     - 從 OLTP sources 同步來源維度
  3. populate_dim_stock()      - 預設種入 0050 / VOO（幂等）
  4. populate_fact_sentiment() - 每日每來源情緒聚合，ON CONFLICT DO UPDATE（upsert）
  5. refresh_all()             - 刷新 Data Mart（mart_daily_summary）
  (市場層級聚合在 Step 5 透過 data_mart.refresh_mart_market_summary() 處理)

支援增量：每次只處理自上次 ETL 以來有新文章的日期（不全量重算）
"""

import logging
import psycopg2
from config import PG_CONFIG
from dw_schema import create_dw_schema
from data_mart import refresh_all, ensure_sp_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 來源屬性對應表：從 config.SOURCES 自動衍生，新增來源不需改這裡
from config import SOURCE_META


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
        ("TW", "台灣股市", "TWD", "Asia/Taipei"),
        ("US", "美國股市", "USD", "America/New_York"),
    ]
    cur.executemany("""
        INSERT INTO dim_market (market_code, market_name, currency, timezone)
        VALUES (%s, %s, %s, %s)
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

def populate_fact_sentiment(cur) -> None:
    """
    每日每來源情緒聚合 → fact_sentiment（upsert）
    呼叫 PostgreSQL Stored Procedure sp_populate_fact_sentiment()
    （定義於 scripts/init_marts.sql）。

    SP 內部邏輯：
      - 4 表 JOIN（articles + sources + dim_source + sentiment_scores）
      - GROUP BY 每日每來源聚合
      - ON CONFLICT UPSERT（增量更新）
      - source_name 直接 denormalize 進 fact，查詢時不需再 JOIN dim_source
    """
    cur.execute("CALL sp_populate_fact_sentiment()")
    logging.info("[DW ETL] fact_sentiment upserted via sp_populate_fact_sentiment()")


# Step 6（市場層級聚合）已合併進 data_mart.refresh_all() — 2026-05-07 MV → Mart 統一


# ─── CLUSTER（讓 fact 資料實體上按 date_id 排序，加速日期範圍查詢）─────────────

def cluster_fact(cur) -> None:
    """
    CLUSTER = 按指定 index 重新排列資料在磁碟上的物理順序。
    範圍查詢（WHERE fact_date BETWEEN x AND y）時連續讀取，不用跳來跳去。
    注意：會鎖表，排程在離峰時段執行。
    """
    cur.execute("CLUSTER fact_sentiment USING idx_fact_date")  # fact_date 上的 index
    logging.info("[DW ETL] fact_sentiment CLUSTERed on idx_fact_date")


# ─── Main ──────────────────────────────────────────────────────────────────────
# 完整流程：填維度 → 填事實 → 刷新 Data Mart → API 讀到最新資料

def run_etl(do_cluster: bool = False) -> None:
    create_dw_schema()                     # Step 0a：確保 DW 所有表存在（幂等）
    ensure_sp_schema()                     # Step 0b：套用 SP/Function 定義（幂等）
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            populate_dim_market(cur)   # Step 1：市場維度
            populate_dim_source(cur)   # Step 2：來源維度
            populate_dim_stock(cur)    # Step 3：股票維度
            populate_fact_sentiment(cur)  # Step 4：事實表（聚合 OLTP 資料）
        if do_cluster:
            with conn.cursor() as cur:
                cluster_fact(cur)
        conn.commit()
        refresh_all()                  # Step 5：刷新所有 Data Mart（daily + market）
        logging.info("[DW ETL] 完成")
    except psycopg2.Error as e:
        logging.error("[DW ETL] 失敗：%s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
