#!/bin/bash  # tell the system to use the bash shell to execute the script

# ETL Pipeline 自動化腳本
# 執行順序：activate venv → 爬蟲 → S3 備份 → GE 驗證 → log 結果

# 硬編碼專案路徑（launchd CWD=/，dirname 會算錯成 /Users/andrew/）
PROJECT_DIR="/Users/andrew/Desktop/andrew/Data_engineer/project"
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

# 直接在專案目錄執行（不再 cp 到 /tmp）
# 前提：需在 System Settings → Privacy & Security → Full Disk Access 加入此 PYTHON
# 否則 launchd 觸發時 python 無法讀取 ~/Desktop/ 下的檔案（TCC 擋）
WORK_DIR="$PROJECT_DIR/dependent_code"

log "===== ETL 開始 ====="

# 1. 確認 python這個路徑的檔案存在
if [ ! -f "$PYTHON" ]; then
    log "ERROR: 找不到 python: $PYTHON"
    exit 1
fi
log "Python 確認成功: $PYTHON"

# 2. 爬蟲
log "開始執行 pipeline.py..."
cd "$WORK_DIR" && "$PYTHON" pipeline.py 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}
if [ $PIPELINE_EXIT -ne 0 ]; then
    log "ERROR: pipeline.py 執行失敗"
    exit 1
fi
log "pipeline.py 執行完成"

# 3. 備份到 S3
log "開始備份到 S3..."
cd "$WORK_DIR" && "$PYTHON" backup.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: S3 備份失敗，但 ETL 已完成"
else
    log "S3 備份完成"
fi

# 4. GE 資料驗證
log "開始 GE 資料驗證..."
cd "$WORK_DIR" && "$PYTHON" ge_validation.py 2>&1 | tee -a "$LOG_FILE"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "WARNING: GE 驗證失敗，請檢查資料品質"
else
    log "GE 驗證完成"
fi

# 7. 掃描 log 統計 ERROR / WARNING（只掃本次執行新增的行）
# 重要：summary 段「不」寫入 LOG_FILE，改寫獨立 SUMMARY_FILE
# 過去版本把 ERROR 明細 tee 進 LOG_FILE，下一輪 grep 又掃到自己，導致 ERROR 數呈指數增長
# Python logging 格式：%(asctime)s [%(levelname)s] %(message)s → 用 \[ERROR\] 精確比對
# Shell 腳本錯誤格式：ERROR: <message> → 用 ^ERROR: 鎖定行首
SUMMARY_FILE="$PROJECT_DIR/logs/etl_summary_$(date +%Y%m%d).log"
ERROR_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -cE "\[ERROR\]|^ERROR:|ERROR: " || true)
WARNING_COUNT=$(tail -n +"$LOG_START_LINE" "$LOG_FILE" 2>/dev/null | grep -cE "\[WARNING\]|^WARNING:|WARNING: " || true)
ERROR_COUNT=${ERROR_COUNT:-0}
WARNING_COUNT=${WARNING_COUNT:-0}

# Summary 段只 echo 到 console + 獨立 SUMMARY_FILE，絕對不污染 LOG_FILE
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

# LOG_FILE 也記一行收尾，方便下次 LOG_START_LINE 對齊（不含關鍵字）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] (run_etl.sh 收尾，summary 已寫入 $SUMMARY_FILE)" >> "$LOG_FILE"
