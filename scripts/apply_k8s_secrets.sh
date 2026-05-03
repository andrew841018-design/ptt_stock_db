#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  apply_k8s_secrets.sh — 從 .env 產生並 apply K8s Secret
#
#  流程：
#    1. 讀取 .env（PG_PASSWORD / PG_API_PASSWORD / JWT_SECRET_KEY / PII_HASH_SALT）
#    2. 確保 namespace 存在
#    3. 用 `kubectl create secret --dry-run=client -o yaml | kubectl apply -f -`
#       做 idempotent upsert（沒有 → 建、已有 → 更新）
#
#  用法：
#    ./scripts/apply_k8s_secrets.sh
#    python dependent_code/cli.py k8s-apply-secrets
#
#  設計原因：
#    - K8s Secret 的 data: 欄位是 base64（不加密），直接 commit 真密碼 = 洩漏
#    - 真密碼統一放 .env（已 gitignore），部署前從 .env 動態生成 Secret
#    - kubectl create --from-literal 會自動幫你做 base64 編碼，不用手動跑
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
NAMESPACE="stock-sentiment"
SECRET_NAME="stock-sentiment-secret"

command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl 未安裝" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "❌ .env 不存在：$ENV_FILE" >&2; exit 1; }

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# 確保 namespace 存在（idempotent）
kubectl apply -f "$PROJECT_DIR/k8s/namespace.yaml" >/dev/null

# 產生 / 更新 Secret（${VAR:?msg} 在未設定時會 fail fast）
kubectl create secret generic "$SECRET_NAME" \
    --namespace="$NAMESPACE" \
    --from-literal=PG_PASSWORD="${PG_PASSWORD:?PG_PASSWORD 未設定於 .env}" \
    --from-literal=PG_API_PASSWORD="${PG_API_PASSWORD:?PG_API_PASSWORD 未設定於 .env}" \
    --from-literal=JWT_SECRET_KEY="${JWT_SECRET_KEY:?JWT_SECRET_KEY 未設定於 .env}" \
    --from-literal=PII_HASH_SALT="${PII_HASH_SALT:?PII_HASH_SALT 未設定於 .env}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✅ K8s Secret '$SECRET_NAME' 已從 .env 同步到 namespace '$NAMESPACE'"
