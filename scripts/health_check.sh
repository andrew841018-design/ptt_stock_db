#!/bin/bash

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
TOTAL=0


check_service() {
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


echo ""
echo "===== 健康檢查開始 ====="
echo ""

check_service \
    "FastAPI (http://localhost:8000/health)" \
    "curl -sf --max-time 10 http://localhost:8000/health"

if command -v pg_isready &> /dev/null; then
    check_service \
        "PostgreSQL (localhost:5432)" \
        "pg_isready -h localhost -p 5432 -q"
else
    check_service \
        "PostgreSQL (localhost:5432)" \
        "docker exec stock_postgres pg_isready -q"
fi

if command -v redis-cli &> /dev/null; then
    check_service \
        "Redis (localhost:6379)" \
        "redis-cli -h localhost -p 6379 ping | grep -q PONG"
else
    check_service \
        "Redis (localhost:6379)" \
        "docker exec stock_redis redis-cli ping | grep -q PONG"
fi

check_service \
    "Airflow (http://localhost:8080/health)" \
    "curl -sf --max-time 10 http://localhost:8080/health"


echo ""
echo "===== 檢查結果 ====="
echo ""
echo -e "  通過：${GREEN}${PASS}${NC} / ${TOTAL}"
echo -e "  失敗：${RED}${FAIL}${NC} / ${TOTAL}"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${YELLOW}[WARN] 有 ${FAIL} 個服務未通過健康檢查${NC}"
    exit 1
else
    echo -e "${GREEN}[OK] 所有服務正常運作${NC}"
    exit 0
fi
