import logging
from datetime import datetime
from typing import Optional

from scrapers.base_scraper import BaseScraper
from scrapers.scraper_schemas import ArticleSchema
from config import SOURCES

_SOURCE     = SOURCES["reddit"]
_SUBREDDITS = _SOURCE["subreddits"]  # "investing+stocks+wallstreetbets"（Reddit API 支援 + 合併語法）

# Reddit 公開 JSON API，不需要 API key
# 需要 User-Agent 否則會被 rate limit（429）
_HEADERS    = {"User-Agent": "ptt-sentiment-bot/1.0"}
_BASE_URL   = "https://www.reddit.com/r/{subreddits}/new.json"
_PAGE_LIMIT = 100  # Reddit API 每頁上限（硬性限制，不可超過）


class RedditScraper(BaseScraper):
    """
    Reddit 財經版爬蟲（r/investing + r/stocks + r/wallstreetbets）。

    設計說明：
      - 繼承 BaseScraper，DB 寫入邏輯統一由 base 處理
      - 使用 Reddit 公開 JSON API（不需要 API key，限制：每分鐘 60 次請求）
      - 分頁：cursor-based（after），格式為 "t3_{post_id}"
      - 每頁最多 100 筆貼文
      - 停止條件：
          1. after = None（已無更多）
          2. 連續 EARLY_STOP_PAGES 頁全為已知 URL
          3. 達到 num_pages 上限

    資料量規模：
      - 增量爬取（每日）：三個版面 new feed，約數百到數千篇/天
      - 歷史大量：改用 Arctic Shift API（另建 bulk_load_reddit.py）
        https://arctic-shift.photon-reddit.com/api/posts/search
    """

    EARLY_STOP_PAGES = 3

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        urls = self._load_urls()
        logging.info(f"Reddit 載入已知 URL：{len(urls)} 筆")

        articles = []
        after = None
        consecutive_empty_pages = 0

        for page_num in range(_SOURCE["num_pages"]):
            params = {"limit": _PAGE_LIMIT, "after": after} if after else {"limit": _PAGE_LIMIT}
            try:
                response = self._get_with_retry(
                    _BASE_URL.format(subreddits=_SUBREDDITS),
                    params=params,
                    headers=_HEADERS,
                )
            except Exception as e:
                logging.warning(f"Reddit 第 {page_num + 1} 頁失敗：{e}，停止")
                break

            data = response.json().get("data", {})
            children = data.get("children", [])
            after = data.get("after")  # 下一頁 cursor

            if not children:
                logging.info("Reddit 無更多貼文，停止")
                break

            page_articles = []
            for child in children:
                article = self._parse_post(child.get("data", {}), urls)
                if article is not None:
                    page_articles.append(article)
            articles.extend(page_articles)


            if not page_articles:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= self.EARLY_STOP_PAGES:
                    logging.info(f"Reddit 連續 {consecutive_empty_pages} 頁無新文章，停止")
                    break
            else:
                consecutive_empty_pages = 0

            if not after:
                logging.info("Reddit 已無更多貼文（after=None）")
                break

        return articles


    def _parse_post(self, post: dict, urls: set) -> Optional[dict]:
        """解析單篇 Reddit 貼文，回傳標準格式 dict。已知 URL、無效貼文回傳 None。"""
        post_id = post.get("id")
        if not post_id:
            return None

        # Reddit permalink 格式：/r/investing/comments/{id}/{title_slug}/
        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}"

        if url in urls:
            return None

        title   = (post.get("title") or "").strip()
        content = (post.get("selftext") or "").strip()

        # 被刪除的貼文內文為 "[removed]" 或 "[deleted]"
        if content in ("[removed]", "[deleted]"):
            content = ""

        created_utc = post.get("created_utc")# html timestamp欄位
        try:
            published_at = datetime.utcfromtimestamp(float(created_utc))
        except (ValueError, TypeError):
            logging.warning(f"Reddit 無法解析時間：{created_utc!r}，略過 {url}")
            return None

        # score = Reddit 的 upvote 數，對應 push_count；clamp 在 -100~100
        score = post.get("score", 0) or 0
        push_count = max(-100, min(100, score))

        article = {
            "title":        title,
            "content":      content,
            "url":          url,
            "author":       post.get("author"),
            "published_at": published_at,
            "push_count":   push_count,
            "comments":     [],             # 不爬留言（降低 API 壓力）
        }
        try:
            ArticleSchema(**article)
        except Exception as e:
            logging.warning(f"Reddit 貼文驗證失敗，略過 {url}：{e}")
            return None
        return article
