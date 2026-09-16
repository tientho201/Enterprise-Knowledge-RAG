"""add failed_tasks table (Celery dead-letter queue)

Task 2.2 (.claude/tasks/production-ops-gaps.md mục 2) — Celery không có DLQ built-in
như SQS/RabbitMQ. Bảng này lưu task thất bại SAU KHI hết autoretry_for/self.retry()
retries, ghi bởi signal task_failure (app/workers/dlq.py), để admin xem lại/replay
thủ công qua GET /admin/failed-tasks thay vì mất task âm thầm.

Revision ID: d1e2f3a4b5c6
Revises: 7e5777fabb9e
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "7e5777fabb9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "failed_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=False),
        sa.Column("args", sa.JSON(), nullable=True),
        sa.Column("kwargs", sa.JSON(), nullable=True),
        sa.Column("exception", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue", sa.String(length=100), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_failed_tasks_task_name", "failed_tasks", ["task_name"])
    op.create_index("ix_failed_tasks_celery_task_id", "failed_tasks", ["celery_task_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_failed_tasks_celery_task_id", table_name="failed_tasks")
    op.drop_index("ix_failed_tasks_task_name", table_name="failed_tasks")
    op.drop_table("failed_tasks")
