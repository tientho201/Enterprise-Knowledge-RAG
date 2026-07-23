"""
Gate "Chế độ tra cứu Nâng cao" (search_mode="advanced") — chỉ user plan=pro (chưa hết
hạn) hoặc role=admin mới qua được; free bị 403 ngay ở tầng dependency (route), TRƯỚC
khi chạm ChatService/LLM/Qdrant. Gọi thẳng endpoint HTTP thật qua ASGI transport (không
qua UI) để xác nhận `Depends(require_advanced_search_access)` thực sự nhận được cùng
request body với route handler — đây là phần cơ chế FastAPI không hiển nhiên, cần test
thật thay vì chỉ gọi hàm Python trực tiếp.

DB: sqlite in-memory riêng cho file test này (không đụng Postgres thật) — patch
app.core.dependencies.AsyncSessionLocal để app.main.app (ASGI thật) dùng chung DB này.
ChatService.chat bị monkeypatch cho case "được phép" để không gọi OpenAI/Qdrant thật.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.models.message import MessageRole
from app.models.user import User, UserPlan, UserRole
from app.schemas.chat import ChatResponse, MessageResponse


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

    # app.core.dependencies làm `from app.db.session import AsyncSessionLocal` (eager, ở đầu
    # file) -> module đó chỉ import 1 lần/tiến trình pytest rồi cache trong sys.modules, nên
    # patch app.db.session.AsyncSessionLocal (module nguồn) không có tác dụng cho các test
    # chạy SAU test đầu tiên (app.main/app.core.dependencies đã import xong từ trước). Phải
    # patch đúng cái tên đã bind trong namespace của app.core.dependencies — get_db() tra cứu
    # lại tên đó mỗi lần gọi nên patch theo cách này có tác dụng ở MỌI test, không chỉ test đầu.
    with patch("app.core.dependencies.AsyncSessionLocal", session_factory):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory

    await engine.dispose()


async def _create_user(
    session_factory, *, role: UserRole, plan: UserPlan, plan_expires_at=None
) -> tuple[str, str]:
    async with session_factory() as db:
        user = User(
            email=f"{role.value}-{plan.value}-{id(session_factory)}@test.local",
            password_hash="unused",
            role=role,
            plan=plan,
            plan_expires_at=plan_expires_at,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    return user_id, create_access_token(user_id)


def _fake_chat_response() -> ChatResponse:
    return ChatResponse(
        conversation_id="conv-1",
        message=MessageResponse(
            id="msg-1",
            role=MessageRole.assistant,
            content="ok",
            created_at=datetime.now(UTC),
            citations=[],
        ),
    )


@pytest.mark.asyncio
async def test_free_user_advanced_search_blocked_403(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    # KHÔNG mock ChatService — nếu gate không chặn, test này sẽ cố gọi OpenAI/Qdrant thật
    # và fail vì lý do khác (che mất bug), đúng ý: xác nhận request bị chặn TRƯỚC khi tới đó.
    resp = await client.post(
        "/api/v1/chat",
        json={"message": "hỏi thử", "searchMode": "advanced"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "gói trả phí" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_pro_user_advanced_search_allowed(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.pro)

    with patch("app.services.chat_service.ChatService.chat", return_value=_fake_chat_response()):
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "hỏi thử", "searchMode": "advanced"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_admin_free_plan_advanced_search_allowed(isolated_app_client):
    """Admin luôn qua gate bất kể plan — role và plan là 2 trục độc lập."""
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.admin, plan=UserPlan.free)

    with patch("app.services.chat_service.ChatService.chat", return_value=_fake_chat_response()):
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "hỏi thử", "searchMode": "advanced"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_pro_user_expired_plan_blocked_403(isolated_app_client):
    client, session_factory = isolated_app_client
    expired = datetime.now(UTC) - timedelta(days=1)
    _, token = await _create_user(
        session_factory, role=UserRole.viewer, plan=UserPlan.pro, plan_expires_at=expired
    )

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "hỏi thử", "searchMode": "advanced"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_free_user_non_advanced_mode_not_blocked(isolated_app_client):
    """search_mode khác "advanced" (hoặc không gửi) -> gate không can thiệp, kể cả free."""
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer, plan=UserPlan.free)

    with patch("app.services.chat_service.ChatService.chat", return_value=_fake_chat_response()):
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "hỏi thử", "searchMode": "hybrid"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
