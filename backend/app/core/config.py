from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str = "Enterprise Knowledge RAG"
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "changeme"
    API_V1_PREFIX: str = "/api/v1"

    # ── Supabase / PostgreSQL ─────────────────────────────────────────────────
    # Lưu trữ: users, documents metadata, chunks, conversations, messages, audit_logs
    # Format:  postgresql+asyncpg://postgres.[PROJECT-REF]:[PASSWORD]@...pooler.supabase.com:6543/postgres
    # Dùng port 6543 (PgBouncer transaction mode) thay vì 5432 để tránh vượt connection limit
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_rag"
    DB_POOL_SIZE: int = 5  # Supabase free tier: tối đa 60 connections
    DB_MAX_OVERFLOW: int = 10  # 5 pool + 10 overflow = 15 per worker instance

    # ── AWS S3 — Raw document storage ─────────────────────────────────────────
    # Lưu trữ: raw files (PDF, DOCX, TXT) upload bởi người dùng
    # Local dev:  LocalStack → AWS_S3_ENDPOINT_URL=http://localhost:4566
    # Production: AWS S3 thật → để trống AWS_S3_ENDPOINT_URL
    AWS_ACCESS_KEY_ID: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET_NAME: str = "documents"
    AWS_S3_ENDPOINT_URL: str = "http://localhost:4566"  # empty string = use real AWS S3

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ── Qdrant Cloud — Vector store ───────────────────────────────────────────
    # Lưu trữ: dense embeddings của chunks
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_NAME: str = "enterprise_knowledge"

    # ── Neo4j — Knowledge Graph ───────────────────────────────────────────────
    # Lưu trữ: graph edges giữa chunks (NEXT_CHUNK, REFERENCES)
    # Local: docker-compose up neo4j
    # Cloud: https://neo4j.com/cloud/aura-free
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j"

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 2048
    OPENAI_TEMPERATURE: float = 0.1

    # ── Embedding (OpenAI) ────────────────────────────────────────────────────
    # text-embedding-3-small: 1536 dims, cost-effective
    # text-embedding-3-large: 3072 dims, higher quality
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_BATCH_SIZE: int = 512

    # ── LangSmith ────────────────────────────────────────────────────────────
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "enterprise-knowledge-rag"

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Chunking ──────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 200

    # ── Retrieval ─────────────────────────────────────────────────────────────
    DENSE_TOP_K: int = 20
    GRAPH_TOP_K: int = 20
    RERANK_TOP_K: int = 5
    DENSE_WEIGHT: float = 0.7
    GRAPH_WEIGHT: float = 0.3

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            import json

            return json.loads(v)
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        # Env rỗng (vd secret DATABASE_URL chưa set trong CD) ghi đè default thành ""
        # → create_async_engine sẽ ném "Could not parse SQLAlchemy URL". Fail sớm với thông điệp rõ.
        if not v or not v.strip():
            raise ValueError(
                "DATABASE_URL is empty. Set it via environment/secret "
                "(e.g. the 'DATABASE_URL' secret of the GitHub 'production' environment "
                "for the CD migrate job)."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
