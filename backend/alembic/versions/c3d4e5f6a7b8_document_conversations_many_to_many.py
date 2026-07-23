"""documents <-> conversations many-to-many (per-document library sharing)

Thay cột đơn `documents.conversation_id` bằng bảng liên kết `document_conversations`
để 1 tài liệu có thể gắn vào nhiều hội thoại (và ngược lại). Backfill dữ liệu cũ
(nếu có) trước khi drop cột.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_conversations",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "conversation_id"),
    )
    op.create_index(
        op.f("ix_document_conversations_conversation_id"),
        "document_conversations",
        ["conversation_id"],
        unique=False,
    )

    # Backfill: mỗi doc.conversation_id cũ (nếu có) trở thành 1 dòng liên kết
    op.execute(
        """
        INSERT INTO document_conversations (document_id, conversation_id, created_at)
        SELECT id, conversation_id, now()
        FROM documents
        WHERE conversation_id IS NOT NULL
        """
    )

    op.drop_constraint(
        "fk_documents_conversation_id_conversations", "documents", type_="foreignkey"
    )
    op.drop_index(op.f("ix_documents_conversation_id"), table_name="documents")
    op.drop_column("documents", "conversation_id")


def downgrade() -> None:
    """Downgrade schema."""
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

    # Backfill tối đa 1 hội thoại/tài liệu (many-to-many -> one-to-many, lấy liên kết cũ nhất)
    op.execute(
        """
        UPDATE documents
        SET conversation_id = dc.conversation_id
        FROM (
            SELECT DISTINCT ON (document_id) document_id, conversation_id
            FROM document_conversations
            ORDER BY document_id, created_at ASC
        ) dc
        WHERE documents.id = dc.document_id
        """
    )

    op.drop_index(
        op.f("ix_document_conversations_conversation_id"), table_name="document_conversations"
    )
    op.drop_table("document_conversations")
