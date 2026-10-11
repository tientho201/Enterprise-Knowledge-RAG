# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Enterprise Knowledge RAG — Backend**

FastAPI + Celery + LangGraph. Ingestion bất đồng bộ, truy hồi hybrid (dense Qdrant + đồ thị Neo4j), agent trả lời có trích dẫn, REST API + SSE dưới `/api/v1`.

File này mô tả **code đang có**. Khi file này và mã nguồn lệch nhau, tin mã nguồn. `CLAUDE.md` ở gốc repo mô tả cả monorepo; file này chỉ đi sâu phần backend.

---

## Tech Stack

| Layer | Technology | Nguồn |
|---|---|---|
| API | FastAPI, strictly async | `app/main.py` |
| ORM / DB | SQLAlchemy async + asyncpg, PostgreSQL | `app/db/session.py` |
| Task queue | Celery + Redis | `app/workers/celery_app.py` |
| Vector DB | Qdrant | `app/rag/retriever.py` |
| Knowledge graph | Neo4j | `app/rag/graph_client.py`, `app/ingestion/graph_indexer.py` |
| Object storage | AWS S3 qua `boto3`; LocalStack khi dev (`AWS_S3_ENDPOINT_URL` có giá trị), S3 thật khi để trống | `app/storage/s3_client.py` |
| LLM | OpenAI `gpt-4o-mini` (`OPENAI_MODEL`) qua `get_llm()` | `app/llm/` |
| Embedding | OpenAI `text-embedding-3-small`, 1536 chiều (`EMBEDDING_MODEL`) | `app/ingestion/embedder.py` |
| Agent | LangGraph | `app/agents/graph.py` |
| Observability | Prometheus `/metrics`, LangSmith (tắt mặc định), `tracker.measure()` | `app/main.py`, `app/analytics/tracker.py` |
| Package manager | **uv**, Python **3.11** | `pyproject.toml` |

---

## Common Commands

Chạy từ `backend/`:

```bash
uv sync --extra dev                                        # cài dependencies + nhóm dev (pytest, ruff, mypy, aiosqlite)
uv run uvicorn app.main:app --reload --port 8000           # API → :8000 (/docs, /health, /metrics)
uv run celery -A app.workers.celery_app worker -Q ingestion,sync --loglevel=info
uv run ruff check . --fix && uv run ruff format .          # lint + format
uv run mypy app/                                           # type check
uv run alembic upgrade head                                # áp migration
uv run alembic revision --autogenerate -m "msg"            # migration mới
uv run alembic current                                     # revision DB đang ở
docker-compose up -d                                       # hạ tầng local: redis, neo4j, localstack
```

- Công cụ dev nằm ở `[project.optional-dependencies] dev`, nên phải có `--extra dev` (CI dùng `uv sync --frozen --extra dev`). `uv sync` trần sẽ **gỡ** các gói dev khỏi môi trường.
- Worker **phải** có `-Q ingestion,sync`: `task_routes` đẩy mọi task vào hai queue này, không task nào ở queue mặc định. Thiếu worker thì upload nằm mãi ở `pending` và email OTP không gửi.
- Trên Windows thêm `--pool=solo` vào lệnh worker — `dev.ps1` chạy đúng lệnh trên kèm cờ này.
- `docker-compose.yml` không dựng Postgres và Qdrant; hai dịch vụ này lấy từ cấu hình môi trường (mẫu ở `.env.example`).
- Từ gốc repo, `dev.ps1` chạy API + worker bằng một lệnh.

### Tests

```bash
uv run pytest app/tests/unit/test_chunker.py -v            # một file
uv run pytest app/tests/unit/test_chunker.py::test_name -v # một test
uv run pytest -m neo4j                                     # cần Neo4j thật, tự skip nếu không kết nối được
uv run pytest -m eval -s app/tests/eval/                   # gọi dịch vụ thật, tốn tiền, không chạy trong CI
```

`asyncio_mode = "auto"`, một event loop session-scoped cho mọi test; unit test dùng SQLite in-memory (`app/tests/conftest.py`).

#### Lưu ý khi chạy test

**Ít nhất** hai file trong `app/tests/unit/` **chạm dịch vụ thật** khi chạy cả bộ unit (`uv run pytest` hoặc `uv run pytest app/tests/unit/`). Chưa được sửa, và CI chạy cả `app/tests/unit/` không có `--ignore`. Các test khác trong bộ unit cũng có thể mở kết nối tới dịch vụ đang cấu hình trong môi trường khi chạy tràn — đừng coi bộ unit là cô lập:

- `test_s3.py` — là script chạy ngay ở cấp module (không có hàm test): pytest chỉ cần *thu thập* file là nó đọc `.env`, tạo `connection_test.txt` và upload lên S3 thật bằng thông tin trong môi trường.
- `test_live_api.py` — gọi `http://127.0.0.1:8000`: đăng nhập/đăng ký rồi gửi `POST /chat` với `search_tool=true`.

Cho tới khi hai file này được xử lý, chạy theo từng file hoặc thêm `--ignore=app/tests/unit/test_s3.py --ignore=app/tests/unit/test_live_api.py`.

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py            # create_app(): CORS, 6 router dưới /api/v1, /metrics, /health
│   ├── api/               # router mỏng: auth, chat, documents, admin, audit_logs, graph
│   ├── services/          # logic: auth, chat, chat_attachment, document, graph, audit_log, web_search
│   ├── repositories/      # truy vấn DB: user, document, conversation, audit_log, failed_task, message_attachment
│   ├── models/            # SQLAlchemy: user, document, chunk, conversation, message, citation,
│   │                      #   audit_log, document_conversation, failed_task, message_attachment
│   ├── schemas/           # Pydantic: auth, chat, document, admin, graph, audit_log
│   ├── core/              # config, dependencies (DI), security (JWT), token_blacklist, rate_limit,
│   │                      #   plan_gate, otp, redis_client
│   ├── auth/rbac.py       # require_role + RequireAdmin/Editor/Viewer
│   ├── agents/            # graph, state + node: guardrail, router, contextualizer, retriever, grader,
│   │                      #   rewriter, generator; helper: history, prompt_defense, dlp, llm_select
│   ├── rag/               # retriever (HybridRetriever), reranker (HybridScoreReranker),
│   │                      #   citation_retriever, graph_client, graph_queries, response_cache
│   ├── ingestion/         # chunker, embedder, pipeline (extract_text), graph_indexer,
│   │                      #   structural_parser, citation_llm_fallback
│   ├── llm/               # base, factory, openai_llm, vllm_llm
│   ├── workers/           # celery_app, dlq, tasks/{ingestion,sync,email}.py
│   ├── storage/s3_client.py
│   ├── connectors/        # base, pdf, confluence
│   ├── analytics/tracker.py
│   ├── db/                # base, session
│   └── tests/             # unit/, integration/, e2e/, eval/ (+ golden_set.json)
├── alembic/versions/      # 8 migration
├── docker-compose.yml     # dev: redis, neo4j, localstack
├── docker-compose.prod.yml
├── Dockerfile
├── .env.example           # mẫu biến môi trường (.env không commit)
└── pyproject.toml
```

---

## Architecture

```
Frontend (Next.js) ──HTTP/SSE──> FastAPI /api/v1 ──> LangGraph agent ──> LLM
                                      │                    │
                                      │                    └─ Qdrant (dense) + Neo4j (graph)
                                      └─ Celery (Redis) ──> ingestion: S3 → chunk → embed → Qdrant + Neo4j
```

| Store | Dùng cho |
|---|---|
| PostgreSQL | users, documents (metadata), chunks, conversations, messages, citations, audit_logs, document_conversations (nhiều-nhiều tài liệu ↔ hội thoại), failed_tasks, message_attachments |
| Qdrant | vector của chunk; payload `document_id`, `document_name`, `chunk_index`, `content`, `owner_id` |
| Neo4j | `(:Chunk)` với cạnh `NEXT_CHUNK` / `REFERENCES`; lớp Provision / LegalDocument với `VIEN_DAN` cho chế độ "Nâng cao" |
| S3 | file gốc của tài liệu, ảnh đính kèm chat |
| Redis | Celery broker/backend, token blacklist, OTP, rate limit, response cache |

Lớp phân tầng: `api/` → `services/` → `repositories/` → `models/`; request/response ở `schemas/`.

---

## LLM Abstraction Layer (Critical)

**KHÔNG BAO GIỜ** gọi OpenAI trực tiếp trong routes, services, hay graph nodes.

```python
from app.llm.factory import get_llm
llm = get_llm()  # BaseLLM
```

- `get_llm()` đọc `LLM_PROVIDER` (mặc định `openai`) và hiện **chỉ** trả `OpenAILLM`. Nhánh `vllm` đang bị comment trong `factory.py`, nên `LLM_PROVIDER=vllm` ném `ValueError` dù `vllm_llm.py` tồn tại.
- BYOM: `get_llm_for_request(model, api_key, base_url)` dựng client OpenAI-compatible tạm cho một request khi có `api_key`; không có `api_key` thì luôn về `get_llm()`. Key không được lưu ở server.
- Hiện chỉ **generator** (và nhánh stream trong `chat_service.py`) dùng BYOM. `router`, `grader`, `rewriter`, `contextualizer` gọi thẳng `get_llm()`. `agents/llm_select.py::get_llm_for_state` đã có nhưng chưa node nào dùng.

---

## LangGraph Agent Workflow

`agents/graph.py`, state ở `agents/state.py`:

```
START → guardrail ─(blocked)──────────────────────────────→ generator → END
            └→ router ─(không phải rag)───────────────────→ generator
                  └(rag)→ contextualizer → retriever → grader ─(ok)→ generator
                                              ↑           └(confidence < 0.3 và retry_count < 2)
                                              └── rewriter ←┘
```

- **guardrail** — regex chặn prompt injection, không gọi LLM; đặt `intent = "blocked"`.
- **router** — phân loại `rag` / `chitchat` / `out_of_scope`.
- **contextualizer** — chỉ làm việc khi `state["history"]` có lượt dùng được: đúng 1 LLM call (timeout 15 giây) viết lại câu hỏi nối tiếp thành câu độc lập, ghi vào `rewritten_query`. `query` không bao giờ bị thay. Mọi lỗi → giữ nguyên state. Chỉ chạy một lần trên đường vào; vòng rewriter → retriever không đi qua nó.
- **retriever** — xem mục Retrieval.
- **grader** — `HybridScoreReranker` cắt top-K, rồi 1 LLM call chấm cả lô; `confidence_score` quyết định có rewrite không (`MAX_RETRIES = 2`).
- **generator** — chỉ trả lời từ context, có trích dẫn. Thiếu context → `"Not found in documents."` / `"Không tìm thấy trong tài liệu."`. Nếu request bật `search_tool`, rơi sang web search (DuckDuckGo, `services/web_search.py`).

`/chat/stream` dùng `build_retrieval_graph()` (cùng các node nhưng dừng trước generator) rồi stream token ngoài graph. Trường hợp chitchat, không có context, web fallback hoặc có ảnh thì gọi `generator_node` và phát một `delta` duy nhất.

### Lịch sử hội thoại

- `ChatService._load_history` nạp tối đa `CHAT_HISTORY_MAX_MESSAGES` (mặc định **6**; `0` = tắt) tin nhắn gần nhất vào `AgentState.history`, **trước** khi lưu tin nhắn user của lượt hiện tại.
- **Không nạp** khi: hội thoại mới (không có `conversation_id`), giới hạn `<= 0`, hoặc request bật `search_tool`. Giới hạn cuối là tạm thời: generator dùng `rewritten_query or query` làm truy vấn web, mà `rewritten_query` có thể mang nội dung tài liệu nội bộ lấy từ lịch sử.
- Fail-safe: nạp lỗi → log WARNING, lượt đó chạy như lượt độc lập.
- `agents/history.py` bóc marker trích dẫn khỏi câu trả lời cũ, chỉ nhận role `user` / `assistant`, vô hiệu hoá tag trước khi đưa vào prompt (khối `<history>`).
- Lượt có lịch sử không đọc và không ghi response cache.

---

## Retrieval

`rag/retriever.py::HybridRetriever`, điều phối bởi `agents/retriever.py::retriever_node`.

Mỗi lượt node chạy: **1** lời gọi Qdrant (`_dense_search`) và **tối đa 1** lời gọi Neo4j (`_graph_search`), rồi trộn bằng `HybridRetriever.merge()` (hàm thuần, không I/O). Node **không** gọi `retrieve()`, vì hàm đó tự chạy lại cả hai nhánh.

- **Dense** — Qdrant `/points/search`, top `DENSE_TOP_K` (20), `score_threshold` tuỳ chọn từ UI.
- **Nhánh thưa = đồ thị Neo4j**, không có chỉ mục từ khoá: từ các chunk dense, đi `NEXT_CHUNK|REFERENCES` độ sâu 1..2, tối đa `GRAPH_TOP_K` (20). Neo4j lỗi → log WARNING và rơi về dense-only.
- **Điểm** — `DENSE_WEIGHT` (0.7) × dense chuẩn hoá + `GRAPH_WEIGHT` (0.3) × điểm graph.
- **Rerank** — `rag/reranker.py::HybridScoreReranker` chỉ sắp theo điểm hybrid sẵn có và cắt `RERANK_TOP_K` (**10**; `top_k` từ request ghi đè). **Không phải cross-encoder**, không tải model nào.

### `search_mode`

| Giá trị | Hành vi hiện tại |
|---|---|
| `None` / `hybrid` | dense + graph như trên |
| `vector` | dense-only: không chạm Neo4j, không gọi `merge()`, điểm là cosine thô |
| `keyword` | **chạy y như hybrid** (chưa có hành vi riêng) |
| `advanced` | hybrid + `rag/citation_retriever.py::graph_augmented_search` (đi `VIEN_DAN`); bị gate theo gói ở route |

Response cache (`rag/response_cache.py`, Redis, exact-match, TTL 30 phút) chỉ áp cho `POST /chat` không-stream và chỉ khi `search_mode` là `None` / `hybrid`, không có web search, ảnh, system prompt tuỳ biến, BYOM hay lịch sử. `/chat/stream` không dùng cache.

### Cô lập dữ liệu và tài liệu tắt

- `owner_id = None if is_admin else user_id`, lọc ở cả Qdrant (`must`) lẫn Cypher (`related.owner_id`). Chunk cũ thiếu `owner_id` trong payload bị ẩn với non-admin cho tới khi reindex.
- Tài liệu `is_active=false` bị loại khỏi RAG bằng **danh sách loại trừ**: `DocumentRepository.list_inactive_ids(owner_id)` → `AgentState.excluded_document_ids` → Qdrant `must_not`, Cypher `NOT related.document_id IN $excluded_document_ids`, cộng chốt chặn trong `merge()` và `_drop_excluded` ở node. Áp dụng cả với admin.
- **Fail-closed**: truy vấn danh sách này không có try/except — DB lỗi thì request lỗi, không chạy truy hồi không lọc. Danh sách cũng nằm trong cache key.
- Bộ lọc này chưa áp cho graph explorer (`/graph/*`).

---

## Ingestion Pipeline

```
POST /documents/upload (202)
  → kiểm content-type (pdf / docx / txt) và kích thước (tối đa 50 MB)
  → S3 (file gốc) + PostgreSQL (metadata, owner_id) + audit log
  → Celery ingest_document
      → tải từ S3 → extract_text → chunk (RecursiveCharacterTextSplitter, 800 / 200)
      → embed (OpenAI, theo lô) → Qdrant (tự tạo collection + payload index owner_id, document_id; upsert lô 100)
      → ghi lại bảng chunks → Neo4j: chunk graph, rồi Provision / LegalDocument graph
      → status = indexed
```

- `chunk_id` tất định: `uuid5(namespace, f"{document_id}:{chunk_index}")` — retry và reindex hội tụ về cùng bản ghi. Không đổi namespace.
- Xoá: soft-delete ở PostgreSQL trước, rồi `delete_document_vectors` dọn Qdrant + Neo4j + S3.
- Reindex: `chain(delete_document_vectors(storage_path=None), ingest_document)` — giữ file S3.
- Upload, xoá, reindex, bật/tắt tài liệu đều gọi `bump_version` để vô hiệu response cache.
- `ingestion/pipeline.py` chỉ còn `extract_text` được dùng.

---

## API Endpoints

Prefix `/api/v1`. Payload chi tiết: `frontend/endpointAPIbe.json` và `/docs`. Nguồn chuẩn là `app/api/*.py`.

**Auth** (`api/auth.py`)
- `POST /auth/register` (201, trả `OtpPendingResponse`), `/auth/verify-otp`, `/auth/resend-otp`, `/auth/login`, `/auth/refresh` — công khai
- `GET /auth/me`, `POST /auth/logout` (204, đưa `jti` vào blacklist) — cần token
- `POST /auth/plan` — đổi gói của chính mình, không có thanh toán thật. Nâng lên `pro` bị **403** trừ khi `SELF_SERVICE_PLAN_ENABLED=true` (mặc định `false`); hạ về `free` luôn được.

**Chat** (`api/chat.py`)
- `POST /chat`, `POST /chat/stream` (SSE: `meta`, `delta`, `done`, `error`) — rate limit + gate `advanced`
- `POST /chat/images` (201) — ảnh vision, tối đa 3 ảnh mỗi tin nhắn, không vào thư viện tài liệu
- `GET /chat/history`, `GET /chat/{conversation_id}`, `DELETE /chat/{conversation_id}` (204)

**Documents** (`api/documents.py`)
- `POST /documents/upload` (202, rate limit), `GET /documents`, `GET /documents/{doc_id}`, `GET /documents/{doc_id}/download` (presigned URL)
- `DELETE /documents/{doc_id}` (204), `POST /documents/reindex`, `PATCH /documents/{doc_id}/active`
- `POST` / `PUT /documents/{doc_id}/conversations`

**Admin** (`api/admin.py`) — `require_role(UserRole.admin)` đặt ở **cấp router**, mọi route thêm sau cũng bị chặn
- `GET /admin/dashboard`, `GET /admin/jobs`, `GET /admin/users`, `PATCH /admin/users/{target_user_id}/role`
- `GET /admin/failed-tasks`, `POST /admin/failed-tasks/{failed_task_id}/resolve`

**Graph** (`api/graph.py`) — cả router qua `require_advanced_access` (gói Pro hoặc admin)
- `GET /graph/overview`, `GET /graph/expand`, `POST /graph/highlight`

**Audit logs** (`api/audit_logs.py`)
- `GET /audit-logs` — chỉ log của chính user
- `POST /audit-logs` (201) — đã siết: chỉ nhận `resource_type` là `config` hoặc `research`, giới hạn độ dài, rate limit riêng (`AUDIT_LOG_RATE_LIMIT_PER_MINUTE`, 60); server luôn gắn `extra_data.source = "client"` và bỏ các khoá dành riêng (`source`, `dlp_flag`, `dlp_reason`).

**Ngoài prefix:** `GET /health` (ping DB, Redis, Qdrant; 503 nếu có thành phần down), `GET /metrics`.

Rate limit là fixed-window trên Redis, theo user, **fail-open** khi Redis lỗi: chat 20, upload 10, ảnh chat 30 mỗi phút.

---

## Auth & Phân quyền thực tế

- JWT HS256: access 30 phút, refresh 7 ngày. `get_current_user_id` yêu cầu `type == "access"` và kiểm blacklist. Đăng ký phải xác minh OTP qua email.
- Quyền truy cập dữ liệu dựa trên **`owner_id` + role admin**: non-admin chỉ thấy tài liệu và chunk của mình; tài nguyên của người khác trả **404**, không phải 403 (`DocumentService._get_owned_or_404`).
- Role `editor` / `viewer` tồn tại trong `UserRole` và `auth/rbac.py`, nhưng **chưa route nào ép**. `require_role` hiện chỉ dùng cho `/admin/*`.
- Gói (`free` / `pro`) là trục độc lập với role: `core/plan_gate.py::can_use_advanced_search` — admin luôn qua; `pro` chưa hết hạn thì qua. Áp cho `search_mode="advanced"` và toàn bộ `/graph/*`.

---

## Database & Migrations

Chuỗi Alembic (`alembic/versions/`), tuyến tính:

```
76a3f5675651  initial schema
a1b2c3d4e5f6  document owner_id
b2c3d4e5f6a7  document conversation + is_active
c3d4e5f6a7b8  document_conversations many-to-many
e5f6a7b8c9d0  user plan
f6a7b8c9d0e1  message_attachments
7e5777fabb9e  user email_verified
d1e2f3a4b5c6  failed_tasks                        ← HEAD
```

Head trong repo là `d1e2f3a4b5c6`. Revision của một DB cụ thể phải kiểm bằng `uv run alembic current`, không suy từ file này.

**Trích dẫn** không có cột riêng: chúng nằm ở **cuối** `Message.content` của tin nhắn assistant dưới dạng marker `\n<!--citations:<JSON list>-->`. Chỉ ghi và đọc qua `_encode_citations` / `_decode_citations` trong `services/chat_service.py` (marker giả trong câu trả lời bị vô hiệu hoá khi ghi). Bảng `citations` được ghi song song nhưng chỉ giữ `chunk_id` + `message_id` và bỏ qua trích dẫn web.

---

## Celery Tasks

Cấu hình chung (`workers/celery_app.py`): `task_acks_late`, `task_reject_on_worker_lost`, `worker_prefetch_multiplier=1`, giới hạn mặc định soft 540 giây / hard 600 giây. Mọi task khai `max_retries=3`, `retry_backoff=True` và tự gọi `self.retry(exc=exc)` khi lỗi; chỉ `ingest_document` có thêm `autoretry_for=(Exception,)`.

| Task | Queue | Soft / hard (giây) | Việc |
|---|---|---|---|
| `ingestion.ingest_document` | ingestion | 300 / 360 | extract → chunk → embed → Qdrant + Neo4j |
| `ingestion.delete_document_vectors` | ingestion | 60 / 90 | xoá Qdrant + Neo4j (+ S3 nếu có `storage_path`) |
| `ingestion.reindex_document` | ingestion | 30 / 60 | chỉ xếp chain delete → ingest |
| `ingestion.delete_chat_attachments` | ingestion | 30 / 60 | xoá ảnh chat trên S3 sau khi xoá hội thoại |
| `sync.sync_confluence` | sync | 180 / 240 | `ConfluenceConnector.sync`: chỉ tải trang và trả số đếm, **không ingest** |
| `sync.sync_slack` | sync | 180 / 240 | chưa làm, trả `not_implemented` |
| `email.send_otp_email` | sync | 20 / 30 | gửi OTP; bỏ qua nếu chưa cấu hình SMTP |

Tên đầy đủ có tiền tố `app.workers.tasks.`. Hai task `sync.*` chỉ được định nghĩa: không nơi nào trong `app/` dispatch chúng. Task hết lượt retry được `workers/dlq.py` ghi vào bảng `failed_tasks` (xem `/admin/failed-tasks`).

---

## Coding Rules

### Cấu trúc
1. **Routes mỏng** — chỉ parse request, gọi service, trả response.
2. **Business logic** → `services/`; **truy vấn DB** → `repositories/`.
3. **Strict async/await** — không gọi DB đồng bộ. Client đồng bộ (boto3, Neo4j driver, httpx sync, OpenAI embedder) phải bọc `asyncio.to_thread` hoặc dùng helper `*_async`.
4. **Dependency injection** cho auth và DB session: `DbDep`, `CurrentUserIdDep`, `CurrentUserDep` (`core/dependencies.py`).
5. **Không gọi OpenAI trực tiếp** — dùng `get_llm()` / `get_llm_for_request()`.
6. **Pydantic** cho mọi request/response.

Ngoại lệ đang tồn tại, đừng nhân rộng: `api/admin.py::dashboard` chạy truy vấn ngay trong route; `chat_service.py` tự `db.add(Citation)`.

### Database
- Mọi thay đổi schema qua **Alembic**; không sửa tay trên production.
- **Soft delete** bằng `deleted_at`.

### Retrieval & bảo mật
- Mọi đường truy hồi mới phải nhận và truyền đủ `owner_id`, `document_ids`, `excluded_document_ids`.
- Bộ lọc bảo mật là fail-closed; tính năng phụ (lịch sử, cache, Neo4j) là fail-safe. Đừng đảo hai loại này.
- Lịch sử, câu hỏi, tài liệu và đầu ra LLM đều là dữ liệu không tin cậy: bọc bằng `prompt_defense.wrap_untrusted`, vô hiệu hoá tag trước.
- Không log nội dung câu hỏi, chunk hay khoá API. (Code hiện **chưa** tuân thủ hết — xem "Chưa làm / giới hạn đã biết".)

### Chunking & embedding
- `RecursiveCharacterTextSplitter`, `CHUNK_SIZE = 800`, `CHUNK_OVERLAP = 200`.
- Embed theo lô (`EMBEDDING_BATCH_SIZE = 512`).

### Generator
1. Chỉ trả lời từ context đã truy hồi.
2. Thiếu context: trả đúng câu "not found", không bịa.
3. Câu trả lời phải có trích dẫn; không bịa trích dẫn.
4. System prompt của người dùng chỉ được **cộng thêm** vào `SYSTEM_PROMPT`, không thay thế.

### Celery
- Task phải **idempotent** và **retry-safe** (xem `chunk_id` tất định).
- Upload **không** được chặn request.
- Task mới phải nằm dưới `app.workers.tasks.{ingestion,sync,email}` để được route vào queue đang có worker, và tự khai `soft_time_limit` / `time_limit`.

---

## Chưa làm / giới hạn đã biết

- `search_mode="keyword"` chưa có chỉ mục riêng.
- Reranker là bản tạm (sắp theo điểm hybrid).
- Role `editor` / `viewer` chưa được ép ở route nào.
- Chưa có OCR: PDF scan bị từ chối ở `extract_text`.
- Đồng bộ nguồn ngoài chưa hoạt động: `sync_confluence` chỉ tải trang rồi trả số đếm (không đưa vào pipeline ingest), `sync_slack` trả `not_implemented`, và không nơi nào dispatch hai task này.
- Document versioning chưa có: cột `documents.version` tồn tại nhưng luôn là `1` (chỉ có giá trị mặc định ở model, không chỗ nào ghi).
- Audit log hiện chỉ được ghi ở: truy vấn chat, upload, xoá, reindex tài liệu (và log client tự gửi). **Chưa ghi** khi bật/tắt tài liệu, đổi role, đổi gói.
- Quy tắc "không log nội dung câu hỏi" đang bị vi phạm ở hai chỗ: `api/chat.py::chat` log nguyên văn `message` ở mức INFO; `chat_service.py` ghi 30 ký tự đầu của câu hỏi vào `audit_logs.action`. Đừng coi là mẫu để làm theo.
- Nhánh `vllm` trong factory đang tắt.
- Lịch sử hội thoại không được nạp khi bật `search_tool`.
