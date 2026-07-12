"""Base connector interface for all external data sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ConnectorDocument:
    id: str
    title: str
    content: str
    source_url: str
    metadata: dict[str, Any]


class BaseConnector(ABC):
    """All connectors must implement load, sync, and diff."""

    @abstractmethod
    def load(self, **kwargs) -> list[ConnectorDocument]:
        """Load all documents from the source."""

    @abstractmethod
    def sync(self, **kwargs) -> dict:
        """Sync documents and return summary stats."""

    @abstractmethod
    def diff(self, last_sync_ts: float, **kwargs) -> list[ConnectorDocument]:
        """Return documents changed since last_sync_ts."""
