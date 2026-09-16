from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.failed_task import FailedTask


class FailedTaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        task_name: str,
        celery_task_id: str,
        exception: str,
        args: list | None = None,
        kwargs: dict | None = None,
        traceback: str | None = None,
        retries: int = 0,
        queue: str | None = None,
    ) -> FailedTask:
        record = FailedTask(
            task_name=task_name,
            celery_task_id=celery_task_id,
            exception=exception,
            args=args,
            kwargs=kwargs,
            traceback=traceback,
            retries=retries,
            queue=queue,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def list_recent(self, limit: int = 100, resolved: bool | None = None) -> list[FailedTask]:
        stmt = select(FailedTask).order_by(FailedTask.created_at.desc()).limit(limit)
        if resolved is not None:
            stmt = stmt.where(FailedTask.resolved == resolved)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_resolved(self, failed_task_id: str) -> FailedTask | None:
        record = await self.db.get(FailedTask, failed_task_id)
        if record:
            record.resolved = True
            await self.db.flush()
            await self.db.refresh(record)
        return record
