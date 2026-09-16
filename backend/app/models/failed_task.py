from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class FailedTask(Base, UUIDMixin, TimestampMixin):
    """Dead-letter cho Celery task thất bại SAU KHI hết `autoretry_for`/`self.retry()`
    retries — xem `app/workers/dlq.py` (signal `task_failure`) và
    `.claude/tasks/production-ops-gaps.md` Task 2.2.

    Celery KHÔNG có dead-letter queue built-in như SQS/RabbitMQ — tự ghi task thất
    bại vào bảng này để admin xem lại/replay thủ công (GET /admin/failed-tasks),
    thay vì mất task âm thầm khi hết retry.
    """

    __tablename__ = "failed_tasks"

    task_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    celery_task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    args: Mapped[list | None] = mapped_column(JSON, nullable=True)
    kwargs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exception: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Admin tick sau khi đã xem/xử lý (vd replay thủ công) — không tự động, không xoá
    # record để giữ lịch sử audit.
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
