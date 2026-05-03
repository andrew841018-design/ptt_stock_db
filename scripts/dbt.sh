#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  dbt wrapper — 確保 .env 載入到 shell env，dbt env_var() 才讀得到
#
#  用法：
#    ./scripts/dbt.sh debug
#    ./scripts/dbt.sh run
#    ./scripts/dbt.sh test
#    ./scripts/dbt.sh run --target bigquery
#
#  設計考量：
#    1. `set -a` 自動 export 所有 source 進來的變數，dbt subprocess 繼承
#    2. 固定用 conda env `de_project` 的 dbt（避免 PATH 髒）
#    3. cd 到 dbt/ 目錄，dbt 預設會在該目錄找 profiles.yml / dbt_project.yml
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
DBT_DIR="$PROJECT_DIR/dbt"
DBT_BIN="/Users/andrew/opt/anaconda3/envs/de_project/bin/dbt"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ .env 不存在：$ENV_FILE" >&2
    exit 1
fi

if [ ! -x "$DBT_BIN" ]; then
    echo "❌ dbt 執行檔不存在：$DBT_BIN" >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

cd "$DBT_DIR"
exec "$DBT_BIN" "$@"
