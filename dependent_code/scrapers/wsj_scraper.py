"""
WSJ（華爾街日報）Markets/Business 爬蟲。
使用 WSJ Google News sitemap 直接取得文章列表。
WSJ 有 paywall，全文無法免費取得，嘗試後 fallback 到 sitemap 標題。
"""

import logging
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional

from scrapers.base_scraper import BaseScraper
from config import SOURCES, DEFAULT_HEADERS as _HEADERS

_SOURCE = SOURCES["wsj"]

_SITEMAP_URL = "https://www.wsj.com/wsjsitemaps/wsj_google_news.xml"

_NS = {
    "sm":   "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


class WsjScraper(BaseScraper):
    """WSJ 爬蟲：sitemap → 嘗試抓全文 → paywall 時 fallback 到標題。"""

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info("WSJ 載入已知 URL：%d 筆", len(known_urls))

        entries = self._fetch_sitemap()
        logging.info("WSJ sitemap 取得 %d 篇（含已知）", len(entries))

        articles = []
        for entry in entries:
            url = entry["url"]
            if url in known_urls:
                continue

            content = self._fetch_article_content(url) or entry["title"]
            article = {
                "title":        entry["title"],
                "content":      content,
                "url":          url,
                "author":       None,
                "published_at": entry["published_at"],
                "push_count":   None,
                "comments":     [],
            }
            if not self.validate_article(article, "WSJ"):
                continue
            articles.append(article)
            known_urls.add(url)

        logging.info("WSJ 本次共取得 %d 篇新文章", len(articles))
        return articles

    def _fetch_sitemap(self) -> list:
        try:
            response = self._get_with_retry(_SITEMAP_URL, headers=_HEADERS)
            root = ET.fromstring(response.content)
        except Exception as e:
            logging.warning("WSJ sitemap 解析失敗：%s", e)
            return []

        entries = []
        for url_elem in root.findall("sm:url", _NS):
            loc     = url_elem.findtext("sm:loc",                         namespaces=_NS) or ""
            title   = url_elem.findtext("news:news/news:title",           namespaces=_NS) or ""
            pub_str = url_elem.findtext("news:news/news:publication_date", namespaces=_NS) or ""
            published_at = _parse_iso_date(pub_str)
            if loc and title and published_at:
                entries.append({"url": loc, "title": title.strip(), "published_at": published_at})
        return entries

    def _fetch_article_content(self, url: str) -> Optional[str]:
        try:
            response = self._get_with_retry(url, headers=_HEADERS)
            soup = BeautifulSoup(response.text, "html.parser")
            body = (
                soup.find("div", class_="article-content")
                or soup.find("div", class_="wsj-snippet-body")
                or soup.find("section", attrs={"data-testid": "article-body"})
            )
            if body:
                paragraphs = body.find_all("p")
            else:
                article_tag = soup.find("article")
                paragraphs = article_tag.find_all("p") if article_tag else []
            text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            return text if len(text) > 50 else None
        except requests.RequestException as e:
            logging.debug("WSJ 全文抓取失敗 %s：%s", url, e)
            return None


def _parse_iso_date(date_str: str) -> Optional[datetime]:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return None
