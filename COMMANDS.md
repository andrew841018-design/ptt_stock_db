# COMMANDS 指令速查表

> 所有操作的單一入口。優先使用 `python dependent_code/cli.py <sub>`，少數 infra 操作列在底部。

---

## 🚀 First-time Setup

```bash
# 1. clone + 進入 conda env
git clone https://github.com/andrew841018-design/ptt_stock_db.git
cd ptt_stock_db
conda activate de_project                    # 或 pip install -r dependent_code/requirements.txt

# 2. 產生 JWT 金鑰與密碼 hash，填入 .env
python dependent_code/cli.py gen-jwt-secret          # → JWT_SECRET_KEY=...
python dependent_code/cli.py gen-pw-hash admin <pw>  # → ADMIN_PW_HASH=...
python dependent_code/cli.py gen-pw-hash viewer <pw> # → VIEWER_PW_HASH=...
# 把上面三行輸出貼進 .env，再加上 PRODUCTION=true

# 3. 啟動基礎服務（PG / Redis / MongoDB）
python dependent_code/cli.py services up

# 4. 建 schema + 初始化 DW
python dependent_code/cli.py schema
python dependent_code/cli.py dw-etl
```

---

## 🔐 Auth 金鑰設定（`auth.py` 對應的環境變數）

> `auth.py` 從三個環境變數讀取金鑰；未設時 production 模式會拒絕啟動。
> 以下指令負責產生對應的值，輸出直接是 `.env` 格式，複製貼上即可。

| 指令 | 寫入的 .env 變數 | 說明 |
|------|-----------------|------|
| `python dependent_code/cli.py gen-jwt-secret` | `JWT_SECRET_KEY` | 256-bit 隨機 hex，用來簽名 / 驗證所有 JWT token |
| `python dependent_code/cli.py gen-pw-hash admin <pw>` | `ADMIN_PW_HASH` | admin 帳號的 bcrypt hash（slow-hash，防 brute-force）|
| `python dependent_code/cli.py gen-pw-hash viewer <pw>` | `VIEWER_PW_HASH` | viewer 帳號的 bcrypt hash |

**完整流程：**

```bash
# 1. 產生三個值（每次部署新環境都重新產，不要重用舊金鑰）
python dependent_code/cli.py gen-jwt-secret
# 輸出：JWT_SECRET_KEY=a3f8c2d1e4b7...

python dependent_code/cli.py gen-pw-hash admin myAdminPw123
# 輸出：ADMIN_PW_HASH=$2b$12$xxxxx...

python dependent_code/cli.py gen-pw-hash viewer myViewerPw456
# 輸出：VIEWER_PW_HASH=$2b$12$yyyyy...

# 2. 把三行輸出貼進 .env，再加上：
#    PRODUCTION=true
```

> ⚠️ 未設 `PRODUCTION=true` 時，`auth.py` 會用內建的 demo hash（admin123 / viewer123）並印 warning；設了 `PRODUCTION=true` 但沒補這三個變數，啟動時直接 `RuntimeError`。

---

## 🔄 日常開發（Dev Servers）

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py dev api` | 啟動 FastAPI（uvicorn --reload, :8000）|
| `python dependent_code/cli.py dev dashboard` | 啟動 Streamlit 主儀表板 |
| `python dependent_code/cli.py dev labeling` | 啟動 Streamlit 標注工具 |
| `python dependent_code/cli.py worker` | 啟動 Celery worker（4 concurrency） |
| `python dependent_code/cli.py logs <service>` | 跟著看某 container log（例：`logs api`） |

---

## 📦 Pipeline / ETL

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py pipeline` | 跑完整 9 步 pipeline |
| `python dependent_code/cli.py extract` | 只跑爬蟲（多來源並行） |
| `python dependent_code/cli.py transform` | QA + 自動修復 + GE 驗證 |
| `python dependent_code/cli.py pii` | PII 遮蔽（author hash 化）|
| `python dependent_code/cli.py bert infer` | BERT 批次推論 |
| `python dependent_code/cli.py dw-etl` | OLTP → DW + 刷新 Data Mart |
| `python dependent_code/cli.py backup` | S3 備份 |

---

## 🧪 測試 / QA

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py validate` | **靜態驗證全套**（Python / YAML / dbt / Docker / pytest）— 對應 CI 的 validate.yml |
| `python dependent_code/cli.py test` | 預設跑 `test_api.py -v` |
| `python dependent_code/cli.py test scrapers/` | 指定路徑 pytest |
| `python dependent_code/cli.py qa` | 資料品質檢查（DB 資料層面）|
| `python dependent_code/cli.py ge` | Great Expectations 驗證 |
| `python dependent_code/cli.py perf-audit` | PG 慢查詢 / 未用 index 審計 |

> **`validate` vs `test` 差別**：`validate` 驗**設定檔 / infra 正確性**（不用 deploy），`test` 驗**業務邏輯**（需要 DB）。CI 每次 push 自動跑 validate，`validate.yml` 在 `.github/workflows/`。

---

## 📊 dbt

```bash
# 所有 dbt 指令一律透過 cli.py（自動載入 .env）
python dependent_code/cli.py dbt debug           # 檢查連線
python dependent_code/cli.py dbt deps            # 裝 dbt_utils
python dependent_code/cli.py dbt parse           # 語法檢查
python dependent_code/cli.py dbt run             # 建所有 models
python dependent_code/cli.py dbt test            # 跑 data tests
python dependent_code/cli.py dbt docs generate   # 產文件
python dependent_code/cli.py dbt run --target bigquery  # 切 BQ target
```

---

## 🐳 Services（Docker Compose）

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py services up` | `docker-compose up -d` |
| `python dependent_code/cli.py services down` | `docker-compose down` |
| `python dependent_code/cli.py services ps` | 列出 container 狀態 |
| `python dependent_code/cli.py logs api` | 跟著看 api log |

---

## ☸️ K8s

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py k8s-apply-secrets` | **從 .env 同步 Secret 到集群**（idempotent）|
| `python dependent_code/cli.py k8s-debug` | **臨時起 debug Pod**（開 bash，退出自刪，不占資源）|
| `python dependent_code/cli.py k8s-debug python cli.py qa` | 在 debug Pod 裡跑一次 QA，跑完結束 |
| `kubectl apply -f k8s/` | 部署全部 manifests |
| `kubectl get pods -n stock-sentiment` | 查 pod 狀態 |
| `kubectl logs -f -n stock-sentiment <pod>` | 跟 pod log |

⚠️ **不要** `kubectl apply -f k8s/secret.yaml`（裡面是 placeholder）。改用 `cli.py k8s-apply-secrets`。

> **設計說明**：沒有常駐 worker Deployment——排程任務由 CronJob 每次啟動新 Pod 跑，debug 用 `k8s-debug` 臨時起 Pod。比 idle Deployment 省 24/7 資源。

---

## 🤖 AI / 抓歷史資料

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py ai-predict run tw` | Walk-Forward 預測（台股）|
| `python dependent_code/cli.py ai-predict run us` | Walk-Forward 預測（美股）|
| `python dependent_code/cli.py llm-label` | Claude Haiku 輔助標注 50 篇 |
| `python dependent_code/cli.py reddit-batch` | Reddit 全歷史載入 |
| `python dependent_code/cli.py reddit-batch 2024-01-01 2024-03-01` | 指定區間 |
| `python dependent_code/cli.py wayback-backfill cnn --min-year 2015` | CNN Wayback 回填 |
| `python dependent_code/cli.py wayback-backfill wsj --max-articles 500` | WSJ 限量 |

---

## 🔧 診斷 / 修復

| 指令 | 用途 |
|------|------|
| `python dependent_code/cli.py reparse` | 從 MongoDB raw 重新解析修復 |
| `python dependent_code/cli.py mongo` | MongoDB 連線測試 + 查 raw_responses 筆數 |
| `bash scripts/health_check.sh` | 健檢所有服務（PG / Redis / API / Airflow） |

---

## 🚢 部署（EC2 / CI-CD）

```bash
bash scripts/deploy.sh                # git pull + build + up + health check
bash scripts/run_etl.sh               # launchd 每小時自動呼叫（不用手動）
```

### GitHub Actions 觸發方式

**自動觸發（push 就跑）：**

| Workflow | 觸發條件 | 內容 |
|----------|---------|------|
| `validate.yml` | **任何 push / PR** | 靜態驗證（kubeconform / hadolint / yamllint / dbt parse / pytest） |
| `deploy.yml` | **push to main** | test → build（可選）→ deploy-docker → post-deploy |

**手動觸發（要進階 job 才用）：**

GitHub UI 操作：
1. 打開 `https://github.com/andrew841018-design/ptt_stock_db/actions`
2. 左側點 `CI/CD Pipeline`
3. 右側點 **`Run workflow`** 按鈕
4. 勾選要跑的 opt-in 任務：
   - `deploy_k8s` — 部署到 K8s cluster（需要 KUBE_CONFIG secret）
   - `ec2_setup` — EC2 初始建置（**一次性**動作：裝 Docker、建資料夾）
   - `wayback_backfill` — 跑 CNN + WSJ 全歷史補抓（**耗時 12 小時**）

命令列操作（`gh` CLI，較快）：

```bash
# 預設跑（只跑核心部署流程，三個 opt-in 都 false）
gh workflow run deploy.yml --ref main

# 勾選 ec2-setup（一次性 EC2 初始化）
gh workflow run deploy.yml --ref main -f ec2_setup=true

# 勾選 wayback 補抓（會跑 12 小時背景執行）
gh workflow run deploy.yml --ref main -f wayback_backfill=true

# 勾選 K8s 部署（需先設 KUBE_CONFIG secret）
gh workflow run deploy.yml --ref main -f deploy_k8s=true

# 看最近 5 次 run 結果
gh run list --workflow=deploy.yml --limit 5

# 跟某次 run 的即時 log（拿到 run id 後）
gh run view <run-id> --log
```

### 必要 GitHub Secrets（透過 `gh secret set` 設定）

```bash
# 必要（才能 deploy）
gh secret set EC2_IP --body "52.65.94.221"
gh secret set EC2_SSH_KEY < ptt-key.pem

# 選配（設了才會啟用對應功能）
gh secret set DOCKER_USERNAME --body "<your-dockerhub-user>"    # Docker Hub push
gh secret set DOCKER_PASSWORD --body "<your-access-token>"
gh secret set KUBE_CONFIG --body "$(base64 < ~/.kube/config)"  # K8s deploy

# 查看現有 secrets（只列名字，安全）
gh secret list
```

### 為什麼 ec2-setup / wayback-backfill 要手動觸發？

這兩個任務**不適合每次 push 自動跑**：

| Job | 原因 |
|-----|------|
| `ec2-setup` | 一次性建置（裝 Docker、建資料夾），自動跑會重裝壞東西 |
| `wayback-backfill` | 跑 12 小時大型補抓，自動跑會卡整天 CI |
| `deploy-k8s` | 你沒 K8s cluster，設自動會每 push 都 fail |

**設計原則**：**破壞性或長耗時的操作一律手動觸發**（防誤觸）。

---

## 📘 其他（不走 cli.py，原生工具就好）

```bash
# Git
git clone <url>
git pull origin main --rebase

# Pip / Conda
pip install -r dependent_code/requirements.txt
conda activate de_project

# Docker 底層（debug 用）
docker-compose build --no-cache                       # 重 build image
docker exec stock_postgres pg_isready -q              # 原生健檢
docker exec stock_redis redis-cli ping
docker exec -it stock_postgres psql -U postgres       # 進 PG CLI

# PG 手動查
pg_isready -h localhost -p 5432
psql -h localhost -U postgres -d stock_analysis_db
```

---

## 🎯 面試 Demo 流程（給 reviewer 看的最小路徑）

```bash
# 1. 起所有服務
python dependent_code/cli.py services up

# 2. 建 schema + 跑完整 pipeline（爬 10 頁 demo）
python dependent_code/cli.py schema
python dependent_code/cli.py pipeline

# 3. 啟動 API + Dashboard
python dependent_code/cli.py dev api       # 另開一個 terminal
python dependent_code/cli.py dev dashboard # 再開一個

# 4. 打開瀏覽器
# http://localhost:8000/docs       ← Swagger UI
# http://localhost:8501            ← Streamlit
# http://localhost:3000            ← Grafana（監控儀表板）
# http://localhost:9090            ← Prometheus（指標查詢）

# 5. 跑 tests 證明可靠
python dependent_code/cli.py test
```

---

## 🗂️ 指令發現（忘記該用什麼時）

```bash
python dependent_code/cli.py --help          # 列出所有 subcommand
python dependent_code/cli.py <sub> --help    # 某個 subcommand 的詳細參數
```
