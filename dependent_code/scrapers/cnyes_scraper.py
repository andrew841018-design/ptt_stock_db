import sys
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from config import SOURCES

_SOURCE = SOURCES["cnyes"]

_API_BASE = "https://api.cnyes.com/media/api/v1"


class CnyesScraper(BaseScraper):

    from config import EARLY_STOP_EMPTY_PAGES as EARLY_STOP_PAGES

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info(f"鉅亨網載入已知 URL：{len(known_urls)} 筆")

        categories = _SOURCE.get("categories", ["tw_stock"])
        articles = []

        for category in categories:
            cat_articles = self._fetch_category(category, known_urls)
            logging.info(f"鉅亨網 category={category}：爬到 {len(cat_articles)} 篇新文")
            articles.extend(cat_articles)

        logging.info(f"鉅亨網總計：{len(articles)} 篇新文（跨 {len(categories)} 個 category）")
        return articles


    def _fetch_category(self, category: str, known_urls: set) -> list:
        articles = []
        consecutive_empty_pages = 0

        for page_num in tqdm(
            range(1, _SOURCE["num_pages"] + 1),
            desc=f"鉅亨網 {category}",
            file=sys.stderr,
        ):
            try:
                items = self._fetch_news_list(category, page_num)
                if not items:
                    logging.info(f"鉅亨網 {category} 已無更多新聞（page {page_num}），停止")
                    break

                page_articles = []
                for item in items:
                    article = self._parse_news_item(item, known_urls)
                    if article:
                        page_articles.append(article)
                articles.extend(page_articles)

                if not page_articles:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= self.EARLY_STOP_PAGES:
                        logging.info(f"鉅亨網 {category} 連續 {consecutive_empty_pages} 頁無新文，停止")
                        break
                else:
                    consecutive_empty_pages = 0
            except requests.RequestException as e:
                logging.warning(f"鉅亨網 {category} 第 {page_num} 頁請求失敗：{e}，略過")
                continue

        return articles


    def _fetch_news_list(self, category: str, page: int) -> list:
        params = {"page": page, "limit": _SOURCE["page_size"]}
        response = self._get_with_retry(
            f"{_API_BASE}/newslist/category/{category}",
            params=params,
        )
        data = response.json()
        return data.get("items", {}).get("data", [])

    def _parse_news_item(self, item: dict, known_urls: set) -> Optional[dict]:
        news_id      = item.get("newsId")
        if not news_id:
            return None

        url = f"https://news.cnyes.com/news/id/{news_id}"
        if url in known_urls:
            return None

        html_content = item.get("content") or item.get("summary", "")
        publish_at   = item.get("publishAt")
        if not html_content or not publish_at:
            return None

        content = BeautifulSoup(html_content, "html.parser").get_text(separator="\n").strip()

        article = {
            "title":        (item.get("title") or "").strip(),
            "content":      content,
            "url":          url,
            "author":       item.get("author"),
            "published_at": self.ts_to_dt(
                                item["publishAt"]
                            ),
            "push_count":   None,
            "comments":     [],
        }
        if not self.validate_article(article, "cnyes"):
            return None
        return article
