import re
import sys
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from config import SOURCES

_SOURCE = SOURCES["cnn"]

# CNN 官方 RSS 已於 2026 年關閉；Google News RSS 的 URL 使用 protobuf 編碼無法解析
# 改用直接爬取 CNN 各 section 頁面，從中提取文章連結
_SECTION_URLS = [
    "https://www.cnn.com/business",
    "https://www.cnn.com/markets",
    "https://edition.cnn.com/business",
]

# 文章 URL 格式：/YYYY/MM/DD/category/slug
_ARTICLE_URL_RE = re.compile(r"/20\d{2}/\d{2}/\d{2}/")

# Headers 走 config.DEFAULT_HEADERS（User-Agent 避免 403）
from config import DEFAULT_HEADERS as _HEADERS


class CnnScraper(BaseScraper):
    """
    CNN Business/Markets 新聞爬蟲。
    透過 RSS feeds 取得文章列表，輔以 Google News RSS 擴大覆蓋。

    資料來源：
      CNN 官方 RSS 已關閉，Google News RSS URL 使用 protobuf 編碼無法解析。
      改用直接爬取 CNN 各 section 頁面（business / markets），提取文章連結。

    增量設計：
      - Section 頁面約顯示 30-50 篇文章，無法歷史回溯
      - 透過排程定期執行，隨時間累積歷史資料
      - URL 去重確保不重複入庫

    特性：
      - 新聞沒有留言，comments 填 []
      - 沒有推/噓，push_count 填 None
      - 嘗試抓取文章頁面全文，失敗則用 RSS 摘要
    """

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info(f"CNN 載入已知 URL：{len(known_urls)} 筆")

        # 從各 section 頁面收集文章 URL
        candidate_urls = set()
        for section_url in tqdm(_SECTION_URLS, desc="CNN section pages", file=sys.stderr):
            page_urls = self._extract_article_urls(section_url)
            new_urls = page_urls - known_urls
            candidate_urls.update(new_urls)
            logging.info(f"CNN {section_url}：發現 {len(page_urls)} 篇，新 {len(new_urls)} 篇")

        # 逐篇抓取內容
        articles = []
        for url in tqdm(candidate_urls, desc="CNN articles", file=sys.stderr):
            article = self._fetch_article(url)
            if article:
                articles.append(article)
                known_urls.add(url)

        logging.info(f"CNN 本次共取得 {len(articles)} 篇新文章")
        return articles

    def _extract_article_urls(self, section_url: str) -> set:
        """從 CNN section 頁面提取文章 URL。"""
        try:
            response = self._get_with_retry(section_url, headers=_HEADERS)
            soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            logging.warning(f"CNN section 頁面抓取失敗 {section_url}：{e}")
            return set()

        urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not _ARTICLE_URL_RE.search(href):
                continue
            if not any(cat in href for cat in ("/business/", "/economy/", "/markets/")):
                continue
            full_url = href if href.startswith("http") else f"https://www.cnn.com{href}"
            # 統一域名（edition.cnn.com → www.cnn.com）
            full_url = full_url.replace("edition.cnn.com", "www.cnn.com")
            urls.add(full_url)
        return urls

    def _fetch_article(self, url: str) -> Optional[dict]:
        """抓取單篇 CNN 文章頁面，提取標題、全文、發布時間。"""
        try:
            response = self._get_with_retry(url, headers=_HEADERS)
            soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            logging.warning(f"CNN 文章抓取失敗 {url}：{e}")
            return None

        # 標題
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else None
        if not title:
            return None

        # 全文
        content = self._extract_content(soup)
        if not content:
            return None

        # 發布時間
        published_at = self._extract_publish_time(soup)
        if not published_at:
            # fallback：從 URL 提取日期
            published_at = self._parse_date_from_url(url)
        if not published_at:
            return None

        # 作者
        author = None
        author_tag = soup.find("span", class_="byline__name") or soup.find("meta", attrs={"name": "author"})
        if author_tag:
            author = author_tag.get_text(strip=True) if author_tag.name != "meta" else author_tag.get("content", "")
            if author and author.lower().startswith("by "):
                author = author[3:].strip()

        article = {
            "title":        title,
            "content":      content,
            "url":          url,
            "author":       author if author else None,
            "published_at": published_at,
            "push_count":   None,
            "comments":     [],
        }
        if not self.validate_article(article, "CNN"):
            return None
        return article

    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """從 CNN 頁面提取文章全文。"""
        paragraphs = []
        body_container = (
            soup.find("div", class_="article__content")
            or soup.find("div", class_="zn-body__paragraph")
            or soup.find("section", class_="body-text")
        )
        if body_container:
            paragraphs = body_container.find_all("p")
        else:
            paragraphs = soup.find_all("p", class_="paragraph")
            if not paragraphs:
                paragraphs = soup.select("article p")

        if not paragraphs:
            return None

        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return text if len(text) > 50 else None

    def _extract_publish_time(self, soup: BeautifulSoup) -> Optional[datetime]:
        """從 meta 標籤或 JSON-LD 提取發布時間。"""
        # meta 標籤
        for meta_name in ("article:published_time", "pubdate", "date"):
            meta = soup.find("meta", attrs={"property": meta_name}) or soup.find("meta", attrs={"name": meta_name})
            if meta and meta.get("content"):
                parsed = self._try_parse_datetime(meta["content"])
                if parsed:
                    return parsed

        # JSON-LD
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script_tag.string)
                if isinstance(data, dict):
                    pub = data.get("datePublished")
                    if pub:
                        parsed = self._try_parse_datetime(pub)
                        if parsed:
                            return parsed
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _try_parse_datetime(self, date_str: str) -> Optional[datetime]:
        """嘗試多種格式解析日期字串。"""
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None

    def _parse_date_from_url(self, url: str) -> Optional[datetime]:
        """從 URL 路徑 /YYYY/MM/DD/ 提取日期作為 fallback。"""
        match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
        return None
