import matplotlib.pyplot as plt
import pandas as pd
#setting
plt.rcParams['font.family']='Arial' #字型
plt.rcParams['font.sans-serif']='Microsoft JhengHei' #中文字型
plt.rcParams['axes.unicode_minus']=False #負號顯示
plt.rcParams['figure.figsize']=(12,6)#圖片大小
plt.rcParams['font.size']=14
def plot_sentiment_trend(df: pd.DataFrame) -> plt.Figure:
    """#sentiment trend=>越高，表示文章的平均情緒越正面"""
    fig,ax=plt.subplots()
    daily_sentiment=df.groupby('Date')['Article_Sentiment_Score'].mean()
    ax.plot(daily_sentiment.index,daily_sentiment.values)
    fig.autofmt_xdate()
    ax.set_title('Ptt Stock Daily Sentiment Trend')
    ax.set_xlabel('Date')
    ax.set_ylabel('Average Article Sentiment Score')
    return fig
def plot_push_count_distribution(df: pd.DataFrame) -> plt.Figure:
    """#push count distribution=>對文章的認同程度＋情緒正負面"""
    fig,ax=plt.subplots()
    ax.scatter(df['Push_count'],df['Article_Sentiment_Score'])
    ax.set_xlabel('Push Count')
    ax.set_ylabel('Article Sentiment Score')
    ax.set_title('Ptt Stock Article Push Count vs Sentiment Score')
    ax.axhline(y=0,color='r',linestyle='--')
    ax.axvline(x=0,color='r',linestyle='--')
    return fig
def plot_daily_article_count(df: pd.DataFrame) -> plt.Figure:
    """group by date and count the number of articles"""
    fig,ax=plt.subplots()
    fig.autofmt_xdate()
    daily_count=df.groupby('Date').size()
    ax.bar(daily_count.index,daily_count.values)
    ax.set_xlabel('Date')
    ax.set_ylabel('Article Count')
    ax.set_title('Ptt Stock Daily Article Count')
    return fig


def plot_sentiment_vs_stock(df: pd.DataFrame, stock_name: str) -> plt.Figure:
    """
    情緒分數 vs 隔日股價漲跌散布圖。
    df 需包含欄位：avg_sentiment、next_day_change
    """
    fig, ax = plt.subplots()
    ax.scatter(df['avg_sentiment'], df['next_day_change'], alpha=0.6)
    ax.axhline(y=0, color='r', linestyle='--', linewidth=0.8)  # 漲跌 0 基準線
    ax.axvline(x=0, color='r', linestyle='--', linewidth=0.8)  # 情緒 0 基準線
    ax.set_xlabel('PTT 平均情緒分數')
    ax.set_ylabel('隔日漲跌（元）')
    ax.set_title(f'PTT 情緒 vs {stock_name} 隔日漲跌')
    return fig


def plot_sentiment_and_price_trend(df: pd.DataFrame, stock_name: str) -> plt.Figure:
    """
    情緒分數與隔日漲跌趨勢雙軸折線圖。
    df 需包含欄位：sentiment_date、avg_sentiment、next_day_change
    """
    fig, ax1 = plt.subplots()

    # 左軸：情緒分數
    ax1.plot(df['sentiment_date'], df['avg_sentiment'], color='steelblue', label='情緒分數')
    ax1.set_xlabel('日期')
    ax1.set_ylabel('平均情緒分數', color='steelblue')
    ax1.tick_params(axis='y', labelcolor='steelblue')

    # 右軸：隔日漲跌價差
    ax2 = ax1.twinx()
    ax2.plot(df['sentiment_date'], df['next_day_change'], color='darkorange', label='隔日漲跌')
    ax2.set_ylabel('隔日漲跌價差（元）', color='darkorange')
    ax2.tick_params(axis='y', labelcolor='darkorange')

    fig.autofmt_xdate()
    ax1.set_title(f'PTT 情緒 vs {stock_name} 隔日漲跌趨勢')
    return fig
