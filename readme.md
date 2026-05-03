# PTT Stock Sentiment Analysis

![CI](https://github.com/andrew841018-design/ptt_stock_db/actions/workflows/deploy.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

> 📘 **所有操作指令統一入口：** [`COMMANDS.md`](COMMANDS.md) ｜ `python dependent_code/cli.py --help`

## 🔗 Demo

| 服務             | 網址                            | 狀態 |
| ---------------- | ------------------------------- | ---- |
| REST API (Swagger) | http://52.65.94.221:8000/docs | ✅ live（JWT bcrypt + Prometheus metrics live）|
| Streamlit 儀表板 | http://52.65.94.221:8501      | ✅ live |
| Prometheus metrics | http://52.65.94.221:8000/metrics | ✅ live（`api_request_duration_seconds` / `articles_scraped_total` / `etl_step_duration_seconds`） |
| Swagger quick test | `admin` / `admin123`（bcrypt hash；production 需設 `ADMIN_PW_HASH` env var 覆寫） | |

> **Note**：EC2 demo 資料快照截至 2026-04-04（982,515 articles / 171,500 sentiment scores），是 frozen demo dataset。本機 PG 持續每小時 launchd ETL 補爬中（280k+ 並擴充）。`/sentiments/today` 若當日無資料會回 404 而非 500；要看歷史資料請用 `/sentiments/recent?period=30` 或 `/articles/search?keyword=AI`。

### 30 秒 Quick Test（curl）

```bash
# 1. 登入拿 JWT（注意是 JSON body，不是 form-encoded）
TOKEN=$(curl -s -X POST http://52.65.94.221:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. 搜尋文章（含 PTT / CNN / WSJ / cnyes / Reddit / MarketWatch）
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://52.65.94.221:8000/articles/search?keyword=AI" | head -c 500

# 3. 情緒 vs 0050 隔日漲跌相關性（已有完整 30 天資料）
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://52.65.94.221:8000/correlation/0050?period=30"

# 4. Prometheus metrics（無需 auth）
curl -s "http://52.65.94.221:8000/metrics" | grep "api_request_duration"
```

## 專案簡介

**問題**：散戶投資人面對眾多財經輿論（PTT 鄉民、新聞媒體、論壇）時，缺乏量化的整體情緒指標來判斷市場 sentiment 與股價走勢的關係。

**解法**：建一條 end-to-end pipeline，從 7 種異質來源（中英混合、有 paywall、有反爬、有 rate-limit）每小時自動爬文 → BERT 情緒分析 → 寫進 Snowflake Schema DW → 透過 REST API 提供查詢，並用 Streamlit 視覺化「情緒 vs 隔日股價漲跌」相關性。

**規模**：~280k articles、122k sentiment scores、10 年股價（0050 / VOO）、每小時自動執行、跨 macOS launchd / Docker Airflow / Kubernetes 三種部署。

## Design Decisions & Trade-offs

| 決策 | 為什麼這樣選 | 代價 |
|------|------------|------|
| **PostgreSQL OLTP + MongoDB raw 雙寫** | MongoDB 存原始 HTTP 回應 → QA 失敗時用 `reparse.py` 從 raw 重新解析寫回 PG，不需重爬 | 雙寫開銷 + 兩個 DB 的維運成本 |
| **Snowflake Schema 而非純 Star** | dim_source 上掛 dim_market（市場粒度的跨來源比較）；dim_stock 上掛 dim_source（追蹤 0050 vs VOO） | 多一層 JOIN，但用 MV 把成本攤到 refresh 時 |
| **Stored Procedure 刷 Mart 而不是 dbt 增量** | TRUNCATE + INSERT 簡單可控，跨 DB 可移植；本專案 Mart 行數小（< 50/日）| 不適合大表（百萬列重灌會慢）；要監控 SP 執行時間 |
| **dbt 同份 SQL 跑 PG + BigQuery** | 用 `{{ dbt.type_*() }}` macro 跨 adapter；展示「未來上 Cloud DW migration」能力 | 寫 macro 的初期成本，跨 adapter 細節（如 BQ `COUNTIF()` vs PG `FILTER`）要 dispatch |
| **base_scraper 共用 `requests.Session()` + jitter** | Wayback Machine 每爬蟲新開 TCP → 8 條同時超 per-IP cap → ECONNREFUSED；Session keep-alive + urllib3 pool 解決 | 一個 thread 阻塞影響其他（實際比序列快 2-4x）|
| **Airflow + launchd + K8s 三套排程並存** | 同份 `pipeline.py` 跑：本機 launchd 開發 / Airflow 演示 DAG 概念 / K8s 演示雲端編排 | 維運三套配置；現實只用其中一套就好 |

## 技術棧

- **爬蟲**：Python, requests, BeautifulSoup（CNN/WSJ/MarketWatch 改用 sitemap XML 解析）
- **資料處理**：Pandas, tqdm
- **NLP**：KeyBERT（關鍵字抽取），BERT（情緒分析）
- **資料庫**：PostgreSQL（Docker，含 Stored Procedure / Materialized View），MongoDB（Docker，raw 儲存）
- **API**：FastAPI, uvicorn, Pydantic（response model + 爬蟲入庫驗證）
- **快取**：Redis（Cache-Aside Pattern）
- **視覺化**：Streamlit, Matplotlib
- **測試**：pytest, Great Expectations
- **容器化**：Docker, Docker Compose（9 services：PostgreSQL / Redis / API / Worker / Airflow ×3 / Prometheus / Grafana）
- **排程**：Apache Airflow（8-task DAG，fail-soft trigger_rule）, Celery（非同步任務佇列）
- **監控**：Prometheus（metrics 收集）, Grafana（視覺化儀表板）
- **容器編排**：Kubernetes（Deployment / Service / CronJob / ConfigMap / Secret）
- **CI/CD**：GitHub Actions
- **雲端**：AWS EC2, AWS S3

## 架構圖

```mermaid
flowchart TB
    subgraph SRC["📰 Sources（7 種異質來源）"]
        S1[PTT Stock 板]
        S2[鉅亨網 cnyes]
        S3[Reddit 增量]
        S4[Reddit 歷史<br/>Arctic Shift]
        S5[CNN]
        S6[WSJ]
        S7[MarketWatch]
    end

    BASE[base_scraper<br/>共用 Session + jitter + retry]
    SCH[Pydantic ArticleSchema<br/>入庫前驗證]
    PG[(PostgreSQL OLTP<br/>articles · comments<br/>sentiment_scores · prices)]
    MG[(MongoDB<br/>raw HTTP 回應)]
    PII[PII Masking<br/>author hash]
    BERT[BERT 情緒分析<br/>fine-tune + 推論]
    QA[QA + Great Expectations]

    subgraph DW["⭐ Data Warehouse（Snowflake Schema）"]
        DIM[dim_market / dim_source / dim_stock]
        FACT[fact_sentiment<br/>stock_symbol denormalized]
        MART[Data Mart<br/>SP: TRUNCATE+INSERT]
        MV[Materialized View<br/>三表 JOIN]
    end

    API[FastAPI + JWT bcrypt]
    CACHE[(Redis Cache-Aside)]
    UI[Streamlit Dashboard]
    PROM[Prometheus /metrics]
    GRAF[Grafana dashboards]

    S1 --> BASE
    S2 --> BASE
    S3 --> BASE
    S4 --> BASE
    S5 --> BASE
    S6 --> BASE
    S7 --> BASE
    BASE --> SCH
    SCH --> PG
    SCH -.原始回應.-> MG
    PG --> PII
    PII --> BERT
    BERT -.寫回 sentiment.-> PG
    PG --> QA
    QA -.失敗.-> MG
    MG -.re-parse.-> PG
    PG --> DIM
    DIM --> FACT
    FACT --> MART
    FACT --> MV
    MART --> API
    MV --> API
    API --> CACHE
    CACHE -.cache hit.-> API
    API --> UI
    API --> PROM
    PROM --> GRAF

    classDef storage fill:#fef3c7,stroke:#92400e
    classDef compute fill:#dbeafe,stroke:#1e40af
    classDef ui fill:#dcfce7,stroke:#166534
    class PG,MG,CACHE storage
    class BASE,SCH,PII,BERT,QA,DIM,FACT,MART,MV compute
    class API,UI,PROM,GRAF ui
```

### 排程與部署（4 種觸發點，同一份 `pipeline.py`）

```mermaid
flowchart LR
    L[launchd<br/>macOS 本機<br/>每小時 :25]
    A[Airflow DAG<br/>Docker · 8-task fail-soft]
    K[K8s CronJob<br/>雲端 · 每小時 :25]
    C[Celery + Redis<br/>非同步任務佇列]

    PIPE[pipeline.py<br/>9 step<br/>schema · extract · transform<br/>pii · bert · dw_etl<br/>backup · ai_predict]

    L --> PIPE
    A --> PIPE
    K --> PIPE
    C --> PIPE

    style PIPE fill:#fef3c7,stroke:#92400e
```

### dbt on BigQuery — Cloud DW Lineage

PostgreSQL DW 之外另外實作 **dbt + BigQuery** 版本（`dbt/` folder），同一份 SQL 邏輯可跑 PG（`--target dev`）或 BQ（`--target bigquery`），展示 Cloud DW migration 能力。

```mermaid
flowchart LR
  A[articles<br/>BQ raw · 177k rows] --> S1[stg_articles<br/>view]
  B[sentiment_scores<br/>BQ raw · 177k rows] --> S2[stg_sentiment_scores<br/>view]
  C[sources<br/>BQ raw · 8 rows] --> S3[stg_sources<br/>view]
  S1 --> F[fact_sentiment<br/>table · 32 rows]
  S2 --> F
  S3 --> F
  F --> M[mart_daily_summary<br/>table · 32 rows]

  style F fill:#fef3c7
  style M fill:#bbf7d0
```

**實跑結果**（`expanded-talon-458706-m2.ptt_sentiment` dataset，2026-04-24）：

| Model | Type | Rows | 用途 |
|---|---|---:|---|
| `stg_articles` / `stg_sentiment_scores` / `stg_sources` | view | 177,543 / 177,543 / 8 | 型別投射 + 跨 adapter（PG/BQ）cast 宏 |
| `fact_sentiment` | table | 32 | 粒度 (fact_date × source_id)，含 pos/neu/neg count |
| `mart_daily_summary` | table | 32 | API / 儀表板直讀，source 粒度（加 pos_ratio / neg_ratio）|

**Tests**：15 data tests 全 PASS（source unique/not_null × 9、model not_null × 6）；同一份 dbt project 兩個 target 皆綠。

**跨 adapter 對照**（同一 dbt model 在兩個 target 上的差異）：

| 概念 | PostgreSQL | BigQuery |
|---|---|---|
| 型別投射 | `col::TYPE` | `CAST(col AS TYPE)` ← 用 `{{ dbt.type_*() }}` 宏跨 adapter |
| 條件計數 | `COUNT(*) FILTER (WHERE ...)` | `COUNTIF(...)` ← 用自訂 `count_if()` macro dispatch |
| 字串型別 | `TEXT` / `VARCHAR(n)` | `STRING` |
| 浮點型別 | `NUMERIC(m,n)` / `REAL` | `FLOAT64` |

**指令**：

```bash
cd dbt

# 本機 PG 跑
GCP_PROJECT=... BQ_DATASET=ptt_sentiment BQ_LOCATION=US \
  dbt run --target dev --profiles-dir .

# BigQuery 跑
GCP_KEYFILE=/path/to/key.json \
  dbt run --target bigquery --profiles-dir .

# 產出 docs 站（含 lineage graph）
dbt docs generate --profiles-dir .
dbt docs serve --profiles-dir .   # 本機 port 8080 開啟互動式 docs
```

**資料品質驗證**：9 個 dbt tests（not_null × 7 + `dbt_utils.unique_combination_of_columns` × 2），確保 fact/mart 欄位完整性。

## 專案結構

```
project/
├── dependent_code/
│   ├── pipeline.py           # 主流程（8-step：schema → extract → transform → pii → bert → dw_etl → backup → ai_predict）
│   ├── cli.py                # 統一 CLI 入口（本機測試 & 手動觸發各功能）
│   ├── config.py             # 集中管理所有常數 + SOURCES 唯一 source of truth（新增來源只需加一筆 entry）
│   ├── schema.py             # PostgreSQL 建表 + index
│   ├── pg_helper.py          # PostgreSQL 連線管理（context manager）
│   ├── cache_helper.py       # Redis Cache-Aside helper
│   ├── scrapers/
│   │   ├── __init__.py           # sys.path 統一設定
│   │   ├── base_scraper.py       # 爬蟲抽象父類別（DB 寫入邏輯）
│   │   ├── ptt_scraper.py        # PTT Stock 板爬蟲
│   │   ├── cnyes_scraper.py      # 鉅亨網爬蟲
│   │   ├── reddit_scraper.py     # Reddit 財經版增量爬蟲
│   │   ├── reddit_batch_loader.py# Reddit 歷史大量資料載入器（Arctic Shift API）
│   │   ├── cnn_scraper.py        # CNN 財經新聞爬蟲（Search API + full-text）
│   │   ├── wsj_scraper.py        # WSJ 財經新聞爬蟲（RSS feeds + Google News RSS）
│   │   ├── marketwatch_scraper.py# MarketWatch 財經新聞爬蟲（RSS feeds + Google News RSS）
│   │   ├── scraper_schemas.py    # Pydantic 資料驗證 schema
│   │   ├── tw_stock_fetcher.py   # 0050 股價抓取（TWSE API）
│   │   └── us_stock_fetcher.py   # VOO 股價抓取（yfinance）
│   ├── api.py                # FastAPI REST API
│   ├── visualization.py      # Streamlit 儀表板
│   ├── plt_function.py       # matplotlib 圖表函式
│   ├── QA.py                 # 資料品質檢查（pipeline 自動呼叫）
│   ├── ge_validation.py      # Great Expectations 資料驗證
│   ├── test_api.py           # pytest 自動測試
│   ├── backup.py             # S3 備份（pg_dump）
│   ├── dw_schema.py          # DW Star/Snowflake Schema DDL（dim_market / dim_source / dim_stock / fact_sentiment）+ Data Mart + Materialized View
│   ├── dw_etl.py             # OLTP → DW incremental ETL
│   ├── data_mart.py          # Data Mart 刷新 + 查詢介面
│   ├── bert_sentiment.py     # BERT fine-tune / evaluate / batch inference
│   ├── labeling_tool.py      # Streamlit 人工標注工具
│   ├── reparse.py            # 資料修復管線（MongoDB raw → re-parse → UPDATE PG）
│   ├── pii_masking.py        # PII 遮蔽（author hash 化）
│   ├── auth.py               # JWT 認證（verify_token）
│   ├── mongo_helper.py       # MongoDB raw_responses helper
│   ├── ai_model_prediction.py # AI 模型預測系統（Walk-Forward + RandomForest）
│   ├── llm_labeling.py       # LLM 輔助情緒標注（Google Gemini 2.5 Flash，寫入 article_labels）
│   ├── metrics.py            # Prometheus 監控指標（Counter / Gauge / Histogram）
│   ├── celery_app.py         # Celery 非同步任務佇列（Redis broker/backend）
│   ├── tasks.py              # Celery task 定義（pipeline 各步驟 + full chain）
│   ├── scrapers/
│   │   └── wayback_backfill.py # Wayback Machine CDX API 回填爬蟲（CNN/WSJ 歷史文章）
│   └── requirements.txt      # 套件清單
├── Dockerfile                # Docker image（python:3.9-slim + dependent_code + init_marts.sql）
├── docker-compose.yml        # 9 services（postgres / redis / api / worker / airflow × 3 / prometheus / grafana）
├── airflow/
│   └── dags/
│       └── etl_dag.py        # Airflow DAG（8-task 線性 pipeline，fail-soft trigger_rule）
├── k8s/
│   ├── api-deployment.yaml   # FastAPI Deployment（2 replicas）+ LoadBalancer Service
│   ├── cronjob.yaml          # K8s CronJob（每小時 :25 分執行 pipeline.py，每次啟新 Pod、跑完即刪）
│   ├── postgres-deployment.yaml  # PostgreSQL StatefulSet + PVC + ClusterIP Service
│   ├── redis-deployment.yaml     # Redis Deployment + ClusterIP Service
│   ├── namespace.yaml        # namespace: stock-sentiment
│   ├── configmap.yaml        # 非敏感環境變數
│   └── secret.yaml           # 模板；真密碼由 scripts/apply_k8s_secrets.sh 從 .env 注入
├── grafana/
│   └── provisioning/
│       ├── datasources/prometheus.yml  # Grafana 自動註冊 Prometheus datasource
│       └── dashboards/dashboard.yml    # Grafana 自動載入 dashboard JSON
├── prometheus.yml            # Prometheus scrape config（self + fastapi:8001）
├── scripts/
│   ├── run_etl.sh            # 自動化 ETL（launchd 每小時執行）
│   ├── init_marts.sql        # Stored Procedure / Function 定義（SP 刷新 + 情緒查詢 Function）
│   ├── deploy.sh             # EC2 部署腳本
│   └── health_check.sh       # 服務健康檢查腳本
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
| source_name | VARCHAR(100) | e.g. "ptt"                    |
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
| scraped_at   | TIMESTAMP      | 爬取時間（DEFAULT (NOW() AT TIME ZONE 'UTC')；scrapers 也以 `datetime.utcnow()` 寫入 → 一致 UTC）|

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
| close      | NUMERIC(10,2) | 收盤價                   |
| change     | NUMERIC(10,2) | 漲跌價差                 |

**us_stock_prices**（VOO 股價，yfinance 抓取）

| 欄位       | 型別          | 說明                         |
| ---------- | ------------- | ---------------------------- |
| price_id   | SERIAL PK     | 自動遞增                     |
| trade_date | DATE UNIQUE   | 交易日（唯一，只追蹤 VOO）   |
| close      | NUMERIC(10,2) | 收盤價                       |
| change     | NUMERIC(10,2) | 漲跌價差                     |

## Commit Tag 對照表

每個 annotated tag 名稱直接取自 `daily_guide_v2.html` 任務名，標記對應的任務完成 commit。

| Phase | Tag | 說明 |
|-------|-----|------|
| Phase 1 | `Phase1·Python爬蟲` | PTT 爬蟲實作（requests + BeautifulSoup）|
| Phase 1 | `Phase1·HTML解析` | HTML 解析與欄位抽取 |
| Phase 1 | `Phase1·Schema設計` | SQLite/PostgreSQL 資料表設計 |
| Phase 1 | `Phase1·logging` | logging 取代 print，結構化日誌 |
| Phase 1 | `Phase1·錯誤處理retry` | requests retry + exponential backoff |
| Phase 1 | `Phase1·IncrementalLoading` | URL 去重，只爬新資料 |
| Phase 1 | `Phase1·資料品質檢查` | QA.py 自動化資料品質檢查 |
| Phase 1 | `Phase1·Index設計` | B-tree index 設計與 EXPLAIN ANALYZE |
| Phase 1 | `Phase1·備份與恢復` | backup.py + pg_dump + S3 |
| Phase 2 | `Phase2·Pandas資料清洗` | Pandas 型別轉換、空值處理、去重 |
| Phase 2 | `Phase2·推噓數格式轉換` | PTT 推噓數爆/XX/X格式正規化 |
| Phase 2 | `Phase2·日期處理` | Unix timestamp → datetime 轉換 |
| Phase 2 | `Phase2·Matplotlib視覺化` | matplotlib 情緒趨勢圖 |
| Phase 2 | `Phase2·Streamlit儀表板` | Streamlit 互動式網頁儀表板 |
| Phase 2 | `Phase2·GreatExpectations` | Great Expectations 資料驗證 |
| Phase 3 | `Phase3·FastAPI` | FastAPI app 與 uvicorn 部署 |
| Phase 3 | `Phase3·REST_API設計` | RESTful endpoint 設計 |
| Phase 3 | `Phase3·pytest` | pytest 自動測試 + mock |
| Phase 3 | `Phase3·Shell自動化` | run_etl.sh + launchd 排程 |
| Phase 3 | `Phase3·環境變數管理` | config.py 集中管理常數與環境變數 |
| Phase 4 | `Phase4·PostgreSQL遷移` | SQLite → PostgreSQL 遷移 |
| Phase 4 | `Phase4·Redis快取` | Redis Cache-Aside Pattern |
| Phase 4 | `Phase4·多來源爬蟲` | PTT + 鉅亨網 OOP 爬蟲架構 |
| Phase 4 | `Phase4·Pydantic驗證` | Pydantic response model + 入庫驗證 + Reddit/VOO 爬蟲 |
| Phase 4 | `Phase4·多來源ETL` | ThreadPoolExecutor 並行 pipeline（待確認無誤後打 tag）|

## API Endpoints

| Method | Endpoint           | 說明                                |
| ------ | ------------------ | ----------------------------------- |
| GET    | /sentiments/today  | 今日平均情緒分數                    |
| GET    | /sentiments/change | 今昨情緒變化量                      |
| GET    | /sentiments/recent | 近 N 天情緒分數（回傳 period + sentiment_score） |
| GET    | /articles/top_push | 熱門文章排行（回傳 limit + articles）            |
| GET    | /articles/search   | 關鍵字搜尋文章                      |
| GET    | /health            | 資料庫健康檢查                      |
| GET    | /correlation/0050  | PTT 情緒 vs 0050 隔日漲跌相關性     |
| POST   | /auth/login        | JWT 登入取得 token                   |
| GET    | /ai_model_prediction/{market} | AI 模型預測結果（tw/us）   |

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

ETL 每小時自動執行（:25 分），支援三種排程方式：

| 方式 | 環境 | 設定 |
|------|------|------|
| **launchd** | macOS 本機 | `~/Library/LaunchAgents/` plist → `run_etl.sh` |
| **Airflow DAG** | Docker Compose | `airflow/dags/etl_dag.py`（8-task 線性 pipeline） |
| **K8s CronJob** | Kubernetes 叢集 | `k8s/cronjob.yaml`（Forbid concurrency） |

> macOS Sequoia 上 cron daemon 無法啟動，改用 launchd。
> plist 位於 `~/Library/LaunchAgents/`，script 放在 `~/scripts/run_etl.sh`（PROJECT_DIR 硬編碼，避免 launchd CWD=/ 路徑問題）

```
schema → extract（PTT + 鉅亨網 + Reddit + CNN + WSJ + MarketWatch + TWSE + VOO）→ transform（QA + 自動修復 + GE）→ PII 遮蔽 → BERT 推論 → DW ETL → S3 備份 → AI 預測
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
- [x] Pydantic response model（所有 endpoint 加上 response_model=，Swagger 自動文件）
- [x] scraper_schemas.py（爬蟲入庫前 Pydantic 驗證：title、url、push_count、published_at）
- [x] API 動態 key 改為固定 key（/sentiments/recent、/articles/top_push）
- [x] Optional[X] 全改為 X | None（Python 3.10+ 語法）
- [x] Bug fix：api.py get_top_push_articles 共享 DataFrame in-place mutation（加 df.copy()）
- [x] Bug fix：ptt_scraper X 前綴推文數計算錯誤（X1=-1 → 應為 X1=-10，乘以 10）
- [x] Bug fix：ptt_scraper _parse_push_count ValueError 改為 log warning + return None，防止崩潰
- [x] Bug fix：cnyes_scraper publishAt 改 item.get() + early return None 防 KeyError
- [x] Bug fix：visualization.py yesterday 空集合時 NaN delta 改為顯示 0
- [x] 多來源 ETL 整合：pipeline.py 改用 `concurrent.futures.ThreadPoolExecutor` 並行爬取 PTT + 鉅亨網 + TWSE，ETL 三階段明確分層
- [x] Bug fix：`str|None` Python 3.9 不相容（5 個檔案改回 `Optional[X]`），修復 cnyes scraper 靜默失敗問題
- [x] Reddit 多版面爬蟲（r/investing + r/stocks + r/wallstreetbets + Bogleheads + personalfinance + financialindependence）
- [x] Arctic Shift 歷史資料載入器（Reddit 2005 年至今完整存檔）
- [x] us_stock_prices 表建立（VOO，yfinance 抓取）
- [x] scraper_schemas.py Pydantic 驗證（ArticleSchema / CommentSchema）
- [x] `_get_with_retry` OOP 架構完善（BaseScraper 實例方法 + module-level 函式並存）
- [x] schema.py SQL comment 標注追蹤標的（0050 / VOO）
- [x] pipeline.py 升級為 ThreadPoolExecutor 並行版本（ETL 三階段分層：extract / transform / load）
- [x] Bug fix：_get_or_create_source 加 ON CONFLICT DO NOTHING，解決並行 race condition
- [x] Bug fix：get_with_retry 改 raise 保留完整 traceback
- [x] Bug fix：cnyes_scraper title 加 .strip() 統一格式
- [x] Bug fix：requirements.txt 移除重複 pydantic
- [x] Phase 4：Star Schema + Snowflake Schema（dim_market 延伸）
- [x] Phase 4：Data Mart（mart_daily_summary，source 粒度）
- [x] Phase 4：Materialized View（mv_market_summary，Snowflake 三表 JOIN，market 粒度）
- [x] ~~Phase 4：Data Lake~~ → 移除（MongoDB raw_responses 已涵蓋 raw layer，專案規模不需要 S3 三層）
- [x] Phase 4：MongoDB（raw_responses 原始 HTTP 存檔）
- [x] Phase 4：自動修復管線（reparse.py：QA 失敗 → MongoDB re-parse → UPDATE PG）
- [x] Phase 4：article_labels 表名集中管理（config.py ARTICLE_LABELS_TABLE）
- [x] Phase 4：launchd 排程改為每小時執行（:25 分）
- [x] Phase 4：base_scraper `_store_raw()` 原始 HTTP 回應自動存入 MongoDB raw_responses
- [x] Database 改名 ptt_stock → stock_analysis_db
- [x] config.py 局部性原則重構（15+ 常數搬回各自模組）
- [x] source_name 統一（PTT Stock/鉅亨網/Reddit Finance → ptt/cnyes/reddit）
- [x] schema.py 角色權限完整註解（GRANT/REVOKE/SEQUENCE/pg_roles）
- [x] backup.py 移除 PG_CONFIG 間接存取，改用 os.environ.get() 直讀
- [x] schema.py 角色建立改用 os.environ.get() 直讀（移除 PG_API_CONFIG 間接層）
- [x] MongoDB 清理：移除 raw_articles collection，只保留 raw_responses
- [x] test_api.py JWT bypass + get_pg_readonly mock 修正（13 tests passing）
- [x] auth.py verify_token 加註解
- [x] Phase 5：BERT 情緒分析（fine-tune + zero-shot 批次推論）
- [x] Phase 5：AI 模型預測系統（Walk-Forward + RandomForest）
- [x] pipeline.py 8-step 整合（schema → extract → transform → pii → bert → dw_etl → backup → ai_predict）
- [x] dim_date 移除（DW schema 簡化，fact_sentiment 直接用 fact_date）
- [x] stock_symbol denormalized 進 fact_sentiment，tracked_stock 加入 dim_source
- [x] Sleep delays 統一收進 config.py
- [x] idx_hot partial index 移除
- [x] Bug fix：base_scraper `_get_or_create_source` race condition（ON CONFLICT RETURNING 為空時 fallback SELECT）
- [x] Bug fix：ai_model_prediction `_spawn_bert_inference_background` subprocess `-c` 模式 `__file__` 未定義
- [x] CNN / WSJ / MarketWatch 三大財經新聞來源爬蟲（BaseScraper 繼承，RSS + full-text fetching）
- [x] config.py 重構為唯一 source of truth（SOURCES dict + helper functions），新增來源只需改 3 個檔案
- [x] GE / QA 動態化：迴圈 SOURCES.items() 衍生檢查規則，新增來源不需改 GE/QA 程式碼
- [x] visualization / AI model / DW ETL / cli / labeling_tool 全部改用 config 衍生，不再 hardcode 來源清單
- [x] backup.py 時區修正（datetime.now() → datetime.utcnow()）
- [x] pipeline.py update_dependencies stamp 時區修正（3 處 `datetime.now()` → `datetime.utcnow()`，與 codebase 一致）
- [x] reddit_scraper.py JSON 解析防禦（`response.json()` 移進 try/except，Reddit 回傳被截斷 response 時降為 warning + break，不中斷其他來源）
- [x] cli.py `_cmd_pipeline` 移除未使用 `os` import（pyflakes 全綠）
- [x] dependent_code/__pycache__ 幽靈 pyc 清除（backtest / fetch_etf_holdings / looker_export / perf_tuning / stock_matcher 共 7 個檔；source 已刪但 pyc 殘留會造成幽靈 import）
- [x] feedparser 安裝（WSJ / MarketWatch RSS 解析）
- [x] `cmd.cpython-39.pyc` 殘留快取清除（cmd.py → cli.py 改名後的遺留問題）
- [x] Bug fix：pg_helper.py 防禦性 rollback（PG server 意外斷線時雙重 crash 修復，rollback/close 各自包 try/except）
- [x] QA.py NOT EXISTS 優化（110 萬筆大表孤兒檢查從 NOT IN 改為 NOT EXISTS，解決記憶體壓力 + PG OOM 問題）
- [x] Phase 6：Dockerfile + Docker Compose（9 services 完整本機部署）
- [x] Phase 6：Airflow DAG（8-task 線性 pipeline，fail-soft trigger_rule='all_done'）
- [x] Phase 6：Kubernetes（api-deployment / cronjob / postgres-statefulset / redis / configmap / secret）
- [x] Phase 6：Prometheus + Grafana 監控（metrics.py Counter/Gauge/Histogram + 自動 datasource provisioning）
- [x] Phase 6：Celery 非同步任務佇列（Redis broker/backend + tasks.py）
- [x] Phase 6：Shell 部署腳本（deploy.sh / health_check.sh）
- [ ] Phase 5：Spark/PySpark 批次處理（待上完課）
- [ ] 人工標注 500 篇 → fine-tune BERT → 重新推論
- [x] JWT Authentication（auth.py + /auth/login + bcrypt password hashing）

## 已知坑 / 設計筆記

### Arctic Shift API：HTTP 200 with Error Body
Arctic Shift API 注意事項：
- 第三方 Reddit 歷史存檔服務，非 Reddit 官方 API
- 錯誤格式特殊：永遠回 HTTP 200，錯誤訊息塞在 JSON body 內，需自行檢查 data.get("error")，HTTP retry 攔不到這類錯誤

Arctic Shift 在參數錯誤時仍回傳 HTTP 200，錯誤訊息在 body 的 `error` 欄位。
`raise_for_status()` 無法捕捉，必須手動 `data.get("error")` 判斷。
```python
data = response.json()
if data.get("error"):
    logging.warning(f"API 錯誤：{data['error']}")
    break
```

### Great Expectations `mostly` 參數
GE expectation 的容忍比例（0.0～1.0），`mostly=0.99` 允許 1% 的值不符合規則。
用於 `change` 欄位：第一筆必定 NULL（無前一日收盤價），設 0.99 避免 pipeline 每次 FAIL。

### Great Expectations 0.18.19：regex anchor（re.match vs re.search）
`expect_column_values_to_match_regex` 底層用 `re.match`（anchor 在字串開頭），不是 `re.search`。
- 若 `url_pattern` 是「URL 中某段子字串」（如 `cnn.com/`），URL 開頭是 `https://...` 會全部 FAIL
- 修法：consumer 端補 `.*` 前綴（`f".*{url_pattern}"`），讓 `re.match` 從任意位置開始比對
- `config.py` 的 pattern 保持 search 語意（乾淨），fix 收斂在 `ge_validation.py` 單一消費端

### API 錯誤訊息 info disclosure 防範（OWASP A05:2021）
FastAPI `HTTPException(detail=str(e))` 會把原始 DB 錯誤文字回給 client，洩漏 schema / column / 套件細節。
- Server side：`logging.exception(msg)` 保留完整 traceback
- Client side：`detail={"message": "database search failed"}` 等 generic 訊息
- 本專案 3 處修復：`load_articles_df()` / `/correlation/0050` / `/health`

### psycopg2 v2 `with conn:` 陷阱
`with psycopg2.connect(**PG_CONFIG) as conn:` **只管 transaction**（commit/rollback），不會 `conn.close()`。
- 慢性 connection leak：ETL 每跑一次漏一個，長時間耗盡 PG `max_connections`
- 修法：改用 `pg_helper.get_pg()`（`finally: conn.close()` 保證釋放）
- 全專案 DML 一律走 `get_pg()`；DDL（CREATE / REFRESH MV）才直接 `psycopg2.connect(**PG_CONFIG)` 用 admin 角色

### MongoDB raw_responses：原始 HTTP 回應存檔
- `base_scraper._store_raw()` 在每次 HTTP 請求成功後自動存入 MongoDB
- PTT → `raw_html`（HTML 字串）；鉅亨網/Reddit → `raw_json`（JSON 字串）
- 降級設計：MongoDB 掛掉只 log warning，不影響爬蟲主流程（`_MONGO_OK` flag + `PyMongoError` catch）
- 用途：QA 抓到壞資料時，從 raw re-parse 修復，不需重新爬取

### Shell tee + grep 自污染雪崩（run_etl.sh ERROR 指數增長）
ETL 摘要段落寫入 LOG_FILE 時若包含 grep 會匹配的關鍵字，下次執行 grep 同一個 LOG_FILE 會把摘要本身計入，造成 ERROR_COUNT 指數成長（0 → 1 → 6 → 16 → 36 → ... → 1012）。
- **不夠的解法**：grep -v "  >>" 過濾 detail 行 + LOG_START_LINE 對齊新增段；race 或 wc 失敗仍會炸
- **根治解法**：summary 段「完全不寫入 LOG_FILE」，改寫獨立 `etl_summary_YYYYMMDD.log`；摘要文字改用「錯誤總數 / 警示總數」中文 keyword 不被 grep 抓
- 教訓：**架構性隔離 > pattern 過濾**。當文字會被同一條工具二次掃描時，最乾淨的修法是分檔，不是過濾

### yfinance rate-limit 期間 NoneType 錯誤（us_stock_fetcher.py）
yfinance 1.2.0 在 Yahoo Finance API rate-limit 或暫時錯誤時，內部 `_history_metadata` 會被設為 None；`Ticker(...).history()` 在後續 subscript 操作時拋出 `'NoneType' object is not subscriptable`，看起來像 logic bug 實則是上游 transient failure。
- **不夠的解法**：只 `if hist.empty:`——empty 檢查無法捕捉「整個 hist 為 None」或「yfinance 內部子物件為 None」這兩種情境
- **根治解法**：(1) try/except 包 `Ticker.history()` (2) 3 次 retry + exponential backoff（5s/15s/30s）(3) 連續失敗 fallback 為空 list，不中斷 pipeline——歷史資料已存於 `us_stock_prices`，本輪略過下輪自動重抓
- 教訓：第三方 SDK 非預期 None 是常見 transient failure 模式；retry decorator + None defense 是標準防禦

### 自動修復管線（reparse.py）
pipeline.py 的 QA 失敗時自動觸發修復流程：
1. `QA_checks()` raise ValueError → catch
2. `repair()` → `diagnose()` 掃描 PostgreSQL 壞資料
3. 依 URL 分類來源（ptt.cc / cnyes.com / reddit.com）
4. 從 MongoDB `raw_responses` 取原始 HTML/JSON
5. 用對應 parser（`_parse_ptt_raw` / `_parse_cnyes_raw` / `_parse_reddit_raw`）重新解析
6. UPDATE PostgreSQL（只更新非 None 欄位，避免覆蓋好的值）
7. 修復後重跑 `QA_checks()`，若仍失敗則 pipeline 中止

### `unittest.mock.patch` 對 refactor 改名靜默失敗（2026-04-30）
- `api.py` 早期用 `get_pg_readonly`，refactor 後改連線池版 `get_pg_pooled`，但 `test_api.py` 仍 patch 舊名 → 14 個測試 `AttributeError: <module 'api'> does not have the attribute 'get_pg_readonly'`
- **根因**：`patch("api.X")` 是字串魔法，IDE refactor 不會自動同步測試；改名後必須 grep `patch(.*\.old_name` 全 codebase
- **修法**：sed 批次將 `api.get_pg_readonly` → `api.get_pg_pooled`（共 8 處）→ 23 passed
- **規範**：本專案任何 helper/function 改名前先跑 `grep -rn 'patch(.*\.<old_name>' --include="test_*.py"`，確認 mock target 同步
