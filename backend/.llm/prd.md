# CLAUDE.md

# Project Overview

Enterprise Knowledge RAG system for internal company knowledge.

Purpose:

* Ingest internal documents
* Retrieve internal knowledge
* Generate grounded answers
* Return accurate citations
* Reduce hallucinations
* Support enterprise internal search

Supported sources:

* PDF
* DOCX
* Confluence
* Slack

Primary use cases:

* HR policy lookup
* Legal contract search
* Internal SOP retrieval
* Technical documentation search

Current phase:

* Prioritize shipping MVP fast
* Use OpenAI for inference
* Keep architecture modular for future local model migration

Future phase:

* Replace OpenAI with local quantized models
* Use vLLM or Ollama

---

# Tech Stack

## Frontend

* Next.js
* TailwindCSS
* shadcn/ui
* Zustand
* TanStack Query

---

## Backend & API

* FastAPI (Strictly Async)
* SQLAlchemy
* PostgreSQL

---

## Queue & Background Tasks

* Celery
* Redis

---

## Current AI Stack (Phase 1)

LLM Provider:

* OpenAI API

LLM Model:

* GPT-4o-mini

Embedding Model:

```
* text-embedding-3-small
```

Orchestration:

* LangChain
* LangGraph

Rules:

* OpenAI is used only for rapid development.
* Embeddings must remain local.
* All LLM calls must go through abstraction layer.

---

## Future AI Stack (Phase 2)

Inference Server:

* vLLM

Development:

* Ollama

Local LLM:

* Llama-3-8B-Instruct (AWQ / GPTQ)

Rules:

* Future migration must not require changing business logic.
* Only LLM provider implementation may change.

---

## Vector Database

* Qdrant

---

## File Storage

* MinIO

---

## Observability

* LangSmith
* Prometheus
* Docker
* Docker Compose

---

# System Architecture

Frontend → FastAPI → LangGraph → Hybrid Retrieval → Re-ranker → OpenAI GPT-4o-mini

Storage:

* PostgreSQL → users, metadata, conversations
* Qdrant → vector embeddings
* MinIO → raw uploaded files
* Redis → queues/cache

Architecture rules:

* Retrieval and generation must be isolated.
* LLM provider must be replaceable.
* API layer must remain stateless.
* All services must be modular.

---

# LLM Abstraction Layer (Critical)

Never call OpenAI directly inside routes, services, or graph nodes.

Must use:

BaseLLM

Implementations:

* OpenAILLM
* VLLMLLM
* OllamaLLM

Factory:

get_llm()

Rules:

* LangGraph must use BaseLLM only.
* Swapping providers must require zero graph changes.

---

# Core Workflows

## Document Ingestion (Async)

Upload
→ Store in MinIO
→ Create metadata in PostgreSQL
→ Dispatch Celery task
→ Extract text
→ Chunk text
→ Generate local embeddings
→ Store vectors in Qdrant

Rules:

* Upload must never block.
* All ingestion must be async.
* Failed jobs must be retryable.

---

## Retrieval Workflow

User Query
→ Router Node
→ Hybrid Retrieval
→ Re-ranker
→ Grader Node
→ Rewrite Node (optional)
→ Generator Node
→ Final Response

---

# LangGraph Workflow

Workflow:

Router
→ Retriever
→ Re-ranker
→ Grader
→ Rewriter (optional)
→ Generator

---

# LangGraph State Contract

State:

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

Rules:

* State must be typed.
* Avoid raw dictionaries.
* Keep graph deterministic.

---

# Retrieval Rules

## Hybrid Search

Dense:

* Qdrant similarity search

Sparse:

* BM25

Weights:

Dense = 0.7
Sparse = 0.3

Top-K:

Dense top-k = 20
Sparse top-k = 20
Merged top-k = 20
Reranked top-k = 5

---

## Re-ranking

Use cross-encoder reranker.

Rules:

* Re-ranking is mandatory.
* Never send raw chunks directly to generator.

---

# Generator Rules

Rules:

1. Answer ONLY from retrieved context.
2. If context is insufficient, return:

Not found in documents.

3. Every answer MUST include citations.
4. Citations must map to:

   * document_id
   * chunk_id
   * page_number

Never:

* hallucinate
* invent citations
* answer beyond context

Current prompt format:

* optimized for GPT-4o-mini

Future prompt format:

* optimized for Llama-3 instruction template

---

# Chunking Rules

Use:

RecursiveCharacterTextSplitter

Default:

chunk_size = 800
chunk_overlap = 200

Rules:

* Preserve semantic boundaries.
* Avoid splitting legal clauses.

---

# Embedding Rules

Embedding model:

BGE-M3

Rules:

* Run locally only.
* Batch embeddings.
* Normalize embeddings.

---

# Backend Rules

1. Keep routes thin.
2. HTTP handling only in routes.
3. Business logic in services/.
4. DB logic in repositories/.
5. Use FastAPI dependency injection.
6. Strict async/await.
7. No sync DB calls.
8. No direct OpenAI calls inside routes.

Structure:

routes/
services/
repositories/
workers/
agents/
rag/

---

# Database Rules

PostgreSQL stores:

* users
* roles
* documents metadata
* conversation history
* audit logs

Rules:

* Use Alembic.
* No manual schema changes in production.
* Use soft delete.

---

# Document Versioning Rules

Rules:

1. Every document must have version.
2. Re-upload creates new version.
3. Old vectors must be archived or deleted.
4. Preserve metadata history.

---

# Security Rules

Required:

* JWT Authentication
* RBAC Authorization
* Document-level access control
* Audit logging

Rules:

* Every API validates JWT.
* Every retrieval validates permissions.
* Every chat request is logged.

Audit fields:

user_id
query
documents_used
timestamp

---

# Celery Rules

Tasks:

* extract_document
* chunk_document
* embed_document
* reindex_document
* delete_vectors

Retry:

max_retries = 3
retry_backoff = True

Rules:

* Tasks must be idempotent.
* Tasks must be retry-safe.

---

# Frontend Rules

1. Prefer server components.
2. Client components only when necessary.
3. Keep components small.
4. Zustand for UI state.
5. TanStack Query for server state.
6. Support SSE streaming.
7. Render citations inline.

Pages:

* /login
* /chat
* /chat/
* /documents
* /documents/
* /admin/dashboard
* /admin/jobs

---

# API Rules

Required:

POST /auth/login
POST /auth/register

POST /chat
GET /chat/history
GET /chat/

POST /documents/upload
GET /documents
GET /documents/
DELETE /documents/
POST /documents/reindex

GET /admin/dashboard
GET /admin/jobs

Rules:

* Pydantic validation required.
* Response models required.

---

# Testing Rules

Unit:

* services
* repositories
* chunking
* embedding

Integration:

* ingestion pipeline
* retrieval pipeline
* LangGraph workflow

E2E:

* upload flow
* chat flow
* document search flow

Rules:

* No feature is complete without tests.

---

# Infrastructure Rules

Everything must be Dockerized.

Services:

* FastAPI
* PostgreSQL
* Redis
* Celery Worker
* Qdrant
* MinIO

Development:

* OpenAI API

Future:

* Ollama
* vLLM

Rules:

* Never hardcode secrets.
* Use .env
* Use BaseSettings

---

# Commands

Run backend:

uvicorn app.main --reload

Run worker:

celery -A app.workers.celery worker --loglevel=info

Run frontend:

npm run dev

Run tests:

pytest

Run lint:

ruff check .

Run format:

black .

Run Docker:

docker-compose up --build

---

# Important Constraints

* Current phase uses OpenAI for fast iteration.
* OpenAI must be abstracted.
* Embeddings must remain local.
* Future migration to local LLM is mandatory.
* Hybrid retrieval is mandatory.
* Re-ranking is mandatory.
* Citations are mandatory.
* Versioning is mandatory.
* RBAC is mandatory.
* Audit logs are mandatory.
* Streaming is mandatory.
* All I/O must be async.
