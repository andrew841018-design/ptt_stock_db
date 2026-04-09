"""
Reddit 歷史批量資料載入器。

用途：一次性（或定期補充）抓取大量歷史貼文，規模可達數百萬筆。
      與 reddit_scraper.py（日常增量）分開，避免每天跑批量抓取。

資料來源：Arctic Shift API（https://arctic-shift.photon-reddit.com/api/）
          ※ 第三方 Reddit 歷史存檔服務，非 Reddit 官方 API
          ※ 錯誤格式特殊：永遠回 HTTP 200，錯誤訊息塞在 JSON body 內
             → 需自行檢查 data.get("error")，HTTP retry 攔不到這類錯誤
  GET /posts/search
      ?subreddit=investing
      &limit=100        # 每頁上限 100（API 硬性上限，寫死於 _PAGE_LIMIT）
      &after=TIMESTAMP  # Unix timestamp，只拿此時間之後的貼文
      &before=TIMESTAMP # Unix timestamp，只拿此時間之前的貼文
      &sort=asc         # 依發文時間升冪排列（asc / desc）

特性：
  - 免費，不需 API key
  - 可存取 Reddit 從 2005 年至今的完整存檔（約 20 年歷史）
  - 每頁 100 筆，cursor 分頁（after timestamp）
  - 不支援 r/a+b+c 合併語法，需逐一查詢各 subreddit

執行方式：
  python3 -m scrapers.reddit_batch_loader                        # 預設：抓 Reddit 全歷史（2005～今）
  python3 -m scrapers.reddit_batch_loader 2022-01-01 2023-12-31  # 指定日期範圍
"""

import sys
import logging
import time
from datetime import datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

import requests
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from scrapers.scraper_schemas import ArticleSchema
from config import SOURCES, MAX_RETRY, REQUEST_DELAY
REDDIT_BATCH_HISTORY_START  = "2005-01-01" # Reddit 創立年份，批量歷史抓取的起點

_SOURCE     = SOURCES["reddit"]
_API_URL    = "https://arctic-shift.photon-reddit.com/api/posts/search"
_HEADERS    = {"User-Agent": "ptt-sentiment-bot/1.0"}
# Reddit batch API 不支援 r/a+b+c 語法，需逐一查詢
_SUBREDDITS = [sub.strip() for sub in _SOURCE["subreddits"].split("+")]
_PAGE_LIMIT  = 100   # API 硬性上限，不可超過，非使用者可調參數


class RedditBatchLoader(BaseScraper):
    """
    Reddit 歷史批量資料載入器。

    繼承 BaseScraper 以復用 _save_to_db / _load_urls / _get_or_create_source。
    fetch_articles() 接受日期範圍，每次抓取指定區間的歷史貼文。
    """

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self, after: datetime, before: datetime) -> list:
        """
        抓取 after～before 之間的歷史貼文（回傳 list，供測試用）。
        正式批量載入請用 run_range()，可逐 subreddit 寫入，避免記憶體堆積。
        """
        urls = self._load_urls()# get article url
        all_articles = []
        for subreddit in _SUBREDDITS:
            all_articles.extend(self._fetch_subreddit(subreddit, after, before, urls))
        return all_articles

    def _fetch_subreddit(self, subreddit: str, after: datetime, before: datetime, urls: set) -> list:
        """抓取單一 subreddit(類似ptt的分版) 的歷史貼文"""
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
                error = data.get("error")# 處理json內部本身error message
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

                # 下一頁 cursor：取本頁最後一筆的 created_utc(html timestamp欄位) + 1
                last_ts = posts[-1].get("created_utc", cursor_after)    
                if last_ts <= cursor_after:
                    break  # 防止無限迴圈
                cursor_after = last_ts + 1

                page += 1
                # 更新進度條
                pbar.update(1)
                pbar.set_postfix({"累計": len(articles), "最新日期": datetime.fromtimestamp(last_ts).date()})
                time.sleep(REQUEST_DELAY)

        return articles

    def run_range(self, after: datetime, before: datetime) -> None:
        """
        批量載入指定日期範圍。
        每個 subreddit 抓完立即寫入 DB，避免大量資料堆積記憶體。
        若中途 crash，已完成的 subreddit 資料不會遺失。
        """
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
        """預設執行：補抓 Reddit 全歷史（REDDIT_BATCH_HISTORY_START ～ 今）"""
        before = datetime.utcnow()
        after  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
        self.run_range(after, before)


    def _parse_post(self, post: dict, urls: set) -> Optional[dict]:
        """解析單篇 Reddit batch 貼文，格式與 reddit_scraper 相同"""
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

        created_utc = post.get("created_utc")# html timestamp欄位
        try:
            published_at = datetime.utcfromtimestamp(float(created_utc))
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
        try:
            ArticleSchema(**article)
        except Exception as e:
            logging.warning(f"Reddit batch 驗證失敗，略過 {url}：{e}")
            return None
        return article



if __name__ == "__main__":
    # sys.argv[0] = 腳本名稱，argv[1] = after 日期，argv[2] = before 日期
    if len(sys.argv) == 3:
        after_dt  = datetime.strptime(sys.argv[1], "%Y-%m-%d")
        before_dt = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    else:
        # 預設：從 config.REDDIT_BATCH_HISTORY_START 至今
        before_dt = datetime.utcnow()
        after_dt  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
        logging.info(f"未指定日期，預設抓取 Reddit 全歷史：{after_dt.date()} ～ {before_dt.date()}")

    RedditBatchLoader().run_range(after_dt, before_dt)
