"""
POST /audit-logs sau khi siết (quyết định D2): bản ghi do client tự khai luôn bị gắn
extra_data.source = "client", chỉ nhận loại config / research, khoá dành riêng của server
(source, dlp_flag, dlp_reason) bị LOẠI BỎ, có giới hạn độ dài và rate limit.

Gọi thẳng HTTP qua ASGI transport với SQLite in-memory — cùng kỹ thuật cô lập DB như
test_admin_users.py / test_plan_gate.py. Redis của rate limiter được thay bằng bản giả
trong bộ nhớ nên không cần Redis thật.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.audit_log_repo import AuditLogRepository
from app.schemas.audit_log import (
    AUDIT_ACTION_MAX_LENGTH,
    AUDIT_EXTRA_DATA_MAX_JSON_LENGTH,
    AUDIT_RESOURCE_ID_MAX_LENGTH,
)

URL = "/api/v1/audit-logs"


class FakeRedis:
    """Đủ 3 lệnh rate_limiter dùng: INCR, EXPIRE, TTL."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.expires.get(key, -1)


@pytest_asyncio.fixture
async def audit_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    fake_redis = FakeRedis()

    # Patch đúng tên đã bind trong module dùng nó (import eager) — xem test_plan_gate.py.
    with (
        patch("app.core.dependencies.AsyncSessionLocal", session_factory),
        patch("app.core.rate_limit.get_redis", return_value=fake_redis),
    ):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory, fake_redis

    await engine.dispose()


async def _create_user(session_factory) -> tuple[str, dict[str, str]]:
    async with session_factory() as db:
        user = User(
            email=f"audit-{uuid.uuid4().hex}@test.local",
            password_hash="unused",
            role=UserRole.viewer,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    return user_id, {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _stored_logs(session_factory, user_id: str) -> list[AuditLog]:
    async with session_factory() as db:
        result = await db.execute(select(AuditLog).where(AuditLog.user_id == user_id))
        return list(result.scalars().all())


# ── Payload hợp lệ (đúng hình dạng frontend/lib/api.ts::auditLogsAPI.create gửi) ──────────


@pytest.mark.parametrize(
    "payload",
    [
        # addAuditLog(action, "config", details)
        {
            "action": "Người dùng An đăng nhập thành công",
            "resource_type": "config",
            "extra_data": {"details": "Email: an@test.local"},
        },
        # addAuditLog(action, "research") — không có details → extra_data: null
        {"action": "Đã xóa báo cáo: Báo cáo Q3", "resource_type": "research", "extra_data": None},
    ],
)
async def test_frontend_shaped_payload_is_accepted(audit_client, payload):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(URL, json=payload, headers=headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == payload["action"]
    assert body["resource_type"] == payload["resource_type"]
    assert body["user_id"] == user_id
    assert body["extra_data"]["source"] == "client"
    # `details` (frontend đọc lại ở refreshAuditLogs) phải còn nguyên.
    expected_details = (payload["extra_data"] or {}).get("details")
    assert body["extra_data"].get("details") == expected_details

    stored = await _stored_logs(session_factory, user_id)
    assert len(stored) == 1
    assert stored[0].extra_data["source"] == "client"


# ── Whitelist loại bản ghi ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("resource_type", ["query", "upload", "document", "Config", "", None])
async def test_resource_type_outside_whitelist_is_rejected(audit_client, resource_type):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(
        URL, json={"action": "giả log hệ thống", "resource_type": resource_type}, headers=headers
    )

    assert resp.status_code == 422
    assert await _stored_logs(session_factory, user_id) == []


async def test_missing_resource_type_is_rejected(audit_client):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(URL, json={"action": "thiếu loại"}, headers=headers)

    assert resp.status_code == 422
    assert await _stored_logs(session_factory, user_id) == []


# ── Khoá dành riêng + source ───────────────────────────────────────────────────────────────


async def test_reserved_keys_are_stripped_and_source_forced_to_client(audit_client):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(
        URL,
        json={
            "action": "cố giả cờ DLP",
            "resource_type": "config",
            "extra_data": {
                "dlp_flag": True,
                "dlp_reason": "bulk",
                "source": "server",
                "DLP_Flag": True,
                " Source ": "system",
                "details": "giữ lại",
            },
        },
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["extra_data"] == {"details": "giữ lại", "source": "client"}

    stored = await _stored_logs(session_factory, user_id)
    assert len(stored) == 1
    assert stored[0].extra_data == {"details": "giữ lại", "source": "client"}


async def test_top_level_server_fields_from_client_are_ignored(audit_client):
    """Client không tự đặt được source / user_id / ip_address ở cấp ngoài cùng của body."""
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(
        URL,
        json={
            "action": "đổi cấu hình",
            "resource_type": "config",
            "source": "server",
            "user_id": "someone-else",
            "ip_address": "10.0.0.1",
        },
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["ip_address"] != "10.0.0.1"
    assert body["extra_data"] == {"source": "client"}


# ── Giới hạn độ dài ────────────────────────────────────────────────────────────────────────


async def test_action_at_limit_accepted_and_over_limit_rejected(audit_client):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    ok = await client.post(
        URL,
        json={"action": "a" * AUDIT_ACTION_MAX_LENGTH, "resource_type": "config"},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text

    for length in (AUDIT_ACTION_MAX_LENGTH + 1, 301):
        resp = await client.post(
            URL, json={"action": "a" * length, "resource_type": "config"}, headers=headers
        )
        assert resp.status_code == 422

    assert len(await _stored_logs(session_factory, user_id)) == 1


async def test_empty_action_is_rejected(audit_client):
    client, session_factory, _ = audit_client
    _, headers = await _create_user(session_factory)

    resp = await client.post(URL, json={"action": "", "resource_type": "config"}, headers=headers)

    assert resp.status_code == 422


async def test_resource_id_over_limit_is_rejected(audit_client):
    client, session_factory, _ = audit_client
    _, headers = await _create_user(session_factory)

    resp = await client.post(
        URL,
        json={
            "action": "x",
            "resource_type": "research",
            "resource_id": "r" * (AUDIT_RESOURCE_ID_MAX_LENGTH + 1),
        },
        headers=headers,
    )

    assert resp.status_code == 422


async def test_oversized_extra_data_is_rejected(audit_client):
    client, session_factory, _ = audit_client
    user_id, headers = await _create_user(session_factory)

    resp = await client.post(
        URL,
        json={
            "action": "x",
            "resource_type": "config",
            "extra_data": {"details": "d" * AUDIT_EXTRA_DATA_MAX_JSON_LENGTH},
        },
        headers=headers,
    )

    assert resp.status_code == 422
    assert await _stored_logs(session_factory, user_id) == []


# ── Rate limit ─────────────────────────────────────────────────────────────────────────────


async def test_exceeding_rate_limit_returns_429(audit_client):
    client, session_factory, fake_redis = audit_client
    user_id, headers = await _create_user(session_factory)
    payload = {"action": "đổi cấu hình", "resource_type": "config"}
    limit = settings.AUDIT_LOG_RATE_LIMIT_PER_MINUTE
    assert limit > 0, "test này giả định cấu hình mặc định (giới hạn dương)"

    # Đã dùng limit - 1 lượt trong cửa sổ hiện tại → lượt thứ `limit` vẫn qua.
    fake_redis.counts[f"ratelimit:audit-log:{user_id}"] = limit - 1
    assert (await client.post(URL, json=payload, headers=headers)).status_code == 201

    over = await client.post(URL, json=payload, headers=headers)
    assert over.status_code == 429
    assert "Retry-After" in over.headers
    assert len(await _stored_logs(session_factory, user_id)) == 1

    # Giới hạn tính theo từng user: user khác không bị ảnh hưởng.
    _, other_headers = await _create_user(session_factory)
    assert (await client.post(URL, json=payload, headers=other_headers)).status_code == 201


async def test_get_is_not_rate_limited(audit_client):
    client, session_factory, fake_redis = audit_client
    user_id, headers = await _create_user(session_factory)
    fake_redis.counts[f"ratelimit:audit-log:{user_id}"] = 10**6

    assert (await client.get(URL, headers=headers)).status_code == 200


@pytest.mark.parametrize("limit", [0, -1])
async def test_non_positive_limit_blocks_every_request(limit):
    """Chốt nghĩa của AUDIT_LOG_RATE_LIMIT_PER_MINUTE <= 0: KHÔNG phải "tắt giới hạn" —
    rate_limiter chặn mọi request (429) ngay từ lượt đầu, khi Redis hoạt động."""
    dependency = rate_limiter(limit, 60, "audit-log")
    request = MagicMock()

    with patch("app.core.rate_limit.get_redis", return_value=FakeRedis()):
        with pytest.raises(HTTPException) as exc_info:
            await dependency(request=request, user_id="user-1")

    assert exc_info.value.status_code == 429


# ── Không ảnh hưởng log do server ghi / GET giữ nguyên hành vi ─────────────────────────────


async def test_requires_authentication(audit_client):
    client, _, _ = audit_client

    resp = await client.post(URL, json={"action": "x", "resource_type": "config"})

    assert resp.status_code in (401, 403)


async def test_get_returns_only_own_logs_and_leaves_server_logs_untouched(audit_client):
    client, session_factory, _ = audit_client
    user_a, headers_a = await _create_user(session_factory)
    user_b, headers_b = await _create_user(session_factory)

    # Bản ghi do server tự ghi (như chat_service): đi thẳng qua repository, không qua service.
    server_extra = {"details": "Trích dẫn: 2", "dlp_flag": True, "dlp_reason": "bulk"}
    async with session_factory() as db:
        await AuditLogRepository(db).create(
            user_id=user_a,
            action='Chạy truy vấn RAG: "abc"',
            resource_type="query",
            resource_id="conv-1",
            extra_data=dict(server_extra),
        )
        await db.commit()

    client_payload = {"action": "đổi cấu hình", "resource_type": "config"}
    assert (await client.post(URL, json=client_payload, headers=headers_a)).status_code == 201
    assert (await client.post(URL, json=client_payload, headers=headers_b)).status_code == 201

    resp_a = await client.get(URL, headers=headers_a)
    assert resp_a.status_code == 200
    logs_a = resp_a.json()
    assert {log["user_id"] for log in logs_a} == {user_a}
    assert len(logs_a) == 2

    by_type = {log["resource_type"]: log for log in logs_a}
    # Log server: giữ nguyên cờ DLP, không bị gắn source.
    assert by_type["query"]["extra_data"] == server_extra
    assert by_type["query"]["resource_id"] == "conv-1"
    assert by_type["config"]["extra_data"] == {"source": "client"}

    logs_b = (await client.get(URL, headers=headers_b)).json()
    assert len(logs_b) == 1
    assert logs_b[0]["user_id"] == user_b
