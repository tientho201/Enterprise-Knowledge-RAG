"""Async Redis client (redis.asyncio) dùng chung cho health check, rate limiting, JWT blacklist.

redis>=5 đã là dependency (Celery broker) nên không thêm dep mới. Client được cache
theo process — an toàn với asyncio (redis.asyncio tự quản connection pool nội bộ).
"""

from functools import lru_cache

import redis.asyncio as aioredis

from app.core.config import settings


@lru_cache
def get_redis() -> aioredis.Redis:
    """Return a cached async Redis client backed by REDIS_URL."""
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
