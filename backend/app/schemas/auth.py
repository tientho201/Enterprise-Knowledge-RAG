from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserPlan, UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: str | None = None


class OtpPendingResponse(BaseModel):
    """Trả về sau /register và /resend-otp — báo hiệu tài khoản đang chờ xác minh
    email, KHÔNG phải UserResponse đầy đủ (tránh lộ role/plan trước khi verify)."""

    email: str
    message: str


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(min_length=6, max_length=6)


class ResendOtpRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    plan: UserPlan
    # Computed (không phải cột DB) — xem core/plan_gate.py::can_use_advanced_search.
    # Frontend dùng field này để khoá/mở nút "Nâng cao", KHÔNG tự suy luận từ role/plan
    # ở client (tránh lệch logic 2 nơi — backend vẫn là nguồn chặn thật qua 403).
    can_use_advanced_search: bool

    model_config = {"from_attributes": True}


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UpdatePlanRequest(BaseModel):
    # Self-service demo — KHÔNG có cổng thanh toán thật (Stripe...) đứng sau. Xem
    # core/plan_gate.py + services/auth_service.py::update_plan.
    plan: UserPlan
