"""
文章情緒標注工具（Streamlit）

用途：人工標注文章情緒，供 BERT fine-tuning 使用
標注規則：
  positive（正面）— 看好後市、利多消息、樂觀情緒
  neutral （中性）— 無明確立場、純資訊、觀望態度
  negative（負面）— 看壞後市、利空消息、悲觀情緒

執行方式：
  cd dependent_code
  streamlit run labeling_tool.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from typing import Optional
import streamlit as st
from pg_helper import get_pg
from config import ARTICLES_TABLE, SOURCES, ARTICLE_LABELS_TABLE

# ── 常數 ──────────────────────────────────────────────────────────────────────

TARGET_COUNT   = 500
LABELS         = ["positive", "neutral", "negative"]
LABEL_DISPLAY  = {"positive": "✅ 正面", "neutral": "⚪ 中性", "negative": "❌ 負面"}
LABEL_COLORS   = {"positive": "green",   "neutral": "gray",   "negative": "red"}

# 中文來源（對比 0050）、英文來源（對比 VOO）
ZH_SOURCES = [SOURCES["ptt"]["name"], SOURCES["cnyes"]["name"]]
EN_SOURCES = [SOURCES["reddit"]["name"]]

# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_progress() -> dict:
    """回傳各 label 數量與總數"""
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT label, COUNT(*) FROM {ARTICLE_LABELS_TABLE} GROUP BY label")
            counts = {label: count for label, count in cur.fetchall()}
    return {label: counts.get(label, 0) for label in LABELS}


def _load_next_article(lang: str) -> Optional[dict]:
    """抓一篇尚未標注的文章（依語言過濾）"""
    source_names = ZH_SOURCES if lang == "zh" else EN_SOURCES
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.article_id, a.title, a.content, a.published_at, s.source_name
                FROM {ARTICLES_TABLE} a
                JOIN sources s ON s.source_id = a.source_id
                WHERE s.source_name = ANY(%s)
                  AND a.article_id NOT IN (SELECT article_id FROM {ARTICLE_LABELS_TABLE})
                  AND a.title != ''
                ORDER BY RANDOM()
                LIMIT 1
            """, (source_names,))
            row = cur.fetchone()
    if not row:
        return None
    article_id, title, content, published_at, source_name = row
    return {
        "article_id":  article_id,
        "title":       title,
        "content":     content or "",
        "published_at": published_at,
        "source_name": source_name,
    }


def _save_label(article_id: int, label: str) -> None:
    """儲存標注結果到 DB"""
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {ARTICLE_LABELS_TABLE} (article_id, label)
                VALUES (%s, %s)
                ON CONFLICT (article_id) DO UPDATE SET label = EXCLUDED.label, labeled_at = NOW()
            """, (article_id, label))


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="情緒標注工具", layout="wide")
st.title("📝 文章情緒標注工具")

# 語言切換
lang = st.sidebar.radio("標注語言", ["zh", "en"],
                         format_func=lambda x: "🇹🇼 中文（PTT + 鉅亨）" if x == "zh" else "🇺🇸 英文（Reddit）")
compare_stock = "0050（元大台灣50）" if lang == "zh" else "VOO（Vanguard S&P 500）"
st.sidebar.markdown(f"**對比標的**：{compare_stock}")

# 進度
progress = _load_progress()
total_labeled = sum(progress.values())
st.sidebar.markdown("---")
st.sidebar.markdown("### 標注進度")
st.sidebar.progress(min(total_labeled / TARGET_COUNT, 1.0))
st.sidebar.markdown(f"**{total_labeled} / {TARGET_COUNT}** 筆")
for label in LABELS:
    st.sidebar.markdown(f"{LABEL_DISPLAY[label]}：{progress[label]} 筆")

if total_labeled >= TARGET_COUNT:
    st.success(f"🎉 已達 {TARGET_COUNT} 筆目標！可以開始 fine-tuning 了。")

st.sidebar.markdown("---")
st.sidebar.markdown("### 標注規則")
st.sidebar.markdown("""
- ✅ **正面**：看好後市、利多、樂觀
- ⚪ **中性**：無立場、純資訊、觀望
- ❌ **負面**：看壞後市、利空、悲觀
""")

# 載入文章（session state 避免重複載入）
if "article" not in st.session_state or st.session_state.get("lang") != lang:
    st.session_state.article = _load_next_article(lang)
    st.session_state.lang = lang

article = st.session_state.article

if article is None:
    st.info(f"{'中文' if lang == 'zh' else '英文'}文章已全部標注完畢！")
    st.stop()

# 文章顯示
st.markdown(f"**來源**：{article['source_name']}　**發布時間**：{article['published_at'].date() if article['published_at'] else '—'}")
st.markdown(f"## {article['title']}")

content_preview = article["content"][:800] + "..." if len(article["content"]) > 800 else article["content"]
if content_preview:
    st.markdown(content_preview)
else:
    st.caption("（無內文）")

st.markdown("---")

# 標注按鈕
col1, col2, col3 = st.columns(3)

def _on_label(label: str):
    _save_label(article["article_id"], label)
    st.session_state.article = _load_next_article(lang)

with col1:
    if st.button("✅ 正面", use_container_width=True):
        _on_label("positive")
        st.rerun()
with col2:
    if st.button("⚪ 中性", use_container_width=True):
        _on_label("neutral")
        st.rerun()
with col3:
    if st.button("❌ 負面", use_container_width=True):
        _on_label("negative")
        st.rerun()
