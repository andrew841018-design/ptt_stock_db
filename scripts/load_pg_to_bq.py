#!/usr/bin/env python3
"""
PG → BigQuery 一次性載入 raw 3 張表。

使用前準備：
  1. gcloud auth login
  2. gcloud config set project <GCP_PROJECT>
  3. bq mk --dataset --location=US <PROJECT>:ptt_sentiment
  4. export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
  5. export GCP_PROJECT=<your-project>

執行：
  /Users/andrew/opt/anaconda3/envs/de_project/bin/python scripts/load_pg_to_bq.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dependent_code"))

import pandas as pd
from pg_helper import get_pg
from google.cloud import bigquery

GCP_PROJECT = os.environ.get("GCP_PROJECT")
BQ_DATASET = os.environ.get("BQ_DATASET", "ptt_sentiment")
TABLES = ["sources", "articles", "sentiment_scores"]

if not GCP_PROJECT:
    sys.exit("請先 export GCP_PROJECT=<your-project>")

client = bigquery.Client(project=GCP_PROJECT)


def load_table(name: str) -> None:
    print(f"[{name}] 從 PG 讀取…")
    with get_pg() as conn:
        df = pd.read_sql(f"SELECT * FROM {name}", conn)
    print(f"[{name}] {len(df)} rows，寫入 BigQuery…")

    table_id = f"{GCP_PROJECT}.{BQ_DATASET}.{name}"
    job = client.load_table_from_dataframe(
        df,
        table_id,
        job_config=bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        ),
    )
    job.result()
    print(f"[{name}] ✅ 載入完成 → {table_id}")


if __name__ == "__main__":
    for t in TABLES:
        load_table(t)
    print("\n全部載入成功，接下來跑：")
    print("  cd dbt && dbt run --target bigquery --profiles-dir .")
