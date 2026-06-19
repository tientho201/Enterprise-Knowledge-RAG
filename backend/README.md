# Enterprise Knowledge RAG — Backend

Backend cho hệ thống RAG truy vấn văn bản pháp luật doanh nghiệp, sử dụng hybrid retrieval (Qdrant dense + Neo4j knowledge graph), LangGraph agents và REST API.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI (strictly async) |
| Database | PostgreSQL — Supabase Cloud |
| Task Queue | Celery + Redis — Upstash Cloud |
| Vector DB | Qdrant Cloud |
| Knowledge Graph | Neo4j Aura |
| Object Storage | MinIO (local) |
| LLM | OpenAI GPT-4o-mini |
| Embedding Model | BGE-M3 (local CPU/GPU) |
| Agents | LangChain + LangGraph |
| Observability | LangSmith |
| Package Manager | uv |
| Python | 3.11 |

---

## Cloud Services

| Service | Provider | URL |
|---|---|---|
| PostgreSQL | [Supabase](https://supabase.com) | `aws-0-ap-southeast-1.pooler.supabase.com` |
| Redis | [Upstash](https://console.upstash.com) | `nearby-aphid-150593.upstash.io` |
| Vector DB | [Qdrant Cloud](https://cloud.qdrant.io) | `eu-central-1-0.aws.cloud.qdrant.io` |
| Knowledge Graph | [Neo4j Aura](https://console.neo4j.io) | `0081b2d4.databases.neo4j.io` |
| Object Storage | MinIO (local Docker) | `localhost:9000` |

---

## Architecture

```
Người dùng
    ↓ HTTP/SSE
FastAPI REST API  (/api/v1)
    ↓
LangGraph Agent
    ├── Router       — phân loại: RAG / chitchat / out-of-scope
    ├── Retriever    — hybrid search:
    │       ├── Dense  (Qdrant BGE-M3, top-20, weight 0.7)
    │       └── Graph  (Neo4j BFS depth≤2, weight 0.3)
    │               ├── NEXT_CHUNK  — điều liền kề
    │               └── REFERENCES  — "Điều X tham chiếu Điều Y"
    ├── Grader       — đánh giá độ liên quan
    ├── Rewriter     — viết lại query nếu cần
    └── Generator    — sinh câu trả lời có citation
    ↓
OpenAI GPT-4o-mini
```

### Ingestion Pipeline

```
Upload file (PDF/DOCX/TXT)
    → MinIO (lưu raw file)
    → PostgreSQL (document metadata)
    → Celery task (async)
        → Extract text
        → Chunk (size=800, overlap=200)
        → Embed (BGE-M3 local)
        → Qdrant (dense vectors)
        → Neo4j (chunk nodes + NEXT_CHUNK + REFERENCES edges)
```

---

## Cài đặt

### 1. Clone & cài dependencies

```bash
uv sync
```

### 2. Cấu hình môi trường

```bash
cp .env.example .env
```

Điền các giá trị bắt buộc trong `.env`:

| Biến | Lấy ở đâu |
|---|---|
| `DATABASE_URL` | Supabase → Settings → Database → Connection string (URI, port 6543) |
| `REDIS_URL` | Upstash → Database → Redis URL (dạng `rediss://`) |
| `CELERY_BROKER_URL` | Giống `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | Giống `REDIS_URL` |
| `QDRANT_URL` | Qdrant Cloud → Cluster → Overview |
| `QDRANT_API_KEY` | Qdrant Cloud → Cluster → API Keys |
| `NEO4J_URI` | Neo4j Aura → Instance → Connect (dạng `neo4j+s://`) |
| `NEO4J_USER` | Neo4j Aura → username |
| `NEO4J_PASSWORD` | Neo4j Aura → password |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |

### 3. Khởi động MinIO (object storage local)

```bash
# Chỉ cần MinIO — Redis/Neo4j/Qdrant/Postgres đều đã ở cloud
docker-compose up -d minio
```

> Nếu muốn chạy Neo4j local thay vì Aura:
> ```bash
> docker-compose up -d neo4j
> # Cập nhật .env: NEO4J_URI=bolt://localhost:7687, NEO4J_PASSWORD=neo4j_password
> ```

### 4. Chạy database migrations

```bash
uv run alembic upgrade head
```

---

## Câu lệnh chạy

### API Server (FastAPI)

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Truy cập:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health:** http://localhost:8000/health

### Celery Worker (xử lý ingestion)

```bash
# Terminal riêng
uv run celery -A app.workers.celery_app worker --loglevel=info -Q ingestion,sync
```

### Celery Beat (scheduler — optional)

```bash
uv run celery -A app.workers.celery_app beat --loglevel=info
```

### Flower (monitor Celery tasks — optional)

```bash
uv run celery -A app.workers.celery_app flower --port=5555
# Truy cập: http://localhost:5555
```

---

## API Endpoints

### Auth

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Đăng ký tài khoản |
| `POST` | `/api/v1/auth/login` | Đăng nhập, nhận JWT |
| `GET` | `/api/v1/auth/me` | Thông tin user hiện tại |

### Chat

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/v1/chat` | Truy vấn RAG (body: `{message, conversation_id?}`) |
| `GET` | `/api/v1/chat/history` | Danh sách hội thoại |
| `GET` | `/api/v1/chat/{id}` | Chi tiết hội thoại + messages |
| `DELETE` | `/api/v1/chat/{id}` | Xóa hội thoại |

### Documents

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/v1/documents/upload` | Upload tài liệu (PDF/DOCX/TXT) |
| `GET` | `/api/v1/documents` | Danh sách tài liệu |
| `GET` | `/api/v1/documents/{id}` | Chi tiết tài liệu |
| `DELETE` | `/api/v1/documents/{id}` | Xóa tài liệu |
| `POST` | `/api/v1/documents/reindex` | Re-index tài liệu |

### Admin

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/api/v1/admin/dashboard` | Thống kê tổng quan |
| `GET` | `/api/v1/admin/jobs` | Danh sách Celery jobs |

---

## Development

```bash
# Lint
uv run ruff check app/

# Auto-fix lint
uv run ruff check app/ --fix

# Format
uv run ruff format app/

# Type check
uv run mypy app/

# Unit tests
uv run pytest app/tests/unit/ -v

# Integration tests
uv run pytest app/tests/integration/ -v

# Tất cả tests với coverage
uv run pytest --cov=app --cov-report=html
```

---

## Database Migrations (Alembic)

```bash
# Tạo migration mới
uv run alembic revision --autogenerate -m "mô tả thay đổi"

# Chạy tất cả migrations
uv run alembic upgrade head

# Rollback 1 bước
uv run alembic downgrade -1

# Xem lịch sử
uv run alembic history
```

---

## Docker (Production)

```bash
# Build image
docker build -t rag-backend .

# Chạy toàn bộ stack production
docker-compose -f docker-compose.prod.yml up -d

# Xem logs
docker-compose -f docker-compose.prod.yml logs -f api
docker-compose -f docker-compose.prod.yml logs -f worker
```

---

## Cấu trúc thư mục

```
backend/
├── app/
│   ├── api/           # FastAPI routers (thin — HTTP only)
│   ├── agents/        # LangGraph graph + nodes
│   ├── core/          # Config, security, dependencies
│   ├── db/            # SQLAlchemy session + base
│   ├── ingestion/     # Pipeline, chunker, embedder, graph_indexer
│   ├── llm/           # LLM abstraction (OpenAI / vLLM)
│   ├── models/        # SQLAlchemy ORM models
│   ├── rag/           # HybridRetriever (Qdrant + Neo4j), reranker
│   ├── repositories/  # DB query layer
│   ├── schemas/       # Pydantic request/response models
│   ├── services/      # Business logic
│   ├── storage/       # MinIO client
│   ├── workers/       # Celery app + tasks
│   └── tests/
│       ├── unit/
│       └── integration/
├── alembic/           # DB migrations
├── docker-compose.yml       # Dev: MinIO (+ Neo4j local option)
├── docker-compose.prod.yml  # Prod: API, worker, beat, Redis, Neo4j
├── Dockerfile
├── pyproject.toml
└── .env.example
```
