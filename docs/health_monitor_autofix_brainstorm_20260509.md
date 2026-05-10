# Health Monitor Autofix Brainstorm — 2026-05-09

6 個 agent 從不同角度 brainstorm 出來的 autofix 想法清單。
今天先實作高槓桿 3 個（標 ✅），其餘按優先序待之後 iter 補。

## ✅ 已實作（2026-05-09）

| # | 想法 | 來自 agent | 對應 code |
|---|------|-----------|-----------|
| 1 | check_etl_recent 改檢查 log mtime | 主執行緒（5/9 修法） | `ptt_pipeline_health_monitor.py:check_etl_recent` |
| 2 | autofix_postgres_containers (docker start) | 主執行緒 | `autofix_postgres_containers` |
| 3 | autofix_zero_source (cnn/wsj 0 → wayback；其他 0 → ptt-etl) | scraper agent + escalation agent | `autofix_zero_source` |
| 4 | Recovery notification (✅) on failure→health 轉態 | state agent | `_send_recovery_notice` |
| 5 | Discord 訊息 inline 帶 autofix 結果 (🟡 / 🔴 / ↳) | state agent | main() |
| 6 | **STATE-2 Heartbeat (12h ✅)** | state + ROI + safety agents（4 票） | `maybe_send_heartbeat` |
| 7 | **STATE-4 Cooldown ladder (1h→4h→24h)** | safety + ROI + reality agents（3 票） | `_ladder_cooldown` + `maybe_alert` |
| 8 | **DOCK-1 Healthcheck unhealthy → docker restart** | ROI + cluster + reality agents（3 票，cover 5/7 mongo 12h crash） | `check_container_health` + `autofix_unhealthy_containers` |

## 🟡 高 user_value 待補（next iter）

### Scheduler / Process 層
- **stuck PID kill**：偵測 pipeline.py PID alive 但 log mtime 5+min 沒成長 → kill -TERM → wait 30s → kill -9 → kickstart。**理由**：kickstart 對「卡住的 process」是 no-op（launchd 認為服務在跑）；BERT/yfinance/Reddit JSON hang 都是這種模式
- **bootout + bootstrap**：plist 解析狀態壞掉時用，比 kickstart 更徹底
- **stop ladder**：autofix kickstart 連續 N=3 次失敗 → `launchctl disable` 停排，escalate Discord「需人工介入」（避免炸 log/DB）

### State / Observability
- **Mute window**：user 手動處理時 state 設 `mute_until=<ts>`，期間 0 alert noise
- **Heartbeat ✅**：每 12h 送一條「all systems normal」確認 monitor 自己活著
- **Autofix success rate tracking**：state 記 last_autofix_attempts/successes，Discord 訊息附「此 autofix 此前 14/15 次成功 (93%)」
- **Cooldown ladder**：first 1hr → second 4hr → third 24hr，避免「越爛叫越多」轟炸
- **Failure streak counter**：同錯第 3 次升 🔴 + @here、第 5 次降頻

### Container / Docker
- **Healthcheck unhealthy 偵測**：`docker inspect --format='{{.State.Health.Status}}'` 看 unhealthy → `docker compose restart`（活著但 sick 的 container）
- **brew PG 撞 5432 偵測**：`lsof -nP -iTCP:5432 -sTCP:LISTEN | grep -v com.docker` → `brew services stop postgresql@14`
- **OOMKilled 偵測 + memory bump**：`docker events --filter event=oom` → `docker update --memory=2g`
- **Docker Desktop 沒開**：`pgrep -f "Docker Desktop"` 無 → `open -a Docker` + 等 daemon ready
- **Volume 寫滿**：`docker exec <c> df -h` → 自動清舊 log
- **Restart loop 偵測**：`docker inspect --format='{{.RestartCount}}'` > 5 → `docker rm -f && docker compose up -d`

### Scraper 層
- **PTT over18 cookie 失效**：HTTP 200 但 body 含 `/ask/over18` → 自動 POST over18 form 取新 cookie
- **SSL EOFError 切備援來源池**：cnn/wsj/marketwatch SSL fail → Google News RSS / archive.today
- **HTTP 401/403 paywall ≥30 篇**：wsj/marketwatch → 自動觸發 wayback_backfill 該 source 24h 範圍
- **Reddit 429 / UA ban**：偵測 → 輪替 User-Agent + REQUEST_DELAY ×2（exponential cap 60s）
- **Reddit JSON 截斷 stream + chunk**：分塊讀 + closing-bracket repair (jsonlines 模式)
- **yfinance NoneType 切 stooq.com 備援**：retry 3 次後切備援 source，標 quarantine_until=now+1h
- **Schema drift KeyError quarantine**：偵測 KeyError/AttributeError on parsed dict → quarantine 該 source 該小時、不影響 24h 0 入庫判定

### Network / Cred drift
- **DNS cache flush**：需要 `sudoers NOPASSWD` 設 `dscacheutil -flushcache` + `killall -HUP mDNSResponder`
- **NTP clock drift**：≥3 host SSL fail 同時 → `sudo sntp -sS time.apple.com`（需 sudoers）
- **.env 整合性檢查**：`size < 200` 或 mtime 異常 → 從 `.env.backup` 還原（wrapper 每次 success 後 cp）
- **proxy state 偵測**：`scutil --proxy` HTTPEnable=1 + curl 失敗 → `networksetup -setwebproxystate Wi-Fi off`
- **Reddit OAuth 過期**：praw cache 50min+ → 刪 cache 強制 re-auth via refresh_token
- **IPv6 black-hole**：v6 hang + v4 OK → `networksetup -setv6off`，下次 success 後 auto-revert

### Escalation / Runbook
- **GitHub issue 自動建**：autofix 連續 3 次失敗 → `gh issue create` + diagnostic bundle URL
- **Diagnostic bundle gist**：alert 觸發時打包 (last 100 log + docker ps + df -h + launchctl list + ps aux) → `gh gist create -p` → URL 進 Discord
- **DB snapshot before risky autofix**：`pg_dump` 備份保留 7 份，dump 失敗就放棄 autofix
- **Cross-monitor correlation**：ptt + line_bot 同時報事件 → 升級為「系統性問題」+ @here
- **Verbose retry mode**：失敗 N 次後下次 kickstart 注入 `PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG`，alert 附複製即用 runbook 指令
- **Email fallback**：Discord API down 連續 3 次 → 透過 macOS `mail` 寄 email
- **Auto PR revert**：偵測「最近 commit 後開始持續失敗」→ `gh pr create` 自動 cherry-pick revert（不 auto-merge）

## 評估準則

新增 autofix 前先過這 3 個 gate：
1. **Detection signal 是否可靠**：能不能用乾淨 signal 區分「真該觸發」vs「正常 transient」
2. **Autofix 風險**：失誤觸發會不會把好的弄壞（risk: L/M/H）
3. **User value**：對「Discord 上看到錯誤被處理」此目標的貢獻（H/M/L）

只有 detection 可靠 + risk ≤ M + user_value ≥ M 才實作。
