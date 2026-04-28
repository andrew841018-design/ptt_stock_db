#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  validate.sh — 本機靜態驗證
#
#  用盡可能用手邊有的工具驗，沒裝的工具會印「跳過」不讓你卡住。
#  CI 裡有更完整的版本（.github/workflows/validate.yml）。
#
#  用法：
#    ./scripts/validate.sh
#    python dependent_code/cli.py validate
# ══════════════════════════════════════════════════════════════════
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1"; shift
    echo ""
    echo "▶ $name"
    if "$@"; then
        echo "  ✅ PASS"; PASS=$((PASS + 1))
    else
        echo "  ❌ FAIL"; FAIL=$((FAIL + 1))
    fi
}

skip() {
    echo ""
    echo "▶ $1"
    echo "  ⏭  SKIP（$2）"
    SKIP=$((SKIP + 1))
}

# 1. Python syntax
check "Python AST parse（所有 dependent_code/*.py）" \
    python -c "import ast, pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('dependent_code').rglob('*.py')]; print('  parsed', len(list(pathlib.Path('dependent_code').rglob('*.py'))), 'files')"

# 2. YAML parse
check "YAML parse（所有 yaml/yml 檔）" \
    python -c "
import yaml, pathlib
EXCLUDE = ('dbt_packages', 'target', 'venv', '.git', 'dbt_modules')
def keep(p):
    s = str(p)
    return not any(e in s.split('/') for e in EXCLUDE) and p.is_file()
files = [f for f in list(pathlib.Path('.').rglob('*.yaml')) + list(pathlib.Path('.').rglob('*.yml')) if keep(f)]
for f in files:
    list(yaml.safe_load_all(f.read_text()))
print(f'  parsed {len(files)} files')
"

# 3. requirements.txt 格式
check "requirements.txt 格式" \
    python -c "
lines = [l.strip() for l in open('dependent_code/requirements.txt') if l.strip() and not l.startswith('#')]
for l in lines:
    assert any(c.isalnum() for c in l), f'bad line: {l}'
print(f'  {len(lines)} packages listed')
"

# 4. kubectl dry-run（如果裝了且有 cluster context）
if command -v kubectl >/dev/null 2>&1 && kubectl config current-context >/dev/null 2>&1; then
    check "kubectl --dry-run（K8s schema 驗證）" \
        bash -c 'for f in k8s/*.yaml; do kubectl apply --dry-run=client -f "$f" >/dev/null; done && echo "  validated $(ls k8s/*.yaml | wc -l) files"'
else
    skip "kubectl --dry-run" "kubectl 未設 cluster context（不影響其他驗證）"
fi

# 5. dbt parse（透過 wrapper 自動載入 .env）
if [ -x scripts/dbt.sh ] && [ -f .env ]; then
    check "dbt parse（model ref 檢查）" \
        bash -c './scripts/dbt.sh parse 2>&1 | grep -qE "Running with dbt|Performance info" && echo "  dbt parse OK"'
else
    skip "dbt parse" "scripts/dbt.sh 或 .env 缺少"
fi

# 6. Dockerfile 語法（快速檢查，不真的 build）
#    完整 build 到 CI 或手動跑 `docker build .` 時才做
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    check "Dockerfile 語法（docker build --check）" \
        bash -c 'docker build --check . >/dev/null 2>&1 && echo "  Dockerfile OK（完整 build 請手動跑 docker build .）"'
else
    skip "Dockerfile 語法檢查" "Docker daemon 未啟動"
fi

# 7. pytest（如果 PG 能連 + 能 import redis）
if python -c "import redis, psycopg2" 2>/dev/null && \
   python -c "import psycopg2; psycopg2.connect(host='localhost', user='postgres', password='pw', dbname='stock_analysis_db', connect_timeout=2).close()" 2>/dev/null; then
    check "pytest（test_api.py）" \
        bash -c 'set -o pipefail; cd dependent_code && python -m pytest test_api.py -q 2>&1 | tail -3'
else
    skip "pytest" "套件或 PG 連線缺（conda activate de_project + 本機 docker ps 要有 ptt_stock_db）"
fi

# 總結
echo ""
echo "══════════════════════════════════════════"
echo "  ✅ PASS: $PASS   ❌ FAIL: $FAIL   ⏭  SKIP: $SKIP"
echo "══════════════════════════════════════════"

[ "$FAIL" -eq 0 ]
