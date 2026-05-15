
from __future__ import annotations

import json
import logging
import random
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Iterator, Tuple

from scrapers.base_scraper import get_with_retry
from scrapers.cnn_scraper import (
    CnnScraper,
    _BUSINESS_PATHS,
    _MONTH_SITEMAP_TEMPLATE,
    _NS,
)
from config import DEFAULT_HEADERS as _HEADERS

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROGRESS_FILE = _PROJECT_ROOT / "logs" / "cnn_backfill_progress.json"

_START_YEAR_MONTH = (2011, 12)
_PARALLEL = 5
_PER_REQUEST_DELAY = 1.5
_PER_REQUEST_JITTER = 0.5
_BATCH_WRITE_SIZE = 100


class CnnBackfillScraper(CnnScraper):

    def fetch_articles(self) -> list:
        return []


def _generate_months(start: Tuple[int, int], end: Tuple[int, int]) -> Iterator[Tuple[int, int]]:
    year, month = start
    end_year, end_month = end
    while (year, month) <= (end_year, end_month):
        yield (year, month)
        month += 1
        if month > 12:
            year += 1
            month = 1


def _fetch_month_business_urls(year: int, month: int) -> list:
    url = _MONTH_SITEMAP_TEMPLATE.format(year=year, month=month)
    try:
        response = get_with_retry(url, headers=_HEADERS, timeout=15)
    except Exception as e:
        logging.warning(f"month {year}-{month:02d} sitemap 抓取失敗：{e}")
        return []
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logging.warning(f"month {year}-{month:02d} sitemap 解析失敗：{e}")
        return []
    urls = []
    for url_elem in root.findall("sm:url", _NS):
        loc = url_elem.findtext("sm:loc", namespaces=_NS) or ""
        if loc and any(p in loc for p in _BUSINESS_PATHS):
            urls.append(loc)
    return urls


def _load_progress() -> dict:
    if _PROGRESS_FILE.exists():
        return json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
    return {
        "completed_months": [],
        "stats": {"fetched": 0, "errors": 0, "skipped_invalid": 0},
        "started_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def _save_progress(progress: dict) -> None:
    _PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROGRESS_FILE.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def _fetch_one(scraper: CnnBackfillScraper, url: str):
    time.sleep(_PER_REQUEST_DELAY + random.uniform(0, _PER_REQUEST_JITTER))
    return url, scraper._fetch_article_full(url)


def _flush_batch(scraper: CnnBackfillScraper, batch: list, stats: dict) -> None:
    if not batch:
        return
    valid = [a for a in batch if scraper.validate_article(a, "CNN-backfill")]
    stats["skipped_invalid"] += len(batch) - len(valid)
    if valid:
        scraper._save_to_db(valid)
        stats["fetched"] += len(valid)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("cnn_backfill")

    progress = _load_progress()
    done_months = set(progress["completed_months"])
    stats = progress["stats"]

    scraper = CnnBackfillScraper()
    known_urls = scraper._load_urls()
    log.info(f"已知 cnn URL：{len(known_urls)} 筆")

    today = datetime.utcnow()
    end_ym = (today.year, today.month)
    months = list(_generate_months(_START_YEAR_MONTH, end_ym))
    log.info(
        f"範圍 {_START_YEAR_MONTH[0]}-{_START_YEAR_MONTH[1]:02d} ~ "
        f"{end_ym[0]}-{end_ym[1]:02d}，共 {len(months)} 月，已完成 {len(done_months)} 月"
    )

    for year, month in months:
        ym_key = f"{year}-{month:02d}"
        if ym_key in done_months:
            continue

        log.info(f"=== {ym_key} ===")
        sitemap_urls = _fetch_month_business_urls(year, month)
        new_urls = [u for u in sitemap_urls if u not in known_urls]
        log.info(f"  sitemap {len(sitemap_urls)} 篇 → 待抓 {len(new_urls)} 篇")

        if not new_urls:
            done_months.add(ym_key)
            progress["completed_months"].append(ym_key)
            _save_progress(progress)
            continue

        errors_before = stats["errors"]
        batch: list = []
        with ThreadPoolExecutor(max_workers=_PARALLEL) as executor:
            futures = {executor.submit(_fetch_one, scraper, u): u for u in new_urls}
            for fut in as_completed(futures):
                try:
                    url, full = fut.result()
                except Exception as e:
                    stats["errors"] += 1
                    log.warning(f"  fetch error: {e}")
                    continue
                if not full:
                    stats["errors"] += 1
                    continue
                batch.append({
                    "title": full["title"],
                    "content": full["content"],
                    "url": url,
                    "author": None,
                    "published_at": full["published_at"],
                    "push_count": None,
                    "comments": [],
                })
                if len(batch) >= _BATCH_WRITE_SIZE:
                    _flush_batch(scraper, batch, stats)
                    log.info(
                        f"  [{ym_key}] 累計 fetched={stats['fetched']} "
                        f"errors={stats['errors']} invalid={stats['skipped_invalid']}"
                    )
                    batch.clear()

        _flush_batch(scraper, batch, stats)
        known_urls.update(a["url"] for a in batch)
        errors_this_month = stats["errors"] - errors_before
        if errors_this_month == 0:
            done_months.add(ym_key)
            progress["completed_months"].append(ym_key)
            log.info(
                f"  done {ym_key}：fetched={stats['fetched']} "
                f"errors={stats['errors']} invalid={stats['skipped_invalid']}"
            )
        else:
            log.warning(
                f"  [{ym_key}] {errors_this_month} 個 URL 失敗，不標記完成，下次重試"
            )
        _save_progress(progress)

    log.info(
        f"全部完成 fetched={stats['fetched']} "
        f"errors={stats['errors']} invalid={stats['skipped_invalid']}"
    )


if __name__ == "__main__":
    main()
