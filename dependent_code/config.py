import os

# 資料庫路徑（絕對路徑，避免工作目錄不同造成找不到檔案）
DB_PATH = os.path.join(os.path.dirname(__file__), 'ptt_stock.db')

# 爬蟲設定
MAX_RETRY = 5
SLEEP_INTERVAL = 0.5

# 爬蟲過濾關鍵字（這類文章不爬）
SKIP_KEYWORDS = ["公告", "盤後閒聊", "盤中閒聊", "情報"]

# 資料庫資料表名稱
TABLE_ARTICLE = "ptt_stock_article_info"
TABLE_COMMENT = "ptt_stock_comment_info"
