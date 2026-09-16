"""Response Cache exact-match (app/rag/response_cache.py) — Task 5.2, xem
.claude/tasks/production-ops-gaps.md mục 5. Dùng FakeRedis tối giản (không cần
Redis thật) — chỉ implement get/set/incr, đủ cho logic module này."""

import pytest

from app.rag import response_cache


class FakeRedis:
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
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(response_cache, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def broken_redis(monkeypatch):
    redis = BrokenRedis()
    monkeypatch.setattr(response_cache, "get_redis", lambda: redis)
    return redis


@pytest.mark.asyncio
async def test_cache_miss_when_nothing_set(fake_redis):
    result = await response_cache.get_cached_answer("cau hoi", "user-a", None)
    assert result is None


@pytest.mark.asyncio
async def test_set_then_get_returns_same_payload(fake_redis):
    payload = {"final_answer": "42", "citations": [], "intent": "rag", "confidence_score": 1.0}
    await response_cache.set_cached_answer("cau hoi", "user-a", None, payload)
    result = await response_cache.get_cached_answer("cau hoi", "user-a", None)
    assert result == payload


@pytest.mark.asyncio
async def test_different_owner_id_does_not_share_cache(fake_redis):
    """BAT BUOC owner_id trong key — day la dieu kien an toan quan trong nhat cua
    module nay. User A khong duoc nhan cache cua user B du cung 1 cau hoi."""
    payload_a = {"final_answer": "answer for A", "citations": [], "intent": "rag",
                 "confidence_score": 1.0}
    await response_cache.set_cached_answer("cau hoi giong nhau", "user-a", None, payload_a)

    result_for_b = await response_cache.get_cached_answer("cau hoi giong nhau", "user-b", None)
    assert result_for_b is None


@pytest.mark.asyncio
async def test_different_document_ids_do_not_share_cache(fake_redis):
    payload = {"final_answer": "answer", "citations": [], "intent": "rag", "confidence_score": 1.0}
    await response_cache.set_cached_answer("q", "user-a", ["doc-1"], payload)

    result = await response_cache.get_cached_answer("q", "user-a", ["doc-2"])
    assert result is None


@pytest.mark.asyncio
async def test_bump_version_invalidates_old_cache_entry(fake_redis):
    payload = {"final_answer": "old answer", "citations": [], "intent": "rag",
               "confidence_score": 1.0}
    await response_cache.set_cached_answer("q", "user-a", None, payload)
    assert await response_cache.get_cached_answer("q", "user-a", None) == payload

    await response_cache.bump_version("user-a")

    assert await response_cache.get_cached_answer("q", "user-a", None) is None


@pytest.mark.asyncio
async def test_bump_version_for_owner_also_invalidates_admin_bucket(fake_redis):
    """Admin thay TAT CA tai lieu — 1 doc cua bat ky owner nao doi cung phai lam
    stale cache cua admin (owner_id=None), khong chi cache cua chinh owner do."""
    admin_payload = {"final_answer": "admin cached", "citations": [], "intent": "rag",
                      "confidence_score": 1.0}
    await response_cache.set_cached_answer("q", None, None, admin_payload)
    assert await response_cache.get_cached_answer("q", None, None) == admin_payload

    await response_cache.bump_version("user-a")

    assert await response_cache.get_cached_answer("q", None, None) is None


@pytest.mark.asyncio
async def test_fail_open_on_redis_error_get(broken_redis):
    result = await response_cache.get_cached_answer("q", "user-a", None)
    assert result is None


@pytest.mark.asyncio
async def test_fail_open_on_redis_error_set_and_bump(broken_redis):
    # KHÔNG được raise — set/bump phải fail-open, không crash luồng /chat hoặc upload
    await response_cache.set_cached_answer("q", "user-a", None, {"final_answer": "x"})
    await response_cache.bump_version("user-a")
