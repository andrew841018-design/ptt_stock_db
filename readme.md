# PTT Stock Sentiment Analysis

## 專案簡介

爬取 PTT 股票板文章與推文，建立資料庫進行情緒分析，並提供 REST API 與視覺化儀表板。

## 技術棧

- Python (requests, BeautifulSoup, Pandas, jieba)
- SQLite
- FastAPI
- Streamlit
- pytest

## 專案架構

**資料流向：**

1. `pipeline.py` 執行主流程
   - `web_scraping.py` 爬取 PTT 文章與推文 → 寫入 SQLite
   - `analysis.py` 清洗資料、計算情緒分數 → 更新 SQLite
   - `sentiment.py` 提供 jieba 情緒分析函式（被 analysis.py 呼叫）

2. `api.py` 從 SQLite 讀取資料，提供 REST API
   - `test_api.py` 對 API 進行自動化測試

3. `visualization.py` 從 SQLite 讀取資料，提供 Streamlit 儀表板

4. `QA.py` 檢查 SQLite 資料品質

## 專案結構

```
├── Create_DB.py              # 建立資料庫
├── pipeline.py               # 主流程，包含：
│   ├── web_scraping.py       # 爬蟲
│   ├── analysis.py           # 資料清洗 + 情緒分數計算
│   ├── sentiment.py          # jieba 情緒分析
│   ├── ptt_sentiment_dict.py # PTT 自訂情緒字典
│   └── data_cleanner.py      # 資料清洗封裝
├── visualization.py          # Streamlit 儀表板
├── plt_function.py           # matplotlib 圖表函式
├── api.py                    # FastAPI REST API
├── QA.py                     # 資料品質檢查
├── test_api.py               # pytest API 測試
└── ptt_stock.db              # SQLite 資料庫（不進 git）
```

## 資料庫 Schema

**ptt_stock_article_info**：文章主表

- Article_id, Title, Push_count, Author, Url, Date, Content, Scraped_time, Published_Time, Article_Sentiment_Score

**ptt_stock_comment_info**：推文表

- Comment_id, Article_id, User_id, Push_tag, Message, Comment_Sentiment_Score

## API Endpoints

- GET /sentiments/today — 今日平均情緒分數
- GET /sentiments/change — 今昨情緒變化量
- GET /sentiments/recent — 近N天情緒分數（預設10天，最多30天）
- GET /articles/top_push — 熱門文章排行（可指定筆數、期間）
- GET /articles/search — 關鍵字搜尋文章
- GET /health — 資料庫健康檢查

## 執行方式

```bash
# 建立資料庫
python3 Create_DB.py

# 執行爬蟲 + 資料清洗 + 情緒分析
python3 pipeline.py

# 啟動視覺化儀表板
streamlit run visualization.py

# 啟動 API
uvicorn api:app --reload

# 執行測試
python3 -m pytest test_api.py -v
```

## 未來規劃

- Phase 4：AWS 部署
- Phase 5：PostgreSQL、資料倉儲（星型 schema）
- Phase 6：Airflow、BERT、CI/CD
