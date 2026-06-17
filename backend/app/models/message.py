from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.citation import Citation
    from app.models.conversation import Conversation


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )
    citations: Mapped[list[Citation]] = relationship(
        "Citation", back_populates="message", cascade="all, delete-orphan"
    )
