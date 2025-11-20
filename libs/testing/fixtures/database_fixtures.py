"""Test fixtures for database connections."""
import pytest
import pytest_asyncio
from typing import AsyncGenerator

from libs.database.postgres import PostgreSQLClient
from libs.database.redis import RedisClient
from libs.database.clickhouse import ClickHouseClient
from libs.database.neo4j import Neo4jClient
from libs.database.qdrant import QdrantClient


@pytest_asyncio.fixture
async def postgres_client() -> AsyncGenerator[PostgreSQLClient, None]:
    """Provide PostgreSQL client for testing."""
    client = PostgreSQLClient()
    yield client
    await client.close()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[RedisClient, None]:
    """Provide Redis client for testing."""
    client = RedisClient()
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
def clickhouse_client() -> ClickHouseClient:
    """Provide ClickHouse client for testing."""
    client = ClickHouseClient()
    yield client
    client.disconnect()


@pytest.fixture
def neo4j_client() -> Neo4jClient:
    """Provide Neo4j client for testing."""
    client = Neo4jClient()
    yield client
    client.close()


@pytest.fixture
def qdrant_client() -> QdrantClient:
    """Provide Qdrant client for testing."""
    return QdrantClient()


@pytest.fixture
def sample_financial_data() -> dict:
    """Provide sample financial data for testing."""
    return {
        'revenue': 1000000,
        'gross_profit': 400000,
        'operating_income': 250000,
        'net_income': 150000,
        'current_assets': 500000,
        'current_liabilities': 200000,
        'total_assets': 1500000,
        'total_debt': 400000,
        'shareholders_equity': 800000,
        'price': 50.0,
        'eps': 2.5,
    }
