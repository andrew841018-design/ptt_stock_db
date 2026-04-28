"""
MarketWatch 財經新聞爬蟲。
使用 MarketWatch 官方 sitemap 直接取得文章列表。
MarketWatch 文章頁自 2026 年起回 401 Forbidden，直接以 sitemap 標題作為 content。
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

from scrapers.base_scraper import BaseScraper
from config import SOURCES, DEFAULT_HEADERS as _HEADERS

_SOURCE = SOURCES["marketwatch"]

_SITEMAP_URLS = [
    # 2026-04-24: MarketWatch 停用分頁版 sitemap（_1.xml / _2.xml 最後更新於 04-22），
    # 改回單檔版 mw_news_sitemap.xml（robots.txt 官方列出的 URL）
    "https://www.marketwatch.com/mw_news_sitemap.xml",
]

_NS = {
    "sm":   "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


class MarketWatchScraper(BaseScraper):
    """MarketWatch 爬蟲：兩個 sitemap → 合併去重 → 標題作 content（paywall）。"""

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info("MarketWatch 載入已知 URL：%d 筆", len(known_urls))

        all_entries = []
        for sitemap_url in _SITEMAP_URLS:
            entries = self._fetch_sitemap(sitemap_url)
            all_entries.extend(entries)
            logging.info("MarketWatch sitemap %s：取得 %d 篇", sitemap_url.split("/")[-1], len(entries))

        articles = []
        seen = set()
        for entry in all_entries:
            url = entry["url"]
            if url in known_urls or url in seen:
                continue
            seen.add(url)

            article = {
                "title":        entry["title"],
                "content":      entry["title"],
                "url":          url,
                "author":       None,
                "published_at": entry["published_at"],
                "push_count":   None,
                "comments":     [],
            }
            if not self.validate_article(article, "MarketWatch"):
                continue
            articles.append(article)
            known_urls.add(url)

        logging.info("MarketWatch 本次共取得 %d 篇新文章", len(articles))
        return articles

    def _fetch_sitemap(self, sitemap_url: str) -> list:
        """支援 sitemap index（含子 sitemap）與直接 urlset 兩種結構。
        2026-04-25：MarketWatch 把 mw_news_sitemap.xml 改成 sitemap index 包子 sitemap。"""
        try:
            response = self._get_with_retry(sitemap_url, headers=_HEADERS)
            root = ET.fromstring(response.content)
        except Exception as e:
            logging.warning("MarketWatch sitemap 解析失敗 %s：%s", sitemap_url, e)
            return []

        # sitemapindex → 遞迴抓所有子 sitemap
        if root.tag.endswith("}sitemapindex") or root.tag == "sitemapindex":
            entries = []
            for sm in root.findall("sm:sitemap", _NS):
                child_url = sm.findtext("sm:loc", namespaces=_NS) or ""
                if child_url:
                    entries.extend(self._fetch_sitemap(child_url))
            logging.info("MarketWatch sitemap index 展開為 %d 個子 sitemap", len(root.findall("sm:sitemap", _NS)))
            return entries

        # 直接 urlset
        entries = []
        for url_elem in root.findall("sm:url", _NS):
            loc     = url_elem.findtext("sm:loc",                         namespaces=_NS) or ""
            title   = url_elem.findtext("news:news/news:title",           namespaces=_NS) or ""
            pub_str = url_elem.findtext("news:news/news:publication_date", namespaces=_NS) or ""
            published_at = _parse_iso_date(pub_str)
            if loc and title and published_at:
                entries.append({"url": loc, "title": title.strip(), "published_at": published_at})
        return entries


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
