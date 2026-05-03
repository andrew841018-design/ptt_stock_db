import sys
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper
from config import SOURCES, MAX_RETRY, REQUEST_DELAY
SKIP_KEYWORDS = ["公告", "盤後閒聊", "盤中閒聊", "情報"]

_SOURCE = SOURCES["ptt"]  # 只讀一次，避免 dict 到處散落


class PttScraper(BaseScraper):
    """
    PTT Stock 板爬蟲。
    實作 BaseScraper 的兩個抽象方法：
      - get_source_info() → 來源名稱與 URL
      - fetch_articles()  → 爬取所有文章，回傳標準格式 list[dict]
    DB 寫入由 BaseScraper.run() 統一處理。
    """

    PTT_BASE_URL = "https://www.ptt.cc"
    HEADERS = {"cookie": "over18=1"}  # PTT 需要 over18 cookie 才能瀏覽
    # EARLY_STOP_PAGES 走 config（ptt / cnyes 共用）；若要 PTT 專屬覆蓋，改指定數字即可
    from config import EARLY_STOP_EMPTY_PAGES as EARLY_STOP_PAGES

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
        """
        從 PTT Stock 板爬取 num_pages 頁，回傳標準格式文章 list。
        增量爬取：先載入 DB 已有的 URL，遇到已知文章跳過 HTTP 請求，
        連續 EARLY_STOP_PAGES 頁全為已知文章時提早結束。
        """
        known_urls = self._load_urls()
        logging.info(f"PTT 載入已知 URL：{len(known_urls)} 筆")

        articles = []
        url = f"{_SOURCE['url']}/index.html"
        consecutive_empty_pages = 0

        for page_num in tqdm(range(_SOURCE["num_pages"]), desc="PTT 爬蟲頁數", file=sys.stderr):
            try:
                page_articles, next_url = self._scrape_list_page(url, known_urls)
                articles.extend(page_articles)

                if not page_articles:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= self.EARLY_STOP_PAGES:
                        logging.info(f"PTT 連續 {consecutive_empty_pages} 頁無新文章，停止")
                        break
                else:
                    consecutive_empty_pages = 0

                if not next_url:
                    logging.info("已到最舊頁，停止爬取")
                    break
                url = self.PTT_BASE_URL + next_url
            except requests.RequestException as e:
                logging.warning(f"第 {page_num + 1} 頁請求失敗：{e}，略過")
                continue

        return articles

    def _scrape_list_page(self, url: str, known_urls: set) -> tuple:
        """
        爬一頁列表，回傳 (articles_list, prev_page_url)。
        articles_list: 該頁成功爬取的文章（標準格式）
        prev_page_url: 上一頁的 href（已到底時回傳 None）
        """
        response = self._get_with_retry(url, headers=self.HEADERS)
        soup = BeautifulSoup(response.text, "html.parser")

        # 找「上頁」連結（往更舊的方向爬）
        prev_url = self._get_previous_page_url(soup)

        articles = []
        for item in soup.find_all("div", class_="r-ent"):
            article = self._parse_article_html(item, known_urls)
            if article:
                articles.append(article)

        return articles, prev_url

    def _get_previous_page_url(self, soup: BeautifulSoup):
        """從頁面導覽列取得「上頁」的 href，找不到回傳 None"""
        nav = soup.find_all("div", class_="btn-group-paging")
        for group in nav:
            prev_tag = group.find("a", string=lambda t: t and "上頁" in t)
            if prev_tag:
                return prev_tag.get("href")
        return None

    def _parse_article_html(self, item, known_urls: set) -> Optional[dict]:
        """
        解析列表頁的單筆 r-ent，回傳標準格式 dict。
        無效文章（被刪除、符合過濾關鍵字、已爬過、內文爬取失敗）回傳 None。
        """
        title_tag  = item.find("div", class_="title")
        author_tag = item.find("div", class_="author")
        nrec_tag   = item.find("div", class_="nrec")

        # 被刪除的文章沒有 <a>
        a_tag = title_tag.find("a") if title_tag else None
        if not a_tag:
            return None

        # 過濾公告、閒聊等不相關文章
        if any(keyword in title_tag.text for keyword in SKIP_KEYWORDS):
            return None

        article_url = self.PTT_BASE_URL + a_tag.get("href")

        # 已爬過的文章直接跳過，不再發 HTTP 請求
        if article_url in known_urls:
            return None

        content_data = self._scrape_article_content(article_url)
        if not content_data:
            return None

        push_txt = nrec_tag.text.strip() if nrec_tag and nrec_tag.text.strip() else "0"

        article = {
            "title":        title_tag.text.strip(),
            "content":      content_data["content"],
            "url":          article_url,
            "author":       author_tag.text.strip() if author_tag else None,
            "published_at": self._extract_published_at(article_url),
            "push_count":   self._parse_push_count(push_txt),
            "comments":     content_data["comments"],
        }
        if not self.validate_article(article, "PTT"):
            return None
        return article

    def _scrape_article_content(self, url: str) -> Optional[dict]:
        """
        爬文章內頁，回傳 {'content': str, 'comments': list[dict]}。
        失敗回傳 None。
        """
        try:
            response = self._get_with_retry(url, headers=self.HEADERS)
        except requests.RequestException as e:
            logging.warning(f"文章內頁請求失敗（重試 {MAX_RETRY} 次後放棄）{url}：{e}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        main_content = soup.find("div", id="main-content")
        if not main_content:
            return None

        # ── 先抓推文（decompose 前）────────────────────────────────────
        comments = []
        for push in main_content.find_all("div", class_="push"):
            user_id    = push.find("span", class_="push-userid")
            push_tag   = push.find("span", class_="push-tag")
            message    = push.find("span", class_="push-content")
            if not (user_id and push_tag and message):
                continue
            comments.append({
                "author":   user_id.text.strip(),
                "push_tag": push_tag.text.strip(),
                "message":  message.text.strip(),
            })

        # ── 移除非正文區塊，取純文字 ──────────────────────────────────
        for tag in main_content.find_all("div", class_="push"):
            tag.decompose()
        for tag in main_content.find_all("div", class_=lambda c: c and "article" in c):
            tag.decompose()
        for tag in main_content.find_all("span", class_="f2"):
            tag.decompose()

        lines = []
        for line in main_content.text.strip().split("\n"):
            if "引述" in line:
                continue
            if line.startswith(": ") or line.startswith("http"):
                continue
            if line.strip():
                lines.append(line.strip())

        time.sleep(REQUEST_DELAY)
        return {"content": "\n".join(lines), "comments": comments}

    @staticmethod
    def _parse_push_count(text: str) -> int:
        """PTT 推文數文字轉整數"""
        text = text.strip()
        try:
            if text == "爆":      # 推文 >= 100
                return 100
            elif text == "XX":   # 噓文 <= -100
                return -100
            elif text.startswith("X"):  # 噓文 -10 ~ -90，如 X1=−10, X9=−90
                return -int(text[1:]) * 10
            else:                # 一般數字
                return int(text)
        except ValueError:
            logging.warning(f"無法解析推文數：{text!r}")
            return None
    @staticmethod
    def _extract_published_at(url: str) -> Optional[datetime]:
        """從 PTT 文章 URL 的 Unix timestamp 提取發文時間"""
        match = re.search(r'M\.(\d+)\.', url)
        if match:
            return BaseScraper.ts_to_dt(int(match.group(1)))  # staticmethod 無 self，直接走 class
        return None
