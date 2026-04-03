import logging
from pg_helper import get_pg
from config import ARTICLES_TABLE, COMMENTS_TABLE, SENTIMENT_SCORES_TABLE, STOCK_PRICES_TABLE, SOURCES_TABLE, SOURCES


def QA_checks():
    with get_pg() as conn:
        with conn.cursor() as cursor:

            # ── sources ───────────────────────────────────────────────────
            cursor.execute(f"SELECT COUNT(*) FROM {SOURCES_TABLE}")
            source_count = cursor.fetchone()[0]
            if source_count == 0:
                raise ValueError("QA FAILED：sources 表是空的")
            logging.info(f"QA PASSED：sources 共 {source_count} 筆")

            # ── articles ──────────────────────────────────────────────────
            cursor.execute(f"SELECT COUNT(*) FROM {ARTICLES_TABLE}")
            article_count = cursor.fetchone()[0]
            if article_count == 0:
                raise ValueError(f"QA FAILED：{ARTICLES_TABLE} 表是空的")
            logging.info(f"QA PASSED：articles 共 {article_count} 筆")

            cursor.execute(f"SELECT url, COUNT(*) FROM {ARTICLES_TABLE} GROUP BY url HAVING COUNT(*) > 1")
            duplicate_urls = cursor.fetchall()
            if duplicate_urls:
                raise ValueError(f"QA FAILED：發現重複 URL，共 {len(duplicate_urls)} 筆：{duplicate_urls}")
            logging.info("QA PASSED：無重複 URL")

            # 不允許 NULL 的欄位
            for col in ("title", "content", "url", "published_at"):
                cursor.execute(f"SELECT COUNT(*) FROM {ARTICLES_TABLE} WHERE {col} IS NULL")
                null_count = cursor.fetchone()[0]
                if null_count > 0:
                    raise ValueError(f"QA FAILED：articles.{col} 有 {null_count} 筆 NULL")
            logging.info("QA PASSED：articles 必填欄位無 NULL")

            # 來源專屬檢查
            cursor.execute(f"""
                SELECT COUNT(*) FROM {ARTICLES_TABLE} a
                JOIN {SOURCES_TABLE} s ON s.source_id = a.source_id
                WHERE s.source_name = %s AND a.push_count IS NULL
            """, (SOURCES["ptt"]["name"],))
            ptt_null_push = cursor.fetchone()[0]
            if ptt_null_push > 0:
                raise ValueError(f"QA FAILED：PTT 文章 push_count 有 {ptt_null_push} 筆 NULL")
            logging.info("QA PASSED：PTT push_count 無 NULL")

            # ── comments ──────────────────────────────────────────────────
            cursor.execute(f"""
                SELECT COUNT(*) FROM {COMMENTS_TABLE}
                WHERE article_id NOT IN (SELECT article_id FROM {ARTICLES_TABLE})
            """)
            orphan_count = cursor.fetchone()[0]
            if orphan_count > 0:
                raise ValueError(f"QA FAILED：孤兒推文 {orphan_count} 筆")
            logging.info("QA PASSED：無孤兒推文")

            for col in ("user_id", "push_tag", "message"):
                cursor.execute(f"SELECT COUNT(*) FROM {COMMENTS_TABLE} WHERE {col} IS NULL")
                null_count = cursor.fetchone()[0]
                if null_count > 0:
                    raise ValueError(f"QA FAILED：comments.{col} 有 {null_count} 筆 NULL")
            logging.info("QA PASSED：comments 必填欄位無 NULL")

            # ── sentiment_scores ──────────────────────────────────────────
            cursor.execute(f"""
                SELECT COUNT(*) FROM {SENTIMENT_SCORES_TABLE}
                WHERE article_id NOT IN (SELECT article_id FROM {ARTICLES_TABLE})
            """)
            orphan_scores = cursor.fetchone()[0]
            if orphan_scores > 0:
                raise ValueError(f"QA FAILED：孤兒情緒分數 {orphan_scores} 筆")
            logging.info("QA PASSED：無孤兒情緒分數")

            cursor.execute(f"SELECT COUNT(*) FROM {SENTIMENT_SCORES_TABLE} WHERE score IS NULL")
            null_scores = cursor.fetchone()[0]
            if null_scores > 0:
                raise ValueError(f"QA FAILED：sentiment_scores.score 有 {null_scores} 筆 NULL")
            logging.info("QA PASSED：sentiment_scores 必填欄位無 NULL")

            # ── stock_prices ──────────────────────────────────────────────
            cursor.execute(f"SELECT COUNT(*) FROM {STOCK_PRICES_TABLE}")
            price_count = cursor.fetchone()[0]
            if price_count == 0:
                raise ValueError(f"QA FAILED：{STOCK_PRICES_TABLE} 表是空的")
            logging.info(f"QA PASSED：stock_prices 共 {price_count} 筆")

            for col in ("trade_date", "close"):
                cursor.execute(f"SELECT COUNT(*) FROM {STOCK_PRICES_TABLE} WHERE {col} IS NULL")
                null_count = cursor.fetchone()[0]
                if null_count > 0:
                    raise ValueError(f"QA FAILED：stock_prices.{col} 有 {null_count} 筆 NULL")
            logging.info("QA PASSED：stock_prices 必填欄位無 NULL")

    logging.info("QA 全部通過")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    QA_checks()
