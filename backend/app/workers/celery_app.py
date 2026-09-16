import ssl

from celery import Celery

from app.core.config import settings

# Upstash Redis dùng scheme `rediss://` (Redis over TLS). Celery result backend
# BẮT BUỘC khai báo `ssl_cert_reqs` cho rediss, nếu không worker crash lúc khởi
# động: "A rediss:// URL must have parameter ssl_cert_reqs...". CERT_NONE = mã hóa
# TLS nhưng không verify cert (khớp hành vi broker vốn đã default insecure).
_SSL_OPTS = {"ssl_cert_reqs": ssl.CERT_NONE}
_broker_use_ssl = _SSL_OPTS if settings.CELERY_BROKER_URL.startswith("rediss://") else None
_backend_use_ssl = _SSL_OPTS if settings.CELERY_RESULT_BACKEND.startswith("rediss://") else None

celery_app = Celery(
    "enterprise_rag",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.ingestion",
        "app.workers.tasks.sync",
        "app.workers.tasks.email",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_use_ssl=_broker_use_ssl,
    redis_backend_use_ssl=_backend_use_ssl,
    # Safety net GLOBAL — chỉ áp dụng cho task nào KHÔNG tự khai báo time_limit/
    # soft_time_limit riêng (xem @celery_app.task(...) từng task trong
    # workers/tasks/*.py — ingestion/sync/email đều đã set riêng, phù hợp độ nặng
    # từng loại). Không có giới hạn nào trước đây → 1 task treo (OpenAI API hang,
    # Neo4j deadlock) giữ worker slot vô thời hạn, không bao giờ nhường chỗ.
    # soft: raise SoftTimeLimitExceeded (task tự cleanup nếu catch được) trước khi
    # hard SIGKILL 60s sau.
    task_soft_time_limit=540,
    task_time_limit=600,
    task_routes={
        "app.workers.tasks.ingestion.*": {"queue": "ingestion"},
        "app.workers.tasks.sync.*": {"queue": "sync"},
        # Tái dùng queue "sync" (không thêm queue mới) — tránh phải đổi lệnh
        # `celery worker -Q ingestion,sync` đã ghi trong CLAUDE.md.
        "app.workers.tasks.email.*": {"queue": "sync"},
    },
)

# Đăng ký dead-letter queue (Task 2.2, xem workers/dlq.py) — bắt signal task_failure,
# ghi task thất bại vào Postgres `failed_tasks`. Import 1 lần ở đây (không phải
# task module nên không thuộc include=[...] ở trên) để signal receiver được đăng ký
# ngay khi celery_app load, dù entrypoint là API hay worker process.
from app.workers import dlq  # noqa: E402, F401
