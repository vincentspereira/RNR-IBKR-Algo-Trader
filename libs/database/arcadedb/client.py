"""ArcadeDB graph database client (Apache-2.0) — replaces the Neo4j client.

docker-compose runs ArcadeDB (not Neo4j). ArcadeDB exposes an HTTP API on port
2480 and speaks SQL, Cypher, Gremlin and MongoDB query languages. This client
uses ArcadeDB's native SQL over the HTTP ``/api/v1/command/{database}`` endpoint,
so it has no third-party dependency beyond the Python standard library
(``urllib``). It is a drop-in for the public surface of ``Neo4jClient``
(execute_query / create_node / create_relationship / find_nodes / health_check).

The Neo4j client in ``libs/database/neo4j`` is retained for anyone running a
real Neo4j server; the *deployed* infrastructure (and thus the default config)
points here.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from libs.common.config import get_config
from libs.common.errors import DatabaseException

logger = logging.getLogger(__name__)


class ArcadeDBError(DatabaseException):
    """Raised when an ArcadeDB HTTP call fails."""


class ArcadeDBClient:
    """ArcadeDB graph database client over the HTTP API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Initialize the ArcadeDB client.

        Args:
            base_url: HTTP base URL (e.g. http://localhost:2480); uses config default.
            database: ArcadeDB database name; uses config default.
            username: ArcadeDB user (``root`` by default); uses config default.
            password: ArcadeDB password; uses config default.
            timeout: Per-request timeout in seconds.
        """
        config = get_config()
        self.base_url = (base_url or config.database.arcadedb_url).rstrip("/")
        self.database = database or config.database.arcadedb_database
        self.username = username or config.database.arcadedb_user
        self.password = password or config.database.arcadedb_password
        self.timeout = timeout
        logger.info("arcadedb_client_initialized", base_url=self.base_url, database=self.database)

    # -- HTTP plumbing -------------------------------------------------------
    def _request(self, payload: Dict[str, Any], path: str = "") -> Any:
        """POST a JSON command to ArcadeDB and return the parsed response."""
        url = f"{self.base_url}/api/v1/command/{urllib.parse.quote(self.database)}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        # Basic auth.
        import base64
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise ArcadeDBError(f"ArcadeDB HTTP {e.code} for {payload!r}: {detail}") from e
        except urllib.error.URLError as e:
            raise ArcadeDBError(f"ArcadeDB unreachable at {self.base_url}: {e}") from e

    # -- Public API (mirrors Neo4jClient) ------------------------------------
    def execute_query(
        self, query: str, language: str = "sql", parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """Run a query in the given language (sql/cypher/gremlin/mongo).

        ArcadeDB does not take a separate parameters map for SQL the way the
        Neo4j driver does; callers should inline parameters. ``parameters`` is
        accepted for interface compatibility and ignored.
        """
        if parameters:
            logger.warning("arcadedb_parameters_ignored", note="inline parameters in SQL/Cypher")
        try:
            resp = self._request(
                {"language": language, "command": query, "serializer": "json"}
            )
            result = resp.get("result", resp) if isinstance(resp, dict) else resp
            if isinstance(result, list):
                return result
            return [result] if result is not None else []
        except ArcadeDBError:
            raise

    @staticmethod
    def _quote(value: Any) -> str:
        """Quote a Python value for ArcadeDB SQL (basic escaping)."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    def create_node(self, label: str, properties: Dict[str, Any]) -> Dict:
        """Create a vertex of ``label`` with the given properties."""
        sets = ", ".join(f"{k} = {self._quote(v)}" for k, v in properties.items())
        clause = f" SET {sets}" if sets else ""
        result = self.execute_query(f"CREATE VERTEX {label}{clause}")
        return result[0] if result else {}

    def create_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ):
        """Create an edge ``rel_type`` from ``from_id`` to ``to_id`` (ArcadeDB RIDs)."""
        sets = ""
        if properties:
            sets = " SET " + ", ".join(f"{k} = {self._quote(v)}" for k, v in properties.items())
        self.execute_query(
            f"CREATE EDGE {rel_type} FROM {from_id} TO {to_id}{sets}"
        )

    def find_nodes(self, label: str, properties: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """Find vertices of ``label`` optionally filtered by ``properties``."""
        if properties:
            where = " AND ".join(f"{k} = {self._quote(v)}" for k, v in properties.items())
            query = f"SELECT FROM {label} WHERE {where}"
        else:
            query = f"SELECT FROM {label}"
        return self.execute_query(query)

    def health_check(self) -> bool:
        """Check ArcadeDB health via the ready endpoint."""
        import base64
        url = f"{self.base_url}/api/v1/ready"
        req = urllib.request.Request(url, method="GET")
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            logger.error("arcadedb_health_check_failed", error=str(e))
            return False

    def close(self):
        """No persistent connection to close (stateless HTTP)."""
        logger.info("arcadedb_closed")


# Global client instance
_arcadedb_client: Optional[ArcadeDBClient] = None


def get_arcadedb_client() -> ArcadeDBClient:
    """Get the ArcadeDB client singleton."""
    global _arcadedb_client
    if _arcadedb_client is None:
        _arcadedb_client = ArcadeDBClient()
    return _arcadedb_client
