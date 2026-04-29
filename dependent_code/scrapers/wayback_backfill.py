"""
Wayback Machine backfill scraper：透過 Internet Archive CDX Server API 抓取
CNN / WSJ 的歷史文章，補足 RSS 無法回溯的長尾資料。

設計重點：
  - CDX API 大範圍 query（matchType=domain 或全年全網域）會觸發 504 Gateway Time-out
    解法：改用 **narrow prefix query**（`matchType=prefix`）並拆細切片
      - CNN：`/YYYY/MM/` 月份前綴（URL 本身就以日期分層）
      - WSJ：`/articles/{letter}-` 字首前綴（每月 × 26 letters + 數字）
  - 每個 slice limit=5000（前次用 15000 會 timeout）
  - 拿到 snapshot 後用 `web/{timestamp}id_/{url}` 取 raw HTML（不含 Wayback 工具列）
  - BeautifulSoup 解析 title / published_at / content
  - source 切換：__init__(source="cnn") 或 "wsj"，get_source_info() 回 wayback_cnn / wayback_wsj

與其他爬蟲的分工：
  - CnnScraper / WsjScraper：抓當下的 sitemap（近期文章）
  - WaybackBackfillScraper：補歷史（過去 N 年）
  - 兩者 URL 去重由 BaseScraper._is_duplicate() 統一處理
"""

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

# 與 pipeline.py extract() 同步的並行模式（ThreadPoolExecutor）
# 2026-04-29 實測：原 8 worker 因 base_scraper.get_with_retry 用 requests.get()
# 沒共用 Session 導致 8 條獨立 TCP，超 Wayback per-IP cap → ECONNREFUSED
# 已改 base_scraper 共用 _SESSION（pool_maxsize=20）+ backoff jitter，現可拉回 8/4
_FETCH_WORKERS = 8           # Phase 2：snapshot HTTP fetch 並行數
_PROBE_WORKERS = 4           # Phase 1：CDX slice probe 並行數
_FETCH_CHUNK_SIZE = 50       # max_articles 的早停粒度

from scrapers.base_scraper import BaseScraper
from config import DEFAULT_HEADERS as _HEADERS


# URL canonicalize 時要剝掉的 tracking query params（大小寫不敏感）
# 常見行銷/社群追蹤參數；CNN/WSJ 的正常文章 URL 本身不會依賴這些
_TRACKING_QUERY_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_name", "utm_id", "utm_brand", "utm_social", "utm_social-type",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "ref", "refsrc", "cid", "ocid", "src", "source",
    "mc_cid", "mc_eid",
    "icid", "ncid",                 # CNN 特有追蹤
    "ampcid", "amp_js_v",           # AMP 相關
    "mod", "st",                    # WSJ 常見
})


# ── CDX / Wayback endpoints ─────────────────────────────────────────────
_CDX_URL = "https://web.archive.org/cdx/search/cdx"
_SNAPSHOT_TEMPLATE = "https://web.archive.org/web/{timestamp}id_/{url}"

# 每個 slice（月+字首）最多拉 1000 筆
# （5000 仍常觸發 504；降到 1000 body 小 5x、response 更快；2026-04-19 修正）
_CDX_ROWS_PER_SLICE = 1000

# probe 階段每隔 N slice 輸出一次 logging.info 到 stdout，
# 避免 tqdm 進度條只寫 stderr 導致 launchd 看不到進度
_PROBE_LOG_EVERY = 10

# HTTP timeout（Wayback 回應較慢，給 120 秒）
_HTTP_TIMEOUT = 120

# 預設 backfill 年份範圍（可依需求調整）
_DEFAULT_START_YEAR = 2015
_DEFAULT_END_YEAR   = datetime.utcnow().year

# WSJ 文章 URL 結尾通常是 slug-{timestamp_id}；字首分布大致覆蓋 a-z 0-9
_WSJ_PREFIX_LETTERS = list(string.ascii_lowercase) + list(string.digits)


class WaybackBackfillScraper(BaseScraper):
    """
    Wayback Machine backfill scraper。
    繼承 BaseScraper，DB 寫入邏輯（去重、寫入 articles）由 base class 處理。

    __init__ 參數：
      source         -> "cnn" / "wsj"（切換 CDX 查詢目標與 source name）
      start_year     -> probe 起始年份（預設 2015）
      end_year       -> probe 結束年份（預設當年）
      max_articles   -> 上限（None = 無限制，有值時取到該數量就停；避免一次灌太多）

    Year range 注意事項：
      - CNN：2015–2024 CDX 都有資料（/YYYY/MM/DD/ 路徑格式，2021 後檔名 pattern 改為
        無 index.html 但 prefix query 仍然涵蓋）。超過當年可能 CDX 尚未索引。
      - WSJ：2015–2021 CDX 幾乎零命中（Wayback 對付費牆站爬得很少），2022+ 才明顯有量。
        想省時間可把 WSJ 的 start_year 直接從 2022 起跳。
    """

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

        # 各來源配置
        if source == "cnn":
            self._source_name = "wayback_cnn"
            self._source_url  = "https://www.cnn.com"
            self._url_regex   = re.compile(r"^https?://(www\.|edition\.)?cnn\.com/\d{4}/\d{2}/\d{2}/")
        else:  # wsj
            self._source_name = "wayback_wsj"
            self._source_url  = "https://www.wsj.com"
            self._url_regex   = re.compile(r"^https?://(www\.)?wsj\.com/articles/")

    def get_source_info(self) -> dict:
        return {"name": self._source_name, "url": self._source_url}

    # ── Streaming write override ──────────────────────────────────────
    # BaseScraper.run() 等 fetch_articles() 全跑完才一次寫 DB；wayback 經常被
    # 6h timeout 砍掉，導致數小時抓的資料全丟。改成「每抓到 N 篇就 commit」，
    # 即使中途被砍，已抓的部分都已落地。
    _SAVE_BATCH = 25

    def run(self) -> None:
        """並行 fetch + serial save 模式（套用 pipeline.extract() 同款 ThreadPoolExecutor）。

        架構：
          - Phase 2 fetch_snapshot 是 I/O bound（HTTP 到 web.archive.org）→ 用 ThreadPoolExecutor
          - DB cursor 不能跨 thread 共享 → save 仍 serial（main thread 從 future 結果取出再寫入）
          - max_articles 早停：以 _FETCH_CHUNK_SIZE 為單位 submit / drain，每 chunk 完檢查是否達標
        """
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
                # 分 chunk submit，避免一次 submit 全部讓 max_articles 早停失靈
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
        """Phase 1：CDX probe，回傳 (targets list, known_urls)。targets = [(timestamp, original_url, canonical), ...]"""
        known_urls = self._load_urls()
        logging.info(f"{self._source_name} 載入已知 URL：{len(known_urls)} 筆")

        snapshots_by_canonical: dict = {}
        slices = list(self._build_slices())
        logging.info(f"{self._source_name} 共 {len(slices)} 個 CDX slice 待 probe")

        seen_canonical = {self._canonicalize_url(u) for u in known_urls}
        new_url_count = 0
        # Phase 1 並行：CDX probe 每個 slice 是獨立 HTTP query
        # 用 ThreadPoolExecutor 並行 probe，主 thread 集中合併結果（dict 不能跨 thread 寫）
        # 早停：每 chunk 完才檢查 new_url_count（保留原 1.2x buffer 邏輯）
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
            # chunk 完才檢查早停（避免 chunk 中途 break 造成 thread leak）
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

    # ── 主流程（保留供測試 / backward compat） ────────────────────
    def fetch_articles(self) -> list:
        known_urls = self._load_urls()
        logging.info(f"{self._source_name} 載入已知 URL：{len(known_urls)} 筆")

        # 階段一：CDX 按 slice 收集 (original_url -> (timestamp, canonical_url))
        # dict key 用 canonical URL 去重 —— 同一篇文章 http / https 兩份快照合併成一條
        snapshots_by_canonical: dict = {}
        slices = list(self._build_slices())
        logging.info(f"{self._source_name} 共 {len(slices)} 個 CDX slice 待 probe")

        # seen URLs（canonical）— probe 階段就用來判斷 early stop 條件
        seen_canonical = {self._canonicalize_url(u) for u in known_urls}
        new_url_count = 0  # 累計尚未入庫的新 URL 數，達 max_articles 即可 break

        for idx, prefix in enumerate(tqdm(slices, desc=f"{self._source_name} CDX probe", file=sys.stderr), start=1):
            slice_snapshots = self._probe_slice(prefix)
            for ts, url in slice_snapshots:
                canonical = self._canonicalize_url(url)
                existing = snapshots_by_canonical.get(canonical)
                # 保留最早的 snapshot（timestamp 最小）以最接近原文
                # original_url 保留「最早的那次」對應的版本，因為 Wayback 用它取 snapshot
                if existing is None or ts < existing[0]:
                    snapshots_by_canonical[canonical] = (ts, url)
                    if canonical not in seen_canonical:
                        new_url_count += 1

            # 每 N slice 輸出一次進度（launchd log 才看得到）
            if idx % _PROBE_LOG_EVERY == 0 or idx == len(slices):
                logging.info(
                    f"{self._source_name} CDX slice {idx}/{len(slices)}, "
                    f"累積 {len(snapshots_by_canonical)} 個唯一 URL（其中 {new_url_count} 篇新）"
                )

            # Early stop：湊夠 max_articles 的新 URL 就不用再 probe 剩下 slice
            # 保險起見留 20% buffer（後續 _fetch_snapshot 可能失敗），實際抓時再依 max_articles cut
            if self._max_articles is not None and new_url_count >= int(self._max_articles * 1.2):
                logging.info(
                    f"{self._source_name} probe early stop at slice {idx}/{len(slices)}: "
                    f"new URL 已 {new_url_count} ≥ {int(self._max_articles * 1.2)}（max_articles × 1.2）"
                )
                break

        logging.info(f"{self._source_name} CDX 共發現 {len(snapshots_by_canonical)} 個唯一文章 URL")

        # 階段二：逐篇抓取 Wayback 快照並解析
        # seen_canonical 已在 probe 階段初始化（early-stop 需要），此處沿用
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

    # ── CDX slice 生成器 ──────────────────────────────────────────
    def _build_slices(self):
        """
        生成 CDX prefix slice list。
          CNN：每年 × 12 月 × 2 domain（www/edition）= 24/年
          WSJ：每年 × 36 字首（a-z + 0-9）= 36/年
        """
        for year in range(self._start_year, self._end_year + 1):
            if self._source == "cnn":
                for month in range(1, 13):
                    yield f"www.cnn.com/{year}/{month:02d}/"
                    yield f"edition.cnn.com/{year}/{month:02d}/"
            else:  # wsj
                frm = f"{year}0101"
                to  = f"{year}1231"
                for letter in _WSJ_PREFIX_LETTERS:
                    yield ("wsj", f"www.wsj.com/articles/{letter}", frm, to)

    # ── CDX probe（單 slice）────────────────────────────────────
    def _probe_slice(self, slice_info) -> list:
        """
        Probe 一個 CDX slice，回傳 [(timestamp, original_url), ...]。
        CNN slice = prefix 字串（URL 本身含日期，不需 from/to）
        WSJ slice = (tag, prefix, frm, to) tuple（需額外 from/to 限年份範圍）
        """
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

        # 第一列是 header
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

    # ── Wayback snapshot 抓取 ─────────────────────────────────────
    def _fetch_snapshot(self, timestamp: str, original_url: str) -> Optional[dict]:
        """抓取單個 Wayback snapshot 並解析成 ArticleSchema 格式 dict"""
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

        # 存 DB 用 canonicalize 過的 URL（去除 http/https 協定差異、trailing slash、
        # fragment、tracking query param），避免同一篇文章在 Wayback 有 http + https
        # 兩份快照時被當成不同 URL 重複插入。
        # 注意：送進 Wayback 取 snapshot 的 URL 不 canonicalize，因為 Wayback 本身已
        # 做過 redirect，此處只影響資料庫寫入的欄位。
        canonical_url = self._canonicalize_url(original_url)

        article = {
            "title":        title,
            "content":      content,
            "url":          canonical_url,       # 用 canonicalize 過的 URL 存 DB
            "author":       None,
            "published_at": published_at,
            "push_count":   None,
            "comments":     [],
        }
        if not self.validate_article(article, "Wayback"):
            return None
        return article

    # ── URL canonicalize ──────────────────────────────────────────
    def _canonicalize_url(self, url: str) -> str:
        """
        將 URL 標準化為資料庫去重友好的形式。規則：
          1. scheme 統一成 https（CNN / WSJ 全站都支援 https）
          2. host 小寫、去掉預設 port
          3. 去掉 fragment（#anchor）
          4. 去掉 tracking query param（utm_*、fbclid、gclid、icid、ampcid... 等）
          5. 路徑 trailing slash 統一剝掉（根路徑 "/" 保留）

        parse 失敗時回傳原字串，不讓 canonicalize 本身阻斷爬蟲流程。
        """
        if not url:
            return url
        try:
            parts = urlparse(url)
            if not parts.scheme or not parts.netloc:
                return url

            scheme = "https"
            netloc = parts.netloc.lower()
            # 去掉預設 port（https:443 / http:80）
            if netloc.endswith(":443") or netloc.endswith(":80"):
                netloc = netloc.rsplit(":", 1)[0]

            # 過濾 tracking query
            if parts.query:
                kept = [
                    (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                    if k.lower() not in _TRACKING_QUERY_PARAMS
                ]
                query = urlencode(kept)
            else:
                query = ""

            # trailing slash：非根路徑剝掉
            path = parts.path or "/"
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")

            return urlunparse((scheme, netloc, path, parts.params, query, ""))
        except Exception as e:
            logging.warning(f"URL canonicalize 失敗，回傳原 URL {url}：{e}")
            return url

    # ── HTML 解析 helpers ─────────────────────────────────────────
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        # 優先 og:title → h1 → <title>
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
            # 移除常見 " - CNN" / " - WSJ" 尾綴
            for suffix in (" - CNN", " | CNN", " - WSJ", " | WSJ"):
                if text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
            if text:
                return text
        return None

    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """提取文章本文（<article> 優先，否則 <p> 聚合）"""
        article_tag = soup.find("article")
        if article_tag:
            paragraphs = article_tag.find_all("p")
        else:
            # 常見 content container class
            container = (
                soup.find("div", class_=re.compile(r"article|story|content|body", re.I))
                or soup
            )
            paragraphs = container.find_all("p")

        if not paragraphs:
            return None

        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        # 過濾純 boilerplate
        if len(text) < 100:
            return None
        return text

    def _extract_publish_time(self,
                              soup: BeautifulSoup,
                              timestamp: str,
                              original_url: str) -> Optional[datetime]:
        """
        優先順序：
          1. meta article:published_time / meta pubdate
          2. <time datetime="...">
          3. JSON-LD datePublished
          4. 從 URL /YYYY/MM/DD/ 提取
          5. 最後 fallback：Wayback snapshot timestamp
        """
        # 1. meta tags
        for meta_name in ("article:published_time", "pubdate", "date", "DC.date.issued"):
            meta = (
                soup.find("meta", attrs={"property": meta_name})
                or soup.find("meta", attrs={"name": meta_name})
            )
            if meta and meta.get("content"):
                parsed = self._try_parse_datetime(meta["content"])
                if parsed:
                    return parsed

        # 2. <time> tag
        time_tag = soup.find("time")
        if time_tag:
            dt_attr = time_tag.get("datetime") or time_tag.get_text(strip=True)
            if dt_attr:
                parsed = self._try_parse_datetime(dt_attr)
                if parsed:
                    return parsed

        # 3. JSON-LD
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

        # 4. URL /YYYY/MM/DD/
        url_match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", original_url)
        if url_match:
            try:
                return datetime(int(url_match.group(1)),
                                int(url_match.group(2)),
                                int(url_match.group(3)))
            except ValueError:
                pass

        # 5. Wayback timestamp fallback（YYYYMMDDhhmmss）
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
                # strip tz so ArticleSchema 的 naive datetime 檢查不出錯
                return parsed.replace(tzinfo=None)
            except ValueError:
                continue
        return None


# 手動執行請改用 cli.py：
#   python cli.py wayback-backfill cnn --min-year 2015 --max-year 2023
#   python cli.py wayback-backfill wsj --min-year 2022 --max-articles 500
# 排程執行由 launchd 每日 03:00 觸發（~/Library/LaunchAgents/com.andrew.wayback-backfill.plist）
# 刻意不加入 pipeline.py 的 _ARTICLE_SOURCES，避免拖慢每小時 ETL
