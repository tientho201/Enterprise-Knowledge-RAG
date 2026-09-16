"""Prometheus /metrics endpoint (Task 3.3, xem .claude/tasks/production-ops-gaps.md
mục 3) — dùng prometheus-fastapi-instrumentator, không code thủ công."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    # Prometheus text format bắt đầu bằng comment "# HELP"/"# TYPE" cho mỗi metric.
    assert "# HELP" in resp.text
    assert "# TYPE" in resp.text


@pytest.mark.asyncio
async def test_metrics_endpoint_not_in_openapi_schema():
    """include_in_schema=False — /metrics là internal, không nên xuất hiện trong
    /docs cho user cuối, tránh lộ chi tiết vận hành."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/openapi.json")

    assert resp.status_code == 200
    assert "/metrics" not in resp.json().get("paths", {})


@pytest.mark.asyncio
async def test_metrics_counts_requests_by_route_and_status():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/health")
        resp = await client.get("/metrics")

    # excluded_handlers=["/health"] — /health KHÔNG được tính vào bộ đếm (tránh
    # nhiễu p95/p99 latency thật vì healthcheck gọi mỗi vài giây).
    assert "/health" not in resp.text
