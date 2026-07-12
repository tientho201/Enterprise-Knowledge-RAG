---
name: rag-review
description: Dùng khi review, audit, hoặc sửa code trong RAG pipeline của backend (embedding, retrieval, reranker, chunking, LangGraph agent). Trigger khi user nhắc "review RAG", "kiểm tra retrieval", "audit embedding", hoặc khi sửa bất kỳ file nào trong backend/app/rag/, backend/app/ingestion/, backend/app/agents/. Dùng cùng với skill enterprise-knowledge-rag (đọc skill đó trước để có context tổng quan, skill này đi sâu vào checklist review).
---

# RAG pipeline review checklist

Review theo đúng thứ tự pipeline: ingestion → retrieval → rerank → generation.

## 1. Embedding (`backend/app/ingestion/embedder.py`)
- [ ] Phải dùng `OpenAIEmbedder` qua `get_embedder()` — model `text-embedding-3-small`
      (1536 dims). Không được import `sentence_transformers`, `FlagEmbedding`, hay `torch`.
- [ ] `embed()` gọi sync `OpenAI` client — nếu code này chạy trong async agent node (không phải
      Celery task), đây là known blocking issue, flag nhưng không cần block PR vì đã ghi nhận.

## 2. Chunking (`backend/app/ingestion/chunker.py`)
- [ ] `chunk_size=800`, `chunk_overlap=200` (đọc từ `settings`, không hardcode).
- [ ] Metadata mỗi chunk phải giữ được `document_id`, `chunk_index`.

## 3. Retrieval (`backend/app/rag/retriever.py`)
- [ ] Dense search: hiện đang dùng `httpx.Client` gọi REST API Qdrant thủ công thay vì
      `qdrant_client` SDK — đây là technical debt đã biết. Nếu PR sửa file này, ưu tiên migrate
      sang `qdrant_client.search()`.
- [ ] Graph search (Neo4j) PHẢI có try/except bao ngoài, trả về `{}` khi Neo4j lỗi — không được
      để exception propagate lên và làm crash toàn bộ retrieval (graceful degradation).
- [ ] Qdrant payload mỗi point bắt buộc có: `document_id`, `document_name`, `chunk_index`,
      `content`. Thiếu field nào thì `RetrievedChunk` sẽ có giá trị rỗng/sai ở downstream.
- [ ] Merge score: `DENSE_WEIGHT=0.7`, `GRAPH_WEIGHT=0.3` — đọc từ settings, không hardcode.

## 4. Reranker (`backend/app/rag/reranker.py`)
- [ ] Hiện tại là **stopgap** — chỉ sort theo hybrid score có sẵn, KHÔNG load model riêng.
      Không được thêm lại `sentence-transformers`/`CrossEncoder`/`torch` — dependency này đã bị
      xóa khỏi `pyproject.toml` để giảm Docker image ~2.5GB. Nếu cần rerank chất lượng cao hơn,
      đề xuất Cohere Rerank API (HTTP call, không cần tự host model) thay vì quay lại torch.
- [ ] Interface `rerank(query, chunks) -> list[RetrievedChunk]` phải giữ nguyên signature —
      `grader_node` gọi trực tiếp, đổi signature sẽ break agent graph.

## 5. LangGraph agent (`backend/app/agents/*.py`)
- [ ] `router_node`: 1 LLM call, `temperature=0.0`, output phải là đúng 1 trong 3 giá trị
      `rag | chitchat | out_of_scope` — có fallback về `rag` nếu LLM trả về giá trị khác.
- [ ] `grader_node`: hiện gọi LLM riêng cho từng chunk (N calls/request) — cực kỳ tốn chi phí.
      Nếu sửa file này, cân nhắc batch thành 1 call duy nhất chấm điểm tất cả chunks.
- [ ] `generator_node`: PHẢI chỉ trả lời từ context đã retrieve, câu trả lời phải có
      `[SOURCE: chunk_id]`. Nếu thêm web search fallback, bắt buộc có disclaimer rõ ràng đây là
      nguồn ngoài tài liệu nội bộ.
- [ ] Không được để `generator_node` gọi OpenAI trực tiếp — luôn qua `get_llm()`.

## Khi review xong

Nếu phát hiện thêm technical debt mới không có trong danh sách trên, cập nhật bảng "Technical
debt" trong skill `enterprise-knowledge-rag` (không lặp lại phân tích ở đây — skill đó là nguồn
chân lý duy nhất cho danh sách technical debt của cả project).
