
import json
import logging
import os
import sys
import time

from google import genai

sys.path.insert(0, os.path.dirname(__file__))
from config import ARTICLES_TABLE, ARTICLE_LABELS_TABLE
from pg_helper import get_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


GEMINI_MODEL = "gemini-2.5-flash"

BATCH_DELAY_SECONDS = 1.0

MAX_TEXT_LENGTH = 800



def get_unlabeled_articles(limit: int = 50) -> list[dict]:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.article_id,
                       a.title || ' ' || COALESCE(a.content, '') AS text
                FROM {ARTICLES_TABLE} a
                LEFT JOIN {ARTICLE_LABELS_TABLE} al ON al.article_id = a.article_id
                WHERE al.article_id IS NULL
                ORDER BY a.article_id
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    articles = []
    for article_id, text in rows:
        truncated = text[:MAX_TEXT_LENGTH] if text else ""
        articles.append({"article_id": article_id, "text": truncated})

    logging.info("[LLM] 取得 %d 篇未標注文章", len(articles))
    return articles



def classify_with_llm(texts: list[str]) -> list[dict]:
    if not texts:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logging.error("[LLM] GEMINI_API_KEY 未設，請在 .env 加入 GEMINI_API_KEY=...")
        return []

    client = genai.Client(api_key=api_key)

    numbered_texts = "\n".join(f"[{idx}] {text}" for idx, text in enumerate(texts))

    prompt = f"""請判斷以下文章的情緒（positive/neutral/negative），回傳 JSON array。

每筆格式：
{{"text_index": <int>, "sentiment": "<positive|neutral|negative>", "confidence": <0.0~1.0>}}

注意：
- 只回傳 JSON array，不要加任何說明文字
- sentiment 只能是 positive、neutral、negative 三者之一
- confidence 是你對判斷的信心程度

文章列表：
{numbered_texts}"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        response_text = response.text.strip()

        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        labels = json.loads(response_text)

        valid_sentiments = {"positive", "neutral", "negative"}
        validated = []
        for item in labels:
            sentiment = item.get("sentiment", "").lower()
            if sentiment not in valid_sentiments:
                logging.warning("[LLM] 無效的 sentiment 值：%s（跳過）", sentiment)
                continue
            validated.append({
                "text_index": item.get("text_index"),
                "sentiment":  sentiment,
                "confidence": float(item.get("confidence", 0.0)),
            })

        logging.info("[LLM] API 回傳 %d 筆標注結果（有效 %d 筆）", len(labels), len(validated))
        return validated

    except Exception as exc:
        logging.error("[LLM] Gemini API 呼叫失敗：%s", exc)
        return []



def save_labels(article_ids: list[int], labels: list[dict]) -> int:
    saved = 0

    with get_pg() as conn:
        with conn.cursor() as cur:
            for label in labels:
                raw_index = label.get("text_index")
                sentiment = label.get("sentiment")

                try:
                    text_index = int(raw_index) if raw_index is not None else None
                except (TypeError, ValueError):
                    logging.warning("[LLM] text_index %r 不是整數，跳過", raw_index)
                    continue

                if text_index is None or text_index < 0 or text_index >= len(article_ids):
                    logging.warning("[LLM] text_index %s 超出範圍（共 %d 篇），跳過", text_index, len(article_ids))
                    continue

                article_id = article_ids[text_index]

                cur.execute("SAVEPOINT row_save")
                try:
                    cur.execute(f"""
                        INSERT INTO {ARTICLE_LABELS_TABLE} (article_id, label)
                        VALUES (%s, %s)
                        ON CONFLICT (article_id) DO UPDATE
                            SET label = EXCLUDED.label,
                                labeled_at = NOW()
                    """, (article_id, sentiment))
                    cur.execute("RELEASE SAVEPOINT row_save")
                    saved += 1
                except Exception as exc:
                    logging.error("[LLM] 寫入 article_id=%d 失敗：%s", article_id, exc)
                    cur.execute("ROLLBACK TO SAVEPOINT row_save")

    logging.info("[LLM] 成功寫入 %d 筆標注", saved)
    return saved



def run_llm_labeling(batch_size: int = 50, max_batches: int = 10) -> dict:
    total_processed = 0
    total_saved = 0

    logging.info("[LLM] " + "=" * 60)
    logging.info("[LLM] 開始 LLM 輔助標注（batch_size=%d, max_batches=%d）", batch_size, max_batches)
    logging.info("[LLM] " + "=" * 60)

    for batch_num in range(1, max_batches + 1):
        logging.info("[LLM] --- 批次 %d / %d ---", batch_num, max_batches)

        articles = get_unlabeled_articles(limit=batch_size)
        if not articles:
            logging.info("[LLM] 沒有更多未標注文章，結束")
            break

        texts       = [article["text"] for article in articles]
        article_ids = [article["article_id"] for article in articles]

        labels = classify_with_llm(texts)
        if not labels:
            logging.warning("[LLM] 批次 %d API 回傳空結果，跳過", batch_num)
            continue

        saved = save_labels(article_ids, labels)

        total_processed += len(articles)
        total_saved     += saved

        logging.info(
            "[LLM] 批次 %d 完成：處理 %d 篇，儲存 %d 筆（累計：%d / %d）",
            batch_num, len(articles), saved, total_saved, total_processed,
        )

        if batch_num < max_batches:
            logging.info("[LLM] 等待 %.1f 秒...", BATCH_DELAY_SECONDS)
            time.sleep(BATCH_DELAY_SECONDS)

    logging.info("[LLM] " + "=" * 60)
    logging.info("[LLM] 標注完成：共處理 %d 篇，成功儲存 %d 筆", total_processed, total_saved)
    logging.info("[LLM] " + "=" * 60)

    return {"total_processed": total_processed, "total_saved": total_saved}
