
import json
import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from config import ARTICLES_TABLE, SOURCES_TABLE
from mongo_helper import get_mongo, RAW_RESPONSES
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_BATCH_SIZE = 500

_HTML_CONTENT_SELECTORS = {
    "cnn": [
        "div.article__content",
        "div.zn-body__paragraph",
        "section.body-text",
    ],
    "wsj": [
        "div.article-content",
        "div.wsj-snippet-body",
        "section[data-testid='article-body']",
    ],
    "marketwatch": [
        "div.article__body",
        "div#js-article__body",
        "div[data-testid='article-body']",
        "div.body",
    ],
}


def diagnose() -> list[dict]:
    bad_articles = []
    null_columns = ("title", "content", "published_at")

    with get_pg() as conn:
        with conn.cursor() as cursor:
            conditions = " OR ".join(f"a.{col} IS NULL" for col in null_columns)
            cursor.execute(f"""
                SELECT a.article_id, a.url, s.source_name,
                       {", ".join(f"a.{col}" for col in null_columns)}
                FROM {ARTICLES_TABLE} a
                JOIN {SOURCES_TABLE} s ON s.source_id = a.source_id
                WHERE {conditions}
                LIMIT %s
            """, (_BATCH_SIZE,))

            rows = cursor.fetchall()

    for row in rows:
        article_id, url, source_name, *values = row
        bad_fields = [col for col, val in zip(null_columns, values) if val is None]
        bad_articles.append({
            "article_id":  article_id,
            "url":         url,
            "source_name": source_name,
            "bad_fields":  bad_fields,
        })

    logging.info("[reparse] diagnose：找到 %d 篇需修復的文章", len(bad_articles))
    return bad_articles


def _reparse_ptt(raw_doc: dict, url: str) -> Optional[dict]:
    raw_html = raw_doc.get("raw_html")
    if not raw_html:
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    main_content = soup.find("div", id="main-content")
    if not main_content:
        return None

    comments = []
    for push in main_content.find_all("div", class_="push"):
        user_id  = push.find("span", class_="push-userid")
        push_tag = push.find("span", class_="push-tag")
        message  = push.find("span", class_="push-content")
        if user_id and push_tag and message:
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

    lines = [
        line.strip()
        for line in main_content.text.strip().split("\n")
        if line.strip()
        and "引述" not in line
        and not line.startswith(": ")
        and not line.startswith("http")
    ]
    content = "\n".join(lines) or None

    published_at = None
    match = re.search(r'M\.(\d+)\.', url)
    if match:
        published_at = datetime.utcfromtimestamp(int(match.group(1)))

    result = {}
    if content:
        result["content"] = content
    if published_at:
        result["published_at"] = published_at

    return result or None


def _reparse_cnyes(raw_doc: dict, url: str) -> Optional[dict]:
    raw_json_str = raw_doc.get("raw_json")
    if not raw_json_str:
        return None

    try:
        data = json.loads(raw_json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    news_id_match = re.search(r'/news/id/(\d+)', url)
    if not news_id_match:
        return None
    target_id = int(news_id_match.group(1))

    items = data.get("items", {}).get("data", [])
    item = next((i for i in items if i.get("newsId") == target_id), None)
    if not item:
        return None

    html_content = item.get("content") or item.get("summary", "")
    content = BeautifulSoup(html_content, "html.parser").get_text(separator="\n").strip() if html_content else None

    publish_at = item.get("publishAt")
    published_at = datetime.utcfromtimestamp(publish_at) if publish_at else None

    title = (item.get("title") or "").strip() or None

    result = {}
    if title:
        result["title"] = title
    if content:
        result["content"] = content
    if published_at:
        result["published_at"] = published_at

    return result or None


def _reparse_reddit(raw_doc: dict, url: str) -> Optional[dict]:
    raw_json_str = raw_doc.get("raw_json")
    if not raw_json_str:
        return None

    try:
        data = json.loads(raw_json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    post_id_match = re.search(r'/comments/(\w+)/', url)
    if not post_id_match:
        return None
    target_id = post_id_match.group(1)

    children = data.get("data", {}).get("children", [])
    post = next(
        (child["data"] for child in children
         if child.get("data", {}).get("id") == target_id),
        None,
    )
    if not post:
        return None

    title = (post.get("title") or "").strip() or None

    content = (post.get("selftext") or "").strip()
    if content in ("[removed]", "[deleted]"):
        content = None
    content = content or None

    published_at = None
    created_utc = post.get("created_utc")
    if created_utc:
        try:
            published_at = datetime.utcfromtimestamp(float(created_utc))
        except (ValueError, TypeError):
            pass

    result = {}
    if title:
        result["title"] = title
    if content:
        result["content"] = content
    if published_at:
        result["published_at"] = published_at

    return result or None


def _parse_iso_datetime(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _reparse_html_news(raw_doc: dict, url: str, source_name: str) -> Optional[dict]:
    raw_html = raw_doc.get("raw_html")
    if not raw_html:
        return None

    soup = BeautifulSoup(raw_html, "html.parser")

    selectors = _HTML_CONTENT_SELECTORS.get(source_name, [])
    paragraphs = []
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            paragraphs = container.find_all("p")
            break
    if not paragraphs:
        article_tag = soup.find("article")
        if article_tag:
            paragraphs = article_tag.find_all("p")

    content = "\n".join(
        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
    )
    content = content if content else None

    title = None
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = (og_title.get("content") or "").strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
    title = title or None

    published_at = None
    for attr in ("property", "name"):
        for meta_name in ("article:published_time", "publishdate", "datePublished"):
            meta = soup.find("meta", attrs={attr: meta_name})
            if meta and meta.get("content"):
                published_at = _parse_iso_datetime(meta["content"])
                if published_at:
                    break
        if published_at:
            break

    if not published_at:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string)
                date_str = ld.get("datePublished") or ld.get("dateCreated")
                if date_str:
                    published_at = _parse_iso_datetime(date_str)
                    if published_at:
                        break
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

    result = {}
    if title:
        result["title"] = title
    if content:
        result["content"] = content
    if published_at:
        result["published_at"] = published_at
    return result or None


_REPARSERS = {
    "ptt":         _reparse_ptt,
    "cnyes":       _reparse_cnyes,
    "reddit":      _reparse_reddit,
    "cnn":         lambda doc, url: _reparse_html_news(doc, url, "cnn"),
    "wsj":         lambda doc, url: _reparse_html_news(doc, url, "wsj"),
    "marketwatch": lambda doc, url: _reparse_html_news(doc, url, "marketwatch"),
}


def _update_article(article_id: int, fields: dict) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [article_id]
    with get_pg() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {ARTICLES_TABLE} SET {set_clause} WHERE article_id = %s",
                values,
            )


def repair() -> dict:
    bad_articles = diagnose()
    if not bad_articles:
        logging.info("[reparse] 無需修復")
        return {"repaired": 0}

    repaired = 0

    with get_mongo() as db:
        col = db[RAW_RESPONSES]

        for article in bad_articles:
            url         = article["url"]
            source_name = article["source_name"]
            article_id  = article["article_id"]
            raw_doc = col.find_one({"url": url}, {"_id": 0})
            if not raw_doc:
                logging.debug("[reparse] MongoDB 無 raw：%s", url)
                continue

            reparser = _REPARSERS.get(source_name)
            if not reparser:
                logging.debug("[reparse] 不支援來源 %s 的 re-parse", source_name)
                continue
            fields = reparser(raw_doc, url)

            if not fields:
                logging.debug("[reparse] re-parse 結果為空：%s", url)
                continue

            try:
                _update_article(article_id, fields)
                repaired += 1
                logging.info("[reparse] 修復成功（id=%d）：%s", article_id, list(fields.keys()))
            except Exception as e:
                logging.warning("[reparse] UPDATE 失敗（id=%d）：%s", article_id, e)

    logging.info("[reparse] 修復完成，共修復 %d 筆", repaired)
    return {"repaired": repaired}

