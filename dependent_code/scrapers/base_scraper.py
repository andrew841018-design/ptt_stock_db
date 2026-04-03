from abc import ABC, abstractmethod
from datetime import datetime
import logging
import time
import requests
from pg_helper import get_pg
from config import ARTICLES_TABLE, COMMENTS_TABLE, SOURCES_TABLE, MAX_RETRY


class BaseScraper(ABC):
    """
    所有爬蟲的抽象基底類別。

    設計分工：
      - 子類別負責「怎麼爬」：實作 get_source_info() 和 fetch_articles()
      - base class 負責「怎麼存」：run() 統一處理 DB 寫入、去重、來源建立

    子類別需實作的兩個方法：
      - get_source_info()  → 回傳來源名稱與 URL
      - fetch_articles()   → 回傳標準格式的文章清單

    子類別不需動的部分（base class 已處理）：
      - HTTP retry（_get_with_retry，MAX_RETRY 次，exponential backoff）
      - sources 表的建立或查找（_get_or_create_source）
      - 重複文章的跳過（_is_duplicate，用 URL 去重）
      - articles / comments 的寫入（_insert_article / _insert_comments）

    新增來源規範：
      - HTTP 請求一律用 self._get_with_retry()，禁止直接用 requests.get()
      - fetch_articles() 回傳的 dict 無該欄位時明確填 None，不靠預設值
    """

    @abstractmethod
    def get_source_info(self) -> dict:
        """只定義抽象類別，實作由子類別實現"""

    @abstractmethod
    def fetch_articles(self) -> list:
        """只定義抽象類別，實作由子類別實現"""

    def run(self) -> None:
        """主流程：fetch → 寫入 DB"""
        source = self.get_source_info()
        logging.info(f"開始爬取：{source['name']}")
        articles = self.fetch_articles()
        self._save_to_db(articles)
        logging.info(f"完成：{source['name']}，共 {len(articles)} 篇")

    # ── 共用 HTTP helper ──────────────────────────────────────────────

    def _get_with_retry(self, url: str, **kwargs) -> requests.Response:
        """
        requests.get 加上 retry 機制。
        失敗時 exponential backoff（1, 2, 4, 8, 16... 秒），超過 MAX_RETRY 次則 raise。
        """
        for attempt in range(MAX_RETRY):
            try:
                response = requests.get(url, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == MAX_RETRY - 1:
                    raise e
                wait = 2 ** attempt
                logging.warning(f"請求失敗（{attempt + 1}/{MAX_RETRY}），{wait}s 後重試：{e}")
                time.sleep(wait)

    # ── 以下為共用 DB 邏輯，子類別不需覆寫 ──────────────────────────

    def _save_to_db(self, articles: list) -> None:
        source = self.get_source_info()
        with get_pg() as conn:
            with conn.cursor() as cursor:
                source_id = self._get_or_create_source(cursor, source['name'], source['url'])
                for article in articles:
                    # 寫入前沒有article_id，因此只能用url去判斷是否重複
                    if self._is_duplicate(cursor, article['url']):
                        continue
                    article_id = self._insert_article(cursor, source_id, article)
                    if article.get('comments'):# for ptt only
                        self._insert_comments(cursor, article_id, article['comments'])

    def _get_or_create_source(self, cursor, name: str, url: str) -> int:
        cursor.execute(f"SELECT source_id FROM {SOURCES_TABLE} WHERE url = %s", (url,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute(
            f"INSERT INTO {SOURCES_TABLE} (source_name, url) VALUES (%s, %s) RETURNING source_id",
            (name, url)
        )
        return cursor.fetchone()[0]

    def _is_duplicate(self, cursor, url: str) -> bool:
        cursor.execute(f"SELECT article_id FROM {ARTICLES_TABLE} WHERE url = %s", (url,))
        return cursor.fetchone() is not None

    def _insert_article(self, cursor, source_id: int, article: dict) -> int:
        cursor.execute(f"""
            INSERT INTO {ARTICLES_TABLE}
                (source_id, title, push_count, author, url, content, published_at, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING article_id
        """, (
            source_id,
            article['title'],
            article.get('push_count'),
            article.get('author'),
            article['url'],
            article.get('content', ''),# 無內文填空字串
            article['published_at'],
            datetime.now(),
        ))
        return cursor.fetchone()[0]

    def _insert_comments(self, cursor, article_id: int, comments: list) -> None:
        for comment in comments:
            cursor.execute(f"""
                INSERT INTO {COMMENTS_TABLE} (article_id, user_id, push_tag, message)
                VALUES (%s, %s, %s, %s)
            """, (article_id, comment['user_id'], comment['push_tag'], comment['message']))
