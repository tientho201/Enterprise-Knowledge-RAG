from functools import lru_cache

from pydantic import field_validator, model_validator
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
    # Pool 15/process (5 + 10 overflow). Tổng peak: API (--workers 4) ≈ 60 + Celery worker
    # (prefork concurrency 4, dùng cùng async engine qua asyncio.run) ≈ 60 = ~120 client conn.
    # CHỈ an toàn vì dùng cổng 6543 (Supavisor transaction-mode pooler) — pooler multiplex
    # nhiều client conn xuống ít Postgres backend; "60" của free tier là giới hạn phía Postgres.
    # ⚠️ Nếu đổi sang cổng trực tiếp 5432 (không pooler) PHẢI giảm mạnh 2 số này.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

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

    # ── Rate limiting (Redis fixed-window, per-user) ──────────────────────────
    # Chặn abuse + kiểm soát cost OpenAI. Fail-open nếu Redis down (không chặn request).
    CHAT_RATE_LIMIT_PER_MINUTE: int = 20
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = 10

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

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> "Settings":
        # Ở production, chặn deploy với secret rác / mặc định. Không tự sinh secret —
        # đó là việc của user (openssl rand -hex 32 → .env.prod / secrets manager).
        if self.APP_ENV.lower() == "production":
            weak = {"changeme", "your-super-secret-key-change-in-production", ""}
            if self.SECRET_KEY.strip() in weak or len(self.SECRET_KEY.strip()) < 32:
                raise ValueError(
                    "SECRET_KEY is weak/default while APP_ENV=production. "
                    "Set a strong random value (e.g. `openssl rand -hex 32`) via "
                    "environment/secret before deploying."
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be false when APP_ENV=production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
