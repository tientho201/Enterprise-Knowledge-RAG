"""Dead-letter queue cho Celery (app/models/failed_task.py, app/workers/dlq.py,
app/repositories/failed_task_repo.py) — Task 2.2, xem
.claude/tasks/production-ops-gaps.md mục 2."""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.models.user import User, UserRole
from app.repositories.failed_task_repo import FailedTaskRepository
from app.workers.dlq import _json_safe, on_task_failure


class _NotJsonSerializable:
    def __repr__(self) -> str:
        return "<weird-object>"


def test_json_safe_passthrough_for_serializable_values():
    assert _json_safe("hello") == "hello"
    assert _json_safe({"a": 1}) == {"a": 1}
    assert _json_safe([1, 2, 3]) == [1, 2, 3]


def test_json_safe_falls_back_to_str_for_non_serializable():
    obj = _NotJsonSerializable()
    assert _json_safe(obj) == "<weird-object>"


def test_task_failure_signal_has_on_task_failure_receiver():
    """Đảm bảo on_task_failure THẬT ĐÃ được đăng ký vào signal task_failure (qua
    import app.workers.celery_app, xem dòng `from app.workers import dlq` ở cuối file
    đó) — regression guard nếu ai vô tình xoá import và signal im lặng mất tác dụng."""
    from celery.signals import task_failure

    import app.workers.celery_app  # noqa: F401 — trigger side-effect import dlq

    receiver_funcs = [ref() for _id, ref in task_failure.receivers if ref() is not None]
    assert on_task_failure in receiver_funcs


@pytest.mark.asyncio
async def test_failed_task_repo_create_and_list(db_session):
    repo = FailedTaskRepository(db_session)
    record = await repo.create(
        task_name="app.workers.tasks.ingestion.ingest_document",
        celery_task_id="abc-123",
        exception="ValueError: boom",
        args=["doc-1", "s3/path"],
        kwargs={"retry": True},
        traceback="Traceback (most recent call last): ...",
    )
    assert record.resolved is False
    assert record.retries == 0

    recent = await repo.list_recent()
    assert any(r.celery_task_id == "abc-123" for r in recent)


@pytest.mark.asyncio
async def test_failed_task_repo_mark_resolved(db_session):
    repo = FailedTaskRepository(db_session)
    record = await repo.create(task_name="t", celery_task_id="xyz-999", exception="boom")
    resolved = await repo.mark_resolved(record.id)
    assert resolved is not None
    assert resolved.resolved is True

    unresolved_only = await repo.list_recent(resolved=False)
    assert all(r.celery_task_id != "xyz-999" for r in unresolved_only)


@pytest_asyncio.fixture
async def isolated_app_client():
    """Mirror test_admin_users.py::isolated_app_client — DB SQLite in-memory riêng,
    patch AsyncSessionLocal đã bind trong app.core.dependencies."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    with patch("app.core.dependencies.AsyncSessionLocal", session_factory):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory

    await engine.dispose()


async def _create_user(session_factory, *, role: UserRole) -> tuple[str, str]:
    async with session_factory() as db:
        user = User(
            email=f"{role.value}-{uuid.uuid4().hex}@test.local",
            password_hash="unused",
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    return user_id, create_access_token(user_id)


@pytest.mark.asyncio
async def test_non_admin_cannot_list_failed_tasks(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.get(
        "/api/v1/admin/failed-tasks", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_and_resolve_failed_tasks(isolated_app_client):
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)

    async with session_factory() as db:
        record = await FailedTaskRepository(db).create(
            task_name="app.workers.tasks.ingestion.ingest_document",
            celery_task_id="task-1",
            exception="ValueError: boom",
        )
        await db.commit()
        failed_task_id = record.id

    resp = await client.get(
        "/api/v1/admin/failed-tasks", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["resolved"] is False

    resp2 = await client.post(
        f"/api/v1/admin/failed-tasks/{failed_task_id}/resolve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["resolved"] is True


@pytest.mark.asyncio
async def test_resolve_unknown_failed_task_404(isolated_app_client):
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)

    resp = await client.post(
        "/api/v1/admin/failed-tasks/does-not-exist/resolve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
