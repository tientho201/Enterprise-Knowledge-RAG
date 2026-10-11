# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

Monorepo with two independent apps:

- `backend/` — FastAPI + Celery RAG service (Python 3.11, managed by **uv**). Has its own detailed `backend/CLAUDE.md` and `backend/README.md`.
- `frontend/` — Next.js 16 / React 19 app (TypeScript, Tailwind 4, shadcn/ui, managed by **npm**).

`backend/CLAUDE.md` is the detailed backend reference (endpoints, retrieval, Celery tasks, known gaps). If a doc disagrees with the source, trust the source.

## Commands

### Backend (run from `backend/`)

```bash
uv sync --extra dev                                              # install deps + dev tools (pytest/ruff/mypy are the optional `dev` extra)
uv run uvicorn app.main:app --reload --port 8000                # API server → :8000 (/docs, /health)
uv run celery -A app.workers.celery_app worker -Q ingestion,sync --loglevel=info   # worker (needed for uploads); on Windows add --pool=solo (as dev.ps1 does)
uv run pytest                                                    # all tests — touches real services, see warning below
uv run pytest app/tests/unit/test_chunker.py::test_name -v      # single test
uv run ruff check app/ --fix && uv run ruff format app/         # lint + format
uv run mypy app/                                                 # type check
uv run alembic upgrade head                                     # apply DB migrations
uv run alembic revision --autogenerate -m "msg"                # new migration
```

**Test warning (not fixed yet):** a bare `uv run pytest` (or all of `app/tests/unit/`) touches real services — at least `app/tests/unit/test_s3.py` (module-level script: collecting it uploads to real S3 with the credentials in the environment) and `test_live_api.py` (calls `http://127.0.0.1:8000`). Run specific test files instead; see `backend/CLAUDE.md`.

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

`backend/docker-compose.yml` provisions local-only deps (Redis, Neo4j, LocalStack S3). Postgres and Qdrant are not in it; set them in `backend/.env` (copy from `backend/.env.example`).

## Architecture — Big Picture

Request flow: **Frontend (Next.js) → FastAPI `/api/v1` → LangGraph agent → LLM (OpenAI GPT-4o-mini)**, with data spread across Postgres (metadata), Qdrant (vectors), Neo4j (graph edges), S3 (raw files), Redis (Celery broker/result backend, token blacklist, OTP, rate limiting, response cache).

### Backend layering (enforced convention)

`api/` (thin HTTP routers) → `services/` (business logic) → `repositories/` (DB queries) → `models/` (SQLAlchemy). Everything is **strictly async**. Auth and DB sessions come via FastAPI dependency injection (`core/dependencies.py`). Request/response shapes live in `schemas/` (Pydantic).

### LangGraph agent (`app/agents/`)

Graph defined in `agents/graph.py`, shared state contract in `agents/state.py`:

```
START → guardrail → (blocked?) → generator → END
            ↓
         router → (not rag?) → generator
            ↓ (rag)
   contextualizer → retriever → grader → (ok) → generator
                        ↑          ↓ (low confidence & retries left)
                        └────── rewriter
```

- **guardrail** is a regex prompt-injection filter (no LLM call); a hit sets `intent = "blocked"`.
- **router** classifies intent (`rag` / other).
- **contextualizer** runs once on the way in (not in the rewriter loop): with non-empty `history`, one LLM call rewrites a follow-up into a standalone `rewritten_query`.
- **retriever** (`agents/retriever.py` over `rag/retriever.py`): per pass, one dense Qdrant call (weight 0.7) + at most one Neo4j graph expansion over `NEXT_CHUNK` / `REFERENCES` edges (weight 0.3), combined by `HybridRetriever.merge()`; `search_mode="advanced"` adds one more Neo4j query (`graph_augmented_search`). The node must not call `retrieve()`, which re-runs both legs.
- **grader** cuts to `RERANK_TOP_K` (10; request `top_k` overrides) with `HybridScoreReranker` — a plain sort by hybrid score, **not** a cross-encoder — then scores relevance; if `confidence_score < 0.3` and `retry_count < MAX_RETRIES (2)`, **rewriter** reformulates and re-retrieves.
- **generator** (`agents/generator.py`) answers **only** from retrieved context with citations. The LLM is told to reply `"Not found in documents."` when context is insufficient; `generator_node` normalizes that to `"Không tìm thấy trong tài liệu."`, unless the request opts into web-search fallback (`search_tool: true`, DuckDuckGo via `services/web_search.py`, answer prefixed with a transparency warning; same Vietnamese string if the web finds nothing either). The token-streaming path of `/chat/stream` forwards LLM tokens verbatim, so the English string can surface there.

### Chat request behaviour

- `POST /chat/stream` is the SSE variant of `POST /chat`: it runs `build_retrieval_graph()` (stops before the generator) and streams tokens outside the graph.
- `search_mode`: `vector` is dense-only (never touches Neo4j); `keyword` currently behaves exactly like hybrid; `advanced` is plan-gated (Pro or admin, `core/plan_gate.py`), as is `/graph/*`. Self-upgrade to Pro (`POST /auth/plan`) needs `SELF_SERVICE_PLAN_ENABLED` (default off).
- Disabled documents (`is_active=false`) are excluded from RAG via `excluded_document_ids`, for admins too. **Fail-closed:** if that lookup fails, retrieval never runs — `POST /chat` errors, `/chat/stream` emits an SSE `error` event.
- History: up to `CHAT_HISTORY_MAX_MESSAGES` (6; `0` = off) earlier messages go into `AgentState.history` — **not** for a new conversation or when `search_tool` is on. Fail-safe: a load error means the turn runs without history.

### Ingestion pipeline (`app/ingestion/`, async via Celery)

Upload → S3 (raw file) + Postgres (metadata) → Celery task → extract → chunk (`RecursiveCharacterTextSplitter`, size 800 / overlap 200) → embed → write vectors to Qdrant + graph nodes/edges to Neo4j (`ingestion/graph_indexer.py`). Celery tasks must be **idempotent and retry-safe**; upload must never block.

### LLM abstraction (critical rule)

Never call OpenAI directly from routes, services, or graph nodes. Go through the factory:

```python
from app.llm.factory import get_llm
llm = get_llm()   # BaseLLM impl (OpenAILLM now; VLLMLLM planned for local migration)
```

## Current Reality vs. Older Docs

These reflect the actual code and differ from older prose such as `backend/README.md`:

- **Embeddings:** OpenAI `text-embedding-3-small` (`ingestion/embedder.py`), *not* BGE-M3 local — `pyproject.toml` has no `FlagEmbedding`/`torch`, and the reranker loads no model either.
- **Object storage:** AWS S3 via `boto3`; LocalStack (`http://localhost:4566`) for local dev, real S3 in prod (empty `AWS_S3_ENDPOINT_URL`). Not MinIO.
- **Retrieval sparse leg:** Neo4j knowledge-graph traversal, not BM25.
- Tunable retrieval/chunking knobs live in `app/core/config.py` (`DENSE_TOP_K`, `GRAPH_WEIGHT`, `RERANK_TOP_K`, `CHUNK_SIZE`, etc.).

## Frontend Notes

- `frontend/lib/api.ts` has **`MOCK_MODE = false`** — the UI talks to the real API (`NEXT_PUBLIC_API_URL`, else `http://127.0.0.1:8000`); `lib/mockRag.ts` is a leftover nothing imports. It also handles JWT access/refresh token storage in `localStorage`.
- `endpointAPIbe.json` documents the backend contract the frontend targets (synced: 34 `/api/v1` routes + `/health`); `lib/context.tsx` holds global React state.
- CI: `.github/workflows/frontend-ci.yml` runs typecheck + build; no lint step yet (16 pre-existing ESLint errors per its comment).

## Conventions

- Backend routes stay thin; put logic in services, DB access in repositories. All I/O async. Validate every request/response with Pydantic. Soft-delete via `deleted_at` rather than hard deletes. Use Alembic for all schema changes.
- Every retrieval must enforce data isolation: filter by `owner_id` (non-admins reach only their own documents/chunks; `admin` sees all) and pass `excluded_document_ids`. `require_role` (`app/auth/rbac.py`) guards only the `/admin/*` router; `editor` / `viewer` roles exist but no route enforces them.
- Audit logging (`models/audit_log.py`) currently covers only chat queries and document upload / delete / reindex (plus client-submitted entries via `POST /audit-logs`), not every action.
- Some code comments and docs are in Vietnamese; matching the surrounding language is fine.
