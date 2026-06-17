
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

    async def chat(self, user_id: str, message: str, conversation_id: str | None = None) -> ChatResponse:
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
            "sparse_results": [],
            "merged_results": [],
            "reranked_results": [],
            "citations": [],
            "final_answer": None,
            "confidence_score": 0.0,
            "retry_count": 0,
        }
        final_state = await graph.ainvoke(initial_state)
        answer = final_state.get("final_answer") or "I'm sorry, I couldn't generate a response."
        citations = final_state.get("citations", [])

        # Save assistant message
        assistant_msg = await self.repo.add_message(conv.id, MessageRole.assistant, answer)

        # Save citations to DB
        if citations:
            from app.models.citation import Citation
            for cit in citations:
                citation_record = Citation(
                    chunk_id=cit["chunk_id"],
                    message_id=assistant_msg.id,
                )
                self.db.add(citation_record)

        return ChatResponse(
            conversation_id=conv.id,
            message=MessageResponse(
                id=assistant_msg.id,
                role=assistant_msg.role,
                content=assistant_msg.content,
                created_at=assistant_msg.created_at,
                citations=[],
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
        messages = [
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in conv.messages
        ]
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
