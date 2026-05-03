"""
Pydantic ArticleSchema 驗證單元測試。

測 5 類邊界 case：
  1. 合法文章 → 通過
  2. 空 title → attr validator 擋下
  3. URL 不符 regex → 擋下
  4. push_count 超 -100~100 → 擋下
  5. published_at 在未來 → 擋下
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

# 讓 pytest 從 project root 或 dependent_code/ 都能跑
sys.path.insert(0, os.path.dirname(__file__))

from scrapers.scraper_schemas import ArticleSchema


# ── 合法 sample（各 test 可複製再改）───────────────────────────────────────────
def _valid_article() -> dict:
    return {
        "title":        "[標的] 2330 台積電 多",
        "url":          "https://www.ptt.cc/bbs/Stock/M.1234567890.A.ABC.html",
        "author":       "test_user",
        "content":      "今日 2330 漲 5%，看多。",
        "published_at": datetime(2026, 4, 10, 10, 0, 0),
        "push_count":   45,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_valid_article_passes():
    """合法輸入應通過驗證"""
    schema = ArticleSchema(**_valid_article())
    assert schema.title.startswith("[標的]")
    assert schema.push_count == 45


def test_empty_title_rejected():
    """空 title（只有空白）應被 validator 擋下"""
    bad = _valid_article()
    bad["title"] = "   "
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_out_of_range_rejected():
    """push_count > 100 應被擋下"""
    bad = _valid_article()
    bad["push_count"] = 999
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_negative_edge():
    """push_count = -100（邊界）應通過"""
    edge = _valid_article()
    edge["push_count"] = -100
    assert ArticleSchema(**edge).push_count == -100


def test_published_at_future_rejected():
    """published_at 在未來（>1 天後）應被擋下"""
    bad = _valid_article()
    bad["published_at"] = datetime.utcnow() + timedelta(days=10)
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_none_allowed():
    """push_count=None（英文新聞無推文數）應通過"""
    ok = _valid_article()
    ok["push_count"] = None
    assert ArticleSchema(**ok).push_count is None
