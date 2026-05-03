import streamlit as st
import pandas as pd
import datetime
from keybert import KeyBERT
from pg_helper import get_pg
from plt_function import plot_sentiment_trend, plot_push_count_distribution, plot_daily_article_count, plot_sentiment_vs_stock, plot_sentiment_and_price_trend
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, TWSE_STOCK_NAME, STOCK_PRICES_TABLE


@st.cache_data
def load_data():
    # JOIN articles + sentiment_scores，用 alias 對齊原本欄位名稱
    with get_pg() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                a.title          AS "Title",
                a.push_count     AS "Push_count",
                a.published_at   AS "Date",
                a.url            AS "Url",
                s.score          AS "Article_Sentiment_Score"
            FROM {ARTICLES_TABLE} a
            JOIN {SENTIMENT_SCORES_TABLE} s
                ON s.article_id = a.article_id
        """, conn)
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    return df


st.set_page_config(page_title="Ptt Stock Sentiment Analysis", page_icon=":chart_with_upwards_trend:", layout="wide")
st.title("Ptt Stock Sentiment Analysis")
df = load_data()
st.write(f"資料期間:{df['Date'].min()} ~ {df['Date'].max()}")

# 日期篩選
st.sidebar.subheader("Date Selection")
start_date = st.sidebar.date_input("Start Date", df['Date'].min())  # default is the earliest date
end_date   = st.sidebar.date_input("End Date",   df['Date'].max())  # default is the latest date
mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)        # record all the dates in the selected date range
if mask.sum() == 0:
    st.warning("No data available for the selected date range")
    st.stop()  # stop the app
else:
    df = df[mask]  # filter the data by the selected date range

fig_sentiment_trend = plot_sentiment_trend(df)
st.subheader("Sentiment Trend")
st.pyplot(fig_sentiment_trend)

fig_push_count_distribution = plot_push_count_distribution(df)
st.subheader("Push Count Distribution")
st.pyplot(fig_push_count_distribution)

st.subheader("Daily Article Count")
fig_daily_article_count = plot_daily_article_count(df)
st.pyplot(fig_daily_article_count)

# show today's sentiment score
today     = df[df['Date'] == df['Date'].max()]
score     = round(today['Article_Sentiment_Score'].mean(), 2)
yesterday = df[df['Date'] == df['Date'].max() - datetime.timedelta(days=1)]
change_score = round(score - yesterday['Article_Sentiment_Score'].mean(), 2)
st.metric(label="Today's Sentiment Score", value=score, delta=change_score)

st.subheader("Today's Top 10 Trending Articles")  # 顯示今日前10名熱門文章
st.dataframe(df.nlargest(10, 'Push_count')[['Title', 'Push_count', 'Article_Sentiment_Score', 'Date']])

@st.cache_resource
def _kw_model():
    return KeyBERT()

# 關鍵字統計 TOP20（KeyBERT）
text         = ' '.join(df['Title'].tolist())
keywords     = _kw_model().extract_keywords(text, keyphrase_ngram_range=(1, 2), top_n=20)
top_20_words = pd.DataFrame(keywords, columns=['Word', 'Score'])
st.subheader("Top 20 Keywords")
st.dataframe(top_20_words)

# ── 情緒 vs 股價關聯分析 ──────────────────────────────────────────────────
st.subheader("情緒 vs 股價關聯分析")

@st.cache_data
def load_correlation_data():
    with get_pg() as conn:
        return pd.read_sql_query(f"""
            SELECT
                sub.sentiment_date,
                sub.avg_sentiment,
                sp.change              AS next_day_change
            FROM (
                SELECT
                    DATE(a.published_at) AS sentiment_date,
                    AVG(s.score)         AS avg_sentiment
                FROM {ARTICLES_TABLE} a
                JOIN {SENTIMENT_SCORES_TABLE} s ON s.article_id = a.article_id
                GROUP BY DATE(a.published_at)
            ) sub
            JOIN {STOCK_PRICES_TABLE} sp
                -- 觀察情緒分數的下一個交易日股價變化，比對市場情緒與價格變化是否存在關聯
                ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
            ORDER BY sub.sentiment_date
        """, conn)

corr_df = load_correlation_data()

if corr_df.empty:
    st.warning("目前尚無情緒分數資料，待 BERT 模型上線後顯示。")
else:
    st.pyplot(plot_sentiment_vs_stock(corr_df, TWSE_STOCK_NAME))
    st.pyplot(plot_sentiment_and_price_trend(corr_df, TWSE_STOCK_NAME))
