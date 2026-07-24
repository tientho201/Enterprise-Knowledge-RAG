from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserPlan, UserRole


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self,
        email: str,
        password_hash: str,
        full_name: str | None = None,
        role: UserRole = UserRole.viewer,
        email_verified: bool = False,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            role=role,
            email_verified=email_verified,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def verify_email(self, user_id: str) -> User | None:
        user = await self.get_by_id(user_id)
        if user:
            user.email_verified = True
            await self.db.flush()
        return user

    async def update_password_and_name(
        self, user: User, password_hash: str, full_name: str | None
    ) -> User:
        """Dùng khi 1 email đăng ký lại trong lúc tài khoản cũ chưa xác minh OTP —
        cho phép ghi đè mật khẩu/tên thay vì kẹt vĩnh viễn ở bản ghi chưa verify
        đầu tiên (xem AuthService.register). Nhận thẳng User đã fetch sẵn (thay vì
        user_id) vì caller luôn đã có bản ghi trong tay, tránh Optional thừa."""
        user.password_hash = password_hash
        user.full_name = full_name
        await self.db.flush()
        return user

    async def update_role(self, user_id: str, role: UserRole) -> User | None:
        user = await self.get_by_id(user_id)
        if user:
            user.role = role
            await self.db.flush()
        return user

    async def update_plan(self, user_id: str, plan: UserPlan) -> User | None:
        """Self-service demo upgrade/downgrade — không có cổng thanh toán thật.
        plan_expires_at không set ở đây (vô thời hạn); nối payment gateway thật
        sau này sẽ set hạn theo chu kỳ thanh toán."""
        user = await self.get_by_id(user_id)
        if user:
            user.plan = plan
            await self.db.flush()
        return user

    async def list_all(self, skip: int = 0, limit: int = 50) -> list[User]:
        result = await self.db.execute(select(User).offset(skip).limit(limit))
        return list(result.scalars().all())
