"""Redis Market Data Cache.

Provides fast, TTL-based caching for market data using Redis.
Caches quotes (short TTL ~5s) and bars (longer TTL ~60s) to reduce
load on upstream data providers.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from libs.database.redis.client import RedisClient, get_redis_client
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("Redis client not available - market data cache will be in-memory only")

logger = structlog.get_logger(__name__)


class InMemoryFallback:
    """Simple in-memory fallback when Redis is unavailable."""

    def __init__(self):
        self._store: Dict[str, tuple] = {}  # key -> (data, expiry_time)

    def _is_expired(self, key: str) -> bool:
        """Check if a key has expired."""
        import time
        if key in self._store:
            _, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return True
            return False
        return True

    async def get(self, key: str) -> Optional[str]:
        if self._is_expired(key):
            return None
        return self._store[key][0]

    async def set(self, key: str, value: str, ttl: int = 5):
        import time
        self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str):
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return not self._is_expired(key)


class MarketDataCache:
    """Redis-backed cache for market data.

    Features:
    - Quote caching with configurable TTL (default 5 seconds)
    - OHLCV bar caching with longer TTL (default 60 seconds)
    - In-memory fallback when Redis is unavailable
    - JSON serialization for complex data structures
    """

    def __init__(self, redis_client: Optional[RedisClient] = None):
        self._redis = redis_client
        self._fallback = InMemoryFallback()
        self._redis_available: Optional[bool] = None

    @property
    def _client(self):
        """Get Redis client, falling back to in-memory if unavailable."""
        if self._redis_available is None:
            self._check_redis_availability()

        if self._redis_available:
            return self._redis
        return self._fallback

    def _check_redis_availability(self):
        """Check if Redis is available."""
        if REDIS_AVAILABLE and self._redis:
            self._redis_available = True
        elif REDIS_AVAILABLE:
            try:
                self._redis = get_redis_client()
                self._redis_available = True
            except Exception:
                self._redis_available = False
                logger.warning("redis_unavailable_using_in_memory_cache")
        else:
            self._redis_available = False
            logger.warning("redis_not_installed_using_in_memory_cache")

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached quote if fresh enough.

        Args:
            symbol: Symbol to look up

        Returns:
            Quote dict with bid, ask, last, volume, timestamp or None
        """
        key = f"quote:{symbol}"
        try:
            client = self._client
            if self._redis_available:
                data = await client.get_json(key)
            else:
                raw = await client.get(key)
                data = json.loads(raw) if raw else None

            if data and data.get("timestamp"):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                )).total_seconds()
                if age <= 5.0:
                    return data

            return None
        except Exception as e:
            logger.error("cache_get_quote_error", symbol=symbol, error=str(e))
            return None

    async def set_quote(
        self,
        symbol: str,
        data: Dict[str, Any],
        ttl: float = 5.0,
    ):
        """Cache a quote with TTL.

        Args:
            symbol: Symbol identifier
            data: Quote data dict
            ttl: Time-to-live in seconds (default 5)
        """
        key = f"quote:{symbol}"
        try:
            if "timestamp" not in data:
                data["timestamp"] = datetime.now(timezone.utc).isoformat()

            client = self._client
            if self._redis_available:
                await client.set_json(key, data, ttl=int(ttl))
            else:
                await client.set(key, json.dumps(data), ttl=int(ttl))
        except Exception as e:
            logger.error("cache_set_quote_error", symbol=symbol, error=str(e))

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached bars for a symbol/timeframe.

        Args:
            symbol: Symbol to look up
            timeframe: Bar timeframe (e.g. '1 min', '5 mins', '1 day')

        Returns:
            List of bar dicts or None
        """
        key = f"bars:{symbol}:{timeframe}"
        try:
            client = self._client
            if self._redis_available:
                data = await client.get_json(key)
            else:
                raw = await client.get(key)
                data = json.loads(raw) if raw else None

            if data and isinstance(data, list):
                return data
            return None
        except Exception as e:
            logger.error("cache_get_bars_error", symbol=symbol, error=str(e))
            return None

    async def set_bars(
        self,
        symbol: str,
        timeframe: str,
        data: List[Dict[str, Any]],
        ttl: float = 60.0,
    ):
        """Cache bars for a symbol/timeframe.

        Args:
            symbol: Symbol identifier
            timeframe: Bar timeframe
            data: List of bar dicts
            ttl: Time-to-live in seconds (default 60)
        """
        key = f"bars:{symbol}:{timeframe}"
        try:
            client = self._client
            if self._redis_available:
                await client.set_json(key, data, ttl=int(ttl))
            else:
                await client.set(key, json.dumps(data), ttl=int(ttl))
        except Exception as e:
            logger.error("cache_set_bars_error", symbol=symbol, error=str(e))

    async def get_bars_dataframe(
        self,
        symbol: str,
        timeframe: str,
    ):
        """Get cached bars as pandas DataFrame.

        Args:
            symbol: Symbol to look up
            timeframe: Bar timeframe

        Returns:
            pandas DataFrame or None
        """
        bars = await self.get_bars(symbol, timeframe)
        if not bars or not PANDAS_AVAILABLE:
            return None

        try:
            df = pd.DataFrame(bars)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error("cache_bars_dataframe_error", symbol=symbol, error=str(e))
            return None

    async def invalidate(self, symbol: str):
        """Invalidate all cached data for a symbol.

        Args:
            symbol: Symbol to invalidate
        """
        patterns = [
            f"quote:{symbol}",
            f"bars:{symbol}:*",
        ]

        try:
            if self._redis_available and self._redis and hasattr(self._redis, 'client'):
                for pattern in patterns:
                    if "*" in pattern:
                        keys = []
                        async for key in self._redis.client.scan_iter(match=pattern):
                            keys.append(key)
                        if keys:
                            await self._redis.client.delete(*keys)
                    else:
                        await self._redis.delete(pattern)
            else:
                for pattern in patterns:
                    if "*" not in pattern:
                        await self._fallback.delete(pattern)
        except Exception as e:
            logger.error("cache_invalidate_error", symbol=symbol, error=str(e))

    async def invalidate_bars(self, symbol: str, timeframe: str):
        """Invalidate cached bars for a specific symbol/timeframe.

        Args:
            symbol: Symbol to invalidate
            timeframe: Timeframe to invalidate
        """
        key = f"bars:{symbol}:{timeframe}"
        try:
            if self._redis_available and self._redis:
                await self._redis.delete(key)
            else:
                await self._fallback.delete(key)
        except Exception as e:
            logger.error("cache_invalidate_bars_error", symbol=symbol, error=str(e))


# Singleton
_market_data_cache: Optional[MarketDataCache] = None


def get_market_data_cache() -> MarketDataCache:
    """Get the global MarketDataCache instance."""
    global _market_data_cache
    if _market_data_cache is None:
        _market_data_cache = MarketDataCache()
    return _market_data_cache
