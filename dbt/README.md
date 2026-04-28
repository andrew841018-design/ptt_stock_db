# ptt_sentiment dbt project

PTT 股票情緒分析的 dbt 層，同一份 SQL 可跑在 PostgreSQL（`--target dev`）或 BigQuery（`--target bigquery`）。

## 結構

```
dbt/
├── dbt_project.yml         # 專案設定
├── profiles.yml            # dev（PG）+ bigquery 兩個 target
├── macros/
│   └── count_if.sql        # 跨 adapter 的 COUNT FILTER / COUNTIF
└── models/
    ├── staging/            # view：型別投射 + 欄位重命名
    │   ├── _sources.yml    # ptt source 定義 + 欄位測試
    │   ├── stg_articles.sql
    │   ├── stg_sentiment_scores.sql
    │   └── stg_sources.sql
    └── marts/              # table：實際 DW 事實 + mart
        ├── _schema.yml     # 欄位測試 + 文件
        ├── fact_sentiment.sql       # (fact_date × source_id) 粒度
        └── mart_daily_summary.sql   # 加 pos_ratio / neg_ratio
```

## 跨 adapter 做法

1. **型別 CAST**：用 `{{ dbt.type_int() }}` / `{{ dbt.type_float() }}` / `{{ dbt.type_string() }}` / `{{ dbt.type_timestamp() }}` 宏，PG → `INTEGER/FLOAT/TEXT/TIMESTAMP`，BQ → `INT64/FLOAT64/STRING/TIMESTAMP`
2. **Conditional count**：自訂 `count_if(condition)` macro 做 adapter dispatch
   - PG / default：`COUNT(*) FILTER (WHERE ...)`
   - BigQuery：`COUNTIF(...)`
3. **Date truncation**：用 `{{ dbt.date_trunc(...) }}` 宏

## 用法

### PostgreSQL（dev）

```bash
cd dbt
dbt deps                                    # 不需要套件也可跳過
dbt run --target dev --profiles-dir .
dbt test --target dev --profiles-dir .
```

### BigQuery（cloud）

準備：
```bash
gcloud auth login
gcloud config set project $GCP_PROJECT
bq mk --dataset --location=US $GCP_PROJECT:ptt_sentiment

export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
export GCP_PROJECT=your-gcp-project
export BQ_DATASET=ptt_sentiment
export DBT_RAW_SCHEMA=ptt_sentiment        # BQ 時 source schema = dataset 名

# 載入 PG raw 資料進 BQ
python ../scripts/load_pg_to_bq.py

# 跑 dbt
cd dbt
dbt run --target bigquery --profiles-dir .
dbt test --target bigquery --profiles-dir .
```
