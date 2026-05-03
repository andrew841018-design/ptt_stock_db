#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  wayback_full_backfill.sh — 一次性歷史回填（2015 → 去年）
#
#  用途：
#    - 日跑 run_wayback_backfill.sh 只掃「當年」資料（288 slice 跑不完）
#    - 這個 script 手動觸發一次，慢慢掃完所有歷史年份
#    - 預期耗時 4-12 小時（視 Wayback Machine 回應速度）
#
#  建議執行時機：
#    - 週末有空 + 電腦整日開機
#    - 螢幕不用休眠但也不用顧；log 記錄所有進度
#
#  跟日跑的差別：
#    日跑：只當年 24 slice × 2 source × 5-15 min = 10-30 min
#    這個：歷年 288 slice × 2 source × 無 timeout = 可能 8-12h
#
#  如何執行：
#    bash scripts/wayback_full_backfill.sh
#
#  如何中斷：
#    Ctrl+C 或 pkill -f wayback_full_backfill
#    中斷後重跑會跳過已入庫的 URL（seen_canonical 機制）
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/Users/andrew/Desktop/andrew/Data_engineer/project"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/wayback_full_backfill_$(date +%Y%m%d_%H%M%S).log"
PYTHON="/Users/andrew/opt/anaconda3/envs/de_project/bin/python3"

# 歷史範圍：從 2015 到去年（當年由日跑負責）
MIN_YEAR=2015
MAX_YEAR=$(($(date +%Y) - 1))

# 每 source 一次灌到 10000 篇上限（沒 CDX 也就到此為止）
MAX_ARTICLES=10000

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "===== Wayback FULL backfill 開始 ====="
log "Range: $MIN_YEAR - $MAX_YEAR per source, max_articles=$MAX_ARTICLES"
cd "$PROJECT_DIR/dependent_code"

# ── CNN（歷年，上限 10000 篇，不設 timeout）──
log "--- CNN full backfill ($MIN_YEAR-$MAX_YEAR, max $MAX_ARTICLES) ---"
"$PYTHON" cli.py wayback-backfill cnn \
    --min-year "$MIN_YEAR" --max-year "$MAX_YEAR" --max-articles "$MAX_ARTICLES" \
    >> "$LOG_FILE" 2>&1 \
    || log "CNN full backfill 失敗 exit=$?"

# ── WSJ（同樣設定）──
log "--- WSJ full backfill ($MIN_YEAR-$MAX_YEAR, max $MAX_ARTICLES) ---"
"$PYTHON" cli.py wayback-backfill wsj \
    --min-year "$MIN_YEAR" --max-year "$MAX_YEAR" --max-articles "$MAX_ARTICLES" \
    >> "$LOG_FILE" 2>&1 \
    || log "WSJ full backfill 失敗 exit=$?"

log "===== Wayback FULL backfill 結束 ====="
