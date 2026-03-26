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

技術棧：Python、SQLite、FastAPI、Streamlit、pytest、GitHub Actions CI/CD、AWS EC2

### 專案結構

```
project/
├── dependent_code/         # 主要程式碼
│   ├── pipeline.py         # 主流程
│   ├── web_scraping.py     # 爬蟲
│   ├── analysis.py         # 資料清洗 + 情緒分數
│   ├── sentiment.py        # jieba 情緒分析
│   ├── ptt_sentiment_dict.py
│   ├── data_cleanner.py
│   ├── visualization.py    # Streamlit 儀表板
│   ├── plt_function.py
│   ├── Create_DB.py
│   └── user_dict.txt / ntusd-*.txt
├── test_code/
│   ├── api.py              # FastAPI
│   ├── test_api.py         # pytest
│   └── QA.py
├── backup.py
├── setup.sh
├── deploy_yml_syntax.md
├── troubleshooting.md      # 所有踩過的坑
└── CLAUDE.md               # 本檔案
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
- [ ] Phase 4（進行中）：遷移腳本（SQLite → PostgreSQL）
- [ ] Phase 4（進行中）：改用 psycopg2 連線
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
| （進行中） | — |

#### 學到的概念

（待補）

#### 下次繼續

- [ ] 遷移腳本：SQLite → PostgreSQL（Push_count TEXT→INTEGER，時間 TEXT→TIMESTAMP）
- [ ] 改用 psycopg2 連線 PostgreSQL
- [ ] `analysis.py` 的 `Column already exist` ERROR 改為 WARNING 或加 IF NOT EXISTS 判斷
- [ ] Phase 2 NEW：PII masking（author hash 化）
- [ ] Phase 3 NEW：JWT Authentication

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
| `update` | 自動讀取並同步更新三個文件（`CLAUDE.md`、`readme.md`、`project_notes.md`），將最新完成項目、進度清單、學到的概念等寫入，並回報各檔案的變動內容 |
