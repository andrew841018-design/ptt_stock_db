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
def plot_push_count_distribution(df: pd.DataFrame) -> plt.Figure:
    """
    各推文數區間的「正向文章比例」橫條圖。

    設計演進（越改越簡單）：
    - v1 scatter：171k 點糊成色塊
    - v2 box plot：需要統計素養（看 median/IQR）
    - v3 100% stacked bar：三色並列仍要比對
    - v4（此版）一個桶子 = 一個數字「這區間有幾 % 文章是正向的」
      非技術背景的人一眼就能回答「哪種推文數的文章最正向」。
      長條越長越正向、紅色 < 50% / 綠色 ≥ 50%。
    """
    df = df.dropna(subset=['Push_count', 'Article_Sentiment_Score']).copy()
    fig, ax = plt.subplots()
    if df.empty:
        ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=ax.transAxes)
        return fig

    push_bins   = [-101, -1, 0, 10, 50, 101]
    push_labels = ['噓文 (<0)', '冷門 (0 推)', '低推 (1-9 推)', '中推 (10-49 推)', '高推 (≥50 推)']
    df['push_bucket'] = pd.cut(df['Push_count'], bins=push_bins,
                               labels=push_labels, include_lowest=True)
    # 正向 = 情緒分數 > 0.05（跟 VADER 慣例一致）
    df['is_positive'] = df['Article_Sentiment_Score'] > 0.05

    pos_ratio = df.groupby('push_bucket', observed=True)['is_positive'].mean() * 100
    pos_ratio = pos_ratio.reindex(push_labels)
    counts    = df['push_bucket'].value_counts().reindex(push_labels)

    # 單一 threshold 配色：≥50% 綠、<50% 紅，方便「及格 / 不及格」直覺判讀
    colors = ['#5cb85c' if p >= 50 else '#d9534f' for p in pos_ratio.values]

    y = range(len(push_labels))
    ax.barh(y, pos_ratio.values, color=colors, edgecolor='white', height=0.65)

    # 每條右邊寫大大的百分比
    for i, val in enumerate(pos_ratio.values):
        ax.text(val + 1, i, f'{val:.0f}%', va='center',
                fontsize=16, fontweight='bold')

    # y 軸：推文桶 + 樣本數註記
    ylabels = [f'{lbl}\n({cnt:,} 篇)' for lbl, cnt in zip(push_labels, counts)]
    ax.set_yticks(list(y))
    ax.set_yticklabels(ylabels)
    ax.invert_yaxis()                          # 噓文在上、高推在下（由冷到熱）
    ax.set_xlim(0, 100)
    ax.set_xlabel('正向文章比例 (%)')
    ax.set_title('哪種推文數的文章最「正向」？')

    # 50% 基準線：一眼看出哪些桶及格
    ax.axvline(x=50, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
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


def plot_sentiment_by_source(df: pd.DataFrame) -> plt.Figure:
    """
    各來源每日平均情緒折線圖（同一張圖多條線）。
    df 需包含欄位：Date、Article_Sentiment_Score、Source
    """
    fig, ax = plt.subplots()

    # 來源配色：從 config.SOURCE_COLORS 衍生，新增來源不需改這裡
    from config import SOURCE_COLORS
    _COLORS = SOURCE_COLORS

    for source_name, group in df.groupby('Source'):
        daily = group.groupby('Date')['Article_Sentiment_Score'].mean()
        color = _COLORS.get(source_name, None)
        ax.plot(daily.index, daily.values, label=source_name, color=color, alpha=0.8)

    ax.legend(loc='upper left', fontsize=10)
    ax.set_xlabel('Date')
    ax.set_ylabel('Average Sentiment Score')
    ax.set_title('Sentiment Trend by Source')
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
