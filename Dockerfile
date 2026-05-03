# ============================================================
# PTT Stock Sentiment Analysis - Dockerfile
# 基於 python:3.9-slim，最小化生產環境映像
# ============================================================

FROM python:3.9-slim

# 系統依賴：gcc + libpq-dev（psycopg2 編譯需要）
# 安裝完立即清理 apt cache，減少映像大小
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先複製 requirements.txt 單獨安裝依賴（利用 Docker layer cache）
# 只要 requirements.txt 沒變，重建映像時這層直接用快取
COPY dependent_code/requirements.txt .
RUN pip install --no-cache-dir --timeout=120 --retries=3 -r requirements.txt

# 複製應用程式碼
COPY dependent_code/ .
# SP/Function 定義（data_mart.ensure_sp_schema() 的 container fallback 路徑）
COPY scripts/init_marts.sql .

EXPOSE 8000

# 預設啟動 FastAPI（uvicorn）
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
