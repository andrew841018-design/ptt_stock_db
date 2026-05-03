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
- **資料處理**：Pandas, tqdm
- **NLP**：KeyBERT（關鍵字抽取），BERT（情緒分析，Phase 5）
- **資料庫**：PostgreSQL（Docker）
- **API**：FastAPI, uvicorn
- **快取**：Redis（Cache-Aside Pattern）
- **視覺化**：Streamlit, Matplotlib
- **測試**：pytest, Great Expectations
- **CI/CD**：GitHub Actions
- **雲端**：AWS EC2, AWS S3

## 架構圖

```
PTT Stock 板 / 鉅亨網
        ↓
  scrapers/（ptt_scraper、cnyes_scraper）
        ↓
  base_scraper（統一寫入 DB）
        ↓
PostgreSQL
├── sources
├── articles
├── comments
├── sentiment_scores  ← 待 BERT 實作（Phase 5）
└── stock_prices      ← 0050 月股價（TWSE API）
        ↓
  api.py + Redis（Cache-Aside）
        ↓
  visualization.py（Streamlit）
```

## 專案結構

```
project/
├── dependent_code/
│   ├── pipeline.py           # 主流程（爬蟲 → QA）
│   ├── config.py             # 集中管理所有常數
│   ├── schema.py             # PostgreSQL 建表 + index
│   ├── pg_helper.py          # PostgreSQL 連線管理（context manager）
│   ├── cache_helper.py       # Redis Cache-Aside helper
│   ├── scrapers/
│   │   ├── __init__.py       # sys.path 統一設定
│   │   ├── base_scraper.py   # 爬蟲抽象父類別（DB 寫入邏輯）
│   │   ├── ptt_scraper.py    # PTT Stock 板爬蟲
│   │   ├── cnyes_scraper.py  # 鉅亨網爬蟲
│   │   └── twse_fetcher.py   # 0050 股價抓取（TWSE API）
│   ├── api.py                # FastAPI REST API
│   ├── visualization.py      # Streamlit 儀表板
│   ├── plt_function.py       # matplotlib 圖表函式
│   ├── QA.py                 # 資料品質檢查（pipeline 自動呼叫）
│   ├── ge_validation.py      # Great Expectations 資料驗證
│   ├── test_api.py           # pytest 自動測試
│   ├── backup.py             # S3 備份（pg_dump）
│   └── requirements.txt      # 套件清單
├── scripts/
│   └── run_etl.sh            # 自動化 ETL（launchd 每日執行）
├── logs/                     # ETL 執行 log（不進 git）
└── .github/workflows/
    └── deploy.yml            # CI/CD（pytest → EC2 部署）
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

| 欄位         | 型別           | 說明                        |
| ------------ | -------------- | --------------------------- |
| article_id   | SERIAL PK      | 自動遞增                    |
| source_id    | INTEGER FK NN  | 對應 sources                |
| title        | TEXT NN        | 文章標題                    |
| push_count   | INTEGER        | 推噓數（鉅亨網為 NULL）     |
| author       | VARCHAR        | 作者（可為 NULL）           |
| url          | TEXT NN UNIQUE | 文章網址                    |
| content      | TEXT NN        | 內文                        |
| published_at | TIMESTAMP NN   | 發文時間                    |
| scraped_at   | TIMESTAMP      | 爬取時間（DEFAULT NOW()）   |

**comments**（留言）

| 欄位       | 型別          | 說明     |
| ---------- | ------------- | -------- |
| comment_id | INTEGER PK    | 自動遞增 |
| article_id | INTEGER FK NN | 對應文章 |
| user_id    | VARCHAR NN    | 推文者   |
| push_tag   | VARCHAR NN    | 推/噓/→  |
| message    | TEXT NN       | 推文內容 |

**sentiment_scores**（情緒分數，每篇文章一筆，BERT 實作後填入）

| 欄位         | 型別       | 說明                |
| ------------ | ---------- | ------------------- |
| score_id     | SERIAL PK  | 自動遞增            |
| article_id   | INTEGER FK | 對應 articles       |
| score        | REAL       | 情緒分數            |
| calculated_at | TIMESTAMP | 計算時間            |

**stock_prices**（0050 股價，TWSE API 每月抓取）

| 欄位       | 型別          | 說明                     |
| ---------- | ------------- | ------------------------ |
| price_id   | SERIAL PK     | 自動遞增                 |
| trade_date | DATE UNIQUE   | 交易日（唯一，只追蹤 0050）|
| open       | NUMERIC(10,2) | 開盤價                   |
| high       | NUMERIC(10,2) | 最高價                   |
| low        | NUMERIC(10,2) | 最低價                   |
| close      | NUMERIC(10,2) | 收盤價                   |
| change     | NUMERIC(10,2) | 漲跌價差                 |

## API Endpoints

| Method | Endpoint           | 說明                                |
| ------ | ------------------ | ----------------------------------- |
| GET    | /sentiments/today  | 今日平均情緒分數                    |
| GET    | /sentiments/change | 今昨情緒變化量                      |
| GET    | /sentiments/recent | 近 N 天情緒分數（預設 10，最多 30） |
| GET    | /articles/top_push | 熱門文章排行                        |
| GET    | /articles/search   | 關鍵字搜尋文章                      |
| GET    | /health            | 資料庫健康檢查                      |
| GET    | /correlation/0050  | PTT 情緒 vs 0050 隔日漲跌相關性     |

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

# 4. 建立資料庫 Schema
python3 dependent_code/schema.py

# 5. 執行爬蟲 + 清洗 + 分析
python3 dependent_code/pipeline.py

# 6. 啟動視覺化儀表板
streamlit run dependent_code/visualization.py

# 7. 啟動 API
cd dependent_code && uvicorn api:app --reload

# 8. 執行測試
pytest dependent_code/test_api.py -v
```

## 自動化排程

ETL 每天由 **launchd**（macOS 官方排程機制）自動執行，完整流程：

> macOS Sequoia 上 cron daemon 無法啟動，改用 launchd。
> plist 位於 `~/Library/LaunchAgents/`，script 放在 `~/scripts/run_etl.sh`（PROJECT_DIR 硬編碼，避免 launchd CWD=/ 路徑問題）

```
爬蟲（PTT + 鉅亨網 + TWSE）→ PostgreSQL → QA 檢查 → S3 備份 → GE 資料驗證
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
- [x] 多來源爬蟲（PTT + 鉅亨網），Dcard 因 Cloudflare 封鎖移除
- [x] TWSE API 抓取 0050 股價，寫入 stock_prices 表
- [x] 情緒 vs 股價相關性分析 endpoint（/correlation/0050）
- [x] Redis Cache-Aside 實作（37x 加速）
- [x] jieba 移除，改以 BERT 為目標情緒分析方案
- [x] KeyBERT 關鍵字抽取（取代 regex 斷詞）
- [x] stock_prices 欄位精簡（移除 stock_no/stock_name/volume，只追蹤 0050）
- [x] GROUP BY Subquery 模式（相關性查詢架構正確化）
- [x] BERT config 框架（config.py 已定義所有權重與模型名稱）
- [x] 爬蟲 retry 機制（base_scraper exponential backoff，MAX_RETRY=5）
- [x] QA 強化（sources/來源專屬檢查、schema NOT NULL 約束對齊）
- [x] cnyes API 結構修正（`items.data` 路徑）
- [x] hardcoded 字串清查（backup.py 容器名稱修正、TWSE sleep、S3 bucket 移進 config）
- [x] api.py `pd.to_datetime()` 移至 `load_articles_df()` 只轉換一次
- [x] ge_validation.py 來源分離（PTT / 鉅亨網各自套用規則）
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：資料倉儲（星型 schema）、BERT 情緒模型
- [ ] Phase 6：Airflow 排程、Kafka、Kubernetes
