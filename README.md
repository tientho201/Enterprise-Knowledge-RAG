# Enterprise Knowledge RAG

Hệ thống RAG (Retrieval-Augmented Generation) nội bộ doanh nghiệp: người dùng upload tài liệu, hỏi đáp qua chat, và nhận câu trả lời có trích dẫn nguồn — được sinh ra **chỉ** từ nội dung tài liệu đã ingest (không bịa, không hallucinate).

Monorepo gồm 2 ứng dụng độc lập:

| App | Path | Stack |
|---|---|---|
| **Backend** | [`backend/`](backend/) | FastAPI + Celery + LangGraph, Python 3.11, quản lý bằng **uv** |
| **Frontend** | [`frontend/`](frontend/) | Next.js 16 / React 19, TypeScript, Tailwind 4, shadcn/ui, quản lý bằng **npm** |

Tài liệu chi tiết từng phần: [`backend/README.md`](backend/README.md) · [`CLAUDE.md`](CLAUDE.md) (quy ước code cho AI agent).

---

## Kiến trúc tổng thể

```
Người dùng
   │  HTTP
   ▼
Frontend (Next.js, :3000)
   │  REST  /api/v1
   ▼
FastAPI (:8000) ── api/ (router mỏng) → services/ (business logic) → repositories/ (DB) → models/ (SQLAlchemy)
   │
   ▼
LangGraph Agent (app/agents/graph.py)

  START → router → (rag?) → retriever → grader → (confidence thấp & còn retry?) → rewriter ↺ retriever
             │ (chitchat / out-of-scope)                  │ (đủ tin cậy)
             ▼                                            ▼
          generator ◄─────────────────────────────────  generator → END
```

- **router** — phân loại intent: `rag` vs chitchat/out-of-scope.
- **retriever** (`app/rag/retriever.py`) — hybrid search: Qdrant dense vector (weight 0.7) + Neo4j graph BFS theo cạnh `NEXT_CHUNK`/`REFERENCES` (weight 0.3), sau đó cross-encoder rerank lấy top-5.
- **grader** — chấm điểm relevance; nếu `confidence_score < 0.3` và còn lượt retry (`MAX_RETRIES = 2`) → **rewriter** viết lại câu hỏi rồi retrieve lại.
- **generator** (`app/agents/generator.py`) — trả lời **chỉ** dựa trên context đã retrieve, kèm citation; nếu không tìm thấy → `"Not found in documents."`, trừ khi request bật `search_tool: true` (fallback DuckDuckGo, có cảnh báo minh bạch ở đầu câu trả lời).

### Ingestion pipeline (async qua Celery)

```
Upload file (PDF/DOCX/TXT)
   → S3 (raw file)  +  PostgreSQL (metadata)
   → Celery task (queue: ingestion)
       → extract → chunk (RecursiveCharacterTextSplitter, size=800, overlap=200)
       → embed (OpenAI text-embedding-3-small)
       → Qdrant (vector) + Neo4j (chunk nodes + NEXT_CHUNK/REFERENCES edges)
```

Celery task phải **idempotent** và **retry-safe**; upload API không bao giờ block chờ ingest xong.

### Data stores

| Store | Vai trò |
|---|---|
| PostgreSQL (Supabase Cloud) | users, documents, chunks, conversations, messages, citations, audit_logs |
| Qdrant Cloud | dense vector embeddings |
| Neo4j Aura | graph edges giữa các chunk (`NEXT_CHUNK`, `REFERENCES`) |
| AWS S3 (LocalStack ở local dev) | raw file gốc |
| Redis (Upstash Cloud) | Celery broker/result backend, rate limiting |

### LLM abstraction

Không bao giờ gọi OpenAI trực tiếp từ route/service/graph node — luôn qua factory:

```python
from app.llm.factory import get_llm
llm = get_llm()   # BaseLLM impl — hiện tại OpenAILLM; VLLMLLM cho migration local sau này
```

---

## Cấu trúc thư mục

```
Enterprise-Knowledge-RAG/
├── backend/                    # FastAPI + Celery + LangGraph service
│   ├── app/
│   │   ├── api/                 # routers: auth, chat, documents, admin, audit_logs
│   │   ├── services/             # business logic (auth, chat, document, web_search)
│   │   ├── repositories/         # DB query layer (user, document, conversation, audit_log)
│   │   ├── models/                # SQLAlchemy ORM (User, Document, Chunk, Conversation,
│   │   │                          #   Message, Citation, AuditLog, DocumentConversation)
│   │   ├── schemas/               # Pydantic request/response
│   │   ├── agents/                # LangGraph: graph.py, state.py, router/retriever/grader/
│   │   │                          #   rewriter/generator nodes
│   │   ├── rag/                   # HybridRetriever (Qdrant+Neo4j), graph_client, reranker
│   │   ├── ingestion/              # pipeline, chunker, embedder, structural_parser, graph_indexer
│   │   ├── connectors/             # nguồn tài liệu: pdf, confluence, base
│   │   ├── llm/                    # BaseLLM / OpenAILLM / VLLMLLM + factory
│   │   ├── auth/                   # RBAC
│   │   ├── analytics/              # usage tracker
│   │   ├── core/                   # config (Settings), security, rate_limit, dependencies
│   │   ├── db/                     # SQLAlchemy async session + base
│   │   ├── storage/                 # S3 client
│   │   ├── workers/                 # Celery app + tasks (ingestion, sync)
│   │   └── tests/                   # unit / integration / e2e (pytest)
│   ├── alembic/                  # DB migrations
│   ├── docker-compose.yml        # local infra: LocalStack S3, Neo4j
│   ├── docker-compose.prod.yml
│   └── pyproject.toml            # deps quản lý bằng uv
│
├── frontend/                   # Next.js 16 / React 19 app
│   ├── app/                      # App Router pages: chat (/), login, register,
│   │                              #   document-library, research-vault, work-history
│   ├── components/                # Sidebar, AuthGuard, theme-provider, ui/ (shadcn)
│   ├── lib/
│   │   ├── api.ts                  # API client (MOCK_MODE flag, JWT access/refresh)
│   │   ├── context.tsx              # global React state (auth, chat sessions, config)
│   │   └── mockRag.ts               # mock data khi MOCK_MODE=true
│   └── endpointAPIbe.json         # contract API backend mà frontend nhắm tới
│
├── .github/workflows/           # ci.yml (lint/test/typecheck), cd.yml (deploy)
├── dev.ps1                     # chạy API + Celery worker (+ frontend) cùng lúc, 1 cửa sổ
└── CLAUDE.md                   # quy ước & kiến trúc cho AI coding agent
```

---

## Bắt đầu nhanh

### Yêu cầu

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node.js + npm
- Docker (cho LocalStack S3 / Neo4j local, tuỳ chọn — Postgres/Redis/Qdrant mặc định trỏ cloud)

### Cài đặt

```bash
# Backend
cd backend
uv sync
cp .env.example .env      # điền DATABASE_URL, REDIS_URL, QDRANT_*, NEO4J_*, OPENAI_API_KEY...
uv run alembic upgrade head

# Frontend
cd ../frontend
npm install
```

### Chạy dev

Cách nhanh nhất — chạy API + Celery worker (và tuỳ chọn frontend) trong 1 cửa sổ, log gộp chung:

```powershell
.\dev.ps1              # API (:8000) + worker
.\dev.ps1 -Frontend    # + frontend (:3000)
```

Hoặc chạy tách từng service:

```bash
# Terminal 1 — API
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — Celery worker (bắt buộc để xử lý upload/ingest)
cd backend && uv run celery -A app.workers.celery_app worker -Q ingestion,sync --loglevel=info

# Terminal 3 — Frontend
cd frontend && npm run dev
```

Truy cập: Frontend `http://localhost:3000` · API docs `http://localhost:8000/docs` · Health `http://localhost:8000/health`

> Frontend hiện có `MOCK_MODE = false` trong `frontend/lib/api.ts` — đã gọi thẳng API thật, cần backend + worker chạy để dùng được (upload, chat, auth).

---

## Test, lint, format

```bash
# Backend (từ backend/)
uv run pytest                                    # toàn bộ test
uv run pytest app/tests/unit/ -v                 # chỉ unit
uv run ruff check app/ --fix && uv run ruff format app/
uv run mypy app/

# Frontend (từ frontend/)
npm run lint
npm run typecheck
npm run format
```

CI (`.github/workflows/ci.yml`) chạy lint/test/typecheck cho cả hai app trên mỗi PR; CD (`cd.yml`) deploy backend.

---

## Ghi chú

- `backend/CLAUDE.md` mô tả dự án ở giai đoạn khung sườn ban đầu (BGE-M3 local, MinIO) — đã **lỗi thời**, code hiện dùng OpenAI embeddings + AWS S3/LocalStack. Ưu tiên đọc source và [`CLAUDE.md`](CLAUDE.md) ở gốc repo.
- Mọi retrieval phải qua kiểm tra quyền theo tài liệu (JWT + RBAC, `backend/app/auth/rbac.py`); hành động được ghi audit log (`backend/app/models/audit_log.py`).
- Backend strictly async; tầng route mỏng — logic nghiệp vụ nằm ở `services/`, truy vấn DB ở `repositories/`.
