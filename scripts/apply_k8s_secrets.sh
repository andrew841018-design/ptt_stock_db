#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
NAMESPACE="stock-sentiment"
SECRET_NAME="stock-sentiment-secret"

command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl 未安裝" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "❌ .env 不存在：$ENV_FILE" >&2; exit 1; }

set -a
source "$ENV_FILE"
set +a

kubectl apply -f "$PROJECT_DIR/k8s/namespace.yaml" >/dev/null

kubectl create secret generic "$SECRET_NAME" \
    --namespace="$NAMESPACE" \
    --from-literal=PG_PASSWORD="${PG_PASSWORD:?PG_PASSWORD 未設定於 .env}" \
    --from-literal=PG_API_PASSWORD="${PG_API_PASSWORD:?PG_API_PASSWORD 未設定於 .env}" \
    --from-literal=JWT_SECRET_KEY="${JWT_SECRET_KEY:?JWT_SECRET_KEY 未設定於 .env}" \
    --from-literal=PII_HASH_SALT="${PII_HASH_SALT:?PII_HASH_SALT 未設定於 .env}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✅ K8s Secret '$SECRET_NAME' 已從 .env 同步到 namespace '$NAMESPACE'"
