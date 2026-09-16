"""Verify moi Celery task co time_limit/soft_time_limit hop ly — Task 2.1, xem
.claude/tasks/production-ops-gaps.md muc 2. Truoc day khong co gioi han nao, 1 task
treo (OpenAI API hang, Neo4j deadlock) giu worker slot vo thoi han."""

from app.workers.celery_app import celery_app
from app.workers.tasks.email import send_otp_email
from app.workers.tasks.ingestion import (
    delete_chat_attachments,
    delete_document_vectors,
    ingest_document,
    reindex_document,
)
from app.workers.tasks.sync import sync_confluence, sync_slack


def test_global_fallback_limits_configured():
    assert celery_app.conf.task_soft_time_limit == 540
    assert celery_app.conf.task_time_limit == 600


def test_ingest_document_has_widest_limit_of_all_tasks():
    """ingest_document lam viec nang nhat (embed + Qdrant + Neo4j) nen phai co limit
    rong nhat trong tat ca task — regression guard neu ai vo tinh sua nham."""
    all_limits = [
        delete_document_vectors.time_limit,
        reindex_document.time_limit,
        delete_chat_attachments.time_limit,
        sync_confluence.time_limit,
        sync_slack.time_limit,
        send_otp_email.time_limit,
    ]
    assert ingest_document.time_limit == 360
    assert ingest_document.soft_time_limit == 300
    assert all(limit < ingest_document.time_limit for limit in all_limits)


def test_every_task_has_soft_limit_strictly_less_than_hard_limit():
    """soft phai luon < hard, neu khong SoftTimeLimitExceeded khong bao gio co co
    hoi raise truoc khi worker bi SIGKILL."""
    tasks = [
        ingest_document,
        delete_document_vectors,
        reindex_document,
        delete_chat_attachments,
        sync_confluence,
        sync_slack,
        send_otp_email,
    ]
    for task in tasks:
        assert task.soft_time_limit is not None, f"{task.name} thieu soft_time_limit"
        assert task.time_limit is not None, f"{task.name} thieu time_limit"
        assert task.soft_time_limit < task.time_limit, f"{task.name}: soft >= hard"


def test_lightest_tasks_have_tightest_limits():
    assert send_otp_email.time_limit <= 30
    assert reindex_document.time_limit <= 60
    assert delete_chat_attachments.time_limit <= 60
