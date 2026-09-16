---
name: rag-review
description: Dùng khi review, audit, hoặc sửa code trong RAG pipeline ONLINE của backend (query rewrite/HyDE, retrieval, fusion, reranker, generation, observability/eval). Trigger khi user nhắc "review RAG", "kiểm tra retrieval", "audit embedding", "RRF", "cross-encoder rerank", "Langfuse", "RAGAS", hoặc khi sửa bất kỳ file nào trong backend/app/rag/, backend/app/ingestion/, backend/app/agents/. Dùng cùng với skill enterprise-knowledge-rag (context tổng quan) và skill ingestion (phần OFFLINE — pipeline nạp tài liệu, đứng trước bước Retrieval của skill này).
---

# RAG pipeline (ONLINE) review checklist

Đây là nửa ONLINE (query time) của toàn bộ RAG pipeline — nửa OFFLINE (ingestion, chạy
lúc nạp tài liệu) xem skill `ingestion`. Pipeline ONLINE mục tiêu (target architecture):

```
                    ONLINE
┌──────────────────────────────────────────────┐
│ User Query                                   │
│      ↓                                       │
│ Query Rewrite / Expand / HyDE                │
│      ↓                                       │
│ ┌──────────────┬────────────────┐            │
│ │ Vector Search│   BM25 Search  │            │
│ └──────┬───────┴───────┬────────┘            │
│        └───────┬───────┘                     │
│                ↓                             │
│          RRF / Fusion                        │
│                ↓                             │
│             Top 20–50                        │
│                ↓                             │
│        Cross-Encoder Reranker                │
│                ↓                             │
│              Top 3–5                         │
│                ↓                             │
│         LLM + Context                        │
│                ↓                             │
│        Answer + Citations                    │
└──────────────────────────────────────────────┘
          │                         │
          ▼                         ▼
      Langfuse                    RAGAS
     Production                 Evaluation
      Tracing                    Quality
```

Review theo đúng thứ tự pipeline này. Mỗi mục dưới đây map 1 khối trong diagram sang code
thật, và ghi rõ gap nếu khối đó chưa implement đúng như mục tiêu — diagram này là kiến
trúc MỤC TIÊU để đối chiếu, không phải roadmap đã chốt phải làm; nếu định triển khai 1
gap lớn (RRF, BM25 thật, HyDE, Langfuse, RAGAS...), hỏi lại trước khi làm vì đều là thay
đổi kiến trúc, không phải fix nhỏ.

## 0. Embedding query + Chunking (OFFLINE, không lặp lại ở đây)

`embedder.py` (dense embedding, dùng lại nguyên `get_embedder()` để embed câu query lúc
retrieval) và `chunker.py` đều thuộc nửa OFFLINE — checklist chi tiết + gap so với
"Semantic Chunking + Metadata" trong diagram mục tiêu nằm ở skill `ingestion` (mục 2–5),
không lặp lại ở đây để tránh 2 nguồn chân lý lệch nhau. Chỉ cần nhớ: `embed_query()` phải
dùng đúng model đã dùng lúc ingest — đổi `EMBEDDING_MODEL` mà không reindex thì dense
search sẽ so sánh 2 không gian vector khác nhau (silent failure, không crash nhưng kết
quả rác).

## 1. Query Rewrite / Expand / HyDE (`backend/app/agents/rewriter.py`)
- [ ] Code thật: **chỉ có "Rewrite"**, chạy trong 1 nhánh cụ thể — `rewriter_node` chỉ được
      gọi khi `grader_node` chấm `confidence_score < 0.3` VÀ còn retry (`retry_count <
      MAX_RETRIES=2`), KHÔNG chạy mặc định cho mọi query như diagram mục tiêu gợi ý.
- [ ] **"Expand" và "HyDE" chưa tồn tại** — gap. Query expansion (sinh nhiều biến thể
      query rồi retrieve từng biến thể) và HyDE (sinh câu trả lời giả định bằng LLM rồi
      embed câu đó thay vì embed query gốc) là 2 kỹ thuật khác nhau, nếu thêm cần quyết
      định chạy trước retrieval đầu tiên (không phải chỉ khi grader reject) — đổi vị trí
      trong `agents/graph.py`, không chỉ sửa `rewriter.py`.
- [ ] `rewriter_node` là 1 LLM call riêng — nếu thêm HyDE là thêm 1 LLM call nữa trước
      retrieval đầu tiên, cộng dồn latency; cân nhắc có đáng đánh đổi cho query enterprise
      thường đã khá cụ thể hay không trước khi triển khai.

## 2. Retrieval — Vector Search + "Sparse" Search + Fusion (`backend/app/rag/retriever.py`)
- [ ] Code thật là `HybridRetriever`: **Vector Search = Qdrant dense**, nhưng nhánh thứ 2
      **KHÔNG phải BM25 Search** — là Neo4j graph traversal (`NEXT_CHUNK`/`REFERENCES`,
      xem docstring đầu file). Đây là quyết định kiến trúc đã chốt (xem skill
      `enterprise-knowledge-rag`) — không tự thêm BM25/`rank_bm25` để "khớp đúng" diagram
      mà không hỏi lại.
- [ ] **Fusion hiện là weighted sum, không phải RRF** — `score = dense_weight * norm_dense
      + graph_weight * graph_score` (`DENSE_WEIGHT=0.7`, `GRAPH_WEIGHT=0.3`, đọc từ
      settings, không hardcode). RRF (Reciprocal Rank Fusion) dùng rank thứ tự thay vì
      điểm số thô, ít nhạy với việc 2 nhánh có scale điểm khác nhau (cosine similarity vs
      graph connection-count normalize) hơn weighted sum hiện tại — nếu đổi sang RRF, đây
      là thay đổi công thức merge, cần benchmark lại trước khi merge PR, không đổi "vì
      diagram nói vậy".
- [ ] Dense search: hiện đang dùng `httpx.Client` gọi REST API Qdrant thủ công thay vì
      `qdrant_client` SDK — technical debt đã biết. Nếu PR sửa file này, ưu tiên migrate
      sang `qdrant_client.search()`.
- [ ] Graph search (Neo4j) PHẢI có try/except bao ngoài, trả về `{}` khi Neo4j lỗi — không
      được để exception propagate lên và làm crash toàn bộ retrieval (graceful degradation).
- [ ] Qdrant payload mỗi point bắt buộc có: `document_id`, `document_name`, `chunk_index`,
      `content`. Thiếu field nào thì `RetrievedChunk` sẽ có giá trị rỗng/sai ở downstream.
- [ ] `DENSE_TOP_K`/`GRAPH_TOP_K` (`app/core/config.py`) là nơi tương ứng với "Top 20–50"
      trong diagram — kiểm tra 2 giá trị này còn hợp lý nếu đổi `RERANK_TOP_K` ở bước sau.

## 3. Reranker (`backend/app/rag/reranker.py`)
- [ ] Hiện tại là **stopgap** — `HybridScoreReranker` chỉ sort lại theo hybrid score đã
      tính ở bước 2 và cắt về `RERANK_TOP_K` (tương ứng "Top 3–5" trong diagram), KHÔNG
      phải Cross-Encoder thật. Không được thêm lại `sentence-transformers`/`CrossEncoder`/
      `torch` — dependency này đã bị xóa khỏi `pyproject.toml` để giảm Docker image ~2.5GB.
      Nếu cần rerank chất lượng cao hơn (đúng nghĩa "Cross-Encoder Reranker" của diagram),
      đề xuất Cohere Rerank API (HTTP call, không cần tự host model) thay vì quay lại torch.
- [ ] Interface `rerank(query, chunks) -> list[RetrievedChunk]` phải giữ nguyên signature —
      `grader_node` gọi trực tiếp, đổi signature sẽ break agent graph.

## 4. LangGraph agent — LLM + Context → Answer + Citations (`backend/app/agents/*.py`)
- [ ] `router_node`: 1 LLM call, `temperature=0.0`, output phải là đúng 1 trong 3 giá trị
      `rag | chitchat | out_of_scope` — có fallback về `rag` nếu LLM trả về giá trị khác.
- [ ] `grader_node`: đã batch chấm điểm TẤT CẢ chunk trong 1 lần gọi LLM duy nhất
      (`BATCH_GRADE_PROMPT`, parse số chunk relevant qua `re.findall`) — KHÔNG còn N calls/
      request như thiết kế cũ. Nếu sửa file này, giữ nguyên tinh thần batch, chỉ cẩn thận
      khi đổi `max_tokens=30`/prompt nếu tăng số chunk (`RERANK_TOP_K`) vượt quá khả năng
      model liệt kê hết số trong 1 response ngắn.
- [ ] `generator_node`: PHẢI chỉ trả lời từ context đã retrieve, câu trả lời phải có
      `[SOURCE: chunk_id]`. Nếu thêm web search fallback, bắt buộc có disclaimer rõ ràng đây là
      nguồn ngoài tài liệu nội bộ.
- [ ] Không được để `generator_node` gọi OpenAI trực tiếp — luôn qua `get_llm()`.
- [ ] Citations hiện có `page_number`/`section_title`/`source_link` luôn `None` (xem
      `_build_context()` trong `generator.py`) — chưa nối với metadata pháp lý
      (Điều/Khoản/Điểm) mà `structural_parser.py` đã parse được ở bước ingest. Xem gap ở
      skill `ingestion` mục 4 (Metadata Enrichment) nếu muốn citation có `section_title`
      thật thay vì `None`.

## 5. Observability — Langfuse Production Tracing
**`AnalyticsTracker` đã wire (2026-09-16), KHÔNG còn dead code — nhưng vẫn CHƯA có
LLM tracing backend (Langfuse/LangSmith) — 2 việc khác nhau, gap còn lại là việc
thứ 2.**
- `app/analytics/tracker.py::AnalyticsTracker.measure()` đã được gọi ở
  `chat_service.py::chat()`/`chat_stream()` — bọc TOÀN BỘ graph run (chưa tách riêng
  từng node), log 1 dòng `QUERY_METRICS` (latency/intent/confidence/chunks/error)
  mỗi request qua `logging` chuẩn. Nếu cần đo latency riêng từng node
  (`router_node`/`retriever_node`/`grader_node`/`rewriter_node`/`generator_node` —
  `grader_node` N LLM calls là điểm nghi tốn chi phí nhất), phải thêm `measure()`
  riêng trong từng node hoặc trong `agents/graph.py`, chưa làm ở mức này.
- **Còn thiếu:** không có Langfuse/LangSmith/Prometheus/OpenTelemetry nào trong
  `pyproject.toml` — `QUERY_METRICS` hiện chỉ ra log text (structured nhưng không có
  dashboard/query UI). Nếu thêm LLM tracing backend thật: KHÔNG log nội dung
  chunk/câu trả lời chứa dữ liệu nhạy cảm ra backend bên thứ 3 (SaaS) mà không kiểm
  tra chính sách bảo mật dữ liệu — hệ thống enterprise, document có thể chứa nội
  dung nội bộ. Cần quyết định Langfuse (self-host) vs LangSmith (SaaS) trước khi
  code (chi phí/vendor lock-in khác nhau).

## 6. Evaluation — RAGAS Quality
**Chưa tồn tại trong code — gap.** Không có eval pipeline nào đo faithfulness/relevance/
context precision. Nếu thêm, đặt ở `backend/app/tests/` hoặc script riêng
(vd `backend/scripts/eval_ragas.py`), chạy offline trên 1 tập câu hỏi mẫu — KHÔNG chạy
RAGAS trong request path (`/chat`), vì RAGAS cần thêm LLM calls để chấm điểm, không phù
hợp latency < 5s (`Response time` target trong `backend/CLAUDE.md`).

## Khi review xong

Nếu phát hiện thêm technical debt mới không có trong danh sách trên, cập nhật bảng "Technical
debt" trong skill `enterprise-knowledge-rag` (không lặp lại phân tích ở đây — skill đó là nguồn
chân lý duy nhất cho danh sách technical debt của cả project).
