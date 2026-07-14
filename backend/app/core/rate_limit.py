"""Rate limiting per-user dựa trên Redis (fixed-window INCR + expire).

Nhẹ, không thêm dependency (slowapi) — tái dùng `redis.asyncio` sẵn có. Áp cho các route
tốn kém (chat → cost OpenAI, upload → cost ingestion). Key theo user_id (đã auth), fallback
IP. **Fail-open**: nếu Redis lỗi thì cho request đi qua (log warning) — rate limit không được
phép làm sập API khi Redis chập chờn.
"""

import logging

from fastapi import Depends, HTTPException, Request, status

from app.core.dependencies import get_current_user_id
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


def rate_limiter(limit: int, window_seconds: int, scope: str):
    """Tạo FastAPI dependency giới hạn `limit` request / `window_seconds` cho mỗi user."""

    async def _dependency(
        request: Request,
        user_id: str = Depends(get_current_user_id),
    ) -> None:
        identity = user_id or (request.client.host if request.client else "anon")
        key = f"ratelimit:{scope}:{identity}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
        except Exception as exc:  # noqa: BLE001 — fail-open, không chặn khi Redis lỗi
            logger.warning("Rate limiter bỏ qua (Redis lỗi): %s", exc)
            return
        if count > limit:
            ttl = await redis.ttl(key)
            retry_after = max(ttl, 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for '{scope}'. Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
