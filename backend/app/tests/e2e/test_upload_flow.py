"""E2E tests require running infrastructure (LocalStack S3, PostgreSQL, Qdrant)."""
import pytest


@pytest.mark.skip(reason="Requires running infrastructure")
@pytest.mark.asyncio
async def test_upload_and_index_flow(client):
    """
    Full E2E: upload a document → expect 202 → poll until indexed.
    Skipped in CI without infrastructure.
    """
    pass
