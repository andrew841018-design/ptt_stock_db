import pandas as pd
import datetime
from typing import Literal, Optional
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from pg_helper import get_pg
from cache_helper import get_cache, set_cache
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, STOCK_PRICES_TABLE, CACHE_KEY_ARTICLES


# ── Response Models ────────────────────────────────────────────────────────────

class TodaySentimentResponse(BaseModel):
    date: str
    sentiment_score: float
    message: str

class ChangeSentimentResponse(BaseModel):
    change_sentiment_score: float
    message: str

class RecentSentimentResponse(BaseModel):
    period: int
    sentiment_score: float
    message: str

class TopPushArticleItem(BaseModel):
    Title: str
    Push_count: Optional[int]
    Published_Time: datetime.datetime
    Url: str

class TopPushResponse(BaseModel):
    note: str
    limit: int
    # 會驗證list內是否是裝TopPushArticleItem的dict，通常回傳dict才會以此行是定義
    articles: list[TopPushArticleItem]
    message: str

class SearchArticleItem(BaseModel):
    Title: str
    Push_count: Optional[int]
    Published_Time: datetime.datetime
    Url: str

class SearchResponse(BaseModel):
    search_articles: list[SearchArticleItem]
    message: str

class SentimentVsStockPriceItem(BaseModel):
    sentiment_date: datetime.date
    avg_sentiment: float
    next_day_change: float

class SentimentVsStockPriceResponse(BaseModel):
    period: int
    data: list[SentimentVsStockPriceItem]

class HealthResponse(BaseModel):
    status: str
    message: str

app = FastAPI()

PERIOD_MIN         = 1
PERIOD_MAX         = 30
ARTICLE_LIMIT_MIN  = 1
ARTICLE_LIMIT_MAX  = 100
ARTICLE_PERIOD_MIN = 1
ARTICLE_PERIOD_MAX = 365


def load_articles_df() -> pd.DataFrame:
    """讀取文章資料（JOIN sentiment_scores），Cache-Aside：先查 Redis，沒有再查 DB"""
    df = get_cache(CACHE_KEY_ARTICLES)
    if df is not None:
        return df
    try:
        with get_pg() as conn:
            df = pd.read_sql_query(f"""
                SELECT
                    a.article_id                    AS "Article_id",
                    a.title                         AS "Title",
                    a.push_count                    AS "Push_count",
                    a.author                        AS "Author",
                    a.url                           AS "Url",
                    a.published_at                  AS "Published_Time",
                    s.score                         AS "Article_Sentiment_Score"
                FROM {ARTICLES_TABLE} a
                JOIN {SENTIMENT_SCORES_TABLE} s
                    ON s.article_id = a.article_id
            """, conn)
        df['Published_Time'] = pd.to_datetime(df['Published_Time'])
        set_cache(CACHE_KEY_ARTICLES, df)
        return df
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "database search failed: " + str(e)})


@app.get("/sentiments/today", response_model=TodaySentimentResponse)
def get_today_sentiment() -> TodaySentimentResponse:
    df = load_articles_df()
    df['Published_Date'] = df['Published_Time'].dt.date
    today = df[df['Published_Date'] == df['Published_Date'].max()]
    if len(today) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data for today"})
    sentiment_score = round(today['Article_Sentiment_Score'].mean(), 2)
    return {"date": str(today['Published_Date'].max()), "sentiment_score": sentiment_score, "message": "Success"}


@app.get("/sentiments/change", response_model=ChangeSentimentResponse)
def get_change_sentiment() -> ChangeSentimentResponse:
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    df['Published_Date'] = df['Published_Time'].dt.date
    today     = df[df['Published_Date'] == df['Published_Date'].max()]
    yesterday = df[df['Published_Date'] == df['Published_Date'].max() - datetime.timedelta(days=1)]
    if len(today) == 0 or len(yesterday) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data for today or yesterday"})
    change_score = round(today['Article_Sentiment_Score'].mean() - yesterday['Article_Sentiment_Score'].mean(), 2)
    return {"change_sentiment_score": change_score, "message": "Success"}


@app.get("/sentiments/recent", response_model=RecentSentimentResponse)
def get_recent_sentiment_score(period: int = Query(default=10, ge=PERIOD_MIN, le=PERIOD_MAX)):
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    start_time  = df['Published_Time'].max() - datetime.timedelta(days=period)
    recent_data = df[df['Published_Time'] >= start_time]
    if len(recent_data) == 0:
        raise HTTPException(status_code=404, detail={"message": f"No data for the past {period} days"})
    recent_score = round(recent_data['Article_Sentiment_Score'].mean(), 2)
    return {"period": period, "sentiment_score": recent_score, "message": "Success"}


@app.get("/articles/top_push", response_model=TopPushResponse)
def get_top_push_articles(
    limit:       int                                      = Query(default=10, ge=ARTICLE_LIMIT_MIN, le=ARTICLE_LIMIT_MAX),
    period:      int                                      = Query(default=7,  ge=ARTICLE_PERIOD_MIN, le=ARTICLE_PERIOD_MAX),
    period_type: Literal["day", "week", "month", "year"] = Query(default="day"),
):
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    """
    python裡，assign兩次會指向同一個物件，用copy第二次才會指向一份新的物件
    """
    df = df.copy()
    df['Published_Date'] = df['Published_Time'].dt.date
    # filter by period
    end_date  = df['Published_Date'].max()
    days_map  = {"day": 1, "week": 7, "month": 30, "year": 365}
    total_days = period * days_map[period_type]
    start_date = end_date - datetime.timedelta(days=total_days)
    filtered_df  = df[df['Published_Date'] >= start_date]
    top_articles = filtered_df.nlargest(limit, 'Push_count')[['Title', 'Push_count', 'Published_Time', 'Url']]
    if len(top_articles) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    return {
        "note": "Push_count 100 表示『爆』(實際值 ≥ 100)，-100 表示『XX』(實際值 ≤ -100)",
        "limit": limit,
        "articles": top_articles.to_dict(orient="records"),
        "message": "Success"
    }


@app.get("/articles/search", response_model=SearchResponse)
# ...表示必填，使用者不填入內容會出錯
def search_articles(keyword: str) -> SearchResponse:
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data found"})
    # case=False-表示不區分大小寫，na=False-表示不處理缺失值
    result = df[df['Title'].str.contains(keyword, case=False, na=False)]
    if len(result) == 0:
        raise HTTPException(status_code=404, detail={"message": "No related articles"})
    return {"search_articles": result[['Title', 'Push_count', 'Published_Time', 'Url']].to_dict(orient="records"), "message": "Success"}


@app.get("/correlation/0050", response_model=SentimentVsStockPriceResponse)
def get_sentiment_vs_stock_price_correlation(period: int = Query(default=30, ge=1, le=365)):
    """PTT 情緒分數 vs 0050 隔日漲跌。每個交易日：當日 PTT 平均情緒 → 隔日漲跌價差。"""
    try:
        with get_pg() as conn:
            df = pd.read_sql_query(f"""
                SELECT
                    sub.sentiment_date,
                    sub.avg_sentiment,
                    sp.change              AS next_day_change
                FROM (
                    SELECT
                        DATE(a.published_at) AS sentiment_date,
                        AVG(s.score)         AS avg_sentiment
                    FROM {ARTICLES_TABLE} a
                    JOIN {SENTIMENT_SCORES_TABLE} s ON s.article_id = a.article_id
                    WHERE a.published_at >= NOW() - INTERVAL '{period} days'
                    GROUP BY DATE(a.published_at)
                ) sub
                JOIN {STOCK_PRICES_TABLE} sp
                    ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
                ORDER BY sub.sentiment_date
            """, conn)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": str(e)})

    if df.empty:
        raise HTTPException(status_code=404, detail={"message": "查無資料，sentiment_scores 可能尚未填入"})

    return {"period": period, "data": df.to_dict(orient="records")}


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    try:
        with get_pg() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")#測試用語法，確認db活著
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "database connection failed: " + str(e)})
    return {"status": "ok", "message": "db connection is successful"}
