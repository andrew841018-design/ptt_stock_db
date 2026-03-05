import pandas as pd 
import re
import sqlite3
from sentiment import calculate_sentiment
def numberic_push_count(push_count):
    if push_count=="爆":
        return 100
    elif push_count.startswith("X"):
        return int(push_count.strip("X"))*-10
    else:
        return int(push_count)
conn=sqlite3.connect('ptt_stock.db')
cursor=conn.cursor()
#clean ptt_stock_article_info
df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
pd.set_option('display.max_colwidth', None)
df['Scraped_time']=pd.to_datetime(df['Scraped_time'])
#新建一個欄位：分析url，抓出『M.』後面的數字(單位當成秒)，並轉換為datetime
df['Published_Time']=df['Url'].apply(lambda url:pd.to_datetime(int(re.search(r'M\.(\d+)\.',url).group(1)),unit="s"))+pd.Timedelta(hours=8)

# 去除重複
column_list=['Article_id','Title','Url','Push_count','Published_Time','Scraped_time']
for column in column_list:
    df=df.drop_duplicates(subset=column)

# 推噓數轉換為數字
df['Push_count']=df['Push_count'].apply(numberic_push_count)

#clean ptt_stock_comment_info
df=pd.read_sql_query("SELECT * FROM ptt_stock_comment_info",conn)
df['Push_tag']=df['Push_tag'].astype("category")
df['Message']=df['Message'].str.lstrip(":")

# create new column for sentiment score
try:
    cursor.execute("ALTER TABLE ptt_stock_article_info ADD COLUMN Article_Sentiment_Score INTEGER")
    cursor.execute("ALTER TABLE ptt_stock_comment_info ADD COLUMN Comment_Sentiment_Score INTEGER")
    conn.commit()
except sqlite3.OperationalError:
    print("Column already exists")

#calculate sentiment score for title and content
df=pd.read_sql_query("SELECT Title,Content,Article_id FROM ptt_stock_article_info",conn)
df['Article_Sentiment_Score']=df.apply(lambda row: calculate_sentiment(str(row['Title']))*2+calculate_sentiment(str(row['Content'])),axis=1)

# store back to database
for _,row in df.iterrows():
    cursor.execute("UPDATE ptt_stock_article_info SET Article_Sentiment_Score=? WHERE Article_id=?",(row['Article_Sentiment_Score'],row['Article_id']))
conn.commit()

#calculate sentiment score for message
df=pd.read_sql_query("SELECT Message,Comment_id,Article_id FROM ptt_stock_comment_info",conn)
df['Comment_Sentiment_Score']=df['Message'].apply(calculate_sentiment)

# store back to database
for _,row in df.iterrows():
    cursor.execute("UPDATE ptt_stock_comment_info SET Comment_Sentiment_Score=? WHERE Comment_id=?",(row['Comment_Sentiment_Score'],row['Comment_id']))
conn.commit()
conn.close()