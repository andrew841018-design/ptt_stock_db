"""
reparse.py — 資料修復管線

流程：
  1. diagnose()  掃 PostgreSQL，找出有 NULL 關鍵欄位的文章
  2. 用 URL 從 MongoDB raw_responses 取回原始 HTTP 回應
  3. 依來源（ptt / cnyes / reddit）re-parse 出正確值
  4. UPDATE PostgreSQL（只更新非 None 的欄位，不覆蓋好資料）
  5. 回傳 {"repaired": N}

使用方式：
  from reparse import repair
  result = repair()
  print(result["repaired"])
"""

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

# 每次最多修復的筆數（避免一次佔用太多資源）
_BATCH_SIZE = 500


def diagnose() -> list[dict]:
    """
    掃 PostgreSQL，回傳有 NULL 關鍵欄位的文章清單。
    每筆格式：{"article_id": int, "url": str, "source_name": str, "bad_fields": list[str]}
    """
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
        # article_id=row[0], url=row[1], source_name=row[2], *values=row[3:]
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
    """
    從 MongoDB raw_doc 的 raw_html 重新解析 PTT 文章內頁。
    回傳可用於 UPDATE 的 dict（只含非 None 的欄位）。
    """
    raw_html = raw_doc.get("raw_html")
    if not raw_html:
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    main_content = soup.find("div", id="main-content")
    if not main_content:
        return None

    # 推文先取，再 decompose
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

    # published_at 從 URL 中的 Unix timestamp 提取
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
    """
    從 MongoDB raw_doc 的 raw_json 重新解析鉅亨網文章。
    raw_json 是 API list 回應，需找到與 url 匹配的 newsId。
    回傳可用於 UPDATE 的 dict（只含非 None 的欄位）。
    """
    raw_json_str = raw_doc.get("raw_json")
    if not raw_json_str:
        return None

    try:
        data = json.loads(raw_json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    # url 格式：https://news.cnyes.com/news/id/{newsId}
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
    """
    從 MongoDB raw_doc 的 raw_json 重新解析 Reddit 貼文。
    raw_json 是 Reddit API listing 回應，需找到與 url 匹配的 post。
    回傳可用於 UPDATE 的 dict（只含非 None 的欄位）。
    """
    raw_json_str = raw_doc.get("raw_json")
    if not raw_json_str:
        return None

    try:
        data = json.loads(raw_json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    # url 格式：https://www.reddit.com/r/investing/comments/{post_id}/{title_slug}/
    post_id_match = re.search(r'/comments/(\w+)/', url)
    if not post_id_match:
        return None
    target_id = post_id_match.group(1)

    # Reddit API response：{"data": {"children": [{"data": {post fields...}}]}}
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


def _update_article(article_id: int, fields: dict) -> None:
    """UPDATE articles 表，只更新 fields 中非 None 的欄位"""
    if not fields:
        return
    # for col in fields 只取 dict 的 key（欄位名），用來組 SQL SET 子句
    # fields = {"title": "...", "content": "..."} 
    set_clause = ", ".join(f"{col} = %s" for col in fields)
    # .values() 取 dict 的所有 value，尾巴加上 article_id 對應 WHERE 的 %s
    # ["...", "...", 42] → 依序對應 SET 裡的兩個 %s 和 WHERE 的一個 %s
    values = list(fields.values()) + [article_id]
    with get_pg() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {ARTICLES_TABLE} SET {set_clause} WHERE article_id = %s",
                values,
            )


def repair() -> dict:
    """
    主修復函式。
    1. 找出有 NULL 關鍵欄位的文章
    2. 從 MongoDB raw_responses 取回原始回應
    3. 依來源 re-parse
    4. UPDATE PostgreSQL

    回傳：{"repaired": N}
    """
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
            # find_one第一筆是條件，第二筆是回傳的欄位，_id:0是不要回傳_id
            raw_doc = col.find_one({"url": url}, {"_id": 0})
            if not raw_doc:
                logging.debug("[reparse] MongoDB 無 raw：%s", url)
                continue

            if source_name == "ptt":
                fields = _reparse_ptt(raw_doc, url)
            elif source_name == "cnyes":
                fields = _reparse_cnyes(raw_doc, url)
            elif source_name == "reddit":
                fields = _reparse_reddit(raw_doc, url)
            else:
                logging.debug("[reparse] 不支援來源 %s 的 re-parse", source_name)
                continue

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

