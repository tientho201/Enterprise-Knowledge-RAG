from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.conversation import Conversation


class UserRole(enum.StrEnum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class UserPlan(enum.StrEnum):
    """Gói trả phí — cổng tính năng (vd Chế độ tra cứu "Nâng cao"), TÁCH BIỆT với
    UserRole (phân quyền duyệt/quản trị). 2 trục độc lập: 1 user có thể vừa admin
    vừa plan=free (role không tự nâng plan), hoặc viewer + pro.
    Admin luôn được coi như đủ quyền "Nâng cao" bất kể plan — xem
    core/plan_gate.py::can_use_advanced_search, không cần set plan=pro cho admin."""

    free = "free"
    pro = "pro"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Riêng biệt với is_active (đó là cờ admin khóa/mở tài khoản). email_verified=False
    # tới khi user xác minh OTP gửi qua email lúc đăng ký — xem core/otp.py + auth_service.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plan: Mapped[UserPlan] = mapped_column(Enum(UserPlan), nullable=False, default=UserPlan.free)
    # None = không áp dụng hạn (vd đang free, hoặc pro vô thời hạn). Có giá trị + đã qua
    # -> coi như hết hạn dù plan vẫn ghi "pro" (chưa có job tự hạ cấp — việc đó thuộc
    # phase nối payment gateway thật sau này, xem can_use_advanced_search).
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan"
    )
