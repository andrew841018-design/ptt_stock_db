import streamlit as st
import pandas as pd
import jieba
from collections import Counter
import datetime
from pg_helper import get_pg
from plt_function import plot_sentiment_trend, plot_push_count_distribution, plot_daily_article_count
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE


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
                ON  s.target_id   = a.article_id
                AND s.target_type = 'article'
                AND s.method      = 'jieba'
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

# 關鍵字統計 TOP20
text  = ' '.join(df['Title'].tolist())  # combine all the titles into a single string
words = jieba.lcut(text)
stopwords = set([
    '什麼', '宣布', '這個', '那個', '因為', '所以', '但是', '如果',
    '已經', '可以', '沒有', '表示', '認為', '今天', '明天', '昨天',
    '的', '了', '在', '是', '我', '他', '她', '它', '們',
    '這', '那', '也', '都', '不', '就', '與', '及', '或',
    '請問', '有沒有', '大家', '一下', '一個', '如何', '怎麼', 'Re', '請益', '心得', '快訊',
    '投資', 'ETF', '是不是', '營收', '今年'
])
counter      = Counter(w for w in words if len(w) > 1 and w not in stopwords and not w.isnumeric())  # count the frequency of each word into dictionary
top_20_words = pd.DataFrame(counter.most_common(20), columns=['Word', 'Frequency'])
st.subheader("Top 20 Keywords")
st.dataframe(top_20_words)
