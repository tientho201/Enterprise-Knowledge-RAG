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

    # Application
    APP_NAME: str = "Enterprise Knowledge RAG"
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "changeme"
    API_V1_PREFIX: str = "/api/v1"

    # Supabase / PostgreSQL
    # Format: postgresql+asyncpg://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_rag"
    # Connection pool size — Supabase free tier giới hạn 60 connections
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Qdrant Cloud
    # URL format: https://[cluster-id].qdrant.tech
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_NAME: str = "enterprise_knowledge"

    # AWS S3 / LocalStack
    # Local dev: LocalStack tại http://localhost:4566 (AWS_S3_ENDPOINT_URL phải được set)
    # Production: để trống AWS_S3_ENDPOINT_URL → dùng AWS S3 thật
    AWS_ACCESS_KEY_ID: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET_NAME: str = "documents"
    AWS_S3_ENDPOINT_URL: str = "http://localhost:4566"  # để trống khi dùng AWS S3 thật

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 2048
    OPENAI_TEMPERATURE: float = 0.1

    # LangSmith
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "enterprise-knowledge-rag"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DEVICE: str = "cpu"

    # Chunking
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 200

    # Neo4j (Knowledge Graph — replaces BM25 sparse search)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j"

    # Retrieval
    DENSE_TOP_K: int = 20
    GRAPH_TOP_K: int = 20       # max graph-expanded chunks per query
    RERANK_TOP_K: int = 5
    DENSE_WEIGHT: float = 0.7
    GRAPH_WEIGHT: float = 0.3   # formerly SPARSE_WEIGHT

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
