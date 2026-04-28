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

### SQL 四大分類

| 類別 | 全稱 | 用途 | 代表指令 |
|------|------|------|----------|
| **DDL** | Data **Definition** Language | 定義結構 | `CREATE` / `ALTER` / `DROP` / `TRUNCATE` |
| **DML** | Data **Manipulation** Language | 操作資料 | `INSERT` / `UPDATE` / `DELETE` / `SELECT` |
| **DCL** | Data **Control** Language | 權限控管 | `GRANT` / `REVOKE` |
| **TCL** | Transaction **Control** Language | 交易管理 | `COMMIT` / `ROLLBACK` |

- **`TRUNCATE` 是 DDL 不是 DML** —— 整張重建、不寫 transaction log、速度快但無法 rollback；`DELETE` 才是 DML（逐列可 rollback）
- **DDL 不能用 `%s` 參數化**：identifier（表名/角色名）必須用 `.format()`，只有 value 能用 `%s`

### 並行寫入 Race Condition（TOCTOU）

```
❌ SELECT 檢查不存在 → INSERT（兩個 thread 同時通過 SELECT → 第二個 crash）
✅ INSERT ON CONFLICT DO NOTHING → fallback SELECT（讓 DB 自己處理衝突）
```

### 大表子查詢效能（NOT EXISTS vs NOT IN）

```sql
-- ❌ NOT IN：把子查詢結果全部物化成 list，110 萬筆 → 記憶體爆炸 → PG OOM crash
SELECT COUNT(*) FROM comments
WHERE article_id NOT IN (SELECT article_id FROM articles);

-- ✅ NOT EXISTS：關聯式子查詢，每列做 index lookup，不物化整個結果集
SELECT COUNT(*) FROM comments c
WHERE NOT EXISTS (
    SELECT 1 FROM articles a WHERE a.article_id = c.article_id
);
```

- **NOT IN 的陷阱**：子查詢結果在記憶體中物化為 list，100 萬筆 = 數十 MB 暫存 → PG server OOM（症狀：`OperationalError: server closed the connection unexpectedly`）
- **NOT EXISTS 原理**：correlated subquery，外層每一列對 articles 做一次 index lookup，記憶體只用到一個 row
- **適用時機**：子查詢結果集超過數萬筆就改 NOT EXISTS；小表 NOT IN 可讀性更高

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
- View → MV：**結果存起來,不用每次重算**（"Materialized" = 實體化）
- MV → Data Mart：**離開 PG 也能用**（Data Mart 是架構概念、MV 是 PG 特有物件，104 JD 常見）
- **MV 的 JOIN 在 `REFRESH` 時跑一次就存起來**，查詢時讀快取 table，不是查詢時 JOIN

### Stored Procedure（SP）— 把 SQL 封裝在 DB 端

「儲存在 DB 裡面的 function」。Python 只送 `CALL sp_name()`，所有 SQL 邏輯在 PG 內部執行：

```sql
CREATE OR REPLACE PROCEDURE sp_refresh_mart_daily_summary()
LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE mart_daily_summary;
    INSERT INTO mart_daily_summary (...)
    SELECT ... FROM fact_sentiment GROUP BY f.fact_date, f.source_name;
END;
$$;
```

```python
cur.execute("CALL sp_refresh_mart_daily_summary()")  # Python 只負責 CALL
```

| 優點 | 缺點 |
|------|------|
| SQL 已編譯，執行快（省 parse 階段）| 版控不直觀（字串嵌在 `dw_schema.py`）|
| DBA `\df+` 看得到所有邏輯 | 跨 DB 不可移植（plpgsql → MySQL 要重寫）|
| 多 client（Python / Java / Go）共用 | 除錯難（log 在 DB server）|
| 權限可獨立控制（只給 CALL 不給 TRUNCATE）| |

- 前綴 `sp_` 是業界慣例，`CREATE OR REPLACE` 幂等（重跑覆蓋舊版）
- `$$ ... $$` 是 PG 字串 delimiter，允許裡面出現單引號不需 escape
- 本專案 2 支 SP：`sp_refresh_mart_daily_summary` / `sp_populate_fact`（mart_hot_stocks 表已棄用：表結構未含 stock_symbol 欄位、API `/articles/top_push` 走 articles 直讀路徑沒讀它，2026-04-17 連同 SP 一起移除）

### Mart 經濟學（為什麼每天重算值得）

**Mart ETL 第一次跑的成本 ≈ 沒 Mart 時一次 query 的成本**（本質是相同的 GROUP BY + AVG）。價值不在讓計算變便宜，而在：

```
沒 Mart:  total = query × N        （user 每次都等那 15 秒）
有 Mart:  total = ETL + query × N  （ETL 1 次在離線時段，user 每次 50ms）
```

| N（一天 query 次數）| 沒 Mart | 有 Mart | 勝方 |
|---|---|---|---|
| 1 | 15 s | 15.05 s | 沒 Mart（差一點）|
| 2 | 30 s | 15.10 s | **有 Mart** |
| 100 | 1500 s | 20 s | **有 Mart ✅✅✅** |

三個獨立觸發條件（任一成立就值得做 Mart）：
1. **查詢次數多** —— ETL 成本被 N 次 query 攤薄
2. **單次查詢要快** —— API 必須 < 1 秒，即使 N=1 也不能讓 user 等 15 秒
3. **複雜運算重複** —— 同樣的 JOIN + GROUP BY 每次結果都一樣（memoization）

核心洞察：**把重活推到離線時段（沒人等的凌晨），線上只做輕活（user 等的時候）** —— 所有 OLAP / DW 系統的基本原則。

**代價 —— 新鮮度**：Mart 是 ETL 時間點的快照，下次刷新前 user 看不到最新資料。秒級即時需求不適合 Mart → 改 streaming（Kafka + Flink / KSQL）。

### Mart vs Cache（常被混淆）

| | Cache | Data Mart |
|---|---|---|
| 資料來源 | **別的系統**（外部 API、主 DB）| **同一顆 PG 的 fact 表** |
| 清空後 | 回原系統撈，撈不到就沒了 | 從 fact 重新 GROUP BY 算出來 |
| 存多少 | 通常只存 hot data | **完整歷史聚合**（每一天都在）|
| 清空風險 | 有 | **沒有**（fact 還在，重算即可）|

- **`TRUNCATE mart_daily_summary` 只清 mart**，fact_sentiment 動都不動
- user 能查多久的歷史，取決於 fact 有多久歷史 —— 跟 mart 刷新策略無關
- 「全量重灌」vs「incremental」只是刷新策略差異，刷完後 mart 內容都是完整歷史

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

**不需要動的檔案**：GE、QA、DW ETL、AI model、visualization、cli、labeling_tool — 全部從 config 衍生。

**市場級 vs 來源級**：labeling_tool 的 zh/en 分類是市場級，只在新增市場時才需修改。

### ETL 流程設計

```
pipeline.py 9-step 編排（_step 標籤）：
  -1. update_dependencies() → 每週檢查並升級非 pin 套件（fail-soft）
   0. create_schema + ensure_indexes → 確保 OLTP 表 + MongoDB index 存在
   1. extract()              → 並行爬蟲寫入 OLTP（6 來源：PTT + cnyes + Reddit + CNN + WSJ + MarketWatch）
   2. transform()            → QA + 自動修復（reparse） + GE 驗證
   3. run_pii()              → PII 遮蔽（fail-soft）
   4. run_batch_inference()  → BERT 情緒推論（必要時自動 fine-tune）（fail-soft）
   5. run_etl()              → DW ETL + Data Mart 刷新
   6. backup_database()      → S3 備份（fail-soft）
   7. run_ai_model_prediction("tw" / "us") → Walk-Forward AI 模型預測（fail-soft）
```

> 註：原 `fetch_etf+stock_matcher` step 已於 2026-04 移除。stock_matcher 的功能（regex 抓代號、最長匹配公司名、`match_done` 表）連同 ETF 持股抓取一併裁撤；現在 sentiment 分析直接以 source 級聚合。

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

### GE 0.18.19 regex anchor（re.match vs re.search）

- `expect_column_values_to_match_regex` 底層用 **`re.match`**（anchor 在字串開頭），不是 `re.search`（任意位置）
- 寫 pattern 時若語意是「URL 中某段子字串」（如 `cnn.com/`），URL 開頭是 `https://...` 時 `re.match` 全部 FAIL
  - 實測：`re.match(r"cnn\.com/", "https://edition.cnn.com/...")` → `None`；`re.search` → 有結果
- 修法：consumer 端補 `.*` 前綴（`f".*{url_pattern}"`），讓 `re.match` 可從任意位置開始比對
- config.py 保持乾淨（search 語意），fix 收斂在 ge_validation.py 單一消費端

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

### NoSQL 選型比較（面試必考）

| 系統 | 資料模型 | 一致性 | 適用場景 |
|------|---------|--------|---------|
| **Redis** | Key-Value + 5 種結構（String/List/Set/SortedSet/Hash）| 強（單執行緒串行）| Cache、Session、排行榜、Pub/Sub、Rate Limiter |
| **Cassandra** | Wide Column（Partition Key + Clustering Key）| 可調（`QUORUM` ～最終）| 時序資料、IoT 寫入密集、跨資料中心高可用，不支援 JOIN |
| **DynamoDB** | Key-Value + Document（GSI/LSI 做 secondary access）| 最終一致性（可選 strong read）| AWS 生態、Serverless、全球分散、無伺服器管理 |
| **Elasticsearch** | Document（倒排索引 Inverted Index）| 最終一致性 | 全文搜尋、Log 分析、APM / Observability |

**選型口訣**（面試講清楚這四問）：
1. **資料模型**：K-V / Wide Column / Document / Search？
2. **一致性要求**：強一致 → Redis/DynamoDB strong；最終一致 → Cassandra/ES
3. **讀寫比例**：讀多寫少 → Redis Cache；寫多（時序）→ Cassandra
4. **規模與管理**：Serverless / 全托管 → DynamoDB；自維護 → Cassandra / ES

**本專案結論**：Redis 已足夠（Cache-Aside + Pub/Sub），不需引入其他 NoSQL。MongoDB 另作原始資料存檔用（raw_responses）。

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

### Stock Matcher（股票比對，已於 2026-04 移除）

> 原 `stock_matcher.py`（前身 `ner.py`）已從 pipeline 移除。下面是當時設計，留作後續若要恢復股票級分析的參考：
>
> - **策略一**：Regex 抓代號 → 比對 `stock_dict.json`（避免隨機數字誤判）
> - **策略二**：最長匹配抓公司名（「台灣積體電路」先於「台積」）
> - **match_done 表**：追蹤已處理文章，避免無提及股票的文章被無限重複處理

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

### psycopg2 v2 `with conn:` 陷阱（常見 connection leak 來源）

```python
# ❌ 看似沒問題，實際上 conn 永遠不會 close
with psycopg2.connect(**PG_CONFIG) as conn:
    with conn.cursor() as cur:
        cur.execute(...)
# 這裡出了 context manager，conn 仍然在記憶體，每次多漏一個

# ✅ 搭配自己的 context manager（get_pg）確保 close
with get_pg() as conn:   # try/yield/finally: conn.close()
    ...
```

- psycopg2 v2 的 `with conn:` 官方設計上**只管 transaction**（context exit 時 commit、exception 時 rollback），**不會呼叫 `conn.close()`**
- 慢性 leak：ETL 每跑一次漏一個，長時間累積會耗盡 PG `max_connections`
- 對比 `get_pg()` 的 `finally: conn.close()` 才是真正的 close；本專案所有 DML 統一走 `get_pg()` 就是為了避開這個坑

### pg_helper 防禦性 rollback（伺服器斷線場景）

```python
# ❌ 問題版：PG server 斷線後 conn.rollback() 本身也會 crash
except Exception:
    conn.rollback()   # InterfaceError: connection already closed → 蓋掉原始 OperationalError
    raise

# ✅ 修正版：rollback 和 close 各自包進 try/except
except Exception:
    try:
        conn.rollback()
    except Exception:
        pass    # InterfaceError 靜默吞掉，保留原始 OperationalError
    raise
finally:
    try:
        conn.close()
    except Exception:
        pass
```

- **觸發場景**：PG server OOM crash → `OperationalError: server closed the connection unexpectedly` → rollback 失敗 → `InterfaceError: connection already closed` 把原始錯誤蓋掉
- **雙重 crash 問題**：第一個 exception 讓 Python 跑進 except，rollback 又拋第二個 exception → 原始錯誤消失，排查方向錯誤
- **rollback / close 各自包**：讓其中一個失敗不影響另一個執行；`raise` 保持在 rollback try/except 外，確保原始 exception 繼續往上傳

### DB 連線雙軌制

| 用途 | 連線方式 | 角色 | 適用檔案 |
|------|---------|------|---------|
| DML（INSERT/UPDATE/SELECT）| `get_pg()` context manager | etl_user | bert_sentiment、data_mart、ai_model_prediction、pii_masking 等 |
| DDL（CREATE TABLE/REFRESH MV/CLUSTER）| `psycopg2.connect(**PG_CONFIG)` | admin | schema.py、dw_schema.py、dw_etl.py |

- DML 統一走 `get_pg()`：自動 commit/rollback/close
- DDL 需要 admin 權限：etl_user 的 GRANT 不含 CREATE，必須用 PG_CONFIG（admin 角色）

### Import 風格

- 全專案統一 `from X import Y`，不用 `import X` 再 `X.Y`
- 好處：呼叫處簡潔（直接 `run_batch_inference()` 而非 `bert_sentiment.run_batch_inference()`）
- Dict comprehension 變數用有意義的名稱（`futures`、`source_name`），不用 `k`、`v`

### 對稱命名（Parallel Naming）

同一概念在不同市場/環境各有一個版本時，用**統一的命名模板**，差異只在變數位置：

```python
load_tw_correlation()   # TW 市場情緒 vs 股價
load_us_correlation()   # US 市場情緒 vs 股價
load_{market}_correlation()   # 新增市場照 pattern 寫 load_jp_correlation
```

好處：
- 讀者看到 tw 版能立刻推斷有 us 版，讀 code 時只關注「差異」而非「從頭理解」
- 搜尋 `load_.*_correlation` 一次找齊所有對稱實作
- 新增市場只要複製一份改兩處（market 代碼 + SQL table），不用新設計命名

本專案例子：`load_tw_correlation` / `load_us_correlation`（差別在 `sources_by_market()` 參數 + JOIN 的股價表）。

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

### Python 字串中的 SQL 注釋陷阱

- Python `#` 是 Python 注釋，**但三引號字串內的 `#` 不被 Python 剝除** — 字串原樣傳給 PostgreSQL
- PostgreSQL 只認識 `--`（單行）和 `/* */`（多行），**不認識 `#`**
- 症狀：`syntax error at or near "#"` → `create_dw_schema()` 失敗 → 整個 ETL pipeline 中斷
- **解法**：SQL 字串內一律用 `--` 代替 `#` 作注釋

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

### Shell Script 自引計數 Bug

```bash
# ❌ 問題：同日 log 共用（tee -a），grep 會計到前次執行摘要中的 "ERROR 數量" 文字
ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE")   # 每次翻倍

# ✅ 修正：記錄本次開始行號，只 grep 新增的行
LOG_START_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
LOG_START_LINE=$((LOG_START_LINE + 1))
# ... pipeline 執行 ...
ERROR_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" | grep -c " - ERROR - ")
```

- **根因**：`tee -a` 追加寫入同一個日 log，每小時一次 ETL 的摘要行也含 "ERROR" 字樣
- **解法**：記下 pipeline 啟動時的行數，結束後只掃新增的行

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

### API 錯誤訊息防 info disclosure（OWASP A05:2021）

```python
# ❌ 反模式：把 str(e) 直接回給 client
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
    # client 可能看到：'column "sentiment_score" of relation "articles" does not exist'
    # → 洩漏 table / column 命名，幫助攻擊者拼湊 schema

# ✅ 正確：server log 完整 stacktrace，client 看 generic 訊息
except Exception:
    logging.exception("[API] load_articles_df 失敗")   # 完整 traceback 進 server log
    raise HTTPException(
        status_code=500,
        detail={"message": "database search failed"},   # 人類可讀但無細節
    )
```

- OWASP A05:2021 Security Misconfiguration 範例：錯誤訊息洩漏系統實作細節（SQL schema / 套件版本 / file path）
- `logging.exception(msg)`：自動附上當前 exception 的 traceback，不用 `str(e)` 拼接；比 `logging.error(str(e))` 資訊完整
- **client 訊息要夠抽象**讓人類 / 監控工具可讀（如 "database search failed"），但不透露細節
- **server log 保留全貌**給 on-call / 排錯使用
- 本專案 3 處修復：`load_articles_df()` / `/correlation/0050` / `/health`

---

## 十五、基礎設施擴充（Celery / Prometheus / Wayback / LLM Labeling）

### Celery 非同步任務佇列

```
celery_app.py → broker: Redis / backend: Redis / concurrency: 4
tasks.py → @app.task + pipeline 各 step → run_full_pipeline() chord
```

- **為何用 Celery**：pipeline 各步驟可非同步分發到 worker，支援重試、排程、分散式執行
- **Redis 雙角色**：同時作為 broker（傳遞任務）和 backend（儲存結果）
- **chord**：等所有子任務完成後才執行回呼（callback），適合 pipeline 依賴鏈
- **啟動指令**：`celery -A celery_app worker --loglevel=info`；`flower`（Web UI）

### Prometheus 監控指標

```python
# metrics.py
from prometheus_client import Counter, Gauge, Histogram
ARTICLES_SCRAPED = Counter('articles_scraped_total', 'Total articles scraped', ['source'])
PIPELINE_DURATION = Histogram('pipeline_duration_seconds', 'Pipeline step duration')
DB_CONNECTIONS = Gauge('db_connections_active', 'Active DB connections')
```

- **Counter**：只增不減（文章爬取數、錯誤數）
- **Gauge**：可增可減（當前 DB 連線數、記憶體使用）
- **Histogram**：分布統計 + 百分位（API 延遲、pipeline 執行時間）
- **Labels**：`['source']` 讓一個 Counter 追蹤多個來源，不用為每個來源建一個 Counter

### Wayback Machine 回填爬蟲

```
WaybackBackfillScraper(source="cnn"|"wsj")
  → CDX API 查詢 URL 列表（依時間範圍）
  → 逐一抓取 Wayback snapshot
  → 寫入 OLTP（sources / articles）
```

- **CDX API**：`http://web.archive.org/cdx/search/cdx?url=...&from=...&to=...`，回傳歷史快照 URL 列表
- **設計決策**：`wayback_cnn` / `wayback_wsj` 是次要補抓來源，**刻意不加入 SOURCES dict**（避免主爬蟲也跑 Wayback），由 pipeline.py 獨立工廠函式 `_wayback_cnn_factory` / `_wayback_wsj_factory` 管理
- **用途**：CNN `search.api.cnn.com` 域名死亡後，補回歷史缺失資料

### LLM 輔助情緒標注

```
get_unlabeled_articles(limit)  → LEFT JOIN article_labels WHERE NULL
  ↓
classify_with_llm(texts)  → Claude API Haiku → JSON array
  [{"text_index": 0, "sentiment": "positive", "confidence": 0.9}, ...]
  ↓
save_labels(article_ids, labels)  → INSERT article_labels ON CONFLICT DO UPDATE
```

- **模型選擇**：Claude Haiku（`claude-haiku-4-5-20251001`）— 情緒分類不需最強模型，降低 API 費用
- **批次設計**：`batch_size=50, max_batches=10`（預設）— `max_batches` 防止 API 費用失控
- **SAVEPOINT 設計**：每筆 INSERT 用 SAVEPOINT 包住，單筆失敗只回滾該筆，不汙染整個 transaction
- **Rate limit 處理**：`RateLimitError` 等 60 秒重試；`TimeoutError` / `StatusError` 跳過該批次
- **與 BERT fine-tune 的關係**：LLM 標注 → `article_labels` → BERT fine-tune 訓練資料 → 更準確的 `sentiment_scores`
- **CLI 指令**：`python cli.py llm-label --batch-size 50 --max-batches 10`

### perf_tuning.py — PostgreSQL 效能審計（檔案已於 2026-04 移除）

> 原 `perf_tuning.py` 已從 codebase 移除。下面為當時設計，留作後續若要恢復效能審計工具的參考：
>
> - `analyze_slow_queries()`：從 `pg_stat_statements` 取最慢 10 條，對 SELECT 執行 `EXPLAIN ANALYZE`
> - `check_index_usage()`：從 `pg_stat_user_indexes` 找 `idx_scan = 0` 的非 UNIQUE / 非 PK index（可刪）
> - `check_table_stats()`：dead tuple 超過 live tuple 10% 時警告需 VACUUM ANALYZE
> - `setup_connection_pool()`：建立 `psycopg2.ThreadedConnectionPool`（min=2, max=10），適合多執行緒 API server
> - **前提**：`analyze_slow_queries()` 需先執行 `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`

---

## 十六、Docker / Docker Compose

### Dockerfile 設計

- **Base image**：`python:3.9-slim`（輕量，只含 Python runtime）
- **WORKDIR /app**：所有後續指令的工作目錄，`COPY` 和 `CMD` 都相對於此
- **COPY 順序**：先 `requirements.txt` + `pip install`（利用 Docker layer cache），再 COPY source code；code 改動不會重裝套件
- **Runtime 讀取的檔案也要 COPY**：`data_mart.ensure_sp_schema()` 讀 `init_marts.sql` → 必須 `COPY scripts/init_marts.sql .`，否則 container 內 FileNotFoundError

### Docker Compose 服務編排

```yaml
# 7 services 完整本機部署
services:
  api:        # FastAPI（uvicorn）
  worker:     # ETL Worker（常駐 or CronJob 觸發）
  postgres:   # PostgreSQL 15
  redis:      # Redis 7（Cache + Celery broker）
  airflow-webserver:  # Airflow Web UI
  airflow-scheduler:  # Airflow 排程器
  airflow-init:       # Airflow 初始化（一次性）
```

- **`depends_on`**：確保啟動順序（api → postgres + redis）
- **`envFrom`**：環境變數從 `.env` 統一注入，不在 compose 裡寫死
- **Volume**：`postgres_data` 持久化 DB 資料；`airflow_logs` 保留排程 log

### workingDir vs COPY 路徑對齊

```dockerfile
COPY dependent_code/ .    # 檔案放在 /app/（WORKDIR）
```

```yaml
# K8s / Docker Compose 的 workingDir 必須與 COPY 目標一致
workingDir: /app          # ✅ 正確：/app/ 下有 pipeline.py、api.py 等
workingDir: /app/dependent_code  # ❌ 錯誤：目錄不存在，uvicorn 找不到模組
```

---

## 十七、Airflow DAG

### DAG 結構（本專案）

```
t1(create_schema) → t2(extract) → t3(transform) → t4(pii_masking) → t5(bert_inference)
  → t6(etf_and_matcher) → t7(dw_etl) → t8(backup) → t9(ai_prediction)
```

- **線性 pipeline**：`t1 >> t2 >> t3 >> ... >> t9`
- **9 個 PythonOperator**：每個 task 包一個 wrapper function，加 logging 方便追蹤

### trigger_rule='all_done'（fail-soft 設計）

```python
t4 = PythonOperator(task_id="pii_masking", trigger_rule="all_done")  # 即使上游失敗也執行
t5 = PythonOperator(task_id="bert_inference", trigger_rule="all_done")
```

- **預設**：`trigger_rule="all_success"` — 上游全部成功才跑
- **all_done**：上游完成（不管成敗）就跑 — 適合非關鍵步驟（PII / BERT / Backup）
- **效果**：PII 遮蔽失敗不會跳過後面的 BERT / DW ETL / Backup，pipeline 韌性更高

### sys.path 路徑解析（本機 vs Docker）

```python
# 本機：dags/ 往上 2 層到 project/，再進 dependent_code/
# Docker：dags/ 往上 1 層到 /opt/airflow/，再進 dependent_code/
_DAG_DIR = os.path.dirname(__file__)
for _levels in [os.path.join("..", ".."), ".."]:
    _candidate = os.path.abspath(os.path.join(_DAG_DIR, _levels, "dependent_code"))
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)
        break
```

- **為什麼要 for loop**：本機目錄結構（`project/airflow/dags/`）和 Docker（`/opt/airflow/dags/`）不同，往上幾層才找到 `dependent_code/` 取決於部署環境
- **`isdir()` 防禦**：只在目錄確實存在時才加入 `sys.path`，避免 ImportError

### default_args

```python
default_args = {
    "retries": 1,                           # 失敗自動重試 1 次
    "retry_delay": timedelta(minutes=5),     # 重試間隔 5 分鐘
    "on_failure_callback": _on_task_failure, # 失敗回呼（log + 未來可接 Slack/Email）
}
```

---

## 十八、Kubernetes（K8s）

### 核心物件

| 物件 | 用途 | 本專案對應 |
|------|------|-----------|
| **Deployment** | 管理 Pod 副本數、滾動更新 | api-deployment（2 replicas）|
| **Service** | 穩定的網路入口（不因 Pod 重啟改 IP）| api-service（LoadBalancer, port 8000）|
| **CronJob** | 定時排程（類似 crontab）| etl-cronjob（每小時 :25 分）|
| **ConfigMap** | 非敏感環境變數 | stock-sentiment-config |
| **Secret** | 敏感環境變數（base64 encoded）| stock-sentiment-secret |

### 健康檢查（Probes）

```yaml
livenessProbe:       # 偵測容器是否卡死 → 失敗時 K8s 自動重啟
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 15   # 給 uvicorn 啟動時間
  failureThreshold: 3       # 連續 3 次失敗才判定不健康

readinessProbe:      # 偵測容器是否準備好接收流量 → 未通過前不導入流量
  httpGet:
    path: /health
    port: 8000
```

- **liveness vs readiness**：liveness 管「要不要重啟」，readiness 管「要不要導流量」
- **initialDelaySeconds**：容器啟動後等 N 秒再開始檢查（uvicorn / Spark 啟動需要時間）

### CronJob 併發策略

```yaml
concurrencyPolicy: Forbid    # 前一次還在跑時，不啟動新的
startingDeadlineSeconds: 200  # 錯過排程，最多容忍 200 秒內補跑
backoffLimit: 0               # 失敗不重試（下一個排程重新跑）
```

- **Forbid**：避免兩個 ETL 同時跑造成資料衝突（重複爬取、DB 鎖競爭）
- **backoffLimit: 0**：ETL 冪等設計，失敗就等下一個排程重跑，不浪費資源重試

### envFrom 環境變數注入

```yaml
envFrom:
  - configMapRef:
      name: stock-sentiment-config   # 非敏感：PG_HOST, REDIS_HOST
  - secretRef:
      name: stock-sentiment-secret   # 敏感：PG_PASSWORD, JWT_SECRET_KEY
```

- ConfigMap + Secret 分離：非敏感設定可直接 `kubectl describe`，敏感設定 base64 encoded
- 程式碼用 `os.environ.get()` 讀取，不區分來源

---

## 十九、BTC Pipeline — 大資料實踐

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

## 十五、專案檔案相依性架構圖

### 全域總覽 — 從 CI/CD 到每個檔案

```
push to main
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  deploy.yml（CI/CD 總控）                                        │
│                                                                 │
│  test ──→ build ──┬──→ deploy-docker ──→ post-deploy            │
│                   └──→ deploy-k8s                               │
│                                                                 │
│  [手動觸發] ec2-setup       → scripts/ec2_setup.sh              │
│  [手動觸發] wayback-backfill → scripts/wayback_full_backfill.sh  │
└─────────────────────────────────────────────────────────────────┘
```

### deploy.yml 各 Job 觸發的檔案

```
deploy.yml
    │
    ├── test
    │     └── dependent_code/test_api.py
    │
    ├── build
    │     └── Dockerfile
    │           ├── COPY dependent_code/requirements.txt  （先裝套件，利用 layer cache）
    │           ├── COPY dependent_code/                  （應用程式碼）
    │           └── COPY scripts/init_marts.sql           （SP/Function 定義）
    │
    ├── deploy-docker ── SSH to EC2
    │     └── scripts/deploy.sh
    │           ├── git pull
    │           ├── docker-compose build  ← Dockerfile
    │           ├── docker-compose up -d  ← docker-compose.yml
    │           │     ├── api        ← Dockerfile（FastAPI）
    │           │     ├── worker     ← Dockerfile（pipeline.py）
    │           │     ├── postgres   ← image: postgres:16
    │           │     ├── redis      ← image: redis:7
    │           │     ├── airflow-*  ← image: apache/airflow:2.9.3
    │           │     │     └── mount: airflow/dags/etl_dag.py
    │           │     ├── prometheus ← image: prom/prometheus
    │           │     │     └── mount: prometheus.yml
    │           │     └── grafana   ← image: grafana/grafana
    │           │           ├── mount: grafana/provisioning/datasources/prometheus.yml
    │           │           ├── mount: grafana/provisioning/dashboards/dashboard.yml
    │           │           └── mount: grafana/dashboards/etl-dashboard.json
    │           └── scripts/health_check.sh
    │                 └── 檢查 FastAPI / PG / Redis / Airflow
    │
    ├── deploy-k8s
    │     └── k8s/（按順序 apply）
    │           ├── 1. namespace.yaml       ← 建立 stock-sentiment 命名空間
    │           ├── 2. configmap.yaml       ← 非敏感環境變數（PG_HOST 等）
    │           ├── 3. secret.yaml          ← 敏感資料（密碼、JWT key）
    │           ├── 4. postgres-deployment.yaml  ← StatefulSet + PVC + Service
    │           ├── 5. redis-deployment.yaml     ← Deployment + Service
    │           ├── 6. api-deployment.yaml       ← 2 replicas + LoadBalancer
    │           └── 7. cronjob.yaml              ← 每小時 :25 跑 pipeline.py（每次新 Pod，跑完自刪）
    │
    └── post-deploy
          ├── health check（外部 curl）
          └── scripts/dbt.sh ──→ dbt/（見下方 dbt 架構圖）
```

### 監控鏈 — metrics 從產生到呈現

```
程式碼記錄指標              Prometheus 收集           Grafana 呈現
┌──────────────┐          ┌──────────────┐         ┌──────────────┐
│  api.py      │  :8001   │ prometheus   │  :9090  │  grafana     │  :3000
│  pipeline.py ├─/metrics→│              ├────────→│              │
│  scrapers/   │          │ prometheus   │         │ provisioning/│
│              │          │   .yml       │         │  datasources/│
│  metrics.py  │          │（每15秒抓）   │         │   prometheus │
│ （指標定義）  │          └──────────────┘         │   .yml       │
└──────────────┘                                   │              │
                                                   │ dashboards/  │
                                                   │  etl-dashboard
                                                   │   .json      │
                                                   └──────────────┘
```

### dbt 檔案相依性

```
scripts/dbt.sh                        dbt_project.yml
  │                                     │
  ├── source .env（載入環境變數）         ├── name: ptt_sentiment
  └── exec dbt run                      ├── profile: ptt_sentiment ──→ profiles.yml
        │                               │                               │
        ▼                               ├── model-paths: [models]       ├── dev（PostgreSQL）
   profiles.yml                         │                               │    └── env_var('PG_HOST') ← .env
     │                                  └── materialization:            └── bigquery（placeholder）
     ├── env_var('PG_HOST') ← .env            staging → view
     ├── env_var('PG_PORT') ← .env            marts   → table
     └── env_var('PG_PASSWORD') ← .env
                                        packages.yml
                                          └── dbt-labs/dbt_utils ──→ dbt deps 安裝

                       ┌─────────────── dbt 資料流 ───────────────┐

    PostgreSQL OLTP                staging/（view）              marts/（table）
  ┌──────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
  │ articles         │     │ stg_articles.sql     │     │ fact_sentiment.sql  │
  │ sources          │────→│ stg_sources.sql      │────→│   ref(stg_articles) │
  │ sentiment_scores │     │ stg_sentiment_scores │     │   ref(stg_sources)  │
  └──────────────────┘     │   .sql               │     │   ref(stg_sentiment)│
         ▲                 └──────────────────────┘     └────────┬────────────┘
         │                  source('ptt','articles')             │
    sources.yml                                                  │ ref(fact_sentiment)
    （宣告 OLTP 表）                                              ▼
                                                        ┌─────────────────────┐
                                                        │ mart_daily_summary  │
                                                        │   .sql              │
                                                        └─────────────────────┘
                                                                 ▲
                                                           schema.yml
                                                          （定義 test：
                                                           not_null,
                                                           unique_combination）
```

### 本機排程 vs 容器化排程

```
┌── 本機（launchd）──────────────────────┐
│                                        │
│  每小時 :25                             │
│  └── scripts/run_etl.sh               │
│        ├── source .env                 │
│        ├── python pipeline.py          │
│        ├── python backup.py            │
│        └── python ge_validation.py     │
│                                        │
│  每天 03:00                             │
│  └── scripts/run_wayback_backfill.sh   │  ← wayback_full_backfill.sh 是手動版
│        ├── cli.py wayback-backfill cnn │
│        └── cli.py wayback-backfill wsj │
└────────────────────────────────────────┘

┌── Docker Compose ──────────────────────┐
│                                        │
│  airflow-scheduler（常駐）              │
│  └── airflow/dags/etl_dag.py          │
│        └── 每小時 :25 觸發 9 個 task    │
│           t1 schema → t2 extract →     │
│           t3 transform → t4 pii →      │
│           t5 bert → t6 match →         │
│           t7 dw_etl → t8 backup →      │
│           t9 ai_prediction             │
└────────────────────────────────────────┘

┌── Kubernetes ──────────────────────────┐
│                                        │
│  cronjob.yaml（K8s 原生排程）           │
│  └── 每小時 :25 建立 Job Pod            │
│        └── python pipeline.py          │
└────────────────────────────────────────┘

三者做同一件事，差別是環境：
  本機 → launchd + run_etl.sh
  Docker → Airflow DAG
  K8s → CronJob
```

---

### Docker 容器 DB 命名陷阱

**症狀**：`FATAL: database "stock_analysis_db" does not exist` — pipeline 每小時失敗，但 DB 資料明明在。

**根本原因**：Docker volume 保存的是「資料」，DB 名稱由容器初始化時的環境變數（`POSTGRES_DB`）決定。如果改了 `.env` 的 `PG_DBNAME` 但 Docker 容器沒有重建，或改名後 volume 被刪掉重建，兩邊就會分裂。

**6 個地方必須同步**（改 DB 名稱時缺一不可）：

| 檔案 | 位置 | 用途 |
|------|------|------|
| `.env` | `PG_DBNAME=xxx` | 主要設定 |
| `config.py` | `PG_CONFIG["dbname"]` fallback | 環境變數缺席時的保底值 |
| `backup.py` | `pg_dbname` fallback | `pg_dump` 目標 DB |
| `schema.py` | `dbname` fallback | `GRANT CONNECT ON DATABASE` |
| `docker-compose.yml` | `POSTGRES_DB` + Airflow `SQL_ALCHEMY_CONN` | Docker 初始化 DB 名稱 + Airflow metadata |
| `k8s/configmap.yaml` | `PG_DBNAME` | K8s Pod 環境變數 |

**MongoDB 不受影響**：`mongo_helper.py` 的 `MONGO_DB = "stock_analysis_db"` 是 MongoDB 資料庫名稱，和 PostgreSQL 是不同系統，刻意保留。

---

---

## 二十、dbt（Data Build Tool）

### dbt 分層架構與 Staging Layer

```
OLTP（sources.yml 登記）→ Staging（stg_.sql, view）→ Mart（mart_.sql, table）
```

- **OLTP 表**：不建 .sql，只在 `sources.yml` 登記；dbt 不動它，直接引用
- **Staging（stg_）**：每張 OLTP 表對應一個 .sql，`materialized='view'`，空殼（不存資料）
- **Mart（mart_）**：業務需求決定，多張 stg JOIN/聚合出一張

### source() 函式

```sql
{{ source('ptt', 'sentiment_scores') }}
-- 展開成 → ptt.sentiment_scores
```

- 綁定 `sources.yml`（檔名不重要，只要內容有 `sources:` key dbt 就讀）
- 好處：schema 改名只改 yml；dbt docs 自動畫血緣圖；可設 freshness 警告

### config() macro

```python
{{ config(materialized='view') }}
```

- dbt 層設定，不碰 DB；`dbt run` 時才真正對 DB 執行 DDL
- `view` = 空殼，查詢時即時跑 SELECT FROM OLTP；不存資料

### CAST + dbt.type_*()

```sql
CAST(score AS {{ dbt.type_float() }})
```

| DB | type_int() | type_float() | type_timestamp() |
|----|-----------|--------------|-----------------|
| PostgreSQL | INTEGER | FLOAT | TIMESTAMP |
| BigQuery | INT64 | FLOAT64 | DATETIME |

換 DB 不用改 SQL，dbt 自動適配。

### Staging 做什麼、不做什麼

- **做**：型別標準化（CAST）、隔離 OLTP 型別不確定性
- **不做**：改欄位名、加計算欄位、JOIN 其他表、過濾資料

### .sql 數量邏輯

- OLTP 有 N 張表 → Staging 有 N 個 `stg_.sql`（1:1）
- Mart 數量由業務需求決定，不由表數量決定
- 總 .sql = N（stg）+ M（mart）+ K（int，可選）

### View vs 其他 materialization

| 類型 | 存資料？ | 查詢時 |
|------|---------|--------|
| `view` | 否 | 每次即時查原始表 |
| `table` | 是 | 查已存的快照 |
| `incremental` | 是 | 只新增異動 |
| `ephemeral` | 否 | 直接內嵌成 CTE |

---

---

### DW Schema 版本控管注意事項（2026-04-22）

- `fact_sentiment` 從舊版 `date_id INTEGER FK → dim_date` 遷移至 `fact_date DATE`（直接存日期）
- 遷移方式：DROP 空表重建（表為空時最安全）；若有資料則需 `ALTER TABLE ADD COLUMN + UPDATE + DROP COLUMN`
- **下次改 DW schema 前必須確認 Homebrew PG（port 5432）和 Docker PG（port 5433）的實際表結構與程式碼 DDL 一致**
- `SOURCE_META` 只衍生自 `SOURCES` dict；Wayback 等非主流爬蟲需手動補入

### Timing-Safe 認證模式（2026-04-23）

`auth.py` 的 `_TIMING_DUMMY_HASH` 模式：username 不存在時仍跑一次 bcrypt.verify，防止 timing attack 推測帳號列表。

**陷阱**：`stored_hash = user["pw_hash"] if user else _TIMING_DUMMY_HASH`  
→ user 存在但 pw_hash=None（env var 未設）時，`stored_hash` 為 None，`verify(password, None)` 拋 ValueError（500）而非 401。

**修法**：`stored_hash = (user["pw_hash"] if user else None) or _TIMING_DUMMY_HASH`  
→ 三種情況全覆蓋：user 不存在 / user 存在但 hash 未設 / user 存在且 hash 有值

**結論**：timing-safe 模式必須確保 dummy_hash 在所有情況都能被使用，不能讓 None 滲透進 verify()。

### Shell Script 自引 Bug（run_etl.sh，2026-04-25）

`>>` detail 行格式：`[timestamp]   >> [timestamp] ERROR: ...`，本身含有 `ERROR:` 子字串。

**Bug**：`grep -cE "\[ERROR\]|ERROR:"` 下次執行會命中 `>> ERROR:` 行，並再次被 `log "  >> $line"` 展開 → 每輪執行 ERROR count 指數倍增（1→6→16→36→...→862）。

**修法**：count 和 detail 兩處 grep 前先 `grep -v "  >>"` 過濾已展開的 detail 行。

**原則**：log 工具本身的輸出絕對不能匹配自己的偵測 pattern，否則形成正回饋迴路。

### DB Migration Robustness（dw_schema.py，2026-04-25）

`IF EXISTS ... AND column = 'fact_date'` 只覆蓋一種舊 schema，遇到其他舊 schema 仍靜默跳過 → `CREATE TABLE IF NOT EXISTS` 也不重建 → `CREATE INDEX` 因 column 不存在而 crash。

**修法**：改成「若表存在但不含 `summary_date`（目標欄位）就 DROP」，邏輯反轉後自動覆蓋所有舊 schema 情境。

**原則**：migration guard 應檢查「預期 schema 是否存在」而非「舊 schema 是否存在」。

### 第三方 SDK Transient Failure：yfinance `'NoneType' object is not subscriptable`（us_stock_fetcher.py，2026-04-28）

yfinance 1.2.0 在 Yahoo Finance API rate-limit 期間，內部 `_history_metadata` 被設為 None；`Ticker(_TICKER).history(start=...)` 後續 subscript 操作直接 raise `'NoneType' object is not subscriptable`。錯誤訊息看起來像 caller 的 logic bug，實際是上游 SDK 的 transient state corruption。

**Bug**：2026-04-27 07:28~11:27 連續 5 小時 ETL 看到 `[Extract] 失敗：UsStockFetcher — 'NoneType' object is not subscriptable`；只在那 5 小時內失敗，前後正常 → 上游 rate-limit 視窗。

**修法**：
1. `try/except Exception` 包整個 `yf.Ticker(_TICKER).history(start=start)` 呼叫，捕捉 SDK 內部任何錯誤
2. 3 次 retry + exponential backoff（5s/15s/30s），跨過短暫 rate-limit 視窗
3. 連續失敗時 `return []` fallback，不中斷 pipeline——歷史資料已存於 `us_stock_prices`，下輪 1 小時後自動重試
4. Python 3.9 相容：`Optional[Exception]` 而非 PEP 604 `Exception | None`

**原則**：上游 SDK 在 rate-limit / transient 時可能回傳 None 或拋意外 exception，**caller 必須假設不可信**：(1) try/except 包外部 I/O (2) retry with backoff (3) fallback 不中斷主流程。

*最後更新：2026-04-28*
