import sys
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from scrapers.scraper_schemas import ArticleSchema
from config import SOURCES

_SOURCE = SOURCES["cnyes"]

# 鉅亨網公開 API
_API_BASE = "https://api.cnyes.com/media/api/v1"


class CnyesScraper(BaseScraper):
    """
    鉅亨網台股新聞爬蟲。
    鉅亨網提供 REST API（JSON），回傳新聞列表。

    分頁機制：
      GET /newslist/category/tw_stock?page=1&limit=30
      page 從 1 開始遞增。

    特性：
      - 新聞沒有留言，comments 填 []
      - 沒有推/噓，push_count 填 None
      - content 為 HTML，需用 BeautifulSoup 轉純文字
    """

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        articles = []

        for page_num in tqdm(range(1, _SOURCE["num_pages"] + 1), desc="鉅亨網爬蟲頁數", file=sys.stderr):
            try:
                items = self._fetch_news_list(page_num)
                if not items:
                    logging.info("鉅亨網已無更多新聞，停止爬取")
                    break
                for item in items:
                    article = self._parse_news_item(item)
                    if article:
                        articles.append(article)
            except requests.RequestException as e:
                logging.warning(f"鉅亨網第 {page_num} 頁請求失敗：{e}，略過")
                continue

        return articles


    def _fetch_news_list(self, page: int) -> list:
        """
        取得一頁新聞列表，回傳 items list。
        API 回傳格式：{"items": {"data": [...], "total": N, "per_page": N, ...}}
        """
        params = {"page": page, "limit": _SOURCE["page_size"]}
        response = self._get_with_retry(
            f"{_API_BASE}/newslist/category/tw_stock",
            params=params,
        )
        data = response.json()
        return data.get("items", {}).get("data", [])

    def _parse_news_item(self, item: dict) -> Optional[dict]:
        """
        將 API 回傳的單筆新聞轉成標準格式。
        content 是 HTML，用 BeautifulSoup 取純文字。

        item 欄位（API 實際回傳）：
          newsId       int     新聞 ID（用來組 URL）
          title        str     標題
          summary      str     摘要（純文字）
          content      str     內文（HTML）
          publishAt    int     發布時間（Unix timestamp，秒）
          source       str     來源（可能為 None）
          keyword      list    關鍵字列表
          market       list    相關股票 [{'code': '2330', 'name': '台積電', ...}]
          categoryId   int     分類 ID
          categoryName str     分類名稱（e.g. '台股新聞'）
          coverSrc     str     封面圖（可能為 None）
          payment      int     是否付費（0=免費）
          fbShare      int     FB 分享數
          fbComment    int     FB 留言數
        """
        news_id      = item.get("newsId")
        html_content = item.get("content") or item.get("summary", "")
        publish_at   = item.get("publishAt")
        if not news_id or not html_content or not publish_at:
            return None

        # HTML → 純文字
        # get_text(separator="\n") 移除所有 HTML 標籤，只保留文字
        content = BeautifulSoup(html_content, "html.parser").get_text(separator="\n").strip()

        article = {
            "title":        item.get("title"),
            "content":      content,
            "url":          f"https://news.cnyes.com/news/id/{news_id}",
            "author":       item.get("author"),          # 記者名稱，可能為 None
            "published_at": datetime.utcfromtimestamp(
                                item["publishAt"]        # 鉅亨網時間戳是秒，統一轉 UTC
                            ),
            "push_count":   None,  # 新聞無推文數
            "comments":     [],    # 新聞無留言
        }
        try:
            ArticleSchema(**article)
        except Exception as e:
            logging.warning(f"文章驗證失敗，略過 {article['url']}：{e}")
            return None
        return article
