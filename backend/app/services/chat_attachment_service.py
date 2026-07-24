"""Chat attachment service — ảnh gửi kèm chat (vision, ngữ cảnh tạm).

KHÔNG phải tài liệu thư viện: không ingest/chunk/embed, không hiện trong danh sách
tài liệu, không gắn được vào hội thoại như document_ids. Lưu S3 (prefix riêng
`chat-attachments/`, tách biệt bucket path khỏi document) + record `message_attachments`
(Supabase) cho phép hiển thị lại khi mở lại lịch sử hội thoại.
"""

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.message_attachment_repo import MessageAttachmentRepository
from app.schemas.chat import AttachmentUploadResponse
from app.storage.s3_client import get_presigned_url_async, upload_bytes_async

# Thoải mái cho screenshot/ảnh chụp thông thường. Base64 encode cho LLM cộng thêm
# ~33% kích thước — 8MB gốc vẫn nằm an toàn dưới giới hạn request của các provider
# OpenAI-compatible phổ biến (OpenAI, Groq, OpenRouter...).
MAX_IMAGE_SIZE = 8 * 1024 * 1024

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def sniff_image_content_type(data: bytes) -> str | None:
    """Nhận diện định dạng ảnh thật qua magic bytes ở đầu file — KHÔNG tin content-type
    hay đuôi file client khai báo (dễ giả mạo: đổi file .exe thành .png)."""
    for signature, content_type in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return content_type
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ChatAttachmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = MessageAttachmentRepository(db)

    async def upload(self, file: UploadFile, owner_id: str) -> AttachmentUploadResponse:
        file_bytes = await file.read()

        if len(file_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Image exceeds {MAX_IMAGE_SIZE // (1024 * 1024)} MB limit",
            )

        content_type = sniff_image_content_type(file_bytes)
        if content_type is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported or unrecognized image format. Allowed: png, jpeg, webp",
            )

        object_name = f"chat-attachments/{owner_id}/{uuid.uuid4()}"
        await upload_bytes_async(object_name, file_bytes, content_type=content_type)

        attachment = await self.repo.create(
            owner_id=owner_id,
            storage_path=object_name,
            content_type=content_type,
            file_size=len(file_bytes),
        )

        url = await get_presigned_url_async(object_name, expires_seconds=3600)
        return AttachmentUploadResponse(id=attachment.id, url=url, content_type=content_type)
