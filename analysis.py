import pandas as pd 
import re
from tqdm import tqdm
import sqlite3
from sentiment import calculate_sentiment
def numberic_push_count(push_count):
    if push_count=="爆":
        return 100
    elif push_count=="XX":
        return -100
    elif push_count.startswith("X"):
        return int(push_count.strip("X"))*-10
    else:
        return int(push_count)
def clean_article_info(conn,cursor):
    df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
    pd.set_option('display.max_colwidth', None)
    df['Article_Sentiment_Score']=df.progress_apply(lambda row: calculate_sentiment(str(row['Title']))*2+calculate_sentiment(str(row['Content'])),axis=1)

    #新建一個欄位：分析url，抓出『M.』後面的數字(單位當成秒)，並轉換為datetime
    df['Published_Time']=df['Url'].progress_apply(lambda url:pd.to_datetime(int(re.search(r'M\.(\d+)\.',url).group(1)),unit="s"))+pd.Timedelta(hours=8)
    df['Push_count']=df['Push_count'].progress_apply(numberic_push_count)# 推噓數轉換為數字

    # store back to database
    df['Published_Time']=df['Published_Time'].astype(str)
    df['Push_count']=df['Push_count'].astype(int)
    df['Article_Sentiment_Score']=df['Article_Sentiment_Score'].astype(int)
    record_list=df[['Published_Time','Push_count','Article_Sentiment_Score','Article_id']].values.tolist()
    cursor.executemany("UPDATE ptt_stock_article_info SET Published_Time=?, Push_count=?, Article_Sentiment_Score=? WHERE Article_id=?",record_list)
def clean_comment_info(conn,cursor):
    df=pd.read_sql_query("SELECT * FROM ptt_stock_comment_info",conn)
    df['Message']=df['Message'].str.lstrip(":")
    df['Comment_Sentiment_Score']=df['Message'].progress_apply(calculate_sentiment)

    # store back to database
    record_list=df[['Comment_Sentiment_Score','Comment_id']].values.tolist()
    cursor.executemany("UPDATE ptt_stock_comment_info SET Comment_Sentiment_Score=? WHERE Comment_id=?",record_list)
if __name__=="__main__":
    conn=sqlite3.connect('ptt_stock.db')
    cursor=conn.cursor()
    tqdm.pandas()
    # create new column
    for sql in ["ALTER TABLE ptt_stock_article_info ADD COLUMN Article_Sentiment_Score INTEGER",
                "ALTER TABLE ptt_stock_comment_info ADD COLUMN Comment_Sentiment_Score INTEGER",
                "ALTER TABLE ptt_stock_article_info ADD COLUMN Published_Time INTEGER"]:
        try:
            cursor.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            print(f"Column {sql} already exist")
    clean_article_info(conn,cursor)
    clean_comment_info(conn,cursor)
    conn.commit()
    conn.close()
    print("Data cleaning completed")