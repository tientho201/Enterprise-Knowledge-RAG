# Enterprise Knowledge RAG — Backend

Backend cho hệ thống RAG doanh nghiệp với ingestion pipeline, hybrid retrieval, LangGraph agents và REST API.

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI (async) |
| Database | PostgreSQL + SQLAlchemy |
| Task Queue | Celery + Redis |
| Vector DB | Qdrant |
| Object Storage | MinIO |
| LLM | OpenAI GPT-4o-mini (Phase 1) |
| Embedding | BGE-M3 (local) |
| Agents | LangChain + LangGraph |

## Cloud Services

| Service | Provider | Mô tả |
|---|---|---|
| PostgreSQL | [Supabase](https://supabase.com) | Managed Postgres, free tier 500MB |
| Vector DB | [Qdrant Cloud](https://cloud.qdrant.io) | Managed Qdrant, free tier 1GB |
| Object Storage | MinIO (local) / Supabase Storage | Raw files |
| Cache / Queue | Redis (local) | Celery broker |

## Quick Start

### 1. Tạo cloud services

**Supabase:**
1. Tạo project tại https://supabase.com
2. Vào **Settings → Database → Connection string** → chọn tab **URI**
3. Copy URI dạng: `postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres`
4. Thay `postgresql://` → `postgresql+asyncpg://` để dùng async driver

**Qdrant Cloud:**
1. Tạo cluster tại https://cloud.qdrant.io
2. Vào cluster → **API Keys** → tạo key mới
3. Copy **Cluster URL** và **API Key**

### 2. Setup môi trường

```bash
cp .env.example .env
# Điền DATABASE_URL (Supabase) và QDRANT_URL + QDRANT_API_KEY (Qdrant Cloud)

uv sync
```

### 3. Khởi động infrastructure local

```bash
# Chỉ cần Redis + MinIO (Postgres và Qdrant đã ở cloud)
docker-compose up -d
```

### 4. Chạy migrations

```bash
uv run alembic upgrade head
```

### 4. Chạy server

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### 5. Chạy Celery worker

```bash
uv run celery -A app.workers.celery_app worker --loglevel=info -Q ingestion,sync
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Đăng ký |
| POST | `/api/v1/auth/login` | Đăng nhập |
| GET | `/api/v1/auth/me` | Thông tin user hiện tại |
| POST | `/api/v1/chat` | Chat với RAG agent |
| GET | `/api/v1/chat/history` | Lịch sử chat |
| POST | `/api/v1/documents/upload` | Upload tài liệu |
| GET | `/api/v1/documents` | Danh sách tài liệu |
| GET | `/api/v1/admin/dashboard` | Dashboard (admin) |

## Architecture

```
FastAPI REST API
    ↓
LangGraph Agent (Router → Retriever → Grader → [Rewriter] → Generator)
    ↓
Hybrid Retrieval: BGE-M3 Dense (Qdrant) + BM25 Sparse
    ↓
Cross-Encoder Re-ranking
    ↓
OpenAI GPT-4o-mini (via LLM abstraction layer)
```

## Development

```bash
# Lint
uv run ruff check app/

# Format
uv run ruff format app/

# Tests
uv run pytest app/tests/unit/ -v

# Type check
uv run mypy app/
```
