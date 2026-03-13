import sqlite3

def create_table():
    conn=sqlite3.connect("ptt_stock.db")
    cursor=conn.cursor()
    ## 清空資料表
    cursor.execute("DROP TABLE IF EXISTS ptt_stock_article_info")
    cursor.execute("DROP TABLE IF EXISTS ptt_stock_comment_info")
    ## 建立資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ptt_stock_article_info (
        Article_id INTEGER PRIMARY KEY AUTOINCREMENT,
        Title TEXT,
        Push_count TEXT,
        Author TEXT,
        Url TEXT UNIQUE,
        Date TEXT,
        Content TEXT,
        Scraped_time TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ptt_stock_comment_info (
        Comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        Article_id INTEGER,
        User_id TEXT,
        Push_tag TEXT,
        Message TEXT,
        FOREIGN KEY (Article_id) REFERENCES ptt_stock_article_info(Article_id)
    )
    """)
    cursor.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
create_table()