import pandas as pd
import datetime
from typing import Literal
from fastapi import FastAPI, Query, HTTPException
from pg_helper import get_pg
from cache_helper import get_cache, set_cache
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE

app = FastAPI()

CACHE_KEY_ARTICLES  = "articles_df"

PERIOD_MIN          = 1
PERIOD_MAX          = 30
ARTICLE_LIMIT_MIN   = 1
ARTICLE_LIMIT_MAX   = 100
ARTICLE_PERIOD_MIN  = 1
ARTICLE_PERIOD_MAX  = 365


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
                    ON  s.target_id   = a.article_id
                    AND s.target_type = 'article'
                    AND s.method      = 'jieba'
            """, conn)
        set_cache(CACHE_KEY_ARTICLES, df)
        return df
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "database search failed: " + str(e)})


@app.get("/sentiments/today")  # 名稱可自由設計
def get_today_sentiment():
    df = load_articles_df()
    df['Published_Time'] = pd.to_datetime(df['Published_Time'])
    df['Published_Date'] = df['Published_Time'].dt.date
    today = df[df['Published_Date'] == df['Published_Date'].max()]
    if len(today) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data for today"})
    sentiment_score = round(today['Article_Sentiment_Score'].mean(), 2)
    return {"date": str(today['Published_Date'].max()), "sentiment_score": sentiment_score, "message": "Success"}


@app.get("/sentiments/change")
def get_change_sentiment():
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    df['Published_Time'] = pd.to_datetime(df['Published_Time'])
    df['Published_Date'] = df['Published_Time'].dt.date
    today     = df[df['Published_Date'] == df['Published_Date'].max()]
    yesterday = df[df['Published_Date'] == df['Published_Date'].max() - datetime.timedelta(days=1)]
    if len(today) == 0 or len(yesterday) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data for today or yesterday"})
    change_score = round(today['Article_Sentiment_Score'].mean() - yesterday['Article_Sentiment_Score'].mean(), 2)
    return {"change_sentiment_score": change_score, "message": "Success"}


@app.get("/sentiments/recent")
def get_recent_sentiment_score(period: int = Query(default=10, ge=PERIOD_MIN, le=PERIOD_MAX)):
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    df['Published_Time'] = pd.to_datetime(df['Published_Time'])
    start_time  = df['Published_Time'].max() - datetime.timedelta(days=period)
    recent_data = df[df['Published_Time'] >= start_time]
    if len(recent_data) == 0:
        raise HTTPException(status_code=404, detail={"message": f"No data for the past {period} days"})
    recent_score = round(recent_data['Article_Sentiment_Score'].mean(), 2)
    return {f"recent_{period}_days_sentiment_score": recent_score, "message": "Success"}


@app.get("/articles/top_push")
def get_top_push_articles(
    limit:       int                                      = Query(default=10, ge=ARTICLE_LIMIT_MIN, lt=ARTICLE_LIMIT_MAX + 1),
    period:      int                                      = Query(default=7,  ge=ARTICLE_PERIOD_MIN, lt=ARTICLE_PERIOD_MAX + 1),  # days
    period_type: Literal["day", "week", "month", "year"] = Query(default="day"),
):
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    df['Published_Time'] = pd.to_datetime(df['Published_Time'])
    df['Published_Time'] = df['Published_Time'].dt.date
    # filter by period
    end_date  = df['Published_Time'].max()
    days_map  = {"day": 1, "week": 7, "month": 30, "year": 365}
    total_days = period * days_map[period_type]
    start_date = end_date - datetime.timedelta(days=total_days)
    filtered_df  = df[df['Published_Time'] >= start_date]
    top_articles = filtered_df.nlargest(limit, 'Push_count')[['Title', 'Push_count', 'Published_Time', 'Url']]
    if len(top_articles) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data"})
    return {
        "note": "Push_count 100 表示『爆』(實際值 ≥ 100)，-100 表示『XX』(實際值 ≤ -100)",
        f"top_{limit}_articles": top_articles.to_dict(orient="records"),
        "message": "Success"
    }


@app.get("/articles/search")
# ...表示必填，使用者不填入內容會出錯
def search_articles(keyword: str):
    df = load_articles_df()
    if len(df) == 0:
        raise HTTPException(status_code=404, detail={"message": "No data found"})
    # case=False-表示不區分大小寫，na=False-表示不處理缺失值
    result = df[df['Title'].str.contains(keyword, case=False, na=False)]
    if len(result) == 0:
        raise HTTPException(status_code=404, detail={"message": "No related articles"})
    return {"search_articles": result[['Title', 'Push_count', 'Published_Time', 'Url']].to_dict(orient="records"), "message": "Success"}


@app.get("/health")
def health_check():
    try:
        with get_pg() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")#測試用語法，確認db活著
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "database connection failed: " + str(e)})
    return {"status": "ok", "message": "db connection is successful"}
