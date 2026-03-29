#!/bin/bash  # tell the system to use the bash shell to execute the script

# ETL Pipeline 自動化腳本
# 執行順序：activate venv → 爬蟲 → 清洗分析 → log 結果

#先找到當前資料夾，然後往上一層，取得絕對路徑
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"  # root directory of the project
LOG_FILE="$PROJECT_DIR/logs/etl_$(date +%Y%m%d).log"

mkdir -p "$PROJECT_DIR/logs" #p－已存在不報錯

#$1-first input message
#tee -a "$LOG_FILE" 將輸出同時寫入log file和終端機
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 直接使用 conda env 的 Python，避免 cron 環境讀取 pyvenv.cfg 產生 PermissionError
PYTHON="/Users/andrew/opt/anaconda3/envs/de_project/bin/python3"

# macOS cron TCC 解法：
# cron daemon 沒有 Desktop 的讀取權限，python3 無法 open() Desktop 下的 .py 和 .db 檔
# 解法：把所有 .py 和 .db 複製到 /tmp 執行，執行完刪除
TMP_DIR="/tmp/etl_run_$$"
mkdir -p "$TMP_DIR"

log "===== ETL 開始 ====="

# 1. 確認 python這個路徑的檔案存在
if [ ! -f "$PYTHON" ]; then
    log "ERROR: 找不到 python: $PYTHON"
    rm -rf "$TMP_DIR"
    exit 1
fi
log "Python 確認成功: $PYTHON"

# 2. 複製所有需要的 .py 檔到 /tmp
log "複製腳本到暫存目錄: $TMP_DIR"
#1 代表正常輸出，2 代表錯誤輸出，2>&1 代表把錯誤導向標準輸出（輸出正常輸出＋錯誤輸出）
cp "$PROJECT_DIR/dependent_code/"*.py "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
#拋棄error meesage,用在不存在也沒關係的檔案
cp "$PROJECT_DIR/dependent_code/"*.txt "$TMP_DIR/" 2>/dev/null  # user_dict.txt 等
cp "$PROJECT_DIR/backup.py" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
cp "$PROJECT_DIR/test_code/ge_validation.py" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
# 複製 DB，由於db可能不存在，因此用|| true 確保exit code為0(成功)
cp "$PROJECT_DIR/dependent_code/ptt_stock.db" "$TMP_DIR/" 2>/dev/null || true
cp "$PROJECT_DIR/.env" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"

# 3. 爬蟲 + 清洗 + 分析（在 /tmp 執行，PYTHONPATH 也指向 /tmp）
log "開始執行 pipeline.py..."
cd "$TMP_DIR" && "$PYTHON" pipeline.py 2>&1 | tee -a "$LOG_FILE"
# PIPESTATUS[0] 代表 pipeline.py 的 exit code
#或者說|左側指令的exit code
PIPELINE_EXIT=${PIPESTATUS[0]}
if [ $PIPELINE_EXIT -ne 0 ]; then
    log "ERROR: pipeline.py 執行失敗"
    rm -rf "$TMP_DIR"
    exit 1
fi
log "pipeline.py 執行完成"

# 同步 DB 回原始位置（爬蟲寫入了新資料）
cp "$TMP_DIR/ptt_stock.db" "$PROJECT_DIR/dependent_code/ptt_stock.db" 2>/dev/null || true

# 4. 備份到 S3（從 /tmp 讀取 db）
log "開始備份到 S3..."
# && 代表前一個指令成功後，才執行後一個指
cd "$TMP_DIR" && "$PYTHON" backup.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: S3 備份失敗，但 ETL 已完成"
else
    log "S3 備份完成"
fi

# 5. GE 資料驗證
log "開始 GE 資料驗證..."
cd "$TMP_DIR" && "$PYTHON" ge_validation.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: GE 驗證失敗，請檢查資料品質"
else
    log "GE 驗證完成"
fi

# 6. 清除暫存目錄
rm -rf "$TMP_DIR"
log "暫存目錄已清除"

# 7. 掃描 log 統計 ERROR / WARNING(default 0)
ERROR_COUNT=$(grep -c " - ERROR - " "$LOG_FILE" 2>/dev/null || echo 0)
WARNING_COUNT=$(grep -c "WARNING" "$LOG_FILE" 2>/dev/null || echo 0)

log "---------- 執行摘要 ----------"
log "ERROR 數量：$ERROR_COUNT"
log "WARNING 數量：$WARNING_COUNT"

if [ "$ERROR_COUNT" -gt 0 ]; then
    log "⚠️  發現 ERROR，列出詳細："
    # | 就是pipe，把左側指令的輸出作為右側指令的輸入，所以line就是從左側的輸出讀取    
    grep " - ERROR - " "$LOG_FILE" | while read -r line; do
        log "  >> $line"
    done
fi

log "===== ETL 完成 ====="
