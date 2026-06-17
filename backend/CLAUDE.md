# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Enterprise Knowledge RAG — Backend**

Backend cho hệ thống RAG doanh nghiệp với ingestion pipeline, hybrid retrieval, LangGraph agents và REST API.

> **Trạng thái hiện tại (Jun 2026):** Dự án đang ở giai đoạn **khởi tạo**. Cấu trúc `app/` chưa được tạo. `pyproject.toml` chưa có dependency nào. `main.py` là placeholder đơn giản. Xem phần "Current Directory Structure" để biết chính xác những gì đã tồn tại.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI (strictly async) |
| ORM | SQLAlchemy |
| Database | PostgreSQL |
| Task Queue | Celery + Redis |
| Vector DB | Qdrant |
| Object Storage | MinIO |
| LLM (Phase 1) | OpenAI GPT-4o-mini |
| Embedding Model | BGE-M3 (local only) |
| AI / Agents | LangChain, LangGraph |
| Observability | LangSmith, Prometheus, Grafana |
| Package Manager | **uv** |
| Python Version | **3.11** (xem `.python-version`) |

---

## Common Commands

### Environment Setup

```bash
# Khởi tạo virtual environment và cài dependencies
uv sync

# Thêm dependency mới (ví dụ: fastapi)
uv add fastapi

# Thêm dev dependency
uv add --dev pytest ruff mypy

# Xem danh sách packages đã cài
uv pip list
```

> **Lưu ý:** `pyproject.toml` hiện tại có `dependencies = []` — chưa có package nào được cài. Cần chạy `uv add <packages>` trước khi sử dụng bất kỳ lệnh nào bên dưới (trừ `uv run python main.py`).

### Run the Application

```bash
# Chạy placeholder hiện tại (in "Hello from backend!")
uv run python main.py

# Chạy FastAPI dev server (sau khi app/ được xây dựng và fastapi được cài)
uv run fastapi dev app/main.py

# Chạy với uvicorn trực tiếp
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run Tests

```bash
# Chạy toàn bộ test suite (yêu cầu: uv add --dev pytest pytest-asyncio httpx)
uv run pytest

# Chạy với verbose output
uv run pytest -v

# Chạy một file test cụ thể
uv run pytest app/tests/test_auth.py -v

# Chạy một test case cụ thể
uv run pytest app/tests/test_auth.py::test_login -v

# Chạy với coverage report
uv run pytest --cov=app --cov-report=html

# Chạy chỉ unit tests
uv run pytest app/tests/unit/ -v

# Chạy chỉ integration tests
uv run pytest app/tests/integration/ -v
```

### Lint & Format

```bash
# Lint với ruff (yêu cầu: uv add --dev ruff)
uv run ruff check .

# Auto-fix lint errors
uv run ruff check . --fix

# Format code với ruff
uv run ruff format .

# Kiểm tra format không sửa (CI mode)
uv run ruff format . --check

# Type check với mypy (yêu cầu: uv add --dev mypy)
uv run mypy app/
```

### Database Migrations (Alembic)

```bash
# Tạo migration mới
uv run alembic revision --autogenerate -m "description"

# Chạy migrations lên phiên bản mới nhất
uv run alembic upgrade head

# Rollback migration một bước
uv run alembic downgrade -1

# Rollback toàn bộ
uv run alembic downgrade base

# Xem lịch sử migration
uv run alembic history

# Xem trạng thái hiện tại
uv run alembic current
```

### Celery Workers

```bash
# Chạy Celery worker
uv run celery -A app.workers.celery_app worker --loglevel=info

# Chạy Celery beat (scheduler)
uv run celery -A app.workers.celery_app beat --loglevel=info

# Monitor với Flower
uv run celery -A app.workers.celery_app flower

# Purge tất cả task trong queue
uv run celery -A app.workers.celery_app purge
```

### Docker

```bash
# Khởi động toàn bộ infrastructure (PostgreSQL, Redis, Qdrant, MinIO)
docker-compose up -d

# Khởi động với rebuild image
docker-compose up --build

# Dừng tất cả services
docker-compose down

# Xem logs
docker-compose logs -f

# Xem logs của service cụ thể
docker-compose logs -f backend
```

---

## Current Directory Structure

Đây là cấu trúc **thực tế hiện tại** (không phải planned):

```
backend/
├── .claude/                          # Claude Code configuration
│   ├── hooks/                        # Automation hooks (placeholder chưa config)
│   │   ├── custom-hook.json          # Custom hook template
│   │   ├── format-on-edit.json       # Format on edit (chưa set command)
│   │   ├── lint-on-edit.json         # Lint on edit (chưa set command)
│   │   └── run-tests-on-edit.json    # Test on edit (chưa set command)
│   └── skills/                       # Claude skill definitions
│       ├── code-review/
│       │   └── SKILL.md
│       ├── continuous-integration/
│       │   └── SKILL.md
│       ├── deployment/
│       │   └── SKILL.md
│       ├── run-next-app/
│       │   ├── driver.mjs
│       │   └── SKILL.md
│       └── testing/
│           └── SKILL.md
├── .llm/
│   └── prd.md                        # Product Requirements Document (full spec)
├── .gitignore
├── .python-version                   # Python 3.11
├── CLAUDE.md                         # This file
├── main.py                           # Entry point placeholder (chỉ in Hello World)
├── pyproject.toml                    # uv project config — hiện tại KHÔNG có dependencies
└── README.md                         # Empty
```

> **Quan trọng:** Thư mục `app/`, `alembic/`, `docker-compose.yml`, `Dockerfile`, `.env.example` **chưa tồn tại**. Tất cả là planned structure cần được tạo.

---

## Planned Application Structure (theo PRD)

```
backend/
├── app/
│   ├── api/                          # FastAPI routers (thin — HTTP only)
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── documents.py
│   │   └── admin.py
│   ├── core/                         # Config, settings, security
│   │   ├── __init__.py
│   │   ├── config.py                 # BaseSettings từ .env
│   │   ├── security.py               # JWT utils
│   │   └── dependencies.py           # FastAPI dependency injection
│   ├── db/                           # Database session, base model
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── session.py
│   ├── models/                       # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── chunk.py
│   │   ├── conversation.py
│   │   ├── message.py
│   │   ├── citation.py
│   │   └── audit_log.py
│   ├── schemas/                      # Pydantic schemas (request/response)
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── chat.py
│   │   └── document.py
│   ├── repositories/                 # DB logic layer
│   │   ├── __init__.py
│   │   ├── user_repo.py
│   │   ├── document_repo.py
│   │   └── conversation_repo.py
│   ├── services/                     # Business logic layer
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   └── chat_service.py
│   ├── workers/                      # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   └── tasks/
│   │       ├── ingestion.py          # extract, chunk, embed
│   │       └── sync.py               # confluence, slack, google drive
│   ├── rag/                          # Retrieval pipeline
│   │   ├── __init__.py
│   │   ├── retriever.py              # Dense (Qdrant) + BM25 + Hybrid merge
│   │   └── reranker.py               # Cross-encoder re-ranking
│   ├── agents/                       # LangGraph agent graph
│   │   ├── __init__.py
│   │   ├── graph.py                  # Graph definition: START → ... → END
│   │   ├── state.py                  # Typed state contract
│   │   ├── router.py
│   │   ├── retriever.py
│   │   ├── grader.py
│   │   ├── rewriter.py
│   │   └── generator.py
│   ├── ingestion/                    # Document ingestion pipeline
│   │   ├── __init__.py
│   │   ├── pipeline.py               # Upload → Store → Extract → Chunk → Embed → Save
│   │   ├── chunker.py                # RecursiveCharacterTextSplitter
│   │   └── embedder.py               # BGE-M3 local embeddings
│   ├── llm/                          # LLM abstraction layer (CRITICAL)
│   │   ├── __init__.py
│   │   ├── base.py                   # BaseLLM interface
│   │   ├── openai_llm.py             # OpenAILLM implementation
│   │   ├── vllm_llm.py               # VLLMLLM implementation (Phase 2)
│   │   └── factory.py                # get_llm() factory
│   ├── storage/                      # MinIO integration
│   │   ├── __init__.py
│   │   └── minio_client.py
│   ├── connectors/                   # Source connectors
│   │   ├── __init__.py
│   │   ├── base.py                   # load(), sync(), diff()
│   │   ├── pdf.py
│   │   ├── docx.py
│   │   └── confluence.py
│   ├── auth/                         # JWT + RBAC
│   │   ├── __init__.py
│   │   └── rbac.py
│   ├── analytics/                    # Usage tracking, latency, hallucination metrics
│   │   ├── __init__.py
│   │   └── tracker.py
│   ├── tests/                        # pytest test suite
│   │   ├── conftest.py
│   │   ├── unit/
│   │   │   ├── test_chunker.py
│   │   │   ├── test_embedder.py
│   │   │   └── test_services.py
│   │   ├── integration/
│   │   │   ├── test_ingestion.py
│   │   │   ├── test_retrieval.py
│   │   │   └── test_agent.py
│   │   └── e2e/
│   │       ├── test_upload_flow.py
│   │       └── test_chat_flow.py
│   └── main.py                       # FastAPI app factory
├── alembic/                          # DB migrations
│   ├── versions/
│   ├── env.py
│   └── alembic.ini
├── docker-compose.yml                # PostgreSQL, Redis, Qdrant, MinIO
├── Dockerfile
├── .env.example                      # Template biến môi trường
├── .env                              # KHÔNG commit — trong .gitignore
├── pyproject.toml
└── main.py
```

---

## High-Level Architecture

```
Frontend (Next.js)
    ↓ HTTP / SSE
FastAPI (REST API)
    ↓
LangGraph Agent Graph
    ↓
Hybrid Retrieval (Qdrant dense + BM25 sparse)
    ↓
Cross-Encoder Re-ranker
    ↓
LLM (OpenAI GPT-4o-mini → future: Llama-3 via vLLM)
```

### Storage

| Store | Purpose |
|---|---|
| PostgreSQL | Users, roles, document metadata, conversation history, audit logs |
| Qdrant | Vector embeddings (dense search) |
| MinIO | Raw uploaded files (PDF, DOCX, ...) |
| Redis | Celery broker + cache |

---

## LLM Abstraction Layer (Critical)

**KHÔNG BAO GIỜ** gọi OpenAI trực tiếp trong routes, services, hay graph nodes.

```python
# Đúng — dùng factory
from app.llm.factory import get_llm
llm = get_llm()  # trả về BaseLLM implementation

# Sai — gọi thẳng
from openai import OpenAI
client = OpenAI()  # KHÔNG làm thế này
```

Interface:

```
BaseLLM
  ├── OpenAILLM   (Phase 1 — hiện tại)
  ├── VLLMLLM     (Phase 2 — future)
  └── OllamaLLM   (development)
```

---

## LangGraph Agent Workflow

```
START
  ↓
Router          — phân loại query (RAG / chitchat / out-of-scope)
  ↓
Retriever       — hybrid search: dense (Qdrant) + sparse (BM25)
  ↓
Re-ranker       — cross-encoder, top-5 từ top-20
  ↓
Grader          — đánh giá relevance của retrieved docs
  ↓
Rewriter (opt.) — rewrite query nếu grader reject
  ↓
Generator       — tạo câu trả lời có citation
  ↓
END
```

### LangGraph State Contract

```python
class AgentState(TypedDict):
    query: str
    intent: str
    rewritten_query: Optional[str]
    dense_results: list
    sparse_results: list
    merged_results: list
    reranked_results: list
    citations: list
    final_answer: Optional[str]
    confidence_score: float
```

---

## Ingestion Pipeline

```
Upload file
  → MinIO (lưu raw file)
  → PostgreSQL (tạo metadata record)
  → Celery queue (dispatch task)
      ↓
  Extract text (PDF/DOCX/Confluence/Slack)
      ↓
  Chunking (RecursiveCharacterTextSplitter, size=800, overlap=200)
      ↓
  Embedding (BGE-M3, local, batched, normalized)
      ↓
  Qdrant (lưu vectors)
```

---

## Retrieval Pipeline

```
User Query
  → Embedding (BGE-M3 local)
  → Dense Search (Qdrant, top-20)    ─┐
  → Sparse Search (BM25, top-20)     ─┤ Hybrid merge (dense 0.7 + sparse 0.3)
                                      ↓
                                    Merged top-20
                                      ↓
                                    Cross-Encoder Re-rank
                                      ↓
                                    Top-5 context → Generator
```

---

## API Endpoints

### Auth
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

### Chat
- `POST /chat`
- `GET /chat/history`
- `GET /chat/{id}`
- `DELETE /chat/{id}`

### Documents
- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{id}`
- `DELETE /documents/{id}`
- `POST /documents/reindex`

### Admin
- `GET /admin/dashboard`
- `GET /admin/analytics`
- `GET /admin/jobs`

---

## Database Schema

**users**: `id, email, password_hash, role, created_at`

**documents**: `id, name, type, status, version, source, created_at, deleted_at` *(soft delete)*

**chunks**: `id, document_id, content, chunk_index, token_count, embedding_model`

**citations**: `id, chunk_id, page_number, section_title, source_link`

**conversations**: `id, user_id, title, created_at`

**messages**: `id, conversation_id, role, content, created_at`

**audit_logs**: `id, user_id, action, metadata, created_at`

---

## Celery Tasks

| Task | Description |
|---|---|
| `extract_document` | Extract text từ file (PDF, DOCX, ...) |
| `chunk_document` | Chia nhỏ document thành chunks |
| `embed_document` | Tạo embeddings và lưu vào Qdrant |
| `sync_confluence` | Sync nội dung từ Confluence |
| `sync_slack` | Sync messages từ Slack |
| `reindex_document` | Reindex document vào vector store |
| `delete_document_vectors` | Xóa vectors khỏi Qdrant |

**Retry config:** `max_retries = 3`, `retry_backoff = True`

---

## External Services (Infrastructure)

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL | 5432 | Relational data |
| Redis | 6379 | Celery broker & cache |
| Qdrant | 6333 | Vector store |
| MinIO | 9000 | Object storage |

---

## Coding Rules

### Backend Structure Rules
1. **Routes thin** — chỉ xử lý HTTP (parse request, return response)
2. **Business logic** → `services/`
3. **DB logic** → `repositories/`
4. **Strict async/await** — không có sync DB calls
5. **FastAPI dependency injection** cho auth, DB session
6. **Không gọi OpenAI trực tiếp** — dùng `get_llm()` factory
7. **Pydantic validation** bắt buộc cho tất cả request/response

### Chunking Rules
- Dùng `RecursiveCharacterTextSplitter`
- `chunk_size = 800`, `chunk_overlap = 200`
- Preserve semantic boundaries, tránh split legal clauses

### Embedding Rules
- Model: **BGE-M3** — chạy local only
- Batch embeddings
- Normalize embeddings trước khi lưu vào Qdrant

### Generator Rules
1. Answer ONLY từ retrieved context
2. Nếu context không đủ: trả về `"Not found in documents."`
3. Mọi answer PHẢI có citations (`document_id`, `chunk_id`, `page_number`)
4. KHÔNG hallucinate, KHÔNG invent citations

### Database Rules
- Dùng **Alembic** cho migrations
- Không manual schema changes trong production
- Dùng **soft delete** (`deleted_at` field)

### Document Versioning Rules
1. Mỗi document phải có version number
2. Re-upload tạo version mới
3. Old vectors phải được archived hoặc deleted
4. Preserve metadata history

### Security Rules
- JWT Authentication cho mọi API
- RBAC Authorization (role-based)
- Document-level access control
- Audit logging cho mọi actions
- Mỗi retrieval phải validate permissions

### Celery Task Rules
- Tasks phải **idempotent**
- Tasks phải **retry-safe**
- Upload KHÔNG được blocking

---

## Security & Observability

**Security:**
- JWT authentication
- RBAC (Role-Based Access Control)
- Protected APIs via FastAPI dependencies
- Audit logs cho mọi actions

**Observability:**
- Track: latency, token usage, retrieval precision, hallucination rate, failed jobs
- Tools: LangSmith · Prometheus · Grafana

---

## Non-Functional Requirements

| Requirement | Target |
|---|---|
| Response time | < 5 seconds |
| Scale | 100k+ documents |
| Reliability | Retry failed Celery tasks (max 3, backoff) |
| Security | RBAC enforced trên mọi API |
| Architecture | Modular, testable, replaceable LLM |
| I/O | Tất cả I/O phải async |
| Streaming | Hỗ trợ SSE streaming |

---

## Phase Roadmap

### Phase 1 — MVP (Hiện tại)
- OpenAI GPT-4o-mini cho inference
- BGE-M3 local embeddings
- FastAPI + Celery + LangGraph
- Hybrid retrieval + re-ranking
- JWT + RBAC

### Phase 2 — Local LLM Migration
- Thay OpenAI bằng Llama-3-8B-Instruct (AWQ/GPTQ)
- Inference server: vLLM (production) / Ollama (development)
- Zero business logic changes — chỉ swap LLM provider
