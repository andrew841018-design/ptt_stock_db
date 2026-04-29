#!/usr/bin/env python3
"""ptt_pipeline_health_monitor.py — 每小時跑一次的 PTT pipeline 健康監測。

對標 line_bot/bot_health_monitor.py 的設計，但這隻只通知不自修。

檢查項目：
  1. ETL 最近 1 小時有沒有跑（看 logs/etl_*.log mtime）
  2. launchd com.andrew.ptt-etl 最後一次 LastExitStatus 是否 0
  3. DB 24h article count 增量 < 50 → 異常
  4. 7 個爬蟲來源（PTT / cnyes / reddit / cnn / wsj / marketwatch / wayback_*）有 ≥ 2
     個近 24h 0 入庫 → 異常

異常時：
  - Discord DM 通知（透過 line_bot/notify_discord.py 的 send_dm）
  - 同類 60 分內不重複 DM（state 存 line_bot/health_monitor_state.json，避免污染 PTT logs/）
  - 不嘗試自修（只通知）
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DEPENDENT_CODE = PROJECT_ROOT / "dependent_code"
LINE_BOT_DIR = Path("/Users/andrew/Desktop/andrew/Data_engineer/line_bot")
STATE_FILE = LINE_BOT_DIR / "ptt_pipeline_health_state.json"

# 只把 dependent_code 加進 sys.path（pg_helper 需要）。
# line_bot 的 config.py 會 shadow 掉 dependent_code/config.py，
# 所以 notify_discord 改成 importlib.util 用絕對檔案路徑載入。
sys.path.insert(0, str(DEPENDENT_CODE))

# 讀 line_bot 的 .env 拿 DISCORD_BOT_TOKEN / DISCORD_USER_ID
try:
    from dotenv import load_dotenv

    load_dotenv(LINE_BOT_DIR / ".env")
except Exception:
    pass

ALERT_COOLDOWN_SEC = 3600  # 60 分內同類不重複


def _now_ts() -> float:
    return time.time()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(d: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"  ! save_state 失敗: {e}")


def check_etl_recent() -> tuple[bool, str]:
    """ETL 最近 1 小時有沒有跑（看 logs/etl_*.log mtime）。"""
    if not LOGS_DIR.exists():
        return False, "logs/ 目錄不存在"
    etl_logs = sorted(LOGS_DIR.glob("etl_*.log"), key=lambda f: f.stat().st_mtime)
    if not etl_logs:
        return False, "logs/ 下沒有 etl_*.log"
    latest = etl_logs[-1]
    age_min = (time.time() - latest.stat().st_mtime) / 60
    if age_min > 70:  # 給 launchd 一點時鐘漂移空間
        return False, f"最新 etl log {latest.name} 已 {age_min:.0f} 分鐘未更新（>70min）"
    return True, f"{latest.name} {age_min:.0f}min ago"


def check_launchd_etl() -> tuple[bool, str]:
    """launchctl list com.andrew.ptt-etl 的 LastExitStatus 是否 0。"""
    try:
        r = subprocess.run(
            ["launchctl", "list", "com.andrew.ptt-etl"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return False, "launchctl list 找不到 com.andrew.ptt-etl"
        m = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', r.stdout)
        if not m:
            return False, "launchctl 輸出沒有 LastExitStatus"
        exit_code = int(m.group(1))
        if exit_code == 0:
            return True, "exit=0"
        # 256 在 launchd = posix exit 1，仍視為失敗但訊息不一樣
        return False, f"LastExitStatus={exit_code}"
    except Exception as e:
        return False, f"launchctl 呼叫失敗: {e}"


def check_db_and_sources() -> tuple[bool, str, dict]:
    """DB 24h 增量 + 各來源 24h 入庫狀況。

    回傳 (overall_ok, reason, raw_stats)。
    """
    try:
        from pg_helper import get_pg
    except Exception as e:
        return False, f"無法 import pg_helper: {e}", {}

    try:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM articles
                    WHERE scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
                    """
                )
                d24_total = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT s.source_name,
                           COUNT(a.article_id) FILTER (
                               WHERE a.scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
                           ) AS new_24h
                    FROM sources s
                    LEFT JOIN articles a ON a.source_id = s.source_id
                    GROUP BY s.source_name
                    ORDER BY new_24h DESC
                    """
                )
                rows = cur.fetchall()
    except Exception as e:
        return False, f"DB 查詢失敗: {e}", {}

    per_source = {name: int(cnt) for name, cnt in rows}
    zero_sources = [n for n, c in per_source.items() if c == 0]
    stats = {"total_24h": int(d24_total), "per_source": per_source}

    issues = []
    if d24_total < 50:
        issues.append(f"24h 增量僅 {d24_total} 筆 (<50)")
    if len(zero_sources) >= 2:
        issues.append(f"{len(zero_sources)} 個來源 24h 0 入庫: {zero_sources}")

    if issues:
        return False, "; ".join(issues), stats
    return True, f"24h +{d24_total}, 全部來源活著", stats


def send_discord(msg: str) -> bool:
    """用 importlib.util 從絕對路徑載 notify_discord，避開 line_bot/config.py 撞 dependent_code/config.py。"""
    notify_path = LINE_BOT_DIR / "notify_discord.py"
    if not notify_path.exists():
        print(f"  ! notify_discord.py 不存在：{notify_path}")
        return False
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("notify_discord", str(notify_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return bool(mod.send_dm(msg))
    except Exception as e:
        print(f"  ! send_dm 例外: {e}")
        return False


def maybe_alert(state: dict, key: str, msg: str) -> bool:
    """同類 60 分內不重複；超過就發。"""
    last = float(state.get(f"last_alert_{key}", 0))
    if _now_ts() - last < ALERT_COOLDOWN_SEC:
        return False
    if send_discord(msg):
        state[f"last_alert_{key}"] = _now_ts()
        return True
    return False


def main() -> int:
    state = load_state()
    issues: list[tuple[str, str]] = []  # (alert_key, msg)

    etl_ok, etl_msg = check_etl_recent()
    if not etl_ok:
        issues.append(("etl_log", f"🟡 ETL log 異常：{etl_msg}"))

    lnd_ok, lnd_msg = check_launchd_etl()
    if not lnd_ok:
        issues.append(("launchd_etl", f"🔴 launchd com.andrew.ptt-etl：{lnd_msg}"))

    db_ok, db_msg, db_stats = check_db_and_sources()
    if not db_ok:
        issues.append(("db_or_sources", f"🔴 DB / 來源異常：{db_msg}"))

    print(
        f"[{_now_str()}] etl_recent={etl_ok} launchd={lnd_ok} db={db_ok} | "
        f"24h_total={db_stats.get('total_24h', '?')}"
    )
    for _, m in issues:
        print(f"  - {m}")

    if issues:
        body_lines = [f"🩺 **PTT Pipeline 健康警示** {datetime.now().strftime('%H:%M')}"]
        for _, m in issues:
            body_lines.append(m)
        if db_stats:
            body_lines.append(
                f"\n📊 24h 入庫：{db_stats.get('total_24h')}，"
                f"per_source={db_stats.get('per_source')}"
            )
        msg = "\n".join(body_lines)
        # 一次性 alert：用所有 keys 排序合併當 cooldown key，
        # 避免同次多 issue 連發 N 條 Discord
        bundle_key = "|".join(sorted({k for k, _ in issues}))
        maybe_alert(state, bundle_key, msg)

    save_state(state)
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
