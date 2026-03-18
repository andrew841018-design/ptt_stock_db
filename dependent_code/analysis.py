import pandas as pd
from sentiment import calculate_sentiment
from data_cleanner import clean_all
from tqdm import tqdm
from config import TABLE_ARTICLE, TABLE_COMMENT
from db_helper import get_db
def clean_article_info():
    tqdm.pandas()
    with get_db() as conn:
        df=pd.read_sql_query(f"SELECT * FROM {TABLE_ARTICLE}",conn)

    df=clean_all(df,TABLE_ARTICLE)
    #calculate sentiment score
    df['Article_Sentiment_Score']=df.progress_apply(lambda row:calculate_sentiment(row['Title']*2+row['Content']*1),axis=1)
    record_list=df[['Published_Time','Push_count','Article_Sentiment_Score','Article_id']].values.tolist()
    with get_db() as conn:
        conn.cursor().executemany(f"UPDATE {TABLE_ARTICLE} SET Published_Time=?, Push_count=?, Article_Sentiment_Score=? WHERE Article_id=?",record_list)
def clean_comment_info():
    tqdm.pandas()
    with get_db() as conn:
        df=pd.read_sql_query(f"SELECT * FROM {TABLE_COMMENT}",conn)
    df=clean_all(df,TABLE_COMMENT)
    #calculate sentiment score
    df['Comment_Sentiment_Score']=df['Message'].progress_apply(calculate_sentiment)
    record_list=df[['Comment_Sentiment_Score','Comment_id']].values.tolist()
    with get_db() as conn:
        conn.cursor().executemany(f"UPDATE {TABLE_COMMENT} SET Comment_Sentiment_Score=? WHERE Comment_id=?",record_list)