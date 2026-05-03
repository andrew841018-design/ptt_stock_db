# 關鍵字速查 key_word.md

> 三個核心指令的完整行為定義。每次 `update` 同步。

---

## `update`

1. 掃描整個對話，找出新學到的格式、指示、偏好、規範
2. 對每一條：檢查 MEMORY.md 是否已有對應記憶；有則更新，沒有則新建
3. **先讀取**五個文件的現有內容，再根據對話新知更新：`CLAUDE.md`、`COMMANDS.md`、`readme.md`、`project_notes.md`、`key_word.md`（五個）
4. 讀取 `logs/` 最新 log，掃描 ERROR / WARNING / Traceback，有問題立即修正
5. 檢查 `logs/` 數量，超過 30 個則刪除最舊的
6. 檢查所有 `.py` 的 import，補上未列入 `requirements.txt` 的套件
7. 檢查 launchd job 健康狀態：
   - `claude-update`：查 `project/logs/claude_update_stdout.log` 最後一筆日期，超過 2 天沒跑則警告
   - `line-bot-health`：查 `~/Library/Logs/line_bot_health.log` 最後一筆日期，超過 2 天沒跑則警告
   - 兩個 job exit code 用 `launchctl list | grep com.andrew` 確認均為 0

---

## `scheduled update`（launchd 排程觸發）

在 `update` 全部步驟前，先做：
- 對整個 project 做 10 次自我迭代 code review，直到連續 10 次沒發現問題才停止
- 再執行上面 `update` 的所有步驟

完成上述步驟後，額外執行：
- 讀取 `/Users/andrew/.claude/scheduled-tasks/daily-mock-interview/SKILL.md`，連續 10 次迭代審查 mock interview 內容（每次從不同角度切入：主題廣度、難度分佈、時間分配、題數合理性、問法有效性、面試官視角盲點……），直到連續 10 次沒有新發現才停止
- 若有任何建議，**不要直接修改 SKILL.md**，將建議追加寫入 `/Users/andrew/Desktop/andrew/Data_engineer/mock_interview_suggestions.md`（格式：`=== {日期} ===` 後接條列建議）
- 核心目標：最大化面試成功率與薪資（台灣 DE 市場）

---

## `git`

1. `git status` + `git diff` 查看所有未 stage 的變更
2. 逐一閱讀變更，對照 readme.md Commit Tag 對照表，生成完整 commit message
3. 審查所有 unpushed commits：確認是否有 tag、內容是否足以獨立一筆
4. 判斷是否需要 soft reset 合併（無法加 tag 的 commit 合併進有意義的）
5. 主動讀 `daily_guide_v2.html`，逐一比對每筆 commit 與任務清單，說明加哪個 tag
6. 步驟 3、4、5 一次列出，**等使用者確認後才執行**
7. 確認後：stage → commit → soft reset（若需合併）→ tag → push commits → push tags

---

## `繼續`

照 `daily_guide_v2.html` 的任務順序繼續下一個未完成的任務。

---

## `fine_tune_md`

1. 掃描 `/Users/andrew/.claude/projects/-Users-andrew-Desktop-andrew-Data-engineer/memory/` 下所有 `.md` 檔案並全部讀取
2. 找出以下問題：
   - 🔴 **實際衝突**：兩個 memory 對同一件事有矛盾指示
   - 🟡 **過時/被取代**：有更新版本存在，舊版應刪除
   - 🟢 **可合併**：同主題分散兩個檔案，合一更好查
3. 按優先順序整理報告（🔴先、🟡次、🟢最後）
4. **等 Andrew 確認後才動檔案，不自行刪改**
