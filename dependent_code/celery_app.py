
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

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    timezone="Asia/Taipei",
    enable_utc=True,

    task_acks_late=True,
    worker_prefetch_multiplier=1,

    result_expires=86400,

    worker_concurrency=4,
)
