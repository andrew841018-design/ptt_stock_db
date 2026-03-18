from config import TABLE_ARTICLE, TABLE_COMMENT
from db_helper import get_db

def create_table():
    with get_db() as conn:
        cursor=conn.cursor()
        ## 清空資料表
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE_ARTICLE}")
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE_COMMENT}")
        ## 建立資料表
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_ARTICLE} (
            Article_id INTEGER PRIMARY KEY AUTOINCREMENT,
            Title TEXT,
            Push_count TEXT,
            Author TEXT,
            Url TEXT UNIQUE,
            Date TEXT,
            Content TEXT,
            Scraped_time TEXT,
            Article_Sentiment_Score REAL,
            Published_Time TEXT
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_COMMENT} (
            Comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            Article_id INTEGER,
            User_id TEXT,
            Push_tag TEXT,
            Message TEXT,
            Comment_Sentiment_Score REAL,
            FOREIGN KEY (Article_id) REFERENCES {TABLE_ARTICLE}(Article_id)
        )
        """)
        cursor.execute("PRAGMA foreign_keys = ON")
if __name__=="__main__":
    create_table()