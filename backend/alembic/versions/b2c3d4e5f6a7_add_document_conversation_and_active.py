"""add documents.conversation_id + is_active (per-conversation library)

Thêm 2 cột vào bảng documents:
  - conversation_id: hội thoại đã upload tài liệu (per-conversation library).
    Nullable + SET NULL để giữ tài liệu khi hội thoại bị xóa và tương thích doc legacy.
  - is_active: bật/tắt tài liệu (default TRUE) — chỉ doc active mới hiện ở panel hội
    thoại và được RAG dùng. server_default='true' để doc legacy mặc định active.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("conversation_id", sa.String(length=36), nullable=True))
    op.create_index(
        op.f("ix_documents_conversation_id"), "documents", ["conversation_id"], unique=False
    )
    op.create_foreign_key(
        "fk_documents_conversation_id_conversations",
        "documents",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "documents",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documents", "is_active")
    op.drop_constraint(
        "fk_documents_conversation_id_conversations", "documents", type_="foreignkey"
    )
    op.drop_index(op.f("ix_documents_conversation_id"), table_name="documents")
    op.drop_column("documents", "conversation_id")
