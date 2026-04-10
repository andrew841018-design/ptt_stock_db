import pandas as pd
import datetime
from typing import Literal, Optional
from fastapi import FastAPI, Query, HTTPException, Depends
from pydantic import BaseModel
from pg_helper import get_pg, get_pg_readonly
from cache_helper import get_cache, set_cache
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, STOCK_PRICES_TABLE
from data_mart import get_daily_sentiment

CACHE_KEY_ARTICLES = "articles_df"
from auth import create_token, verify_token, authenticate_user


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

class AIModelPredictionDailyPoint(BaseModel):
    date: datetime.date
    strategy_cumulative_return: float   # 1.025 = +2.5%
    buy_and_hold_return: float

class AIModelPredictionResponse(BaseModel):
    market: str
    display_name: str
    accuracy: float
    strategy_cumulative_return: float   # 最終值（1.025 = +2.5%）
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

app = FastAPI(title="PTT Stock Sentiment API", description="JWT 保護的情緒分析 API")

PERIOD_MIN         = 1
PERIOD_MAX         = 30
ARTICLE_LIMIT_MIN  = 1
ARTICLE_LIMIT_MAX  = 100
ARTICLE_PERIOD_MIN = 1
ARTICLE_PERIOD_MAX = 365


# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    """帳密驗證 → 回傳 JWT token"""
    user = authenticate_user(req.username, req.password)
    token = create_token(user["username"], user["role"])
    from config import JWT_EXPIRE_MINUTES
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": JWT_EXPIRE_MINUTES,
    }


# ── Data Loading（articles 個別資料，top_push / search 用）────────────────────

def load_articles_df() -> pd.DataFrame:
    """讀取文章資料（JOIN sentiment_scores），Cache-Aside：先查 Redis，沒有再查 DB"""
    df = get_cache(CACHE_KEY_ARTICLES)
    if df is not None:
        return df
    try:
        with get_pg_readonly() as conn:
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
# Depends(verify_token) 表示這個function需要一個JWT token，如果沒有token，會返回401錯誤
def get_today_sentiment(user: dict = Depends(verify_token)) -> TodaySentimentResponse:
    rows = get_daily_sentiment(days=7)  # 取近 7 天，拿最新一天
    if not rows:
        raise HTTPException(status_code=404, detail={"message": "No data for today"})
    latest = rows[0]  # ORDER BY summary_date DESC，第一筆就是最新
    return {
        "date": str(latest["summary_date"]),
        "sentiment_score": round(float(latest["avg_sentiment"]), 2),
        "message": "Success",
    }


@app.get("/sentiments/change", response_model=ChangeSentimentResponse)
def get_change_sentiment(user: dict = Depends(verify_token)) -> ChangeSentimentResponse:
    rows = get_daily_sentiment(days=7)  # 取近 7 天，拿最新兩天比較
    if len(rows) < 2:
        raise HTTPException(status_code=404, detail={"message": "No data for today or yesterday"})
    today_score     = float(rows[0]["avg_sentiment"])
    yesterday_score = float(rows[1]["avg_sentiment"])
    return {
        "change_sentiment_score": round(today_score - yesterday_score, 2),
        "message": "Success",
    }


@app.get("/sentiments/recent", response_model=RecentSentimentResponse)
def get_recent_sentiment_score(period: int = Query(default=10, ge=PERIOD_MIN, le=PERIOD_MAX), user: dict = Depends(verify_token)):
    rows = get_daily_sentiment(days=period)
    if not rows:
        raise HTTPException(status_code=404, detail={"message": f"No data for the past {period} days"})
    # 加權平均：各天 avg_sentiment × total_articles，再除以總文章數
    total_articles = sum(r["total_articles"] for r in rows)
    weighted_sum   = sum(float(r["avg_sentiment"]) * r["total_articles"] for r in rows)
    recent_score   = round(weighted_sum / total_articles, 2)
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
def search_articles(keyword: str, user: dict = Depends(verify_token)) -> SearchResponse:
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data found"})
    # case=False-表示不區分大小寫，na=False-表示不處理缺失值
    result = df[df['Title'].str.contains(keyword, case=False, na=False)]
    if len(result) == 0:
        raise HTTPException(status_code=404, detail={"message": "No related articles"})
    return {"search_articles": result[['Title', 'Push_count', 'Published_Time', 'Url']].to_dict(orient="records"), "message": "Success"}


@app.get("/correlation/0050", response_model=SentimentVsStockPriceResponse)
def get_sentiment_vs_stock_price_correlation(period: int = Query(default=30, ge=1, le=365), user: dict = Depends(verify_token)):
    """
    PTT 情緒分數 vs 0050 隔日漲跌。
    改用 mart_daily_summary（pre-computed），不再即時 JOIN articles + sentiment_scores。
    """
    try:
        with get_pg_readonly() as conn:
            df = pd.read_sql_query(f"""
                SELECT
                    m.summary_date         AS sentiment_date,
                    SUM(m.avg_sentiment * m.total_articles)
                        / NULLIF(SUM(m.total_articles), 0)
                                           AS avg_sentiment,
                    sp.change              AS next_day_change
                FROM mart_daily_summary m
                JOIN {STOCK_PRICES_TABLE} sp
                    ON sp.trade_date = m.summary_date + INTERVAL '1 day'
                WHERE m.summary_date >= CURRENT_DATE - INTERVAL '{period} days'
                  AND m.avg_sentiment IS NOT NULL
                GROUP BY m.summary_date, sp.change
                ORDER BY m.summary_date
            """, conn)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": str(e)})

    if df.empty:
        raise HTTPException(status_code=404, detail={"message": "查無資料，mart_daily_summary 可能尚未刷新"})

    return {"period": period, "data": df.to_dict(orient="records")}


@app.get("/ai_model_prediction/{market}", response_model=AIModelPredictionResponse)
def get_ai_model_prediction(market: str, user: dict = Depends(verify_token)) -> AIModelPredictionResponse:
    """
    Walk-Forward AI 模型預測結果。即時重算，不走快取（MLflow + ai_model_prediction_runs 有歷史）。
    市場：tw（0050）/ us（VOO）
    """
    if market not in ("tw", "us"):
        raise HTTPException(status_code=400, detail={"message": "market must be 'tw' or 'us'"})

    # lazy import：ai_model_prediction 拖 sklearn + torch，放 module-level 會拖慢 FastAPI 啟動
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
    """公開 endpoint，不需要 JWT token"""
    try:
        with get_pg_readonly() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")#測試用語法，確認db活著
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "database connection failed: " + str(e)})
    return {"status": "ok", "message": "db connection is successful"}
