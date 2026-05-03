import streamlit as st
import pandas as pd
import datetime
from typing import Optional
from pg_helper import get_pg
from plt_function import (
    plot_sentiment_trend, plot_push_count_distribution,
    plot_daily_article_count, plot_sentiment_vs_stock,
    plot_sentiment_and_price_trend, plot_sentiment_by_source,
)
from config import (
    ARTICLES_TABLE, SENTIMENT_SCORES_TABLE, SOURCES_TABLE,
    STOCK_PRICES_TABLE, US_STOCK_PRICES_TABLE,
    sources_by_market,
)

TW_STOCK_NAME = "0050 元大台灣50"
US_STOCK_NAME = "VOO Vanguard S&P 500 ETF"


@st.cache_data
def load_data():
    # JOIN articles + sentiment_scores + sources，取 source_name 供來源篩選
    # INNER JOIN 天然過濾成「有情緒分數」的文章
    with get_pg() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                a.title          AS "Title",
                a.push_count     AS "Push_count",
                a.published_at   AS "Date",
                a.url            AS "Url",
                s.score          AS "Article_Sentiment_Score",
                src.source_name  AS "Source"
            FROM {ARTICLES_TABLE} a
            JOIN {SENTIMENT_SCORES_TABLE} s
                ON s.article_id = a.article_id
            JOIN {SOURCES_TABLE} src
                ON src.source_id = a.source_id
        """, conn)
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    return df


st.set_page_config(
    page_title="Stock Sentiment Analysis",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)
st.title("Stock Sentiment Analysis Dashboard")
df = load_data()
st.write(f"資料期間: {df['Date'].min()} ~ {df['Date'].max()}　｜　共 {len(df):,} 篇文章")

# ─── 側邊欄篩選 ─────────────────────────────────────────────────────────────
st.sidebar.subheader("Date Selection")
_min_date = df['Date'].min()
_max_date = df['Date'].max()
start_date = st.sidebar.date_input("Start Date", _min_date, min_value=_min_date, max_value=_max_date)
end_date   = st.sidebar.date_input("End Date",   _max_date, min_value=_min_date, max_value=_max_date)

# 來源篩選（多選）
all_sources = sorted(df['Source'].unique().tolist())
st.sidebar.subheader("Source Filter")
selected_sources = st.sidebar.multiselect("選擇來源", all_sources, default=all_sources)

mask = (
    (df['Date'] >= start_date) &
    (df['Date'] <= end_date) &
    (df['Source'].isin(selected_sources))
)
if mask.sum() == 0:
    st.warning("No data available for the selected filters")
    st.stop()
else:
    df = df[mask]

# ─── 今日情緒指標 ─────────────────────────────────────────────────────────────
today     = df[df['Date'] == df['Date'].max()]
score     = round(today['Article_Sentiment_Score'].mean(), 2)
yesterday = df[df['Date'] == df['Date'].max() - datetime.timedelta(days=1)]
change_score = round(score - yesterday['Article_Sentiment_Score'].mean(), 2) if not yesterday.empty else 0
st.metric(label="Today's Sentiment Score", value=score, delta=change_score)

# ─── Sentiment Trend（全來源合併）─────────────────────────────────────────────
st.subheader("Sentiment Trend")
st.pyplot(plot_sentiment_trend(df))

# ─── Sentiment by Source（各來源分開畫線）──────────────────────────────────────
if len(df['Source'].unique()) > 1:
    st.subheader("Sentiment by Source")
    st.pyplot(plot_sentiment_by_source(df))

# ─── Daily Article Count ─────────────────────────────────────────────────────
st.subheader("Daily Article Count")
st.pyplot(plot_daily_article_count(df))

# ─── Push Count Distribution ─────────────────────────────────────────────────
st.subheader("Push Count Distribution")
st.pyplot(plot_push_count_distribution(df))

# ─── Top Articles by Engagement ──────────────────────────────────────────────
st.subheader("Top Articles by Engagement")
# 含來源欄位，所有來源的文章都會顯示
top_cols = ['Title', 'Source', 'Push_count', 'Article_Sentiment_Score', 'Date']
st.dataframe(df.nlargest(20, 'Push_count')[top_cols])

# ─── 關鍵字統計 TOP20（TF-IDF 版）───────────────────────────────────────────
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
    vec = TfidfVectorizer(
        ngram_range=(1, 2),
        token_pattern=r"(?u)\b\w{2,}\b",
        max_features=2000,
    )
    matrix = vec.fit_transform(titles)
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


# ─── 情緒 vs 股價關聯分析（TW: PTT+cnyes → 0050）────────────────────────────
st.subheader("TW 情緒 vs 0050 股價關聯分析")

@st.cache_data
def load_tw_correlation():
    tw_sources = sources_by_market("TW")
    placeholders = ",".join(["%s"] * len(tw_sources))
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
                JOIN {SOURCES_TABLE} src ON src.source_id = a.source_id
                WHERE src.source_name IN ({placeholders})
                GROUP BY DATE(a.published_at)
            ) sub
            JOIN {STOCK_PRICES_TABLE} sp
                ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
            ORDER BY sub.sentiment_date
        """, conn, params=tw_sources)

tw_corr = load_tw_correlation()
if tw_corr.empty:
    st.warning("尚無 TW 情緒 + 股價資料")
else:
    st.pyplot(plot_sentiment_vs_stock(tw_corr, TW_STOCK_NAME, market_label="TW"))
    st.pyplot(plot_sentiment_and_price_trend(tw_corr, TW_STOCK_NAME, market_label="TW"))


# ─── 情緒 vs 股價關聯分析（US: Reddit+CNN+WSJ+MarketWatch → VOO）─────────────
st.subheader("US 情緒 vs VOO 股價關聯分析")

@st.cache_data
def load_us_correlation():
    us_sources = sources_by_market("US")
    placeholders = ",".join(["%s"] * len(us_sources))
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
                JOIN {SOURCES_TABLE} src ON src.source_id = a.source_id
                WHERE src.source_name IN ({placeholders})
                GROUP BY DATE(a.published_at)
            ) sub
            JOIN {US_STOCK_PRICES_TABLE} sp
                ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
            ORDER BY sub.sentiment_date
        """, conn, params=us_sources)

us_corr = load_us_correlation()
if us_corr.empty:
    st.warning("尚無 US 情緒 + 股價資料（待 CNN/WSJ/MarketWatch 爬蟲跑完後顯示）")
else:
    st.pyplot(plot_sentiment_vs_stock(us_corr, US_STOCK_NAME, market_label="US"))
    st.pyplot(plot_sentiment_and_price_trend(us_corr, US_STOCK_NAME, market_label="US"))


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


_MARKETS = [("tw", TW_STOCK_NAME), ("us", US_STOCK_NAME)]

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
