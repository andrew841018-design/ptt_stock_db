#!/bin/bash
# ─── 健康檢查腳本 ────────────────────────────────────────────────────
# 用途：逐一檢查所有服務是否正常運作
# 使用方式：bash scripts/health_check.sh
# 回傳值：0 = 全部通過；1 = 有服務異常
# ────────────────────────────────────────────────────────────────────

# ─── 顏色定義 ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ─── 計數器 ────────────────────────────────────────────────────────────
PASS=0
FAIL=0
TOTAL=0

# ─── 檢查函式 ──────────────────────────────────────────────────────────

check_service() {
    # $1: 服務名稱
    # $2: 檢查指令（eval 執行）
    local service_name="$1"
    local check_cmd="$2"
    TOTAL=$((TOTAL + 1))

    if eval "$check_cmd" > /dev/null 2>&1; then
        echo -e "  ${GREEN}[PASS]${NC} ${service_name}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} ${service_name}"
        FAIL=$((FAIL + 1))
    fi
}

# ─── 開始檢查 ──────────────────────────────────────────────────────────

echo ""
echo "===== 健康檢查開始 ====="
echo ""

# 1. FastAPI（REST API）
#    檢查 /health endpoint 是否回傳 200
check_service \
    "FastAPI (http://localhost:8000/health)" \
    "curl -sf --max-time 10 http://localhost:8000/health"

# 3. PostgreSQL（主資料庫）
#    使用 pg_isready 檢查連線狀態
if command -v pg_isready &> /dev/null; then
    check_service \
        "PostgreSQL (localhost:5432)" \
        "pg_isready -h localhost -p 5432 -q"
else
    # pg_isready 未安裝時，改用 Docker exec 檢查
    # 容器名稱與 docker-compose.yml 的 container_name 對齊
    check_service \
        "PostgreSQL (localhost:5432)" \
        "docker exec stock_postgres pg_isready -q"
fi

# 4. Redis（快取 + Celery broker）
#    使用 redis-cli ping 檢查，預期回傳 PONG
if command -v redis-cli &> /dev/null; then
    check_service \
        "Redis (localhost:6379)" \
        "redis-cli -h localhost -p 6379 ping | grep -q PONG"
else
    # redis-cli 未安裝時，改用 Docker exec 檢查
    # 容器名稱與 docker-compose.yml 的 container_name 對齊
    check_service \
        "Redis (localhost:6379)" \
        "docker exec stock_redis redis-cli ping | grep -q PONG"
fi

# 5. Airflow（排程器）
#    檢查 /health endpoint 是否回傳 200
check_service \
    "Airflow (http://localhost:8080/health)" \
    "curl -sf --max-time 10 http://localhost:8080/health"

# ─── 檢查摘要 ──────────────────────────────────────────────────────────

echo ""
echo "===== 檢查結果 ====="
echo ""
echo -e "  通過：${GREEN}${PASS}${NC} / ${TOTAL}"
echo -e "  失敗：${RED}${FAIL}${NC} / ${TOTAL}"
echo ""

# 任何服務失敗則回傳 exit code 1
if [ $FAIL -gt 0 ]; then
    echo -e "${YELLOW}[WARN] 有 ${FAIL} 個服務未通過健康檢查${NC}"
    exit 1
else
    echo -e "${GREEN}[OK] 所有服務正常運作${NC}"
    exit 0
fi
