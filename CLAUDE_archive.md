# CLAUDE_archive.md — 對話記錄歸檔

> 2026-03-18 ~ 2026-04-08 的舊對話記錄。最新記錄見 `CLAUDE.md`。

---

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
| PostgreSQL 建立 | Docker 容器 ptt_stock_db，port 5432，database: stock_analysis_db |
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
- **父類別同時有兩種方法**：`@abstractmethod` = 規格，子類別必須實作；一般方法（`_load_urls` / `_save_to_db` / `_get_with_retry`）= 父類別已實作好，子類別直接繼承使用，不需要重寫
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

---

### 2026-04-03（下午）

#### 完成項目

| 項目 | 說明 |
|------|------|
| Pydantic response model | api.py 所有 endpoint 加上 `response_model=`，Swagger 自動產生文件，過濾多餘欄位 |
| API 動態 key 改為固定 key | `/sentiments/recent` → `{period, sentiment_score}`；`/articles/top_push` → `{limit, articles}` |
| scraper_schemas.py 新建 | 爬蟲入庫前 Pydantic 驗證：title 非空、url regex、push_count -100~100、published_at 非未來 |
| Optional[X] → X \| None | 全專案統一改為 Python 3.10+ 語法，移除 `from typing import Optional` |
| test_api.py 補強 | 所有 endpoint 的 200 response 加上 body key 驗證 |
| update 定義更新 | code review 環節改為自我迭代 10 次無錯才停 |
| 繼續指令定義 | 說「繼續」→ 按照 daily_guide_v2.html 順序推進下一個任務 |
| Bug fix：api.py DataFrame mutation | `get_top_push_articles` 改 `df = df.copy()` 防止共享快取物件被污染 |
| Bug fix：ptt_scraper X 前綴推文數 | `X1=-1` 錯誤 → 改為 `X1=-10`（乘以 10），與 PTT 規格一致 |
| Bug fix：ptt_scraper _parse_push_count | 無效 push_count 不再 raise ValueError 崩潰，改為 log warning + return None |
| Bug fix：cnyes_scraper publishAt | 改用 `item.get()` + early return None，防止 publishAt 缺失時 KeyError |
| Bug fix：visualization.py NaN delta | yesterday 無資料時 change_score 改顯示 0，不再傳 NaN 給 st.metric |

#### 學到的概念

- **Pydantic BaseModel**：用 class 定義資料結構，FastAPI 自動驗證 response 型別、過濾多餘欄位、產生 Swagger 文件
- **response_model=**：endpoint 的合約，告訴 FastAPI 這個 endpoint 應該回傳什麼格式
- **`extra: allow`**：允許 model 有靜態定義以外的 key，適合動態 key 場景；但代價是失去型別保護，能避則避
- **API breaking change**：key 名稱改變會讓呼叫方靜默壞掉，趁未對外公開前改好
- **`list[X]`**：list 裡每個元素都要符合 X 型別，Pydantic 逐一驗證；vs `list` 不驗證內容
- **`@field_validator("欄位名")`**：指定這個 validator 對哪個欄位生效，不加裝飾器 validator 不會被呼叫
- **`@classmethod`**：Pydantic v2 規定 field_validator 必須是 classmethod，`cls` 是固定語法但實際用不到
- **validator 參數命名**：`v` 是舊慣例，直接用欄位名（`title`、`url`）更直觀
- **`int | None`**：Python 3.10+ Union 型別，等同 `Optional[int]`，更簡潔
- **scraper_schemas.py 驗證失敗 return None**：在 for loop 裡，None 讓這篇跳過繼續爬下一篇；raise 會中斷整個爬蟲

#### 下次繼續

- [ ] 按 daily_guide_v2.html 繼續推進（說「繼續」自動接續）
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：BERT 情緒分析實作（bert_sentiment.py，config.py 框架已就位）
- [ ] Phase 5：資料倉儲（星型 schema）
- [ ] Phase 6：Airflow、Kafka、Kubernetes

---

### 2026-04-04

#### 完成項目

| 項目 | 說明 |
|------|------|
| Git history rewrite | 16 → 14 commits；commit message 移除 `[PhaseX·xxx]` 前綴，改為乾淨格式 |
| Git tags 建立 | 每個 commit 標上對應任務的 annotated tag，tag 名稱直接取自 daily_guide_v2.html 任務名 |
| key_word.md 新建 | 人類可讀的關鍵字速查文件（update / git / 繼續），每次 update 同步 |
| Commit Tag 對照表 | 加入 readme.md，列出 Phase1~Phase4 所有已實作任務的 tag 對照 |
| `git` 關鍵字升級 | 新增步驟：①主動讀 HTML 判斷是否完成任務並建議 tag ②檢查近期 commit 是否有應合併的，兩個判斷都等使用者確認才執行 |
| `_get_with_retry` 恢復 | BaseScraper 加回 `_get_with_retry` 實例方法（委派給 module-level `get_with_retry()`）；ptt / cnyes / reddit / arctic_shift 四支爬蟲全部改回 `self._get_with_retry()`，多餘的 import 移除 |
| `schema.py` 追蹤標的標註 | `stock_prices` 和 `us_stock_prices` 的 DDL 前加上 SQL comment，說明各自追蹤 0050（元大台灣50）和 VOO（Vanguard S&P 500 ETF） |
| PTT pipeline 啟動 | PID 61194，爬 10000 頁，背景執行中 |
| Arctic Shift pipeline | PID 95637，背景執行中（6 subreddits 歷史資料） |
| code review bug fix | `visualization.py` import `TWSE_STOCK_NAME` 但 config.py 未定義 → 補上 `TWSE_STOCK_NO` 和 `TWSE_STOCK_NAME`；`pydantic` 未列入 requirements.txt → 補上 |

#### 學到的概念

- **`git tag` vs commit message prefix**：tag 是獨立的 git ref，指向某個 commit；`[PhaseX·xxx]` 只是 message 文字，兩者完全不同
- **`git tag -a`**：annotated tag，有獨立的 tag 物件（含訊息、時間戳），比 lightweight tag 更完整
- **`git push origin :refs/tags/tagname`**：刪除遠端 tag（`:` 前為空代表推送「空」覆蓋遠端）
- **`git tag --points-at <hash>`**：列出某個 commit 上的所有 tag
- **git tag 唯一性**：同一個 tag 名稱只能指向一個 commit；需要移動 tag 時要先 `git tag -d` 再重建
- **純 docs commit 不應單獨存在**：沒有完成任何任務 → 無法加 tag → 應與下一個有意義的 commit 合併後再 push
- **`git commit-tree`**：低階指令，直接建立 commit 物件（tree + parent + message），不依賴 working tree 狀態，適合腳本化 history rewrite
- `_get_with_retry` 作為實例方法存在的原因：BaseScraper 子類別用 `self._get_with_retry()` 是 OOP 慣例，也讓子類別未來可以覆寫 retry 行為；module-level `get_with_retry()` 則給不繼承 BaseScraper 的類別（如 `tw_stock_fetcher`）直接 import 使用
- SQL comment 寫法：`-- 這是 SQL 單行 comment`，可寫在 DDL 字串裡，`psycopg2` 執行時不影響
- config.py 邊界原則補充：像 `TWSE_STOCK_NAME` 這類圖表顯示用的常數，雖然只有 visualization 用，但來源是 config 追蹤的標的，應放 config 而非 hardcoded 在 visualization

#### Architecture note

- `base_scraper.py`：module-level `get_with_retry()` → `BaseScraper._get_with_retry()` 委派它
- 四支爬蟲（ptt / cnyes / reddit / arctic_shift）：`self._get_with_retry()`
- `tw_stock_fetcher.py`：直接 `from scrapers.base_scraper import get_with_retry`（不繼承 BaseScraper）

#### 完成項目（code review 2026-04-04）

| 項目 | 說明 |
|------|------|
| `reddit_batch_loader.py` 修正 | 移除 `"title": title or url` fallback，改為 `"title": title`，讓 ArticleSchema 的 `title_not_empty` validator 正確攔截空 title；reddit_scraper.py 同步修正 |
| `sys.argv` 說明 | `reddit_batch_loader.py` `__main__` 加上 `sys.argv[0/1/2]` 說明註解 |

#### 學到的概念（code review 2026-04-04）

- `title or url` 反模式：讓 fallback 繞過 schema 驗證，問題資料悄悄存進 DB；正確做法是讓 ArticleSchema validator 攔截並 log warning
- `push_count = max(-100, min(100, score))`：clamp 把 Reddit 無上限 score 壓進 -100~100，與 PTT push_count 欄位設計保持一致；ArticleSchema 的 `push_count_in_range` validator 作為第二道防線
- `post.get("score", 0) or 0`：雙重保護，`.get("score", 0)` 處理 key 不存在，`or 0` 處理 key 存在但值為 `None`（JSON null）
- `sys.argv`：`argv[0]` = 腳本名稱，`argv[1]`、`argv[2]` = 使用者傳入的命令列參數；`len(sys.argv) == 3` 表示使用者傳了兩個日期參數（補抓指定區間用）

#### 下次繼續

- [ ] `41cd8ad`（純 docs commit）下次有新 commit 時合併進去
- [x] `reddit_batch_loader.py` title fallback 移除（`title or url` 反模式）
- [ ] PTT pipeline 跑完後確認 article count
- [ ] Arctic Shift 跑完後重跑（new no-keyword config）
- [ ] Run `UsStockFetcher().run()` 填入 VOO 資料（us_stock_prices 目前為空，QA 會 FAIL）
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：BERT 情緒分析實作（bert_sentiment.py，config.py 框架已就位）
- [ ] Phase 5：資料倉儲（星型 schema）
- [ ] Phase 6：Airflow、Kafka、Kubernetes

---

### 2026-04-04（下午）

#### 完成項目

| 項目 | 說明 |
|------|------|
| 多來源 ETL 整合 | pipeline.py 改用 `concurrent.futures.ThreadPoolExecutor` 並行爬取，ETL 三階段明確分層（`extract()` / `transform()`），新增來源只需在 `_ALL_SOURCES` 加一行 |
| Bug fix：`str\|None` Python 3.9 不相容 | `Optional[X] → X\|None` 語法只支援 3.10+，導致 cnyes scraper 靜默失敗 0 篇；修復 5 個檔案改回 `Optional[X]` |
| `update` 關鍵字升級 | 新增第一步：讀最新 log 掃 ERROR/WARNING/Traceback，有問題先修 |
| git 關鍵字升級 | 每次 push 前審查所有 unpushed commits，判斷是否 soft reset 合併（目標每筆都有 tag）|

#### 學到的概念

- **`str | None` 是 Python 3.10+ 語法（PEP 604）**：Python 3.9 執行 `str | None` 會 `TypeError: unsupported operand type(s) for |`，Pydantic 在 class 定義時就會觸發，導致整個模組 import 失敗
- **`Optional[X]` vs `X | None`**：功能等價，`Optional[X]` 是 `Union[X, None]` 的縮寫，適用 3.9；`X | None` 更簡潔但只限 3.10+
- **爬蟲靜默失敗的危險性**：import 失敗不會 raise 到 pipeline 層（因為 `except requests.RequestException` 只抓網路錯誤），導致 0 篇但沒有 ERROR log，只靠 DB 筆數才能發現
- **`concurrent.futures.ThreadPoolExecutor`**：I/O bound 任務用 thread（等 HTTP response），比 ProcessPoolExecutor 啟動快；`as_completed()` 拿到最先完成的 future，適合多來源並行

#### 下次繼續

- [ ] `41cd8ad`（純 docs commit）下次有新 commit 時合併進去
- [ ] cnyes 實際跑一次確認資料寫入
- [ ] Phase 4：Star Schema / Data Warehouse
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] Phase 5：BERT 情緒分析

---

### 2026-04-05

#### 完成項目（2026-04-05 上午）

| 項目 | 說明 |
|------|------|
| `reddit_scraper.py` 重構 | `_PAGE_LIMIT = 100` 常數化；walrus operator 改為 explicit for loop；`consecutive_dup_pages` → `consecutive_empty_pages` |
| `us_stock_fetcher.py` 重構 | `iterrows` + `get_loc` 改用 `shift(1)` 向量化計算 change；補上 `import pandas as pd` |

#### 學到的概念（2026-04-05 上午）

- `shift(1)`：把整欄往下移一格，自動對齊前一天；第一筆變 NaN；取代逐列計算前後差的迴圈
- `iterrows()`：逐列遍歷 DataFrame，每次給 `(idx, row)`；`idx` 是 index（縱軸），`row["欄位"]` 是橫向取值
- `NaN` vs `None`：NaN 是 pandas/numpy 的缺失值（特殊浮點數）；None 是 Python 空值；psycopg2 只認識 None，看到 None 自動轉 DB NULL，NaN 會報錯
- `pd.isna()`：判斷是否為 NaN，配合三元運算子轉成 None 再存 DB
- `items()`：DataFrame 逐欄遍歷（對應 iterrows 的逐列），實務上少用，直接 `df["欄位"]` 更常見
- magic number 原則：API 硬性上限（如 Reddit `_PAGE_LIMIT = 100`）應定義為模組級常數，加註說明不可超過的原因

#### 完成項目（2026-04-05 下午）

| 項目 | 說明 |
|------|------|
| Git 清理 | main 推送完成（f742d45 Phase4·Pydantic驗證）；`big_data_etl` worktree + branch + remote 全部刪除；`Phase4·多來源ETL` tag 砍掉（指向錯誤 commit）；claude/ 殘留 branch 清除 |
| `pipeline.py` 升級 | ThreadPoolExecutor 並行版本修正上線：修正 import 路徑（`tw_stock_fetcher`）、補上 `RedditScraper` + `UsStockFetcher`、tqdm 改為 logging |
| `base_scraper.py` bug fix | `_get_or_create_source` 改為 INSERT ON CONFLICT DO NOTHING → SELECT 模式，解決 ThreadPoolExecutor 並行時 race condition |
| `base_scraper.py` bug fix | `raise e` → `raise`，保留完整 traceback |
| `cnyes_scraper.py` fix | title 加 `.strip()`，與其他來源保持一致 |
| `requirements.txt` fix | 移除重複的 `pydantic` 條目 |
| pipeline 啟動 | PID 24096，PTT 10000 頁爬取中；Arctic Shift PID 95637 歷史載入中 |

#### 學到的概念（2026-04-05 下午）

- `git worktree`：branch 被 worktree 使用時無法直接砍，需先 `git worktree remove` 再 `git branch -D`
- `git branch -a` 的 `+` 前綴：代表該 branch 是某個 worktree 的 checked-out branch
- `git worktree prune`：清除已不存在目錄的 worktree 紀錄（prunable 狀態）
- `git fsck --unreachable | grep commit`：找回已 drop 的 stash 或被 reset 蓋掉的 commit（git GC 前都還在）
- `ON CONFLICT DO NOTHING RETURNING`：INSERT 成功時回傳 row，衝突時不 raise 只是靜默跳過、RETURNING 為空；需搭配 fallback SELECT 才能取到已存在的 id
- `raise e` vs `raise`：`raise e` 會重置 traceback 起點（看起來 exception 從這裡發生）；`raise` 保留完整 traceback（真正的錯誤位置）；99% 情況用 `raise`
- ThreadPoolExecutor race condition：多個 thread 同時通過 SELECT 判斷「不存在」→ 同時 INSERT → 第二個 INSERT 觸發 unique constraint；解法是讓 DB 自己處理（ON CONFLICT），而非在 application 層做 TOCTOU 判斷

#### 下次繼續

#### 完成項目（2026-04-05 下午）

| 項目 | 說明 |
|------|------|
| `dw_schema.py` 新建 | Star Schema DDL：`dim_source`（含 tracked_stock）/ `fact_sentiment`（含直接 DATE 欄位 fact_date，stock_symbol denormalized）+ Materialized View（`mv_daily_summary` / `mv_hot_stocks`）|
| `dw_etl.py` 新建 | OLTP → DW incremental ETL；`source_name` denormalize 進 fact；`run_etl(do_cluster=True)` 支援 CLUSTER |
| Snowflake 延伸 | 新增 `dim_market`（TW / US）；`dim_source` 加 FK `market_id`；支援三層 JOIN：`fact → dim_source → dim_market` |
| `bert_sentiment.py` 新建 | BERT fine-tune + evaluate（F1 / Confusion Matrix）+ predict + 批次推論入庫（zero-shot fallback） |
| BERT 批次推論啟動 | PID 23436，190k 篇文章推論中，結果寫入 `sentiment_scores` |
| Claude Code 權限設定 | `~/.claude/settings.json`：`Bash(*)` 萬用字元 allow + `PermissionRequest` hook 自動 approve（見下方「Claude Code 設定」）|

#### Claude Code 權限設定（解決一直跳 prompt 的問題）

**問題**：GUI 每次執行工具都跳 permission confirm prompt。
**根因**：project 層 `settings.local.json` 有舊的 allow 白名單，蓋掉 global 設定；且 `bypassPermissions` 需要 `allowDangerouslySkipPermissions: true` + GUI 不支援 `bypassPermissions`。
**解法**：三個設定檔都改成以下格式：

```json
{
  "permissions": {
    "allow": [
      "Bash(*)", "Read(*)", "Edit(*)", "Write(*)", "Glob(*)", "Grep(*)",
      "WebFetch(*)", "WebSearch(*)"
    ]
  },
  "hooks": {
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PermissionRequest\",\"decision\":{\"behavior\":\"allow\"}}}'"
          }
        ]
      }
    ]
  }
}
```

套用位置：
- `~/.claude/settings.json`（global）
- `Data_engineer/.claude/settings.local.json`（project）
- `Data_engineer/project/.claude/settings.local.json`（sub-project）

**重要**：每次修改設定檔後需 Cmd+Q 重啟 Claude Code GUI 才生效。`PermissionRequest` hook 是攔截 prompt 最可靠的方式。

#### 完成項目（2026-04-05 延續 session）

| 項目 | 說明 |
|------|------|
| `datalake.py` 新建 | S3 Data Lake 三層架構：raw(JSON) / processed(Parquet) / curated(聚合 Parquet) |
| `mongo_helper.py` 新建 | MongoDB Docker 本機，`raw_articles` collection，`sync_from_pg()` PG→MongoDB 同步 |
| `stock_matcher.py`（原 `ner.py`）新建 | 股票代號比對：regex 抓代號 + 最長匹配抓公司名稱；`stock_mentions` + `match_done` 表；`run_matcher()` 取代原 `run_ner()` |
| `labeling_tool.py` 新建 | Streamlit 標注工具，供人工標注情緒（正/中/負）後 fine-tune BERT |
| Data Mart 實作 | `data_mart.py` 新建 + `dw_schema.py` 加入 `mart_daily_summary` / `mart_hot_stocks` table + partial index |
| Materialized View 移除 | `mv_daily_summary` / `mv_hot_stocks` 移除，改用 Data Mart table（更貼近業界 104 JD 用語，可跨 DB 移植） |
| `dw_etl.py` 更新 | `refresh_views()` 移除，改呼叫 `data_mart.refresh_all()`（TRUNCATE + INSERT） |
| `backtest.py` 新建 | 回測系統：yfinance 抓 0050/VOO 歷史股價 → 情緒 vs 隔日漲跌 → RandomForest Walk-Forward Validation → 累積報酬曲線（後於 2026-04-10 rename 為 `ai_model_prediction.py`） |
| `fetch_etf_holdings.py` 新建 | TW 50 支（TWSE API）+ US 503 支（Wikipedia S&P 500） |
| `stock_dict.json` 更新 | TW 50 支、US 503 支，供 NER 使用 |
| Spark 移除 | `spark_analysis.py` 刪除、`pyspark` 從 requirements.txt 移除（待上完課再實作） |
| `lxml` 安裝 | `pd.read_html` 所需，加入 conda env |

#### 設計決策

- **Data Mart vs Materialized View**：選 Data Mart table。MV 是 PostgreSQL 特有物件（`REFRESH MATERIALIZED VIEW`）；Data Mart 是標準 table（`TRUNCATE + INSERT`），可跨 DB 移植。104 JD 都用「Data Mart」而非「MV」，因為 Data Mart 是架構概念（DW 的子集，針對部門/用途），MV 只是實作技術。
- **Partial index**：`idx_hot` partial index 已從 `mart_hot_stocks` 移除（資料量不足以受益）。
- **stock_dict.json 範圍**：用戶要求 TW 只保留 0050 的 50 支持股、US 只保留 S&P 500（VOO），不做全上市股票。

#### 下次繼續

- [ ] BERT 推論完成後重跑 `dw_etl.py`，讓 `avg_sentiment` 從 NULL 填入實際值
- [ ] 啟動 labeling_tool（`streamlit run labeling_tool.py`）標注 500 篇，再 fine-tune BERT
- [ ] `Phase4·多來源ETL` tag 等 pipeline.py ThreadPoolExecutor 確認無誤後重打
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] **Google Looker Studio 儀表板**（looker_export.py 已完成，CSV 已匯出）：
  - 把 `looker_output/` 下三個 CSV 上傳 Google Sheets
  - 開 https://lookerstudio.google.com 建立報表
  - 四個圖表：情緒折線圖 / 文章數長條圖 / 熱門文章表格 / 來源圓餅圖
  - 取得分享連結放進 readme
- [ ] Phase 5 剩餘：Spark/PySpark（待上完課再做）
- [ ] Phase 6：Airflow、Kafka、Kubernetes

---

### 2026-04-05（延續 session 2 — context recovery）

#### 完成項目

| 項目 | 說明 |
|------|------|
| `reparse.py` 新建 | 完整資料修復管線：diagnose() 掃 PG → 分類來源 → MongoDB raw re-parse → UPDATE PG |
| `pipeline.py` 整合 repair | transform() 的 QA 失敗時自動呼叫 `repair()`，修復後重跑 QA，仍失敗才 pipeline 中止 |
| `mongo_helper.py` 升級 | 新增 `raw_responses` collection + `save_raw_response()` + `get_raw_response()` + `count_raw_responses()` |
| `base_scraper.py` 原始存檔 | `_archive_raw()` 每次 HTTP 成功後自動存入 MongoDB raw_responses，降級設計（`_MONGO_OK` flag） |
| `config.py` ARTICLE_LABELS_TABLE | 新增 `ARTICLE_LABELS_TABLE = "article_labels"`，bert_sentiment / labeling_tool / schema 同步改用 |
| `looker_export.py` 新建 | 匯出三份 CSV（daily_sentiment / hot_articles / source_stats）+ optional gspread 上傳 |
| launchd 改為每小時 | 移除 `Hour` key，只留 `Minute=25`，每小時 :25 分執行 |
| `diagnose()` BSON 修復 | `$in` 查詢超過 16MB 上限 → 改為分批查詢（每批 500 URL） |
| 三份文件更新 | CLAUDE.md / readme.md / project_notes.md 同步更新 |

#### 學到的概念

- **MongoDB raw_responses 的價值**：存 HTTP 原文而非解析後的資料，parser bug 修完後直接 re-parse，不需重新爬取
- **Graceful Degradation 模式**：`_MONGO_OK` flag + try/except，附加功能掛掉不影響主流程
- **BSON 16MB 限制**：MongoDB 單個 document（含查詢 command）不能超過 16MB，`$in` 大量 URL 時必須分批
- **pipeline 自動修復設計**：QA 失敗 → catch → repair → 重跑 QA → 仍失敗才真正中止
- **UPDATE 只更新非 None 欄位**：避免 re-parse 拿不到的欄位覆蓋 DB 已有的好值

#### 下次繼續

- [ ] BERT 推論完成後重跑 `dw_etl.py`，讓 `avg_sentiment` 從 NULL 填入實際值
- [ ] 啟動 labeling_tool（`streamlit run labeling_tool.py`）標注 500 篇，再 fine-tune BERT
- [ ] `Phase4·多來源ETL` tag 等 pipeline.py ThreadPoolExecutor 確認無誤後重打
- [ ] PII masking（author hash 化）
- [ ] JWT Authentication
- [ ] **Google Looker Studio 儀表板**（looker_export.py 已完成，CSV 已匯出）
- [ ] Phase 6：Kubernetes、Prometheus、Grafana、Docker Compose、Airflow

#### ⚠️ PTT 專案完成後提醒

**開一個 BTC Pipeline 練習以下技能**（PTT 專案資料量不足，無法有效練習）：

| 技能 | PTT 做不到的原因 | BTC Pipeline 怎麼練 |
|------|------------------|---------------------|
| Spark + PySpark | 600k rows，JVM 啟動 overhead > 實際計算 | 用公開大資料集（NYC Taxi 10GB+）跑 Databricks Community |
| Hadoop / Hive / HDFS | 100MB 資料放單機就好 | Docker Hadoop cluster + Hive 查詢 HDFS |
| Spark ML Pipeline | 需要大量資料才能展現優勢 | 與 Spark 同一個 BTC Pipeline |
| Kafka Streaming | PTT 無即時串流來源 | 模擬即時資料源 → Kafka → Consumer → DB |
| Partition Strategy | 600k rows 分區沒有可測量的效能提升 | 大資料集 + PostgreSQL Range Partition |
| Data Lake (S3) | 已用 MongoDB raw_responses 取代 | 搭配 Spark 練 S3 raw → processed → curated 三層 |

---

### 2026-04-08

#### 完成項目

| 項目 | 說明 |
|------|------|
| Database 改名 | `ptt_stock` → `stock_analysis_db`（PostgreSQL ALTER DATABASE + .env + config/schema/backup/mongo_helper 預設值同步）|
| source_name 統一 | SOURCES dict name 從 "PTT Stock"/"鉅亨網"/"Reddit Finance" 改成 "ptt"/"cnyes"/"reddit"，與 dict key 一致 |
| config.py 局部性重構 | 15+ 只有單一模組用的常數搬回各自檔案（PTT_SCRAPE_SLEEP→ptt_scraper、REDIS_HOST→cache_helper 等）|
| schema.py 角色權限註解 | CREATE_ROLES SQL 每行加上中文註解（pg_roles、IF NOT EXISTS、GRANT 三層權限、SEQUENCE、REVOKE 防禦）|
| schema.py 變數直讀 | api_user/api_pw/etl_user/etl_pw 從 `PG_API_CONFIG["user"]` 改為 `os.environ.get()` 直讀，移除間接層 |
| backup.py 直讀 .env | 移除 `from config import PG_CONFIG`，改為 `os.environ.get()` 直接讀取 DB 連線參數 |
| MongoDB 清理 | 移除 raw_articles collection 及相關程式碼（mongo_helper/base_scraper），只保留 raw_responses |
| `_archive_raw` → `_store_raw` | base_scraper 方法重命名，區分 `_store_raw`（準備參數）vs `save_raw_response`（實際寫入 MongoDB）|
| `_source_key` 移除 | 四支爬蟲的 `_source_key` class variable 移除，`_store_raw` 改用 `self.get_source_info().get("name")` |
| test_api.py 修正 | 加 `app.dependency_overrides[verify_token]` bypass JWT + `get_pg` → `get_pg_readonly`，13 tests passing |
| auth.py 加註解 | verify_token 函式加中文註解：token 擷取、jwt.decode 三功能、JWTError 涵蓋範圍 |
| looker_export.py 清理 | 移除未使用的 `from datetime import date` |
| project_notes.md 更新 | config 邊界 + Markdown 預覽 + GRANT/REVOKE 權限層級 + SEQUENCE 說明 |

#### 學到的概念

- **PostgreSQL 三層權限**：`CONNECT`（連線）→ `USAGE`（看到 table）→ `SELECT`（讀資料），每層獨立，缺一不可
- **USAGE vs SELECT 成對**：USAGE = 進入 schema，SELECT = 讀資料；只給其中一個都會 permission denied
- **SEQUENCE 權限**：`USAGE` 允許 `nextval()`（INSERT 產生 ID），`SELECT` 允許 `currval()`（讀回剛才的 ID）
- **`pg_roles`**：PostgreSQL 內建系統表，裝好就有，不用自己建
- **`CREATE ROLE ... LOGIN`**：建帳號 + 允許登入，沒加 `LOGIN` 的角色連不進 DB
- **`DO $$ ... END $$`**：PostgreSQL 匿名程式區塊，讓 SQL 可以用 IF/THEN 邏輯
- **DDL 不能用 `%s`**：`CREATE ROLE`、`GRANT` 的 identifier（角色名）不能用 `%s`（會加引號），只能用 `.format()`
- **`ALTER DEFAULT PRIVILEGES`**：對未來新建的 table 自動授權，否則新表沒權限
- **REVOKE 防禦性設計**：明確收回 api_user 寫入權限，防止有人誤下 `GRANT ALL`
- **`ALTER DATABASE RENAME`**：DB 改名需無人連線，改完後 `.env` 同步即可，程式碼透過 `os.environ.get()` 自動讀到新名稱
- **config 間接層簡化**：`PG_API_CONFIG["user"]` 套兩層不如 `os.environ.get("PG_API_USER")` 直讀一層
- **`app.dependency_overrides[verify_token]`**：FastAPI 內建 dict，key 放函式物件，value 放替代 callable，測試時跳過 JWT

#### 下次繼續

- [ ] 恢復 `reparse.py`（已刪且 untracked，需重寫）
- [ ] 恢復 `test_reparse.py`（同上）
- [ ] PII masking（pii_masking.py 未執行）
- [ ] BERT sentiment_scores 表仍為空
- [ ] 每日 Mock Interview（完整面試格式，非只專案）
- [ ] Phase 6：Airflow、Kafka、Kubernetes

---

