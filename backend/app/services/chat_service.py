import base64
import json
from collections.abc import AsyncIterator
from typing import Literal

import openai
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph, get_retrieval_graph
from app.agents.state import AgentState
from app.analytics.tracker import tracker
from app.models.message import MessageRole
from app.models.message_attachment import MessageAttachment
from app.rag.response_cache import get_cached_answer, set_cached_answer
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_attachment_repo import MessageAttachmentRepository
from app.schemas.chat import (
    AttachmentSchema,
    ChatResponse,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)
from app.storage.s3_client import download_file_async, get_presigned_url_async


def _friendly_llm_error(
    exc: Exception, model: str | None, api_key: str | None, has_image: bool = False
) -> str:
    """Diễn giải lỗi gọi LLM dễ hiểu hơn. BYOM (có api_key riêng) hay gặp: sai Model ID,
    API Key, hoặc Base URL không phải endpoint OpenAI-compatible (vd Anthropic Claude).
    Khi request có ảnh (vision), model tùy chỉnh cũng có thể không hỗ trợ vision dù
    Model ID/API Key/Base URL đều đúng — thông báo riêng để không gây nhầm lẫn."""
    if api_key and isinstance(exc, openai.APIError):
        hint = f" (model: {model})" if model else ""
        if has_image:
            return (
                f"Không thể gọi model tùy chỉnh{hint} với ảnh đính kèm. Model này có thể "
                f"không hỗ trợ vision (đọc ảnh) — thử model khác (vd gpt-4o-mini, gpt-4o) "
                f"hoặc bỏ ảnh khỏi tin nhắn. Chi tiết lỗi: {exc}"
            )
        return (
            f"Không thể gọi model tùy chỉnh{hint}. Vui lòng kiểm tra lại Model ID, API Key "
            f"và Base URL trong panel Cấu hình — lưu ý Base URL phải là endpoint "
            f"OpenAI-compatible (OpenAI, Gemini, Groq, OpenRouter, vLLM tự host...). "
            f"Chi tiết lỗi: {exc}"
        )
    return str(exc)


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)
        self.attachment_repo = MessageAttachmentRepository(db)

    async def _load_images(
        self, image_ids: list[str] | None, user_id: str
    ) -> tuple[list[str], list[MessageAttachment]]:
        """Tải ảnh đã upload (POST /chat/images) → data URI base64 cho LLM.

        Data isolation: chỉ chấp nhận attachment thuộc chính user_id (mirror
        DocumentService._get_owned_or_404) — id lạ/không sở hữu → 404, không lộ tồn tại.
        """
        if not image_ids:
            return [], []
        attachments = await self.attachment_repo.get_owned(image_ids, user_id)
        if len(attachments) != len(set(image_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
            )
        data_urls = []
        for att in attachments:
            file_bytes = await download_file_async(att.storage_path)
            b64 = base64.b64encode(file_bytes).decode("ascii")
            data_urls.append(f"data:{att.content_type};base64,{b64}")
        return data_urls, attachments

    async def chat(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
        search_tool: bool | None = False,
        document_ids: list[str] | None = None,
        is_admin: bool = False,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        image_ids: list[str] | None = None,
        search_mode: Literal["hybrid", "vector", "keyword", "advanced"] | None = None,
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

        # Ảnh gửi kèm (vision) — tải trước khi lưu message để 404 sớm nếu id không hợp lệ
        image_data_urls, attachments = await self._load_images(image_ids, user_id)

        # Save user message, rồi gắn ảnh đã upload (message_id=NULL) vào message vừa tạo
        user_msg = await self.repo.add_message(conv.id, MessageRole.user, message)
        if attachments:
            await self.attachment_repo.attach_to_message(
                [a.id for a in attachments], user_msg.id, user_id
            )

        # Run agent graph.
        # Data isolation: retrieval chỉ chạm chunk của user (owner_id=user_id).
        # Admin → owner_id=None → không filter, truy hồi mọi chunk. Mirror document_service.
        owner_id = None if is_admin else user_id
        graph = get_agent_graph()

        # Response Cache exact-match (Task 5.2, xem app/rag/response_cache.py) — chỉ
        # áp dụng case "đơn giản" (không web search/ảnh/custom prompt/BYOM/advanced
        # mode), vì các case đó có biến số không nằm trong cache key, cache sẽ trả
        # sai nếu tái dùng. owner_id LUÔN có trong key (bên trong response_cache) —
        # bắt buộc để không lộ câu trả lời chéo user.
        cache_eligible = (
            not search_tool
            and not image_data_urls
            and not system_prompt
            and not model
            and not api_key
            and not base_url
            and (search_mode or "hybrid") != "advanced"
        )
        cached = (
            await get_cached_answer(message, owner_id, document_ids) if cache_eligible else None
        )

        final_state: dict
        if cached is not None:
            final_state = {
                "final_answer": cached.get("final_answer"),
                "citations": cached.get("citations", []),
                "intent": cached.get("intent", "rag"),
                "confidence_score": cached.get("confidence_score", 0.0),
                "reranked_results": [],
                "citation_graph_path": [],
                "citation_graph_nodes": [],
                "suggested_documents": [],
            }
            async with tracker.measure(message) as metrics:
                metrics.intent = final_state["intent"]
                metrics.confidence_score = final_state["confidence_score"]
                metrics.had_citations = bool(final_state["citations"])
                metrics.metadata["cache_hit"] = True
        else:
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
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "system_prompt": system_prompt,
                "model": model,
                "api_key": api_key,
                "base_url": base_url,
                "image_data_urls": image_data_urls,
                "search_mode": search_mode,
                "citation_graph_path": [],
                "citation_graph_nodes": [],
                "suggested_documents": [],
                "dlp_flag": False,
                "dlp_reason": None,
            }
            # Observability (Task 3.1, xem app/analytics/tracker.py) — bọc toàn bộ
            # graph run, log QUERY_METRICS (latency/intent/confidence/chunks) sau
            # mỗi request. measure() tự bắt exception (kể cả HTTPException raise
            # bên trong) để ghi metrics.error trước khi re-raise — không nuốt lỗi,
            # không đổi hành vi cũ.
            async with tracker.measure(message) as metrics:
                try:
                    final_state = await graph.ainvoke(initial_state)
                except openai.APIError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=_friendly_llm_error(
                            exc, model, api_key, has_image=bool(image_data_urls)
                        ),
                    ) from exc
                metrics.intent = final_state.get("intent") or ""
                metrics.confidence_score = final_state.get("confidence_score") or 0.0
                metrics.retrieved_chunks = len(final_state.get("reranked_results") or [])
                metrics.had_citations = bool(final_state.get("citations"))

            if cache_eligible:
                await set_cached_answer(
                    message,
                    owner_id,
                    document_ids,
                    {
                        "final_answer": final_state.get("final_answer"),
                        "citations": final_state.get("citations", []),
                        "intent": final_state.get("intent"),
                        "confidence_score": final_state.get("confidence_score"),
                    },
                )

        answer = final_state.get("final_answer") or "Không tìm thấy trong tài liệu."
        citations = final_state.get("citations", [])
        citation_graph_path = final_state.get("citation_graph_path", [])
        citation_graph_nodes = final_state.get("citation_graph_nodes", [])
        suggested_documents = final_state.get("suggested_documents", [])

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

        # Save audit log to DB/Supabase — kèm cờ DLP (agents/dlp.py) nếu generator_node
        # phát hiện dấu hiệu bulk extraction, để admin có thể tra soát qua audit log.
        from app.repositories.audit_log_repo import AuditLogRepository

        extra_data: dict = {"details": f"Trích dẫn: {len(citations)}"}
        if final_state.get("dlp_flag"):
            extra_data["dlp_flag"] = True
            extra_data["dlp_reason"] = final_state.get("dlp_reason")

        audit_repo = AuditLogRepository(self.db)
        await audit_repo.create(
            user_id=user_id,
            action=f'Chạy truy vấn RAG: "{message[:30] + "..." if len(message) > 30 else message}"',
            resource_type="query",
            resource_id=conv.id,
            extra_data=extra_data,
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
            citation_graph_path=citation_graph_path,
            citation_graph_nodes=citation_graph_nodes,
            suggested_documents=suggested_documents,
        )

    async def _persist_assistant(
        self,
        conv_id: str,
        user_id: str,
        message: str,
        answer: str,
        citations: list[dict],
        dlp_flag: bool = False,
        dlp_reason: str | None = None,
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

        extra_data: dict = {"details": f"Trích dẫn: {len(citations)}"}
        if dlp_flag:
            extra_data["dlp_flag"] = True
            extra_data["dlp_reason"] = dlp_reason

        await AuditLogRepository(self.db).create(
            user_id=user_id,
            action=f'Chạy truy vấn RAG: "{message[:30] + "..." if len(message) > 30 else message}"',
            resource_type="query",
            resource_id=conv_id,
            extra_data=extra_data,
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
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        image_ids: list[str] | None = None,
        search_mode: Literal["hybrid", "vector", "keyword", "advanced"] | None = None,
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

        has_image = False
        try:
            if conversation_id:
                conv = await self.repo.get_by_id(conversation_id, user_id)
                if not conv:
                    yield sse({"type": "error", "detail": "Conversation not found"})
                    return
            else:
                title = message[:60] + ("..." if len(message) > 60 else "")
                conv = await self.repo.create(user_id=user_id, title=title)

            image_data_urls, attachments = await self._load_images(image_ids, user_id)
            has_image = bool(image_data_urls)

            user_msg = await self.repo.add_message(conv.id, MessageRole.user, message)
            if attachments:
                await self.attachment_repo.attach_to_message(
                    [a.id for a in attachments], user_msg.id, user_id
                )
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
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "system_prompt": system_prompt,
                "model": model,
                "api_key": api_key,
                "base_url": base_url,
                "image_data_urls": image_data_urls,
                "search_mode": search_mode,
                "citation_graph_path": [],
                "citation_graph_nodes": [],
                "suggested_documents": [],
                "dlp_flag": False,
                "dlp_reason": None,
            }
            # Observability (Task 3.1) — bọc retrieval+generation, mirror chat() không-stream.
            # async with quanh generator OK dù hàm này có yield bên trong (async generator
            # method) — measure() vẫn tự bắt exception + log latency khi thoát block.
            async with tracker.measure(message) as metrics:
                state = await get_retrieval_graph().ainvoke(initial_state)

                from app.agents.dlp import check_bulk_extraction
                from app.agents.generator import SYSTEM_PROMPT, _build_context
                from app.agents.prompt_defense import wrap_untrusted
                from app.llm.factory import get_llm_for_request

                intent = state.get("intent", "rag")
                context, citations = _build_context(state)
                dlp_flag = False
                dlp_reason: str | None = None
                metrics.intent = intent
                metrics.confidence_score = state.get("confidence_score") or 0.0
                metrics.retrieved_chunks = len(state.get("reranked_results") or [])

                # Có ảnh → luôn đi qua generator_node (nhánh else) để dùng chung logic dựng
                # content đa phương thức (text + image_url) thay vì lặp lại ở đây; tránh
                # phải viết + bảo trì multimodal streaming riêng cho nhánh fast-path.
                if intent == "rag" and context and not has_image:
                    # Happy path: stream câu trả lời RAG token-by-token. Lớp 1 (SYSTEM_PROMPT,
                    # bất biến) + Lớp 2 (system_prompt tùy biến, CỘNG THÊM) — mirror đúng
                    # generator_node, xem app/agents/prompt_defense.py.
                    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"{wrap_untrusted('context', context)}\n\n"
                                f"{wrap_untrusted('user_query', message)}"
                            ),
                        }
                    )
                    llm = get_llm_for_request(model=model, api_key=api_key, base_url=base_url)
                    buffer = ""
                    async for token in llm.stream_chat(messages=messages, temperature=0.1):
                        buffer += token
                        yield sse({"type": "delta", "text": token})
                    answer = buffer.strip() or "Không tìm thấy trong tài liệu."
                    if (
                        "Not found in documents." in answer
                        or "Không tìm thấy trong tài liệu." in answer
                    ):
                        citations = []
                    else:
                        # DLP tối thiểu (xem agents/dlp.py) — mirror generator_node, chỉ log.
                        dlp_result = check_bulk_extraction(
                            answer, state.get("reranked_results", [])
                        )
                        dlp_flag, dlp_reason = dlp_result.flagged, dlp_result.reason
                        if dlp_flag:
                            import logging

                            logging.getLogger(__name__).warning(
                                "DLP: possible bulk extraction detected (owner_id=%s): %s",
                                owner_id,
                                dlp_reason,
                            )
                else:
                    # chitchat / out_of_scope / không có context / web fallback / có ảnh
                    # → tái dùng generator (multimodal-aware)
                    from app.agents.generator import generator_node

                    final_state = await generator_node(state)
                    answer = final_state.get("final_answer") or "Không tìm thấy trong tài liệu."
                    citations = final_state.get("citations", [])
                    dlp_flag = final_state.get("dlp_flag", False)
                    dlp_reason = final_state.get("dlp_reason")
                    yield sse({"type": "delta", "text": answer})

                metrics.had_citations = bool(citations)

            assistant_msg = await self._persist_assistant(
                conv.id, user_id, message, answer, citations, dlp_flag, dlp_reason
            )
            await self.db.commit()

            yield sse(
                {
                    "type": "done",
                    "conversation_id": conv.id,
                    "message_id": assistant_msg.id,
                    "citations": citations,
                    # Additive — rỗng ([]) trừ khi search_mode="advanced". FE cũ bỏ qua
                    # field lạ, không vỡ tương thích ngược (xem schemas/chat.py::ChatResponse).
                    "citation_graph_path": state.get("citation_graph_path", []),
                    "citation_graph_nodes": state.get("citation_graph_nodes", []),
                    "suggested_documents": state.get("suggested_documents", []),
                }
            )
        except Exception as exc:  # noqa: BLE001 — báo lỗi qua stream thay vì để đứt kết nối
            import logging

            logging.getLogger(__name__).exception("chat_stream failed")
            await self.db.rollback()
            yield sse(
                {
                    "type": "error",
                    "detail": _friendly_llm_error(exc, model, api_key, has_image=has_image),
                }
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

            attachments = []
            for att in m.attachments:
                url = await get_presigned_url_async(att.storage_path, expires_seconds=3600)
                attachments.append(
                    AttachmentSchema(id=att.id, url=url, content_type=att.content_type)
                )

            messages.append(
                MessageResponse(
                    id=m.id,
                    role=m.role,
                    content=content,
                    created_at=m.created_at,
                    citations=citations,
                    attachments=attachments,
                )
            )
        return ConversationDetailResponse(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            messages=messages,
        )

    async def delete_conversation(self, user_id: str, conv_id: str) -> None:
        # Thu thập storage_path ảnh TRƯỚC khi xóa (record DB xóa cascade qua
        # conversation → message → message_attachments ngay khi repo.delete() chạy).
        attachment_paths = await self.attachment_repo.list_storage_paths_by_conversation(conv_id)

        deleted = await self.repo.delete(conv_id, user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )

        # Dọn S3 nền qua Celery — record DB đã xóa (transaction ORM ở trên), S3 xóa
        # không nằm trong transaction đó nên chạy tách rời, retry-safe, idempotent.
        if attachment_paths:
            from app.workers.tasks.ingestion import delete_chat_attachments

            delete_chat_attachments.delay(attachment_paths)
