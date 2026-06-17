from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.message import Message


class Citation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "citations"

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunk: Mapped[Chunk] = relationship("Chunk", back_populates="citations")
    message: Mapped[Message | None] = relationship("Message", back_populates="citations")
