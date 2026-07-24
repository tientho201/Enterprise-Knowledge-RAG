"""OTP (mã xác minh email 6 số) — sinh, lưu, verify qua Redis.

Redis TTL tự hết hạn OTP, không cần cột DB riêng hay job dọn dẹp. Dùng cho luồng
xác minh email lúc đăng ký (xem services/auth_service.py). Key theo user_id
(không theo email) — email có thể đổi chủ giữa các lần đăng ký lại trước khi
verify (xem AuthService.register), user_id thì cố định 1 bản ghi.
"""

import logging
import secrets

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_OTP_KEY = "otp:register:{user_id}"
_ATTEMPTS_KEY = "otp:attempts:{user_id}"
_COOLDOWN_KEY = "otp:cooldown:{user_id}"


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def issue_otp(user_id: str) -> str:
    """Sinh OTP mới, lưu Redis (TTL OTP_EXPIRE_MINUTES), reset bộ đếm số lần thử sai."""
    code = generate_otp_code()
    redis = get_redis()
    ttl_seconds = settings.OTP_EXPIRE_MINUTES * 60
    await redis.set(_OTP_KEY.format(user_id=user_id), code, ex=ttl_seconds)
    await redis.delete(_ATTEMPTS_KEY.format(user_id=user_id))
    return code


async def seconds_until_resend_allowed(user_id: str) -> int:
    """0 nếu được phép gửi lại ngay, > 0 = số giây còn phải chờ."""
    redis = get_redis()
    ttl = await redis.ttl(_COOLDOWN_KEY.format(user_id=user_id))
    return max(ttl, 0)


async def start_resend_cooldown(user_id: str) -> None:
    redis = get_redis()
    await redis.set(
        _COOLDOWN_KEY.format(user_id=user_id), "1", ex=settings.OTP_RESEND_COOLDOWN_SECONDS
    )


async def verify_otp(user_id: str, code: str) -> None:
    """Raise HTTPException 400 nếu OTP sai/hết hạn/vượt số lần thử; xóa OTP nếu đúng."""
    redis = get_redis()
    otp_key = _OTP_KEY.format(user_id=user_id)
    attempts_key = _ATTEMPTS_KEY.format(user_id=user_id)

    stored = await redis.get(otp_key)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã OTP đã hết hạn hoặc không tồn tại. Vui lòng yêu cầu gửi lại mã.",
        )

    attempts = await redis.incr(attempts_key)
    if attempts == 1:
        await redis.expire(attempts_key, settings.OTP_EXPIRE_MINUTES * 60)
    if attempts > settings.OTP_MAX_ATTEMPTS:
        await redis.delete(otp_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nhập sai mã OTP quá số lần cho phép. Vui lòng yêu cầu gửi lại mã.",
        )

    if not secrets.compare_digest(stored, code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mã OTP không đúng.")

    await redis.delete(otp_key)
    await redis.delete(attempts_key)
