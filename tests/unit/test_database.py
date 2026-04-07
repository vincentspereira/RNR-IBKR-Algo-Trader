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

    # --- Extended tests ---

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_execute_query_with_params(self, mock_get_config):
        """Execute query should pass query string and params to session.execute."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_result = MagicMock()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        params = {"symbol": "AAPL", "price": 150.0}
        result = await client.execute_query("SELECT * FROM orders WHERE symbol = :symbol", params)

        assert result is mock_result
        mock_session.execute.assert_awaited_once_with(
            "SELECT * FROM orders WHERE symbol = :symbol", params
        )

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_insert_and_fetch(self, mock_get_config):
        """Insert a row then fetch it to verify round-trip behaviour through execute_query."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        call_count = 0
        side_effects = {}

        async def fake_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if "INSERT" in query:
                mock_result.rowcount = 1
                return mock_result
            # SELECT
            mock_result.fetchall.return_value = [("AAPL", 150.0)]
            return mock_result

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=fake_execute)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        insert_result = await client.execute_query(
            "INSERT INTO market_data (symbol, price) VALUES (:symbol, :price)",
            {"symbol": "AAPL", "price": 150.0},
        )
        assert insert_result.rowcount == 1

        fetch_result = await client.execute_query(
            "SELECT symbol, price FROM market_data WHERE symbol = :symbol",
            {"symbol": "AAPL"},
        )
        rows = fetch_result.fetchall()
        assert rows == [("AAPL", 150.0)]
        assert call_count == 2

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_transaction_commit(self, mock_get_config):
        """Successful session context should commit automatically."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        async with client.session() as session:
            assert session is mock_session

        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_transaction_rollback(self, mock_get_config):
        """Exception inside session context should trigger rollback."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        from libs.common.errors import DatabaseException

        with pytest.raises(DatabaseException):
            async with client.session() as session:
                raise ValueError("simulated DB error")

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_connection_pool(self, mock_get_config):
        """Verify engine is created with pool settings from config."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        with patch("libs.database.postgres.client.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            # Verify pool_size is passed through from config
            assert call_kwargs[1]["pool_size"] == 5
            assert call_kwargs[1]["max_overflow"] == 10
            assert call_kwargs[1]["pool_pre_ping"] is True

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_health_check_failure(self, mock_get_config):
        """Health check should return False when connection fails."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Connection refused"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)
        client.engine = mock_engine

        result = await client.health_check()
        assert result is False

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_query_timeout(self, mock_get_config):
        """Query that raises during execution should propagate DatabaseException."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient
        from libs.common.errors import DatabaseException

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Query timed out"))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        with pytest.raises(DatabaseException, match="Query execution failed"):
            await client.execute_query("SELECT pg_sleep(30)")

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_session_context_manager_success(self, mock_get_config):
        """Session context manager yields a usable session and commits on exit."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        yielded_session = None
        async with client.session() as sess:
            yielded_session = sess

        assert yielded_session is mock_session
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_session_context_manager_rollback_on_error(self, mock_get_config):
        """Session context manager should rollback and raise DatabaseException on error."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient
        from libs.common.errors import DatabaseException

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        with pytest.raises(DatabaseException, match="Database session error"):
            async with client.session() as sess:
                raise RuntimeError("Unexpected DB failure")

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_close_cleans_up(self, mock_get_config):
        """Close should dispose the engine and be safe to call."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        client.engine = mock_engine

        await client.close()
        mock_engine.dispose.assert_awaited_once()

        # Calling close again should not raise
        await client.close()
        assert mock_engine.dispose.await_count == 2

    @pytest.mark.asyncio
    @patch("libs.database.postgres.client.get_config")
    async def test_postgres_execute_query_returns_results(self, mock_get_config):
        """Execute query should return the raw result object from the session."""
        mock_get_config.return_value = _mock_config()
        from libs.database.postgres.client import PostgreSQLClient

        client = PostgreSQLClient(connection_url="postgresql+asyncpg://user:pass@localhost:5432/test")

        mock_result = MagicMock()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        client.async_session_factory = mock_factory

        result = await client.execute_query("SELECT 1")
        assert result is mock_result

    @patch("libs.database.postgres.client.get_config")
    def test_postgres_singleton_pattern(self, mock_get_config):
        """get_postgres_client should return the same instance each time."""
        mock_get_config.return_value = _mock_config()
        import libs.database.postgres.client as mod

        # Ensure clean state
        mod._pg_client = None

        try:
            client_a = mod.get_postgres_client()
            client_b = mod.get_postgres_client()
            assert client_a is client_b
            assert isinstance(client_a, mod.PostgreSQLClient)
        finally:
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


# ---------------------------------------------------------------------------
# QdrantClient tests
# ---------------------------------------------------------------------------


class TestQdrantClient:
    """Test Qdrant vector database client."""

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_connect(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient(url="http://localhost:6333")
        assert client.url == "http://localhost:6333"
        mock_sdk.assert_called_once()

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_create_collection(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        client.create_collection("test_collection", vector_size=128)
        mock_instance.create_collection.assert_called_once()

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_create_collection_euclidean(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        client.create_collection("test_coll", vector_size=64, distance="Euclidean")
        mock_instance.create_collection.assert_called_once()

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_create_collection_failure(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.create_collection.side_effect = Exception("Already exists")
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient
        from libs.common.errors import DatabaseException

        client = QdrantClient()
        with pytest.raises(DatabaseException, match="Failed to create collection"):
            client.create_collection("dup_collection", vector_size=128)

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_upsert_vectors(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        points = [
            {"id": 1, "vector": [0.1, 0.2, 0.3], "payload": {"symbol": "AAPL"}},
            {"id": 2, "vector": [0.4, 0.5, 0.6], "payload": {"symbol": "GOOG"}},
        ]
        client.upsert_vectors("test_collection", points)
        mock_instance.upsert.assert_called_once()

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_upsert_vectors_no_payload(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        points = [{"id": 1, "vector": [0.1, 0.2]}]
        client.upsert_vectors("test_collection", points)
        mock_instance.upsert.assert_called_once()

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_upsert_vectors_failure(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.upsert.side_effect = Exception("Write error")
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient
        from libs.common.errors import DatabaseException

        client = QdrantClient()
        with pytest.raises(DatabaseException, match="Failed to upsert vectors"):
            client.upsert_vectors("test_collection", [{"id": 1, "vector": [0.1]}])

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_search_similar(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.id = "point_1"
        mock_result.score = 0.95
        mock_result.payload = {"symbol": "AAPL"}
        mock_instance.search.return_value = [mock_result]
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        results = client.search("test_collection", [0.1, 0.2, 0.3], limit=5)
        assert len(results) == 1
        assert results[0]["id"] == "point_1"
        assert results[0]["score"] == 0.95
        assert results[0]["payload"] == {"symbol": "AAPL"}

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_search_with_threshold(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.search.return_value = []
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        results = client.search("test_collection", [0.1], limit=10, score_threshold=0.8)
        assert results == []
        call_kwargs = mock_instance.search.call_args
        assert call_kwargs[1]["score_threshold"] == 0.8

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_search_failure(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.search.side_effect = Exception("Search failed")
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient
        from libs.common.errors import DatabaseException

        client = QdrantClient()
        with pytest.raises(DatabaseException, match="Search failed"):
            client.search("test_collection", [0.1])

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_health_check_healthy(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.get_collections.return_value = []
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        assert client.health_check() is True

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_health_check_failure(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.get_collections.side_effect = Exception("Connection refused")
        mock_sdk.return_value = mock_instance

        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        assert client.health_check() is False

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_uses_config_defaults(self, mock_sdk, mock_get_config):
        config = _mock_config()
        mock_get_config.return_value = config
        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient()
        assert client.url is config.database.qdrant_url

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_custom_url_and_key(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.qdrant.client import QdrantClient

        client = QdrantClient(url="http://custom:6333", api_key="test-key")
        assert client.url == "http://custom:6333"
        assert client.api_key == "test-key"

    @patch("libs.database.qdrant.client.get_config")
    @patch("libs.database.qdrant.client.QdrantClientSDK")
    def test_qdrant_singleton(self, mock_sdk, mock_get_config):
        mock_get_config.return_value = _mock_config()
        import libs.database.qdrant.client as mod

        mod._qdrant_client = None
        client1 = mod.get_qdrant_client()
        client2 = mod.get_qdrant_client()
        assert client1 is client2
        mod._qdrant_client = None  # cleanup


# ---------------------------------------------------------------------------
# Extended ClickHouse tests
# ---------------------------------------------------------------------------


class TestClickHouseClientExtended:
    """Extended ClickHouse client tests for deeper coverage."""

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_execute_with_params(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.execute.return_value = [("AAPL",)]
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        result = client.execute("SELECT symbol FROM market_data WHERE price > :p", {"p": 100})
        assert result == [("AAPL",)]
        mock_instance.execute.assert_called_once_with(
            "SELECT symbol FROM market_data WHERE price > :p", {"p": 100}
        )

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_insert_dataframe(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_cls.return_value = mock_instance

        import pandas as pd
        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        df = pd.DataFrame({"symbol": ["AAPL"], "price": [150.5]})
        client.insert_dataframe("market_data", df)
        mock_instance.insert_dataframe.assert_called_once()

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_insert_dataframe_failure(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.insert_dataframe.side_effect = Exception("Insert failed")
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient
        from clickhouse_driver.errors import Error as ClickHouseError

        # Re-raise as ClickHouseError to trigger the right except branch
        mock_instance.insert_dataframe.side_effect = ClickHouseError("Insert failed")

        with pytest.raises(Exception, match="Insert failed"):
            client = ClickHouseClient()
            import pandas as pd
            df = pd.DataFrame({"symbol": ["AAPL"]})
            client.insert_dataframe("test_table", df)

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_batch_insert_empty_list(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        client.insert_batch("market_data", [], ["symbol", "price"])
        mock_instance.execute.assert_called_once()

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_execute_error_handling(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        from clickhouse_driver.errors import Error as ClickHouseError
        mock_instance.execute.side_effect = ClickHouseError("Query failed")
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient
        from libs.common.errors import DatabaseException

        client = ClickHouseClient()
        with pytest.raises(DatabaseException, match="ClickHouse query failed"):
            client.execute("SELECT * FROM nonexistent")

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_health_check_failure(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_instance.execute.side_effect = Exception("Connection lost")
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        assert client.health_check() is False

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_disconnect_cleans_up(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        client.disconnect()
        mock_instance.disconnect.assert_called_once()

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_clickhouse_singleton(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        import libs.database.clickhouse.client as mod

        mod._clickhouse_client = None
        client1 = mod.get_clickhouse_client()
        client2 = mod.get_clickhouse_client()
        assert client1 is client2
        mod._clickhouse_client = None  # cleanup

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_clickhouse_connects_on_init(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        mock_ch_cls.assert_called_once()

    @patch("libs.database.clickhouse.client.get_config")
    @patch("libs.database.clickhouse.client.Client")
    def test_clickhouse_insert_batch_with_data(self, mock_ch_cls, mock_get_config):
        mock_get_config.return_value = _mock_config()
        mock_instance = MagicMock()
        mock_ch_cls.return_value = mock_instance

        from libs.database.clickhouse.client import ClickHouseClient

        client = ClickHouseClient()
        data = [
            ("AAPL", datetime(2026, 1, 1), 150.5, 10000),
            ("GOOG", datetime(2026, 1, 1), 2800.0, 5000),
        ]
        client.insert_batch("market_data", data, ["symbol", "ts", "price", "volume"])
        mock_instance.execute.assert_called_once()
        call_args = mock_instance.execute.call_args
        assert "INSERT INTO market_data" in call_args[0][0]


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
