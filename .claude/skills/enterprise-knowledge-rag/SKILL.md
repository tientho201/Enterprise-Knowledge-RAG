---
name: enterprise-knowledge-rag
description: Context nén cho backend của project Enterprise Knowledge RAG (FastAPI + LangGraph + Qdrant + Neo4j + Supabase + S3), nằm trong thư mục backend/ của monorepo. LUÔN đọc skill này TRƯỚC khi đọc bất kỳ file source nào trong backend/, khi được hỏi về kiến trúc backend, khi sửa code, thêm feature, fix bug, review, hoặc bàn về CI/CD, deploy, storage, RAG pipeline, LangGraph agent, Celery task. Đọc skill này thay vì đọc lại backend/CLAUDE.md, config.py, hay grep qua nhiều file — skill này đã tổng hợp sẵn. Chỉ đọc file source thật khi cần xem chi tiết implementation cụ thể mà skill chưa đủ. Không dùng skill này cho frontend/ (xem skill run-frontend).
---

# Enterprise Knowledge RAG — Backend context

Monorepo: `E:\Project\Enterprise-Knowledge-RAG` (`.git` ở root, gồm `backend/` + `frontend/`).
Backend FastAPI cho hệ thống RAG doanh nghiệp nằm ở `backend/`. Tất cả path trong skill này
đều tính từ **repo root** (không phải từ `backend/`).

## Kiến trúc storage (đã chốt — không đề xuất đổi lại)

| Layer | Dùng gì | Lưu gì |
|---|---|---|
| Metadata | Supabase / PostgreSQL (asyncpg, port **6543** PgBouncer) | users, documents, chunks, conversations, messages, citations, audit_logs, failed_tasks, message_attachments |
| Raw files | AWS S3 (boto3; LocalStack ở dev qua `AWS_S3_ENDPOINT_URL`) | PDF/DOCX/TXT người dùng upload |
| Vector | Qdrant Cloud | dense embeddings của chunks |
| Graph | Neo4j (best-effort, graceful degradation) | NEXT_CHUNK / REFERENCES edges giữa chunks |
| Broker/cache | Redis | Celery broker + result backend; token blacklist, OTP, rate limit, response cache |

**Không dùng MinIO** — đã migrate sang S3. `backend/app/db/session.py` tự detect Supabase URL
để bật `statement_cache_size=0` + `ssl=require` (logic này có unit test riêng, xem mục CI/CD).
`DB_POOL_SIZE=5` vì Supabase free tier giới hạn 60 connections.

**Lưu ý**: đây là kiến trúc **production**. CI test integration KHÔNG dùng Supabase/Qdrant Cloud
thật — dùng container tạm (`postgres:16-alpine`, `qdrant/qdrant`) để tránh phụ thuộc secret/
mạng/cost. Xem mục CI/CD bên dưới.

## Layer convention (bắt buộc tuân theo khi sửa/thêm code)

```
backend/app/api/*          → route, CHỈ xử lý HTTP (parse request, gọi service, return response)
backend/app/services/*     → business logic, transaction orchestration
backend/app/repositories/* → DB query (SQLAlchemy async), không có business logic
backend/app/models/*       → SQLAlchemy ORM models
backend/app/schemas/*      → Pydantic request/response schemas
```
Không viết DB query trong route hoặc service. Không viết business logic trong repository.

## LLM & Embedding — factory pattern bắt buộc

- **Không bao giờ** gọi OpenAI client trực tiếp. Luôn dùng `get_llm()` từ
  `backend/app/llm/factory.py`.
- BYOM (model tùy chỉnh từ panel Cấu hình): `get_llm_for_request(model, api_key, base_url)` cùng
  file — có `api_key` thì dựng client OpenAI-compatible tạm cho request đó (không cache, không lưu
  key), không có thì về `get_llm()`. Hiện chỉ `generator_node` và nhánh stream của
  `chat_service.py` dùng. Nhánh `vllm` trong `get_llm()` đang bị comment (`LLM_PROVIDER=vllm` →
  `ValueError`).
- Embedding qua `get_embedder()` trong `backend/app/ingestion/embedder.py` — OpenAI
  `text-embedding-3-small` (1536 dims). **BGE-M3/local embedding đã bị loại bỏ hoàn toàn** —
  `torch`, `sentence-transformers`, `FlagEmbedding` đã bị xóa khỏi `backend/pyproject.toml`,
  không thêm lại.
- Provider hiện tại: `LLM_PROVIDER=openai` (GPT-4o-mini). Phase 2 dự kiến swap sang vLLM/Llama-3
  chỉ qua đổi biến môi trường, không đụng business logic.
- Reranker (`backend/app/rag/reranker.py`) hiện là **stopgap**: sort theo hybrid score có sẵn từ
  `HybridRetriever`, không dùng model riêng (đã bỏ CrossEncoder vì phụ thuộc
  sentence-transformers). Nếu cần chất lượng tốt hơn: Cohere Rerank API hoặc batch 1 LLM call.

## Async/sync boundary — nguồn lỗi phổ biến nhất trong repo này

- FastAPI route = async. Nhưng `boto3` (S3) và `openai.OpenAI` (sync client) **không async-safe**.
- Trong route/service: dùng async helpers `upload_bytes_async`, `download_file_async`,
  `delete_file_async`, `get_presigned_url_async` trong `backend/app/storage/s3_client.py` (wrap
  `run_in_executor`) — không gọi `S3Client` sync trực tiếp từ async context.
- Trong Celery task: gọi sync client (`get_s3_client()`) trực tiếp — Celery worker là sync
  context, không cần wrap.
- **Technical debt đã biết, chưa fix**: `OpenAIEmbedder.embed()` (client `openai.OpenAI` sync),
  `HybridRetriever._dense_search()` (dùng `httpx.Client` sync gọi REST API Qdrant thủ công thay
  vì SDK) và `_graph_search()` (Neo4j driver sync) vẫn là code sync. `retriever_node` đã bọc cả
  ba qua `asyncio.to_thread` nên KHÔNG còn block event loop — gọi mới từ async context phải bọc
  tương tự. Migrate sang `AsyncOpenAI` và `qdrant_client` async client khi có dịp.

## Celery task convention

- Tasks ở `backend/app/workers/tasks/*`, luôn `bind=True` + `retry_backoff=True`;
  `ingest_document` có thêm `autoretry_for=(Exception,)` và time limit riêng (soft 300s / hard 360s).
- Phải idempotent. Khi 2 task cần chạy tuần tự (vd: xóa vector trước khi re-ingest), dùng
  `celery.chain()` — **không** gọi `.delay()` rời rạc liên tiếp (đã từng có race condition ở
  `reindex_document`, đã fix bằng chain).
- `delete_document_vectors(document_id, storage_path)`: `storage_path=None` → chỉ xóa vector
  (dùng khi reindex, giữ file S3); có giá trị → xóa luôn file S3 (dùng khi user xóa document
  thật).

## LangGraph agent pipeline

State: `backend/app/agents/state.py` (`AgentState` TypedDict).
Flow (`backend/app/agents/graph.py`):
`guardrail → router → (contextualizer → retriever → grader → [rewriter ↺ retriever, max 2] →) generator`

- `guardrail_node`: đứng đầu graph; gắn `intent="blocked"` thì đi thẳng tới generator (trả câu
  cố định, không gọi LLM, không qua router).
- `router_node`: phân loại intent `rag | chitchat | out_of_scope` bằng 1 LLM call.
- `contextualizer_node`: chỉ chạy 1 lần trên đường vào nhánh `rag` (vòng rewriter không qua lại).
  Có `state["history"]` → 1 LLM call viết lại câu hỏi nối tiếp thành câu độc lập, ghi vào
  `rewritten_query` (`query` gốc không bao giờ bị thay). Không có lịch sử / LLM lỗi / đầu ra không
  hợp lệ → trả nguyên state.
- `retriever_node`: mỗi lượt đúng 1 lời gọi Qdrant (`_dense_search`) + tối đa 1 lời gọi Neo4j
  (`_graph_search`), trộn bằng `HybridRetriever.merge()` theo `DENSE_WEIGHT=0.7 /
  GRAPH_WEIGHT=0.3` — KHÔNG gọi `retrieve()` (sẽ chạy lại cả hai). Neo4j lỗi → `_graph_search`
  trả `{}` và log WARNING (rơi về dense-only, không còn im lặng).
- `grader_node`: rerank (`HybridScoreReranker` — chỉ sort theo điểm hybrid rồi cắt top_k, không
  gọi model) rồi chấm relevance CẢ LÔ chunk trong 1 lời gọi LLM duy nhất;
  `confidence_score` = số chunk relevant / số chunk đã rerank.
- `generator_node`: chỉ trả lời từ context đã retrieve, bắt buộc citation `[SOURCE: chunk_id]`.
  Nếu không tìm thấy và `search_tool=True` → fallback web search (DuckDuckGo scraping, fragile,
  cân nhắc thay Tavily API) kèm disclaimer rõ ràng là nguồn ngoài tài liệu nội bộ.

Các tham số request ảnh hưởng pipeline (dựng state ở `chat_service.py::_build_initial_state`):

- **`search_mode`** (`hybrid | vector | keyword | advanced`, `None` = hybrid): `vector` = dense-only
  (không chạm Neo4j, điểm cosine thô); `keyword` hiện chạy Y HỆT hybrid (chưa có nhánh riêng);
  `advanced` = hybrid + citation graph (`rag/citation_retriever.py`), gate theo gói ở route
  (`core/plan_gate.py::require_advanced_search_access` — admin hoặc plan Pro còn hạn, sai → 403).
- **Tài liệu tắt (`is_active=false`)**: `DocumentRepository.list_inactive_ids(owner_id)` →
  `AgentState.excluded_document_ids` → loại ở Qdrant (`must_not`), Cypher, `merge()` và
  `_drop_excluded` trong node. **Fail-closed**: DB lỗi thì request lỗi, không chạy retrieval
  không lọc.
- **Lịch sử hội thoại**: `ChatService._load_history` nạp tối đa `CHAT_HISTORY_MAX_MESSAGES` (mặc
  định 6) tin nhắn gần nhất của chính hội thoại đó vào `AgentState.history` (qua
  `agents/history.py::to_history`, đã bóc marker trích dẫn), TRƯỚC khi lưu tin nhắn user. Dùng ở
  contextualizer và generator (khối `<history>` chỉ là ngữ cảnh, không phải nguồn trích dẫn).
  Fail-safe: nạp lỗi → `[]`. **Không nạp khi `search_tool=True`** (xem bảng debt).
- **Response cache** (`rag/response_cache.py`, chỉ `POST /chat`): chỉ đọc/ghi khi không web
  search/ảnh/system prompt/BYOM, `search_mode` là `None`/`hybrid` và lượt đó không có lịch sử.
- **Streaming**: `POST /chat/stream` (SSE: `meta`/`delta`/`done`/`error`) chạy
  `get_retrieval_graph()` (dừng trước generator) rồi stream bằng `llm.stream_chat`; không dùng
  response cache.

## Technical debt đã phát hiện (đọc trước khi đề xuất lại các vấn đề này — tránh lặp lại phân tích)

| Vấn đề | File | Mức độ |
|---|---|---|
| Citations vẫn lưu bằng marker `<!--citations:{json}-->` ở CUỐI `Message.content`; chỉ ghi/đọc qua `_encode_citations` / `_decode_citations` (marker giả trong câu trả lời bị vô hiệu hoá `<` → `&lt;`, chỉ nhận marker cuối có JSON hợp lệ) | `backend/app/services/chat_service.py` | Đã gia cố, nhưng `get_conversation` vẫn đọc từ marker thay vì bảng `citations` (bảng chỉ được ghi `chunk_id` + `message_id`) |
| `_dense_search()` dùng `httpx.Client` build REST request thủ công thay vì `qdrant_client` SDK | `backend/app/rag/retriever.py` | Dư thừa, dễ lỗi khi Qdrant đổi API |
| Lịch sử hội thoại KHÔNG được nạp khi `search_tool=True` (tạm thời): web search dùng `rewritten_query or query`, mà `rewritten_query` có thể dựng từ lịch sử chứa nội dung tài liệu nội bộ | `backend/app/services/chat_service.py` (`_load_history`), `backend/app/agents/generator.py` | Mất multi-turn khi bật web search; gỡ sau khi generator chỉ dùng `query` gốc cho web search |
| Connectors: Confluence có `load()` thật (REST, phân trang) nhưng `sync()` chỉ đếm số trang tải được, CHƯA nối vào ingestion; Slack: task `sync_slack` trả `not_implemented`, không có connector; Google Drive: không có file nào | `backend/app/connectors/confluence.py`, `backend/app/workers/tasks/sync.py` | Chưa dùng được để nạp tài liệu |
| Reranker là stopgap (sort theo hybrid score, không phải model rerank thật) | `backend/app/rag/reranker.py` | Chất lượng rerank có thể chưa tối ưu |

**Đã fix (production-readiness audit, xem `.claude/tasks/production-readiness-audit.md`):**
- ✅ Health check thật (ping DB/Redis/Qdrant, trả 503 nếu down) — `backend/app/main.py` + `app/core/redis_client.py`.
- ✅ Rate limiting `/chat` + `/documents/upload` (Redis fixed-window, fail-open) — `backend/app/core/rate_limit.py`.
- ✅ JWT logout + Redis blacklist (`jti` trong token, `POST /auth/logout`) — `app/core/token_blacklist.py`, `app/api/auth.py`.
- ✅ Config hardening: guard SECRET_KEY/DEBUG khi `APP_ENV=production`; `.gitignore` thêm `.env.prod`.
- ✅ File `user-EKRag_accessKeys.csv`: xác nhận KHÔNG được git track (`git ls-files` sạch); `.gitignore` có `*.csv`.
- ✅ **Data isolation documents** (owner-scoped, personal workspace): `documents.owner_id` (migration
  `a1b2c3d4e5f6`) + `_get_owned_or_404` guard trong `document_service.py` → list/get/download/delete/
  reindex chỉ thấy doc của chính user; admin thấy tất cả; doc owner=NULL (legacy) ẩn với non-admin.
  Access control cho document = **ownership-based** (không role-gated — mọi user đăng nhập upload/
  mutate được doc của mình). `get_current_user`/`CurrentUserDep` mới trong `core/dependencies.py`.
- ✅ **Data isolation RAG retrieval** (end-to-end nối tiếp isolation documents): chunk mang `owner_id`
  trong payload Qdrant + property node Neo4j (ghi lúc ingest, `ingestion.py` + `graph_indexer.py`).
  `HybridRetriever._build_qdrant_filter` + owner filter trong Cypher `_graph_search`; `AgentState.owner_id`
  chảy từ `chat_service` (owner_id=user_id, admin=None → không filter) → `retriever_node`. `/chat` giờ
  chỉ truy hồi chunk của chính user; admin thấy tất cả; chunk legacy (payload thiếu owner_id) ẩn với
  non-admin. **Lưu ý deploy:** chunk cũ ingest trước thay đổi này thiếu `owner_id` → non-admin không
  truy hồi được; cần reindex để backfill payload.

## CI/CD — đã fix vị trí (từng là bug: workflow nằm sai chỗ)

`.git` nằm ở **repo root**, không phải trong `backend/`. GitHub Actions chỉ scan
`.github/workflows` tại repo root — vì vậy `.github/` PHẢI nằm ở root, không phải
`backend/.github`. (Đã từng bị đặt sai chỗ và các workflow chưa bao giờ chạy — đã fix.)

- `.github/workflows/ci.yml`: `defaults.run.working-directory: backend`, trigger có `paths:
  ["backend/**"]`. Jobs: lint (ruff+mypy) → unit tests (SQLite) + integration tests (Postgres +
  Qdrant + Redis + Neo4j + LocalStack — **tất cả container tạm trong CI job**, KHÔNG dùng
  Supabase staging hay Qdrant Cloud thật, không cần secret nào cho CI) → docker build validate
  (`context: ./backend`). PgBouncer-specific logic được test riêng bằng unit test
  (`backend/app/tests/unit/test_db_session.py`), không cần container PgBouncer thật. Lý do đầy
  đủ + cách debug xem skill `continuous-integration`.
- `.github/workflows/cd.yml`: build & push ghcr.io (`context: ./backend`) → `alembic upgrade
  head` với `secrets.DATABASE_URL` (production Supabase) → SSH deploy → health check. Cần
  GitHub Environment `production` với required reviewers.
- `backend/docker-compose.yml` (dev): chỉ Redis + Neo4j + LocalStack (S3 giả lập); Postgres/Qdrant
  cloud managed, S3 thật ở production — CI thì local container, xem trên.
- `backend/docker-compose.prod.yml`: thêm Celery worker + beat, image từ ghcr.io.

## File map nhanh — sửa gì thì mở file nào (path tính từ repo root)

| Muốn sửa | File |
|---|---|
| Cấu hình env/settings | `backend/app/core/config.py` |
| Auth/JWT | `backend/app/core/security.py`, `backend/app/services/auth_service.py` |
| Upload/download/xóa document | `backend/app/services/document_service.py`, `backend/app/api/documents.py` |
| S3 client | `backend/app/storage/s3_client.py` |
| DB session / PgBouncer detection | `backend/app/db/session.py` |
| Chunking | `backend/app/ingestion/chunker.py` (RecursiveCharacterTextSplitter, 800/200) |
| Embedding | `backend/app/ingestion/embedder.py` |
| Celery ingestion tasks | `backend/app/workers/tasks/ingestion.py` |
| Retrieval (dense+graph) | `backend/app/rag/retriever.py` |
| Rerank | `backend/app/rag/reranker.py` |
| LangGraph nodes | `backend/app/agents/{guardrail,router,contextualizer,retriever,grader,rewriter,generator}.py` |
| Lịch sử hội thoại trong prompt | `backend/app/agents/history.py`, `ChatService._load_history` |
| Chat/conversation | `backend/app/services/chat_service.py`, `backend/app/api/chat.py` |
| Admin dashboard | `backend/app/api/admin.py` |
| Audit log | `backend/app/repositories/audit_log_repo.py`, `backend/app/api/audit_logs.py` |
| DB models | `backend/app/models/*.py` |
| Migrations | `backend/alembic/` |
| CI/CD | `.github/workflows/{ci,cd}.yml` (repo root, không phải backend/) |

## Quy tắc khi đề xuất thay đổi

1. Storage split (Supabase=metadata, S3=raw file) là quyết định đã chốt — không đề xuất đổi lại
   trừ khi user yêu cầu.
2. Trước khi báo "đã xong", kiểm tra xem thay đổi có ảnh hưởng file nào khác trong bảng technical
   debt ở trên không (vd: sửa reranker thì check luôn `grader_node` có gọi đúng interface không).
3. Khi thêm dependency mới vào `backend/pyproject.toml`, cân nhắc kích thước Docker image —
   project đã một lần phải dọn ~2.5GB do torch/sentence-transformers không dùng nữa.
4. Ưu tiên sync file `backend/.env.example`, `backend/CLAUDE.md`, và CI workflow mỗi khi đổi
   kiến trúc storage hoặc dependencies — 3 chỗ này dễ bị lệch khỏi code thật nếu quên cập nhật.
5. `.github/workflows/` phải luôn ở repo root — không di chuyển vào `backend/` (GitHub không
   scan workflow ở subfolder).
6. Ưu tiên container tạm (self-host image) cho CI thay vì cloud thật (Supabase/Qdrant Cloud),
   trừ khi có lý do kỹ thuật cụ thể không thể tái tạo bằng container local — xem giải thích ở
   mục CI/CD.
