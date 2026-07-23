"""
Gate tính năng trả phí — hiện chỉ áp dụng cho Chế độ tra cứu "Nâng cao" (chat).

UserRole (phân quyền duyệt/quản trị) và UserPlan (gói trả phí) là 2 trục độc lập —
xem models/user.py::UserPlan. Admin luôn qua được gate này bất kể plan.
"""

from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.core.dependencies import CurrentUserDep
from app.models.user import User, UserPlan, UserRole
from app.schemas.chat import ChatRequest


def can_use_advanced_search(user: User) -> bool:
    """Admin luôn qua được (bất kể plan). Không phải admin: cần plan=pro và chưa hết hạn."""
    if user.role == UserRole.admin:
        return True
    if user.plan != UserPlan.pro:
        return False
    expires_at = user.plan_expires_at
    if expires_at is not None:
        # Phòng driver/DB trả về datetime naive (vd sqlite không lưu tzinfo) dù cột khai
        # báo DateTime(timezone=True) — coi naive là UTC thay vì crash lúc so sánh.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return False
    return True


async def require_advanced_search_access(body: ChatRequest, user: CurrentUserDep) -> None:
    """
    FastAPI dependency — chặn 403 nếu request chọn search_mode="advanced" mà user
    không đủ quyền. `user` (CurrentUserDep) đã fetch bản ghi mới nhất từ DB qua
    user_id giải mã từ JWT — KHÔNG tin claim tĩnh trong token, vì plan có thể đổi
    giữa các phiên đăng nhập; nếu cache trong JWT, user bị huỷ gói vẫn dùng được
    "Nâng cao" tới khi token hết hạn.

    Đặt ở tầng route (`dependencies=[Depends(...)]`, cùng vị trí `rate_limiter()`) —
    gọi thẳng API vẫn bị chặn; ẩn/khoá nút ở frontend chỉ là lớp UX.
    """
    if body.search_mode != "advanced":
        return
    if not can_use_advanced_search(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chế độ tra cứu Nâng cao yêu cầu gói trả phí (Pro).",
        )
