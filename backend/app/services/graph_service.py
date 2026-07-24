"""
Graph explorer service — orchestration cho "Giao diện Nâng cao".

Trách nhiệm:
  • Xác thực hội thoại thuộc user (data isolation) + lấy document_ids gắn vào hội thoại
    từ Postgres (owner-scoped).
  • Quy ước owner_id: admin → None (không filter, thấy tất cả); user thường → user.id
    (mirror ChatService / HybridRetriever).
  • Gọi tầng Cypher (rag/graph_queries.py) qua `asyncio.to_thread` — Neo4j driver là
    sync, KHÔNG được gọi trực tiếp trong async route (block event loop).

Client chỉ gửi conversation_id / document_id / query — KHÔNG bao giờ gửi Cypher thô.
"""

import asyncio

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.rag import graph_queries
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.document_repo import DocumentRepository


class GraphService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversations = ConversationRepository(db)
        self.documents = DocumentRepository(db)

    def _owner_id(self, user: User) -> str | None:
        """Admin → None (không filter). User thường → id của chính họ."""
        return None if user.role == UserRole.admin else user.id

    async def _scoped_document_ids(self, user: User, conversation_id: str) -> list[str]:
        """Verify hội thoại thuộc user + trả document_ids (owner-scoped) gắn vào nó.

        Trả 404 nếu hội thoại không tồn tại hoặc không thuộc user (non-admin) — không
        tiết lộ sự tồn tại của hội thoại người khác.
        """
        owner_id = self._owner_id(user)
        conv_owner = await self.conversations.get_owner_id(conversation_id)
        if conv_owner is None or (owner_id is not None and conv_owner != owner_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy hội thoại."
            )
        return await self.documents.list_document_ids_for_conversation(conversation_id, owner_id)

    async def overview(self, user: User, conversation_id: str) -> dict:
        """Endpoint A — cấu trúc cấp tài liệu cho các doc gắn vào hội thoại."""
        owner_id = self._owner_id(user)
        document_ids = await self._scoped_document_ids(user, conversation_id)
        return await asyncio.to_thread(graph_queries.fetch_overview, document_ids, owner_id)

    async def expand(self, user: User, conversation_id: str, document_id: str) -> dict:
        """Endpoint A — bung 1 tài liệu → chunk của nó (trần GRAPH_MAX_NODES).

        Chặn bung tài liệu KHÔNG thuộc phạm vi hội thoại/owner của user → 404, tránh
        dùng conversation hợp lệ làm bàn đạp đọc chunk của tài liệu người khác.
        """
        owner_id = self._owner_id(user)
        document_ids = await self._scoped_document_ids(user, conversation_id)
        if document_id not in document_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tài liệu không thuộc hội thoại này.",
            )
        return await asyncio.to_thread(
            graph_queries.fetch_expand, document_id, owner_id, settings.GRAPH_MAX_NODES
        )

    async def highlight(self, user: User, conversation_id: str, query: str) -> dict:
        """Endpoint B — ID node trúng truy vấn (dense search scoped theo hội thoại+owner).

        CHỈ trả node_ids; client đổi trạng thái visual của graph có sẵn (không nạp lại).
        """
        owner_id = self._owner_id(user)
        document_ids = await self._scoped_document_ids(user, conversation_id)
        return await asyncio.to_thread(
            graph_queries.fetch_highlight_ids,
            document_ids,
            owner_id,
            query,
            settings.DENSE_TOP_K,
        )
