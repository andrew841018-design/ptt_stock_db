import pandas as pd
from sentiment import calculate_sentiment
from tqdm import tqdm
from pg_helper import get_pg
from config import SENTIMENT_SCORES_TABLE, ARTICLES_TABLE, COMMENTS_TABLE


def clean_article_info():
    """計算文章情緒分數並寫入 sentiment_scores 表"""
    tqdm.pandas()
    # 讀取文章（關閉連線後再計算，避免 connection hold）
    with get_pg() as conn:
        df = pd.read_sql_query(f"SELECT article_id, title, content FROM {ARTICLES_TABLE}", conn)

    # calculate sentiment score（title 權重 x2，content 權重 x1）
    df['score'] = df.progress_apply(lambda row: calculate_sentiment((row['title'] or '') * 2 + (row['content'] or '')), axis=1)

    # 寫入 sentiment_scores（遇到衝突，直接overwrite新的資料）
    records = df[['article_id', 'score']].values.tolist()
    with get_pg() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(f"""
                INSERT INTO {SENTIMENT_SCORES_TABLE} (target_type, target_id, method, score)
                VALUES ('article', %s, 'jieba', %s)
                ON CONFLICT (target_type, target_id, method) DO UPDATE SET score = EXCLUDED.score
            """, records)


def clean_comment_info():
    """計算留言情緒分數並寫入 sentiment_scores 表"""
    tqdm.pandas()
    # 讀取留言（關閉連線後再計算，避免 connection hold）
    with get_pg() as conn:
        df = pd.read_sql_query(f"SELECT comment_id, message FROM {COMMENTS_TABLE}", conn)

    # calculate sentiment score
    df['score'] = df['message'].progress_apply(
        lambda msg: calculate_sentiment(msg or '')
    )

    # 寫入 sentiment_scores（遇到衝突，直接overwrite新的資料）
    records = df[['comment_id', 'score']].values.tolist()
    with get_pg() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(f"""
                INSERT INTO {SENTIMENT_SCORES_TABLE} (target_type, target_id, method, score)
                VALUES ('comment', %s, 'jieba', %s)
                ON CONFLICT (target_type, target_id, method) DO UPDATE SET score = EXCLUDED.score
            """, records)
