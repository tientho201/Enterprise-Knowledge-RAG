from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.core.security import decode_token
from app.core.token_blacklist import blacklist_token
from app.schemas.auth import (
    LoginRequest,
    OtpPendingResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResendOtpRequest,
    TokenResponse,
    UpdatePlanRequest,
    UserResponse,
    VerifyOtpRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer()


@router.post("/register", response_model=OtpPendingResponse, status_code=201)
async def register(body: RegisterRequest, db: DbDep):
    """Tạo tài khoản (chưa active để đăng nhập) và gửi mã OTP xác minh qua email.
    Gọi `/auth/verify-otp` để hoàn tất đăng ký."""
    service = AuthService(db)
    return await service.register(body.email, body.password, body.full_name)


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(body: VerifyOtpRequest, db: DbDep):
    """Xác minh mã OTP đã gửi lúc /register — thành công thì trả token (auto-login)."""
    service = AuthService(db)
    return await service.verify_otp(body.email, body.otp_code)


@router.post("/resend-otp", response_model=OtpPendingResponse)
async def resend_otp(body: ResendOtpRequest, db: DbDep):
    service = AuthService(db)
    return await service.resend_otp(body.email)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbDep):
    service = AuthService(db)
    return await service.login(body.email, body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshTokenRequest, db: DbDep):
    service = AuthService(db)
    return await service.refresh(body.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(user_id: CurrentUserIdDep, db: DbDep):
    service = AuthService(db)
    return await service.get_current_user(user_id)


@router.post("/plan", response_model=UserResponse)
async def update_plan(body: UpdatePlanRequest, user_id: CurrentUserIdDep, db: DbDep):
    """Self-service demo nâng cấp/hạ cấp gói — KHÔNG thu tiền thật (chưa nối payment
    gateway). User chỉ đổi được plan của chính mình."""
    service = AuthService(db)
    return await service.update_plan(user_id, body.plan)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
):
    """Thu hồi access token hiện tại — đẩy jti vào Redis blacklist tới khi token hết hạn.

    Idempotent: token không hợp lệ / đã hết hạn vẫn trả 204 (không lộ thông tin token).
    """
    payload = decode_token(credentials.credentials)
    if payload and payload.get("jti") and payload.get("exp"):
        await blacklist_token(payload["jti"], payload["exp"])
