import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
from api import app, PERIOD_MIN, PERIOD_MAX, ARTICLE_LIMIT_MIN, ARTICLE_LIMIT_MAX, ARTICLE_PERIOD_MIN, ARTICLE_PERIOD_MAX

client = TestClient(app)

# ===== Mock 資料 =====
MOCK_DATA = pd.DataFrame({
    "Article_id": [1, 2, 3],
    "Title": ["台積電大漲", "聯發科分析", "台積電展望"],
    "Push_count": [50, 30, 100],
    "Author": ["user1", "user2", "user3"],
    "Url": ["http://a.com", "http://b.com", "http://c.com"],
    "Date": ["2024/01/01", "2024/01/01", "2024/01/02"],
    "Content": ["內容1", "內容2", "台積電內容3"],
    "Scraped_time": ["2024-01-01", "2024-01-01", "2024-01-02"],
    "Article_Sentiment_Score": [0.5, -0.3, 0.8],
    "Published_Time": ["2024-01-01 10:00:00", "2024-01-01 11:00:00", "2024-01-02 10:00:00"],
})

MOCK_EMPTY = pd.DataFrame({col: [] for col in MOCK_DATA.columns})

STANDARD_CASES = [
    ("mock_db_with_data", [200, 404]),
    ("mock_db_empty", [404]),
]

# ===== Fixtures =====
@pytest.fixture
def mock_db_with_data():
    """
    api=>file name=>api.py , get_pg=>context manager for DB connection
    .copy=>we don't want to change the original data
    MagicMock=>instead of connect to DB, we use MagicMock to mock the DB connection
    """
    with patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()):
        with patch("api.get_pg"):# patch 內部自動用magicmock替換get_pg，因此不需要import MagicMock
            yield

@pytest.fixture
def mock_db_empty():
    with patch("api.pd.read_sql_query", return_value=MOCK_EMPTY.copy()):
        with patch("api.get_pg"):
            yield

# ===== Tests =====
@pytest.mark.parametrize("mock_fixture,expected", [
    ("mock_db_with_data", [200]),
    ("mock_db_empty", [404]),
])
def test_get_today_sentiment(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    response = client.get("/sentiments/today")
    assert response.status_code in expected

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_change_sentiment(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    response = client.get("/sentiments/change")
    assert response.status_code in expected

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_recent_sentiment_score(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    # correct request
    for period in [PERIOD_MIN, PERIOD_MAX]:
        response = client.get(f"/sentiments/recent?period={period}")
        assert response.status_code in expected, f"period: {period}"
    # incorrect request
    response = client.get(f"/sentiments/recent?period={PERIOD_MIN - 1}")
    assert response.status_code == 422
    response = client.get(f"/sentiments/recent?period={PERIOD_MAX + 1}")
    assert response.status_code == 422

@pytest.mark.parametrize("mock_fixture,expected", STANDARD_CASES)
def test_get_top_push_articles(mock_fixture, expected, request):
    request.getfixturevalue(mock_fixture)
    # correct request
    for limit in [ARTICLE_LIMIT_MIN, ARTICLE_LIMIT_MAX]:
        for period in [ARTICLE_PERIOD_MIN, ARTICLE_PERIOD_MAX]:
            response = client.get(f"/articles/top_push?limit={limit}&period={period}")
            assert response.status_code in expected, f"limit: {limit}, period: {period}"
    # incorrect request
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
    # correct request
    response = client.get("/articles/search?keyword=台積電")
    assert response.status_code in expected
    if response.status_code == 200:
        assert response.json()["search_articles"] is not None
    # empty keyword
    response = client.get("/articles/search?keyword=")
    assert response.status_code in expected
    # incorrect request
    response = client.get("/articles/search")
    assert response.status_code == 422

def test_health_check():
    with patch("api.get_pg"):
        response = client.get("/health")
        assert response.status_code == 200