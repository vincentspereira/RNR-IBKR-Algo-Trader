"""PostgreSQL database utilities."""
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.errors import DatabaseException, ConnectionException

logger = get_logger(__name__)

# Base class for SQLAlchemy models
Base = declarative_base()


class PostgreSQLClient:
    """PostgreSQL database client with connection pooling."""
    
    def __init__(self, connection_url: Optional[str] = None):
        """
        Initialize PostgreSQL client.
        
        Args:
            connection_url: Database connection URL (uses config if not provided)
        """
        config = get_config()
        self.connection_url = connection_url or config.database.postgres_async_url
        
        # Create async engine
        self.engine = create_async_engine(
            self.connection_url,
            pool_size=config.database.postgres_pool_size,
            max_overflow=10,
            pool_pre_ping=True,
            echo=config.debug
        )
        
        # Create session factory
        self.async_session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        logger.info("postgresql_client_initialized", url=self.connection_url)
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get database session context manager.
        
        Yields:
            AsyncSession instance
        """
        async with self.async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error("session_error", error=str(e))
                raise DatabaseException(f"Database session error: {str(e)}")
    
    async def execute_query(self, query: str, params: dict = None):
        """
        Execute a raw SQL query.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            Query result
        """
        async with self.session() as session:
            try:
                result = await session.execute(query, params or {})
                return result
            except Exception as e:
                logger.error("query_execution_error", query=query, error=str(e))
                raise DatabaseException(f"Query execution failed: {str(e)}")
    
    async def health_check(self) -> bool:
        """
        Check database connection health.
        
        Returns:
            True if healthy
        """
        try:
            async with self.engine.connect() as conn:
                # SQLAlchemy 2.0 requires an executable object, not a raw string.
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False
    
    async def close(self):
        """Close database connections."""
        await self.engine.dispose()
        logger.info("postgresql_client_closed")


# Global client instance
_pg_client: Optional[PostgreSQLClient] = None


def get_postgres_client() -> PostgreSQLClient:
    """
    Get PostgreSQL client singleton.
    
    Returns:
        PostgreSQL client instance
    """
    global _pg_client
    if _pg_client is None:
        _pg_client = PostgreSQLClient()
    return _pg_client
