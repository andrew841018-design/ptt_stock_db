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
- `sentiment_scores` 獨立成一張表，每篇文章對應一筆（article_id FK UNIQUE）
  - 移除了 `target_type` / `target_id`（原 Polymorphic Association 設計），改用直接 FK 更簡單
  - 好處：未來換 BERT 模型只要更新 score 欄位，schema 不用改
- 6 張表：`sources` / `articles` / `comments` / `sentiment_scores` / `stock_prices` / `us_stock_prices`
- `stock_prices`：只追蹤 0050 一支股票，只留 trade_date / close / change，UNIQUE 在 `trade_date`
- `us_stock_prices`：只追蹤 VOO 一支 ETF，結構與 stock_prices 相同，資料來源為 yfinance

---

## 二、Index 設計

### 為什麼需要 Index
查詢沒有 index 時，DB 會做全表掃描（Seq Scan），資料量大時非常慢。

### 本專案建立的 6 個 Index（全是 B-tree）

| Index | 欄位 | 用途 |
|-------|------|------|
| `idx_articles_published_at` | `published_at` | 範圍查詢「某段時間的文章」|
| `idx_articles_source_id` | `source_id` | 等值查詢「特定來源」|
| `idx_comments_article_id` | `article_id` | JOIN articles 加速 |
| `idx_sentiment_article_id` | `article_id` | 情緒分數 JOIN articles 加速 |
| `idx_stock_prices_trade_date` | `trade_date` | 0050 股價日期範圍查詢 |
| `idx_us_stock_prices_trade_date` | `trade_date` | VOO 股價日期範圍查詢 |

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
- API Redis 快取已實作（2026-04-01）→ Cache-Aside Pattern，TTL 24小時（86400 秒）
  - 第一次請求（Cache MISS）：4.11s；第二次（Cache HIT）：0.11s，提升 37 倍

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

### QA.py — Pipeline 內建資料品質檢查

Data Engineering 的 QA ≠ 手動點按鈕，而是在 pipeline 裡埋自動檢查點：

| 檢查項目 | SQL | assert 條件 |
|---------|-----|------------|
| 無重複 URL | `GROUP BY url HAVING COUNT(*) > 1` | `not duplicate_urls` |
| 無孤兒推文 | `WHERE article_id NOT IN (SELECT article_id FROM articles)` | `orphan_count == 0` |
| articles 不為空 | `SELECT COUNT(*) FROM articles` | `article_count > 0` |

**assert vs warning 的差別：**
- `logging.warning` — 資料有問題，pipeline 繼續跑 → 錯誤資料進下游
- `assert` — 資料有問題，拋 `AssertionError` 中止 → 強迫處理

**QA.py 架構：**
```python
def QA_checks():        # ← 被 pipeline.py import 呼叫
    ...

if __name__ == "__main__":  # ← 也可以單獨 python QA.py 執行
    QA_checks()
```

### HAVING vs WHERE

```sql
-- WHERE：分組前過濾原始資料
SELECT url FROM articles WHERE push_count > 10

-- HAVING：分組後過濾聚合結果
SELECT url, COUNT(*) FROM articles GROUP BY url HAVING COUNT(*) > 1
```

`HAVING` 只能用在有 `GROUP BY` 的查詢，用來過濾 `COUNT`、`SUM` 等聚合函式的結果。

### fetchone vs fetchall

```python
cursor.execute("SELECT COUNT(*) FROM articles")
cursor.fetchone()     # → (42,)      單個 tuple
cursor.fetchone()[0]  # → 42         取第一個欄位值

cursor.execute("SELECT url, COUNT(*) FROM articles GROUP BY url HAVING COUNT(*) > 1")
cursor.fetchall()     # → [("https://...", 2), ("https://...", 3)]   list of tuples
                      # 無結果時 → []
```

### assert 語法

```python
# 正確：assert 是關鍵字，不是函式
assert orphan_count == 0, f"孤兒推文 {orphan_count} 筆"

# 陷阱：加括號變成 tuple，永遠是 truthy，永遠不會 fail
assert(orphan_count == 0, "孤兒推文")  # ← 永遠通過！
```

---

## 九、Logging

### logging vs print

| | print | logging |
|---|---|---|
| 輸出格式 | 只有訊息本身 | 時間 + 等級 + 訊息 |
| 等級控制 | 無 | DEBUG / INFO / WARNING / ERROR |
| 適合場景 | 快速測試 | 正式程式碼 |

### basicConfig — 設定怎麼印

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
```

| 佔位符 | 輸出內容 |
|--------|---------|
| `%(asctime)s` | 時間戳記，格式：`2026-03-26 10:00:00,毫秒` |
| `%(levelname)s` | `INFO` / `WARNING` / `ERROR` |
| `%(name)s` | logger 名稱（需手動加入 format 才會印出） |
| `%(message)s` | `logger.info("這裡的內容")` |

### getLogger — 設定誰來印

```python
logger = logging.getLogger(__name__)
```

- `__name__` = 當前檔案的模組名稱（e.g. `migrate.py` → `"migrate"`）
- 幫這個模組的 log 在系統內部標記名字
- 兩個實際用途：
  1. 在 format 加 `%(name)s`，印出是哪個模組發出的訊息
  2. 針對單一模組單獨設定等級：`logging.getLogger("migrate").setLevel(logging.ERROR)`
- `basicConfig` 是全域設定；`getLogger` 讓你針對單一模組獨立設定
- 目前專案用不到，但是業界標準寫法，預留彈性

### 分工

```
logger.info("開始遷移")    ← 你決定印什麼內容
basicConfig(format=...)    ← 決定格式長什麼樣
```

### f-string vs 佔位符

```python
# f-string
logging.info(f"第 {expensive_function()} 筆")
# 執行順序：expensive_function() 先跑 → 組合字串 → 判斷等級，不印就丟掉

# 佔位符
logging.info("第 %s 筆", expensive_function())
# 執行順序：先判斷等級 → 等級不夠就直接停，expensive_function() 完全不跑
```

> f-string 是「做了再決定印不印」，佔位符是「先決定印不印，不印就什麼都不做」。

- 實際好處：針對 `DEBUG` 等級，上線後改成 `INFO`，佔位符連字串都不組合，省效能
- 目前專案只用 INFO / WARNING / ERROR，沒有 DEBUG，兩種寫法沒有實質差別

### .env 與環境變數的陷阱

```bash
# .env 裡空值會覆蓋 os.environ.get() 的預設值
PG_HOST=        # ← 讀進來是空字串 ""，不是 None
PG_PORT=        # ← os.environ.get("PG_HOST", "localhost") 拿到 ""，不是 "localhost"
```

- `os.environ.get("KEY", "default")` 只有在找**不到**這個 KEY 時才用預設值
- `.env` 裡設了空值 = 找得到，但值是 `""`，預設值完全不起作用
- psycopg2 拿到空字串的 `host`，改走 Unix socket（`/tmp/.s.PGSQL.5432`），連線失敗

**解法**：`.env` 裡要嘛填入正確值，要嘛直接刪掉該行：
```bash
PG_HOST=localhost   # ✅ 填入值
PG_PORT=5432        # ✅ 填入值
# 或直接刪掉這兩行，讓 os.environ.get() 用預設值
```

### rollback + raise 模式

```python
except psycopg2.Error as e:
    logging.error("Failed: %s", e)
    if conn:
        conn.rollback()  # 撤銷這次所有操作，資料庫回到操作前的狀態
    raise                # 把例外往上拋，讓呼叫者知道出錯了
```

- `rollback`：確保資料庫乾淨，不留半殘的表或髒資料
- `raise`：確保你看到錯誤訊息，知道哪裡出問題
- 結果：什麼都沒做，但知道錯在哪 → 像交易沒完成就取消

---

---

## 十、Exception 處理模式

### raise vs try/except

```
raise     → 製造 / 往上傳遞例外
try/except → 接住例外
```

### 分層處理原則

```
底層函式    → raise（我不管，往上丟）
中層函式    → except + 處理 + raise（rollback 等，但還是往上丟）
最上層      → except + logging（收尾，不再 raise）
```

專案範例：
```
scrape_article()   → raise
pg_helper.get_pg() → rollback + raise
pipeline.py        → logging.error → 程式結束
```

最上層不 raise 的原因：再拋就是 unhandled exception，Python 直接印 traceback 死掉，不如自己用 logging 收尾乾淨。

### str(e) vs raise

```python
# str(e) — 只記錄訊息，繼續執行（錯誤是預期內的）
except Exception as e:
    logging.error(f"爬取失敗：{str(e)}")

# raise — 往上拋，中止執行（錯誤是嚴重的）
except Exception as e:
    conn.rollback()
    raise
```

---

---

## 十二、Redis 快取（Cache-Aside Pattern）

### 為什麼需要快取
每次 API 請求都打 DB，DB 是磁碟 I/O，速度慢（本專案測到 4.11s）。Redis 是 in-memory key-value store，同樣的資料第二次只要 0.11s（37 倍提升）。

### Cache-Aside Pattern（旁路快取）

```
API 收到請求
  ↓
先查 Redis（get_cache）
  ├─ HIT  → 直接回傳（不打 DB）
  └─ MISS → 查 DB → 存進 Redis（set_cache）→ 回傳
```

由「應用層」控制快取，Redis 不主動同步，DB 是唯一的資料來源（source of truth）。

### 本專案實作

| 檔案 | 改動 |
|------|------|
| `cache_helper.py` | `get_cache(key)` / `set_cache(key, df, ttl)`；含 `RedisError` 保護，Redis 掛掉不影響 API |
| `api.py` | `load_articles_df()` 改用 Cache-Aside |
| `config.py` | 新增 `REDIS_HOST` / `REDIS_PORT` / `REDIS_TTL`（86400 = 24小時）|
| `requirements.txt` | 補上 `redis` |

### 關鍵概念

**TTL（Time To Live）**
```python
r.setex(key, ttl, value)   # SET + EXpire 合一，到期 Redis 自動刪除
```

**`orient='table'` 保留 dtype**
```python
# 序列化（存入 Redis）
df.to_json(orient='table')      # 保留 int/float/datetime 型別資訊

# 反序列化（從 Redis 讀出）
pd.read_json(StringIO(cached), orient='table')  # 正確還原型別
```
不用 `orient='table'` 的話：int 欄位可能變 float，datetime 欄位可能變 str。

**`StringIO` — 字串變 file-like object**
```python
from io import StringIO
pd.read_json(StringIO(json_string))  # pd.read_json 需要 file-like object
```

**RedisError 保護**
```python
try:
    cached = r.get(key)
except redis.RedisError:
    return None   # Redis 掛掉就當作 MISS，繼續查 DB
```
Redis 是快取不是資料庫，掛掉應降級（fallback）到 DB，不應讓 API 整個死掉。

### 測試策略

| 測試 | 說明 |
|------|------|
| `test_cache_hit` | Redis 有資料 → `get_cache` 直接回傳，DB 不被呼叫 |
| `test_cache_miss` | Redis 沒資料 → 查 DB → `set_cache` 被呼叫 |
| `test_cache_redis_down` | `get_cache` 拋 RedisError → 降級查 DB，API 正常回傳 |
| `test_set_and_get_cache` | 真實 Redis 存取驗證（需 Redis 服務在線）|

**patch 命名空間原則**
```python
# 要 patch「使用者的命名空間」，不是「定義者的命名空間」
patch("api.get_cache")        # ✅ api.py 裡的 get_cache
patch("cache_helper.get_cache")  # ✗ api.py 不認得這個名字
```

**平行 patch 語法（Python 3.x）**
```python
# 平行（推薦，較清楚）
with patch("api.get_cache", ...), patch("api.set_cache", ...):
    ...

# 嵌套（效果相同，縮排多）
with patch("api.get_cache", ...):
    with patch("api.set_cache", ...):
        ...
```

**`side_effect` vs `return_value`**
```python
mock.return_value = None          # 每次呼叫都回傳 None
mock.side_effect = RedisError()   # 呼叫時拋出例外
mock.side_effect = lambda k: ...  # 呼叫時執行自訂函式
```

### Docker 基礎設施

```bash
# 啟動 Redis 容器
docker run -d --name redis_cache -p 6379:6379 --restart=always redis:7

# 設為開機自動啟動（需搭配 Docker Desktop 開機啟動）
docker update --restart=always redis_cache
```

**GitHub Actions CI/CD（deploy.yml）**
```yaml
services:
  redis:
    image: redis:7
    ports:
      - 6379:6379
```
讓 CI/CD 環境也能跑需要真實 Redis 的測試。

*最後更新：2026-04-03*

---

---

## 十九、Pydantic 資料驗證

### 三個驗證層，互不重疊

```
爬蟲                         DB                         使用者
  │                           │                           │
  ▼                           ▼                           ▼
scraper_schemas.py       QA.py / GE          api.py response model
（資料進來前）           （資料進 DB 後）      （資料出去前）
```

| 層 | 位置 | 時間點 | 驗證什麼 |
|---|---|---|---|
| 爬蟲入庫前 | `scraper_schemas.py` | 爬到 → DB | 格式對不對（title 非空、url regex、push_count 範圍）|
| DB 入庫後 | `QA.py` / `ge_validation.py` | DB 存進去後 | 資料品質（無重複 URL、無孤兒推文、NULL 檢查）|
| API 回傳前 | `api.py` response model | DB 讀出 → 回傳 | 回傳格式對不對、過濾多餘欄位 |

三層目的不同，不重疊。

### scraper_schemas.py — 爬蟲入庫驗證

```python
class ArticleSchema(BaseModel):
    title:        str
    url:          str
    push_count:   int | None
    published_at: datetime
    ...

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, title):
        if not title.strip():
            raise ValueError("title cannot be empty")
        return title
```

使用方式：
```python
try:
    ArticleSchema(**article)   # 驗證通過才回傳
except Exception as e:
    logging.warning(f"驗證失敗，略過：{e}")
    return None
```

驗證失敗 `return None` 而非 `raise`，讓 for loop 跳過這篇繼續爬下一篇。

### 哪些欄位需要 validator？原則說明

| 欄位 | DB 能擋嗎？ | 為什麼需要 Pydantic validator |
|------|------------|-------------------------------|
| `title` | ❌ `NOT NULL` 擋不住空字串 `""` | `title_not_empty`：`title.strip()` 不為空才算有效 |
| `url` | ❌ 只有型別，不驗格式 | `url_must_be_valid`：確保是 `https?://` 開頭，格式正確 |
| `push_count` | ❌ 無 CHECK constraint | `push_count_in_range`：確保 -100 ≤ n ≤ 100，與 PTT 規格一致 |
| `published_at` | ❌ TIMESTAMP 不會拒絕未來時間 | `published_at_not_future`：爬蟲解析錯誤時間時能被抓到 |
| `content` | ✅ NOT NULL 已足夠 | 不需要額外 validator |
| `author` | ✅ 允許 NULL，型別對就好 | 不需要額外 validator |
| `comments` | ✅ 空 list 合法，逐筆由 CommentSchema 驗 | 不需要額外 validator |

原則：**DB 的 NOT NULL / 型別約束擋不住的東西（空字串、格式、範圍、未來時間），才需要 Pydantic validator 補上。**

### API Response Models

每個 endpoint 對應一個 model：

| Endpoint | Model |
|----------|-------|
| `/sentiments/today` | `TodaySentimentResponse` |
| `/sentiments/change` | `ChangeSentimentResponse` |
| `/sentiments/recent` | `RecentSentimentResponse` |
| `/articles/top_push` | `TopPushResponse` + `TopPushArticleItem` |
| `/articles/search` | `SearchResponse` + `SearchArticleItem` |
| `/correlation/0050` | `SentimentVsStockPriceResponse` + `SentimentVsStockPriceItem` |
| `/health` | `HealthResponse` |

### 關鍵概念

**`response_model=` 做三件事**
1. 型別驗證（回傳錯誤型別會被抓到）
2. 過濾多餘欄位（防止 DB 內部欄位外洩）
3. 自動產生 Swagger 文件

**`list[X]` vs `list`**
- `list` = 裡面可以裝任何東西，Pydantic 不管
- `list[X]` = 裡面每個元素都要符合 X，逐一驗證

**`@field_validator("欄位名")`**
- 告訴 Pydantic「這個函式負責驗證這個欄位」
- 不加裝飾器 = 普通 classmethod，建立 model 時不會觸發
- `@classmethod` 是 Pydantic v2 規定，`cls` 固定在第一個參數但實際用不到

**動態 key 的問題**
```python
# 避免這樣：key 隨參數變動，Pydantic 無法靜態定義 model
return {f"recent_{period}_days_sentiment_score": score}

# 改為固定 key：
return {"period": period, "sentiment_score": score}
```

### 常見 Bug 紀錄

**shared DataFrame in-place mutation**
```python
# 危險：df 來自快取，in-place 改動會污染後續所有呼叫
df['Published_Time'] = df['Published_Time'].dt.date

# 正確：先 copy 再改
df = df.copy()
df['Published_Time'] = df['Published_Time'].dt.date
```
快取物件是共享的，不 copy 就直接改，所有用到同一物件的地方都會看到被改過的版本。

**PTT X 前綴推文數計算錯誤**
```python
# 錯誤：X1 → -1
return -int(text[1:])

# 正確：X1 → -10（PTT 規格：X1=10 噓，X9=90 噓）
return -int(text[1:]) * 10
```

**dict 直接 key 存取 vs .get()**
```python
item["publishAt"]        # publishAt 缺失 → KeyError，繞過上層 try/except
item.get("publishAt")    # 缺失 → None，可以加 early return 優雅處理
```
在爬蟲 article dict 建構期間拋出的例外，不在 ArticleSchema(**article) 的 try/except 範圍內，會向上傳播。

---

## 十八、資料品質設計原則（QA）

### Schema 層 vs Application 層的分工

| 層 | 工具 | 負責範圍 |
|---|---|---|
| Schema 層 | `NOT NULL`、`UNIQUE`、`FK` | DB 強制，任何來源都不能繞過 |
| Application 層 | `QA.py` | 跨表邏輯、來源專屬規則、數量檢查 |

兩層互補：Schema 負責「欄位層級」的硬約束，QA 負責「業務邏輯層級」的軟檢查。

### 哪些欄位該 NOT NULL

判斷原則：**沒有這個值，這筆資料有沒有意義？**

| 表 | NOT NULL 欄位 | 允許 NULL 欄位 |
|---|---|---|
| articles | title、content、url、published_at、source_id | author、push_count |
| comments | user_id、push_tag、message、article_id | — |
| sentiment_scores | score、article_id | — |
| stock_prices | trade_date | open、high、low、close、change |

### 來源專屬檢查

不同來源對同一欄位有不同規範，透過 JOIN sources 表篩出來單獨檢查：

```python
cursor.execute(f"""
    SELECT COUNT(*) FROM articles a
    JOIN sources s ON s.source_id = a.source_id
    WHERE s.source_name = 'PTT Stock' AND a.push_count IS NULL
""")
```

### published_at 單位一致性

| 來源 | 格式 | 轉換方式 |
|---|---|---|
| PTT | Unix timestamp（秒），從 URL 抽取 | `datetime.fromtimestamp(int(...))` |
| 鉅亨網 | Unix timestamp（秒），API `publishAt` 欄位 | `datetime.fromtimestamp(item["publishAt"])` |

兩個來源單位相同，存進 DB 都是 `TIMESTAMP`，不需要額外轉換。

---

## 十三、遷移腳本（SQLite → PostgreSQL）

### 為什麼需要遷移腳本

SQLite 是單機輕量 DB，適合開發期快速迭代。PostgreSQL 支援多連線、更嚴謹的型別、FK 約束、Index 優化，適合正式環境。遷移腳本把歷史資料從 SQLite 搬進 PostgreSQL 的正規化 Schema。

### 核心挑戰

**1. id 不連續問題**
SQLite `Article_id` 是自增的，PostgreSQL `article_id`（SERIAL）從 1 開始獨立計算。兩邊 id 不同，留言的 `article_id` FK 會對不上。

**解法**：建立 `id_map: Dict[sqlite_id, pg_id]`，用 URL 當橋梁：
```python
# 插入文章後用 RETURNING 拿到 PG article_id
INSERT INTO articles (...) VALUES (...) ON CONFLICT (url) DO NOTHING RETURNING article_id
# 已存在就用 url 查
SELECT article_id FROM articles WHERE url = %s
```

**2. 型別轉換**
```python
def _to_int(value) -> int:
    try: return int(value)       # "27" → 27
    except: return 0             # 意外值 → 0，不中斷遷移

def _to_ts(value) -> Optional[datetime]:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")  # TEXT → TIMESTAMP
```

**3. 記憶體管理（140 萬筆留言）**
```python
# 不要 fetchall()，改用 fetchmany() 分批讀
while True:
    rows = sqlite_cur.fetchmany(BATCH_SIZE)  # 每次 5000 筆
    if not rows: break
    # 處理並寫入...
```

**4. batch 內 dedup**
同一篇文章可能有多則內容相同的推文（e.g. 很多人推「好」），用 `(push_tag, message)` 找 PG comment_id 時會命中同一筆，導致 batch 裡有重複的 `(target_type, target_id, method)`，ON CONFLICT DO UPDATE 報 CardinalityViolation。

```python
# dict comprehension 去重：相同 key 只保留最後一個 value
deduped = list({(t, tid, m): (t, tid, m, s) for t, tid, m, s in batch}.values())
```

### 冪等設計

遷移腳本可安全重複執行：
```python
pg_cur.execute("SELECT COUNT(*) FROM articles")
if pg_cur.fetchone()[0] == 0:
    # 第一次跑：插入文章 + 留言
else:
    # 已有資料：只重建 id_map，不重複插入
    id_map = _build_id_map_from_pg(sqlite_cur, pg_cur)
```

`sentiment_scores` 用 `ON CONFLICT DO UPDATE`，重跑會更新分數而非重複插入。

### 最終遷移結果

| 表 | 筆數 |
|---|---|
| sources | 1 |
| articles | 30,395 |
| comments | 4,492,615 |
| sentiment_scores | 3,100,896 |

---

## 十四、情緒分析加權設計（push_tag_bonus）

### 設計

```python
_PUSH_TAG_BONUS = {"推": 0.3, "噓": -0.3}
score = max(-1.0, min(1.0, text_score + tag_bonus))  # clamp [-1, 1]
```

### 為什麼是 0.3

**老實說：沒有統計依據，是 heuristic。**

設計邏輯：
- 推/噓是明確的情緒訊號，應影響分數
- 但不能讓推噓完全主導文字分析（所以不用 0.5 或 1.0）
- 0.3 ≈ 整體範圍的 30%，「有影響但不主導」

**面試標準回答：**
> 「0.3 是初步的 heuristic，嚴謹做法應該用標注資料集跑不同加權值的實驗來找最佳值，這是這個專案還沒做到的改進方向。」

---

## 十七、抽象類別（ABC）與 @abstractmethod

### base class 同時有兩種方法

父類別不是純框架，而是**規格 + 共用實作**並存：

| 方法 | 類型 | 誰來實作 |
|------|------|---------|
| `get_source_info()` | `@abstractmethod` | 每個子類別自己寫 |
| `fetch_articles()` | `@abstractmethod` | 每個子類別自己寫 |
| `_load_urls()` | 一般方法 | BaseScraper 寫好，子類別繼承直接用 |
| `_save_to_db()` | 一般方法 | BaseScraper 寫好，子類別繼承直接用 |
| `_get_with_retry()` | 一般方法 | BaseScraper 寫好，子類別繼承直接用 |

`BaseScraper` 定義「要有什麼、回傳什麼格式」，子類別填入「實際怎麼做」：

```
BaseScraper（框架 + 共用邏輯）
  ├── 你必須告訴我來源資訊     → get_source_info()   ← @abstractmethod，空殼
  ├── 你必須告訴我怎麼爬文章   → fetch_articles()    ← @abstractmethod，空殼
  └── 存進 DB 我來處理         → run() / _save_to_db() / _insert_*  ← 有實作

PttScraper（實作）
  ├── get_source_info()  → {'name': 'PTT Stock', 'url': '...'}
  └── fetch_articles()   → requests + BeautifulSoup 解析 PTT HTML
```

### @abstractmethod 的空殼永遠不會被執行

```python
@abstractmethod
def fetch_articles(self) -> list:
    """..."""   # 這裡的內容永遠不跑
```

`PttScraper().run()` 呼叫 `self.fetch_articles()` 時，Python 直接跳到 `PttScraper.fetch_articles()`，base 的空殼完全略過。

### Python 在 import 時就掃描 class 結構

不用執行任何方法，import 時 Python 就已讀完所有 class 定義：

```
import PttScraper
    ↓
Python 掃描：PttScraper 繼承 BaseScraper
    ↓
檢查所有 @abstractmethod 是否都被實作
    ↓
有 → 登記完畢，可以建立物件
沒有 → 標記「不完整」，建立物件時報錯
```

```python
class PttScraper(BaseScraper):
    pass  # 沒有實作 fetch_articles

scraper = PttScraper()  # TypeError: Can't instantiate abstract class
```

### class 子類別(父類別) — 繼承語法

```python
class PttScraper(BaseScraper):
```

括號裡放父類別，代表：
1. **擁有**父類別所有方法（`run()` / `_save_to_db()` 等不用重寫）
2. **必須實作**父類別的所有 `@abstractmethod`，否則建立物件時報錯

沒有括號就是普通 class，跟 BaseScraper 完全無關，什麼都要自己從頭寫。

### config.py 的邊界

**放進 config 的**：整個專案都可能用到的常數（DB 設定、table 名稱、TWSE 設定、Redis、S3）

**不放 config 的**：只有單一模組使用的常數（api.py 的查詢範圍限制、visualization 的 UI 設定）

---

### 新增來源規範（強制）

1. **HTTP 請求一律用 `self._get_with_retry()`**，禁止直接用 `requests.get()`
2. **無該欄位明確填 `None`**，不靠 `.get('key', 預設值)` 猜測

```python
class NewScraper(BaseScraper):
    def fetch_articles(self):
        response = self._get_with_retry(url)   # ✅ 有 retry
        # response = requests.get(url)         # ❌ 禁止
        return [{
            'title':      '...',
            'push_count': None,   # ✅ 無此欄位明確填 None
            'comments':   [],     # ✅ 無留言明確填空 list
        }]
```

### 擴充新來源只需加子類別

DB 寫入邏輯全在 base，新增來源只要建新子類別實作兩個方法，其餘不用動：

```python
class NewScraper(BaseScraper):
    def get_source_info(self): ...
    def fetch_articles(self): ...
# run() / _save_to_db() / _insert_* 全部繼承，不用重寫
```

---

## 十五、GROUP BY 規則與 Subquery 模式

### 問題：非聚合欄位必須全部放進 GROUP BY

PostgreSQL 規定：SELECT 裡出現的每個欄位，若沒有被聚合函式包住（AVG/SUM/COUNT/MAX/MIN），就必須出現在 GROUP BY 子句。

```sql
-- ❌ 錯誤：score 是聚合欄位，但 close、change 不是
SELECT DATE(published_at), AVG(score), close, change
FROM articles a
JOIN sentiment_scores s ON ...
JOIN stock_prices sp ON ...
GROUP BY DATE(published_at)    -- close、change 沒放進來 → 報錯
```

### AVG 只是「怎麼壓」，GROUP BY 才是「按什麼切」

`avg_sentiment` 是壓縮**之後**的結果，GROUP BY 就是壓縮的動作本身。

```sql
-- 沒有 GROUP BY：把全部文章（不分日期）全壓成一個數字，只回傳一列
SELECT DATE(published_at), AVG(score)
FROM articles a JOIN sentiment_scores s ON ...

-- 加上 GROUP BY：按日期分組，每組各算一個平均，每天一列
SELECT DATE(published_at), AVG(score)
FROM articles a JOIN sentiment_scores s ON ...
GROUP BY DATE(published_at)
```

### GROUP BY 只看 SELECT，不看整個 table

> 你先決定 SELECT 要哪些欄位 → 哪些用了聚合函式 → 剩下的全部放 GROUP BY

跟 table 有多少欄位無關，只看你 SELECT 裡寫了什麼。

```sql
SELECT
    DATE(published_at),   -- 沒有聚合函式 → 放 GROUP BY
    AVG(score)            -- 有聚合函式   → 不放 GROUP BY
FROM ...
GROUP BY DATE(published_at)
-- table 裡還有 title、author、url... 全部不管，因為 SELECT 沒選它們
```

### 聚合 vs 非聚合的判斷

- **判斷範圍**：只看 SELECT 裡出現的欄位，不是整個 table
- **聚合欄位**：SELECT 裡被 AVG/SUM/COUNT/MAX/MIN 包住的欄位 → 不放 GROUP BY
- **非聚合欄位**：SELECT 裡沒有被聚合函式包住的欄位 → 全部放 GROUP BY

### 解法：Subquery 模式

在 subquery 裡先做聚合（只 GROUP BY 真正的 key），外層再 JOIN 其他表拿剩下的欄位：

```sql
SELECT sub.sentiment_date, sub.avg_sentiment, sp.close, sp.change
FROM (
    SELECT
        DATE(a.published_at) AS sentiment_date,
        AVG(s.score)         AS avg_sentiment
    FROM articles a
    JOIN sentiment_scores s ON s.article_id = a.article_id
    GROUP BY DATE(a.published_at)   -- 只有一個 key，乾淨
) sub
JOIN stock_prices sp
    ON sp.trade_date = sub.sentiment_date + INTERVAL '1 day'
ORDER BY sub.sentiment_date
```

- 內層 subquery：只做 articles × sentiment_scores 的聚合，GROUP BY 只放 DATE(published_at)
- 外層：把聚合結果當成一張暫時表，JOIN stock_prices 拿 close、change
- `+ INTERVAL '1 day'`：PTT 情緒是當日，股價是隔日，JOIN 時做日期偏移

### 為什麼不在外層加更多 GROUP BY

```sql
-- 技術上能通過，但語義錯誤
GROUP BY DATE(published_at), close, change
-- 同一天如果有多個 close 值（不同股票），就會分成多組
-- 現在只有 0050 一支，所以不會出錯；但一旦多股就爆
```

Subquery 模式才是正確架構：讓聚合和 JOIN 分開，各自只做自己該做的事。

---

## 十六、KeyBERT 關鍵字抽取

### 為什麼換掉 regex 斷詞

regex 只能做字面切分（e.g. 按標點符號切），沒有語意理解，常抓到無意義詞。KeyBERT 用 BERT 的語意向量，選出和整段文字語意最相近的詞組，品質高很多。

### 使用方式

```python
from keybert import KeyBERT

@st.cache_resource     # 模型是重量級物件，整個 app 只建立一次
def _kw_model():
    return KeyBERT()

text     = ' '.join(df['Title'].tolist())           # 所有標題串成一段文字
keywords = _kw_model().extract_keywords(
    text,
    keyphrase_ngram_range=(1, 2),   # 抽 1~2 個字的詞組
    top_n=20                        # 回傳前 20 個關鍵詞
)
# keywords = [("台積電", 0.82), ("股價上漲", 0.79), ...]
top_20_words = pd.DataFrame(keywords, columns=['Word', 'Score'])
```

### @st.cache_resource vs @st.cache_data

| 裝飾器 | 用於 | 特點 |
|--------|------|------|
| `@st.cache_resource` | 模型、DB 連線等重量級物件 | 整個 app session 只建立一份，所有使用者共用 |
| `@st.cache_data` | DataFrame、JSON 等資料 | 每個不同的輸入參數各快取一份 |

---

## 十一、Shell 輸出重導向

### Linux 三個預設 file descriptor

| 數字 | 名稱   | 說明           |
|------|--------|----------------|
| `0`  | stdin  | 標準輸入（鍵盤）|
| `1`  | stdout | 標準輸出（正常結果）|
| `2`  | stderr | 標準錯誤（錯誤訊息）|

### `> /dev/null 2>&1 &` 拆解

```bash
> /dev/null    # stdout → 黑洞
2>&1           # stderr → 跟 stdout 同一個地方（也就是黑洞）
&              # 背景執行
```

- `&1` 裡的 `&` = 「這是 fd 編號，不是檔名」；若寫 `2>1` 會建立名為 `1` 的檔案
- 為什麼不直接 `2>/dev/null`：可以，但 `2>&1` 只需寫一次目的地，改目的地時只改一處
- 為什麼 `nohup` 還需要 `> /dev/null 2>&1`：`nohup` 只處理 SIGHUP，stdout/stderr 若沒重導向仍掛在 SSH session，SSH 斷線時 process 可能被 kill

### `pkill -f` vs `kill $(lsof -t -i:PORT)`

```bash
# 用 port 找（舊版）
kill $(lsof -t -i:8000) 2>/dev/null   # port 沒有 process 時 lsof 回傳空，kill 報錯

# 用程式名稱找（新版）
pkill -f "uvicorn api:app" || true    # 找不到時 || true 讓 exit code = 0，script 不中斷
```

---

## 十七、Great Expectations 進階用法

### `mostly` 參數

`mostly` 是 GE expectation 的容忍比例，值域 0.0～1.0。

```python
# 允許最多 1% 的值不符合規則（99% 符合就算 PASS）
ge_voo.expect_column_values_to_be_between('change', -100, 100, mostly=0.99)
```

使用時機：資料有**已知且合理的例外**時。
- `change` 欄位的第一筆必定是 NULL（沒有前一日收盤價），嚴格 `mostly=1.0` 會讓 pipeline 每次都 FAIL
- `mostly=0.99` 讓這個極少數 NULL 不影響整體驗證

不用 `mostly`：`title`、`url`、`trade_date` 這類絕對不能有 NULL 的欄位，直接用 `expect_column_values_to_not_be_null()`（等同 `mostly=1.0`）

---

## 十八、API 特殊行為：HTTP 200 with Error Body

Arctic Shift API 注意事項：
- 第三方 Reddit 歷史存檔服務，非 Reddit 官方 API
- 錯誤格式特殊：永遠回 HTTP 200，錯誤訊息塞在 JSON body 內，需自行檢查 data.get("error")，HTTP retry 攔不到這類錯誤

### 問題

多數 API 遇到錯誤會回傳 4xx/5xx，`raise_for_status()` 可以捕捉。
但部分第三方 API（如 **Arctic Shift**）即使參數錯誤，仍回傳 HTTP 200，錯誤在 body 裡：

```json
{"data": null, "error": "'sort' must be one of asc, desc"}
```

### 問題所在

```python
response.raise_for_status()     # HTTP 200 → 不 raise，程式繼續跑
posts = data.get("data") or []  # None → [] → 以為「無資料」，靜默結束
```
結果：爬蟲正常跑完，但一篇都沒拿到，沒有任何 ERROR log。

### 解法

```python
data  = response.json()
error = data.get("error")
if error:
    logging.warning(f"API 錯誤：{error}，停止")
    break
```

**先讀 body，再判斷 error 欄位**，不能只靠 HTTP status code。

### 教訓

遇到第三方 API 時，先看文件確認錯誤回傳格式，不要假設錯誤一定是 4xx/5xx。

---

## 十九、`_get_with_retry` 架構設計

### 為什麼同時有 module-level 函式和實例方法

```
base_scraper.py
  ├── def get_with_retry(url, **kwargs)          ← module-level，供任何地方 import
  └── class BaseScraper
        └── def _get_with_retry(self, url, **kwargs)  ← 實例方法，委派給上面那個
```

**module-level `get_with_retry()`**：給不繼承 BaseScraper 的類別直接 import 使用。
```python
# tw_stock_fetcher.py（不繼承 BaseScraper，股價不是文章）
from scrapers.base_scraper import get_with_retry
response = get_with_retry(url, params=params)
```

**`BaseScraper._get_with_retry(self, ...)`**：給子類別用 `self._get_with_retry()` 呼叫。
```python
# ptt_scraper.py（繼承 BaseScraper）
response = self._get_with_retry(url, headers=self.HEADERS)
```

### 為什麼子類別要用 `self._get_with_retry()` 而不直接 import

1. **OOP 慣例**：子類別用 `self.method()` 呼叫父類別方法，是繼承的標準寫法
2. **可覆寫性**：子類別未來可以 override `_get_with_retry()` 加入自訂邏輯（e.g. 特定來源的 header 處理）
3. **語意清晰**：`self._get_with_retry()` 表示「我用自己的 retry 方法」，不是任意全域函式

### SQL comment 寫法

```python
CREATE_STOCK_PRICES = """
-- 追蹤標的：0050（元大台灣50）
CREATE TABLE IF NOT EXISTS stock_prices (
    ...
);
-- 追蹤標的：VOO（Vanguard S&P 500 ETF）
CREATE TABLE IF NOT EXISTS us_stock_prices (
    ...
);
"""
```

`--` 是 SQL 單行 comment，可直接寫在 DDL 字串裡，`psycopg2.execute()` 執行時完全忽略，不影響建表。

---

## 二十、Schema Validator 作為唯一驗證點

### Fallback 反模式

在把資料傳給 schema validator 之前加 fallback，會讓 validator 失去意義：

```python
# ❌ 反模式：title or url 繞過 validator
article = {
    "title": title or url,   # title 空時改用 url 頂替，validator 收到非空字串，不會攔截
    ...
}
ArticleSchema(**article)     # title_not_empty 永遠不會觸發

# ✅ 正確做法：直接傳，讓 validator 決定
article = {
    "title": title,          # title 空 → validator 攔截 → logging.warning → return None
    ...
}
ArticleSchema(**article)
```

### 設計原則

**Validator 應該是唯一的資料品質把關點**，不要在上游加 fallback 繞過它。

理由：
- `title or url` 讓空 title 的貼文悄悄存進 DB，標題變成 URL，難以察覺
- schema validator 的存在就是為了攔截壞資料，fallback 讓它形同虛設
- 一旦有 fallback，QA.py 的 `title IS NOT NULL` 檢查也會誤以為資料乾淨

### 具體案例：Reddit `push_count` 的多重保護

```python
# score 欄位的雙重保護
score = post.get("score", 0) or 0
# .get("score", 0)：key 不存在 → 0
# or 0：key 存在但值是 None（JSON null）→ 0

# clamp 把無上限的 Reddit score 壓進 -100~100
push_count = max(-100, min(100, score))

# ArticleSchema.push_count_in_range 作為第二道防線
ArticleSchema(**article)  # 若 clamp 邏輯有 bug，validator 兜底
```

`max(-100, min(100, score))` 是標準 clamp 寫法：先 `min` 設上限，再 `max` 設下限。

---

## 二十一、`sys.argv` — CLI 腳本的命令列參數

### 基本結構

```python
import sys

# python3 script.py 2022-01-01 2023-12-31
# sys.argv[0] = "script.py"       ← 腳本名稱，永遠存在
# sys.argv[1] = "2022-01-01"      ← 第一個使用者參數
# sys.argv[2] = "2023-12-31"      ← 第二個使用者參數
# len(sys.argv) = 3
```

### 典型用法（reddit_batch_loader.py）

```python
if __name__ == "__main__":
    # sys.argv[0] = 腳本名稱，argv[1] = after 日期，argv[2] = before 日期
    if len(sys.argv) == 3:
        after_dt  = datetime.strptime(sys.argv[1], "%Y-%m-%d")
        before_dt = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    else:
        # 使用者沒傳參數，用預設值
        before_dt = datetime.utcnow()
        after_dt  = datetime.strptime(REDDIT_BATCH_HISTORY_START, "%Y-%m-%d")
```

### `len(sys.argv) == 3` 的含義

腳本名稱永遠佔 `argv[0]`，所以「使用者傳了兩個參數」對應的是 `len == 3`，不是 `len == 2`。

| 執行指令 | `len(sys.argv)` | 說明 |
|---------|----------------|------|
| `python3 script.py` | 1 | 沒有使用者參數 |
| `python3 script.py 2022-01-01` | 2 | 一個使用者參數 |
| `python3 script.py 2022-01-01 2023-12-31` | 3 | 兩個使用者參數（補抓指定區間）|

## 二十二、pandas 向量化 vs iterrows

### iterrows() 的結構

把 DataFrame 逐列切開：
- `idx` = 那一列的 index（縱軸，如日期）
- `row` = 那一列所有欄位的值（可用 `row["欄位"]` 橫向取值）

```python
for idx, row in hist.iterrows():
    val = row["Close"]  # 橫向取欄位
```

### shift(1) 取代逐列計算

計算每日漲跌：
```python
# 舊寫法（iterrows + get_loc，繁瑣）
loc = hist.index.get_loc(idx)
prev_close = closes.iloc[loc - 1] if loc > 0 else None
change = round(float(row["Close"]) - float(prev_close), 2) if prev_close else None

# 新寫法（向量化，一行）
hist["change"] = (hist["Close"] - hist["Close"].shift(1)).round(2)
```

`shift(1)` 把整欄往下移一格，第一筆自動是 NaN（無前一天），其餘每格自動對齊前一天。

### NaN vs None

| | NaN | None |
|---|---|---|
| 來源 | pandas/numpy | Python |
| 意義 | 缺失的浮點數 | 空值 |
| DB | psycopg2 不認識，會報錯 | 自動轉 NULL |

處理方式：
```python
float(row["change"]) if not pd.isna(row["change"]) else None
```

---

## 二十三、Git Workflow 設計

### git tag vs commit message prefix

| | commit message prefix | git annotated tag |
|---|---|---|
| 位置 | 訊息文字 | 獨立 git ref 物件 |
| 查詢 | `git log --oneline` | `git tag -l` |
| GitHub 顯示 | commit 列表 | Tags 頁面 / commit 旁標記 |
| 唯一性 | 可重複 | 全 repo 唯一，只能指向一個 commit |
| 推薦用途 | 描述改動脈絡 | 標記任務完成里程碑 |

**本專案規範**：commit message 不加前綴，改用 annotated tag 標記對應的任務名稱（直接取自 daily_guide_v2.html）。

### git tag 操作

```bash
# 建立 annotated tag
git tag -a "Phase3·FastAPI" <hash> -m "Phase3·FastAPI"

# 刪除本地 tag
git tag -d "Phase3·FastAPI"

# 刪除遠端 tag（: 前空白 = 推送空內容覆蓋遠端）
git push origin :refs/tags/Phase3·FastAPI

# 查看某 commit 上的所有 tag
git tag --points-at <hash>

# 推送所有 tag
git push origin --tags
```

### 什麼時候不加 tag

- 純文件修改（md / CLAUDE.md / key_word.md）
- bug fix 不對應任何 daily_guide 任務
- 多個 commit 共同完成一個任務（只在最後一個加 tag）

### 純 docs commit 的處理原則

純文件 commit 不應單獨存在：無法對應任何任務 → 無法加 tag → 造成 history 出現無意義的孤立節點。

**正確做法**：等下一個有實質改動的 commit 一起 push，用 soft reset 合併後再 push。

### git history rewrite 技術（無 -i 旗標）

```python
# 逐一重建 commit（保留原始 tree、author、timestamp）
new_hash = subprocess.run(
    ['git', 'commit-tree', tree, '-p', parent, '-m', new_msg],
    env={**os.environ, 'GIT_AUTHOR_DATE': original_date, ...}
)
# 更新 branch 指向
subprocess.run(['git', 'update-ref', 'refs/heads/main', new_hash])
subprocess.run(['git', 'reset', '--hard', new_hash])
```

- squash：跳過舊 commit，用新 commit 的 tree，parent 接到舊 commit 的 parent
- force push 後遠端同步更新

---

## 二十四、Python 版本相容性陷阱

### `X | None` vs `Optional[X]`

| 語法 | 支援版本 | 說明 |
|------|----------|------|
| `Optional[X]` | Python 3.5+ | `from typing import Optional`；`Union[X, None]` 縮寫 |
| `X \| None` | Python 3.10+ | PEP 604，更簡潔但不向下相容 |

**危險情境**：在 Python 3.9 環境用了 `str | None`，在 Pydantic model class 定義時立即觸發 `TypeError`，導致整個模組 import 失敗。

```python
# Python 3.9 會在 class 定義時炸掉：
class ArticleSchema(BaseModel):
    author: str | None  # TypeError: unsupported operand type(s) for |

# 正確寫法（3.9 相容）：
from typing import Optional
class ArticleSchema(BaseModel):
    author: Optional[str]  # OK
```

**靜默失敗的危險性**：import 失敗不會被 `except requests.RequestException` 捕捉，pipeline 繼續跑但爬蟲回傳 0 篇，log 只有 INFO 沒有 ERROR，只靠 DB 筆數才能發現。

### `concurrent.futures` 並行爬蟲

```python
# I/O bound → ThreadPoolExecutor（等 HTTP，不消耗 CPU）
with concurrent.futures.ThreadPoolExecutor() as executor:
    futures = {executor.submit(_run_source, cls): cls.__name__ for cls in _ALL_SOURCES}
    for future in concurrent.futures.as_completed(futures):
        name = futures[future]
        try:
            future.result()  # 若子執行緒 raise，這裡會重新 raise
        except Exception as e:
            logging.error(f"[Extract] 失敗：{name} — {e}")
```

- `as_completed()`：哪個先跑完先處理，不按送入順序
- `future.result()`：取得回傳值，若有 exception 會重新 raise 到主執行緒
- 每個來源獨立 thread，DB 連線在各自的 `_save_to_db()` 內，`pg_helper` context manager 是 thread-safe（`psycopg2` 每次建立獨立連線）

*最後更新：2026-04-05*

---

## 二十五、並行 DB 寫入 Race Condition

### TOCTOU（Time-Of-Check-Time-Of-Use）問題

原本 `_get_or_create_source` 的流程：

```python
# 問題版：SELECT 然後 INSERT，中間有時間差
cursor.execute("SELECT source_id FROM sources WHERE url = %s", (url,))
if not cursor.fetchone():
    cursor.execute("INSERT INTO sources ...")  # 兩個 thread 都通過 SELECT → 都 INSERT → 第二個 crash
```

**root cause**：ThreadPoolExecutor 多個 thread 同時進行 SELECT 判斷「不存在」，然後同時 INSERT，第二個 INSERT 觸發 unique constraint violation。

### 修正：讓 DB 自己處理衝突

```python
# 修正版：INSERT 優先，ON CONFLICT DO NOTHING，再 SELECT 確保拿到 id
cursor.execute(
    "INSERT INTO sources (source_name, url) VALUES (%s, %s)"
    " ON CONFLICT (url) DO NOTHING RETURNING source_id",
    (name, url)
)
row = cursor.fetchone()
if row:
    return row[0]
# ON CONFLICT 觸發時 RETURNING 為空，fallback SELECT
cursor.execute("SELECT source_id FROM sources WHERE url = %s", (url,))
return cursor.fetchone()[0]
```

**關鍵點**：
- `ON CONFLICT DO NOTHING`：衝突時靜默跳過，不 raise exception
- `RETURNING`：INSERT 成功才有回傳；衝突時為空，需 fallback SELECT
- 這個模式是 PostgreSQL 的標準 upsert-or-read 寫法

### `raise e` vs `raise`

```python
# 錯誤（重置 traceback）
except Exception as e:
    raise e  # traceback 起點變成這一行，看不到真正的錯誤位置

# 正確（保留完整 traceback）
except Exception as e:
    raise  # 原始 traceback 完整保留
```

*最後更新：2026-04-05*
