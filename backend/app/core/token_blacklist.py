"""JWT blacklist trên Redis — cho logout / thu hồi token.

Token JWT là stateless nên logout không tự vô hiệu hoá token. Ta lưu `jti` của token
đã logout vào Redis với TTL = thời gian còn lại tới `exp`. Sau khi token hết hạn tự
nhiên, key cũng tự xoá → không phình bộ nhớ.
"""

import time

from app.core.redis_client import get_redis

_PREFIX = "jwt:blacklist:"


async def blacklist_token(jti: str, exp: int | float) -> None:
    """Đưa `jti` vào blacklist tới khi token hết hạn (`exp` = epoch seconds)."""
    ttl = int(exp - time.time())
    if ttl <= 0:
        return  # token đã hết hạn — không cần lưu
    await get_redis().set(f"{_PREFIX}{jti}", "1", ex=ttl)


async def is_blacklisted(jti: str | None) -> bool:
    if not jti:
        return False
    return await get_redis().exists(f"{_PREFIX}{jti}") == 1
