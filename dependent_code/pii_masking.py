
import hashlib
import logging
from typing import Optional
from config import PII_HASH_SALT, ARTICLES_TABLE, COMMENTS_TABLE
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def hash_author(author: str) -> Optional[str]:
    if not author:
        return None
    salted = f"{PII_HASH_SALT}:{author}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()[:16]


def mask_articles_author() -> int:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT article_id, author
                FROM {ARTICLES_TABLE}
                WHERE author IS NOT NULL AND LENGTH(author) != 16
            """)
            rows = cur.fetchall()

            updated = 0
            for article_id, author in rows:
                hashed = hash_author(author)
                cur.execute(f"""
                    UPDATE {ARTICLES_TABLE}
                    SET author = %s
                    WHERE article_id = %s
                """, (hashed, article_id))
                updated += 1

    logging.info("articles.author hash 完成：%d 筆", updated)
    return updated


def mask_comments_author() -> int:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT comment_id, author
                FROM {COMMENTS_TABLE}
                WHERE author IS NOT NULL AND LENGTH(author) != 16
            """)
            rows = cur.fetchall()

            updated = 0
            for comment_id, author in rows:
                hashed = hash_author(author)
                cur.execute(f"""
                    UPDATE {COMMENTS_TABLE}
                    SET author = %s
                    WHERE comment_id = %s
                """, (hashed, comment_id))
                updated += 1

    logging.info("comments.author hash 完成：%d 筆", updated)
    return updated


def run() -> None:
    a = mask_articles_author()
    c = mask_comments_author()
    logging.info("PII masking 完成：articles %d 筆, comments %d 筆", a, c)
