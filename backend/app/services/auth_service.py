from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import otp
from app.core.plan_gate import can_use_advanced_search
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserPlan
from app.repositories.user_repo import UserRepository
from app.schemas.auth import OtpPendingResponse, TokenResponse, UserResponse

_OTP_SENT_MESSAGE = "Mã OTP xác minh đã được gửi tới email của bạn. Vui lòng kiểm tra hộp thư."


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        plan=user.plan,
        can_use_advanced_search=can_use_advanced_search(user),
    )


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UserRepository(db)

    async def register(
        self,
        email: str,
        password: str,
        full_name: str | None = None,
    ) -> OtpPendingResponse:
        existing = await self.repo.get_by_email(email)
        if existing:
            if existing.email_verified:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered",
                )
            # Đăng ký lại trong lúc bản ghi cũ chưa xác minh OTP (vd quên, gõ sai
            # mật khẩu, hoặc mã hết hạn) — ghi đè mật khẩu/tên và gửi OTP mới thay
            # vì kẹt vĩnh viễn hoặc trả 409 cho 1 tài khoản chưa từng dùng được.
            user = await self.repo.update_password_and_name(
                existing, hash_password(password), full_name
            )
        else:
            user = await self.repo.create(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                email_verified=False,
            )
        await self._issue_and_send_otp(user)
        return OtpPendingResponse(email=user.email, message=_OTP_SENT_MESSAGE)

    async def verify_otp(self, email: str, otp_code: str) -> TokenResponse:
        user = await self.repo.get_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email hoặc mã OTP không hợp lệ.",
            )
        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email đã được xác minh trước đó. Vui lòng đăng nhập.",
            )
        await otp.verify_otp(user.id, otp_code)
        await self.repo.verify_email(user.id)
        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def resend_otp(self, email: str) -> OtpPendingResponse:
        user = await self.repo.get_by_email(email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email đã được xác minh trước đó. Vui lòng đăng nhập.",
            )
        wait_seconds = await otp.seconds_until_resend_allowed(user.id)
        if wait_seconds > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Vui lòng đợi {wait_seconds}s trước khi yêu cầu gửi lại mã.",
                headers={"Retry-After": str(wait_seconds)},
            )
        await self._issue_and_send_otp(user)
        return OtpPendingResponse(email=user.email, message=_OTP_SENT_MESSAGE)

    async def _issue_and_send_otp(self, user: User) -> None:
        code = await otp.issue_otp(user.id)
        await otp.start_resend_cooldown(user.id)
        from app.workers.tasks.email import send_otp_email

        send_otp_email.delay(user.email, code, user.full_name)

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.repo.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )
        if not user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email chưa được xác minh. Vui lòng kiểm tra OTP đã gửi tới email.",
            )
        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        user_id = payload["sub"]
        user = await self.repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def get_current_user(self, user_id: str) -> UserResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return _to_user_response(user)

    async def update_plan(self, user_id: str, plan: UserPlan) -> UserResponse:
        """Self-service demo nâng cấp/hạ cấp gói — KHÔNG có cổng thanh toán thật đứng
        sau (xem schemas/auth.py::UpdatePlanRequest). User tự đổi plan của chính mình."""
        user = await self.repo.update_plan(user_id, plan)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return _to_user_response(user)
