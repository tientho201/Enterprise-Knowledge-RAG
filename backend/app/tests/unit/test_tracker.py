"""AnalyticsTracker (app/analytics/tracker.py) — Task 3.1, xem
.claude/tasks/production-ops-gaps.md mục 3. Trước đây tracker có sẵn nhưng KHÔNG
node/service nào gọi (dead code) — giờ đã wire vào chat_service.py::chat()/
chat_stream() (bọc toàn bộ graph run). Test này verify chính tracker hoạt động
đúng theo cách chat_service.py đang dùng (set field trong block, đọc lại sau khi
block thoát)."""

import pytest

from app.analytics.tracker import AnalyticsTracker, QueryMetrics


@pytest.mark.asyncio
async def test_measure_records_fields_set_inside_block():
    tracker = AnalyticsTracker()
    captured: list[QueryMetrics] = []
    tracker.track = captured.append  # type: ignore[method-assign]

    async with tracker.measure("cau hoi test") as metrics:
        metrics.intent = "rag"
        metrics.confidence_score = 0.8
        metrics.retrieved_chunks = 5
        metrics.had_citations = True

    assert len(captured) == 1
    recorded = captured[0]
    assert recorded.query == "cau hoi test"
    assert recorded.intent == "rag"
    assert recorded.confidence_score == 0.8
    assert recorded.retrieved_chunks == 5
    assert recorded.had_citations is True
    assert recorded.error is None
    assert recorded.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_measure_captures_error_and_reraises():
    tracker = AnalyticsTracker()
    captured: list[QueryMetrics] = []
    tracker.track = captured.append  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="boom"):
        async with tracker.measure("cau hoi loi"):
            raise ValueError("boom")

    assert len(captured) == 1
    assert captured[0].error == "boom"


@pytest.mark.asyncio
async def test_measure_default_metrics_when_nothing_set():
    tracker = AnalyticsTracker()
    captured: list[QueryMetrics] = []
    tracker.track = captured.append  # type: ignore[method-assign]

    async with tracker.measure("cau hoi rong"):
        pass

    assert captured[0].intent == ""
    assert captured[0].retrieved_chunks == 0
    assert captured[0].had_citations is False
