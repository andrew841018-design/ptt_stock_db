import time
import logging
import pandas as pd
import datetime
from contextlib import asynccontextmanager
from typing import Literal, Optional
from fastapi import FastAPI, Query, HTTPException, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from pg_helper import init_pool, get_pg_pooled
from cache_helper import get_cache, set_cache
from config import (
    ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, STOCK_PRICES_TABLE,
    JWT_EXPIRE_MINUTES,
)
from data_mart import get_daily_sentiment
from auth import create_token, verify_token, authenticate_user

from metrics import api_request_duration_seconds
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

CACHE_KEY_ARTICLES = "articles_df"



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

class AIModelPredictionDailyPoint(BaseModel):
    date: datetime.date
    strategy_cumulative_return: float
    buy_and_hold_return: float

class AIModelPredictionResponse(BaseModel):
    market: str
    display_name: str
    accuracy: float
    strategy_cumulative_return: float
    buy_and_hold_return: float
    sample_days: int
    daily: list[AIModelPredictionDailyPoint]

class HealthResponse(BaseModel):
    status: str
    message: str

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in_minutes: int

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool(minconn=2, maxconn=10)
    yield


app = FastAPI(title="PTT Stock Sentiment API", description="JWT 保護的情緒分析 API", lifespan=lifespan)


@app.middleware("http")
async def _prom_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path) if route else request.url.path
    api_request_duration_seconds.labels(endpoint=endpoint).observe(elapsed)
    return response


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


PERIOD_MIN         = 1
PERIOD_MAX         = 30
ARTICLE_LIMIT_MIN  = 1
ARTICLE_LIMIT_MAX  = 100
ARTICLE_PERIOD_MIN = 1
ARTICLE_PERIOD_MAX = 365



@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    user = authenticate_user(req.username, req.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": JWT_EXPIRE_MINUTES,
    }



def load_articles_df() -> pd.DataFrame:
    df = get_cache(CACHE_KEY_ARTICLES)
    if df is not None:
        return df
    try:
        with get_pg_pooled() as conn:
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
    except Exception:
        logging.exception("[API] load_articles_df 失敗")
        raise HTTPException(status_code=500, detail={"message": "database search failed"})


def _aggregate_by_date(rows: list) -> dict:
    by_date: dict = {}
    for r in rows:
        d = r["summary_date"]
        if "scored_articles" in r and r["scored_articles"] is not None:
            weight = r["scored_articles"]
        else:
            weight = r["total_articles"]
        slot = by_date.setdefault(d, {"total": 0, "weighted": 0.0})
        slot["total"] += weight
        slot["weighted"] += float(r["avg_sentiment"]) * weight
    return by_date


@app.get("/sentiments/today", response_model=TodaySentimentResponse)
def get_today_sentiment(user: dict = Depends(verify_token)) -> TodaySentimentResponse:
    rows = get_daily_sentiment(days=7)
    if not rows:
        raise HTTPException(status_code=404, detail={"message": "No data for today"})
    by_date = _aggregate_by_date(rows)
    latest_date = max(by_date.keys())
    slot = by_date[latest_date]
    score = slot["weighted"] / slot["total"]
    return {
        "date": str(latest_date),
        "sentiment_score": round(score, 2),
        "message": "Success",
    }


@app.get("/sentiments/change", response_model=ChangeSentimentResponse)
def get_change_sentiment(user: dict = Depends(verify_token)) -> ChangeSentimentResponse:
    rows = get_daily_sentiment(days=7)
    by_date = _aggregate_by_date(rows)
    if len(by_date) < 2:
        raise HTTPException(status_code=404, detail={"message": "No data for today or yesterday"})
    dates = sorted(by_date.keys(), reverse=True)
    today_score     = by_date[dates[0]]["weighted"] / by_date[dates[0]]["total"]
    yesterday_score = by_date[dates[1]]["weighted"] / by_date[dates[1]]["total"]
    return {
        "change_sentiment_score": round(today_score - yesterday_score, 2),
        "message": "Success",
    }


@app.get("/sentiments/recent", response_model=RecentSentimentResponse)
def get_recent_sentiment_score(period: int = Query(default=10, ge=PERIOD_MIN, le=PERIOD_MAX), user: dict = Depends(verify_token)):
    rows = get_daily_sentiment(days=period)
    if not rows:
        raise HTTPException(status_code=404, detail={"message": f"No data for the past {period} days"})
    weights = [
        r["scored_articles"] if ("scored_articles" in r and r["scored_articles"] is not None) else r["total_articles"]
        for r in rows
    ]
    total_weight = sum(weights)
    weighted_sum = sum(float(r["avg_sentiment"]) * w for r, w in zip(rows, weights))
    recent_score = round(weighted_sum / total_weight, 2) if total_weight else 0.0
    return {"period": period, "sentiment_score": recent_score, "message": "Success"}


@app.get("/articles/top_push", response_model=TopPushResponse)
def get_top_push_articles(
    user: dict = Depends(verify_token),
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
def search_articles(keyword: str, user: dict = Depends(verify_token)) -> SearchResponse:
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data found"})
    result = df[df['Title'].str.contains(keyword, case=False, na=False, regex=False)].copy()
    if len(result) == 0:
        raise HTTPException(status_code=404, detail={"message": "No related articles"})
    result['Push_count'] = result['Push_count'].fillna(0).astype(int)
    return {"search_articles": result[['Title', 'Push_count', 'Published_Time', 'Url']].to_dict(orient="records"), "message": "Success"}


@app.get("/correlation/0050", response_model=SentimentVsStockPriceResponse)
def get_sentiment_vs_stock_price_correlation(period: int = Query(default=30, ge=1, le=365), user: dict = Depends(verify_token)):
    try:
        with get_pg_pooled() as conn:
            df = pd.read_sql_query(f"""
                SELECT
                    m.summary_date         AS sentiment_date,
                    SUM(m.avg_sentiment * m.scored_articles)
                        / NULLIF(SUM(m.scored_articles), 0)
                                           AS avg_sentiment,
                    sp.change              AS next_day_change
                FROM mart_daily_summary m
                JOIN {STOCK_PRICES_TABLE} sp
                    ON sp.trade_date = m.summary_date + INTERVAL '1 day'
                WHERE m.summary_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
                  AND m.avg_sentiment IS NOT NULL
                GROUP BY m.summary_date, sp.change
                ORDER BY m.summary_date
            """, conn, params=(period,))
    except Exception:
        logging.exception("[API] correlation 查詢失敗")
        raise HTTPException(status_code=500, detail={"message": "database query failed"})

    if df.empty:
        raise HTTPException(status_code=404, detail={"message": "查無資料，mart_daily_summary 可能尚未刷新"})

    return {"period": period, "data": df.to_dict(orient="records")}


@app.get("/ai_model_prediction/{market}", response_model=AIModelPredictionResponse)
def get_ai_model_prediction(market: str, user: dict = Depends(verify_token)) -> AIModelPredictionResponse:
    if market not in ("tw", "us"):
        raise HTTPException(status_code=400, detail={"message": "market must be 'tw' or 'us'"})

    from ai_model_prediction import run_ai_model_prediction, MARKET_CONFIG
    df = run_ai_model_prediction(market)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail={"message": f"No AI model prediction result for {market}"})

    daily = df[["date", "strategy_cumulative_return", "buy_and_hold_return"]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date

    return {
        "market":                     market,
        "display_name":               MARKET_CONFIG[market]["display_name"],
        "accuracy":                   float((df["true"] == df["pred"]).mean()),
        "strategy_cumulative_return": float(df["strategy_cumulative_return"].iloc[-1]),
        "buy_and_hold_return":        float(df["buy_and_hold_return"].iloc[-1]),
        "sample_days":                len(df),
        "daily":                      daily.to_dict(orient="records"),
    }


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    try:
        with get_pg_pooled() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
    except Exception:
        logging.exception("[API] health check DB 連線失敗")
        raise HTTPException(status_code=500, detail={"message": "database connection failed"})
    return {"status": "ok", "message": "db connection is successful"}
