"""
Quản lý user của admin (GET /admin/users, PATCH /admin/users/{id}/role) và tự nâng
cấp gói (POST /auth/plan, self-service demo — không thu tiền thật). Gọi thẳng HTTP
qua ASGI transport, không qua UI — cùng kỹ thuật cô lập DB như test_plan_gate.py.
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.models.user import User, UserPlan, UserRole


@pytest_asyncio.fixture
async def isolated_app_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Xem giải thích chi tiết trong test_plan_gate.py — phải patch đúng tên đã bind
    # trong app.core.dependencies (import eager), không phải app.db.session.
    with patch("app.core.dependencies.AsyncSessionLocal", session_factory):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory

    await engine.dispose()


async def _create_user(
    session_factory, *, role: UserRole, plan: UserPlan = UserPlan.free
) -> tuple[str, str]:
    async with session_factory() as db:
        user = User(
            email=f"{role.value}-{plan.value}-{uuid.uuid4().hex}@test.local",
            password_hash="unused",
            role=role,
            plan=plan,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    return user_id, create_access_token(user_id)


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_users(isolated_app_client):
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)
    await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert len(emails) == 2


@pytest.mark.asyncio
async def test_non_admin_cannot_change_role(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer)
    target_id, _ = await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.patch(
        f"/api/v1/admin/users/{target_id}/role",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_change_role(isolated_app_client):
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)
    target_id, _ = await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.patch(
        f"/api/v1/admin/users/{target_id}/role",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


@pytest.mark.asyncio
async def test_update_role_unknown_user_404(isolated_app_client):
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)

    resp = await client.patch(
        "/api/v1/admin/users/does-not-exist/role",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_self_service_upgrade_to_pro(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    resp = await client.post(
        "/api/v1/auth/plan",
        json={"plan": "pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "pro"
    assert body["can_use_advanced_search"] is True


@pytest.mark.asyncio
async def test_self_service_downgrade_to_free(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)

    resp = await client.post(
        "/api/v1/auth/plan",
        json={"plan": "free"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "free"
    assert body["can_use_advanced_search"] is False
