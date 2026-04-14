"""
PII Masking — author 欄位 hash 化
將 PTT 使用者 ID 轉為不可逆的 SHA-256 hash，保護個資。
"""

import hashlib
import logging
from typing import Optional
from config import PII_HASH_SALT, ARTICLES_TABLE, COMMENTS_TABLE
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def hash_author(author: str) -> Optional[str]:
    """將 author 加鹽後做 SHA-256 hash，取前 16 碼"""
    if not author:
        return None
    salted = f"{PII_HASH_SALT}:{author}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()[:16]


def mask_articles_author() -> int:
    """
    批次將 articles.author 欄位 hash 化。
    只處理尚未 hash 的資料（hash 輸出固定 16 碼，長度 != 16 表示尚未 hash）。
    回傳更新筆數。
    """
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
    """
    批次將 comments.author 欄位 hash 化。
    只處理尚未 hash 的資料（hash 輸出固定 16 碼，長度 != 16 表示尚未 hash）。
    回傳更新筆數。
    """
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
    """遮蔽 articles + comments 的 author 欄位"""
    a = mask_articles_author()
    c = mask_comments_author()
    logging.info("PII masking 完成：articles %d 筆, comments %d 筆", a, c)
