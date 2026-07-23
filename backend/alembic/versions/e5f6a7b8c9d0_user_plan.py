"""user plan (subscription gate, Chế độ tra cứu Nâng cao)

Thêm users.plan (enum free|pro, default free) + users.plan_expires_at (nullable).
Tách biệt hoàn toàn với users.role (phân quyền) — xem models/user.py::UserPlan.
User hiện có đều mặc định free (server_default), không có ai bị khoá quyền hiện tại.

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_user_plan_enum = postgresql.ENUM("free", "pro", name="userplan")


def upgrade() -> None:
    """Upgrade schema."""
    _user_plan_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column(
            "plan",
            _user_plan_enum,
            nullable=False,
            server_default="free",
        ),
    )
    op.add_column(
        "users",
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "plan_expires_at")
    op.drop_column("users", "plan")
    _user_plan_enum.drop(op.get_bind(), checkfirst=True)
