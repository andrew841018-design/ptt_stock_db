import sqlite3
import pandas as pd
conn = sqlite3.connect("ptt_stock.db")
cursor = conn.cursor()

# 檢查重複 URL
cursor.execute("SELECT url, COUNT(*) FROM ptt_stock_article_info GROUP BY url HAVING COUNT(*) > 1")
duplicate_url = cursor.fetchall()
if duplicate_url:
    print(f"有重複：{duplicate_url}")
else:
    print("無重複URL")

# 檢查孤兒推文（FK 沒對應到文章）
cursor.execute("SELECT COUNT(*) FROM ptt_stock_comment_info WHERE article_id NOT IN (SELECT article_id FROM ptt_stock_article_info)")
print(f"孤兒推文：{cursor.fetchone()[0]}")

# 抽查 FK 關聯
cursor.execute("SELECT a.title, COUNT(c.comment_id) FROM ptt_stock_article_info a LEFT JOIN ptt_stock_comment_info c ON a.article_id = c.article_id GROUP BY a.article_id LIMIT 5")
print("－－－－－－－－－－－－－－以下推文數如果全部都是0,表示沒關聯到，有問題－－－－－－－－－－－－－－－－")
for row in cursor.fetchall():
    print(f"{row[0]} | 推文數：{row[1]}")

conn.close()