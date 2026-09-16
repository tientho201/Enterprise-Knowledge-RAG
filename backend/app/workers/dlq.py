"""Dead-letter queue cho Celery — Task 2.2, xem .claude/tasks/production-ops-gaps.md
mục 2 + app/models/failed_task.py.

Celery KHÔNG có DLQ built-in như SQS/RabbitMQ. Thay vì tự tạo queue `*.failed` mới
(phải đổi lệnh `celery worker -Q ingestion,sync` + thêm consumer riêng), ghi task
thất bại vào bảng Postgres `failed_tasks` — đơn giản hơn, tái dùng hạ tầng DB đã có,
và admin xem lại được ngay qua GET /admin/failed-tasks (không cần thêm tool mới).

Bắt sự kiện qua Celery signal `task_failure` — signal này CHỈ fire khi exception
thật sự thoát khỏi task (hết `autoretry_for`/`self.retry()` retries), KHÔNG fire khi
`self.retry()` raise `Retry` giữa các lần retry (đó là signal `task_retry` khác) —
đúng yêu cầu "chỉ ghi sau khi hết retry", không ghi nhiễu mỗi lần retry.

Import module này 1 lần trong celery_app.py để đăng ký signal receiver — bản thân
module không định nghĩa task nào nên KHÔNG thêm vào `include=[...]`.
"""

import asyncio
import json
import logging

from celery.signals import task_failure

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Celery args/kwargs có thể chứa object không JSON-serializable (hiếm với các
    task hiện tại — toàn str/dict đơn giản) — fallback str() để không crash khi ghi
    JSON column thay vì làm mất luôn cả record lỗi."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _persist_failed_task(
    task_name: str,
    celery_task_id: str,
    args: tuple,
    kwargs: dict,
    exception: str,
    traceback_str: str | None,
) -> None:
    from app.db.session import AsyncSessionLocal, engine
    from app.repositories.failed_task_repo import FailedTaskRepository

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await FailedTaskRepository(db).create(
                task_name=task_name,
                celery_task_id=celery_task_id,
                exception=exception,
                args=[_json_safe(a) for a in args] if args else None,
                kwargs={k: _json_safe(v) for k, v in kwargs.items()} if kwargs else None,
                traceback=traceback_str,
            )
            await db.commit()

    async def _main() -> None:
        # Mirror workers/tasks/ingestion.py::ingest_document — asyncio.run() tạo event
        # loop mới mỗi lần gọi; dispose pool trong CHÍNH loop đã tạo connection, tránh
        # "Event loop is closed" ở lần task_failure kế tiếp.
        try:
            await _run()
        finally:
            await engine.dispose()

    try:
        asyncio.run(_main())
    except Exception:  # noqa: BLE001 — DLQ ghi log KHÔNG được làm crash worker
        logger.exception(
            "Failed to persist dead-letter record for task %s (celery_task_id=%s)",
            task_name,
            celery_task_id,
        )


@task_failure.connect
def on_task_failure(
    sender=None,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    traceback=None,  # noqa: ARG001 — Celery truyền traceback object thô, dùng einfo (đã format) thay vào
    einfo=None,
    **_extra,
) -> None:
    task_name = getattr(sender, "name", None) or str(sender) if sender else "unknown"
    _persist_failed_task(
        task_name=task_name,
        celery_task_id=task_id or "unknown",
        args=tuple(args) if args else (),
        kwargs=dict(kwargs) if kwargs else {},
        exception=str(exception) if exception else "unknown",
        traceback_str=str(einfo) if einfo else None,
    )
