#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/andrew/Desktop/andrew/Data_engineer/project"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/wayback_full_backfill_$(date +%Y%m%d_%H%M%S).log"
PYTHON="/Users/andrew/opt/anaconda3/envs/de_project/bin/python3"

MIN_YEAR=2015
MAX_YEAR=$(($(date +%Y) - 1))

MAX_ARTICLES=10000

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "===== Wayback FULL backfill 開始 ====="
log "Range: $MIN_YEAR - $MAX_YEAR per source, max_articles=$MAX_ARTICLES"
cd "$PROJECT_DIR/dependent_code"

log "--- CNN full backfill ($MIN_YEAR-$MAX_YEAR, max $MAX_ARTICLES) ---"
"$PYTHON" cli.py wayback-backfill cnn \
    --min-year "$MIN_YEAR" --max-year "$MAX_YEAR" --max-articles "$MAX_ARTICLES" \
    >> "$LOG_FILE" 2>&1 \
    || log "CNN full backfill 失敗 exit=$?"

log "--- WSJ full backfill ($MIN_YEAR-$MAX_YEAR, max $MAX_ARTICLES) ---"
"$PYTHON" cli.py wayback-backfill wsj \
    --min-year "$MIN_YEAR" --max-year "$MAX_YEAR" --max-articles "$MAX_ARTICLES" \
    >> "$LOG_FILE" 2>&1 \
    || log "WSJ full backfill 失敗 exit=$?"

log "===== Wayback FULL backfill 結束 ====="
