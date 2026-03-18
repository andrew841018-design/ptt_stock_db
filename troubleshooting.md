# PTT 專案部署過程問題排查文件

---

## 1. GitHub 帳號被鎖（帳單問題）

**問題**
```
The job was not started because your account is locked due to a billing issue.
```

**原因**
GitHub 帳號有未付款的月費（3筆 $5 = $15 USD，2022年底），導致帳號被停用，GitHub Actions 無法執行。

**解決方式**
刪除舊帳號，重新申請新帳號（`andrew841018-design`），用 `git push --mirror` 保留所有 commit 紀錄。

---

## 2. Git Authentication Failed

**問題**
```
remote: Invalid username or token. Password authentication is not supported for Git operations.
fatal: Authentication failed
```

**原因**
GitHub 不支援帳號密碼登入，需要使用 Personal Access Token（PAT）。

**解決方式**
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 勾選 **repo** 權限
3. 產生 token 後放入 remote url：
```bash
git remote set-url origin https://TOKEN@github.com/帳號/repo.git
git push
```

**注意**
Token 是敏感資訊，不要貼到聊天室或任何公開地方，使用完立即撤銷重新產生。

---

## 3. EC2 SSH 連線 Timeout

**問題**
```
ssh: connect to host 3.104.105.81 port 22: Operation timed out
```

**原因排查過程**
- Security Group SSH 規則的 Source IP 過期（ISP 動態 IP 變換）
- IPv4 vs IPv6 不匹配（本機實際是 IPv6，但 Security Group 設的是 IPv4）
- EC2 instance sshd 服務異常（Stop → Start 重建 instance 解決）

**解決方式**
1. 確認本機 IP：`curl ifconfig.me`
2. AWS Console → Security Group → 編輯 SSH 規則，Source 選 **My IP**
3. 如果是 IPv6，Source 設為 `::/0` 或 `0.0.0.0/0` 暫時測試
4. 若仍無法連線，Terminate 舊 instance，Launch 新 instance

---

## 4. EC2 pip 安裝失敗（Ubuntu 24.04）

**問題**
```
error: externally-managed-environment
```

**原因**
Ubuntu 24.04 預設不允許直接用 `pip install` 安裝系統層級套件。

**解決方式**
使用 venv：
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r require_lib.txt
```

---

## 5. Streamlit 找不到檔案

**問題**
```
Error: Invalid value: File does not exist: visualization.py
```

**原因**
執行 `streamlit run visualization.py` 時，工作目錄不是 `visualization.py` 所在的目錄。

**解決方式**
使用完整路徑或先 cd 到正確目錄：
```bash
cd /home/ubuntu/ptt_stock_db/dependent_code
streamlit run visualization.py --server.port 8501 --server.address 0.0.0.0
```

---

## 6. Port 已被佔用

**問題**
```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8000): address already in use
Port 8501 is not available
```

**原因**
前一次啟動的 uvicorn/streamlit 程序還在執行，沒有被關閉。

**解決方式**
```bash
kill $(lsof -t -i:8000) 2>/dev/null
kill $(lsof -t -i:8501) 2>/dev/null
```

---

## 7. GitHub Actions test_api.py 找不到

**問題**
```
ERROR: file or directory not found: test_api.py
```

**原因**
- 檔案在子目錄裡，deploy.yml 路徑沒有對應
- 或是本機的 `test_api` 沒有 `.py` 副檔名

**解決方式**
在 deploy.yml 指定正確路徑：
```yaml
- name: Run tests
  run: |
    pytest test_code/test_api.py -v
```

---

## 8. pytest KeyError: 'Published_Time'

**問題**
```
KeyError: 'Published_Time'
```

**原因**
GitHub Actions 虛擬機沒有真實的 `ptt_stock.db`，建出來的空 DB 缺少 `Published_Time` 欄位（因為這個欄位是後來用 ALTER TABLE 加的，不在原始建表語法裡）。

**解決方式**
用 `unittest.mock.patch` 攔截 DB 連線，注入假資料：
```python
@pytest.fixture
def mock_db_with_data():
    with patch("api.pd.read_sql_query", return_value=MOCK_DATA.copy()):
        with patch("api.get_db_connection", return_value=MagicMock()):
            yield
```

---

## 9. pytest 422 測試邊界值錯誤

**問題**
```
AssertionError: limit: 100, period: 1
assert 422 in [200, 404]
```

**原因**
`api.py` 用 `lt=ARTICLE_LIMIT_MAX+1` 而不是 `le=ARTICLE_LIMIT_MAX`，導致邊界值判斷錯誤。

**解決方式**
統一使用 `ge`（greater or equal）和 `le`（less or equal）：
```python
limit: int = Query(default=10, ge=ARTICLE_LIMIT_MIN, le=ARTICLE_LIMIT_MAX)
```

---

## 10. uvicorn 找不到 api 模組

**問題**
```
ERROR: Error loading ASGI app. Could not import module "api"
```
或
```
ERROR: Error loading ASGI app. Could not import module "test_code/api"
```

**原因**
uvicorn 的模組名稱不是路徑，要用 Python import 格式（點號），且執行目錄必須是模組所在的目錄。

**解決方式**
方式一：cd 到 api.py 所在目錄再啟動：
```bash
cd /home/ubuntu/ptt_stock_db/dependent_code
uvicorn api:app --host 0.0.0.0 --port 8000
```

方式二：用點號格式指定模組路徑：
```bash
cd /home/ubuntu/ptt_stock_db
uvicorn test_code.api:app --host 0.0.0.0 --port 8000
```

---

## 11. pipeline.py 找不到 user_dict.txt

**問題**
```
FileNotFoundError: [Errno 2] No such file or directory: 'user_dict.txt'
```

**原因**
`sentiment.py` 用相對路徑載入 `user_dict.txt`，但執行 `pipeline.py` 時的工作目錄是 `ptt_stock_db`，不是 `dependent_code`。

**解決方式**
```bash
cd /home/ubuntu/ptt_stock_db/dependent_code
python3 pipeline.py
```

---

## 12. git pull Merge Conflict

**問題**
```
CONFLICT (rename/delete): test/QA.py renamed to test_code/QA.py
Automatic merge failed; fix conflicts and then commit the result.
```

**原因**
本機和 remote 有不同的變更，自動 merge 失敗。

**解決方式**
```bash
git checkout --theirs test_code/QA.py
git add .
git commit -m "resolve merge conflict"
git push
```

---

## 13. deploy.yml SSH key 格式錯誤

**問題**
```
ssh.ParsePrivateKey: ssh: no key found
ssh: handshake failed: ssh: unable to authenticate
```

**原因**
GitHub Secret `EC2_SSH_KEY` 的內容不完整，缺少頭尾：
```
-----BEGIN RSA PRIVATE KEY-----
-----END RSA PRIVATE KEY-----
```

**解決方式**
用 `cat ~/Downloads/ptt-key.pem` 複製完整內容（包含頭尾），重新設定 GitHub Secret。

---

## 14. get_change_sentiment 空 DB 時 TypeError

**問題**
```
TypeError: unsupported operand type(s) for -: 'float' and 'datetime.timedelta'
```

**原因**
空 DB 時 `df['Published_Date'].max()` 回傳 `NaN`（float），無法做日期運算。

**解決方式**
在日期操作前先檢查是否有資料：
```python
if len(df) == 0:
    raise HTTPException(status_code=404, detail={"message": "No data"})
df['Published_Time'] = pd.to_datetime(df['Published_Time'])
```

---

## 15. deploy.yml venv 路徑問題

**問題**
`source venv/bin/activate` 找不到 venv。

**原因**
venv 建立在 `dependent_code` 目錄下，但 deploy.yml 的工作目錄是 repo 根目錄。

**解決方式**
用 `find` 確認 venv 位置後，在正確目錄下 activate：
```bash
find /home/ubuntu/ptt_stock_db -name "activate"
```

確認後在 deploy.yml 中 cd 到正確目錄：
```yaml
script: |
  cd /home/ubuntu/ptt_stock_db
  git pull
  cd dependent_code
  source venv/bin/activate
  ...
```


---

## 16. Streamlit 路徑用點號格式錯誤

**問題**
```
Error: Invalid value: File does not exist: dependent_code.visualization.py
```

**原因**
deploy.yml 的 streamlit 指令用了 Python import 格式（點號），但 streamlit 要用路徑格式（斜線）。

**解決方式**
```yaml
# 錯誤
nohup streamlit run dependent_code.visualization.py ...

# 正確
nohup streamlit run dependent_code/visualization.py ...
```

---

## 17. CI/CD deploy job SSH session Timeout

**問題**
```
2026/03/14 08:04:18 Run Command Timeout
Error: Process completed with exit code 1
```

**原因**
`appleboy/ssh-action` 等待 SSH session 結束，但 uvicorn 和 streamlit 啟動後持續輸出 log，導致 session 不結束，最終超時。

**解決方式**
三個手段合用：
1. `setsid` — 建立新 session，完全脫離 SSH session
2. `> /dev/null 2>&1` — 把所有輸出丟掉，不讓 log 卡住 session
3. `command_timeout: 30s` — 設短 timeout，服務啟動後立即結束

```yaml
with:
  command_timeout: 30s
  script: |
    setsid nohup uvicorn test_code.api:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
    setsid nohup bash -c 'cd /home/ubuntu/ptt_stock_db/dependent_code && /home/ubuntu/ptt_stock_db/venv/bin/streamlit run visualization.py --server.port 8501 --server.address 0.0.0.0' > /dev/null 2>&1 &
    sleep 1 && exit 0
```

**`setsid` vs `nohup` 差別**
- `nohup` — 忽略 SIGHUP 信號，但程序還在同一個 session
- `setsid` — 建立全新 session，SSH 斷線完全不影響

---

## 18. user_dict.txt 相對路徑問題（import chain）

**問題**
```
FileNotFoundError: [Errno 2] No such file or directory: 'user_dict.txt'
```

**原因**
`visualization.py` import `data_cleanner` → import `analysis` → import `sentiment` → `jieba.load_userdict("user_dict.txt")`

`user_dict.txt` 用相對路徑，但執行時工作目錄不是 `dependent_code`，所以找不到。

**解決方式**
streamlit 啟動時必須在 `dependent_code` 目錄下執行：

```yaml
# 用 bash -c 在子 shell 切換目錄，不影響主 script
setsid nohup bash -c 'cd /home/ubuntu/ptt_stock_db/dependent_code && /home/ubuntu/ptt_stock_db/venv/bin/streamlit run visualization.py ...' > /dev/null 2>&1 &
```

或用絕對路徑在 `sentiment.py` 裡載入字典：
```python
import os
DICT_PATH = os.path.join(os.path.dirname(__file__), 'user_dict.txt')
jieba.load_userdict(DICT_PATH)
```

---

## 19. DB schema 缺少欄位

**問題**
```
KeyError: 'Published_Time'
KeyError: 'Article_Sentiment_Score'
```

**原因**
`Create_DB.py` 原始建表語法沒有 `Published_Time` 和 `Article_Sentiment_Score` 欄位，這兩個欄位是後來用 `ALTER TABLE` 加的。新 EC2 跑 `Create_DB.py` 建出來的 DB 就缺這些欄位。

**解決方式**
直接在 `Create_DB.py` 的建表語法裡加入這兩個欄位：

```python
CREATE TABLE IF NOT EXISTS ptt_stock_article_info (
    Article_id INTEGER PRIMARY KEY AUTOINCREMENT,
    Title TEXT,
    Push_count TEXT,
    Author TEXT,
    Url TEXT UNIQUE,
    Date TEXT,
    Content TEXT,
    Scraped_time TEXT,
    Article_Sentiment_Score REAL,   -- 新增
    Published_Time TEXT             -- 新增
)
```

`Comment_Sentiment_Score` 同理加進 `ptt_stock_comment_info`。

---

## 20. get_change_sentiment 空 DB 時 TypeError

**問題**
```
TypeError: unsupported operand type(s) for -: 'float' and 'datetime.timedelta'
```

**原因**
空 DB 時 `df['Published_Date'].max()` 回傳 `NaN`（float 型別），`NaN - datetime.timedelta(days=1)` 不合法。

**解決方式**
在日期操作前先判斷 DB 是否有資料：

```python
if len(df) == 0:
    raise HTTPException(status_code=404, detail={"message": "No data"})
df['Published_Time'] = pd.to_datetime(df['Published_Time'])
# 後續日期操作...
```

---

## 21. uvicorn 模組路徑格式錯誤

**問題**
```
ERROR: Error loading ASGI app. Could not import module "test_code/api"
```

**原因**
uvicorn 的模組名稱用的是 Python import 格式（點號），不是檔案路徑格式（斜線）。

**解決方式**
```bash
# 錯誤（路徑格式）
uvicorn test_code/api:app

# 正確（Python import 格式）
uvicorn test_code.api:app
```

執行目錄必須是 `test_code.api` 的上層，也就是 `ptt_stock_db` 根目錄。

---

## 22. cd 改變工作目錄影響後續指令

**問題**
deploy.yml 中間插入 `cd dependent_code`，導致後面的 uvicorn 找不到 `test_code.api`。

**原因**
shell script 裡的 `cd` 會改變整個 script 的工作目錄，後續所有指令都在新目錄下執行。

**解決方式**
用 `bash -c` 在子 shell 裡執行需要切換目錄的指令，不影響主 script：

```yaml
# 主 script 維持在 ptt_stock_db
cd /home/ubuntu/ptt_stock_db

# uvicorn 在根目錄跑
setsid nohup uvicorn test_code.api:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &

# streamlit 用子 shell 切換目錄
setsid nohup bash -c 'cd /home/ubuntu/ptt_stock_db/dependent_code && streamlit run visualization.py ...' > /dev/null 2>&1 &
```

