# PTT Stock Sentiment Analysis

![CI](https://github.com/andrew841018-design/ptt_stock_db/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

## 🔗 Demo

| 服務             | 網址                            |
| ---------------- | ------------------------------- |
| REST API         | http://13.236.116.213:8000/docs |
| Streamlit 儀表板 | http://13.236.116.213:8501      |

## 專案簡介

爬取 PTT 股票板文章與推文，建立資料庫進行情緒分析，並提供 REST API 與視覺化儀表板。

## 技術棧

- **爬蟲**：Python, requests, BeautifulSoup
- **資料處理**：Pandas, jieba, tqdm
- **資料庫**：SQLite → PostgreSQL（Docker）
- **API**：FastAPI, uvicorn
- **視覺化**：Streamlit, Matplotlib
- **測試**：pytest, Great Expectations
- **CI/CD**：GitHub Actions
- **雲端**：AWS EC2, AWS S3

## 架構圖

```
PTT 股票板
    ↓
web_scraping.py      ← 爬蟲
    ↓
SQLite (ptt_stock.db)
    ↓
analysis.py          ← 清洗 + 情緒分析
    ↓
migrate.py           ← 遷移至 PostgreSQL（Docker）
    ↓
PostgreSQL
├── sources
├── articles
├── comments
└── sentiment_scores
    ↓
┌─────────────────┐
│  api.py         │  ← REST API
│  visualization  │  ← Streamlit 儀表板
└─────────────────┘
```

## 專案結構

```
project/
├── dependent_code/
│   ├── pipeline.py           # 主流程（爬蟲 + 清洗 + 分析）
│   ├── web_scraping.py       # 爬蟲
│   ├── analysis.py           # 資料清洗 + 情緒分數
│   ├── sentiment.py          # jieba 情緒分析（含 PTT 自訂字典）
│   ├── visualization.py      # Streamlit 儀表板
│   ├── plt_function.py       # matplotlib 圖表函式
│   ├── api.py                # FastAPI REST API
│   ├── test_api.py           # pytest 自動測試
│   ├── ge_validation.py      # Great Expectations 資料驗證
│   ├── QA.py                 # 資料品質檢查（pipeline 自動呼叫）
│   ├── config.py             # 集中管理常數
│   ├── pg_helper.py          # PostgreSQL 連線管理（context manager）
│   ├── schema.py             # PostgreSQL 建表 + index
│   ├── backup.py             # S3 備份（pg_dump）
│   ├── requirements.txt      # 套件清單
│   └── user_dict.txt         # jieba 自訂詞典
├── scripts/
│   ├── run_etl.sh            # 自動化 ETL（cron 每日 08:00 執行）
│   └── schema.py             # PostgreSQL Schema 建立腳本（建表 + index）
├── logs/                     # ETL 執行 log（不進 git）
├── backup.py                 # S3 備份
├── README.md
└── ptt_stock.db              # SQLite 資料庫（不進 git）
```

## 資料庫 Schema

### PostgreSQL（正規化，目前使用）

**sources**（資料來源）

| 欄位        | 型別         | 說明                          |
| ----------- | ------------ | ----------------------------- |
| source_id   | SERIAL PK    | 自動遞增                      |
| source_name | VARCHAR(100) | e.g. "PTT Stock"              |
| url         | TEXT UNIQUE  | e.g. "https://ptt.cc/bbs/Stock" |

**articles**（文章，不含情緒分數）

| 欄位        | 型別      | 說明                    |
| ----------- | --------- | ----------------------- |
| article_id  | SERIAL PK | 自動遞增                |
| source_id   | INTEGER FK | 對應 sources            |
| title       | TEXT      | 文章標題                |
| push_count  | INTEGER   | 推噓數                  |
| author      | VARCHAR   | 作者                    |
| url         | TEXT UNIQUE | 文章網址              |
| content     | TEXT      | 內文                    |
| published_at | TIMESTAMP | 發文時間               |
| scraped_at  | TIMESTAMP | 爬取時間                |

**comments**（留言，不含情緒分數）

| 欄位       | 型別       | 說明     |
| ---------- | ---------- | -------- |
| comment_id | INTEGER PK | 自動遞增 |
| article_id | INTEGER FK | 對應文章 |
| user_id    | VARCHAR    | 推文者   |
| push_tag   | VARCHAR    | 推/噓/→  |
| message    | TEXT       | 推文內容 |

**sentiment_scores**（情緒分數，文章＋留言統一管理）

| 欄位         | 型別       | 說明                        |
| ------------ | ---------- | --------------------------- |
| score_id     | INTEGER PK | 自動遞增                    |
| target_type  | VARCHAR    | "article" 或 "comment"      |
| target_id    | INTEGER    | 對應 article_id / comment_id |
| method       | VARCHAR    | "jieba", "bert"...          |
| score        | REAL       | 情緒分數                    |
| calculated_at | TIMESTAMP | 計算時間                   |

## API Endpoints

| Method | Endpoint           | 說明                                |
| ------ | ------------------ | ----------------------------------- |
| GET    | /sentiments/today  | 今日平均情緒分數                    |
| GET    | /sentiments/change | 今昨情緒變化量                      |
| GET    | /sentiments/recent | 近 N 天情緒分數（預設 10，最多 30） |
| GET    | /articles/top_push | 熱門文章排行                        |
| GET    | /articles/search   | 關鍵字搜尋文章                      |
| GET    | /health            | 資料庫健康檢查                      |

## 安裝與執行

```bash
# 1. clone 專案
git clone https://github.com/andrew841018-design/ptt_stock_db.git
cd ptt_stock_db

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 3. 安裝套件
pip install -r requirements.txt

# 4. 建立資料庫
python3 dependent_code/Create_DB.py

# 5. 執行爬蟲 + 清洗 + 分析
python3 dependent_code/pipeline.py

# 6. 啟動視覺化儀表板
streamlit run dependent_code/visualization.py

# 7. 啟動 API
uvicorn test_code.api:app --reload

# 8. 執行測試
pytest test_code/test_api.py -v
```

## 自動化排程

ETL 每天由 **launchd**（macOS 官方排程機制）自動執行，完整流程：

> macOS Sequoia 上 cron daemon 無法啟動，改用 launchd。
> plist 位於 `~/Library/LaunchAgents/`，script 放在 `~/scripts/run_etl.sh`（PROJECT_DIR 硬編碼，避免 launchd CWD=/ 路徑問題）

```
爬蟲（PTT 股票板）→ SQLite → 情緒分析 → S3 備份 → GE 資料驗證
```

執行 log 存於 `logs/etl_YYYYMMDD.log`，每次結束自動產生摘要：

```
[...] ---------- 執行摘要 ----------
[...] ERROR 數量：0
[...] WARNING 數量：0
[...] ===== ETL 完成 =====
```

## 未來規劃

- [x] Phase 4：PostgreSQL 正規化 Schema 設計完成（Docker）
- [x] Phase 4：create_schema.sql 執行完成（4 張表 + 4 個 B-tree index）
- [x] Phase 4：backup.py 改用 config.DB_PATH；ge_validation.py import bug 修復
- [x] launchd 排程修復（cron daemon 在 macOS Sequoia 失效，改用 launchd）
- [x] requirements.txt 補齊（psycopg2-binary、great_expectations）
- [ ] Phase 4（進行中）：遷移腳本（SQLite → PostgreSQL）、psycopg2 連線
- [ ] 修復 score_target → target_type（analysis.py、visualization.py、api.py）
- [ ] Phase 5：資料倉儲（星型 schema）、BERT 情緒模型
- [ ] Phase 6：Airflow 排程、Kafka、Kubernetes
