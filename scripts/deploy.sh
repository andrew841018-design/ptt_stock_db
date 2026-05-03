#!/bin/bash
# ─── 部署腳本 ────────────────────────────────────────────────────────
# 用途：拉取最新程式碼、建構 Docker image、啟動所有服務、驗證健康狀態
# 使用方式：bash scripts/deploy.sh
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─── 路徑設定 ──────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="${PROJECT_DIR}/scripts"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"

# ─── 顏色定義（終端機輸出用）──────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

# ─── 輔助函式 ──────────────────────────────────────────────────────────

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 檢查指令是否存在
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "找不到指令：$1，請先安裝"
        exit 1
    fi
}

# ─── 前置檢查 ──────────────────────────────────────────────────────────

log_info "===== 部署開始 ====="
log_info "專案目錄：${PROJECT_DIR}"

# 確認必要工具已安裝
check_command git
check_command docker
check_command docker-compose

# 確認 Docker daemon 正在執行
if ! docker info &> /dev/null; then
    log_error "Docker daemon 未啟動，請先啟動 Docker Desktop"
    exit 1
fi

# 確認 docker-compose.yml 存在
if [ ! -f "${COMPOSE_FILE}" ]; then
    log_error "找不到 docker-compose.yml：${COMPOSE_FILE}"
    exit 1
fi

# ─── Step 1：拉取最新程式碼 ────────────────────────────────────────────

log_info "Step 1/5：拉取最新程式碼"
cd "${PROJECT_DIR}"

# 檢查是否有未提交的變更
if ! git diff --quiet || ! git diff --cached --quiet; then
    log_warn "偵測到未提交的變更，建議先 commit 或 stash"
    git status --short
fi

# 拉取最新程式碼（使用 rebase 保持線性歷史）
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
log_info "當前分支：${CURRENT_BRANCH}"
git pull origin "${CURRENT_BRANCH}" --rebase || {
    log_error "git pull 失敗，請手動解決衝突"
    exit 1
}
log_info "程式碼已更新至最新版本"

# ─── Step 2：建構 Docker image ─────────────────────────────────────────

log_info "Step 2/5：建構 Docker image"
docker-compose -f "${COMPOSE_FILE}" build --no-cache || {
    log_error "Docker image 建構失敗"
    exit 1
}
log_info "Docker image 建構完成"

# ─── Step 3：啟動所有服務 ──────────────────────────────────────────────

log_info "Step 3/5：啟動所有服務"

# 先停止舊容器（如果有的話）
docker-compose -f "${COMPOSE_FILE}" down --remove-orphans 2>/dev/null || true

# 啟動所有服務（背景執行）
docker-compose -f "${COMPOSE_FILE}" up -d || {
    log_error "Docker Compose 啟動失敗"
    exit 1
}
log_info "所有容器已啟動"

# ─── Step 4：等待服務就緒 ──────────────────────────────────────────────

log_info "Step 4/5：等待服務就緒"

MAX_WAIT=120    # 最多等待 120 秒
INTERVAL=5      # 每 5 秒檢查一次
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # 檢查所有容器是否都在 running 狀態
    RUNNING=$(docker-compose -f "${COMPOSE_FILE}" ps --services --filter "status=running" 2>/dev/null | wc -l | tr -d ' ')
    TOTAL=$(docker-compose -f "${COMPOSE_FILE}" ps --services 2>/dev/null | wc -l | tr -d ' ')

    if [ "$RUNNING" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
        log_info "所有服務已就緒（${RUNNING}/${TOTAL}）"
        break
    fi

    log_info "等待服務啟動中...（${ELAPSED}/${MAX_WAIT} 秒，已就緒 ${RUNNING}/${TOTAL}）"
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    log_error "服務啟動逾時（超過 ${MAX_WAIT} 秒）"
    log_error "容器狀態："
    docker-compose -f "${COMPOSE_FILE}" ps
    exit 1
fi

# ─── Step 5：健康檢查 ──────────────────────────────────────────────────

log_info "Step 5/5：執行健康檢查"

if [ -x "${SCRIPTS_DIR}/health_check.sh" ]; then
    bash "${SCRIPTS_DIR}/health_check.sh"
    HEALTH_EXIT=$?
else
    log_warn "找不到 health_check.sh，跳過健康檢查"
    HEALTH_EXIT=0
fi

# ─── 部署摘要 ──────────────────────────────────────────────────────────

echo ""
echo "==========================================="
if [ $HEALTH_EXIT -eq 0 ]; then
    log_info "部署成功"
else
    log_warn "部署完成，但部分健康檢查未通過"
fi
echo "==========================================="
echo ""

# 顯示所有容器狀態
log_info "容器狀態："
docker-compose -f "${COMPOSE_FILE}" ps

echo ""
log_info "服務端點："
echo "  - API:        http://localhost:8000"
echo "  - API 文件:   http://localhost:8000/docs"
echo "  - Airflow:    http://localhost:8080"
echo "  - Prometheus: http://localhost:9090"
echo "  - Grafana:    http://localhost:3000"
echo ""

exit $HEALTH_EXIT
