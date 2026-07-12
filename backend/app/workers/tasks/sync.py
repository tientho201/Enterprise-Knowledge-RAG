"""Celery tasks for external source connectors (Confluence, Slack, Google Drive)."""

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.sync.sync_confluence",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def sync_confluence(self, space_key: str) -> dict:
    """Sync all pages from a Confluence space."""
    logger.info("Syncing Confluence space: %s", space_key)
    try:
        from app.connectors.confluence import ConfluenceConnector

        connector = ConfluenceConnector()
        result = connector.sync(space_key)
        return result
    except Exception as exc:
        logger.error("Confluence sync failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="app.workers.tasks.sync.sync_slack",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def sync_slack(self, channel_id: str) -> dict:
    """Sync messages from a Slack channel."""
    logger.info("Syncing Slack channel: %s", channel_id)
    try:
        # TODO: implement Slack connector
        return {"channel_id": channel_id, "status": "not_implemented"}
    except Exception as exc:
        raise self.retry(exc=exc)
