from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    # Echo mọi câu SQL ra log. Tách khỏi DEBUG vì DEBUG=true (dev) mà bật echo sẽ
    # làm log "nhảy liên tục" (mỗi request chat = hàng chục câu SQL). Mặc định tắt.
    DB_ECHO: bool = False
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
    AWS_S3_ENDPOINT_URL: str = ""  # empty string = use real AWS S3

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
    # File credentials Aura tải về dùng key `NEO4J_USERNAME` (KHÔNG phải `NEO4J_USER`),
    # và username = <instance-id> chứ không phải "neo4j". Chấp nhận cả 2 tên biến để
    # dán thẳng file Aura vào .env là chạy — nếu chỉ đọc NEO4J_USER thì NEO4J_USERNAME
    # bị bỏ qua, rơi về mặc định "neo4j" → AuthError.
    NEO4J_USER: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"),
    )
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

    # ── Citation graph / Provision layer (phase 2 — viện dẫn ngoại + LLM fallback) ─
    # Trần cứng số câu "viện dẫn ngầm" (không match được C1/C2 bằng regex) đưa vào
    # 1 LLM call/document — văn bản dài bất thường không được đội chi phí LLM
    # không kiểm soát. Xem structural_parser.find_implicit_citation_sentences.
    IMPLICIT_CITATION_MAX_SENTENCES: int = 30

    # ── Retrieval ─────────────────────────────────────────────────────────────
    DENSE_TOP_K: int = 20
    GRAPH_TOP_K: int = 20
    RERANK_TOP_K: int = 10  # số chunk đưa tới generator. Tăng 5→10 để cải thiện recall
    DENSE_WEIGHT: float = 0.7
    GRAPH_WEIGHT: float = 0.3

    # ── Graph explorer (Giao diện Nâng cao) ───────────────────────────────────
    # Trần cứng số node trả về / 1 lần bung (expand) 1 tài liệu. react-force-graph
    # mượt tới vài trăm node trên máy tầm trung; 1 Thông tư ~40–50 trang ≈ 125 chunk
    # nên 300 thoải mái. Bị cắt → trả cờ truncated để client báo "hiển thị 300/N".
    GRAPH_MAX_NODES: int = 300

    # ── Rate limiting (Redis fixed-window, per-user) ──────────────────────────
    # Chặn abuse + kiểm soát cost OpenAI. Fail-open nếu Redis down (không chặn request).
    CHAT_RATE_LIMIT_PER_MINUTE: int = 20
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = 10
    # Ảnh gửi kèm chat (vision) — tách riêng khỏi UPLOAD_RATE_LIMIT_PER_MINUTE (đó là cho
    # tài liệu thư viện). Ngưỡng cao hơn vì user có thể paste nhiều screenshot liên tiếp.
    CHAT_IMAGE_RATE_LIMIT_PER_MINUTE: int = 30

    # ── SMTP / OTP đăng ký (xác minh email qua mã 6 số) ──────────────────────
    # SMTP_HOST rỗng = chưa cấu hình → Celery task bỏ qua gửi thật (log warning),
    # không raise lỗi (giống cách Neo4j graceful-degrade khi service phụ chưa sẵn).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True
    # OTP lưu ở Redis (không phải cột DB) — tự hết hạn bằng TTL, không cần job dọn.
    OTP_EXPIRE_MINUTES: int = 10
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_ATTEMPTS: int = 5

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
