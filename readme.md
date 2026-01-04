# PTT Stock Sentiment Analysis

## 專案簡介

爬取 PTT 股票板文章與推文，建立資料庫進行情緒分析。

## 技術棧

- Python (requests, BeautifulSoup)
- SQLite
- (後續：Pandas, Streamlit, FastAPI)

## 專案結構

├── create_database.py # 建立資料庫
├── web_scraping.py # 爬蟲
├── QA.py # 針對database做一點簡單的測試
└── ptt_stock.db # SQLite 資料庫

## 資料庫 Schema

- ptt_stock_article_info：文章主表
- ptt_stock_comment_info：推文表

## 未來規劃

- Phase 2：情緒分析 + 儀表板
- Phase 3：API + 部署
- Phase 4-6：PostgreSQL、BERT、Airflow
