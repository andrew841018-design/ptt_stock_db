# PTT 情緒分析專案 — 重點整理

> 以這個專案為主軸，記錄設計決策、踩過的坑、效能問題與解法

---

## 一、Schema 設計

### SQLite（舊）的問題
- `Push_count` 存成 TEXT，導致排序和計算要額外轉型
- `Published_Time`、`Article_Sentiment_Score` 是後來 `ALTER TABLE` 加進去的，不在原始建表語法裡
- **造成的問題**：新環境跑 `Create_DB.py` 建出的 DB 缺欄位，API 直接 KeyError

**教訓**：欄位一開始就要設計好放進建表語法，不要靠 ALTER TABLE 補丁

### PostgreSQL（新）的改進
- `push_count` 改為 `INTEGER`，`published_at` 改為 `TIMESTAMP`
- `sentiment_scores` 獨立成一張表，用 `target_type`（"article" / "comment"）統一管理
  - 好處：未來換 BERT 模型只要新增一筆，schema 不用改
- 4 張表：`sources` / `articles` / `comments` / `sentiment_scores`

---

## 二、Index 設計

### 為什麼需要 Index
查詢沒有 index 時，DB 會做全表掃描（Seq Scan），資料量大時非常慢。

### 本專案建立的 4 個 Index（全是 B-tree）

| Index | 欄位 | 用途 |
|-------|------|------|
| `idx_articles_published_at` | `published_at` | 範圍查詢「某段時間的文章」|
| `idx_articles_source_id` | `source_id` | 等值查詢「特定來源」|
| `idx_comments_article_id` | `article_id` | JOIN articles 加速 |
| `idx_sentiment_target` | `(target_type, target_id)` | Composite，同時過濾兩欄 |

### 各類型 Index 選型原則

| 類型 | 適用場景 | 本專案狀況 |
|------|---------|-----------|
| B-tree | 預設，等值＋範圍查詢 | 全部用這個 |
| Hash | 只做等值查詢 | 不需要，B-tree 夠用 |
| Composite | 常同時過濾多欄位 | `idx_sentiment_target` |
| Partial | 只查部分資料（分佈不均）| 未來 `push_count > 100` 可考慮 |
| Full-text (GIN) | 文字搜尋 | 未來 `/articles/search` 資料量大後需要 |
| Clustered | 大量資料＋少寫入＋範圍查詢 | Phase 5 的 Fact Table 適合 |

### Index 的代價
- 加快讀取，但**拖慢寫入**（每次 INSERT/UPDATE 都要更新 index）
- 本專案 articles 每天新增資料 → B-tree 合適，不用 Clustered
- 用 `EXPLAIN ANALYZE` 看是 `Index Scan` 還是 `Seq Scan` 來驗證效果
- 用 `pg_stat_user_indexes` 找從未被使用的 index 刪掉

---

## 三、效能問題

### 查詢慢的常見原因（由淺到深）

1. **沒有 index** → 全表掃描，資料量大時直接爆
2. **Index 選錯類型** → 例如範圍查詢用 Hash，完全沒用
3. **Composite index 欄位順序錯** → 最左前綴原則，篩選力強的欄位要放左邊
4. **SELECT \*** → 拉太多不需要的欄位，浪費 I/O
5. **N+1 query** → 迴圈裡每次都查一次 DB，應改成批次 JOIN
6. **缺少 LIMIT** → 一次回傳全部資料
7. **沒有 Connection Pool** → 每次 API 請求都建立新連線，overhead 大

### 本專案的效能問題
- `analysis.py` 每次跑都嘗試 `ALTER TABLE` 加已存在的欄位 → Column already exist ERROR
  - **解法**：加 `IF NOT EXISTS` 判斷，或一開始就寫進建表語法
- API 沒有 Redis 快取（Phase 4 待做）→ 每次請求都打 DB
  - **解法**：Cache-Aside Pattern，TTL 1小時

---

## 四、路徑問題（踩了很多次）

### 相對路徑 vs 絕對路徑
- **問題根源**：Python script 的相對路徑是以「執行時的工作目錄」為基準，不是以「檔案位置」為基準
- **標準解法**：
  ```python
  import os
  BASE_DIR = os.path.dirname(__file__)
  DICT_PATH = os.path.join(BASE_DIR, 'user_dict.txt')
  ```

### uvicorn vs streamlit 路徑格式不同
- `uvicorn`：用 Python import 格式（**點號**）→ `uvicorn test_code.api:app`
- `streamlit`：用檔案路徑格式（**斜線**）→ `streamlit run dependent_code/visualization.py`

### cd 的副作用
- shell script 裡 `cd` 會改變整個 script 的工作目錄，影響後續所有指令
- **解法**：用 `bash -c '...'` 子 shell 隔離，不影響主 script
  ```bash
  setsid nohup bash -c 'cd /path/to/dir && streamlit run ...' > /dev/null 2>&1 &
  ```

### cron / launchd 的路徑問題
- cron / launchd 的工作目錄預設是 `/`，`dirname "$0"` 算出來的 PROJECT_DIR 會錯
- **解法**：script 裡硬編碼 `PROJECT_DIR`，不靠動態計算

---

## 五、CI/CD 部署問題

### SSH Session Timeout
- **問題**：uvicorn / streamlit 啟動後持續輸出 log，SSH session 不結束，CI/CD 超時
- **解法**：三個手段合用
  ```bash
  setsid nohup uvicorn ... > /dev/null 2>&1 &
  ```
  - `setsid`：建立新 session，SSH 斷線不影響
  - `> /dev/null 2>&1`：丟掉所有輸出
  - `command_timeout: 30s`：設短 timeout

### pytest 在 CI/CD 沒有真實 DB
- **問題**：GitHub Actions 沒有 `ptt_stock.db`，API 測試直接炸
- **解法**：`unittest.mock.patch` 注入假資料
  ```python
  with patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()):
      with patch("api.get_db_connection", return_value=MagicMock()):
  ```

### SSH Key 格式問題
- GitHub Secret 要貼完整 PEM 內容，包含頭尾 `-----BEGIN/END RSA PRIVATE KEY-----`

---

## 六、重構原則（實際應用）

### config.py — 集中管理常數
- 把 DB_PATH、TABLE 名稱、SKIP_KEYWORDS 等全部移到 `config.py`
- SQL 語法裡用常數取代 hardcoded 字串，改表名只要改一個地方

### db_helper.py — Context Manager 管理連線
```python
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()  # 不管有沒有 exception 都會關
```
- 解決 connection leak 問題

### Lazy Load — sentiment.py
- 詞庫只在第一次呼叫 `calculate_sentiment()` 時才載入
- 避免 import 時就佔用記憶體

### 循環 import 的解法
- `data_cleanner.py` import `analysis.py`，`analysis.py` 又 import `data_cleanner.py` → 循環 import
- **解法**：把共用函式移到正確的模組，讓依賴方向單向

---

## 七、macOS 自動排程

### cron 在 macOS Sequoia 的問題
- `launchctl load com.vix.cron.plist` 失敗（Input/output error）
- 系統限制，cron daemon 無法在新版 macOS 啟動

### 改用 launchd（Apple 官方推薦）
- plist 放在 `~/Library/LaunchAgents/`，用 `launchctl load` 載入
- 排錯過程：
  1. **第一個錯誤**：`Operation not permitted` → launchd 無法存取 Desktop（TCC 限制）
     - 解法：把 script 複製到 `~/scripts/`，Desktop 路徑不再被存取
  2. **第二個錯誤**：`line 7: root: command not found` + log 路徑變成 `/logs/...`
     - 原因：launchd 預設 CWD 是 `/`，`dirname "$0"` 算出 `.`，`cd ./..` 得到 `/`，PROJECT_DIR 變空
     - 解法：script 裡硬編碼 `PROJECT_DIR="/Users/andrew/Desktop/..."`，不靠動態計算
- plist 設定範例：
  ```xml
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/andrew/scripts/run_etl.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>10</integer>
    <key>Minute</key><integer>25</integer>
  </dict>
  ```

---

## 八、資料品質

### Great Expectations
- 驗證欄位型別、值範圍、非空值等
- cron 環境下 import 路徑要用 try/except 同時支援本地和 `/tmp` 環境

### Incremental Loading
- 爬蟲用 URL 做 UNIQUE 去重，已存在的文章跳過
- 避免每次全量重爬、重複寫入

---

*最後更新：2026-03-25（下午）*
