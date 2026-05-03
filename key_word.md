# 關鍵字速查

在對話中輸入這些關鍵字，Claude 會自動執行對應流程。

---

## update

自動 log 檢查 + code review + 更新文件

1. 讀取 `logs/` 最新的 log 檔，掃描 ERROR / WARNING / Traceback，有問題立即修正 code
2. 檢查 `logs/` 檔案數量，超過 30 個則刪除最舊的，只保留最新 30 個
3. 對整個 project 逐行自我檢查，發現問題立即修正，重新從頭檢查，連續 10 次無錯才停
4. 同步更新：`CLAUDE.md`、`readme.md`、`project_notes.md`、`key_word.md`
5. 檢查所有 `.py` import，確認 `requirements.txt` 沒有漏掉的套件

---

## git

自動生成 commit message 並 push

1. 查看當前所有未 stage 的變更（git status + git diff）
2. **逐一閱讀變更內容**，對照 `readme.md` 的 Commit Tag 對照表，生成 commit message 給你看
3. **逐一審查所有 unpushed commits（含本次）**：每一筆確認是否已有 tag、能否獨立成一筆
4. **判斷是否需要 soft reset 合併**：把無 tag、純文件、WIP、同任務零散的 commit 合併，目標是每筆都能對應一個 tag；說明哪幾筆合併、合併後的 message
5. **判斷是否新增 git tag**：讀取 `daily_guide_v2.html`，比對每筆 commit 改動與任務清單，說明每筆加哪個 tag 或不加（+ 理由）
6. 步驟 3、4、5 一次列出，等你確認（ok / 好 / 可以 / yes...）
7. 確認後：stage → commit；若需合併先 soft reset → 重新 commit；打 tag → push commits → push tags

---

## 繼續

按照 `daily_guide_v2.html` 的順序，推進下一個未完成的任務
