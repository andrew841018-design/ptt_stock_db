import matplotlib.pyplot as plt
import pandas as pd
# 中文字型：依 macOS / Linux / Windows 順序列出候選，matplotlib 會挑第一個存在的。
# EC2 Ubuntu 需先 `sudo apt-get install -y fonts-noto-cjk` 並清掉 ~/.cache/matplotlib。
plt.rcParams['font.family']       = 'sans-serif'
plt.rcParams['font.sans-serif']   = [
    'PingFang TC',          # macOS 繁中
    'Heiti TC',             # macOS 備援
    'Noto Sans CJK JP',     # Linux (fonts-noto-cjk) — .ttc 統一註冊為 JP family，含所有 CJK 字形
    'Noto Sans CJK TC',
    'WenQuanYi Zen Hei',    # Linux 備援
    'Microsoft JhengHei',   # Windows 繁中
    'DejaVu Sans',          # 最後備援（僅英數）
]
plt.rcParams['axes.unicode_minus'] = False  # 負號顯示
plt.rcParams['figure.figsize']     = (12, 6)
plt.rcParams['font.size']          = 14
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
    """
    推文數分桶 × 情緒分數 box plot。

    為什麼不用 scatter：171k 個點全疊在 [-100, 100] × [-1, 1] 的小區塊裡，
    會糊成一片色塊看不出任何訊號。分桶後直接比較各桶的情緒中位數，可以回答
    核心問題——「推文數越高的文章，情緒是否越正向？」

    分桶邏輯（貼近 PTT 文化 + Reddit 正規化後 -100~100）：
        噓文(<0) / 冷門(0) / 低推(1-9) / 中推(10-49) / 高推(≥50)
    """
    df = df.dropna(subset=['Push_count', 'Article_Sentiment_Score']).copy()
    fig, ax = plt.subplots()
    if df.empty:
        ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=ax.transAxes)
        return fig

    bins   = [-101, -1, 0, 10, 50, 101]
    labels = ['噓文(<0)', '冷門(0)', '低推(1-9)', '中推(10-49)', '高推(≥50)']
    df['push_bucket'] = pd.cut(df['Push_count'], bins=bins, labels=labels, include_lowest=True)

    grouped = [df.loc[df['push_bucket'] == lbl, 'Article_Sentiment_Score'].values
               for lbl in labels]
    counts  = [len(bucket) for bucket in grouped]

    bp = ax.boxplot(
        grouped,
        tick_labels=labels,                                  # matplotlib 3.9+ API，3.11 將移除舊的 labels=
        showfliers=False,                                    # outlier 點太多反而蓋掉 box，關掉
        patch_artist=True,
        medianprops={'color': 'red', 'linewidth': 2},
    )

    # 噓文紅 → 爆文綠的漸層，語意化顏色
    colors = ['#d9534f', '#6c757d', '#f0ad4e', '#5bc0de', '#5cb85c']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)

    ax.axhline(y=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.set_xlabel('推文數區間')
    ax.set_ylabel('情緒分數')
    ax.set_title(f'各推文數區間的情緒分數分布（n={len(df):,}）')

    # 每個桶下緣標註樣本數
    y_lo, y_hi = ax.get_ylim()
    for idx, count in enumerate(counts, start=1):
        ax.text(idx, y_lo + (y_hi - y_lo) * 0.02, f'n={count:,}',
                ha='center', va='bottom', fontsize=9, color='dimgray')

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
