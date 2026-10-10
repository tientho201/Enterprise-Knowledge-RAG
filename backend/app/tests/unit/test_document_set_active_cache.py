"""DocumentService.set_active phải vô hiệu Response Cache của CHỦ SỞ HỮU tài liệu.

Bật/tắt tài liệu đổi tập tài liệu RAG được dùng → câu trả lời đã cache (TTL 30 phút,
app/rag/response_cache.py) trở thành stale. Cùng cơ chế với upload/delete/reindex:
`bump_version(doc.owner_id)`.

Hai lớp test:
  - Lớp "gọi đúng": monkeypatch `app.services.document_service.bump_version` để khẳng
    định được await đúng 1 lần, đúng owner.
  - Lớp "hiệu lực thật": chỉ thay Redis bằng FakeRedis, để bump_version thật chạy và
    kiểm tra entry cache cũ không còn tra được.
Dùng SQLite in-memory (fixture db_session), không cần Redis/S3/Celery thật.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.document import DocumentType
from app.rag import response_cache
from app.services import document_service
from app.services.document_service import DocumentService

USER_A = "user-aaaa"
USER_B = "user-bbbb"
ADMIN = "user-admin"

PAYLOAD = {"final_answer": "cached", "citations": [], "intent": "rag", "confidence_score": 1.0}


class FakeRedis:
    """Tối giản — đủ get/set/incr cho response_cache (giống test_response_cache.py)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.store[key] = value

    async def incr(self, key: str) -> int:
        current = int(self.store.get(key, "0")) + 1
        self.store[key] = str(current)
        return current


class BrokenRedis:
    """Giả lập Redis lỗi — mọi method raise, để verify fail-open."""

    async def get(self, *_a, **_k):
        raise ConnectionError("redis down")

    async def set(self, *_a, **_k):
        raise ConnectionError("redis down")

    async def incr(self, *_a, **_k):
        raise ConnectionError("redis down")


@pytest.fixture
def bump_mock(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(document_service, "bump_version", mock)
    return mock


@pytest.fixture
def fake_redis(monkeypatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(response_cache, "get_redis", lambda: redis)
    return redis


async def _seed(db, owner_id: str | None = USER_A):
    svc = DocumentService(db)
    doc = await svc.repo.create(name="a.pdf", doc_type=DocumentType.pdf, owner_id=owner_id)
    await db.flush()
    return svc, doc


# ── Lớp "gọi đúng" ────────────────────────────────────────────────────────────


async def test_deactivate_bumps_owner_cache_once(db_session, bump_mock):
    svc, doc = await _seed(db_session)

    res = await svc.set_active(doc.id, user_id=USER_A, is_active=False)

    assert res.is_active is False
    bump_mock.assert_awaited_once_with(USER_A)


async def test_activate_bumps_owner_cache_once(db_session, bump_mock):
    svc, doc = await _seed(db_session)
    await svc.set_active(doc.id, user_id=USER_A, is_active=False)
    bump_mock.reset_mock()

    res = await svc.set_active(doc.id, user_id=USER_A, is_active=True)

    assert res.is_active is True
    bump_mock.assert_awaited_once_with(USER_A)


async def test_admin_toggle_bumps_document_owner_not_actor(db_session, bump_mock):
    """Admin tắt tài liệu của USER_B → bump theo USER_B (chủ tài liệu), KHÔNG theo
    admin đang thao tác."""
    svc, doc = await _seed(db_session, owner_id=USER_B)

    await svc.set_active(doc.id, user_id=ADMIN, is_active=False, is_admin=True)

    bump_mock.assert_awaited_once_with(USER_B)


async def test_admin_toggle_legacy_doc_bumps_admin_bucket(db_session, bump_mock):
    """Doc legacy (owner=None) chỉ admin thấy → bump bucket admin (owner_id=None)."""
    svc, doc = await _seed(db_session, owner_id=None)

    await svc.set_active(doc.id, user_id=ADMIN, is_active=False, is_admin=True)

    bump_mock.assert_awaited_once_with(None)


async def test_non_owner_gets_404_and_no_bump(db_session, bump_mock):
    svc, doc = await _seed(db_session, owner_id=USER_B)

    with pytest.raises(HTTPException) as exc:
        await svc.set_active(doc.id, user_id=USER_A, is_active=False)

    assert exc.value.status_code == 404
    bump_mock.assert_not_awaited()
    # Tài liệu của USER_B không bị đổi trạng thái.
    assert (await svc.repo.get_by_id(doc.id)).is_active is True


async def test_missing_document_gets_404_and_no_bump(db_session, bump_mock):
    svc = DocumentService(db_session)

    with pytest.raises(HTTPException) as exc:
        await svc.set_active("khong-ton-tai", user_id=USER_A, is_active=False)

    assert exc.value.status_code == 404
    bump_mock.assert_not_awaited()


async def test_bump_happens_after_state_change_is_flushed(db_session, monkeypatch):
    """Thứ tự: đổi is_active (flush) TRƯỚC, bump SAU — bump trước khi ghi thì 1
    request chen giữa sẽ cache lại câu trả lời theo trạng thái cũ dưới version mới."""
    svc, doc = await _seed(db_session)
    seen: list[bool] = []

    async def _spy(_owner_id):
        seen.append((await svc.repo.get_by_id(doc.id)).is_active)

    monkeypatch.setattr(document_service, "bump_version", _spy)

    await svc.set_active(doc.id, user_id=USER_A, is_active=False)

    assert seen == [False]


# ── Lớp "hiệu lực thật" (bump_version thật + FakeRedis) ───────────────────────


@pytest.mark.parametrize("is_active", [False, True])
async def test_toggle_invalidates_owner_cached_answer(db_session, fake_redis, is_active):
    svc, doc = await _seed(db_session)
    await response_cache.set_cached_answer("q", USER_A, None, PAYLOAD)
    assert await response_cache.get_cached_answer("q", USER_A, None) == PAYLOAD

    await svc.set_active(doc.id, user_id=USER_A, is_active=is_active)

    assert await response_cache.get_cached_answer("q", USER_A, None) is None


async def test_toggle_does_not_invalidate_other_users_cache(db_session, fake_redis):
    svc, doc = await _seed(db_session, owner_id=USER_A)
    await response_cache.set_cached_answer("q", USER_B, None, PAYLOAD)

    await svc.set_active(doc.id, user_id=USER_A, is_active=False)

    assert await response_cache.get_cached_answer("q", USER_B, None) == PAYLOAD


async def test_admin_toggle_invalidates_owner_and_admin_cache(db_session, fake_redis):
    """Admin tắt tài liệu của USER_B: cache của USER_B chết, cache admin
    (owner_id=None, thấy mọi tài liệu) cũng chết; cache của USER_A không liên quan."""
    svc, doc = await _seed(db_session, owner_id=USER_B)
    await response_cache.set_cached_answer("q", USER_B, None, PAYLOAD)
    await response_cache.set_cached_answer("q", None, None, PAYLOAD)
    await response_cache.set_cached_answer("q", USER_A, None, PAYLOAD)

    await svc.set_active(doc.id, user_id=ADMIN, is_active=False, is_admin=True)

    assert await response_cache.get_cached_answer("q", USER_B, None) is None
    assert await response_cache.get_cached_answer("q", None, None) is None
    assert await response_cache.get_cached_answer("q", USER_A, None) == PAYLOAD


async def test_redis_down_does_not_break_toggle(db_session, monkeypatch):
    """Fail-open như upload/delete/reindex: Redis lỗi không được làm hỏng thao tác
    bật/tắt — trạng thái DB vẫn đổi, không raise."""
    monkeypatch.setattr(response_cache, "get_redis", lambda: BrokenRedis())
    svc, doc = await _seed(db_session)

    res = await svc.set_active(doc.id, user_id=USER_A, is_active=False)

    assert res.is_active is False
    assert (await svc.repo.get_by_id(doc.id)).is_active is False
