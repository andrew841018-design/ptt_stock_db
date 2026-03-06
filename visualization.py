import matplotlib.pyplot as plt
import sqlite3
import pandas as pd
import matplotlib.dates as mdates
import datetime
import re
from data_cleanner import clean_all
def set_x_axis_format(plt):
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45)
#setting
plt.rcParams['font.family']='Arial' #字型
plt.rcParams['font.sans-serif']='Microsoft JhengHei' #中文字型
plt.rcParams['axes.unicode_minus']=False #負號顯示
plt.rcParams['figure.figsize']=(12,6)#圖片大小
plt.rcParams['font.size']=14
conn=sqlite3.connect('ptt_stock.db')
cursor=conn.cursor()
df=pd.read_sql_query("SELECT * FROM ptt_stock_article_info",conn)
df=clean_all(df,'ptt_stock_article_info')
#format
current_year=datetime.datetime.now().year
df['Published_Time']=df['Url'].apply(lambda url:pd.to_datetime(int(re.search(r'M\.(\d+)\.',url).group(1)),unit="s"))+pd.Timedelta(hours=8)
df['Date']=df['Published_Time'].dt.date

daily_sentiment=df.groupby('Date')['Article_Sentiment_Score'].mean()
print(f"資料期間:{df['Date'].min()} ~ {df['Date'].max()}")

#sentiment trend=>越高，表示文章的平均情緒越正面
plt.figure()
plt.gcf().autofmt_xdate()
plt.plot(daily_sentiment.index,daily_sentiment.values)
plt.title('Ptt Stock Daily Sentiment Trend')
plt.xlabel('Date')
plt.ylabel('Average Article Sentiment Score')
plt.savefig('daily_sentiment.png')


#push count distribution=>對文章的認同程度＋情緒正負面
plt.figure()
plt.scatter(df['Push_count'],df['Article_Sentiment_Score'])
plt.xlabel('Push Count')
plt.ylabel('Article Sentiment Score')
plt.title('Ptt Stock Article Push Count vs Sentiment Score')
plt.axhline(y=0,color='r',linestyle='--')
plt.axvline(x=0,color='r',linestyle='--')
plt.savefig('push_count_vs_sentiment_score.png')

#group by date and count the number of articles
plt.figure()
plt.gcf().autofmt_xdate()
daily_count=df.groupby('Date').size()
plt.bar(daily_count.index,daily_count.values)
plt.xlabel('Date')
plt.ylabel('Article Count')
plt.title('Ptt Stock Daily Article Count')
plt.savefig('daily_article_count.png')
plt.show()#這行結束後會清空畫布

conn.close()
