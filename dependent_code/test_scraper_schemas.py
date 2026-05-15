
import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from scrapers.scraper_schemas import ArticleSchema


def _valid_article() -> dict:
    return {
        "title":        "[標的] 2330 台積電 多",
        "url":          "https://www.ptt.cc/bbs/Stock/M.1234567890.A.ABC.html",
        "author":       "test_user",
        "content":      "今日 2330 漲 5%，看多。",
        "published_at": datetime(2026, 4, 10, 10, 0, 0),
        "push_count":   45,
    }


def test_valid_article_passes():
    schema = ArticleSchema(**_valid_article())
    assert schema.title.startswith("[標的]")
    assert schema.push_count == 45


def test_empty_title_rejected():
    bad = _valid_article()
    bad["title"] = "   "
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_out_of_range_rejected():
    bad = _valid_article()
    bad["push_count"] = 999
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_negative_edge():
    edge = _valid_article()
    edge["push_count"] = -100
    assert ArticleSchema(**edge).push_count == -100


def test_published_at_future_rejected():
    bad = _valid_article()
    bad["published_at"] = datetime.utcnow() + timedelta(days=10)
    with pytest.raises(ValueError):
        ArticleSchema(**bad)


def test_push_count_none_allowed():
    ok = _valid_article()
    ok["push_count"] = None
    assert ArticleSchema(**ok).push_count is None
