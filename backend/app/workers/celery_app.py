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
    task_routes={
        "app.workers.tasks.ingestion.*": {"queue": "ingestion"},
        "app.workers.tasks.sync.*": {"queue": "sync"},
    },
)
