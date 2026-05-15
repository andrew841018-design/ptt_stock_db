import redis
import logging
import pandas as pd
from io import StringIO
from typing import Optional
import os

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_TTL  = 86400

_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_cache(key: str) -> Optional[pd.DataFrame]:
    try:
        data = _redis.get(key)
        if data:
            logging.info(f"Cache HIT: {key}")
            return pd.read_json(StringIO(data), orient='table')
        logging.info(f"Cache MISS: {key}")
    except redis.RedisError as e:
        logging.warning(f"Redis get failed: {e}")
    return None


def set_cache(key: str, df: pd.DataFrame) -> None:
    try:
        _redis.setex(key, REDIS_TTL, df.to_json(orient='table'))
    except redis.RedisError as e:
        logging.warning(f"Redis set failed: {e}")
