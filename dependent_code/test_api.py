import datetime
import pytest
import pandas as pd
import redis
from unittest.mock import patch
from fastapi.testclient import TestClient
from api import app, PERIOD_MIN, PERIOD_MAX, ARTICLE_LIMIT_MIN, ARTICLE_LIMIT_MAX, ARTICLE_PERIOD_MIN, ARTICLE_PERIOD_MAX
from auth import verify_token

client = TestClient(app)

app.dependency_overrides[verify_token] = lambda: {"sub": "testuser", "role": "admin"}

MOCK_DATA = pd.DataFrame({
    "Article_id":             [1, 2, 3],
    "Title":                  ["台積電大漲", "聯發科分析", "台積電展望"],
    "Push_count":             [50, 30, 100],
    "Author":                 ["user1", "user2", "user3"],
    "Url":                    ["http://a.com", "http://b.com", "http://c.com"],
    "Published_Time":         pd.to_datetime(["2024-01-01 10:00:00", "2024-01-01 11:00:00", "2024-01-02 10:00:00"]),
    "Article_Sentiment_Score": [0.5, -0.3, 0.8],
})

MOCK_EMPTY = pd.DataFrame({col: [] for col in MOCK_DATA.columns})

MOCK_SENTIMENT_ROWS = [
    {"summary_date": datetime.date(2024, 1, 2), "total_articles": 100, "scored_articles": 100, "avg_sentiment": 0.5},
    {"summary_date": datetime.date(2024, 1, 1), "total_articles": 80,  "scored_articles": 80,  "avg_sentiment": 0.3},
]

STANDARD_CASES = [
    ("mock_db_with_data", [200, 404]),
    ("mock_db_empty", [404]),
]

@pytest.fixture
def mock_db_with_data():
    with patch("api.get_cache", return_value=None), \
         patch("api.set_cache"), \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_pooled"), \
         patch("api.get_daily_sentiment", return_value=list(MOCK_SENTIMENT_ROWS)):
        yield

@pytest.fixture
def mock_db_empty():
    with patch("api.get_cache", return_value=None), \
         patch("api.set_cache"), \
         patch("api.pd.read_sql_query", return_value=MOCK_EMPTY.copy()), \
         patch("api.get_pg_pooled"), \
         patch("api.get_daily_sentiment", return_value=[]):
        yield

@pytest.mark.parametrize("mock_fixture,expected", [
    ("mock_db_with_data", [200]),
    ("mock_db_empty", [404]),
])
def test_get_today_sentiment(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    response = client.get("/sentiments/today")
    assert response.status_code in expected
    if response.status_code == 200:
        assert "date" in response.json()
        assert "sentiment_score" in response.json()

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_change_sentiment(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    response = client.get("/sentiments/change")
    assert response.status_code in expected
    if response.status_code == 200:
        assert "change_sentiment_score" in response.json()

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_recent_sentiment_score(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    for period in [PERIOD_MIN, PERIOD_MAX]:
        response = client.get(f"/sentiments/recent?period={period}")
        assert response.status_code in expected, f"period: {period}"
        if response.status_code == 200:
            assert "period" in response.json()
            assert "sentiment_score" in response.json()
    response = client.get(f"/sentiments/recent?period={PERIOD_MIN - 1}")
    assert response.status_code == 422
    response = client.get(f"/sentiments/recent?period={PERIOD_MAX + 1}")
    assert response.status_code == 422

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_top_push_articles(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    for limit in [ARTICLE_LIMIT_MIN, ARTICLE_LIMIT_MAX]:
        for period in [ARTICLE_PERIOD_MIN, ARTICLE_PERIOD_MAX]:
            response = client.get(f"/articles/top_push?limit={limit}&period={period}")
            assert response.status_code in expected, f"limit: {limit}, period: {period}"
            if response.status_code == 200:
                assert "limit" in response.json()
                assert "articles" in response.json()
    response = client.get(f"/articles/top_push?limit={ARTICLE_LIMIT_MIN - 1}")
    assert response.status_code == 422
    response = client.get(f"/articles/top_push?limit={ARTICLE_LIMIT_MAX + 1}")
    assert response.status_code == 422
    response = client.get(f"/articles/top_push?period={ARTICLE_PERIOD_MIN - 1}")
    assert response.status_code == 422
    response = client.get(f"/articles/top_push?period={ARTICLE_PERIOD_MAX + 1}")
    assert response.status_code == 422

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_search_articles(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    response = client.get("/articles/search?keyword=台積電")
    assert response.status_code in expected
    if response.status_code == 200:
        assert response.json()["search_articles"] is not None
    response = client.get("/articles/search?keyword=")
    assert response.status_code in expected
    response = client.get("/articles/search")
    assert response.status_code == 422

def test_health_check():
    with patch("api.get_pg_pooled"):
        response = client.get("/health")
        assert response.status_code == 200


def test_set_and_get_cache():
    from cache_helper import get_cache, set_cache
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    set_cache("test_key", df)
    result = get_cache("test_key")
    assert result is not None
    assert list(result["a"]) == [1, 2, 3]
    assert list(result["b"]) == ["x", "y", "z"]


def test_cache_hit():
    with patch("api.get_cache", return_value=MOCK_DATA.copy()) as mock_get, \
         patch("api.get_pg_pooled") as mock_db:
        response = client.get("/articles/top_push")
        assert response.status_code == 200
        mock_get.assert_called_once()
        mock_db.assert_not_called()


def test_cache_miss():
    with patch("api.get_cache", return_value=None) as mock_get, \
         patch("api.set_cache") as mock_set, \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_pooled"):
        response = client.get("/articles/top_push")
        assert response.status_code == 200
        mock_get.assert_called_once()
        mock_set.assert_called_once()

def test_cache_redis_down():
    with patch("cache_helper._redis.get", side_effect=redis.RedisError("Redis 掛了")), \
         patch("cache_helper._redis.setex", side_effect=redis.RedisError("Redis 掛了")), \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_pooled"):
        response = client.get("/articles/top_push")
        assert response.status_code == 200
