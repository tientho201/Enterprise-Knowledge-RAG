import json
from collections.abc import AsyncIterator

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph, get_retrieval_graph
from app.agents.state import AgentState
from app.models.message import MessageRole
from app.repositories.conversation_repo import ConversationRepository
from app.schemas.chat import (
    ChatResponse,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

    async def chat(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
        search_tool: bool | None = False,
        document_ids: list[str] | None = None,
        is_admin: bool = False,
    ) -> ChatResponse:
        # Get or create conversation
        if conversation_id:
            conv = await self.repo.get_by_id(conversation_id, user_id)
            if not conv:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
                )
        else:
            # Auto-title from first message
            title = message[:60] + ("..." if len(message) > 60 else "")
            conv = await self.repo.create(user_id=user_id, title=title)

        # Save user message
        await self.repo.add_message(conv.id, MessageRole.user, message)

        # Run agent graph.
        # Data isolation: retrieval chỉ chạm chunk của user (owner_id=user_id).
        # Admin → owner_id=None → không filter, truy hồi mọi chunk. Mirror document_service.
        owner_id = None if is_admin else user_id
        graph = get_agent_graph()
        initial_state: AgentState = {
            "query": message,
            "intent": "",
            "rewritten_query": None,
            "dense_results": [],
            "graph_results": [],
            "merged_results": [],
            "reranked_results": [],
            "citations": [],
            "final_answer": None,
            "confidence_score": 0.0,
            "retry_count": 0,
            "search_tool": search_tool,
            "document_ids": document_ids,
            "owner_id": owner_id,
        }
        final_state = await graph.ainvoke(initial_state)
        answer = final_state.get("final_answer") or "Không tìm thấy trong tài liệu."
        citations = final_state.get("citations", [])

        # Save assistant message
        import json

        content_to_save = answer
        if citations:
            content_to_save += f"\n<!--citations:{json.dumps(citations)}-->"
        assistant_msg = await self.repo.add_message(conv.id, MessageRole.assistant, content_to_save)

        # Save citations to DB (skip web citations which are not in local DB chunks table)
        if citations:
            from app.models.citation import Citation

            for cit in citations:
                chunk_id = cit.get("chunk_id", "")
                if chunk_id and not chunk_id.startswith("web_"):
                    citation_record = Citation(
                        chunk_id=chunk_id,
                        message_id=assistant_msg.id,
                    )
                    self.db.add(citation_record)

        # Save audit log to DB/Supabase
        from app.repositories.audit_log_repo import AuditLogRepository

        audit_repo = AuditLogRepository(self.db)
        await audit_repo.create(
            user_id=user_id,
            action=f'Chạy truy vấn RAG: "{message[:30] + "..." if len(message) > 30 else message}"',
            resource_type="query",
            resource_id=conv.id,
            extra_data={"details": f"Trích dẫn: {len(citations)}"},
        )

        return ChatResponse(
            conversation_id=conv.id,
            message=MessageResponse(
                id=assistant_msg.id,
                role=assistant_msg.role,
                content=answer,
                created_at=assistant_msg.created_at,
                citations=citations,
            ),
        )

    async def _persist_assistant(
        self, conv_id: str, user_id: str, message: str, answer: str, citations: list[dict]
    ):
        """Lưu message assistant + citations + audit log (dùng chung cho luồng stream)."""
        content_to_save = answer
        if citations:
            content_to_save += f"\n<!--citations:{json.dumps(citations)}-->"
        assistant_msg = await self.repo.add_message(conv_id, MessageRole.assistant, content_to_save)

        if citations:
            from app.models.citation import Citation

            for cit in citations:
                chunk_id = cit.get("chunk_id", "")
                if chunk_id and not chunk_id.startswith("web_"):
                    self.db.add(Citation(chunk_id=chunk_id, message_id=assistant_msg.id))

        from app.repositories.audit_log_repo import AuditLogRepository

        await AuditLogRepository(self.db).create(
            user_id=user_id,
            action=f'Chạy truy vấn RAG: "{message[:30] + "..." if len(message) > 30 else message}"',
            resource_type="query",
            resource_id=conv_id,
            extra_data={"details": f"Trích dẫn: {len(citations)}"},
        )
        return assistant_msg

    async def chat_stream(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
        search_tool: bool | None = False,
        document_ids: list[str] | None = None,
        is_admin: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming SSE: chạy retrieval rồi stream câu trả lời token-by-token.

        Sự kiện (mỗi dòng `data: <json>\\n\\n`):
          - meta  : {type, conversation_id}  — gửi sớm để FE gắn hội thoại
          - delta : {type, text}             — từng mẩu văn bản khi LLM sinh
          - done  : {type, message_id, citations, conversation_id}
          - error : {type, detail}
        """

        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            if conversation_id:
                conv = await self.repo.get_by_id(conversation_id, user_id)
                if not conv:
                    yield sse({"type": "error", "detail": "Conversation not found"})
                    return
            else:
                title = message[:60] + ("..." if len(message) > 60 else "")
                conv = await self.repo.create(user_id=user_id, title=title)

            await self.repo.add_message(conv.id, MessageRole.user, message)
            yield sse({"type": "meta", "conversation_id": conv.id})

            # Chạy pipeline retrieval (dừng trước generator)
            owner_id = None if is_admin else user_id
            initial_state: AgentState = {
                "query": message,
                "intent": "",
                "rewritten_query": None,
                "dense_results": [],
                "graph_results": [],
                "merged_results": [],
                "reranked_results": [],
                "citations": [],
                "final_answer": None,
                "confidence_score": 0.0,
                "retry_count": 0,
                "search_tool": search_tool,
                "document_ids": document_ids,
                "owner_id": owner_id,
            }
            state = await get_retrieval_graph().ainvoke(initial_state)

            from app.agents.generator import SYSTEM_PROMPT, _build_context
            from app.llm.factory import get_llm

            intent = state.get("intent", "rag")
            context, citations = _build_context(state)

            if intent == "rag" and context:
                # Happy path: stream câu trả lời RAG token-by-token
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {message}"},
                ]
                buffer = ""
                async for token in get_llm().stream_chat(messages=messages, temperature=0.1):
                    buffer += token
                    yield sse({"type": "delta", "text": token})
                answer = buffer.strip() or "Không tìm thấy trong tài liệu."
                if (
                    "Not found in documents." in answer
                    or "Không tìm thấy trong tài liệu." in answer
                ):
                    citations = []
            else:
                # chitchat / out_of_scope / không có context / web fallback → tái dùng generator
                from app.agents.generator import generator_node

                final_state = await generator_node(state)
                answer = final_state.get("final_answer") or "Không tìm thấy trong tài liệu."
                citations = final_state.get("citations", [])
                yield sse({"type": "delta", "text": answer})

            assistant_msg = await self._persist_assistant(
                conv.id, user_id, message, answer, citations
            )
            await self.db.commit()

            yield sse(
                {
                    "type": "done",
                    "conversation_id": conv.id,
                    "message_id": assistant_msg.id,
                    "citations": citations,
                }
            )
        except Exception as exc:  # noqa: BLE001 — báo lỗi qua stream thay vì để đứt kết nối
            import logging

            logging.getLogger(__name__).exception("chat_stream failed")
            await self.db.rollback()
            yield sse({"type": "error", "detail": str(exc)})

    async def get_history(self, user_id: str) -> list[ConversationResponse]:
        convs = await self.repo.list_by_user(user_id)
        return [
            ConversationResponse(
                id=c.id,
                title=c.title,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in convs
        ]

    async def get_conversation(self, user_id: str, conv_id: str) -> ConversationDetailResponse:
        conv = await self.repo.get_by_id(conv_id, user_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )

        import json
        import re

        messages = []
        for m in conv.messages:
            content = m.content
            citations = []
            if m.role == MessageRole.assistant:
                match = re.search(r"<!--citations:(.*?)-->", content, re.DOTALL)
                if match:
                    try:
                        citations = json.loads(match.group(1))
                    except Exception:
                        pass
                    content = re.sub(r"\s*<!--citations:.*?-->", "", content, flags=re.DOTALL)

            messages.append(
                MessageResponse(
                    id=m.id,
                    role=m.role,
                    content=content,
                    created_at=m.created_at,
                    citations=citations,
                )
            )
        return ConversationDetailResponse(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            messages=messages,
        )

    async def delete_conversation(self, user_id: str, conv_id: str) -> None:
        deleted = await self.repo.delete(conv_id, user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
