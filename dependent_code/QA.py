import logging
from pg_helper import get_pg
from config import ARTICLES_TABLE, COMMENTS_TABLE


def QA_checks():
    with get_pg() as conn:
        with conn.cursor() as cursor:
            # 檢查重複 URL
            cursor.execute(f"SELECT url, COUNT(*) FROM {ARTICLES_TABLE} GROUP BY url HAVING COUNT(*) > 1")
            duplicate_urls = cursor.fetchall()
            if duplicate_urls:
                raise ValueError(f"QA FAILED：發現重複 URL，共 {len(duplicate_urls)} 筆：{duplicate_urls}")
            logging.info("QA PASSED：無重複 URL")

            # 檢查孤兒推文（FK 沒對應到文章）
            cursor.execute(f"SELECT COUNT(*) FROM {COMMENTS_TABLE} WHERE article_id NOT IN (SELECT article_id FROM {ARTICLES_TABLE})")
            orphan_count = cursor.fetchone()[0]
            if orphan_count > 0:
                raise ValueError(f"QA FAILED：孤兒推文 {orphan_count} 筆")
            logging.info("QA PASSED：無孤兒推文")

            # 檢查文章數量不為零
            cursor.execute(f"SELECT COUNT(*) FROM {ARTICLES_TABLE}")
            article_count = cursor.fetchone()[0]
            if article_count == 0:
                raise ValueError(f"QA FAILED：{ARTICLES_TABLE} 表是空的")
            logging.info(f"QA PASSED：{ARTICLES_TABLE} 共 {article_count} 筆")

    logging.info("QA 全部通過")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    QA_checks()
