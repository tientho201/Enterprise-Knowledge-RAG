import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import admin, audit_logs, auth, chat, documents, graph
from app.core.config import settings
from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.rag.retriever import get_qdrant_client

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s in %s mode", settings.APP_NAME, settings.APP_ENV)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Enterprise Knowledge RAG — Backend API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
    app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
    app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
    app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
    app.include_router(audit_logs.router, prefix=settings.API_V1_PREFIX)
    app.include_router(graph.router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["health"])
    async def health_check():
        """Liveness + readiness: ping DB, Redis, Qdrant. Trả 503 nếu bất kỳ service down.

        CD (`cd.yml`) dùng endpoint này để xác nhận deploy — phải phản ánh trạng thái thật.
        """
        checks = await asyncio.gather(
            _check_db(),
            _check_redis(),
            _check_qdrant(),
            return_exceptions=False,
        )
        components = dict(checks)
        healthy = all(v == "ok" for v in components.values())
        body = {
            "status": "ok" if healthy else "degraded",
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "components": components,
        }
        if not healthy:
            return JSONResponse(status_code=503, content=body)
        return body

    return app


async def _check_db() -> tuple[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return "database", "ok"
    except Exception as exc:  # noqa: BLE001 — health check phải nuốt mọi lỗi
        logger.warning("Health check DB failed: %s", exc)
        return "database", "down"


async def _check_redis() -> tuple[str, str]:
    try:
        await get_redis().ping()
        return "redis", "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health check Redis failed: %s", exc)
        return "redis", "down"


async def _check_qdrant() -> tuple[str, str]:
    # QdrantClient là sync → chạy trong executor để không block event loop.
    try:
        await asyncio.to_thread(get_qdrant_client().get_collections)
        return "qdrant", "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health check Qdrant failed: %s", exc)
        return "qdrant", "down"


app = create_app()
