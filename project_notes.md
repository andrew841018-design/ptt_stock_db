# Domain Know-How — Data Engineering 重點速查

> 從 PTT 情緒分析專案提煉的實戰知識。每個概念一眼看懂，面試時能直接用。
>
> **更新原則**：本文件是精華整理，不是流水帳。新增知識時維持「概念 → 一句話 → 關鍵要點」格式。

---

## 一、Database

### Schema 設計原則

- **一開始就設計好欄位**，不要靠 `ALTER TABLE` 補丁 — 新環境建表會缺欄位
- **DDL 和 DML 要同步**：CREATE TABLE 定義的欄位必須涵蓋 INSERT 用到的所有欄位，否則新 DB 建表後 INSERT 直接 crash（如 `dim_market` DDL 只有 2 欄，INSERT 寫 4 欄）
- **型別要嚴謹**：`push_count` 用 INTEGER 不用 TEXT（排序/計算不需額外轉型）
- **時間統一用 TIMESTAMP**：PTT 和鉅亨網都是 Unix timestamp（秒），`datetime.fromtimestamp()` 轉換

### NOT NULL 判斷原則

> **沒有這個值，這筆資料有沒有意義？**

- 有意義 → 允許 NULL（如 author、push_count）
- 沒意義 → NOT NULL（如 title、content、url、published_at）

### Index 選型

| 類型 | 適用場景 | 一句話 |
|------|---------|--------|
| **B-tree** | 等值 + 範圍查詢 | 預設選擇，最通用 |
| **Hash** | 純等值查詢 | 幾乎不用，B-tree 都能做 |
| **Composite** | 多欄位同時過濾 | 最左前綴原則：篩選力強的欄位放左邊 |
| **Partial** | 只查部分資料 | `WHERE push_count > 100` 只索引熱門資料，小又快 |
| **Full-text (GIN)** | 文字搜尋 | 比 `LIKE '%keyword%'` 快 N 倍 |
| **Clustered** | 大量資料 + 少寫入 + 範圍查詢 | 資料實體排序，DW Fact Table 適合 |

- **Index 的代價**：加速讀取，拖慢寫入（每次 INSERT/UPDATE 都要更新 index）
- **驗證**：`EXPLAIN ANALYZE` 看 `Index Scan` vs `Seq Scan`
- **清理**：`pg_stat_user_indexes` 找從未被使用的 index → 刪掉

### 查詢效能問題排查（由淺到深）

1. 沒有 index → 全表掃描
2. Index 類型選錯（範圍查詢用了 Hash）
3. Composite index 欄位順序錯
4. `SELECT *` 拉太多不需要的欄位
5. N+1 query → 迴圈裡每次都查 DB，應改成批次 JOIN
6. 沒有 Connection Pool → 每次建立新連線

### GROUP BY 規則

- SELECT 裡的欄位：被聚合函式（AVG/SUM/COUNT）包住 → 不放 GROUP BY
- SELECT 裡的欄位：沒被聚合函式包住 → **全部放 GROUP BY**
- 只看 SELECT 列出的欄位，跟 table 有多少欄位無關

**Subquery 模式**：內層做聚合（GROUP BY 只放 key），外層 JOIN 其他表拿剩下欄位 — 讓聚合和 JOIN 各做各的事。

### SQL 速查

| 語法 | 用途 |
|------|------|
| `WHERE` | 分組前過濾原始資料 |
| `HAVING` | 分組後過濾聚合結果（只能搭配 GROUP BY）|
| `fetchone()` | 回傳單個 tuple，如 `(42,)` |
| `fetchall()` | 回傳 list of tuples，無結果回 `[]` |
| `fetchmany(N)` | 分批讀取，避免記憶體爆（140 萬筆留言用這個）|
| `ON CONFLICT DO NOTHING` | 衝突時靜默跳過 |
| `ON CONFLICT DO UPDATE` | 衝突時更新（upsert）|
| `RETURNING` | INSERT 成功才有回傳；衝突時為空 |

### 並行寫入 Race Condition（TOCTOU）

```
❌ SELECT 檢查不存在 → INSERT（兩個 thread 同時通過 SELECT → 第二個 crash）
✅ INSERT ON CONFLICT DO NOTHING → fallback SELECT（讓 DB 自己處理衝突）
```

---

## 二、Data Architecture

### OLTP vs OLAP（DW）

| | OLTP | OLAP（Data Warehouse）|
|---|---|---|
| 優化目標 | 寫入（INSERT/UPDATE）| 讀取 + 分析（SELECT + 聚合）|
| 設計 | 正規化（減少冗餘）| 反正規化（冗餘換速度）|
| 本專案 | articles / comments / sentiment_scores | fact_sentiment / dim_* |

### Star Schema

```
dim_source → fact_sentiment
              (fact_date DATE, stock_symbol VARCHAR)
```

- **Fact Table**：每日每來源的聚合值（article_count, avg_sentiment, avg_push_count）
  - `fact_date`：直接用 DATE 欄位，不透過 dim_date FK（簡化 JOIN）
  - `stock_symbol`：denormalized，直接存代號（0050 / VOO），不透過 dim_stock FK
- **Dimension Table**：描述性維度（來源）；`dim_source` 含 `tracked_stock` 欄位標記該來源追蹤的股票代號
- **dim_stock**：獨立存在供查詢用，但 fact_sentiment 不再 FK 參照
- **Snowflake**：Dimension 再正規化（dim_source → dim_market），查詢多一層 JOIN 但更乾淨

### Denormalization（反正規化）

DW 把 `source_name` 和 `stock_symbol` 直接冗餘放進 Fact Table — 查詢時不用 JOIN dim_source / dim_stock。
OLTP 不能這樣做（冗餘 = 更新異常），但 DW 是「讀多寫少」，這是正確做法。

### fact_date 直接用 DATE

- dim_date 已移除，fact_sentiment 改用 `fact_date DATE` 直接存日期
- 省掉 JOIN dim_date 的開銷，查詢更簡潔
- DATE 型別原生支援範圍查詢（BETWEEN）、日期運算（+ INTERVAL），不需另存欄位

### Data Mart / MV / View / Subquery 四層比較

四種「把複雜 SQL 封裝」的機制，差別在**有沒有取名**和**有沒有存結果**：

| 機制 | 取名 | 存結果 | 查詢時 JOIN | 更新機制 |
|------|------|--------|-------------|----------|
| **Subquery** | ❌ | ❌ | ✅ 每次都跑 | 無（inline）|
| **View** | ✅ | ❌ | ✅ 每次都跑 | 永遠最新 |
| **Materialized View** | ✅ | ✅ | ❌ 讀 cache | `REFRESH MATERIALIZED VIEW`（PG 內建）|
| **Data Mart** | ✅ | ✅ | ❌ 讀 cache | `TRUNCATE + INSERT`（手寫 ETL，跨 DB 可移植）|

- Subquery → View：**有名字可以重用**
- View → MV：**結果存起來，不用每次重算**（"Materialized" = 實體化）
- MV → Data Mart：**離開 PG 也能用**（Data Mart 是架構概念、MV 是 PG 特有物件，104 JD 常見）
- **MV 的 JOIN 在 `REFRESH` 時跑一次就存起來**，查詢時讀快取 table，不是查詢時 JOIN

### 粒度（Granularity）

> 一筆資料代表多細的東西

| 粒度 | 本專案對應 | 用途 |
|------|-----------|------|
| 來源 × 日 | `mart_daily_summary`（Data Mart）| dashboard、API |
| 市場 × 日 | `mv_market_summary`（MV，Snowflake 三表 JOIN）| 跨市場比較（TW vs US）|

- Mart（source 粒度）+ MV（market 粒度）**互補不重複**
- MV 跑 `fact_sentiment JOIN dim_source JOIN dim_market`，在 market 層級聚合；Mart 直接在 source 層級 `GROUP BY`
- 刷新順序：`dw_etl.populate_fact()` → `data_mart.refresh_all()` → `dw_etl.refresh_mv()`

### Data Lake

- **本質**：原始資料的中央存儲，保留原始格式，支援各種檔案類型（JSON、CSV、Parquet...）
- **三層架構**：`raw/`（原始資料）→ `processed/`（清洗後 Parquet）→ `curated/`（聚合結果）
- **本專案**：用 MongoDB raw_responses 取代（600k 資料不需要 S3 三層架構）

### Parquet 格式

- **Columnar**：查詢只讀需要的欄位，不掃全部資料
- **壓縮**：同樣資料比 JSON 小 5-10x（Snappy 壓縮）
- **型別保留**：int / float / datetime 原生支持（JSON 全是字串）
- **生態系**：pandas、Spark、BigQuery、Athena 都原生支持

### Config-Driven Architecture（Single Source of Truth）

```python
# config.py — 唯一 source of truth
SOURCES = {
    "ptt":         { "market": "TW", "lang": "zh", "has_push_count": True,  ... },
    "cnyes":       { "market": "TW", "lang": "zh",                          ... },
    "reddit":      { "market": "US", "lang": "en", "has_push_count": True,  ... },
    "cnn":         { "market": "US", "lang": "en",                          ... },
    "wsj":         { "market": "US", "lang": "en",                          ... },
    "marketwatch": { "market": "US", "lang": "en",                          ... },
}

# Helper functions — 其他模組 import 這些，不要自己 hardcode 來源清單
sources_by_market("TW")  → ["ptt", "cnyes"]
sources_by_lang("en")    → ["reddit", "cnn", "wsj", "marketwatch"]

# 衍生 dict — dict comprehension 自動產生
SOURCE_META        → 來源 → {market, stock}
SOURCE_MARKET_MAP  → 來源 → market
SOURCE_COLORS      → 來源 → 圖表配色
```

**新增來源只需改 3 個檔案**：
1. `config.py`（加一筆 SOURCES entry）
2. 新爬蟲檔案（繼承 BaseScraper）
3. `pipeline.py`（在 `_ARTICLE_SOURCES` 加一行）

**不需要動的檔案**：GE、QA、DW ETL、AI model、visualization、cli、labeling_tool、stock_matcher — 全部從 config 衍生。

**市場級 vs 來源級**：labeling_tool 的 zh/en 分類、stock_matcher 的 tw/us 邏輯是市場級，只在新增市場時才需修改。

### ETL 流程設計

```
pipeline.py 8-step 編排：
  0. create_schema      → 確保 OLTP 表存在
  1. extract()          → 並行爬蟲寫入 OLTP（6 來源：PTT + cnyes + Reddit + CNN + WSJ + MarketWatch）
  2. transform()        → QA + 自動修復 + GE 驗證
  3. run_pii()          → PII 遮蔽
  4. run_batch_inference() → BERT 情緒推論
  5. run_fetch_etf() + run_matcher() → ETF 持股更新 + 股票比對
  6. run_etl()          → DW ETL + Data Mart 刷新
  7. backup_database()  → S3 備份
```

- 所有獨立腳本已整合進 `pipeline.py`，透過 `from X import Y` 統一呼叫
- 非關鍵步驟（3-5, 7-8）用 try/except fail-soft，失敗只 warning 不中止 pipeline
- `__main__` 區塊已從 pipeline 整合的檔案中移除（僅保留可獨立執行的工具）
- 所有 INSERT 都用 `ON CONFLICT`，幂等可重複執行
- Incremental Loading：用 URL UNIQUE 去重，已存在的跳過

### CLUSTER（實體排序）

```sql
CLUSTER fact_sentiment USING idx_fact_date;
```

資料實體上按 date_id 排序 → 範圍查詢只讀連續磁碟頁。會鎖表（ACCESS EXCLUSIVE LOCK），只在離峰執行。

---

## 三、Data Quality

### 三層驗證架構

```
爬蟲入庫前               DB 入庫後              API 回傳前
scraper_schemas.py      QA.py / GE            api.py response_model
（格式對不對）          （資料品質）           （輸出格式）
```

三層目的不同，互不重疊。

### Pydantic Validator 判斷原則

> **DB 的 NOT NULL / 型別約束擋不住的東西，才需要 Pydantic validator 補上。**

- `title`：NOT NULL 擋不住空字串 `""` → 需要 `title_not_empty`
- `url`：型別對但格式可能錯 → 需要 regex 驗證
- `push_count`：無 CHECK constraint → 需要 `-100 ≤ n ≤ 100` 範圍檢查
- `content`：NOT NULL 已夠 → 不需要額外 validator

### Schema Validator 反模式

```python
# ❌ 反模式：上游加 fallback 繞過 validator
article = {"title": title or url}    # 空 title 被 url 頂替，validator 收到非空值

# ✅ 正確：直接傳，讓 validator 決定
article = {"title": title}           # 空 → validator 攔截 → return None
```

**Validator 是唯一的資料品質把關點**，不要在上游加 fallback 繞過它。

### QA.py 檢查模式

| 檢查項目 | 方法 | 失敗行為 |
|---------|------|---------|
| 無重複 URL | `GROUP BY url HAVING COUNT(*) > 1` | raise ValueError 中止 pipeline |
| 無孤兒推文 | `WHERE article_id NOT IN (SELECT ...)` | raise ValueError |
| 資料不為空 | `SELECT COUNT(*)` | raise ValueError |

- `assert` 中止 pipeline、`logging.warning` 繼續跑 — 資料品質問題必須用 assert（或 raise）
- `assert(x, msg)` 是 tuple（永遠 truthy），正確寫法：`assert x, msg`

### Great Expectations

- `mostly=0.99`：容忍 1% 的例外（如 `change` 第一筆必為 NULL）
- 絕對不能有 NULL 的欄位不加 `mostly`（等同 `mostly=1.0`）

---

## 四、Redis Cache

### Cache-Aside Pattern（旁路快取）

```
API 請求 → 查 Redis → HIT → 直接回傳
                     → MISS → 查 DB → 存 Redis → 回傳
```

- Redis 是快取不是資料庫，DB 是 source of truth
- 本專案效果：4.11s → 0.11s（37 倍提升）

### 關鍵概念

| 概念 | 說明 |
|------|------|
| `setex(key, ttl, value)` | SET + EXpire 合一，到期自動刪除 |
| `orient='table'` | DataFrame 序列化保留 dtype（不然 int 變 float、datetime 變 str）|
| `StringIO` | 字串變 file-like object，`pd.read_json()` 需要 |
| RedisError 保護 | Redis 掛 → 降級到 DB，不讓 API 死掉 |

### 測試策略

- patch 命名空間原則：patch「使用者的命名空間」→ `patch("api.get_cache")` ✅
- `return_value`：固定回傳值；`side_effect`：拋例外或執行自訂函式

---

## 五、API Design

### REST 原則

- 資源導向：`/articles`（複數名詞），不用 `/getArticles`
- HTTP 語意：GET（讀）、POST（建）、PUT（全更新）、PATCH（部分更新）、DELETE
- 統一錯誤格式：`{"error": True, "code": "NOT_FOUND", "message": "..."}`

### Pydantic response_model 三件事

1. 型別驗證（回傳錯型別被抓到）
2. 過濾多餘欄位（防 DB 內部欄位外洩）
3. 自動產生 Swagger 文件

### 常見 Bug

- **共享 DataFrame in-place mutation**：快取物件是共用的，不 `.copy()` 就改 → 污染所有後續呼叫
- **dict `item["key"]` vs `item.get("key")`**：前者缺失 → KeyError 可能繞過上層 try/except
- **HTTP 200 with Error Body**：Arctic Shift API 永遠回 200，錯誤在 JSON body 裡 — 不能只靠 `raise_for_status()`

---

## 六、MongoDB

### PostgreSQL vs MongoDB

| | PostgreSQL | MongoDB |
|---|---|---|
| Schema | 嚴格，欄位事先定義 | 彈性，每筆 document 可不同結構 |
| 適用 | 結構化分析、JOIN、聚合 | 原始資料保留、半結構化 |
| 本專案 | OLTP + DW | raw_responses（HTTP 原文存檔）|

### raw_responses 的價值

- 存 HTTP 原文（HTML / JSON），不是解析後的資料
- Parser 有 bug → 修完 bug 後直接 re-parse，不需重新爬取
- 三種來源結構天生不同（PTT=HTML、鉅亨/Reddit=JSON）→ schema-less 完美適合

### Graceful Degradation 模式

```python
_MONGO_OK = True   # MongoDB 可用旗標
# MongoDB 掛 → _MONGO_OK = False → 靜默跳過 → 不影響主流程（PostgreSQL 寫入）
```

**原則**：附加功能掛掉不能影響核心流程。

### BSON 16MB 限制

MongoDB 單個 document（含查詢 command）不能超過 16MB。
`$in` 查詢放 56 萬筆 URL → 超過限制 → **分批查詢**（每批 500 個 URL）。

### Upsert 模式

```python
db["raw_articles"].update_one({"url": url}, {"$set": doc}, upsert=True)
```

以 url 為唯一鍵，重複跑不產生重複資料。

---

## 七、Data Repair Pipeline

### 修復流程

```
QA_checks() 失敗 → repair() → diagnose() 掃壞資料 → 分類來源
  → MongoDB raw re-parse → UPDATE PG（只更新非 None 欄位）→ 重跑 QA
```

### 設計要點

- **diagnose()**：掃 PG 找 NULL 的 title/content/push_count/published_at
- **UPDATE 只更新非 None**：re-parse 可能某些欄位取不到，不應覆蓋 DB 已有的好值
- **pipeline 整合**：QA 失敗 → catch → repair → 重跑 QA → 仍失敗才真正中止

---

## 八、ML / NLP

### BERT 情緒分析

| 項目 | 值 |
|------|-----|
| Base model | `bert-base-chinese` |
| Labels | 3（negative / neutral / positive）|
| Score 計算 | `P(positive) - P(negative)`，範圍 [-1, +1] |
| 最少標注量 | 50 筆才 fine-tune（避免 overfitting）|
| Zero-shot fallback | 未 fine-tune 時用預訓練模型（不準但有值）|
| 批次推論 | `LEFT JOIN WHERE IS NULL` + 每批獨立 commit，中途斷可接續 |

### Stock Matcher（股票比對）

- **檔案**：`stock_matcher.py`（原 `ner.py`），函式 `run_matcher()`
- **策略一**：Regex 抓代號 → 比對 `stock_dict.json`（避免隨機數字誤判）
- **策略二**：最長匹配抓公司名（「台灣積體電路」先於「台積」）
- **match_done 表**：追蹤已處理文章，避免無提及股票的文章被無限重複處理

### AI 模型預測系統（Walk-Forward Validation）

- **為什麼不用 Random Split**：時間序列 random split 會偷看未來（data leakage）
- **Walk-Forward**：Train=[歷史] → Test=[下一季]，訓練集逐步擴展
- **所有 lag/rolling 特徵都 shift(1)**：用昨日資料預測今日，避免 leakage
- **策略報酬**：預測漲 → 進場；預測跌 → 不進場。對照 Buy-and-Hold 計算超額報酬

### 情緒分析加權（push_tag_bonus）

```python
score = text_score + tag_bonus   # 推 +0.3 / 噓 -0.3，clamp [-1, +1]
```

0.3 是 heuristic，嚴謹做法要用標注資料跑實驗找最佳值。

### KeyBERT vs Regex 斷詞

- Regex 只做字面切分，KeyBERT 用 BERT 語意向量選出最相關詞組
- `@st.cache_resource`：模型等重量級物件，整個 app 只建一份
- `@st.cache_data`：DataFrame 等資料，不同輸入各快取一份

---

## 九、Python Patterns

### Exception 分層處理

```
底層（scraper）    → raise（往上丟）
中層（DB helper） → rollback + raise（清理 + 往上丟）
最上層（pipeline）→ logging.error（收尾，不再 raise）
```

- `raise`：保留完整 traceback ✅
- `raise e`：重置 traceback 起點 ❌
- 最上層不 raise：再拋就是 unhandled exception，Python 印 traceback 死掉

### Abstract Base Class（ABC）

```
BaseScraper（框架 + 共用邏輯）
  ├── @abstractmethod：get_source_info()、fetch_articles()  ← 子類別必須實作
  └── 一般方法：run()、_save_to_db()、_get_with_retry()    ← 子類別繼承直接用
```

- 新增來源只要建子類別實作兩個 method，DB 寫入邏輯全在 base（目前 6 支爬蟲：ptt / cnyes / reddit / cnn / wsj / marketwatch）
- `@abstractmethod` 的空殼永遠不會被執行，Python import 時就掃描 class 結構

### 並行爬蟲（ThreadPoolExecutor）

```python
with ThreadPoolExecutor() as executor:
    futures = {executor.submit(fn, arg): name for ...}
    for future in as_completed(futures):
        future.result()   # 若子 thread raise，這裡重新 raise
```

- I/O bound → `ThreadPoolExecutor`（等 HTTP，不消耗 CPU）
- `as_completed()`：哪個先完先處理，不按送入順序
- 每個來源獨立 thread + 獨立 DB 連線 → thread-safe

### Context Manager

```python
@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()   # 不管有沒有 exception 都會關
```

解決 connection leak：`with` 進去拿 handle，出來自動關閉。

### DB 連線雙軌制

| 用途 | 連線方式 | 角色 | 適用檔案 |
|------|---------|------|---------|
| DML（INSERT/UPDATE/SELECT）| `get_pg()` context manager | etl_user | bert_sentiment、stock_matcher、data_mart 等 |
| DDL（CREATE TABLE/REFRESH MV/CLUSTER）| `psycopg2.connect(**PG_CONFIG)` | admin | schema.py、dw_schema.py、dw_etl.py |

- DML 統一走 `get_pg()`：自動 commit/rollback/close
- DDL 需要 admin 權限：etl_user 的 GRANT 不含 CREATE，必須用 PG_CONFIG（admin 角色）

### Import 風格

- 全專案統一 `from X import Y`，不用 `import X` 再 `X.Y`
- 好處：呼叫處簡潔（直接 `run_matcher()` 而非 `stock_matcher.run_matcher()`）
- Dict comprehension 變數用有意義的名稱（`futures`、`source_name`），不用 `k`、`v`

### Python 版本陷阱

- `str | None`（PEP 604）→ Python 3.10+ 才支持
- Python 3.9 在 class 定義時直接 `TypeError`，整個模組 import 失敗
- 安全寫法：`Optional[str]`（3.5+）

### subprocess `-c` 模式陷阱

- `python -c "..."` 執行時 `__file__` 未定義（不是從檔案執行）
- 需要在外層先取 `cwd = os.path.dirname(__file__)`，再用 f-string 嵌入 `-c` 字串

### argparse 跨模組呼叫陷阱

- 模組的 `main()` 如果用 `argparse.parse_args()`，會讀 `sys.argv`
- 被另一個 CLI 工具（pipeline / cmd）import 呼叫時，`sys.argv` 帶的是外層的參數 → `unrecognized arguments` 報錯
- **解法**：expose 不帶 argparse 的函式（如 `save_csv()`），`main()` 只在 `__main__` 用

### pandas 速查

| 概念 | 說明 |
|------|------|
| `shift(1)` | 整欄往下移一格，第一筆自動 NaN — 取代 iterrows 逐列計算 |
| NaN vs None | NaN = pandas 缺失值，psycopg2 不認識；None = Python 空值，自動轉 NULL |
| `.copy()` | 操作共享 DataFrame 前必須 copy，否則 in-place 修改污染快取 |

---

## 十、Infrastructure

### CI/CD（GitHub Actions）

- SSH 啟動 uvicorn 後不結束 → 用 `setsid nohup ... > /dev/null 2>&1 &`
- pytest 無真實 DB → `unittest.mock.patch` 注入假資料
- patch 要 patch「使用者的命名空間（import 後）」：`patch("api.get_daily_sentiment")` ✅，不是 `patch("data_mart.get_daily_sentiment")` ❌
- **重構搬函式時，測試 mock 要同步跟著搬**：否則 pytest 悄悄連真實 DB — CI 無 DB 會 fail、本機有 DB 會 false pass（最難抓的那種）
- **`continue-on-error: true` 陷阱**：step 失敗不影響 job 狀態 → deploy step 顯示綠燈但實際整個爆；production deploy step 絕對不能開，只有「預期可能失敗且不影響後續」的實驗性 step 才用
- **`git pull` 在 deploy script 裡是地雷**：遇到 divergent branches 會直接 fail 並要求選 merge strategy；正確做法 `git fetch && git reset --hard origin/main`（deploy 永遠追 remote，不保留 local 改動）
- **Git 歷史無共同祖先**：`git merge-base A B` 回傳空 → 兩條 branch 完全獨立發展，硬 merge 會地獄；正確解法是選定主幹 `git reset --hard`

### Shell 重導向

```bash
> /dev/null    # stdout → 黑洞
2>&1           # stderr → 跟 stdout 同一個地方
&              # 背景執行
```

`&1` 的 `&` = fd 編號標記；`2>1` 會建立名為 `1` 的檔案。

### macOS 自動排程

- **cron 在 macOS Sequoia 無法使用**（launchctl load 失敗）
- **改用 launchd**：plist 放 `~/Library/LaunchAgents/`
- **路徑陷阱**：launchd CWD 預設 `/`，script 裡必須硬編碼 `PROJECT_DIR`

### Logging

| 概念 | 說明 |
|------|------|
| `basicConfig` | 全域設定：格式、等級 |
| `getLogger(__name__)` | 模組級 logger，可單獨設定等級 |
| f-string | 做了再決定印不印（DEBUG 等級也會組合字串）|
| `%s` 佔位符 | 先決定印不印，不印什麼都不做（效能較好）|

### .env 陷阱

```bash
PG_HOST=        # 讀進來是空字串 ""，不是 None
# os.environ.get("PG_HOST", "localhost") 拿到 ""，不是 "localhost"
```

`.env` 設了空值 = key 存在但值是 `""`，預設值不會生效。要嘛填值，要嘛刪掉那行。

### config.py 邊界（局部性原則）

- **放 config**：多個檔案 import 的常數（PG_CONFIG、SOURCES、MAX_RETRY、*_TABLE）
- **放 config**：跨模組共用的 sleep 延遲 — `REQUEST_DELAY=0.3`（通用）、`TWSE_DELAY=3`（TWSE 官方限速）
- **不放 config**：只有單一模組用的常數 → 放在該模組最上面

```
REDIS_HOST/PORT    → cache_helper.py（只有 cache 用）
S3_BUCKET          → backup.py（只有 backup 用）
BERT_MODEL         → bert_sentiment.py（只有 bert 用）
CACHE_KEY_ARTICLES → api.py（只有 api 用）
```

好處：改參數只開一個檔案，常數就在使用它的程式碼旁邊。
壞處：如果常數未來變成多處共用，要記得搬回 config。

### Markdown 預覽

| 方式 | 操作 |
|------|------|
| **VS Code 側邊預覽** | `Cmd + K` → `V` |
| **VS Code 全螢幕預覽** | `Cmd + Shift + V` |
| **HackMD** | 貼到 https://hackmd.io，左右分割即時預覽 |
| **GitHub** | push 後直接在網頁點 `.md` 檔，自動渲染 |

---

## 十一、遷移與資料搬運

### SQLite → PostgreSQL 核心挑戰

- **ID 不連續**：用 URL 當橋梁建立 `id_map: Dict[sqlite_id, pg_id]`
- **型別轉換**：TEXT → INTEGER/TIMESTAMP，轉換失敗用預設值不中斷遷移
- **記憶體管理**：140 萬筆用 `fetchmany(5000)` 分批讀，不用 `fetchall()`
- **幂等設計**：`ON CONFLICT DO NOTHING/UPDATE`，遷移腳本可安全重複執行

### batch 內 dedup

同一篇文章多則相同推文 → dict comprehension 去重：

```python
deduped = list({(t, tid, m): row for t, tid, m, *_ in batch}.values())
```

---

## 十二、ETF 持股與 NER 字典

### 台股 0050 成分股

無公開 API → 用 TWSE 收盤價排序取前 50 名普通股。

### 美股 VOO（S&P 500）

從 Wikipedia 用 `pd.read_html()` 抓取，約 503 支（含雙股份類別）。
Yahoo Finance 代號：`BRK.B` → `BRK-B`。

### stock_dict.json 更新

**replace 而非 merge**：用 merge 的話被剔除的舊成分股會永遠留著。

---

## 十三、Git Workflow

### Tag 規範

| | commit message | git annotated tag |
|---|---|---|
| 用途 | 描述改動脈絡 | 標記任務完成里程碑 |
| 唯一性 | 可重複 | 全 repo 唯一 |
| 查詢 | `git log --oneline` | `git tag -l` |

- commit message 不加前綴，改用 annotated tag 標記任務名稱
- 純 docs commit 等下一個實質改動一起合併 push
- 不加 tag 的情況：純文件修改、bug fix、多 commit 共同完成一個任務（只在最後一個加）

---

## 十四、API 資安與權限管理

### SQL 層：GRANT / REVOKE

PostgreSQL 沒有 `DENY`（SQL Server 才有），只有 `GRANT` 和 `REVOKE`。

```sql
-- DO $$ ... END $$：匿名程式區塊，讓 SQL 可以用 IF/THEN 邏輯
-- pg_roles：PostgreSQL 內建系統表（存放所有角色），不需要建，裝好就有
-- CREATE ROLE ... LOGIN：建帳號 + 允許登入
IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api_user') THEN
    CREATE ROLE api_user LOGIN PASSWORD 'xxx';
END IF;

-- 三層權限（CONNECT → USAGE → SELECT），成對授權，缺一不可
GRANT CONNECT ON DATABASE stock_analysis_db TO api_user;  -- 允許連線
GRANT USAGE ON SCHEMA public TO api_user;                 -- 允許看到 table（與 SELECT 成對）
GRANT SELECT ON ALL TABLES IN SCHEMA public TO api_user;  -- 允許讀資料（與 USAGE 成對）
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO api_user;  -- 未來新建的 table 也自動授權

-- etl_user：給完整讀寫
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO etl_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO etl_user;  -- SERIAL 自動遞增需要

-- 防禦性 REVOKE：防止有人誤下 GRANT ALL
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM api_user;
```

- **USAGE vs SELECT**：USAGE = 進入 schema 看到有哪些 table；SELECT = 讀 table 裡的資料。兩個缺一不可，PostgreSQL 不會自動隱含
- **SEQUENCE 權限**：`USAGE` 允許 `nextval()`（INSERT 時產生 ID），`SELECT` 允許 `currval()`（讀取剛才產生的 ID）
- **權限在 DB 端控制，不在 Python 端**：`psycopg2.connect(user="api_user")` 只是用哪個帳號登入，實際能做什麼由 GRANT/REVOKE 決定
- **`ALTER DEFAULT PRIVILEGES`**：確保未來新建的表也自動繼承權限，不用每次手動 GRANT
- **帳密存 `.env`**，透過 `os.environ.get()` 讀取，不寫死在 code
- **DDL 不能用 `%s` 參數化**：`CREATE ROLE`、`GRANT` 的 identifier（角色名、表名）不能用 `%s`（會加引號導致語法錯），只能用 `.format()` 或 `psycopg2.sql.Identifier()`

### JWT Authentication

```
POST /auth/login
Body: {"username": "admin", "password": "admin123"}
         ↓
FastAPI + Pydantic 解析 request body → LoginRequest 物件
         ↓
驗證帳密 → create_token() → 回傳 JWT token
         ↓
後續請求 Header: Authorization: Bearer <token>
         ↓
Depends(verify_token) 驗證 → 通過才進 endpoint
```

- **`sub`**：JWT 標準欄位（RFC 7519），全名 subject，放 username；不用自訂 `"username"` key
- **`exp`**：過期時間，`python-jose` 自動驗證
- **`role`**：自訂欄位，標準沒有，可自由命名
- **`token_type: "bearer"`**：OAuth 2.0 標準，誰拿到 token 就能用（持有者授權）
- **`Depends(verify_token)`**：FastAPI 執行 endpoint 前先跑 verify_token，失敗直接 401 不進 function body
- **`dict.get()` vs `dict[]`**：key 不存在時 `.get()` 回 None，`[]` 拋 KeyError；login 驗證用 `.get()` 防止帳號不存在時 crash

### Pydantic request body 解析流程

```
Client 送 JSON: {"username": "admin", "password": "admin123"}
         ↓
def login(req: LoginRequest):   ← 型別是 BaseModel 子類別
         ↓
FastAPI 看到 BaseModel → 自動從 request body 解析
         ↓
Pydantic 把 JSON key 對應到 class 欄位（名稱要完全一樣）
         ↓
req.username = "admin" / req.password = "admin123"
```

- **型別提示決定來源**：`BaseModel` → body；`int/str` 基本型別 → path/query；`Query(...)` → query string
- **key 名稱一對一對應**：JSON `"username"` → class `username: str`，名稱不同 → 422 Validation Error

### PII Masking

```python
def hash_author(author: str) -> str:
    salted = f"{PII_HASH_SALT}:{author}"
    return hashlib.sha256(salted.encode()).hexdigest()[:16]
```

- **SHA-256 加鹽**：防彩虹表攻擊，鹽值存 `.env`
- **取前 16 碼**：夠唯一（2^64 碰撞機率極低），比完整 hash 省空間
- **不可逆**：hash 後無法還原原始帳號（GDPR 合規）
- **冪等**：同帳號 → 同 hash → `GROUP BY` 統計仍有意義
- **LENGTH > 16 判斷**：已 hash 的不重複處理（冪等設計）

---

## 十五、BTC Pipeline — 大資料實踐

### Kafka 串流
- **KRaft mode**: Kafka 3.7+ 不需要 Zookeeper，KAFKA_PROCESS_ROLES=broker,controller
- **Idempotent Producer**: enable_idempotence=True → 避免重複推送（exactly-once 語義的基礎）
- **Manual Offset Commit**: enable_auto_commit=False → 處理完才 commit，確保 at-least-once
- **Dead Letter Queue (DLQ)**: 壞訊息不丟棄，送入另一個 topic 事後排查
- **Partition Key**: 同一 symbol 進同一 partition → 保證同交易對的訊息順序

### Data Lake 三層
- **raw → processed → curated**: 原始 JSONL → 清洗後 Parquet (Snappy) → 聚合 OHLCV
- **Quarantine Layer**: 壞資料（price≤0、quantity≤0、trade_id=None）不混入主流程，隔離到 quarantine/
- **Snappy 壓縮**: Parquet + Snappy ≈ 6.6x 壓縮，兼顧壓縮率和解壓速度

### Partition Strategy
- **partitionBy('date','symbol')**: 寫入時建立 Hive-style 目錄 `date=2026-03-15/symbol=BTCUSDT/`
- **Partition Pruning**: 查詢 WHERE date='...' 時，Spark 只掃描目標分區目錄，跳過其他 → explain 看 PartitionFilters
- **repartition vs coalesce**: repartition = full shuffle（可增可減）、coalesce = no shuffle（只能縮減）
- **何時該分區**: 資料夠大 + 查詢有明確的分區鍵（低基數、常用於 WHERE）

### Spark ML Pipeline
- **Transformer**: 轉換資料但不改 schema（VectorAssembler、StandardScaler）
- **Estimator**: fit() 後產出 Transformer（RandomForestClassifier → RandomForestClassificationModel）
- **Pipeline**: 串接 stages，fit(train) 一次完成所有 stage → PipelineModel
- **VectorAssembler**: 多個 feature column → 一個 Vector column（Spark ML 要求）
- **模型儲存**: model.write().save(path) → 完整保留 Pipeline 所有 stage

---

*最後更新：2026-04-16*
