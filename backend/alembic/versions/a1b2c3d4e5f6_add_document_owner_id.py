"""add documents.owner_id (data isolation)

Thêm cột owner_id vào bảng documents để scope tài liệu theo người upload
(personal workspace). Nullable + SET NULL để giữ document khi user bị xóa và
để tương thích với document legacy tạo trước migration này (owner=NULL → admin-only).

Revision ID: a1b2c3d4e5f6
Revises: 76a3f5675651
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "76a3f5675651"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("owner_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_documents_owner_id"), "documents", ["owner_id"], unique=False)
    op.create_foreign_key(
        "fk_documents_owner_id_users",
        "documents",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_documents_owner_id_users", "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_owner_id"), table_name="documents")
    op.drop_column("documents", "owner_id")
