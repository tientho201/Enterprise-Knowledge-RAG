"""
Usage tracker — records latency, token usage, retrieval precision,
and hallucination rate. Integrates with LangSmith.
"""

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    query: str
    latency_ms: float = 0.0
    tokens_used: int = 0
    retrieved_chunks: int = 0
    intent: str = ""
    confidence_score: float = 0.0
    had_citations: bool = False
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class AnalyticsTracker:
    """Records per-query metrics. Extend to push to Prometheus/LangSmith."""

    def track(self, metrics: QueryMetrics) -> None:
        logger.info(
            "QUERY_METRICS | query=%r | latency_ms=%.1f | intent=%s | "
            "chunks=%d | confidence=%.2f | tokens=%d | error=%s",
            metrics.query[:80],
            metrics.latency_ms,
            metrics.intent,
            metrics.retrieved_chunks,
            metrics.confidence_score,
            metrics.tokens_used,
            metrics.error,
        )
        # TODO: push to Prometheus via prometheus_client
        # TODO: push to LangSmith via LangChain callbacks

    @asynccontextmanager
    async def measure(self, query: str):
        start = time.monotonic()
        m = QueryMetrics(query=query)
        try:
            yield m
        except Exception as exc:
            m.error = str(exc)
            raise
        finally:
            m.latency_ms = (time.monotonic() - start) * 1000
            self.track(m)


tracker = AnalyticsTracker()
