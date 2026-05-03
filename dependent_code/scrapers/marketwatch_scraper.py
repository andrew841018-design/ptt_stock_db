import sys
import logging
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from config import SOURCES, DEFAULT_HEADERS as _HEADERS

_SOURCE = SOURCES["marketwatch"]

# MarketWatch RSS feeds（免費、不受 paywall 限制）
_RSS_FEEDS = [
    "https://www.marketwatch.com/rss/topstories",        # Top Stories
    "https://www.marketwatch.com/rss/marketpulse",        # Market Pulse（即時市場動態）
    "https://www.marketwatch.com/rss/realtimeheadlines",  # Real-time Headlines
]

# Google News RSS 多組查詢擴大覆蓋（MarketWatch 官方 RSS 可能不夠即時）
# Google News URL 使用 protobuf 編碼無法解碼為實際 URL
# 策略：直接用 Google News URL 作為文章 URL，RSS 標題作為內容
_GOOGLE_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=site:marketwatch.com+stock+market&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=site:marketwatch.com+economy+business&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=site:marketwatch.com+wall+street&hl=en-US&gl=US&ceid=US:en",
]

class MarketWatchScraper(BaseScraper):
    """
    MarketWatch 財經新聞爬蟲。
    主要透過 RSS feeds 取得文章列表，輔以 Google News RSS 擴大覆蓋。

    資料來源：
      1. MarketWatch 官方 RSS：Top Stories / Market Pulse / Real-time Headlines
      2. Google News RSS：搜尋 site:marketwatch.com 的股市相關文章

    MarketWatch 優勢（vs WSJ）：
      - 大部分文章免費全文可讀（無 paywall）
      - 全文抓取成功率高

    增量設計：
      - RSS 只顯示最近約 50 篇文章，無法歷史回溯
      - 透過排程定期執行（每小時），隨時間累積歷史資料
      - URL 去重確保不重複入庫

    特性：
      - 新聞沒有留言，comments 填 []
      - 沒有推/噓，push_count 填 None
      - author 來自 RSS 的 dc:creator 或 author 欄位

    注意：需要安裝 feedparser（pip install feedparser），已記錄在 requirements.txt
    """

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        if feedparser is None:
            logging.error("feedparser 未安裝，MarketWatch 爬蟲中止。請執行 pip install feedparser")
            return []

        known_urls = self._load_urls()
        logging.info(f"MarketWatch 載入已知 URL：{len(known_urls)} 筆")

        articles = []

        # 階段一：MarketWatch 官方 RSS feeds
        for feed_url in tqdm(_RSS_FEEDS, desc="MarketWatch RSS feeds", file=sys.stderr):
            feed_articles = self._parse_rss_feed(feed_url, known_urls)
            articles.extend(feed_articles)
            logging.info(f"MarketWatch RSS {feed_url.split('/')[-1]}：取得 {len(feed_articles)} 篇新文章")

        # 階段二：Google News RSS 補充（多組查詢擴大覆蓋）
        for gn_feed in _GOOGLE_NEWS_FEEDS:
            gn_articles = self._parse_google_news_rss(gn_feed, known_urls)
            articles.extend(gn_articles)
            query = gn_feed.split("q=")[1].split("&")[0] if "q=" in gn_feed else gn_feed
            logging.info(f"Google News RSS（MarketWatch）{query}：取得 {len(gn_articles)} 篇新文章")

        logging.info(f"MarketWatch 本次共取得 {len(articles)} 篇新文章")
        return articles

    def _parse_rss_feed(self, feed_url: str, known_urls: set) -> list:
        """
        解析一個 MarketWatch RSS feed，回傳標準格式文章 list。

        RSS entry 主要欄位（feedparser 解析後）：
          title           str     文章標題
          link            str     文章 URL
          description     str     摘要（HTML 或純文字）
          published_parsed time.struct_time  發布時間
          author          str     記者名稱
        """
        try:
            response = self._get_with_retry(feed_url, headers=_HEADERS)
            feed = feedparser.parse(response.text)
        except requests.RequestException as e:
            logging.warning(f"MarketWatch RSS 請求失敗 {feed_url}：{e}")
            return []

        if feed.bozo and not feed.entries:
            logging.warning(f"MarketWatch RSS 解析失敗 {feed_url}：{feed.bozo_exception}")
            return []

        articles = []
        for entry in feed.entries:
            article = self._parse_rss_entry(entry, known_urls)
            if article:
                articles.append(article)
        return articles

    def _parse_rss_entry(self, entry, known_urls: set) -> Optional[dict]:
        """
        解析單篇 RSS entry，回傳標準格式 dict。
        已知 URL 或無效資料回傳 None。
        """
        url = (entry.get("link") or "").strip()
        if not url:
            return None

        # 清除 URL 中的 query string 追蹤參數（保持去重一致性）
        if "?" in url:
            url = url.split("?")[0]

        if url in known_urls:
            return None

        title = (entry.get("title") or "").strip()
        if not title:
            return None

        # RSS 摘要（MarketWatch 文章頁自 2026 年起回 401 Forbidden，全文抓取已停用）
        raw_desc = entry.get("description") or entry.get("summary", "")
        content = BeautifulSoup(raw_desc, "html.parser").get_text(separator="\n").strip()

        if not content:
            return None

        # 解析發布時間
        published_at = self._parse_rss_date(entry)
        if not published_at:
            return None

        # author 可能在 author 或 dc:creator 欄位
        author = entry.get("author") or entry.get("dc_creator")
        if author:
            author = author.strip()

        article = {
            "title":        title,
            "content":      content,
            "url":          url,
            "author":       author if author else None,
            "published_at": published_at,
            "push_count":   None,   # 新聞無推文數
            "comments":     [],     # 新聞無留言
        }
        if not self.validate_article(article, "MarketWatch"):
            return None

        # 記錄已處理的 URL，同一次 run 內避免重複
        known_urls.add(url)
        return article

    def _parse_google_news_rss(self, feed_url: str, known_urls: set) -> list:
        """
        從 Google News RSS 取得 MarketWatch 相關文章。
        MarketWatch 文章頁自 2026 年起回 401 Forbidden，全文無法抓取。
        Google News URL 的 protobuf 編碼無法解碼為實際 MarketWatch URL。

        策略：
          - 用 source.href 判斷是否為 MarketWatch 來源
          - 直接使用 Google News link 作為文章 URL（dedup key）
          - 用 RSS title + description 作為 content
        """
        try:
            response = self._get_with_retry(feed_url, headers=_HEADERS)
            feed = feedparser.parse(response.text)
        except requests.RequestException as e:
            logging.warning(f"Google News RSS（MarketWatch）請求失敗 {feed_url}：{e}")
            return []

        if feed.bozo and not feed.entries:
            logging.warning(f"Google News RSS（MarketWatch）解析失敗 {feed_url}：{feed.bozo_exception}")
            return []

        articles = []
        for entry in feed.entries:
            # 用 source.href 判斷是否為 MarketWatch 來源
            source = entry.get("source", {})
            source_href = source.get("href", "") if hasattr(source, "get") else ""
            if "marketwatch.com" not in source_href:
                continue

            # 直接用 Google News link 作為 URL（protobuf 編碼無法解碼）
            url = (entry.get("link") or "").strip()
            if not url or url in known_urls:
                continue

            title = (entry.get("title") or "").strip()
            if not title:
                continue
            # 移除 " - MarketWatch" 尾綴
            if title.endswith(" - MarketWatch"):
                title = title[:-14].strip()

            # content：用 description（若有），否則用 title
            raw_desc = entry.get("description") or entry.get("summary", "")
            content = BeautifulSoup(raw_desc, "html.parser").get_text(separator="\n").strip()
            if not content or content == title:
                content = title

            published_at = self._parse_rss_date(entry)
            if not published_at:
                continue

            author = entry.get("author")
            if author:
                author = author.strip()

            article = {
                "title":        title,
                "content":      content,
                "url":          url,
                "author":       author if author else None,
                "published_at": published_at,
                "push_count":   None,
                "comments":     [],
            }
            if not self.validate_article(article, "MarketWatch Google News"):
                continue

            articles.append(article)
            known_urls.add(url)
        return articles

    def _parse_rss_date(self, entry) -> Optional[datetime]:
        """
        從 RSS entry 解析發布時間。
        feedparser 會自動解析為 time.struct_time（published_parsed）。
        """
        parsed_time = entry.get("published_parsed")
        if parsed_time:
            try:
                return datetime(*parsed_time[:6])
            except (ValueError, TypeError):
                pass

        # fallback：手動解析 published 字串
        pub_str = entry.get("published", "")
        if pub_str:
            formats = [
                "%a, %d %b %Y %H:%M:%S %Z",     # RFC 822
                "%a, %d %b %Y %H:%M:%S %z",     # RFC 822 with offset
                "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601
                "%Y-%m-%dT%H:%M:%S.%fZ",         # ISO 8601 with ms
                "%Y-%m-%d %H:%M:%S",             # Simple format
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(pub_str, fmt)
                except ValueError:
                    continue
            logging.warning(f"MarketWatch 無法解析時間格式：{pub_str!r}")

        return None
