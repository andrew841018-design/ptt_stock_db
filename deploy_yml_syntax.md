# GitHub Actions YAML 語法說明

## 頂層關鍵字

| 關鍵字 | 用途 |
|--------|------|
| `name` | workflow 的名稱，顯示在 GitHub Actions 頁面 |
| `on` | 觸發條件，什麼時候執行這個 workflow |
| `jobs` | 定義要執行的工作，底下可以有多個 job |

---

## `on` — 觸發條件

```yaml
on:
  push:             # push 時觸發
    branches:
      - main        # 只有 push 到 main branch 才觸發
```

---

## `jobs` — 工作定義

```yaml
jobs:
  job名稱:          # 自訂名稱，例如 test、deploy
    runs-on: ...    # 在哪台機器上執行
    needs: ...      # 等哪個 job 完成才執行
    steps:          # 這個 job 要做的步驟
```

---

## `steps` 底下的關鍵字

| 關鍵字 | 用途 |
|--------|------|
| `name` | 這個步驟的名稱，顯示在 GitHub Actions 頁面 |
| `uses` | 引用別人寫好的 Action（類似 pip 裝套件） |
| `run` | 直接執行 bash 指令 |
| `with` | 傳入參數給 `uses` 的 Action |

---

## `uses` vs `run`

```yaml
# uses — 引用現成 Action，背後封裝了複雜的操作
- uses: actions/setup-python@v4
  with:
    python-version: '3.10'

# run — 直接寫 bash 指令
- run: |
    pip install -r require_lib.txt
    pytest test_api.py -v
```

---

## `needs` — job 依賴

```yaml
jobs:
  test:             # 第一個 job
  deploy:
    needs: test     # 等 test 成功才執行，名稱對應上面的 job 名稱
```

---

## `secrets` — 環境變數

```yaml
${{ secrets.EC2_HOST }}     # 讀取 GitHub repo Settings 裡設定的變數
```
敏感資訊（IP、金鑰）存在 GitHub Settings，不寫在程式碼裡。
名稱自訂，yml 和 GitHub Settings 兩邊一致即可。

---

## `runs-on` — 執行環境

```yaml
runs-on: ubuntu-latest    # GitHub 提供的全新 Ubuntu 虛擬機
                          # 每次跑完就銷毀，下次又是全新的
```

---

## `run: |` 的 `|`

`|` 是 YAML 的多行字串符號，讓你可以寫多行 bash 指令：

```yaml
run: |
  pip install -r require_lib.txt
  pytest test_api.py -v
```
