"""
CNN Business/Markets 新聞爬蟲。
雙層 sitemap：
  - news.xml：滾動視窗（最近 ~120 篇），含完整 metadata（title / published_at）
  - 月份 business sitemap：當月～上月整月財經文章 URL（CNN 把 tech/economy/markets 都歸在 business 下），metadata 由 article 頁面補
CNN 個別文章頁為 SSR，可靜態解析全文。
"""

import logging
import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional

from scrapers.base_scraper import BaseScraper
from config import SOURCES, DEFAULT_HEADERS as _HEADERS

_SOURCE = SOURCES["cnn"]

_NEWS_SITEMAP_URL = "https://edition.cnn.com/sitemap/news.xml"
_MONTH_SITEMAP_TEMPLATE = "https://www.cnn.com/sitemap/article/business/{year}/{month:02d}.xml"

_BUSINESS_PATHS = (
    "/business/", "/markets/", "/economy/", "/money/",
    "/investing/", "/tech/", "/media/",
)

_NS = {
    "sm":   "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}

_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


class CnnScraper(BaseScraper):
    """CNN 爬蟲：news.xml + 月份 business sitemap → 過濾財經路徑 → 抓全文。"""

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info("CNN 載入已知 URL：%d 筆", len(known_urls))

        entries = self._fetch_sitemap()
        logging.info("CNN sitemap 取得 %d 篇（含已知）", len(entries))

        articles = []
        for entry in entries:
            url = entry["url"]
            if url in known_urls:
                continue
            if not any(p in url for p in _BUSINESS_PATHS):
                continue

            if entry.get("_needs_full_fetch"):
                full = self._fetch_article_full(url)
                if not full:
                    continue
                title        = full["title"]
                content      = full["content"]
                published_at = entry["published_at"] or full["published_at"]
            else:
                content      = self._fetch_article_content(url) or entry["title"]
                title        = entry["title"]
                published_at = entry["published_at"]

            article = {
                "title":        title,
                "content":      content,
                "url":          url,
                "author":       None,
                "published_at": published_at,
                "push_count":   None,
                "comments":     [],
            }
            if not self.validate_article(article, "CNN"):
                continue
            articles.append(article)
            known_urls.add(url)

        logging.info("CNN 本次共取得 %d 篇新文章", len(articles))
        return articles

    def _fetch_sitemap(self) -> list:
        """合併 news.xml（完整 metadata）+ 月份 business sitemap（補 URL）。"""
        entries_by_url: dict = {}

        try:
            response = self._get_with_retry(_NEWS_SITEMAP_URL, headers=_HEADERS)
            root = ET.fromstring(response.content)
            for url_elem in root.findall("sm:url", _NS):
                loc     = url_elem.findtext("sm:loc",                          namespaces=_NS) or ""
                title   = url_elem.findtext("news:news/news:title",            namespaces=_NS) or ""
                pub_str = url_elem.findtext("news:news/news:publication_date", namespaces=_NS) or ""
                published_at = _parse_iso_date(pub_str)
                if loc and title and published_at:
                    entries_by_url[loc] = {
                        "url":          loc,
                        "title":        title.strip(),
                        "published_at": published_at,
                    }
        except Exception as e:
            logging.warning("CNN news.xml 解析失敗：%s", e)

        for month_url in _month_sitemap_urls():
            try:
                response = self._get_with_retry(month_url, headers=_HEADERS)
                root = ET.fromstring(response.content)
                for url_elem in root.findall("sm:url", _NS):
                    loc = url_elem.findtext("sm:loc", namespaces=_NS) or ""
                    if not loc or loc in entries_by_url:
                        continue
                    if not any(p in loc for p in _BUSINESS_PATHS):
                        continue
                    entries_by_url[loc] = {
                        "url":               loc,
                        "title":             "",
                        "published_at":      _published_at_from_url(loc),
                        "_needs_full_fetch": True,
                    }
            except Exception as e:
                logging.warning("CNN 月份 sitemap 解析失敗 %s：%s", month_url, e)

        return list(entries_by_url.values())

    def _fetch_article_content(self, url: str) -> Optional[str]:
        try:
            response = self._get_with_retry(url, headers=_HEADERS, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            body = (
                soup.find("div", class_="article__content")
                or soup.find("div", class_="zn-body__paragraph")
                or soup.find("section", class_="body-text")
            )
            paragraphs = body.find_all("p") if body else soup.select("article p")
            text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            return text if len(text) > 50 else None
        except requests.RequestException as e:
            logging.debug("CNN 全文抓取失敗 %s：%s", url, e)
            return None

    def _fetch_article_full(self, url: str) -> Optional[dict]:
        """一次抓 title + published_at + content（給月份 sitemap 來的 URL）。"""
        try:
            response = self._get_with_retry(url, headers=_HEADERS, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")

            title = ""
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title:
                title = soup.title.get_text(strip=True)

            published_at = None
            meta_pub = soup.find("meta", property="article:published_time")
            if meta_pub and meta_pub.get("content"):
                published_at = _parse_iso_date(meta_pub["content"])

            body = (
                soup.find("div", class_="article__content")
                or soup.find("div", class_="zn-body__paragraph")
                or soup.find("section", class_="body-text")
            )
            paragraphs = body.find_all("p") if body else soup.select("article p")
            content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if len(content) < 50:
                return None

            return {
                "title":        title or url.rstrip("/").rsplit("/", 1)[-1],
                "content":      content,
                "published_at": published_at,
            }
        except requests.RequestException as e:
            logging.debug("CNN 全文 + metadata 抓取失敗 %s：%s", url, e)
            return None


def _month_sitemap_urls() -> list:
    """本月 + 月初 3 日內回溯上月（避免月初剛換月時錯過上月尾文章）。"""
    today = datetime.utcnow()
    months = [today]
    if today.day <= 3:
        months.append(today.replace(day=1) - timedelta(days=1))
    return [
        _MONTH_SITEMAP_TEMPLATE.format(year=m.year, month=m.month)
        for m in months
    ]


def _published_at_from_url(url: str) -> Optional[datetime]:
    """從 cnn.com/YYYY/MM/DD/ slug 推發布日期。"""
    m = _URL_DATE_RE.search(url)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_iso_date(date_str: str) -> Optional[datetime]:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return None
