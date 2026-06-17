"""Confluence connector — syncs pages from a Confluence space."""
import os

from app.connectors.base import BaseConnector, ConnectorDocument


class ConfluenceConnector(BaseConnector):
    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        api_token: str | None = None,
    ):
        self.base_url = base_url or os.getenv("CONFLUENCE_BASE_URL", "")
        self.username = username or os.getenv("CONFLUENCE_USERNAME", "")
        self.api_token = api_token or os.getenv("CONFLUENCE_API_TOKEN", "")

    def _get_client(self):
        import httpx
        return httpx.Client(
            base_url=self.base_url,
            auth=(self.username, self.api_token),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def load(self, space_key: str, **kwargs) -> list[ConnectorDocument]:
        client = self._get_client()
        docs = []
        start = 0
        limit = 25

        while True:
            resp = client.get(
                "/wiki/rest/api/content",
                params={"spaceKey": space_key, "type": "page", "start": start, "limit": limit, "expand": "body.storage"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])

            for page in results:
                docs.append(
                    ConnectorDocument(
                        id=page["id"],
                        title=page["title"],
                        content=page["body"]["storage"]["value"],
                        source_url=f"{self.base_url}/wiki/spaces/{space_key}/pages/{page['id']}",
                        metadata={"space_key": space_key, "version": page.get("version", {}).get("number", 1)},
                    )
                )

            if data.get("_links", {}).get("next"):
                start += limit
            else:
                break

        return docs

    def sync(self, space_key: str = "", **kwargs) -> dict:
        docs = self.load(space_key)
        return {"synced": len(docs), "space_key": space_key}

    def diff(self, last_sync_ts: float, space_key: str = "", **kwargs) -> list[ConnectorDocument]:
        # Simplified: return all pages; production would filter by lastModified
        return self.load(space_key)
