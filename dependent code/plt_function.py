import matplotlib.pyplot as plt
#setting
plt.rcParams['font.family']='Arial' #字型
plt.rcParams['font.sans-serif']='Microsoft JhengHei' #中文字型
plt.rcParams['axes.unicode_minus']=False #負號顯示
plt.rcParams['figure.figsize']=(12,6)#圖片大小
plt.rcParams['font.size']=14
def plot_sentiment_trend(df):
    #sentiment trend=>越高，表示文章的平均情緒越正面
    fig,ax=plt.subplots()
    daily_sentiment=df.groupby('Date')['Article_Sentiment_Score'].mean()
    ax.plot(daily_sentiment.index,daily_sentiment.values)
    fig.autofmt_xdate()
    ax.set_title('Ptt Stock Daily Sentiment Trend')
    ax.set_xlabel('Date')
    ax.set_ylabel('Average Article Sentiment Score')
    return fig
def plot_push_count_distribution(df):
    #push count distribution=>對文章的認同程度＋情緒正負面
    fig,ax=plt.subplots()
    ax.scatter(df['Push_count'],df['Article_Sentiment_Score'])
    ax.set_xlabel('Push Count')
    ax.set_ylabel('Article Sentiment Score')
    ax.set_title('Ptt Stock Article Push Count vs Sentiment Score')
    ax.axhline(y=0,color='r',linestyle='--')
    ax.axvline(x=0,color='r',linestyle='--')
    return fig
def plot_daily_article_count(df):
    #group by date and count the number of articles
    fig,ax=plt.subplots()
    fig.autofmt_xdate()
    daily_count=df.groupby('Date').size()
    ax.bar(daily_count.index,daily_count.values)
    ax.set_xlabel('Date')
    ax.set_ylabel('Article Count')
    ax.set_title('Ptt Stock Daily Article Count')
    return fig

