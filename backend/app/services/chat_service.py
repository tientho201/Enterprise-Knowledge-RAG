
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph
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
    ) -> ChatResponse:
        # Get or create conversation
        if conversation_id:
            conv = await self.repo.get_by_id(conversation_id, user_id)
            if not conv:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        else:
            # Auto-title from first message
            title = message[:60] + ("..." if len(message) > 60 else "")
            conv = await self.repo.create(user_id=user_id, title=title)

        # Save user message
        await self.repo.add_message(conv.id, MessageRole.user, message)

        # Run agent graph
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
            extra_data={"details": f"Trích dẫn: {len(citations)}"}
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        
        import re
        import json
        
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
