"""ClickHouse database utilities."""
from typing import Optional, List, Dict, Any
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.errors import DatabaseException

logger = get_logger(__name__)


class ClickHouseClient:
    """ClickHouse database client for time-series data."""
    
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        """
        Initialize ClickHouse client.
        
        Args:
            host: ClickHouse host (uses config if not provided)
            port: ClickHouse port (uses config if not provided)
        """
        config = get_config()
        self.host = host or config.database.clickhouse_host
        self.port = port or config.database.clickhouse_port
        
        self.client = Client(
            host=self.host,
            port=9000,  # Native protocol port
            user='default',
            password=config.database.clickhouse_password,
            database=config.database.clickhouse_db,
            settings={'use_numpy': True}
        )
        
        logger.info("clickhouse_client_initialized", host=self.host)
    
    def execute(self, query: str, params: Optional[Dict] = None) -> List[tuple]:
        """
        Execute query and return results.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            Query results
        """
        try:
            result = self.client.execute(query, params or {})
            return result
        except ClickHouseError as e:
            logger.error("clickhouse_query_error", query=query, error=str(e))
            raise DatabaseException(f"ClickHouse query failed: {str(e)}")
    
    def insert_dataframe(self, table: str, df: Any):
        """
        Insert pandas DataFrame into table.
        
        Args:
            table: Table name
            df: Pandas DataFrame
        """
        try:
            self.client.insert_dataframe(f'INSERT INTO {table} VALUES', df)
            logger.info("dataframe_inserted", table=table, rows=len(df))
        except ClickHouseError as e:
            logger.error("insert_error", table=table, error=str(e))
            raise DatabaseException(f"Insert failed: {str(e)}")
    
    def insert_batch(self, table: str, data: List[tuple], columns: List[str]):
        """
        Insert batch of data.
        
        Args:
            table: Table name
            data: List of tuples
            columns: Column names
        """
        try:
            query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES"
            self.client.execute(query, data)
            logger.info("batch_inserted", table=table, rows=len(data))
        except ClickHouseError as e:
            logger.error("batch_insert_error", table=table, error=str(e))
            raise DatabaseException(f"Batch insert failed: {str(e)}")
    
    def health_check(self) -> bool:
        """Check ClickHouse connection health."""
        try:
            self.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False
    
    def disconnect(self):
        """Close connection."""
        self.client.disconnect()
        logger.info("clickhouse_disconnected")


# Global client instance
_clickhouse_client: Optional[ClickHouseClient] = None


def get_clickhouse_client() -> ClickHouseClient:
    """Get ClickHouse client singleton."""
    global _clickhouse_client
    if _clickhouse_client is None:
        _clickhouse_client = ClickHouseClient()
    return _clickhouse_client
