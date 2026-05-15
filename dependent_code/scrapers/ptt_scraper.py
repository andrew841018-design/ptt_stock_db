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

_SOURCE = SOURCES["ptt"]


class PttScraper(BaseScraper):

    PTT_BASE_URL = "https://www.ptt.cc"
    HEADERS = {"cookie": "over18=1"}
    from config import EARLY_STOP_EMPTY_PAGES as EARLY_STOP_PAGES

    def get_source_info(self) -> dict:
        return {"name": _SOURCE["name"], "url": _SOURCE["url"]}

    def fetch_articles(self) -> list:
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
        response = self._get_with_retry(url, headers=self.HEADERS)
        soup = BeautifulSoup(response.text, "html.parser")

        prev_url = self._get_previous_page_url(soup)

        articles = []
        for item in soup.find_all("div", class_="r-ent"):
            article = self._parse_article_html(item, known_urls)
            if article:
                articles.append(article)

        return articles, prev_url

    def _get_previous_page_url(self, soup: BeautifulSoup):
        nav = soup.find_all("div", class_="btn-group-paging")
        for group in nav:
            prev_tag = group.find("a", string=lambda t: t and "上頁" in t)
            if prev_tag:
                return prev_tag.get("href")
        return None

    def _parse_article_html(self, item, known_urls: set) -> Optional[dict]:
        title_tag  = item.find("div", class_="title")
        author_tag = item.find("div", class_="author")
        nrec_tag   = item.find("div", class_="nrec")

        a_tag = title_tag.find("a") if title_tag else None
        if not a_tag:
            return None

        if any(keyword in title_tag.text for keyword in SKIP_KEYWORDS):
            return None

        article_url = self.PTT_BASE_URL + a_tag.get("href")

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
        try:
            response = self._get_with_retry(url, headers=self.HEADERS)
        except requests.RequestException as e:
            logging.warning(f"文章內頁請求失敗（重試 {MAX_RETRY} 次後放棄）{url}：{e}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        main_content = soup.find("div", id="main-content")
        if not main_content:
            return None

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
    def _parse_push_count(text: str) -> Optional[int]:
        text = text.strip()
        try:
            if text == "爆":
                return 100
            elif text == "XX":
                return -100
            elif text.startswith("X"):
                return -int(text[1:]) * 10
            else:
                return int(text)
        except ValueError:
            logging.warning(f"無法解析推文數：{text!r}")
            return None
    @staticmethod
    def _extract_published_at(url: str) -> Optional[datetime]:
        match = re.search(r'M\.(\d+)\.', url)
        if match:
            return BaseScraper.ts_to_dt(int(match.group(1)))
        return None
