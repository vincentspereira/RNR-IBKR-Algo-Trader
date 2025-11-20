"""Qdrant vector database utilities."""
from typing import Optional, List, Dict, Any
from qdrant_client import QdrantClient as QdrantClientSDK
from qdrant_client.models import Distance, VectorParams, PointStruct

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.errors import DatabaseException

logger = get_logger(__name__)


class QdrantClient:
    """Qdrant vector database client."""
    
    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize Qdrant client.
        
        Args:
            url: Qdrant URL (uses config if not provided)
            api_key: Qdrant API key (uses config if not provided)
        """
        config = get_config()
        self.url = url or config.database.qdrant_url
        self.api_key = api_key or config.database.qdrant_api_key
        
        self.client = QdrantClientSDK(
            url=self.url,
            api_key=self.api_key
        )
        
        logger.info("qdrant_client_initialized", url=self.url)
    
    def create_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: str = "Cosine"
    ):
        """
        Create a collection.
        
        Args:
            collection_name: Name of the collection
            vector_size: Size of vectors
            distance: Distance metric (Cosine, Euclidean, Dot)
        """
        try:
            distance_map = {
                "Cosine": Distance.COSINE,
                "Euclidean": Distance.EUCLID,
                "Dot": Distance.DOT
            }
            
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=distance_map.get(distance, Distance.COSINE)
                )
            )
            logger.info("collection_created", collection=collection_name)
        except Exception as e:
            logger.error("create_collection_error", error=str(e))
            raise DatabaseException(f"Failed to create collection: {str(e)}")
    
    def upsert_vectors(
        self,
        collection_name: str,
        points: List[Dict[str, Any]]
    ):
        """
        Upsert vectors into collection.
        
        Args:
            collection_name: Collection name
            points: List of points with id, vector, and payload
        """
        try:
            point_structs = [
                PointStruct(
                    id=p['id'],
                    vector=p['vector'],
                    payload=p.get('payload', {})
                )
                for p in points
            ]
            
            self.client.upsert(
                collection_name=collection_name,
                points=point_structs
            )
            logger.info("vectors_upserted", collection=collection_name, count=len(points))
        except Exception as e:
            logger.error("upsert_error", error=str(e))
            raise DatabaseException(f"Failed to upsert vectors: {str(e)}")
    
    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 10,
        score_threshold: Optional[float] = None
    ) -> List[Dict]:
        """
        Search for similar vectors.
        
        Args:
            collection_name: Collection name
            query_vector: Query vector
            limit: Maximum number of results
            score_threshold: Minimum similarity score
            
        Returns:
            List of search results
        """
        try:
            results = self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold
            )
            
            return [
                {
                    'id': r.id,
                    'score': r.score,
                    'payload': r.payload
                }
                for r in results
            ]
        except Exception as e:
            logger.error("search_error", error=str(e))
            raise DatabaseException(f"Search failed: {str(e)}")
    
    def health_check(self) -> bool:
        """Check Qdrant connection health."""
        try:
            self.client.get_collections()
            return True
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False


# Global client instance
_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Get Qdrant client singleton."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient()
    return _qdrant_client
