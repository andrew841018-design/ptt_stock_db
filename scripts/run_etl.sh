#!/bin/bash  # tell the system to use the bash shell to execute the script


PROJECT_DIR="/Users/andrew/Desktop/andrew/Data_engineer/project"
LOG_FILE="$PROJECT_DIR/logs/etl_$(date +%Y%m%d).log"

mkdir -p "$PROJECT_DIR/logs"
touch "$LOG_FILE"

LOG_START_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
LOG_START_LINE=$((LOG_START_LINE + 1))

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

PYTHON="/Users/andrew/opt/anaconda3/envs/de_project/bin/python3"

WORK_DIR="$PROJECT_DIR/dependent_code"

log "===== ETL 開始 ====="

if [ ! -f "$PYTHON" ]; then
    log "ERROR: 找不到 python: $PYTHON"
    exit 1
fi
log "Python 確認成功: $PYTHON"

log "開始執行 pipeline.py..."
cd "$WORK_DIR" && "$PYTHON" pipeline.py 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}
if [ $PIPELINE_EXIT -ne 0 ]; then
    log "ERROR: pipeline.py 執行失敗"
    exit 1
fi
log "pipeline.py 執行完成"

log "開始備份到 S3..."
cd "$WORK_DIR" && "$PYTHON" backup.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: S3 備份失敗，但 ETL 已完成"
else
    log "S3 備份完成"
fi

log "開始 GE 資料驗證..."
cd "$WORK_DIR" && "$PYTHON" ge_validation.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: GE 驗證失敗，請檢查資料品質"
else
    log "GE 驗證完成"
fi

SUMMARY_FILE="$PROJECT_DIR/logs/etl_summary_$(date +%Y%m%d).log"
ERROR_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -cE "\[ERROR\]|^ERROR:|ERROR: " || true)
WARNING_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -cE "\[WARNING\]|^WARNING:|WARNING: " || true)
ERROR_COUNT=${ERROR_COUNT:-0}
WARNING_COUNT=${WARNING_COUNT:-0}

{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ---------- 執行摘要 ----------"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 錯誤總數: $ERROR_COUNT"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 警示總數: $WARNING_COUNT"
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 錯誤明細："
        tail -n +"$LOG_START_LINE" "$LOG_FILE" | grep -E "\[ERROR\]|^ERROR:|ERROR: " | sed 's/^/    /'
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ETL 完成 ====="
} | tee -a "$SUMMARY_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] (run_etl.sh 收尾，summary 已寫入 $SUMMARY_FILE)" >> "$LOG_FILE"
