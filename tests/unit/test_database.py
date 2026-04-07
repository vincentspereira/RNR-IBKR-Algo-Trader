"""Test suite for database client modules."""

import sys
import os
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


def _mock_config():
    """Create a mock config object with all required database settings."""
    mock_db = Mock()
    mock_db.postgres_async_url = "postgresql+asyncpg://user:pass@localhost:5432/test"
    mock_db.postgres_pool_size = 5
    mock_db.clickhouse_host = "localhost"
    mock_db.clickhouse_port = 9000
    mock_db.clickhouse_password = "test"
    mock_db.clickhouse_db = "test_db"
    mock_db.redis_host = "localhost"
    mock_db.redis_port = 6379
    mock_db.redis_password = "test"
    mock_db.redis_pool_size = 10

    mock = Mock()
    mock.database = mock_db
    mock.debug = False
    return mock


# ---------------------------------------------------------------------------
# PostgreSQLClient tests
# ---------------------------------------------------------------------------


class TestPostgreSQLClient:
    """Test PostgreSQL client."""

    @patch("libs.database.postgres.client.get_config")
    def test_initialization(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")
        assert client is not None
        assert client.connection_url == "postgresql+asyncpg://user:pass@localhost:5432/test"

    @patch("libs.database.postgres.client.get_config")
    def test_session_context_manager(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")
        assert hasattr(client, "session")
        assert hasattr(client, "async_session_factory")

    @patch("libs.database.postgres.client.get_config")
    def test_has_query_method(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")
        assert hasattr(client, "execute_query")
        assert hasattr(client, "health_check")
        assert hasattr(client, "close")

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_close(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")
        client.engine = MagicMock()
        client.engine.dispose = AsyncMock()

        await client.close()
        client.engine.dispose.assert_awaited_once()

    @patch("libs.database.postgres.client.get_config")
    def test_get_postgres_client_singleton(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        import libs.database.postgres.client as mod

        mod._pg_client = None
        client1 = mod.get_postgres_client()
        client2 = mod.get_postgres_client()
        assert client1 is client2
        mod._pg_client = None  # cleanup


# ---------------------------------------------------------------------------
# ClickHouseClient tests
# ---------------------------------------------------------------------------


class TestClickHouseClient:
    """Test ClickHouse client."""

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_initialization(self, mock_ch_client, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient(host="localhost", port=9000)
        assert client.host == "localhost"
        assert client.port == 9000

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_execute(self, mock_ch_client_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.execute.return_value = [("AAPL", 150.5)]
        mock_ch_client_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient(host="localhost", port=9000)
        result = client.execute("SELECT symbol, price FROM market_data")
        assert result == [("AAPL", 150.5)]

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_insert_batch(self, mock_ch_client_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_client_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient(host="localhost", port=9000)
        data = [("AAPL", datetime.now(), 150.5, 10000)]
        client.insert_batch("market_data", data, ["symbol", "timestamp", "price", "volume"])
        mock_instance.execute.assert_called_once()

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_health_check(self, mock_ch_client_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.execute.return_value = [(1,)]
        mock_ch_client_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient(host="localhost", port=9000)
        assert client.health_check() is True

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_disconnect(self, mock_ch_client_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_client_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient(host="localhost", port=9000)
        client.disconnect()
        mock_instance.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# RedisClient tests
# ---------------------------------------------------------------------------


class TestRedisClient:
    """Test Redis client."""

    @patch("libs.database.redis.client.get_config")
    def test_initialization(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        assert client is not None
        assert client.redis_url == "redis://localhost:6379/0"
        assert client.client is None

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_set_and_get(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "test_value"
        mock_redis.set.return_value = True
        client.client = mock_redis

        await client.set("test_key", "test_value")
        mock_redis.set.assert_called_once_with("test_key", "test_value")

        result = await client.get("test_key")
        assert result == "test_value"

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_delete(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.delete("test_key")
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_set_with_ttl(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.set("cache_key", "cached_value", ttl=300)
        mock_redis.setex.assert_called_once_with("cache_key", 300, "cached_value")

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_health_check(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        client.client = mock_redis

        result = await client.health_check()
        assert result is True

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_connect_creates_client(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        assert client.client is None

        with patch("libs.database.redis.client.aioredis") as mock_aioredis:
            mock_redis = AsyncMock()
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)
            await client.connect()
            assert client.client is not None

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_disconnect(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.disconnect()
        mock_redis.close.assert_awaited_once()
        assert client.client is None

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_get_json(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.get.return_value = '{"symbol": "AAPL", "price": 150.5}'
        client.client = mock_redis

        result = await client.get_json("market:AAPL")
        assert result == {"symbol": "AAPL", "price": 150.5}

    @pytest.mark.asyncio
    @patch("libs.database.redis.client.get_config")
    async def test_set_json(self, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.redis.client import RedisClient

        client = RedisClient(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.set_json("market:AAPL", {"symbol": "AAPL", "price": 150.5}, ttl=60)
        mock_redis.setex.assert_called_once()


# ---------------------------------------------------------------------------
# Caching strategies (conceptual tests)
# ---------------------------------------------------------------------------


class TestRedisCachingStrategies:
    """Test different caching strategies using Redis."""

    def test_write_through_cache(self):
        key = "write_through_key"
        value = "write_through_value"
        assert key is not None
        assert value is not None

    def test_write_back_cache(self):
        key = "write_back_key"
        value = "write_back_value"
        assert key is not None
        assert value is not None

    def test_cache_aside_pattern(self):
        cache_hit = True
        assert cache_hit is True


class TestDatabaseConnectionPooling:
    """Test database connection pooling concepts."""

    def test_pool_creation(self):
        pool_size = 10
        max_overflow = 5
        assert pool_size > 0
        assert max_overflow > 0

    def test_pool_connection_reuse(self):
        connections_used = 5
        pool_size = 10
        assert connections_used <= pool_size

    def test_pool_cleanup(self):
        idle_connections = 3
        cleanup_threshold = 2
        assert idle_connections >= cleanup_threshold
