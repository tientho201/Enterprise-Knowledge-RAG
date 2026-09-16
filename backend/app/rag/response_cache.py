"""Response Cache (exact-match) cho /chat — Task 5.2, xem
.claude/tasks/production-ops-gaps.md mục 5 + skill prompt-engineering mục 3.2.

Cache hit → bỏ qua TOÀN BỘ pipeline (không gọi Qdrant/Neo4j, không gọi LLM) cho
câu hỏi verbatim giống nhau. Redis đã có sẵn (core/redis_client.py, dùng cho rate
limit/JWT blacklist) — tái dùng, không thêm dependency mới.

**BẮT BUỘC `owner_id` trong cache key** — thiếu owner_id nghĩa là user A có thể
nhận câu trả lời cache từ câu hỏi giống nhau của user B, vi phạm thẳng data
isolation đã implement công phu ở tầng retrieval (xem skill
`enterprise-knowledge-rag`). Đây là điều kiện an toàn quan trọng nhất của module này.

**Invalidation:** không xoá key chủ động theo document_id (exact-match key là hash,
không tra ngược được) — dùng "cache version" per-owner: mỗi lần tài liệu của 1 owner
thay đổi (upload/delete/reindex), `bump_version(owner_id)` tăng 1 counter Redis, làm
mọi cache key CŨ (tính theo version cũ) không còn được tra tới nữa (tự "chết", hết
TTL sẽ tự dọn). Admin thấy TẤT CẢ tài liệu nên bucket admin luôn bị bump kèm theo
bất kỳ thay đổi tài liệu nào của bất kỳ owner nào — không chỉ khi owner_id=None.
"""

import hashlib
import json
import logging

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 30 phút — tài liệu có thể đổi (reindex/xoá) giữa các lần hỏi; TTL ngắn để giảm
# rủi ro trả lời cache đã stale, đổi lấy hit-rate thấp hơn TTL dài. Cache version
# (bump_version) là lớp invalidate chính; TTL chỉ là an toàn phụ.
DEFAULT_TTL_SECONDS = 1800

_ADMIN_VERSION_KEY = "response_cache:version:__admin__"


def _version_key(owner_id: str | None) -> str:
    return f"response_cache:version:{owner_id}" if owner_id else _ADMIN_VERSION_KEY


async def _get_version(owner_id: str | None) -> int:
    try:
        redis = get_redis()
        raw = await redis.get(_version_key(owner_id))
        return int(raw) if raw else 0
    except Exception:  # noqa: BLE001 — cache fail-open, lỗi Redis không chặn request
        logger.warning("response_cache: doc version that bai (Redis loi)", exc_info=True)
        return 0


async def bump_version(owner_id: str | None) -> None:
    """Vô hiệu hoá toàn bộ cache exact-match của 1 owner — gọi khi upload/xoá/
    reindex tài liệu CỦA owner đó. Luôn bump kèm bucket admin (owner_id=None) vì
    admin thấy tất cả tài liệu — 1 doc của BẤT KỲ owner nào đổi cũng phải làm
    stale cache admin, không chỉ khi chính owner_id truyền vào là None."""
    try:
        redis = get_redis()
        await redis.incr(_version_key(owner_id))
        if owner_id is not None:
            await redis.incr(_ADMIN_VERSION_KEY)
    except Exception:  # noqa: BLE001 — fail-open, không làm crash luồng upload/delete
        logger.warning("response_cache: bump_version that bai (Redis loi)", exc_info=True)


def _build_key(
    query: str, owner_id: str | None, document_ids: list[str] | None, version: int
) -> str:
    doc_part = ",".join(sorted(document_ids)) if document_ids else ""
    raw = f"{owner_id or ''}|{query.strip().lower()}|{doc_part}|v{version}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"response_cache:entry:{digest}"


async def get_cached_answer(
    query: str, owner_id: str | None, document_ids: list[str] | None
) -> dict | None:
    try:
        redis = get_redis()
        version = await _get_version(owner_id)
        key = _build_key(query, owner_id, document_ids, version)
        raw = await redis.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:  # noqa: BLE001 — fail-open: cache lỗi → coi như miss, chạy pipeline bình thường
        logger.warning("response_cache: get_cached_answer that bai (Redis loi)", exc_info=True)
        return None


async def set_cached_answer(
    query: str,
    owner_id: str | None,
    document_ids: list[str] | None,
    payload: dict,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    try:
        redis = get_redis()
        version = await _get_version(owner_id)
        key = _build_key(query, owner_id, document_ids, version)
        await redis.set(key, json.dumps(payload), ex=ttl_seconds)
    except Exception:  # noqa: BLE001 — fail-open: cache lỗi không được crash luồng /chat
        logger.warning("response_cache: set_cached_answer that bai (Redis loi)", exc_info=True)
