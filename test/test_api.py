from fastapi.testclient import TestClient
from api import PERIOD_MIN,PERIOD_MAX,ARTICLE_LIMIT_MIN,ARTICLE_LIMIT_MAX,ARTICLE_PERIOD_MIN,ARTICLE_PERIOD_MAX
from api import app
client=TestClient(app)

def test_get_today_sentiment():
    response=client.get("/sentiments/today")
    assert response.status_code in [200,404]
def test_get_change_sentiment():
    response=client.get("/sentiments/change")
    assert response.status_code in [200,404]
def test_get_recent_sentiment_score():
    # correct request
    for period in [PERIOD_MIN,PERIOD_MAX]:
        response=client.get(f"/sentiments/recent?period={period}")
        assert response.status_code in [200,404],f"period: {period}"
    # incorrect request
    response=client.get(f"/sentiments/recent?period={PERIOD_MIN-1}")
    assert response.status_code==422
    response=client.get(f"/sentiments/recent?period={PERIOD_MAX+1}")
    assert response.status_code==422
def test_get_top_push_articles():
    # correct request
    for limit in [ARTICLE_LIMIT_MIN,ARTICLE_LIMIT_MAX]:
        for period in [ARTICLE_PERIOD_MIN,ARTICLE_PERIOD_MAX]:
            response=client.get(f"/articles/top_push?limit={limit}&period={period}")
            assert response.status_code in [200,404],f"limit: {limit}, period: {period}"
    # incorrect request
    response=client.get(f"/articles/top_push?limit={ARTICLE_LIMIT_MIN-1}")
    assert response.status_code==422
    response=client.get(f"/articles/top_push?limit={ARTICLE_LIMIT_MAX+1}")
    assert response.status_code==422
    response=client.get(f"/articles/top_push?period={ARTICLE_PERIOD_MIN-1}")
    assert response.status_code==422
    response=client.get(f"/articles/top_push?period={ARTICLE_PERIOD_MAX+1}")
    assert response.status_code==422
def test_get_search_articles():
    # correct request
    response=client.get(f"/articles/search?keyword=台積電")
    assert response.status_code in [200,404]
    if response.status_code == 200:
        assert response.json()["search_articles"] is not None
    # empty keyword
    response=client.get(f"/articles/search?keyword=")
    assert response.status_code in [200,404]
    
    # incorrect request
    # missing keyword
    response=client.get("/articles/search")
    assert response.status_code==422  
def test_health_check():
    response=client.get("/health")
    assert response.status_code==200