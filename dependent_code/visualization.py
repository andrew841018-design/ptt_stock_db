import streamlit as st
import pandas as pd
import datetime
from typing import Optional
from pg_helper import get_pg
from plt_function import plot_sentiment_trend, plot_push_count_distribution, plot_daily_article_count, plot_sentiment_vs_stock, plot_sentiment_and_price_trend
from config import ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, STOCK_PRICES_TABLE

TWSE_STOCK_NAME = "元大台灣50"  # 圖表標題用


@st.cache_data
def load_data():
    # JOIN articles + sentiment_scores，用 alias 對齊原本欄位名稱。
    # INNER JOIN 天然過濾成「有情緒分數」的文章（~171k 筆 / ~170 MB），
    # 在 t3.small 2 GB RAM + 2 GB swap 上可負擔。Streamlit 會透過
    # @st.cache_data 快取整個 DataFrame，後續 request 直接 hit cache。
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
# Streamlit date_input 預設把可選範圍限制在 default ± 10 年，
# 會讓使用者選不到 2018 之後（因為 start default = 2008）。
# 明確傳 min_value / max_value 涵蓋整個資料範圍。
_min_date = df['Date'].min()
_max_date = df['Date'].max()
start_date = st.sidebar.date_input("Start Date", _min_date, min_value=_min_date, max_value=_max_date)
end_date   = st.sidebar.date_input("End Date",   _max_date, min_value=_min_date, max_value=_max_date)
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
change_score = round(score - yesterday['Article_Sentiment_Score'].mean(), 2) if not yesterday.empty else 0
st.metric(label="Today's Sentiment Score", value=score, delta=change_score)

st.subheader("Today's Top 10 Trending Articles")  # 顯示今日前10名熱門文章
st.dataframe(df.nlargest(10, 'Push_count')[['Title', 'Push_count', 'Article_Sentiment_Score', 'Date']])

# 關鍵字統計 TOP20（TF-IDF 版）
#
# 為什麼不用 KeyBERT：
# - t3.small 只有 1.9 GB RAM，Streamlit 起來已吃 1.2 GB（watcher 掃 transformers
#   module tree），再載 BERT (~500 MB) 會直接 swap 地獄或被 OOM killer 殺掉。
# - TF-IDF 對「標題短文」的關鍵字抽取效果跟 BERT 差距很小（標題本來就
#   高度濃縮），但記憶體用 ~30 MB、毫秒內完成。
# - sklearn 已經是 requirements 的 transitive dep，零新依賴。
_KEYWORD_MAX_DOCS = 200

def _extract_keywords_tfidf(titles: list[str], top_n: int = 20) -> pd.DataFrame:
    """用 TF-IDF 從標題抽關鍵字（1-2 gram）。回傳 Word/Score DataFrame。"""
    from sklearn.feature_extraction.text import TfidfVectorizer
    # token_pattern 改為「至少 2 個非空白字元」以支援中文單字
    vec = TfidfVectorizer(
        ngram_range=(1, 2),
        token_pattern=r"(?u)\b\w{2,}\b",
        max_features=2000,
    )
    matrix = vec.fit_transform(titles)
    # 全部文件的 TF-IDF 加總 = 該詞在語料中的總重要度
    scores = matrix.sum(axis=0).A1
    vocab  = vec.get_feature_names_out()
    top_idx = scores.argsort()[::-1][:top_n]
    return pd.DataFrame({'Word': vocab[top_idx], 'Score': scores[top_idx].round(3)})

st.subheader("Top 20 Keywords")
if df.empty:
    st.warning("No data available for keyword analysis")
elif st.button(f"載入關鍵字分析（取 top {_KEYWORD_MAX_DOCS} 熱門文章）"):
    with st.spinner("計算中..."):
        sample = df.nlargest(_KEYWORD_MAX_DOCS, 'Push_count') if len(df) > _KEYWORD_MAX_DOCS else df
        top_20_words = _extract_keywords_tfidf(sample['Title'].tolist(), top_n=20)
    st.dataframe(top_20_words)

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


# ─── AI 模型預測結果（Walk-Forward）──────────────────────────────────────────
st.subheader("AI 模型預測結果 (Walk-Forward)")


@st.cache_data(ttl=3600)   # 每小時 refresh，重跑預測
def load_ai_model_prediction(market: str) -> Optional[pd.DataFrame]:
    """
    直接呼叫 run_ai_model_prediction()，取得 enriched DataFrame。
    不經過 CSV/檔案系統 — 計算結果只存在 Streamlit cache，每小時重算。
    """
    from ai_model_prediction import run_ai_model_prediction
    return run_ai_model_prediction(market)


_MARKETS = [("tw", "0050 元大台灣50"), ("us", "VOO Vanguard S&P 500 ETF")]

for market_code, market_name in _MARKETS:
    st.markdown(f"#### {market_name}")
    df_pred = load_ai_model_prediction(market_code)

    if df_pred is None or df_pred.empty:
        st.info(f"{market_name}：無預測結果（情緒/股價/訓練資料不足，或 BERT 推論尚未完成）")
        continue

    accuracy           = (df_pred["true"] == df_pred["pred"]).mean()
    final_strategy     = df_pred["strategy_cumulative_return"].iloc[-1]
    final_buy_and_hold = df_pred["buy_and_hold_return"].iloc[-1]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Accuracy",       f"{accuracy * 100:.2f}%")
    col2.metric("策略累積報酬",   f"{(final_strategy - 1) * 100:.2f}%")
    col3.metric("Buy & Hold",     f"{(final_buy_and_hold - 1) * 100:.2f}%")

    # 累積報酬曲線（Streamlit 原生 line_chart，互動式，不依賴 matplotlib）
    chart_df = df_pred.set_index("date")[["strategy_cumulative_return", "buy_and_hold_return"]]
    chart_df.columns = ["Sentiment Strategy", "Buy-and-Hold"]
    st.line_chart(chart_df)
