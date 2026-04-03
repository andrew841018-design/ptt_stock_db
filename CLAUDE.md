# CLAUDE.md — Andrew 的 PTT 專案學習記錄

> 每次對話結束後請更新此檔案，確保下次能無縫接續。

---

## 關於 Andrew

- 目標：Data Engineer 轉職
- 學習風格：需要引導、範例、指引，抓 bug 時希望被引導找原因，而非直接給解法
- 偏好輸出格式：HTML（不需要 PDF）

---

## 專案簡介

**PTT 股票板情緒分析系統**

資料流：`爬蟲 → SQLite → 情緒分析 → FastAPI + Streamlit 儀表板`

技術棧：Python、SQLite / PostgreSQL、FastAPI、Streamlit、Redis、pytest、GitHub Actions CI/CD、AWS EC2

### 專案結構

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
│   │   ├── base_scraper.py   # 爬蟲抽象父類別
│   │   ├── ptt_scraper.py    # PTT Stock 板爬蟲
│   │   ├── cnyes_scraper.py  # 鉅亨網爬蟲
│   │   └── twse_fetcher.py   # 0050 股價抓取（TWSE API）
│   ├── api.py                # FastAPI REST API
│   ├── visualization.py      # Streamlit 儀表板
│   ├── plt_function.py       # matplotlib 圖表函式
│   ├── QA.py                 # 資料品質檢查
│   ├── ge_validation.py      # Great Expectations 驗證
│   ├── test_api.py           # pytest 自動測試
│   ├── backup.py             # S3 備份
│   └── requirements.txt
├── scripts/
│   └── run_etl.sh
├── .github/workflows/
│   └── deploy.yml
└── CLAUDE.md
```

---

## 目前進度

### 已完成

- [x] Phase 1：建 DB + 爬蟲 + 情緒分析 + matplotlib 視覺化
- [x] Phase 2：重構 + Streamlit 網頁視覺化 + pipeline 串接
- [x] Phase 3：FastAPI REST API + pytest 自動測試 + GitHub Actions CI/CD + AWS EC2 部署

### 進行中 / 下一步

- [x] cron 自動排程修復（Full Disk Access + conda Python 絕對路徑）
- [x] great_expectations 安裝並修復 import 路徑
- [x] run_etl.sh 加入執行摘要（ERROR / WARNING 數量）
- [x] Phase 4：PostgreSQL 正規化 Schema 設計（sources / articles / comments / sentiment_scores）
- [x] PostgreSQL Docker 容器建立（inspiring_wozniak，port 5432）
- [x] create_schema.sql 執行完成，4 張表建立
- [x] ge_validation.py bug 修復（`except ImportError` 改為 `from config import`）
- [x] backup.py 改用 `from dependent_code.config import DB_PATH`
- [x] ptt_stock.db 從 git 移除，加入 .gitignore
- [x] scripts/create_schema.sql 加入版控
- [x] .gitignore 補強（.claude/settings.local.json、*.db、*.pem）
- [x] Index 設計完成（4 個 B-tree index，含選型原則與 EXPLAIN ANALYZE）
- [x] launchd 排程修復（macOS Sequoia cron 失效 → 改用 launchd，解決 TCC Desktop 限制）
- [x] ETL 自動排程驗證（etl_20260325.log 成功產生）
- [x] Redis 快取實作（Cache-Aside Pattern，TTL 24小時，37倍速度提升）
- [x] AWS CLI 安裝與設定
- [x] Phase 4：遷移腳本（SQLite → PostgreSQL）完成（migrate.py）
- [x] Phase 4：psycopg2 連線（pg_helper.py 已實作）
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：資料倉儲（星型 schema）、BERT 情緒模型
- [ ] Phase 6：Airflow、BERT、CI/CD 進階

---

## Git Commit 歷史摘要

| Commit  | 內容                                      |
| ------- | ----------------------------------------- |
| 8ffcc80 | 把整串流程包進 script（crontab 定期執行） |
| 7c2fc5b | update readme；處理 backup.py 路徑問題    |
| 8731353 | 修改 code 符合 clean code / design pattern |
| dd580d4 | 更新 troubleshooting.md（所有遇過的問題） |
| 7aa8abb | bypass CI/CD SSH timeout 問題             |
| 2dd42a8 | 自動測試 API + FastAPI 基礎端點           |

---

## 踩過的重大坑（摘要）

詳細見 `troubleshooting.md`，以下是最關鍵的幾個：

1. **CI/CD SSH session timeout**（#17）— 用 `setsid + nohup + > /dev/null 2>&1 &` 解決
2. **cd 污染工作目錄**（#22）— 用 `bash -c` 子 shell 隔離
3. **uvicorn 路徑格式**（#21）— 用點號（Python import 格式），不是斜線
4. **streamlit 路徑格式**（#16）— 用斜線（檔案路徑），不是點號
5. **user_dict.txt 相對路徑**（#18）— import chain 導致，需在 `dependent_code` 目錄下執行
6. **DB schema 缺欄位**（#19）— `Published_Time` 等欄位需直接寫進 `Create_DB.py`
7. **pytest mock DB**（#8）— CI/CD 無真實 DB，用 `unittest.mock.patch` 注入假資料

---

## API Endpoints

- `GET /sentiments/today` — 今日平均情緒分數
- `GET /sentiments/change` — 今昨情緒變化量
- `GET /sentiments/recent` — 近 N 天（預設10，最多30）
- `GET /articles/top_push` — 熱門文章排行
- `GET /articles/search` — 關鍵字搜尋
- `GET /health` — DB 健康檢查

---

## 對話記錄摘要

### 2026-03-18

- Andrew 讓 Claude 讀取所有 HTML 指南、project code、git history、troubleshooting.md
- 確認輸出偏好：HTML 為主，PDF 跳過
- 討論 Claude Code vs Cowork 差異：開發用 Claude Code，文件用 Cowork
- 建立 CLAUDE.md 作為跨對話的記憶機制
- Andrew 的學習需求：引導、範例、指引、抓 bug，希望被引導而非直接給答案
- 專案程式需要遵守 clean code/system design/design pattern/重構原則
- CLAUDE.md 要按時更新，不只在對話結束時

#### 重構完成項目（2026-03-18）

| 檔案 | 改動 |
|------|------|
| `config.py` | 新建，集中管理所有常數（DB_PATH、TABLE、SKIP_KEYWORDS 等） |
| `db_helper.py` | 新建，context manager 統一管理 DB 連線，解決 connection leak |
| `api.py` | 抽出 `load_articles_df()`，消除 5 個 endpoint 的重複 try/except/finally |
| `web_scraping.py` | 拆出 `_is_duplicate()`、`_insert_article()`、`_insert_comments()` helper；SQL 換用 TABLE 常數 |
| `sentiment.py` | 改為 lazy load，詞庫只在第一次呼叫 `calculate_sentiment()` 才載入；修正 `user_dict.txt` 路徑 |
| `analysis.py` | 移除 `pd.set_option` 全局副作用；DB 讀寫分離（讀完關連線再處理） |
| `data_cleanner.py` | 解決循環 import（`numberic_push_count` 從 `analysis.py` 移過來）；修正 `Published_Time` 計算順序 |
| `pipeline.py` | tuple unpack 替代 hardcoded SQL；print → logging；main loop 加 retry 邏輯 |

#### 學到的概念（2026-03-18）

- `yield` + `@contextmanager` + `finally` → 自動關閉資源
- `_` 前綴 = 私有函式慣例
- `-> pd.DataFrame` = type hint
- `astype(int)` 在 NULL 欄位會 crash
- `os.path.dirname(__file__)` 解決相對路徑問題
- `while...else` — break 不進 else，loop 跑完才進 else
- print vs logging 差異
- 循環 import 的解法：移動函式到正確的模組

#### 今日額外完成（2026-03-18 下午）

| 項目 | 狀態 |
|------|------|
| `backup.py` | S3 備份完成，AWS credentials 設定好，bucket `ptt-sentiment-backup` |
| `scripts/run_etl.sh` | Shell script 自動化 ETL，含 log 輸出 |
| crontab | 每天 08:00 自動跑 `run_etl.sh` |
| README badge | CI badge 加入 README |
| `sentiment.py` | `jieba.load_userdict` 改用 `os.path.join(__file__)` 絕對路徑 |

#### 學到的概念（下午）

- `$(dirname "$0")` vs `cd ..`：script 的路徑永遠相對於檔案位置
- `$(date +%Y%m%d)` = bash 指令替換，等同 Python f-string
- `2>&1 | tee -a log` = 同時輸出到 terminal 和 log 檔
- tqdm 在非 TTY 環境（redirect 到檔案）自動停用
- MIT License = Massachusetts Institute of Technology 授權，最寬鬆開源授權
- `.env` + `load_dotenv` = 環境變數管理，把 secret 從 code 分離
- Claude Code = terminal 裡的 claude，可直接執行程式、讀檔、修 bug
- `--dangerously-skip-permissions` 跳過每次指令確認

---

### 2026-03-20

#### 完成項目

| 項目 | 說明 |
|------|------|
| cron 排程修復 | macOS Full Disk Access 給 `/usr/sbin/cron`；改用 conda Python 絕對路徑，移除 `source activate` |
| ge_validation.py 修復 | 安裝 `great_expectations==0.18.19`；修復 `import` 和 DB 路徑（try/except 同時支援本地 + /tmp cron 環境） |
| run_etl.sh 加摘要 | ETL 結束自動統計 ERROR / WARNING 數量並列出詳細內容 |
| 全流程驗證 | cron 14:05 自動觸發，pipeline + S3 + GE 全部通過，0 error |

#### 學到的概念

- macOS cron TCC：cron daemon 沒有 Desktop 磁碟存取權，需給 Full Disk Access 或複製到 /tmp
- `source activate` 在 cron 無效，應直接用 venv/conda 的絕對 Python 路徑
- `$?` = 上一個指令的 exit code（0 成功，非 0 失敗）
- `[ ! -f "$PATH" ]` = 檔案不存在的判斷
- `"$VAR"` = 變數加引號防止路徑空格問題
- `grep -c` = 計算符合行數
- `${PIPESTATUS[0]}` = pipe 中第一個指令的 exit code

#### 下次繼續

- [ ] `analysis.py` 的 `Column already exist` ERROR 改為 WARNING 或加 IF NOT EXISTS 判斷
- [ ] Phase 1 NEW：Index 設計（`CREATE INDEX`、`EXPLAIN QUERY PLAN`）
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication
- [ ] README：截圖（Swagger UI + Streamlit）、Mermaid 架構圖
- [ ] QA.py 加 `if __name__ == "__main__"` guard
- [ ] EC2 確認是否在跑（`http://13.236.116.213:8000` 連不上）

---

### 2026-03-24

#### 完成項目

| 項目 | 說明 |
|------|------|
| PostgreSQL Schema 設計 | 4 張正規化表：sources / articles / comments / sentiment_scores |
| sentiment_scores 設計決策 | 用 target_type 統一管理文章＋留言情緒，支援多模型（jieba / bert）|
| PostgreSQL 建立 | Docker 容器 inspiring_wozniak，port 5432，database: ptt_stock |
| create_schema.sql 執行 | 4 張表 + 4 個 index 建立完成 |
| run_etl.sh 逐行理解 | 見下方學到的概念 |
| ge_validation.py bug 發現 | try/except 兩行 import 路徑相同，except 應改為 `from config import` |

#### 學到的概念

- `#!/bin/bash` = shebang，告訴系統用哪個程式執行 script
- `dirname "$0"` = 取得 script 所在資料夾，確保路徑不受執行位置影響
- `2>&1` = 把 stderr 合併進 stdout（`&` 代表「這是 fd 編號，不是檔名」）
- `2>/dev/null` = 把錯誤丟棄（只藏訊息，exit code 不變）
- `|| true` = 讓失敗的 exit code 變成 0，防止 `set -e` 中斷 script
- `tee -a` = 同時輸出到終端機和 log 檔（`-a` = append）
- `${PIPESTATUS[0]}` = pipe 中第一個指令的 exit code（`$?` 只會拿到最後一個）
- `while read -r line` + pipe = 逐行處理 pipe 左側的輸出
- `&&` vs `;` = `&&` 前一個成功才執行下一個；`;` 不管成敗都執行
- `os.environ.get('KEY')` = 讀環境變數，找不到回傳 None
- 正規化設計原則：sentiment_scores 獨立成表，方便未來替換 NLP 模型

#### 下次繼續

- [ ] 遷移腳本：SQLite → PostgreSQL（注意型別轉換：Push_count TEXT→INTEGER，時間 TEXT→TIMESTAMP）
- [ ] 改用 psycopg2 連線 PostgreSQL
- [ ] ge_validation.py bug 修復（except 改為 `from config import`）
- [ ] backup.py 改用 `from config import DB_PATH`

---

### 2026-03-25

#### 完成項目

| 項目 | 說明 |
|------|------|
| ge_validation.py bug 修復 | `except ImportError` 的 import 路徑從 `dependent_code.config` 改為 `config`，正確支援 cron `/tmp` 環境 |
| backup.py 路徑修復 | 改用 `from dependent_code.config import DB_PATH`，消除硬寫路徑 |
| ptt_stock.db 從 git 移除 | 加入 `.gitignore`，避免二進位 DB 檔污染版控 |
| scripts/create_schema.sql 加入版控 | PostgreSQL 建表腳本納入 git，確保 schema 可重現 |
| .gitignore 補強 | 加入 `.claude/settings.local.json`、`*.db`、`*.pem` |
| Index 深度學習 | B-tree / Hash / Clustered / Composite / Partial / Full-text(GIN) / GiST 七種類型，選型原則與本專案應用 |
| daily_guide_v2.html 更新 | index 內容融合進 Phase 1（task card 擴充）+ Phase 4（PostgreSQL遷移、Star Schema、Data Mart、Query Optimization）|
| launchd 排程修復 | cron daemon 在 macOS Sequoia 無法啟動 → 改用 launchd；解決 TCC Desktop 存取問題（script 移到 ~/scripts/，PROJECT_DIR 硬編碼）|
| ETL 自動排程驗證 | etl_20260325.log 成功產生，launchd 正常觸發 |
| project_snapshot.html 生成 | 專案現況快照（架構、Schema、API、已知問題、下一步）|
| project_notes.md 生成 | 以專案為主軸的重點整理（8 個章節）|
| "update" 關鍵字設定 | 說 update → 自動讀取並更新三個文件，回報變動 |

#### 學到的概念

- Index 7 種類型的差異與選型原則（詳見 project_notes.md）
- `EXPLAIN ANALYZE` 看 Index Scan vs Seq Scan
- `pg_stat_user_indexes` 找無用 index
- launchd plist 設定（`~/Library/LaunchAgents/`）
- TCC（隱私權限）限制：launchd agent 無法存取 Desktop → 移到 `~/scripts/`
- launchd 預設 CWD 是 `/`，script 裡 `dirname "$0"` 會算錯 → 硬編碼 PROJECT_DIR
- Claude Code hooks：PreToolUse / PostToolUse / Stop 等事件，exit 0 放行 / exit 2 阻擋

#### 下次繼續

- [ ] 遷移腳本：SQLite → PostgreSQL（注意型別轉換：Push_count TEXT→INTEGER，時間 TEXT→TIMESTAMP）
- [ ] 改用 psycopg2 連線 PostgreSQL
- [ ] `analysis.py` 的 `Column already exist` ERROR 改為 WARNING 或加 IF NOT EXISTS 判斷
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

---

### 2026-03-26

#### 完成項目

| 項目 | 說明 |
|------|------|
| Schema 設計深度理解 | sources 正規化理由、sentiment_scores Polymorphic Association 設計決策 |
| psycopg2-binary 安裝 | psycopg2 需編譯，開發環境改用 psycopg2-binary |
| schema.py 清理 | 移除 getLogger、改用 logging.info()、移除未使用的 `from psycopg2 import sql` |
| Logging 概念 | basicConfig vs getLogger 分工，詳見 project_notes.md 九、Logging |

#### 學到的概念

- `sources` 獨立成表：避免 source 屬性（url、name）在每篇文章重複存，改一次不用改萬筆
- Polymorphic Association：`target_type + target_id` 讓 sentiment_scores 同時支援文章/留言，新增目標類型不用改 schema
- `logging.basicConfig` 是全域設定（格式、等級）；`logging.info()` 直接用就好，`getLogger` 在單一模組專案用不到
- `psycopg2` 需要本機 PostgreSQL 開發工具才能編譯，開發環境直接裝 `psycopg2-binary`

#### 下次繼續

- [ ] 遷移腳本：SQLite → PostgreSQL（Push_count TEXT→INTEGER，時間 TEXT→TIMESTAMP）
- [ ] 改用 psycopg2 連線 PostgreSQL
- [ ] `analysis.py` 的 `Column already exist` ERROR 改為 WARNING 或加 IF NOT EXISTS 判斷
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

---

### 2026-03-29

#### 完成項目

| 項目 | 說明 |
|------|------|
| QA.py 重構 | 原本只有 `__main__`，改為包成 `QA_checks()` 函式，支援獨立執行與被 import 兩種情境 |
| QA.py 加 assert | 3 個 assert 取代 if/warning：無重複 URL、無孤兒推文、articles 不為空 |
| pipeline.py 整合 QA | `from QA import QA_checks`，`analysis()` 後呼叫，QA 邏輯不重複寫進 pipeline |
| require_lib.txt 改名 | 改為標準 `requirements.txt`，配合 `pip install -r` 慣例 |
| python-dotenv 安裝修復 | launchd 排程跑 pipeline 時 ModuleNotFoundError，安裝至 conda env 解決 |

#### 學到的概念

- `HAVING` vs `WHERE`：`WHERE` 分組前過濾原始資料；`HAVING` 分組後過濾聚合結果（`COUNT`、`SUM` 等）
- Data Engineering QA ≠ 手動測試，而是 pipeline 裡的自動化檢查點（重複資料、FK 完整性、資料量）
- `assert` 是關鍵字不是函式，不需要括號：`assert 條件, "訊息"`
- `assert(條件, "訊息")` 的陷阱 — 括號使整體變成 tuple，永遠是 truthy，assert 永遠不會 fail
- `fetchone()` 回傳單個 tuple（一列），用 `[0]` 取第一個欄位值
- `fetchall()` 回傳 list of tuples（全部列），空結果是 `[]`
- `ModuleNotFoundError` = 該套件未裝在「執行當下」的 Python 環境，conda env 需逐一安裝

#### 下次繼續

- [ ] 遷移腳本：SQLite → PostgreSQL（Push_count TEXT→INTEGER，時間 TEXT→TIMESTAMP）
- [ ] 改用 psycopg2 連線 PostgreSQL
- [ ] `analysis.py` 的 `Column already exist` ERROR 改為 WARNING 或加 IF NOT EXISTS 判斷
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

---

### 2026-03-29（下午）

#### 完成項目

| 項目 | 說明 |
|------|------|
| 全專案 code review | 找出 20 個問題，最高優先：`score_target` → `target_type` 欄位名錯誤（analysis/visualization/api 全部受影響）|
| `ptt_sentiment_dict.py` 合併 | 字典內容移入 `sentiment.py`，刪除原檔，少一個 import |
| `_get_or_create_source` 加 type hint | `-> int` + docstring，讓回傳值一目瞭然 |
| requirements.txt 補齊 | 補上 `psycopg2-binary`、`great_expectations==0.18.19` |

#### 學到的概念

- `SERIAL PRIMARY KEY` = PostgreSQL 自動遞增，INSERT 不用填該欄位
- `RETURNING` = INSERT 後直接回傳指定欄位值，不用再查一次
- `_` 前綴 = 只在本檔案內用的 helper，不對外開放
- `-> int` type hint = 讓 IDE 直接顯示回傳型別，不用看函式內容
- `re.search(r'M\.(\d+)\.', url)` = regex 找 PTT URL 裡的 Unix timestamp
- `group(0)` = 整個 match；`group(1)` = 第一個括號內容
- `datetime.fromtimestamp()` = Unix timestamp → Python datetime
- `item.decompose()` = BeautifulSoup 把元素從 DOM 移除並銷毀（vs `extract()` 移除但保留）
- Python 檔案無法在不改 import 路徑的前提下移進子資料夾，根本原因是 import 依賴當前目錄
- `str(e)` vs `raise`：`str(e)` 只取訊息文字繼續跑；`raise` 往上拋中止執行
- Exception 傳遞方向：底層 raise → 中層 except+處理+raise → 最上層 except+logging 收尾

#### 下次繼續

- [ ] 修復 `score_target` → `target_type`（analysis.py、visualization.py、api.py）
- [ ] QA.py、ge_validation.py 連線改用 context manager
- [ ] 遷移腳本：SQLite → PostgreSQL
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

---

### 2026-03-29（晚）

#### 學到的概念

- `st.dataframe()` 回傳 `None`，賦值給變數毫無意義，直接呼叫才是正確寫法
- `finally` + `os.path.exists()` 組合：`pg_dump` 失敗時暫存檔不一定存在，先檢查再刪才不會 FileNotFoundError
- 不能把清理移到 `try` 裡：失敗時不會執行到，暫存檔殘留
- Linux 三個預設 file descriptor：`0`=stdin / `1`=stdout / `2`=stderr
- `> /dev/null`：把 stdout 導入黑洞（輸出消失）
- `2>&1`：把 stderr 導向「stdout 現在去的地方」；`&` = 這是 fd 編號，不是檔名
- `os.environ.get()` 永遠回傳字串，psycopg2 `port` 需要 `int()` 轉型，其他欄位不用
- `MagicMock` 被移除的原因：連線從 `get_db_connection()`（回傳物件）改為 `get_pg()`（context manager），`patch` 替換整個 context manager 不需要指定 `return_value`
- `出場` 從 `POSITIVE_WORDS` 移除：語意模糊（獲利出場 vs 停損出場），拿掉避免情緒方向誤判
- `deploy.yml` 三個改動：requirements.txt 改名同步 / pytest 路徑隨資料夾搬移 / `pkill -f` 取代 `kill $(lsof)` 更穩健

#### 下次繼續

- [ ] 修復 `score_target` → `target_type`（analysis.py、visualization.py、api.py）
- [ ] QA.py、ge_validation.py 連線改用 context manager
- [ ] 遷移腳本：SQLite → PostgreSQL
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

---

### 2026-04-01

#### 完成項目

| 項目 | 說明 |
|------|------|
| Redis 快取實作 | Docker 啟動 redis:7 容器（redis_cache，port 6379，--restart=always） |
| cache_helper.py 新建 | `get_cache()` / `set_cache()`，Cache-Aside Pattern，含 RedisError 保護 |
| api.py 快取整合 | `load_articles_df()` 實作 Cache-Aside：先查 Redis → MISS 才查 DB → 存進 Redis |
| config.py 擴充 | 新增 REDIS_HOST / REDIS_PORT / REDIS_TTL（86400 = 24小時） |
| requirements.txt | 補上 redis 套件 |
| 速度驗證 | 第一次 4.11s（DB），第二次 0.11s（Redis），提升 37 倍 |
| test_api.py 補強 | 舊 fixtures 加 mock Redis；新增 test_cache_hit / test_cache_miss / test_cache_redis_down / test_set_and_get_cache，全部 15 個測試通過 |
| deploy.yml 更新 | 加入 Redis service（image: redis:7），讓 CI/CD 也能跑真實 Redis 測試 |
| backup.py bug 修復 | `DOCKER` / `CONTAINER` 移到模組頂層；`'localhost'` 改用 `PG_CONFIG['host']`；移除 finally 中文 what 註解 |
| config.py 改善 | `load_dotenv` 改為先找同層 .env，找不到再往上 |
| run_etl.sh 改善 | 新增複製 .env 到 /tmp |
| 基礎設施 | Docker Desktop 設為開機自動啟動；inspiring_wozniak 和 redis_cache 均設為 --restart=always |
| AWS CLI | 安裝完成，`aws configure` 設定完成 |
| launchd 排程 | 每天 10:25 自動跑 ETL |

#### 學到的概念

- Cache-Aside Pattern：先查 Redis → MISS 才查 DB → 存進 Redis（由應用層控制快取）
- Redis 是 key-value store，內部用 hash table，查詢 O(1)
- TTL（Time To Live）：`setex` = SET + EXpire，到期自動刪除
- `StringIO`：把字串包成 file-like object，讓 `pd.read_json()` 接受
- `Optional[X]` = X 或 None（Python 3.9 寫法，等同 `X | None`）
- `orient='table'`：JSON 序列化時保留 dtype，避免 int→float、datetime→str 型別漂移
- `patch("api.get_cache")` vs `patch("cache_helper.get_cache")`：要 patch 使用者的命名空間
- `with patch` 嵌套 vs 平行（逗號分隔）：兩者效果相同，平行語法更清楚
- `side_effect` vs `return_value`：side_effect 觸發行為（拋錯/自訂函式），return_value 固定回傳值
- unit test 測的是「程式面對錯誤時的行為」，不是「基礎設施會不會出錯」
- GitHub Actions services：CI/CD 環境自動啟動 Docker 容器供測試使用
- file descriptor（OS 層級整數）vs file-like object（Python 層級物件）

#### 下次繼續

- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：星型 Schema、BERT 情緒模型
- [ ] Phase 6：Airflow

---

### 2026-04-02

#### 完成項目（上午）

| 項目 | 說明 |
|------|------|
| migrate.py 新建 | SQLite → PostgreSQL 完整遷移腳本，冪等設計（可重複執行） |
| 文章遷移 | 14,024 筆，含型別轉換（Push_count TEXT→INTEGER、時間 TEXT→TIMESTAMP）|
| 留言遷移 | 1,422,053 筆，分批寫入（BATCH_SIZE=5000）|
| 情緒分數遷移 | 14,024 筆，batch 內 dedup 避免衝突 |
| id_map 設計 | SQLite article_id ≠ PG article_id，用 URL 當橋梁建立對應表 |

#### 完成項目（下午）

| 項目 | 說明 |
|------|------|
| jieba 完整移除 | analysis.py、sentiment.py、ntusd-*.txt、user_dict.txt 全部刪除；visualization.py 改用 regex 斷詞 |
| Dcard 移除 | Cloudflare Bot Fight Mode 無法繞過，dcard_scraper.py 刪除，config/pipeline 同步清理 |
| sentiment_scores schema 簡化 | 移除 target_type / target_id / method，改為 article_id FK（一篇文章一個分數）|
| scrapers/__init__.py 新建 | 集中處理 sys.path，所有爬蟲 import 前自動執行 |
| 多來源爬蟲架構 | PTT + 鉅亨網，base_scraper 統一 DB 寫入邏輯 |
| TWSE stock_prices | 新建 stock_prices 表，twse_fetcher.py 抓 0050 股價（TWSE API URL 更新：exchangeReport → rwd/zh/afterTrading）|
| 相關性分析 | api.py 新增 /correlation/0050，visualization.py 新增兩張圖（散布圖 + 雙軸折線）|
| TWSE_STOCKS 簡化 | 從 50 支個股改為只追蹤 0050，config 改用 TWSE_STOCK_NO / TWSE_STOCK_NAME |
| ptt_scraper 重構 | _parse_list_item → _parse_article_html；_parse_push_count 三段式可讀性改善（爆/XX/X數字）|
| deploy.yml 版本 | 誤改為 @v4/@v5，後於 2026-04-03 還原為正確的 @v6（2026 年當前版本）|
| 文件全面更新 | readme.md、CLAUDE.md 架構圖與 schema 同步至最新狀態 |

#### 學到的概念

- `relativedelta(months=i)`：精確往前推 N 個月，不用擔心月份天數不同
- `strftime("%Y%m%d")`：date 物件轉字串格式
- `@staticmethod`：method 不使用 self，語意上與 class 狀態無關
- TWSE API：每次回傳整個月資料，`date` 參數只要填該月任意一天
- `tqdm` 雙層進度條：外層留著（`leave=True`），內層跑完消失（`leave=False`）
- `reversed(list)`：不改原 list，回傳 iterator

#### 下次繼續

- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：BERT 情緒分析實作（sentiment_scores 填入資料）
- [ ] Phase 5：星型 Schema（資料倉儲）
- [ ] Phase 6：Airflow

---

### 2026-04-03

#### 完成項目

| 項目 | 說明 |
|------|------|
| stock_prices table 簡化 | 移除 stock_no、stock_name、volume 欄位，因為只追蹤 0050 一支股票，這些欄位冗餘 |
| schema.py 更新 | UNIQUE constraint 改為只在 trade_date，移除 idx_stock_prices_stock_no index，改為 idx_stock_prices_trade_date |
| twse_fetcher.py 簡化 | 移除外層 for 迴圈（只剩一支股票），INSERT 移除 stock_no/stock_name/volume 欄位 |
| Subquery 模式修復 GROUP BY | api.py 和 visualization.py 的相關性查詢改用 subquery 先聚合再 JOIN，解決非聚合欄位必須全部放進 GROUP BY 的問題 |
| KeyBERT 取代 regex 斷詞 | visualization.py 的關鍵字統計從 regex 改用 KeyBERT，`keyphrase_ngram_range=(1,2)` 抽取 1-2 詞組合，`top_n=20` |
| @st.cache_resource 快取模型 | KeyBERT 模型用 `@st.cache_resource`（重量級資源），vs DataFrame 用 `@st.cache_data` |
| BERT config 框架 | config.py 新增 BERT_MODEL、PUSH_TAG_WEIGHT、TITLE_WEIGHT、CONTENT_WEIGHT、COMMENT_WEIGHT，Phase 5 實作時直接 import |
| STOCK_PRICES_TABLE 加入 config | config.py 新增 `STOCK_PRICES_TABLE = "stock_prices"`，所有用到此表的地方改用 config 變數 |
| deploy.yml @v6 確認 | 確認 actions/checkout@v6 和 actions/setup-python@v6 是正確版本（2026 年當前版本）；前次誤改為 @v4/@v5 已還原 |
| keybert 安裝 | venv 中 `pip install keybert`，requirements.txt 已加入 |

#### 學到的概念

- **GROUP BY 規則**：SELECT 中所有非聚合欄位（非 AVG/SUM/COUNT 等）都必須放進 GROUP BY，PostgreSQL 無法推斷哪個欄位才是「真正的 key」
- **GROUP BY 只看 SELECT，不看整個 table**：只有 SELECT 裡出現的欄位才需要判斷要不要放 GROUP BY，table 裡其他欄位完全不管
- **AVG 只是「怎麼壓」，GROUP BY 才是「按什麼切」**：avg_sentiment 是壓縮之後的結果，GROUP BY 就是壓縮動作本身；沒有 GROUP BY，AVG 會把全部資料壓成一個值
- **Subquery 解法**：在 subquery 先做聚合（GROUP BY 只放需要分組的欄位），外層再 JOIN 其他表取值，避免把不需要的欄位塞進 GROUP BY
  ```sql
  SELECT sub.sentiment_date, sub.avg_sentiment, sp.close
  FROM (
      SELECT DATE(published_at) AS sentiment_date, AVG(score) AS avg_sentiment
      FROM articles a JOIN sentiment_scores s ON ...
      GROUP BY DATE(published_at)   -- 只有這一個 key
  ) sub
  JOIN stock_prices sp ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
  ```
- **聚合欄位判斷**：能用 AVG/SUM/COUNT 等函式「多對一壓縮」的數值才算聚合欄位（score、push_count）；代表個別實體的欄位（id、url、title）每筆都不同，不能聚合
- **@st.cache_resource vs @st.cache_data**：`cache_resource` 用於重量級物件（模型、DB 連線），整個 app session 共用一份；`cache_data` 用於 DataFrame 等資料，每個參數組合各快取一份
- **KeyBERT 原理**：用 BERT 算句子和候選詞的語意相似度，`keyphrase_ngram_range=(1,2)` 表示 1 到 2 個字的詞組，`top_n` 控制回傳關鍵詞數量；不需要額外讀 text，`extract_keywords(text)` 一次完成

- **stock_prices 移除 sp.close**：相關性分析只需要 `next_day_change`，`close` 本身跟情緒預測無關；plt_function.py 右軸同步改為畫 `next_day_change`
- **@abstractmethod 是框架，不是實作**：base class 只定義「要有什麼方法、回傳什麼格式」，實際邏輯在子類別；base 的空殼永遠不會被執行
- **Python import 時掃描 class 結構**：不用執行任何方法，import 時就已知道哪些 abstractmethod 有沒有被實作；沒實作 → 建立物件時直接報錯
- **base class 的分工**：子類別負責「怎麼爬」（get_source_info / fetch_articles），base 負責「怎麼存」（run / _save_to_db / _insert_*）；新增來源只要加子類別，DB 邏輯完全不用動
- **繼承語法 `class 子類別(父類別)`**：擁有父類別所有方法 + 必須實作父類別的 abstractmethod；沒有括號就是普通 class，跟父類別完全無關
- **push_count 設計修正**：cnyes 無推文數，改為明確回傳 `None`（語意正確），schema 改為 `INTEGER`（允許 NULL），base_scraper 用 `.get('push_count')` 取值
- **comments 設計修正**：`_insert_comments` 改為 `if article.get('comments')` 才呼叫，不再靠空 list 默默跳過
- **Retry 架構**：`_get_with_retry()` 統一放在 base_scraper，所有子類別繼承後直接用 `self._get_with_retry()`；retry 次數由 `config.MAX_RETRY` 控制；失敗時 exponential backoff（2s、4s、8s...）；**未來新增任何來源，HTTP 請求一律用 `self._get_with_retry()`，不用 `requests.get()`**
- **published_at 單位**：PTT 和鉅亨網都是 Unix timestamp（秒），都用 `datetime.fromtimestamp()` 轉換，單位一致
- **QA 架構強化**：schema.py 對 articles（title/content/url/published_at）和 comments（user_id/push_tag/message）加 NOT NULL 約束；QA.py 新增 sources 不為空檢查、來源專屬檢查（PTT push_count 不為 NULL）；schema NOT NULL 需重建 DB 才生效（待 pipeline 跑完後執行）
- **cnyes API 結構修正**：回傳格式是 `{"items": {"data": [...]}}` 而非 `{"data": {"items": [...]}}`，`_fetch_news_list` 取值路徑已修正
- **cnyes page_size 加入 config**：`SOURCES["cnyes"]["page_size"] = 30`，`_fetch_news_list` 改用 `_SOURCE["page_size"]`
- **hardcoded 字串清查**：backup.py 的 BUCKET/DOCKER/CONTAINER、twse_fetcher 的 sleep(3)、api.py 的 CACHE_KEY 全部移進 config；API 查詢限制常數（PERIOD_MIN 等）留在 api.py（只有 api 用，不屬於全域設定）
- **api.py 效能修正**：`pd.to_datetime()` 從四個 endpoint 各自轉換，改為在 `load_articles_df()` 裡做一次
- **backup.py 容器名稱修正**：`inspiring_wozniak` → `ptt_stock_db`（重建容器後名稱已改）
- **ge_validation.py 來源分離**：JOIN sources 表，PTT 和鉅亨網各自套用對應的 URL regex 和 push_count 規則；`_log_result()` 抽成函式避免重複
- **正規化的 JOIN 代價**：articles JOIN sources 取 source_name 是正規化的正常代價；目前只有 2 個來源規模小，JOIN 沒問題；Phase 5 星型 schema 時改為 denormalization（已記錄在 memory）

#### 下次繼續

- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：BERT 情緒分析實作（bert_sentiment.py，config.py 框架已就位）
- [ ] Phase 5：資料倉儲（星型 schema）
- [ ] Phase 6：Airflow、Kafka、Kubernetes

---

## 使用說明

每次開新對話時，請先說：「先讀 CLAUDE.md」，Claude 就能快速接續上次進度。

對話結束前，請更新：

- 當天完成的事
- 遇到的問題
- 下次要繼續的地方

每次改動，務必檢查是否遵守：

- clean code/system design/design pattern/重構原則

### 關鍵字速查

| 關鍵字 | 用途 |
|--------|------|
| `update` | 執行前先對整個 project 做一次 code review（讀取所有 `.py` 與 `.yml` 檔案，確認無功能性問題）。review 完畢後，自動讀取並同步更新三個文件（`CLAUDE.md`、`readme.md`、`project_notes.md`），將最新完成項目、進度清單、學到的概念等寫入，並回報各檔案的變動內容。同時檢查所有 `.py` 檔案的 import，確認有無未列入 `requirements.txt` 的套件，若有則補上 |
