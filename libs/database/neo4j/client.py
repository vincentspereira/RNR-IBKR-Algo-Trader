"""Neo4j graph database utilities."""
from typing import Optional, Dict, List, Any
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.errors import DatabaseException

logger = get_logger(__name__)


class Neo4jClient:
    """Neo4j graph database client."""
    
    def __init__(self, uri: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize Neo4j client.
        
        Args:
            uri: Neo4j URI (uses config if not provided)
            password: Neo4j password (uses config if not provided)
        """
        config = get_config()
        self.uri = uri or config.database.neo4j_uri
        self.password = password or config.database.neo4j_password
        
        self.driver: Driver = GraphDatabase.driver(
            self.uri,
            auth=("neo4j", self.password)
        )
        
        logger.info("neo4j_client_initialized", uri=self.uri)
    
    def execute_query(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        """
        Execute Cypher query.
        
        Args:
            query: Cypher query
            parameters: Query parameters
            
        Returns:
            Query results as list of dictionaries
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]
        except Neo4jError as e:
            logger.error("neo4j_query_error", query=query, error=str(e))
            raise DatabaseException(f"Neo4j query failed: {str(e)}")
    
    def create_node(self, label: str, properties: Dict[str, Any]) -> Dict:
        """
        Create a node.
        
        Args:
            label: Node label
            properties: Node properties
            
        Returns:
            Created node data
        """
        query = f"CREATE (n:{label} $props) RETURN n"
        result = self.execute_query(query, {"props": properties})
        return result[0]['n'] if result else {}
    
    def create_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: Optional[Dict] = None
    ):
        """
        Create relationship between nodes.
        
        Args:
            from_id: Source node ID
            to_id: Target node ID
            rel_type: Relationship type
            properties: Relationship properties
        """
        query = f"""
        MATCH (a), (b)
        WHERE id(a) = $from_id AND id(b) = $to_id
        CREATE (a)-[r:{rel_type} $props]->(b)
        RETURN r
        """
        self.execute_query(query, {
            "from_id": from_id,
            "to_id": to_id,
            "props": properties or {}
        })
    
    def find_nodes(self, label: str, properties: Optional[Dict] = None) -> List[Dict]:
        """
        Find nodes by label and properties.
        
        Args:
            label: Node label
            properties: Properties to match
            
        Returns:
            List of matching nodes
        """
        if properties:
            where_clause = " AND ".join([f"n.{k} = ${k}" for k in properties.keys()])
            query = f"MATCH (n:{label}) WHERE {where_clause} RETURN n"
            result = self.execute_query(query, properties)
        else:
            query = f"MATCH (n:{label}) RETURN n"
            result = self.execute_query(query)
        
        return [r['n'] for r in result]
    
    def health_check(self) -> bool:
        """Check Neo4j connection health."""
        try:
            self.execute_query("RETURN 1")
            return True
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False
    
    def close(self):
        """Close driver."""
        self.driver.close()
        logger.info("neo4j_closed")


# Global client instance
_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """Get Neo4j client singleton."""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient()
    return _neo4j_client
