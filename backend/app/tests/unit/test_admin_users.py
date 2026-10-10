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

from app.core.config import settings
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


async def _plan_in_db(session_factory, user_id: str) -> UserPlan:
    async with session_factory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        return user.plan


@pytest.mark.asyncio
async def test_self_service_upgrade_to_pro(isolated_app_client, monkeypatch):
    # Tự nâng Pro chỉ còn chạy khi cờ demo bật (mặc định tắt) — bật tường minh ở đây.
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", True)
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


# ── Cờ SELF_SERVICE_PLAN_ENABLED (quyết định D1) ─────────────────────────────


def test_self_service_plan_flag_defaults_off():
    # Đọc mặc định khai báo trong code (không phải giá trị .env có thể ghi đè):
    # mặc định phải là tắt, nếu không gate trả phí vô nghĩa.
    assert type(settings).model_fields["SELF_SERVICE_PLAN_ENABLED"].default is False


@pytest.mark.asyncio
async def test_upgrade_to_pro_forbidden_when_flag_off(isolated_app_client, monkeypatch):
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", False)
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/v1/auth/plan", json={"plan": "pro"}, headers=headers)
    assert resp.status_code == 403
    # Frontend (UpgradeModal) hiển thị nguyên văn `detail` cho người dùng.
    assert resp.json()["detail"] == "Nâng cấp gói Pro cần được quản trị viên kích hoạt."

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["plan"] == "free"
    assert me.json()["can_use_advanced_search"] is False
    assert await _plan_in_db(session_factory, user_id) == UserPlan.free


@pytest.mark.asyncio
async def test_downgrade_to_free_allowed_when_flag_off(isolated_app_client, monkeypatch):
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", False)
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)

    resp = await client.post(
        "/api/v1/auth/plan",
        json={"plan": "free"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"
    assert resp.json()["can_use_advanced_search"] is False
    assert await _plan_in_db(session_factory, user_id) == UserPlan.free


@pytest.mark.asyncio
async def test_upgrade_to_pro_persisted_when_flag_on(isolated_app_client, monkeypatch):
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", True)
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    resp = await client.post(
        "/api/v1/auth/plan",
        json={"plan": "pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro"
    assert resp.json()["can_use_advanced_search"] is True
    assert await _plan_in_db(session_factory, user_id) == UserPlan.pro


@pytest.mark.asyncio
async def test_existing_pro_user_untouched_when_flag_off(isolated_app_client, monkeypatch):
    # User đã ở Pro gọi lại "nâng Pro" lúc cờ tắt: bị từ chối như mọi yêu cầu lên Pro,
    # nhưng gói Pro sẵn có KHÔNG bị đụng tới (không hạ, không ghi gì).
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", False)
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/v1/auth/plan", json={"plan": "pro"}, headers=headers)
    assert resp.status_code == 403

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["plan"] == "pro"
    assert me.json()["can_use_advanced_search"] is True
    assert await _plan_in_db(session_factory, user_id) == UserPlan.pro


@pytest.mark.asyncio
async def test_admin_keeps_advanced_access_when_flag_off(isolated_app_client, monkeypatch):
    # Admin không cần plan Pro để qua gate (core/plan_gate.py). Cờ tắt chặn admin tự
    # đặt plan=pro cho chính mình như mọi user, nhưng không làm mất quyền Nâng cao
    # và không ảnh hưởng route quản trị.
    monkeypatch.setattr(settings, "SELF_SERVICE_PLAN_ENABLED", False)
    client, session_factory = isolated_app_client
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)
    target_id, _ = await _create_user(session_factory, role=UserRole.viewer)
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = await client.post("/api/v1/auth/plan", json={"plan": "pro"}, headers=headers)
    assert resp.status_code == 403

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["can_use_advanced_search"] is True

    role_resp = await client.patch(
        f"/api/v1/admin/users/{target_id}/role", json={"role": "editor"}, headers=headers
    )
    assert role_resp.status_code == 200
