import logging
from typing import Optional

from scrapers.base_scraper import BaseScraper
from config import SOURCES

_SOURCE     = SOURCES["reddit"]
_SUBREDDITS = _SOURCE["subreddits"]

_HEADERS    = {"User-Agent": "ptt-sentiment-bot/1.0"}
_BASE_URL   = "https://www.reddit.com/r/{subreddits}/new.json"
_PAGE_LIMIT = 100


class RedditScraper(BaseScraper):

    from config import EARLY_STOP_EMPTY_PAGES as EARLY_STOP_PAGES

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
                data = response.json().get("data", {})
            except Exception as e:
                logging.warning(f"Reddit 第 {page_num + 1} 頁失敗：{e}，停止")
                break


            children = data.get("children", [])
            after = data.get("after")

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
        post_id = post.get("id")
        if not post_id:
            return None

        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}"

        if url in urls:
            return None

        title   = (post.get("title") or "").strip()
        content = (post.get("selftext") or "").strip()

        if content in ("[removed]", "[deleted]"):
            content = ""

        created_utc = post.get("created_utc")
        try:
            published_at = self.ts_to_dt(float(created_utc))
        except (ValueError, TypeError):
            logging.warning(f"Reddit 無法解析時間：{created_utc!r}，略過 {url}")
            return None

        score = post.get("score", 0) or 0
        push_count = max(-100, min(100, score))

        article = {
            "title":        title,
            "content":      content,
            "url":          url,
            "author":       post.get("author"),
            "published_at": published_at,
            "push_count":   push_count,
            "comments":     [],
        }
        if not self.validate_article(article, "Reddit"):
            return None
        return article
