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
- 5 張表：`sources` / `articles` / `comments` / `sentiment_scores` / `stock_prices`
- `stock_prices`：只追蹤 0050 一支股票，UNIQUE 在 `trade_date`，不需要 stock_no 欄位

---

## 二、Index 設計

### 為什麼需要 Index
查詢沒有 index 時，DB 會做全表掃描（Seq Scan），資料量大時非常慢。

### 本專案建立的 5 個 Index（全是 B-tree）

| Index | 欄位 | 用途 |
|-------|------|------|
| `idx_articles_published_at` | `published_at` | 範圍查詢「某段時間的文章」|
| `idx_articles_source_id` | `source_id` | 等值查詢「特定來源」|
| `idx_comments_article_id` | `article_id` | JOIN articles 加速 |
| `idx_sentiment_article_id` | `article_id` | 情緒分數 JOIN articles 加速 |
| `idx_stock_prices_trade_date` | `trade_date` | 股價日期範圍查詢 |

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

### base class 是框架，不是實作

`BaseScraper` 定義「要有什麼、回傳什麼格式」，子類別填入「實際怎麼做」：

```
BaseScraper（框架）
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

*最後更新：2026-04-03*
