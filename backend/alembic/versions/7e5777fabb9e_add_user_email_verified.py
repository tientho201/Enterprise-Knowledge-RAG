"""add user email_verified (OTP đăng ký)

Cột mới trên `users` để tách "email đã xác minh OTP" khỏi `is_active` (đó là cờ
admin khóa/mở tài khoản — 2 trục độc lập, cùng pattern với role/plan). Backfill
server_default=true cho user đã tồn tại (đăng ký trước khi có luồng OTP, coi như
đã hợp lệ); user mới do `UserRepository.create()` set explicit False.

Revision ID: 7e5777fabb9e
Revises: f6a7b8c9d0e1
Create Date: 2026-07-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e5777fabb9e"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column("users", "email_verified", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "email_verified")
