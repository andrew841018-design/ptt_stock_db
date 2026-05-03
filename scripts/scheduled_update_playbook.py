#!/usr/bin/env python3
"""scheduled_update_playbook.py — 把 `scheduled update` 的機械檢查段自動化。

設計動機：原本 Andrew 打「scheduled update」時，Claude 要逐項手動跑：
  - launchd 14+ 個 job 的 exit code
  - logs/ 檔案數 + ERROR / WARNING 抓取
  - ETL 最近 run 狀態
  - requirements.txt vs 實際 import 差異
  - DB article count 24h / 7d 增量
  - 每個爬蟲來源 24h 活動

這些都是機械重複動作，浪費 LLM token + 時間。Playbook 把它們一次跑完，
寫到 logs/scheduled_update_report_YYYYMMDD.md，Claude 讀報告後直接進
code review / mock interview 階段。

呼叫方式：python scripts/scheduled_update_playbook.py
退出碼：0 = 全部 OK / 1 = 有警告 / 2 = 致命錯誤
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DEPENDENT_CODE = PROJECT_ROOT / "dependent_code"
LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"

sys.path.insert(0, str(DEPENDENT_CODE))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def section_launchd(out: list) -> int:
    """檢查所有 com.andrew.* launchd job 健康狀態。回傳警告數。"""
    out.append("\n## 1. launchd jobs 健康狀態\n")
    plists = sorted(LAUNCHD_DIR.glob("com.andrew.*.plist"))
    warnings = 0
    out.append("| Job | last exit | stderr mtime | 狀態 |")
    out.append("|-----|-----------|--------------|------|")
    for p in plists:
        label = p.stem
        # launchctl list 抓 exit code
        try:
            r = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', r.stdout)
            exit_code = int(m.group(1)) if m else "?"
        except Exception:
            exit_code = "?"

        # 找 stderr log
        stderr_log = Path.home() / "Library" / "Logs" / f"{label}_stderr.log"
        if not stderr_log.exists():
            stderr_log = Path.home() / "Library" / "Logs" / f"{label.replace('com.andrew.', '')}_stderr.log"
        # 也試 launchd_stderr 系列
        if not stderr_log.exists():
            for cand in (Path.home() / "Library" / "Logs").glob(f"*{label.replace('com.andrew.', '')}*stderr*"):
                stderr_log = cand
                break
        if stderr_log.exists():
            mtime = datetime.fromtimestamp(stderr_log.stat().st_mtime)
            mtime_str = mtime.strftime("%m-%d %H:%M")
            age_hours = (datetime.now() - mtime).total_seconds() / 3600
        else:
            mtime_str = "(無)"
            age_hours = -1

        # 判斷狀態
        # launchd exit code 256 = posix exit 1（launchctl list 顯示 256 是慣例）
        # 把 256 當成 ⚠️（軟警告）而非致命錯誤
        if exit_code == 0:
            status = "✅"
        elif exit_code == "?":
            status = "⚠️ 未載入"
            warnings += 1
        elif exit_code == 256:
            status = "⚠️ exit=1（看 stderr）"
            warnings += 1
        else:
            status = f"🔴 exit={exit_code}"
            warnings += 1

        out.append(f"| {label} | {exit_code} | {mtime_str} | {status} |")
    return warnings


def section_logs(out: list) -> int:
    """logs/ 數量 + 最近 ERROR/WARNING 統計。"""
    out.append("\n## 2. logs/ 統計\n")
    if not LOGS_DIR.exists():
        out.append("(logs/ 不存在)")
        return 1
    files = list(LOGS_DIR.glob("*"))
    out.append(f"- 檔案數：{len(files)}（上限 30，超過要清最舊）")
    if len(files) > 30:
        oldest = sorted(files, key=lambda f: f.stat().st_mtime)[: len(files) - 30]
        out.append(f"- ⚠️ 超出 {len(files) - 30} 個，建議清最舊：")
        for f in oldest[:5]:
            out.append(f"  - {f.name}")

    # 今日 etl summary
    today = datetime.now().strftime("%Y%m%d")
    summary_log = LOGS_DIR / f"etl_summary_{today}.log"
    if summary_log.exists():
        out.append(f"\n### 今日 etl_summary_{today}.log")
        out.append("```")
        out.append(summary_log.read_text(errors="ignore")[:2000])
        out.append("```")

    # 今日 etl 主 log 抓 ERROR / Traceback
    etl_log = LOGS_DIR / f"etl_{today}.log"
    if etl_log.exists():
        content = etl_log.read_text(errors="ignore")
        err_count = content.count("[ERROR]") + content.count("ERROR:")
        warn_count = content.count("[WARNING]") + content.count("WARNING:")
        traceback_count = content.count("Traceback")
        out.append(f"\n### etl_{today}.log")
        out.append(f"- ERROR：{err_count} / WARNING：{warn_count} / Traceback：{traceback_count}")
        if traceback_count > 0:
            # 抓最後一個 traceback
            idx = content.rfind("Traceback")
            snippet = content[idx : idx + 500]
            out.append("```")
            out.append(snippet)
            out.append("```")
            return 1
    return 0


def section_etl_db(out: list) -> int:
    """ETL DB article count 24h / 7d 增量 + 各來源 24h 活動。"""
    out.append("\n## 3. ETL / DB 狀態\n")
    try:
        from pg_helper import get_pg
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM articles")
                total = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM articles
                    WHERE scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
                """)
                d24 = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM articles
                    WHERE scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '7 days'
                """)
                d7 = cur.fetchone()[0]
                cur.execute("""
                    SELECT s.source_name,
                           COUNT(a.article_id) FILTER (WHERE a.scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours') AS new_24h,
                           COUNT(a.article_id) FILTER (WHERE a.scraped_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '7 days') AS new_7d
                    FROM sources s
                    LEFT JOIN articles a ON a.source_id = s.source_id
                    GROUP BY s.source_name
                    ORDER BY new_24h DESC
                """)
                src_rows = cur.fetchall()
    except Exception as e:
        out.append(f"⚠️ DB 查詢失敗：{e}")
        return 1

    out.append(f"- 總文章數：{total:,}")
    out.append(f"- 近 24h 增量：+{d24}")
    out.append(f"- 近 7d 增量：+{d7}")
    out.append("\n### 各來源 24h / 7d 活動")
    out.append("| Source | 24h | 7d |")
    out.append("|--------|-----|----|")
    stalled = 0
    for name, h24, d7 in src_rows:
        icon = "✅" if h24 > 0 else ("🟡" if d7 > 0 else "🔴")
        out.append(f"| {icon} {name} | +{h24} | +{d7} |")
        if h24 == 0 and d7 == 0:
            stalled += 1
    if stalled > 0:
        out.append(f"\n⚠️ 有 {stalled} 個來源近 7d 完全停滯")
    return 1 if stalled > 0 else 0


def section_requirements(out: list) -> int:
    """掃 .py 找 import 對比 requirements.txt。"""
    out.append("\n## 4. requirements.txt 覆蓋\n")
    req_file = DEPENDENT_CODE / "requirements.txt"
    if not req_file.exists():
        out.append("⚠️ requirements.txt 不存在")
        return 1
    req_pkgs = set()
    for line in req_file.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        pkg = re.split(r"[<>=!~\[]", line)[0].strip().lower().replace("-", "_")
        req_pkgs.add(pkg)

    # 簡單 normalize：把常見 package 名 → import 名
    NORMALIZE = {
        "psycopg2_binary": "psycopg2",
        "python_dotenv": "dotenv",
        "google_genai": "google",
        "google_cloud_bigquery": "google",
        "python_dateutil": "dateutil",
        "python_jose": "jose",
        "beautifulsoup4": "bs4",
        "scikit_learn": "sklearn",
        "great_expectations": "great_expectations",
        "celery_redis": "celery",
        "pillow": "pil",
    }
    req_imports = {NORMALIZE.get(p, p) for p in req_pkgs}

    # 掃所有 .py 找 import
    actual = set()
    for py in DEPENDENT_CODE.rglob("*.py"):
        try:
            for line in py.read_text(errors="ignore").splitlines():
                m = re.match(r"^(?:from|import)\s+([\w_]+)", line.strip())
                if m:
                    actual.add(m.group(1).lower())
        except Exception:
            continue

    # 過濾標準庫 + 本地 module
    LOCAL_MODULES = {
        "config", "pg_helper", "memory", "schema", "pii_masking",
        "qa", "ge_validation", "scrapers", "data_mart", "dw_etl",
        "dw_schema", "metrics", "tasks", "celery_app", "auth",
        "api", "bert_sentiment", "ai_model_prediction", "llm_labeling",
        "labeling_tool", "reparse", "mongo_helper", "cache_helper",
        "backup", "cli", "pipeline", "visualization", "plt_function",
        "scraper_schemas", "base_scraper",
    }
    STDLIB = {
        "os", "sys", "re", "json", "logging", "datetime", "time", "pathlib",
        "subprocess", "argparse", "typing", "collections", "itertools",
        "functools", "abc", "contextlib", "tempfile", "shutil", "math",
        "random", "uuid", "hashlib", "base64", "io", "csv", "urllib",
        "concurrent", "threading", "multiprocessing", "pickle", "asyncio",
        "decimal", "string", "operator", "enum", "dataclasses", "warnings",
        "traceback", "inspect", "copy", "glob", "zlib", "gzip", "smtplib",
        "email", "mimetypes", "ssl", "socket", "http", "platform",
        "zoneinfo", "getpass", "secrets", "unittest", "xml", "html",
        "queue", "signal", "stat", "select", "struct", "fnmatch",
        "textwrap", "weakref", "types", "ast", "importlib",
    }
    third_party = actual - LOCAL_MODULES - STDLIB
    missing = third_party - req_imports
    # 排除少數已知非套件
    missing = {m for m in missing if not m.startswith("_") and len(m) > 1}

    out.append(f"- 掃到 {len(actual)} 個 import，{len(third_party)} 個第三方")
    if missing:
        out.append(f"- ⚠️ 可能漏列 requirements.txt：{sorted(missing)}")
        return 1
    out.append("- ✅ 第三方 import 都在 requirements.txt 裡")
    return 0


def main() -> int:
    out: list = []
    out.append(f"# Scheduled Update Report — {_now()}\n")

    warnings = 0
    warnings += section_launchd(out)
    warnings += section_logs(out)
    warnings += section_etl_db(out)
    warnings += section_requirements(out)

    out.append("\n---\n")
    if warnings == 0:
        out.append("\n## ✅ 全部檢查 PASS（無警告）")
    else:
        out.append(f"\n## ⚠️ 共 {warnings} 個警告 — 請檢查上面 🟡 / 🔴 / ⚠️ 標記")

    out.append(
        "\n下一步（給 Claude 的提示）：\n"
        "1. 讀完此報告\n"
        "2. **跳過已自動完成的機械檢查**（launchd / logs / DB / requirements 都 OK 了）\n"
        "3. 直接進 10 次 code review iteration\n"
        "4. 接著 mock interview review（如果是 scheduled update 命令）\n"
        "5. 改 5 個文件（CLAUDE.md / readme.md / project_notes.md / COMMANDS.md / key_word.md）\n"
    )

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report = LOGS_DIR / f"scheduled_update_report_{datetime.now().strftime('%Y%m%d')}.md"
    report.write_text("\n".join(out))
    print(f"Report saved: {report}")
    print(f"Warnings: {warnings}")
    return 0 if warnings == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
