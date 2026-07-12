from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _connect_args() -> dict:
    args: dict = {}
    if "supabase.co" in settings.DATABASE_URL or "pooler.supabase.com" in settings.DATABASE_URL:
        # PgBouncer transaction mode: disable prepared statement cache
        args["statement_cache_size"] = 0
        args["ssl"] = "require"
    return args


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    connect_args=_connect_args(),
)

AsyncSessionLocal = async_sessionmaker[AsyncSession](
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
