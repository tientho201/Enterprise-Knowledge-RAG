"""
Gate "Giao diện Nâng cao" cho endpoint đồ thị (GET /api/v1/graph/overview) — chỉ user
plan=pro (chưa hết hạn) hoặc role=admin qua được; free bị 403 ngay ở tầng dependency
(`require_advanced_access`), TRƯỚC khi chạm GraphService/Neo4j. Gọi thẳng endpoint HTTP
thật qua ASGI transport để xác nhận gate body-less hoạt động (khác gate của /chat vốn
suy `search_mode` từ request body).

DB: sqlite in-memory riêng cho file test này — patch app.core.dependencies.AsyncSessionLocal
(cùng lý do đã ghi ở test_plan_gate.py). Neo4j không có thật trong unit test → fetch_overview
graceful-degrade về đồ thị rỗng, không ảnh hưởng khẳng định của test (chỉ kiểm gate + isolation).
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
from app.models.conversation import Conversation
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

    with patch("app.core.dependencies.AsyncSessionLocal", session_factory):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory

    await engine.dispose()


async def _create_user(session_factory, *, role: UserRole, plan: UserPlan) -> tuple[str, str]:
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


async def _create_conversation(session_factory, user_id: str) -> str:
    async with session_factory() as db:
        conv = Conversation(user_id=user_id, title="test")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id


@pytest.mark.asyncio
async def test_free_user_graph_overview_blocked_403(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    resp = await client.get(
        "/api/v1/graph/overview",
        params={"conversation_id": "any-id"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "Nâng cao" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_free_user_graph_highlight_blocked_403(isolated_app_client):
    """Gate router-level áp cho mọi route graph, gồm POST /highlight (Endpoint B)."""
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    resp = await client.post(
        "/api/v1/graph/highlight",
        json={"conversationId": "any-id", "query": "thử"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pro_user_graph_overview_allowed(isolated_app_client):
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)
    conv_id = await _create_conversation(session_factory, user_id)

    resp = await client.get(
        "/api/v1/graph/overview",
        params={"conversation_id": conv_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Qua gate (không 403). Không có tài liệu gắn → đồ thị rỗng.
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_admin_free_plan_graph_overview_allowed(isolated_app_client):
    """Admin luôn qua gate bất kể plan."""
    client, session_factory = isolated_app_client
    user_id, token = await _create_user(session_factory, role=UserRole.admin, plan=UserPlan.free)
    conv_id = await _create_conversation(session_factory, user_id)

    resp = await client.get(
        "/api/v1/graph/overview",
        params={"conversation_id": conv_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_pro_user_other_users_conversation_404(isolated_app_client):
    """Data isolation: pro user không xem được đồ thị của hội thoại người khác → 404."""
    client, session_factory = isolated_app_client
    owner_id, _ = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)
    conv_id = await _create_conversation(session_factory, owner_id)
    # user thứ 2 (pro) cố truy cập hội thoại của user 1
    _, token2 = await _create_user(session_factory, role=UserRole.admin, plan=UserPlan.pro)
    # dùng viewer để không bypass isolation bằng quyền admin
    _, token_viewer = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)

    resp = await client.get(
        "/api/v1/graph/overview",
        params={"conversation_id": conv_id},
        headers={"Authorization": f"Bearer {token_viewer}"},
    )
    assert resp.status_code == 404, resp.text
