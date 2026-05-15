
import sys
import logging
import time
from datetime import datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

import requests
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from config import SOURCES, MAX_RETRY, REQUEST_DELAY
REDDIT_BATCH_HISTORY_START  = "2005-01-01"

_SOURCE     = SOURCES["reddit"]
_API_URL    = "https://arctic-shift.photon-reddit.com/api/posts/search"
_HEADERS    = {"User-Agent": "ptt-sentiment-bot/1.0"}
_SUBREDDITS = [sub.strip() for sub in _SOURCE["subreddits"].split("+")]
_PAGE_LIMIT  = 100


class RedditBatchLoader(BaseScraper):

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self, after: datetime, before: datetime) -> list:
        urls = self._load_urls()
        all_articles = []
        for subreddit in _SUBREDDITS:
            all_articles.extend(self._fetch_subreddit(subreddit, after, before, urls))
        return all_articles

    def _fetch_subreddit(self, subreddit: str, after: datetime, before: datetime, urls: set) -> list:
        articles     = []
        cursor_after = int(after.timestamp())
        before_ts    = int(before.timestamp())
        page         = 0

        with tqdm(desc=f"r/{subreddit}", unit=" 頁", file=sys.stderr) as pbar:
            while True:
                params = {
                    "subreddit": subreddit,
                    "limit":     _PAGE_LIMIT,
                    "after":     cursor_after,
                    "before":    before_ts,
                    "sort":      "asc",
                }
                try:
                    response = self._get_with_retry(
                        _API_URL, params=params, headers=_HEADERS, timeout=60
                    )
                except requests.RequestException as e:
                    logging.warning(
                        f"Reddit batch 請求失敗（r/{subreddit} page {page}，"
                        f"已重試 {MAX_RETRY} 次）：{e}，停止"
                    )
                    break

                data  = response.json()
                error = data.get("error")
                if error:
                    logging.warning(f"Reddit batch API 錯誤（r/{subreddit}）：{error}，停止")
                    break

                posts = data.get("data") or []
                if not posts:
                    logging.info(f"Reddit batch r/{subreddit} 無更多資料")
                    break

                page_articles = []
                for post in posts:
                    article = self._parse_post(post, urls)
                    if article is not None:
                        page_articles.append(article)
                articles.extend(page_articles)

                last_ts = posts[-1].get("created_utc", cursor_after)    
                if last_ts <= cursor_after:
                    break
                cursor_after = last_ts + 1

                page += 1
                pbar.update(1)
                pbar.set_postfix({"累計": len(articles), "最新日期": datetime.fromtimestamp(last_ts).date()})
                time.sleep(REQUEST_DELAY)

        return articles

    def run_range(self, after: datetime, before: datetime) -> None:
        urls = self._load_urls()
        logging.info(f"Reddit batch 載入已知 URL：{len(urls)} 筆")
        logging.info(f"抓取區間：{after.date()} ～ {before.date()}")
        total = 0
        for subreddit in _SUBREDDITS:
            logging.info(f"Reddit batch 開始抓取 r/{subreddit}")
            articles = self._fetch_subreddit(subreddit, after, before, urls)
            if articles:
                self._save_to_db(articles)
                total += len(articles)
                logging.info(f"Reddit batch r/{subreddit} 完成，寫入 {len(articles)} 筆")
            else:
                logging.warning(f"Reddit batch r/{subreddit} 無新資料寫入")
        logging.info(f"Reddit batch 全部完成，共寫入 {total} 筆")

    def run(self) -> None:
        before = datetime.utcnow()
        after  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
        self.run_range(after, before)


    def _parse_post(self, post: dict, urls: set) -> Optional[dict]:
        post_id   = post.get("id")
        permalink = post.get("permalink", "")
        if not post_id or not permalink:
            return None

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
        if not self.validate_article(article, "Reddit batch"):
            return None
        return article



