You are the lead architect and senior reviewer of this Enterprise Knowledge RAG system.

Your job is to deeply inspect the entire repository and verify end-to-end consistency.

Perform a full-system audit.

Validate all layers:

Frontend
Backend
Database
Celery workers
LangGraph workflow
Retrieval pipeline
Embedding pipeline
Storage layer
API contracts
Security
Streaming
Testing

Your objective:

detect architectural inconsistencies
detect broken flows
detect missing implementations
detect invalid imports
detect dead code
detect dependency mismatches
detect API mismatch between frontend and backend
detect schema mismatch between SQLAlchemy models and Pydantic schemas
detect LangGraph state mismatch between nodes
detect retrieval bugs
detect citation tracking bugs
detect document versioning bugs
detect RBAC leaks
detect async violations
detect race conditions in Celery workflows
detect broken retry logic
