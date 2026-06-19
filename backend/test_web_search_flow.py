import asyncio
from sqlalchemy import select, delete
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.services.chat_service import ChatService
from app.core.security import hash_password

async def test_flow():
    async with AsyncSessionLocal() as db:
        # 1. Get or create a test user
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users found. Creating a test user...")
            user = User(
                email="test_web_search@example.com",
                hashed_password=hash_password("password123"),
                full_name="Test Web Search User",
                is_active=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        user_id = user.id
        print(f"Using user_id: {user_id} (email: {user.email})")

        chat_service = ChatService(db)

        # Query that is guaranteed NOT to be in local RAG documents
        query = "Who was the winner of the UEFA Euro 2024 final and what was the score?"

        # --- Test 1: search_tool=False (Should return 'Không tìm thấy trong tài liệu.') ---
        print("\n=== Running Test 1: search_tool=False ===")
        res1 = await chat_service.chat(
            user_id=user_id,
            message=query,
            conversation_id=None,
            search_tool=False
        )
        print("Response 1:", repr(res1.message.content))
        print("Citations 1 count:", len(res1.message.citations))
        assert "Không tìm thấy trong tài liệu." in res1.message.content, "Test 1 failed!"

        # --- Test 2: search_tool=True (Should perform web search and return with disclaimer) ---
        print("\n=== Running Test 2: search_tool=True ===")
        res2 = await chat_service.chat(
            user_id=user_id,
            message=query,
            conversation_id=None,
            search_tool=True
        )
        print("Response 2:", repr(res2.message.content))
        print("Citations 2:")
        for cit in res2.message.citations:
            print(f"- {cit.chunk_id}: {cit.document_name} ({cit.source_link})")
        
        disclaimer = "Câu trả lời này được tổng hợp từ Internet, không nằm trong tài liệu nội bộ của công ty..."
        assert disclaimer in res2.message.content, "Disclaimer prefix missing!"
        assert len(res2.message.citations) > 0, "No web citations returned!"
        assert any(c.source_link for c in res2.message.citations), "No links in citations!"

        # --- Test 2.5: Verify citation serialization on get_conversation load ---
        print("\n=== Running Test 2.5: Loaded conversation citations ===")
        conv_detail = await chat_service.get_conversation(user_id, res2.conversation_id)
        loaded_assistant_msg = next(m for m in conv_detail.messages if m.role == "assistant")
        print("Loaded response content:", repr(loaded_assistant_msg.content))
        print("Loaded citations count:", len(loaded_assistant_msg.citations))
        assert disclaimer in loaded_assistant_msg.content, "Loaded response disclaimer missing!"
        assert len(loaded_assistant_msg.citations) > 0, "Loaded response has no citations!"
        assert any(c.source_link for c in loaded_assistant_msg.citations), "Loaded response citations have no links!"
        assert "<!--citations:" not in loaded_assistant_msg.content, "Hidden comments leaked into loaded content!"

        # --- Test 3: RAG query (Should run retriever successfully and return 'Không tìm thấy trong tài liệu.' because DB is empty, without crashing) ---
        print("\n=== Running Test 3: RAG query ===")
        rag_query = "What is the policy for annual leave?"
        res3 = await chat_service.chat(
            user_id=user_id,
            message=rag_query,
            conversation_id=None,
            search_tool=False
        )
        print("Response 3:", repr(res3.message.content))
        assert "Không tìm thấy trong tài liệu." in res3.message.content, "Test 3 failed!"

        print("\n=== All Tests Passed Successfully! ===")

        # Clean up conversation
        from app.models.conversation import Conversation
        await db.execute(delete(Conversation).where(Conversation.id.in_([res1.conversation_id, res2.conversation_id, res3.conversation_id])))
        await db.commit()

if __name__ == "__main__":
    asyncio.run(test_flow())
