from abc import ABC, abstractmethod
from datetime import datetime
import json
import logging
import random
import time
from typing import Optional, Union
import requests
from requests.adapters import HTTPAdapter
from pg_helper import get_pg
from config import ARTICLES_TABLE, COMMENTS_TABLE, SOURCES_TABLE, MAX_RETRY
from scrapers.scraper_schemas import ArticleSchema

_SESSION = requests.Session()
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)

try:
    from mongo_helper import save_raw_response
    _MONGO_OK = True
except ImportError:
    _MONGO_OK = False


def get_with_retry(url: str, **kwargs) -> requests.Response:
    for attempt in range(MAX_RETRY):
        try:
            response = _SESSION.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code < 500:
                raise
            if attempt == MAX_RETRY - 1:
                raise e
            wait = (2 ** attempt) + random.uniform(0, 1)
            logging.debug(f"請求失敗（{attempt + 1}/{MAX_RETRY}），{wait:.1f}s 後重試：{e}")
            time.sleep(wait)
        except requests.RequestException as e:
            if attempt == MAX_RETRY - 1:
                raise e
            wait = (2 ** attempt) + random.uniform(0, 1)
            logging.debug(f"請求失敗（{attempt + 1}/{MAX_RETRY}），{wait:.1f}s 後重試：{e}")
            time.sleep(wait)


class BaseScraper(ABC):

    @abstractmethod
    def get_source_info(self) -> dict:
        pass

    @abstractmethod
    def fetch_articles(self) -> list:
        pass


    @staticmethod
    def validate_article(article: dict, context: str = "") -> bool:
        try:
            ArticleSchema(**article)
            return True
        except Exception as err:
            url = (article or {}).get("url", "<no url>")
            prefix = f"{context} " if context else ""
            logging.warning(f"{prefix}文章驗證失敗，略過 {url}：{err}")
            return False

    @staticmethod
    def ts_to_dt(ts: Union[int, float]) -> datetime:
        if ts > 1e12:
            ts = ts / 1000
        return datetime.utcfromtimestamp(ts)

    def _get_with_retry(self, url: str, **kwargs) -> requests.Response:
        response = get_with_retry(url, **kwargs)
        self._store_raw(url, response)
        return response

    def _store_raw(self, url: str, response: requests.Response) -> None:
        if not _MONGO_OK:
            return
        try:
            content_type = response.headers.get("Content-Type", "")
            source_key   = self.get_source_info().get("name", "unknown")
            if "json" in content_type:
                save_raw_response(source_key, url, response.text,
                          content_type="json", http_status=response.status_code)
            else:
                save_raw_response(source_key, url, response.text,
                          content_type="html", http_status=response.status_code)
        except Exception as e:
            logging.warning(f"[Mongo] best-effort archival skipped for {url}: {e}")

    def _save_to_raw(self, articles: list) -> None:
        if not articles:
            return
        source_name = self.get_source_info().get("name", "unknown")
        with get_pg() as conn:
            with conn.cursor() as cur:
                for article in articles:
                    cur.execute(
                        "INSERT INTO raw_articles (source_name, raw_payload) VALUES (%s, %s::jsonb)",
                        (source_name, json.dumps(article, default=str))
                    )

    def _save_one_to_raw(self, cursor, article: dict) -> None:
        if not article:
            return
        source_name = self.get_source_info().get("name", "unknown")
        cursor.execute(
            "INSERT INTO raw_articles (source_name, raw_payload) VALUES (%s, %s::jsonb)",
            (source_name, json.dumps(article, default=str))
        )

    def _save_sentiment_scores_to_raw(self, scores: list) -> None:
        if not scores:
            return
        with get_pg() as conn:
            with conn.cursor() as cur:
                for score in scores:
                    article_id_raw = score.get("article_id_raw") or score.get("url")
                    cur.execute(
                        "INSERT INTO raw_sentiment_scores (article_id_raw, raw_payload) VALUES (%s, %s::jsonb)",
                        (article_id_raw, json.dumps(score, default=str))
                    )

    def run(self) -> None:
        source = self.get_source_info()
        logging.info(f"開始爬取：{source['name']}")
        articles = self.fetch_articles()
        self._save_to_db(articles)
        logging.info(f"完成：{source['name']}，共 {len(articles)} 篇")


    def _load_urls(self) -> set:
        source = self.get_source_info()
        with get_pg() as conn:
            with conn.cursor() as cursor:
                source_id = self._get_or_create_source(cursor, source['name'], source['url'])
                cursor.execute(
                    f"SELECT url FROM {ARTICLES_TABLE} WHERE source_id = %s", (source_id,)
                )
                return {url for (url,) in cursor.fetchall()}

    def _save_to_db(self, articles: list) -> None:
        self._save_to_raw(articles)

        source = self.get_source_info()
        with get_pg() as conn:
            with conn.cursor() as cursor:
                source_id = self._get_or_create_source(cursor, source['name'], source['url'])
                for article in articles:
                    if self._is_duplicate(cursor, article['url']):
                        continue
                    article_id = self._insert_article(cursor, source_id, article)
                    if article_id and article.get('comments'):
                        self._insert_comments(cursor, article_id, article['comments'])

    def _find_source(self, cursor, url: str) -> Optional[int]:
        cursor.execute(f"SELECT source_id FROM {SOURCES_TABLE} WHERE url = %s", (url,))
        row = cursor.fetchone()
        return row[0] if row else None

    def _get_or_create_source(self, cursor, name: str, url: str) -> int:
        source_id = self._find_source(cursor, url)
        if source_id is not None:
            return source_id
        cursor.execute(
            f"INSERT INTO {SOURCES_TABLE} (source_name, url) VALUES (%s, %s)"
            f" ON CONFLICT (url) DO NOTHING",
            (name, url)
        )
        return self._find_source(cursor, url)

    def _is_duplicate(self, cursor, url: str) -> bool:
        cursor.execute(f"SELECT article_id FROM {ARTICLES_TABLE} WHERE url = %s", (url,))
        return cursor.fetchone() is not None

    def _insert_article(self, cursor, source_id: int, article: dict) -> Optional[int]:
        cursor.execute(f"""
            INSERT INTO {ARTICLES_TABLE}
                (source_id, title, push_count, author, url, content, published_at, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            RETURNING article_id
        """, (
            source_id,
            article['title'],
            article.get('push_count'),
            article.get('author'),
            article['url'],
            article.get('content', ''),
            article['published_at'],
            datetime.utcnow(),
        ))
        row = cursor.fetchone()
        return row[0] if row else None

    def _insert_comments(self, cursor, article_id: int, comments: list) -> None:
        for comment in comments:
            cursor.execute(f"""
                INSERT INTO {COMMENTS_TABLE} (article_id, author, push_tag, message)
                VALUES (%s, %s, %s, %s)
            """, (article_id, comment['author'], comment['push_tag'], comment['message']))
