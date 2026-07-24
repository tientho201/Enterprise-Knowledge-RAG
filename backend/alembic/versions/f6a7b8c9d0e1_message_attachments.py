"""message attachments (ảnh gửi kèm chat, vision-only, không phải tài liệu thư viện)

Bảng `message_attachments`: ảnh đính kèm 1 tin nhắn chat. Tách biệt hoàn toàn khỏi
`documents` — không ingest/chunk/embed, không hiện trong thư viện tài liệu. Upload
xảy ra TRƯỚC khi message tồn tại nên message_id nullable; owner_id bắt buộc để kiểm
tra quyền sở hữu ngay từ lúc upload. ON DELETE CASCADE ở cả 2 tầng (message, user)
để xóa hội thoại/tin nhắn tự dọn theo (S3 cleanup xử lý riêng qua Celery — xem
services/chat_service.py).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "message_attachments",
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_message_attachments_message_id"),
        "message_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_attachments_owner_id"),
        "message_attachments",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_message_attachments_owner_id"), table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_message_id"), table_name="message_attachments")
    op.drop_table("message_attachments")
