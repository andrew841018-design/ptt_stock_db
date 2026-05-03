from fastapi import FastAPI,Query
import sqlite3
import pandas as pd
import datetime
from typing import Literal
from fastapi import HTTPException
app=FastAPI()
PERIOD_MIN=1
PERIOD_MAX=30
ARTICLE_LIMIT_MIN=1
ARTICLE_LIMIT_MAX=100
ARTICLE_PERIOD_MIN=1
ARTICLE_PERIOD_MAX=365
#TODO:

def get_db_connection():
    return sqlite3.connect('ptt_stock.db')
@app.get("/sentiments/today")#名稱可自由設計
def get_today_sentiment():
    conn=None
    try:
        conn=get_db_connection()
        df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database search failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    df['Published_Time']=pd.to_datetime(df['Published_Time'])
    df['Published_Date']=df['Published_Time'].dt.date
    today=df[df['Published_Date']==df['Published_Date'].max()]
    if len(today)==0:
        raise HTTPException(status_code=404,detail={"message":"No data for today"})
    sentiment_score=round(today['Article_Sentiment_Score'].mean(),2)
    return {"date":str(today['Published_Date'].max()),"sentiment_score":sentiment_score,"message":"Success"}
@app.get("/sentiments/change")
def get_change_sentiment():
    conn=None
    try:
        conn=get_db_connection()
        df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database search failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    df['Published_Time']=pd.to_datetime(df['Published_Time'])
    df['Published_Date']=df['Published_Time'].dt.date
    today=df[df['Published_Date']==df['Published_Date'].max()]
    yesterday=df[df['Published_Date']==df['Published_Date'].max()-datetime.timedelta(days=1)]
    if len(today)==0 or len(yesterday)==0:
        raise HTTPException(status_code=404,detail={"message":"No data for today or yesterday"})
    change_score=round(today['Article_Sentiment_Score'].mean()-yesterday['Article_Sentiment_Score'].mean(),2)
    return {"change_sentiment_score":change_score,"message":"Success"}
@app.get("/sentiments/recent")
def get_recent_sentiment_score(period:int=Query(default=10,ge=PERIOD_MIN,le=PERIOD_MAX)):
    conn=None
    try:
        conn=get_db_connection()
        df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database search failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    if len(df)==0:
        raise HTTPException(status_code=404,detail={"message":"No data"})
    df['Published_Time']=pd.to_datetime(df['Published_Time'])
    start_time=df['Published_Time'].max()-datetime.timedelta(days=period)
    recent_data=df[df['Published_Time']>=start_time]
    if len(recent_data)==0:
        raise HTTPException(status_code=404,detail={"message": f"No data for the past {period} days"})
    recent_score=round(recent_data['Article_Sentiment_Score'].mean(),2)
    return {f"recent_{period}_days_sentiment_score":recent_score,"message":"Success"}
@app.get("/articles/top_push")
def get_top_push_articles(
    limit:int=Query(default=10,ge=ARTICLE_LIMIT_MIN,lt=ARTICLE_LIMIT_MAX+1),
    period:int=Query(default=7,ge=ARTICLE_PERIOD_MIN,lt=ARTICLE_PERIOD_MAX+1),#days
    period_type:Literal["day","week","month","year"]=Query(default="day"),#day,week,month,year
    ):
    conn=None
    try:
        conn=get_db_connection()
        df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database search failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    if len(df)==0:
        raise HTTPException(status_code=404,detail={"message":"No data"})
    df['Published_Time']=pd.to_datetime(df['Published_Time'])
    df['Push_count']=df['Push_count'].astype(int)
    df['Published_Time']=df['Published_Time'].dt.date
    #filter by period
    end_date=df['Published_Time'].max()
    days_map={"day":1,"week":7,"month":30,"year":365}
    total_days=period*days_map[period_type]
    start_date=end_date-datetime.timedelta(days=total_days)
    filtered_df=df[df['Published_Time']>=start_date]
    top_articles=filtered_df.nlargest(limit,'Push_count')[['Title','Push_count','Published_Time','Url']]
    if len(top_articles)==0:
        raise HTTPException(status_code=404,detail={"message":"No data"})
    return {
    "note":"Push_count 100 表示『爆』(實際值 ≥ 100)，-100 表示『XX』(實際值 ≤ -100)",
    f"top_{limit}_articles":top_articles.to_dict(orient="records"),
    "message":"Success"
    }
@app.get("/articles/search")
#...表示必填，使用者不填入內容會出錯
def search_articles(keyword:str):
    conn=None
    try:
        conn=get_db_connection()
        df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database search failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    if len(df)==0:
        raise HTTPException(status_code=404,detail={"message":"No data found"})
    #case=False-表示不區分大小寫，na=False-表示不處理缺失值
    result=df[df['Title'].str.contains(keyword,case=False,na=False) | df['Content'].str.contains(keyword,case=False,na=False)]
    if len(result)==0:
        raise HTTPException(status_code=404,detail={"message":"No related articles"})
    return {"search_articles":result[['Title','Push_count','Published_Time','Url']].to_dict(orient="records"),"message":"Success"}
@app.get("/health")
def health_check():
    conn=None
    try:
        conn=get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500,detail={"message":"database connection failed: "+str(e)})
    finally:
        if conn:
            conn.close()
    return {"status":"ok","message":"db connection is successful"}