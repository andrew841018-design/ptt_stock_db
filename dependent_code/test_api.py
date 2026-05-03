import pytest
import pandas as pd
import redis
from unittest.mock import patch
from fastapi.testclient import TestClient
from api import app, PERIOD_MIN, PERIOD_MAX, ARTICLE_LIMIT_MIN, ARTICLE_LIMIT_MAX, ARTICLE_PERIOD_MIN, ARTICLE_PERIOD_MAX
from auth import verify_token

client = TestClient(app)

# ── JWT bypass for all tests ──────────────────────────────────────────────────
# verify_token 是 FastAPI Depends，測試時繞過 DB/JWT，直接回傳固定 dict
app.dependency_overrides[verify_token] = lambda: {"sub": "testuser", "role": "admin"}

# ===== Mock 資料 =====
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

STANDARD_CASES = [
    ("mock_db_with_data", [200, 404]),
    ("mock_db_empty", [404]),
]

# ===== Fixtures =====
@pytest.fixture
def mock_db_with_data():
    """
    四個 patch 平行生效，同時換掉、同時還原，無階層關係：
    - get_cache       → None（模擬 MISS，確保走到 DB）
    - set_cache       → no-op（不實際寫 Redis）
    - read_sql_query  → MOCK_DATA（不查真實 DB）
    - get_pg_readonly → no-op（不建立真實連線）
    """
    with patch("api.get_cache", return_value=None), \
         patch("api.set_cache"), \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_readonly"):
        yield

@pytest.fixture
def mock_db_empty():
    with patch("api.get_cache", return_value=None), \
         patch("api.set_cache"), \
         patch("api.pd.read_sql_query", return_value=MOCK_EMPTY.copy()), \
         patch("api.get_pg_readonly"):
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
    # correct request
    for period in [PERIOD_MIN, PERIOD_MAX]:
        response = client.get(f"/sentiments/recent?period={period}")
        assert response.status_code in expected, f"period: {period}"
        if response.status_code == 200:
            assert "period" in response.json()
            assert "sentiment_score" in response.json()
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
            if response.status_code == 200:
                assert "limit" in response.json()
                assert "articles" in response.json()
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
    with patch("api.get_pg_readonly"):
        response = client.get("/health")
        assert response.status_code == 200


# ===== Cache Helper Tests =====
def test_set_and_get_cache():
    """驗證 cache_helper 真的把資料存進 Redis 再取出，且內容正確"""
    from cache_helper import get_cache, set_cache
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    set_cache("test_key", df)
    result = get_cache("test_key")
    assert result is not None
    assert list(result["a"]) == [1, 2, 3]
    assert list(result["b"]) == ["x", "y", "z"]


# ===== Cache-Aside Tests =====
def test_cache_hit():
    """
    測試目的：Cache HIT 時，get_cache 有被呼叫，get_pg_readonly 不被呼叫

    mock 設定：
    - api.get_cache       → 回傳 MOCK_DATA（模擬 Redis 有資料）
    - api.get_pg_readonly → 空物件（保險用，確保萬一走錯時不會真的連 DB）

    flow:
    client.get("/sentiments/today")
    => get_today_sentiment()
    => load_articles_df()
    => get_cache() 回傳 MOCK_DATA → 直接 return，get_pg_readonly 不執行
    """
    with patch("api.get_cache", return_value=MOCK_DATA.copy()) as mock_get, \
         patch("api.get_pg_readonly") as mock_db:
        response = client.get("/sentiments/today")
        assert response.status_code == 200
        mock_get.assert_called_once()   # Redis 有被查
        mock_db.assert_not_called()     # DB 完全沒被碰


def test_cache_miss():
    """Cache MISS：Redis 沒資料 → 查 DB → 存進 Redis"""
    with patch("api.get_cache", return_value=None) as mock_get, \
         patch("api.set_cache") as mock_set, \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_readonly"):
        response = client.get("/sentiments/today")
        assert response.status_code == 200
        mock_get.assert_called_once()   # Redis 有被查（但 MISS）
        mock_set.assert_called_once()   # 查完 DB 後有存進 Redis

#平常應該不會出錯，這個只用來偵測Redis掛掉時，API是否不會爆錯
def test_cache_redis_down():
    """Redis 掛掉：cache_helper 內部 catch 錯誤回傳 None，fallback 查 DB，API 不爆"""
    with patch("cache_helper._redis.get", side_effect=redis.RedisError("Redis 掛了")), \
         patch("cache_helper._redis.setex", side_effect=redis.RedisError("Redis 掛了")), \
         patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()), \
         patch("api.get_pg_readonly"):
        response = client.get("/sentiments/today")
        assert response.status_code == 200  # API 正常回傳，沒有爆
