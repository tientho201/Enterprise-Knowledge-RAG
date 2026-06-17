from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.citation import Citation
    from app.models.document import Document


class Chunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "chunks"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qdrant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
    citations: Mapped[list[Citation]] = relationship(
        "Citation", back_populates="chunk", cascade="all, delete-orphan"
    )
