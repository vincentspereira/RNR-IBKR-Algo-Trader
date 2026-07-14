"""ArcadeDB (Apache-2.0) graph database client.

The deployed infrastructure runs ArcadeDB, not Neo4j (see docker-compose.yml).
This package provides the canonical graph client; the legacy ``libs/database/
neo4j`` client is retained for anyone running a real Neo4j server.
"""
from .client import ArcadeDBClient, ArcadeDBError, get_arcadedb_client

__all__ = ["ArcadeDBClient", "ArcadeDBError", "get_arcadedb_client"]
