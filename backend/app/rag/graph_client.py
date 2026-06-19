"""
Neo4j driver — singleton via lru_cache.

Supports graceful degradation: if Neo4j is unreachable, retrieval falls back
to dense-only mode (graph_weight is effectively ignored).
"""
import logging
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_neo4j_driver() -> Driver:
    """Return a cached synchronous Neo4j driver instance."""
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        max_connection_lifetime=3600,
        max_connection_pool_size=50,
    )


def ensure_graph_schema(driver: Driver) -> None:
    """
    Create indexes and constraints for the graph schema.
    Should be called once on application startup.
    """
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
            "FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE"
        )
        session.run(
            "CREATE INDEX chunk_document_id IF NOT EXISTS "
            "FOR (c:Chunk) ON (c.document_id)"
        )
    logger.info("Neo4j graph schema verified.")
