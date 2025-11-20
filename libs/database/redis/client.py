"""Redis database utilities."""
from typing import Optional, Any
import json
import redis.asyncio as aioredis
from redis.asyncio import Redis

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.errors import DatabaseException

logger = get_logger(__name__)


class RedisClient:
    """Redis client with connection pooling and caching utilities."""
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis client.
        
        Args:
            redis_url: Redis connection URL (uses config if not provided)
        """
        config = get_config()
        
        if redis_url is None:
            redis_url = f"redis://:{config.database.redis_password}@{config.database.redis_host}:{config.database.redis_port}/0"
        
        self.redis_url = redis_url
        self.client: Optional[Redis] = None
        
        logger.info("redis_client_initialized", url=redis_url)
    
    async def connect(self):
        """Establish Redis connection."""
        if self.client is None:
            self.client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=get_config().database.redis_pool_size
            )
            logger.info("redis_connected")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("redis_disconnected")
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        await self.connect()
        return await self.client.get(key)
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        """Set key-value pair with optional TTL."""
        await self.connect()
        if ttl:
            await self.client.setex(key, ttl, value)
        else:
            await self.client.set(key, value)
    
    async def delete(self, key: str):
        """Delete key."""
        await self.connect()
        await self.client.delete(key)
    
    async def get_json(self, key: str) -> Optional[Any]:
        """Get JSON value by key."""
        value = await self.get(key)
        return json.loads(value) if value else None
    
    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set JSON value with optional TTL."""
        await self.set(key, json.dumps(value), ttl)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        await self.connect()
        return await self.client.exists(key) > 0
    
    async def expire(self, key: str, ttl: int):
        """Set TTL on existing key."""
        await self.connect()
        await self.client.expire(key, ttl)
    
    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            await self.connect()
            await self.client.ping()
            return True
        except Exception as e:
            logger.error("redis_health_check_failed", error=str(e))
            return False


# Global client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
