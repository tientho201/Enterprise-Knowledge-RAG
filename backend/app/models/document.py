from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class DocumentStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    indexed = "indexed"
    failed = "failed"
    archived = "archived"


class DocumentType(enum.StrEnum):
    pdf = "pdf"
    docx = "docx"
    txt = "txt"
    confluence = "confluence"
    slack = "slack"
    google_drive = "google_drive"


class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "documents"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Chủ sở hữu (người upload). Nullable: (a) document legacy tạo trước khi có cột này,
    # (b) SET NULL khi user bị xóa. Doc owner=NULL chỉ admin thấy/quản lý (data isolation).
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Hội thoại đã upload tài liệu này (per-conversation library). Nullable: upload từ trang
    # document-library (kho tổng) hoặc doc legacy trước migration này → không gắn hội thoại.
    # SET NULL khi hội thoại bị xóa để giữ lại tài liệu.
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Bật/tắt tài liệu: chỉ doc active mới hiện ở panel hội thoại và được RAG dùng.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), nullable=False, default=DocumentStatus.pending
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
