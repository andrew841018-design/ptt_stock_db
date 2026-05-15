
import logging
import psycopg2
from config import PG_CONFIG
from dw_schema import create_dw_schema
from data_mart import refresh_all, ensure_sp_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from config import SOURCE_META



def populate_dim_market(cur) -> None:
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



def populate_dim_source(cur) -> None:
    cur.execute("SELECT market_id, market_code FROM dim_market")
    market_map = {market_code: market_id for market_id, market_code in cur.fetchall()}

    cur.execute("SELECT source_id, source_name, url FROM sources")
    sources = cur.fetchall()

    for source_id, source_name, url in sources:
        meta          = SOURCE_META.get(source_name, {})
        market_id     = market_map.get(meta.get("market", "TW"))
        tracked_stock = meta.get("stock")
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



def populate_dim_stock(cur) -> None:
    stocks = [
        ("0050", "元大台灣50"),
        ("VOO",  "Vanguard S&P 500 ETF"),
    ]
    cur.executemany("""
        INSERT INTO dim_stock (symbol, name)
        VALUES (%s, %s)
        ON CONFLICT (symbol) DO NOTHING  -- 已存在就跳過
    """, stocks)
    logging.info("[DW ETL] dim_stock ready (%d stocks)", len(stocks))



def populate_fact_sentiment(cur) -> None:
    cur.execute("CALL sp_populate_fact_sentiment()")
    logging.info("[DW ETL] fact_sentiment upserted via sp_populate_fact_sentiment()")





def cluster_fact(cur) -> None:
    cur.execute("CLUSTER fact_sentiment USING idx_fact_date")
    logging.info("[DW ETL] fact_sentiment CLUSTERed on idx_fact_date")



def run_etl(do_cluster: bool = False) -> None:
    create_dw_schema()
    ensure_sp_schema()
    conn = None
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn.cursor() as cur:
            populate_dim_market(cur)
            populate_dim_source(cur)
            populate_dim_stock(cur)
            populate_fact_sentiment(cur)
        if do_cluster:
            with conn.cursor() as cur:
                cluster_fact(cur)
        conn.commit()
        refresh_all()
        logging.info("[DW ETL] 完成")
    except psycopg2.Error as e:
        logging.error("[DW ETL] 失敗：%s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
