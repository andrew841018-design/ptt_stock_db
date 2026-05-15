#!/bin/bash
set -euo pipefail

NAMESPACE="stock-sentiment"
IMAGE="stock-sentiment-worker:latest"
POD_NAME="debug-$(date +%s)"

command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl 未安裝" >&2; exit 1; }

if [ $# -gt 0 ]; then
    CMD=("$@")
else
    CMD=(bash)
fi

kubectl run "$POD_NAME" \
    --namespace="$NAMESPACE" \
    --image="$IMAGE" \
    --image-pull-policy=Always \
    --restart=Never \
    --rm -it \
    --overrides='{
      "spec": {
        "containers": [{
          "name": "'"$POD_NAME"'",
          "image": "'"$IMAGE"'",
          "stdin": true,
          "tty": true,
          "workingDir": "/app",
          "envFrom": [
            {"configMapRef": {"name": "stock-sentiment-config"}},
            {"secretRef":    {"name": "stock-sentiment-secret"}}
          ]
        }]
      }
    }' \
    -- "${CMD[@]}"
