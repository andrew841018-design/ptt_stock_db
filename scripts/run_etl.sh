#!/bin/bash  # tell the system to use the bash shell to execute the script

# ETL Pipeline 自動化腳本
# 執行順序：activate venv → 爬蟲 → S3 備份 → GE 驗證 → log 結果

#先找到當前資料夾，然後往上一層，取得絕對路徑
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"  # root directory of the project
LOG_FILE="$PROJECT_DIR/logs/etl_$(date +%Y%m%d).log"

mkdir -p "$PROJECT_DIR/logs" #p－已存在不報錯

# 記錄本次開始前的行數（同一天多次執行共用 log 檔，summary 只掃本次新增的行）
LOG_START_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
LOG_START_LINE=$((LOG_START_LINE + 1))

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

# 2. 複製所有需要的檔案到 /tmp
log "複製腳本到暫存目錄: $TMP_DIR"
#1 代表正常輸出，2 代表錯誤輸出，2>&1 代表把錯誤導向標準輸出（輸出正常輸出＋錯誤輸出）
cp "$PROJECT_DIR/dependent_code/"*.py "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
# scrapers/ 是子目錄（package），需用 -r 遞迴複製，否則 pipeline.py 找不到 PttScraper 等 class
cp -r "$PROJECT_DIR/dependent_code/scrapers" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
cp "$PROJECT_DIR/dependent_code/backup.py" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
cp "$PROJECT_DIR/dependent_code/ge_validation.py" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"
cp "$PROJECT_DIR/.env" "$TMP_DIR/" 2>&1 | tee -a "$LOG_FILE"

# 3. 爬蟲（在 /tmp 執行，PYTHONPATH 也指向 /tmp）
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

# 4. 備份到 S3
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

# 7. 掃描 log 統計 ERROR / WARNING（只掃本次執行新增的行，避免前幾次 summary 被重複計算）
# 同一天的 log 共用同一個檔案（tee -a），只從本次開始行往下 grep
# Python logging 格式：%(asctime)s [%(levelname)s] %(message)s → 用 \[ERROR\] 精確比對
# Shell 腳本錯誤格式：ERROR: <message> → 用 ERROR: 比對
# 故意排除 ERROR 數量:/ERROR 數量：等 summary 行，避免計入自己
ERROR_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -cE "\[ERROR\]|ERROR:" || echo 0)
WARNING_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -c "WARNING" || echo 0)

log "---------- 執行摘要 ----------"
log "ERROR 數量：$ERROR_COUNT"
log "WARNING 數量：$WARNING_COUNT"

if [ "$ERROR_COUNT" -gt 0 ]; then
    log "⚠️  發現 ERROR，列出詳細："
    tail -n +"$LOG_START_LINE" "$LOG_FILE" | grep -E "\[ERROR\]|ERROR:" | while read -r line; do
        log "  >> $line"
    done
fi

log "===== ETL 完成 ====="
