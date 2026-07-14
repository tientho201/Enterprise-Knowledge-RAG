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
| Metadata | Supabase / PostgreSQL (asyncpg, port **6543** PgBouncer) | users, documents, chunks, conversations, messages, citations, audit_logs |
| Raw files | AWS S3 (boto3; LocalStack ở dev qua `AWS_S3_ENDPOINT_URL`) | PDF/DOCX/TXT người dùng upload |
| Vector | Qdrant Cloud | dense embeddings của chunks |
| Graph | Neo4j (best-effort, graceful degradation) | NEXT_CHUNK / REFERENCES edges giữa chunks |
| Broker/cache | Redis | Celery broker + result backend |

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
- **Technical debt đã biết, chưa fix**: `OpenAIEmbedder.embed()` và
  `HybridRetriever._dense_search()` (dùng `httpx.Client` sync gọi REST API Qdrant thủ công thay
  vì SDK) đang block event loop khi gọi từ async agent node. Cần migrate sang `AsyncOpenAI` và
  `qdrant_client` async client khi có dịp.

## Celery task convention

- Tasks ở `backend/app/workers/tasks/*`, luôn `bind=True` + `autoretry_for=(Exception,)` +
  `retry_backoff=True`.
- Phải idempotent. Khi 2 task cần chạy tuần tự (vd: xóa vector trước khi re-ingest), dùng
  `celery.chain()` — **không** gọi `.delay()` rời rạc liên tiếp (đã từng có race condition ở
  `reindex_document`, đã fix bằng chain).
- `delete_document_vectors(document_id, storage_path)`: `storage_path=None` → chỉ xóa vector
  (dùng khi reindex, giữ file S3); có giá trị → xóa luôn file S3 (dùng khi user xóa document
  thật).

## LangGraph agent pipeline

State: `backend/app/agents/state.py` (`AgentState` TypedDict).
Flow: `router → (retriever → grader → [rewrite loop, max 2] →) generator`

- `router_node`: phân loại intent `rag | chitchat | out_of_scope` bằng 1 LLM call.
- `retriever_node`: `HybridRetriever` — dense (Qdrant) + graph expansion (Neo4j), merge theo
  `DENSE_WEIGHT=0.7 / GRAPH_WEIGHT=0.3`.
- `grader_node`: rerank rồi grade từng chunk. **Technical debt**: gọi LLM 1 lần/chunk (N calls)
  — nên batch thành 1 call hoặc thay bằng cosine similarity threshold.
- `generator_node`: chỉ trả lời từ context đã retrieve, bắt buộc citation `[SOURCE: chunk_id]`.
  Nếu không tìm thấy và `search_tool=True` → fallback web search (DuckDuckGo scraping, fragile,
  cân nhắc thay Tavily API) kèm disclaimer rõ ràng là nguồn ngoài tài liệu nội bộ.

## Technical debt đã phát hiện (đọc trước khi đề xuất lại các vấn đề này — tránh lặp lại phân tích)

| Vấn đề | File | Mức độ |
|---|---|---|
| Citations lưu bằng HTML comment `<!--citations:{json}-->` nhúng vào `message.content`, parse lại bằng regex | `backend/app/services/chat_service.py` | Fragile — bảng `citations` đã có nhưng dùng sai cách |
| `_dense_search()` dùng `httpx.Client` build REST request thủ công thay vì `qdrant_client` SDK | `backend/app/rag/retriever.py` | Dư thừa, dễ lỗi khi Qdrant đổi API |
| SSE streaming cho `/chat` chưa implement — block đến khi graph chạy xong | `backend/app/api/chat.py` | UX |
| Conversation history không được nạp vào `AgentState` — mỗi câu hỏi xử lý độc lập | `backend/app/services/chat_service.py` | Thiếu multi-turn |
| Connectors Confluence/Slack/Google Drive: model có enum nhưng code trống | `backend/app/connectors/` | Chưa implement |
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
  ⚠️ RAG retrieval (`retriever.py`) CHƯA scope theo owner — nếu cần cô lập cả kết quả truy hồi thì
  phải filter Qdrant/Neo4j theo owner_id (task riêng, chưa làm).

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
- `backend/docker-compose.yml` (dev): chỉ Redis + Neo4j (Postgres/S3/Qdrant đều cloud managed ở
  production — CI thì local container, xem trên).
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
| LangGraph nodes | `backend/app/agents/{router,retriever,grader,rewriter,generator}.py` |
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
