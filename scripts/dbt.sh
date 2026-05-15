#!/bin/bash
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
source "$ENV_FILE"
set +a

cd "$DBT_DIR"
exec "$DBT_BIN" "$@"
