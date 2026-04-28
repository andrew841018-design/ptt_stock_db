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
    ax.set_title('Daily Sentiment Trend')
    ax.set_xlabel('Date')
    ax.set_ylabel('Average Article Sentiment Score')
    return fig
def plot_daily_article_count(df: pd.DataFrame) -> plt.Figure:
    """group by date and count the number of articles"""
    fig,ax=plt.subplots()
    fig.autofmt_xdate()
    daily_count=df.groupby('Date').size()
    ax.bar(daily_count.index,daily_count.values)
    ax.set_xlabel('Date')
    ax.set_ylabel('Article Count')
    ax.set_title('Daily Article Count')
    return fig


def plot_sentiment_vs_stock(df: pd.DataFrame, stock_name: str, market_label: str = "") -> plt.Figure:
    """
    情緒分數 vs 隔日股價漲跌散布圖。
    df 需包含欄位：avg_sentiment、next_day_change
    market_label：圖表前綴（e.g. "TW" / "US"），留空則不顯示
    """
    fig, ax = plt.subplots()
    ax.scatter(df['avg_sentiment'], df['next_day_change'], alpha=0.6)
    ax.axhline(y=0, color='r', linestyle='--', linewidth=0.8)  # 漲跌 0 基準線
    ax.axvline(x=0, color='r', linestyle='--', linewidth=0.8)  # 情緒 0 基準線
    prefix = f'{market_label} ' if market_label else ''
    ax.set_xlabel(f'{prefix}平均情緒分數')
    ax.set_ylabel('隔日漲跌（元）')
    ax.set_title(f'{prefix}情緒 vs {stock_name} 隔日漲跌')
    return fig


def plot_sentiment_and_price_trend(df: pd.DataFrame, stock_name: str, market_label: str = "") -> plt.Figure:
    """
    情緒分數與隔日漲跌趨勢雙軸折線圖。
    df 需包含欄位：sentiment_date、avg_sentiment、next_day_change
    market_label：圖表前綴（e.g. "TW" / "US"），留空則不顯示
    """
    fig, ax1 = plt.subplots()

    prefix = f'{market_label} ' if market_label else ''

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
    ax1.set_title(f'{prefix}情緒 vs {stock_name} 隔日漲跌趨勢')
    return fig


def plot_sentiment_avg_by_source_bar(df: pd.DataFrame) -> plt.Figure:
    """
    各來源「整段期間平均情緒」橫條圖。
    一眼回答：哪個來源最樂觀 / 最悲觀？
    紅色 < 0 / 綠色 ≥ 0；按平均情緒從正到負排序（高在上）。
    """
    fig, ax = plt.subplots(figsize=(6, 4.5))

    avg = (
        df.groupby('Source')['Article_Sentiment_Score']
        .agg(['mean', 'count'])
        .sort_values('mean', ascending=True)  # ascending 配合 barh 顯示時自然由上到下從正到負
    )

    if avg.empty:
        ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=ax.transAxes)
        return fig

    colors = ['#5cb85c' if v >= 0 else '#d9534f' for v in avg['mean'].values]
    y = range(len(avg))
    ax.barh(y, avg['mean'].values, color=colors, edgecolor='white', height=0.65)

    # 每條右邊標數字
    for i, (val, cnt) in enumerate(zip(avg['mean'].values, avg['count'].values)):
        offset = 0.01 if val >= 0 else -0.01
        ha = 'left' if val >= 0 else 'right'
        ax.text(val + offset, i, f'{val:+.2f}', va='center', ha=ha,
                fontsize=11, fontweight='bold')

    # y 軸：來源 + 樣本數
    ylabels = [f'{src}\n({cnt:,} 篇)' for src, cnt in zip(avg.index, avg['count'].values)]
    ax.set_yticks(list(y))
    ax.set_yticklabels(ylabels, fontsize=9)
    ax.set_xlim(-1, 1)
    ax.axvline(x=0, color='gray', linestyle='-', linewidth=0.8, alpha=0.6)
    ax.set_xlabel('Average Sentiment Score')
    ax.set_title('當期平均情緒（哪個來源最樂觀 / 最悲觀？）')

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return fig
