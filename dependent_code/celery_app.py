# ─── Celery 應用程式設定 ─────────────────────────────────────────────
# 使用 Redis 作為 message broker 與 result backend
# broker:  redis://<host>:6379/0（任務佇列）
# backend: redis://<host>:6379/1（結果儲存）
# REDIS_HOST 預設 localhost（本機開發），Docker/K8s 環境透過環境變數覆蓋

import os
from celery import Celery

_REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
_REDIS_PORT = os.environ.get("REDIS_PORT", "6379")

app = Celery(
    "stock_sentiment",
    broker=f"redis://{_REDIS_HOST}:{_REDIS_PORT}/0",
    backend=f"redis://{_REDIS_HOST}:{_REDIS_PORT}/1",
    include=["tasks"],
)

# ─── Celery 全域設定 ──────────────────────────────────────────────────
app.conf.update(
    # 序列化格式：JSON（可讀、跨語言）
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 時區設定（與 pipeline log 一致）
    timezone="Asia/Taipei",
    enable_utc=True,

    # 任務執行限制
    task_acks_late=True,             # 任務完成後才確認（worker 中途死掉可重派）
    worker_prefetch_multiplier=1,    # 每次只取一個任務（避免長任務卡住其他 worker）

    # 結果過期時間：24 小時
    result_expires=86400,

    # Worker 同時處理的任務數
    worker_concurrency=4,
)
