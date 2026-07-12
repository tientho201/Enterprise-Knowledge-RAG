"""
Unit test cho _connect_args() trong app/db/session.py — hàm string-matching thuần túy,
quyết định có bật PgBouncer workaround (statement_cache_size=0, ssl=require) hay không dựa
trên DATABASE_URL. Đây là lý do duy nhất project cân nhắc dùng Supabase thật trong CI; test
này verify đúng logic đó mà không cần container/service thật nào.
"""

from app.core.config import settings
from app.db.session import _connect_args


class TestConnectArgs:
    def test_supabase_co_url_enables_pgbouncer_workaround(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://user:pass@db.abcproject.supabase.co:5432/postgres",
        )
        assert _connect_args() == {"statement_cache_size": 0, "ssl": "require"}

    def test_pooler_supabase_com_url_enables_pgbouncer_workaround(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://postgres.ref:pass@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres",
        )
        assert _connect_args() == {"statement_cache_size": 0, "ssl": "require"}

    def test_local_postgres_url_returns_empty_connect_args(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        )
        assert _connect_args() == {}

    def test_sqlite_url_returns_empty_connect_args(self, monkeypatch):
        monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        assert _connect_args() == {}
