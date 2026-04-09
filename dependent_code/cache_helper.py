import redis
import logging
import pandas as pd
from io import StringIO
from typing import Optional
import os

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_TTL  = 86400  # 24 hours (seconds)

# 類似hash是一個key-value store.
_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_cache(key: str) -> Optional[pd.DataFrame]:
    """從 Redis 取快取，回傳 DataFrame；找不到回傳 None"""
    try:
        data = _redis.get(key)  # string type
        if data:
            logging.info(f"Cache HIT: {key}")
            return pd.read_json(StringIO(data), orient='table')  # StringIO(data) is file-like object, so we can use it as a file
        logging.info(f"Cache MISS: {key}")
    except redis.RedisError as e:
        # Redis 掛掉時不中斷 API，直接走 DB
        logging.warning(f"Redis get failed: {e}")
    return None


def set_cache(key: str, df: pd.DataFrame) -> None:
    """將 DataFrame 存入 Redis，TTL 由 config.REDIS_TTL 控制"""
    try:
        _redis.setex(key, REDIS_TTL, df.to_json(orient='table'))
    except redis.RedisError as e:
        logging.warning(f"Redis set failed: {e}")
