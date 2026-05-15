
import re
import sys
import json
import string
import logging
import requests
import concurrent.futures
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from tqdm import tqdm

_FETCH_WORKERS = 4
_PROBE_WORKERS = 2
_FETCH_CHUNK_SIZE = 50

from scrapers.base_scraper import BaseScraper
from config import DEFAULT_HEADERS as _HEADERS


_TRACKING_QUERY_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_name", "utm_id", "utm_brand", "utm_social", "utm_social-type",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "ref", "refsrc", "cid", "ocid", "src", "source",
    "mc_cid", "mc_eid",
    "icid", "ncid",
    "ampcid", "amp_js_v",
    "mod", "st",
})


_CDX_URL = "https://web.archive.org/cdx/search/cdx"
_SNAPSHOT_TEMPLATE = "https://web.archive.org/web/{timestamp}id_/{url}"

_CDX_ROWS_PER_SLICE = 1000

_PROBE_LOG_EVERY = 10

_HTTP_TIMEOUT = 120

_DEFAULT_START_YEAR = 2015
_DEFAULT_END_YEAR   = datetime.utcnow().year

_WSJ_PREFIX_LETTERS = list(string.ascii_lowercase) + list(string.digits)


class WaybackBackfillScraper(BaseScraper):

    def __init__(self,
                 source: str = "cnn",
                 start_year: int = _DEFAULT_START_YEAR,
                 end_year: int = _DEFAULT_END_YEAR,
                 max_articles: Optional[int] = None):
        if source not in ("cnn", "wsj"):
            raise ValueError(f"Unknown source: {source}. Must be 'cnn' or 'wsj'")
        if start_year > end_year:
            raise ValueError(f"start_year ({start_year}) > end_year ({end_year})")
        self._source       = source
        self._start_year   = start_year
        self._end_year     = end_year
        self._max_articles = max_articles

        if source == "cnn":
            self._source_name = "wayback_cnn"
            self._source_url  = "https://www.cnn.com"
            self._url_regex   = re.compile(r"^https?://(www\.|edition\.)?cnn\.com/\d{4}/\d{2}/\d{2}/")
        else:
            self._source_name = "wayback_wsj"
            self._source_url  = "https://www.wsj.com"
            self._url_regex   = re.compile(r"^https?://(www\.)?wsj\.com/articles/")

    def get_source_info(self) -> dict:
        return {"name": self._source_name, "url": self._source_url}

    _SAVE_BATCH = 25

    def run(self) -> None:
        from pg_helper import get_pg
        source = self.get_source_info()
        logging.info(f"開始爬取：{source['name']}（並行 fetch + serial save，{_FETCH_WORKERS} workers）")

        targets, known_urls = self._collect_targets()
        if not targets:
            logging.info(f"{self._source_name} 無新 URL 可抓")
            return

        seen_canonical = {self._canonicalize_url(u) for u in known_urls}
        saved = 0
        total = len(targets)
        with get_pg() as conn:
            with conn.cursor() as cursor:
                source_id = self._get_or_create_source(cursor, source['name'], source['url'])
                pbar = tqdm(total=total, desc=f"{self._source_name} fetch+save", file=sys.stderr)
                for i in range(0, total, _FETCH_CHUNK_SIZE):
                    if self._max_articles is not None and saved >= self._max_articles:
                        logging.info(f"{self._source_name} 達到 max_articles={self._max_articles}，停止")
                        break
                    chunk = targets[i:i + _FETCH_CHUNK_SIZE]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
                        futures = {
                            ex.submit(self._fetch_snapshot, ts, original_url): canonical
                            for ts, original_url, canonical in chunk
                        }
                        for fut in concurrent.futures.as_completed(futures):
                            canonical = futures[fut]
                            pbar.update(1)
                            try:
                                article = fut.result()
                            except Exception as e:
                                logging.debug(f"{self._source_name} fetch 失敗 {canonical}: {e}")
                                continue
                            if not article:
                                continue
                            self._save_one_to_raw(cursor, article)
                            if self._is_duplicate(cursor, article['url']):
                                continue
                            if self._insert_article(cursor, source_id, article):
                                saved += 1
                                seen_canonical.add(canonical)
                                if saved % self._SAVE_BATCH == 0:
                                    conn.commit()
                                    logging.info(f"{self._source_name} 已寫入 DB {saved} 篇")
                conn.commit()
                pbar.close()
        logging.info(f"完成：{source['name']}，本次新增 {saved} 篇（parallel）")

    def _collect_targets(self):
        known_urls = self._load_urls()
        logging.info(f"{self._source_name} 載入已知 URL：{len(known_urls)} 筆")

        snapshots_by_canonical: dict = {}
        slices = list(self._build_slices())
        logging.info(f"{self._source_name} 共 {len(slices)} 個 CDX slice 待 probe")

        seen_canonical = {self._canonicalize_url(u) for u in known_urls}
        new_url_count = 0
        pbar = tqdm(total=len(slices), desc=f"{self._source_name} CDX probe", file=sys.stderr)
        idx = 0
        for chunk_start in range(0, len(slices), _PROBE_WORKERS * 2):
            chunk = slices[chunk_start:chunk_start + _PROBE_WORKERS * 2]
            with concurrent.futures.ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as ex:
                futures = {ex.submit(self._probe_slice, prefix): prefix for prefix in chunk}
                for fut in concurrent.futures.as_completed(futures):
                    idx += 1
                    pbar.update(1)
                    try:
                        result = fut.result()
                    except Exception as e:
                        logging.warning(f"{self._source_name} probe slice 失敗 {futures[fut]}: {e}")
                        continue
                    for ts, url in result:
                        canonical = self._canonicalize_url(url)
                        existing = snapshots_by_canonical.get(canonical)
                        if existing is None or ts < existing[0]:
                            snapshots_by_canonical[canonical] = (ts, url)
                            if canonical not in seen_canonical:
                                new_url_count += 1
                    if idx % _PROBE_LOG_EVERY == 0 or idx == len(slices):
                        logging.info(
                            f"{self._source_name} CDX slice {idx}/{len(slices)}, "
                            f"累積 {len(snapshots_by_canonical)} 個唯一 URL（{new_url_count} 篇新）"
                        )
            if self._max_articles is not None and new_url_count >= int(self._max_articles * 1.2):
                logging.info(f"{self._source_name} probe early stop at slice {idx}/{len(slices)}")
                break
        pbar.close()

        targets = [
            (ts, original_url, canonical)
            for canonical, (ts, original_url) in snapshots_by_canonical.items()
            if canonical not in seen_canonical
        ]
        logging.info(f"{self._source_name} 共發現 {len(targets)} 篇待抓")
        return targets, known_urls

    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info(f"{self._source_name} 載入已知 URL：{len(known_urls)} 筆")

        snapshots_by_canonical: dict = {}
        slices = list(self._build_slices())
        logging.info(f"{self._source_name} 共 {len(slices)} 個 CDX slice 待 probe")

        seen_canonical = {self._canonicalize_url(u) for u in known_urls}
        new_url_count = 0

        for idx, prefix in enumerate(tqdm(slices, desc=f"{self._source_name} CDX probe", file=sys.stderr), start=1):
            slice_snapshots = self._probe_slice(prefix)
            for ts, url in slice_snapshots:
                canonical = self._canonicalize_url(url)
                existing = snapshots_by_canonical.get(canonical)
                if existing is None or ts < existing[0]:
                    snapshots_by_canonical[canonical] = (ts, url)
                    if canonical not in seen_canonical:
                        new_url_count += 1

            if idx % _PROBE_LOG_EVERY == 0 or idx == len(slices):
                logging.info(
                    f"{self._source_name} CDX slice {idx}/{len(slices)}, "
                    f"累積 {len(snapshots_by_canonical)} 個唯一 URL（其中 {new_url_count} 篇新）"
                )

            if self._max_articles is not None and new_url_count >= int(self._max_articles * 1.2):
                logging.info(
                    f"{self._source_name} probe early stop at slice {idx}/{len(slices)}: "
                    f"new URL 已 {new_url_count} ≥ {int(self._max_articles * 1.2)}（max_articles × 1.2）"
                )
                break

        logging.info(f"{self._source_name} CDX 共發現 {len(snapshots_by_canonical)} 個唯一文章 URL")

        articles = []
        targets = [
            (ts, original_url, canonical)
            for canonical, (ts, original_url) in snapshots_by_canonical.items()
            if canonical not in seen_canonical
        ]

        for timestamp, original_url, canonical in tqdm(
                targets,
                desc=f"{self._source_name} fetch snapshots",
                file=sys.stderr):
            if self._max_articles is not None and len(articles) >= self._max_articles:
                logging.info(f"{self._source_name} 達到 max_articles={self._max_articles}，停止")
                break
            article = self._fetch_snapshot(timestamp, original_url)
            if article:
                articles.append(article)
                seen_canonical.add(canonical)

        logging.info(f"{self._source_name} 本次共取得 {len(articles)} 篇新文章")
        return articles

    def _build_slices(self):
        for year in range(self._start_year, self._end_year + 1):
            if self._source == "cnn":
                for month in range(1, 13):
                    yield f"www.cnn.com/{year}/{month:02d}/"
                    yield f"edition.cnn.com/{year}/{month:02d}/"
            else:
                frm = f"{year}0101"
                to  = f"{year}1231"
                for letter in _WSJ_PREFIX_LETTERS:
                    yield ("wsj", f"www.wsj.com/articles/{letter}", frm, to)

    def _probe_slice(self, slice_info) -> list:
        if isinstance(slice_info, str):
            prefix = slice_info
            params = {
                "url":       prefix,
                "matchType": "prefix",
                "output":    "json",
                "collapse":  "urlkey",
                "filter":    ["statuscode:200", "mimetype:text/html"],
                "limit":     _CDX_ROWS_PER_SLICE,
            }
        else:
            _, prefix, frm, to = slice_info
            params = {
                "url":       prefix,
                "matchType": "prefix",
                "from":      frm,
                "to":        to,
                "output":    "json",
                "collapse":  "urlkey",
                "filter":    ["statuscode:200", "mimetype:text/html"],
                "limit":     _CDX_ROWS_PER_SLICE,
            }
        try:
            response = self._get_with_retry(
                _CDX_URL,
                params=params,
                headers=_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            logging.warning(f"CDX slice 失敗 {self._source_name} {prefix}：{e}")
            return []

        body = response.text.strip()
        if not body:
            return []

        try:
            rows = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"CDX JSON 解析失敗 {self._source_name} {prefix}：{e}")
            return []

        if not rows or len(rows) <= 1:
            return []
        header = rows[0]
        try:
            ts_idx  = header.index("timestamp")
            url_idx = header.index("original")
        except ValueError as e:
            logging.warning(f"CDX header 格式異常 {self._source_name} {prefix}：{e}")
            return []

        snapshots = []
        for row in rows[1:]:
            if len(row) <= max(ts_idx, url_idx):
                continue
            original = row[url_idx]
            if not self._url_regex.match(original):
                continue
            snapshots.append((row[ts_idx], original))
        return snapshots

    def _fetch_snapshot(self, timestamp: str, original_url: str) -> Optional[dict]:
        snapshot_url = _SNAPSHOT_TEMPLATE.format(timestamp=timestamp, url=original_url)
        try:
            response = self._get_with_retry(
                snapshot_url,
                headers=_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            logging.warning(f"Wayback snapshot 抓取失敗 {snapshot_url}：{e}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        title = self._extract_title(soup)
        if not title:
            return None

        content = self._extract_content(soup)
        if not content:
            return None

        published_at = self._extract_publish_time(soup, timestamp, original_url)
        if not published_at:
            return None

        canonical_url = self._canonicalize_url(original_url)

        article = {
            "title":        title,
            "content":      content,
            "url":          canonical_url,
            "author":       None,
            "published_at": published_at,
            "push_count":   None,
            "comments":     [],
        }
        if not self.validate_article(article, "Wayback"):
            return None
        return article

    def _canonicalize_url(self, url: str) -> str:
        if not url:
            return url
        try:
            parts = urlparse(url)
            if not parts.scheme or not parts.netloc:
                return url

            scheme = "https"
            netloc = parts.netloc.lower()
            if netloc.endswith(":443") or netloc.endswith(":80"):
                netloc = netloc.rsplit(":", 1)[0]

            if parts.query:
                kept = [
                    (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                    if k.lower() not in _TRACKING_QUERY_PARAMS
                ]
                query = urlencode(kept)
            else:
                query = ""

            path = parts.path or "/"
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")

            return urlunparse((scheme, netloc, path, parts.params, query, ""))
        except Exception as e:
            logging.warning(f"URL canonicalize 失敗，回傳原 URL {url}：{e}")
            return url

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        for meta in (
            soup.find("meta", attrs={"property": "og:title"}),
            soup.find("meta", attrs={"name": "title"}),
        ):
            if meta and meta.get("content"):
                text = meta["content"].strip()
                if text:
                    return text

        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(strip=True)
            if text:
                return text

        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            for suffix in (" - CNN", " | CNN", " - WSJ", " | WSJ"):
                if text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
            if text:
                return text
        return None

    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        article_tag = soup.find("article")
        if article_tag:
            paragraphs = article_tag.find_all("p")
        else:
            container = (
                soup.find("div", class_=re.compile(r"article|story|content|body", re.I))
                or soup
            )
            paragraphs = container.find_all("p")

        if not paragraphs:
            return None

        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        if len(text) < 100:
            return None
        return text

    def _extract_publish_time(self,
                              soup: BeautifulSoup,
                              timestamp: str,
                              original_url: str) -> Optional[datetime]:
        for meta_name in ("article:published_time", "pubdate", "date", "DC.date.issued"):
            meta = (
                soup.find("meta", attrs={"property": meta_name})
                or soup.find("meta", attrs={"name": meta_name})
            )
            if meta and meta.get("content"):
                parsed = self._try_parse_datetime(meta["content"])
                if parsed:
                    return parsed

        time_tag = soup.find("time")
        if time_tag:
            dt_attr = time_tag.get("datetime") or time_tag.get_text(strip=True)
            if dt_attr:
                parsed = self._try_parse_datetime(dt_attr)
                if parsed:
                    return parsed

        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script_tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                pub = item.get("datePublished")
                if pub:
                    parsed = self._try_parse_datetime(pub)
                    if parsed:
                        return parsed

        url_match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", original_url)
        if url_match:
            try:
                return datetime(int(url_match.group(1)),
                                int(url_match.group(2)),
                                int(url_match.group(3)))
            except ValueError:
                pass

        if timestamp and len(timestamp) >= 8:
            try:
                return datetime.strptime(timestamp[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
            except ValueError:
                try:
                    return datetime.strptime(timestamp[:8], "%Y%m%d")
                except ValueError:
                    pass
        return None

    def _try_parse_datetime(self, date_str: str) -> Optional[datetime]:
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        cleaned = date_str.strip()
        for fmt in formats:
            try:
                parsed = datetime.strptime(cleaned, fmt)
                return parsed.replace(tzinfo=None)
            except ValueError:
                continue
        return None


