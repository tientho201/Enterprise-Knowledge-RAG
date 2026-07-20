"""JWT blacklist trên Redis — cho logout / thu hồi token.

Token JWT là stateless nên logout không tự vô hiệu hoá token. Ta lưu `jti` của token
đã logout vào Redis với TTL = thời gian còn lại tới `exp`. Sau khi token hết hạn tự
nhiên, key cũng tự xoá → không phình bộ nhớ.
"""

import logging
import time

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_PREFIX = "jwt:blacklist:"


async def blacklist_token(jti: str, exp: int | float) -> None:
    """Đưa `jti` vào blacklist tới khi token hết hạn (`exp` = epoch seconds)."""
    ttl = int(exp - time.time())
    if ttl <= 0:
        return  # token đã hết hạn — không cần lưu
    try:
        await get_redis().set(f"{_PREFIX}{jti}", "1", ex=ttl)
    except Exception:  # noqa: BLE001 — Redis down: logout best-effort, không chặn user
        logger.warning("Redis unavailable — không thể blacklist token %s", jti, exc_info=True)


async def is_blacklisted(jti: str | None) -> bool:
    if not jti:
        return False
    try:
        return await get_redis().exists(f"{_PREFIX}{jti}") == 1
    except Exception:  # noqa: BLE001 — fail-open: Redis down không được khoá toàn bộ auth
        logger.warning("Redis unavailable — bỏ qua kiểm tra blacklist (fail-open)", exc_info=True)
        return False
