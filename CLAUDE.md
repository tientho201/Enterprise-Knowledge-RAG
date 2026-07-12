# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

Monorepo with two independent apps:

- `backend/` — FastAPI + Celery RAG service (Python 3.11, managed by **uv**). Has its own detailed `backend/CLAUDE.md` and `backend/README.md`.
- `frontend/` — Next.js 16 / React 19 app (TypeScript, Tailwind 4, shadcn/ui, managed by **npm**).

> **Note on `backend/CLAUDE.md`:** parts of it are stale (describes the project as an empty skeleton, lists BGE-M3 local embeddings / MinIO / BM25). The code has since diverged — see "Current Reality" below. Trust the source files and this document over that file.

## Commands

### Backend (run from `backend/`)

```bash
uv sync                                                          # install deps (incl. dev via groups)
uv run uvicorn app.main:app --reload --port 8000                # API server → :8000 (/docs, /health)
uv run celery -A app.workers.celery_app worker -Q ingestion,sync --loglevel=info   # worker (needed for uploads)
uv run pytest                                                    # all tests
uv run pytest app/tests/unit/test_chunker.py::test_name -v      # single test
uv run ruff check app/ --fix && uv run ruff format app/         # lint + format
uv run mypy app/                                                 # type check
uv run alembic upgrade head                                     # apply DB migrations
uv run alembic revision --autogenerate -m "msg"                # new migration
```

### Frontend (run from `frontend/`)

```bash
npm install
npm run dev          # dev server → :3000
npm run build
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm run format       # prettier
```

### Local infrastructure

`backend/docker-compose.yml` provisions local-only deps (LocalStack S3, Neo4j). Postgres/Redis/Qdrant point at cloud by default; override in `backend/.env` (copy from `backend/.env.example`).

## Architecture — Big Picture

Request flow: **Frontend (Next.js) → FastAPI `/api/v1` → LangGraph agent → LLM (OpenAI GPT-4o-mini)**, with data spread across Postgres (metadata), Qdrant (vectors), Neo4j (graph edges), S3 (raw files), Redis (Celery broker).

### Backend layering (enforced convention)

`api/` (thin HTTP routers) → `services/` (business logic) → `repositories/` (DB queries) → `models/` (SQLAlchemy). Everything is **strictly async**. Auth and DB sessions come via FastAPI dependency injection (`core/dependencies.py`). Request/response shapes live in `schemas/` (Pydantic).

### LangGraph agent (`app/agents/`)

Graph defined in `agents/graph.py`, shared state contract in `agents/state.py`:

```
START → router → (rag?) → retriever → grader → (low confidence & retries left?) → rewriter ↺ retriever
                    ↓ (chitchat/out-of-scope)                    ↓ (ok)
                 generator ← ─────────────────────────────────── generator → END
```

- **router** classifies intent (`rag` / other).
- **retriever** (`rag/retriever.py`) does hybrid search: dense Qdrant (weight 0.7) + Neo4j graph BFS over `NEXT_CHUNK` / `REFERENCES` edges (weight 0.3), then cross-encoder rerank to top-5.
- **grader** scores relevance; if `confidence_score < 0.3` and `retry_count < MAX_RETRIES (2)`, **rewriter** reformulates and re-retrieves.
- **generator** (`agents/generator.py`) answers **only** from retrieved context with citations; falls back to `"Not found in documents."` unless the request opts into web-search fallback (`search_tool: true`, DuckDuckGo via `services/web_search.py`, prefixed with a transparency warning).

### Ingestion pipeline (`app/ingestion/`, async via Celery)

Upload → S3 (raw file) + Postgres (metadata) → Celery task → extract → chunk (`RecursiveCharacterTextSplitter`, size 800 / overlap 200) → embed → write vectors to Qdrant + graph nodes/edges to Neo4j (`ingestion/graph_indexer.py`). Celery tasks must be **idempotent and retry-safe**; upload must never block.

### LLM abstraction (critical rule)

Never call OpenAI directly from routes, services, or graph nodes. Go through the factory:

```python
from app.llm.factory import get_llm
llm = get_llm()   # BaseLLM impl (OpenAILLM now; VLLMLLM planned for local migration)
```

## Current Reality vs. Older Docs

These reflect the actual code and differ from `backend/CLAUDE.md`/`README.md` prose:

- **Embeddings:** OpenAI `text-embedding-3-small` (`ingestion/embedder.py`), *not* BGE-M3 local — despite `FlagEmbedding`/`torch` still being in `pyproject.toml`.
- **Object storage:** AWS S3 via `boto3`; LocalStack (`http://localhost:4566`) for local dev, real S3 in prod (empty `AWS_S3_ENDPOINT_URL`). Not MinIO.
- **Retrieval sparse leg:** Neo4j knowledge-graph traversal, not BM25.
- Tunable retrieval/chunking knobs live in `app/core/config.py` (`DENSE_TOP_K`, `GRAPH_WEIGHT`, `RERANK_TOP_K`, `CHUNK_SIZE`, etc.).

## Frontend Notes

- `frontend/lib/api.ts` has **`MOCK_MODE = true`** — the UI currently bypasses the backend and uses `lib/mockRag.ts`. Set it to `false` to hit the real API at `http://localhost:8000`. It also handles JWT access/refresh token storage in `localStorage`.
- `endpointAPIbe.json` documents the backend contract the frontend targets; `lib/context.tsx` holds global React state.

## Conventions

- Backend routes stay thin; put logic in services, DB access in repositories. All I/O async. Validate every request/response with Pydantic. Soft-delete via `deleted_at` rather than hard deletes. Use Alembic for all schema changes.
- Every retrieval must enforce document-level permissions (JWT + RBAC in `app/auth/rbac.py`); actions are audit-logged (`models/audit_log.py`).
- Some code comments and docs are in Vietnamese; matching the surrounding language is fine.
