from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.message import Message


class MessageAttachment(Base, UUIDMixin, TimestampMixin):
    """Ảnh gửi kèm 1 tin nhắn chat (vision, ngữ cảnh tạm — KHÔNG phải tài liệu thư viện,
    không ingest/chunk/embed). Tách biệt hoàn toàn khỏi bảng `documents`.

    Vòng đời: upload trước (message_id=NULL, chỉ owner_id) rồi mới được gắn vào
    message_id khi tin nhắn user được lưu (xem chat_service). Ảnh chưa từng gắn vào
    message nào (user upload rồi bỏ ngang) là orphan vô hại — dọn dẹp định kỳ để sau,
    chưa cần xử lý ở phase này.
    """

    __tablename__ = "message_attachments"

    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Chủ sở hữu (người upload) — bắt buộc để kiểm tra quyền sở hữu TRƯỚC khi message tồn tại.
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    message: Mapped[Message | None] = relationship("Message", back_populates="attachments")
