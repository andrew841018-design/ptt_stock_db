#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  k8s_debug_pod.sh — 在 K8s 叢集臨時起一個 debug Pod
#
#  取代：舊版 worker-deployment.yaml 的 idle 常駐 Pod
#  好處：要用才起、`--rm` 退出自動刪，不占資源
#
#  用法：
#    ./scripts/k8s_debug_pod.sh                    # 互動式 bash
#    ./scripts/k8s_debug_pod.sh python cli.py qa   # 跑完立即結束
#
#  進去後可手動跑：
#    python cli.py pipeline
#    python cli.py bert infer
#    python cli.py reparse
#    python cli.py mongo
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

NAMESPACE="stock-sentiment"
IMAGE="stock-sentiment-worker:latest"
POD_NAME="debug-$(date +%s)"

command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl 未安裝" >&2; exit 1; }

# 如果使用者傳參數 → 當命令執行；沒傳 → 開 bash
if [ $# -gt 0 ]; then
    CMD=("$@")
else
    CMD=(bash)
fi

# --rm：Pod 退出自動刪除
# -it：互動 + tty
# --overrides：一次注入 ConfigMap + Secret（和正式 Deployment 一致）
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
