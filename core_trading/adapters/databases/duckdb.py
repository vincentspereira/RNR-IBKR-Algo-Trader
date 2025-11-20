import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
# from .base import ()
import json
"DuckDB Database Adapter"
# "
# This module provides a DuckDB adapter implementation for the NautilusTrader engine.
# It handles in-process OLAP analytics, backtesting data, and strategy performance analysis.
# "
# Key Features:
# - In-process analytical database
# - Fast OLAP queries and aggregations
# - Excellent for backtesting and analysis
# - SQL compatibility with PostgreSQL
# - Columnar storage for analytics"
# "
# "
# "
# try:
#     import duckdb
# "
#     DUCKDB_AVAILABLE = True
# except ImportError:
#     duckdb = None
#     DUCKDB_AVAILABLE = False
# "
#     BaseDatabaseAdapter,
#     BaseDatabaseConnection,
#     BaseDatabaseTransaction,
#     ConnectionStatus,
#     DatabaseConfig,
#     DatabaseType,
#     HealthCheck,
#     QueryResult,
#     QueryType,
#     TransactionInfo,
#     TransactionStatus,
# )

logger = logging.getLogger(__name__)


# @dataclass
class DuckDBConfig(DatabaseConfig):""
#     "DuckDB-specific configuration"

    # DuckDB specific settings"
#     database_path: str = ":memory:"  # Use in-memory by default
#     read_only: bool = False

    # Performance settings"
# memory_limit: str = "1GB
# threads: int = 4"
#     max_memory: str = "80%"

    # Extensions to load
#     extensions: List[str] = None

    # Pragma settings
#     pragmas: Dict[str, Any] = None

#     def __post_init__(self):
#         if self.extensions is None:""
#             self.extensions = ["httpfs", "parquet", "json"]

#         if self.pragmas is None:
#             self.pragmas = {
# "enable_progress_bar": True,"
# "enable_profiling": "json","
# "profiling_output": "/tmp/duckdb_profile.json",
# }

        # Set default port (not used for DuckDB but required by base)
#         if self.port == 0:
#             self.port = 0  # DuckDB doesn't use ports'


class DuckDBConnection(BaseDatabaseConnection):""
# "DuckDB database connection wrapper
# "
# "

#     def __init__(self, connection: duckdb.DuckDBPyConnection, config: DuckDBConfig):
#         self.connection = connection
#         self.config = config
#         self._closed = False
#         self._executor = ThreadPoolExecutor(max_workers=1)

#     async def execute(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
# "Execute a query
#         if self._closed:""
#             raise RuntimeError("Connection is closed")
# "
#         start_time = datetime.now()
# '
#         try:''
            # Run DuckDB query in thread pool since it's synchronous
#             loop = asyncio.get_event_loop()
# "
#             if parameters:
                # DuckDB uses positional parameters, convert from dict
#                 param_values = list(parameters.values())
# result = await loop.run_in_executor(
#                     self._executor,
#                     lambda: self.connection.execute(query, param_values).fetchall(),
# )
#             else:
# result = await loop.run_in_executor(
#                     self._executor, lambda: self.connection.execute(query).fetchall()
# )

#             execution_time = (datetime.now() - start_time).total_seconds() * 1000

            # Determine query type
#             query_type = self._get_query_type(query)

            # Convert result to list of dictionaries
#             if result and query_type == QueryType.SELECT:
#                 columns = [desc[0] for desc in self.connection.description]
#                 data = [dict(zip(columns, row)) for row in result]
#             else:
#                 data = None

#             return QueryResult(
#                 query_type=query_type,
#                 rows_affected=len(result) if result else self.connection.rowcount,
#                 execution_time_ms=execution_time,
#                 data=data,
# )

#         except Exception as e:
# execution_time = (datetime.now() - start_time).total_seconds() * 1000"
#             logger.error(f"DuckDB query execution failed: {e}")

#             return QueryResult(
#                 query_type=self._get_query_type(query),
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#     async def execute_many(
# self, query: str, parameters_list: List[Dict[str, Any]]
# ) -> QueryResult:"
# "Execute query with multiple parameter sets
#         if self._closed:""
#             raise RuntimeError("Connection is closed")
# "
#         start_time = datetime.now()
#         total_affected = 0
# "
#         try:
#             loop = asyncio.get_event_loop()
# "
            # Convert parameters to list format for DuckDB
#             param_lists = [list(params.values()) for params in parameters_list]
# "
# result = await loop.run_in_executor(
#                 self._executor, lambda: self.connection.executemany(query, param_lists)
# )
# "
#             total_affected = self.connection.rowcount
#             execution_time = (datetime.now() - start_time).total_seconds() * 1000
# "
#             return QueryResult(
#                 query_type=self._get_query_type(query),
#                 rows_affected=total_affected,
#                 execution_time_ms=execution_time,
# )
# "
#         except Exception as e:
# execution_time = (datetime.now() - start_time).total_seconds() * 1000"
#             logger.error(f"DuckDB batch execution failed: {e}")

#             return QueryResult(
#                 query_type=self._get_query_type(query),
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

# "

#     async def fetch_one(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> Optional[Dict[str, Any]]:"
#         "Fetch single row"
#         result = await self.execute(query, parameters)
#         if result.data and len(result.data) > 0:
#             return result.data[0]
#         return None

#     async def fetch_all(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> List[Dict[str, Any]]:"
#         "Fetch all rows"
#         result = await self.execute(query, parameters)
#         return result.data or []

#     async def fetch_many(
# self, query: str, size: int, parameters: Optional[Dict[str, Any]] = None
# ) -> List[Dict[str, Any]]:"
# "Fetch limited number of rows
        # Add LIMIT clause to query"
#         limited_query = f"{query} LIMIT {size}"
#         result = await self.execute(limited_query, parameters)
#         return result.data or []

# "

#     async def begin_transaction(
# self, isolation_level: Optional[str] = None, read_only: bool = False"
# ):"
#         "Begin transaction"
#         return DuckDBTransaction(self, isolation_level, read_only)

#     async def close(self):
#         "Close connection"
#         if not self._closed:
#             self._closed = True
#             self._executor.shutdown(wait=True)
#             if self.connection:
#                 loop = asyncio.get_event_loop()
#                 await loop.run_in_executor(None, self.connection.close)

#     def is_closed(self):
#         "Check if connection is closed"
#         return self._closed

#     def _get_query_type(self, query: str):
# "Determine query type from SQL
# query_upper = query.strip().upper()"
#         if query_upper.startswith("SELECT"):
#             return QueryType.SELECT""
#         elif query_upper.startswith("INSERT"):
#             return QueryType.INSERT""
#         elif query_upper.startswith("UPDATE"):
#             return QueryType.UPDATE""
#         elif query_upper.startswith("DELETE"):
#             return QueryType.DELETE""
#         elif query_upper.startswith("CREATE"):
#             return QueryType.CREATE""
#         elif query_upper.startswith("DROP"):
#             return QueryType.DROP""
#         elif query_upper.startswith("ALTER"):
#             return QueryType.ALTER
#         else:
#             return QueryType.SELECT  # Default


class DuckDBTransaction(BaseDatabaseTransaction):""
#     "DuckDB transaction wrapper"

#     def __init__(
#         self,
# connection: DuckDBConnection,
#         isolation_level: Optional[str] = None,
#         read_only: bool = False,
# ):
#         self.connection = connection
#         self.isolation_level = isolation_level
#         self.read_only = read_only""
#         self.transaction_id = f"duck_tx_{datetime.now().timestamp()}"
#         self.start_time = datetime.now(timezone.utc)
#         self.status = TransactionStatus.ACTIVE
#         self._started = False

#     async def _ensure_transaction_started(self):
# "Ensure transaction is started
#         if not self._started:""
#             await self.connection.execute("BEGIN TRANSACTION")
#             self._started = True

# "

#     async def execute(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
# "Execute query within transaction
#         if self.status != TransactionStatus.ACTIVE:""
#             raise RuntimeError(f"Transaction is not active: {self.status}")

#         await self._ensure_transaction_started()
#         return await self.connection.execute(query, parameters)

# "

#     async def execute_many(
# self, query: str, parameters_list: List[Dict[str, Any]]
# ) -> QueryResult:"
# "Execute multiple queries within transaction
#         if self.status != TransactionStatus.ACTIVE:""
#             raise RuntimeError(f"Transaction is not active: {self.status}")

#         await self._ensure_transaction_started()
#         return await self.connection.execute_many(query, parameters_list)

# "

#     async def commit(self):
# "Commit transaction
#         if self.status == TransactionStatus.ACTIVE and self._started:""
#             await self.connection.execute("COMMIT")
#             self.status = TransactionStatus.COMMITTED""
#             logger.info(f"DuckDB transaction {self.transaction_id} committed")

# "

#     async def rollback(self):
# "Rollback transaction
#         if self.status == TransactionStatus.ACTIVE and self._started:""
#             await self.connection.execute("ROLLBACK")
#             self.status = TransactionStatus.ROLLED_BACK""
#             logger.info(f"DuckDB transaction {self.transaction_id} rolled back")

# "

#     async def savepoint(self, name: str):
# "Create savepoint
# await self._ensure_transaction_started()"
#         await self.connection.execute(f"SAVEPOINT {name}")

# "

#     async def rollback_to_savepoint(self, name: str):
#         "Rollback to savepoint"
#         await self.connection.execute(f"ROLLBACK TO SAVEPOINT {name}")

#     async def release_savepoint(self, name: str):
#         "Release savepoint"
#         await self.connection.execute(f"RELEASE SAVEPOINT {name}")

#     def get_info(self):
#         "Get transaction information"
#         return TransactionInfo(
#             transaction_id=self.transaction_id,
#             status=self.status,
#             start_time=self.start_time,
#             isolation_level=self.isolation_level,
# read_only=self.read_only,"
#             metadata={"started": self._started, "database_type": "duckdb"},
# )


class DuckDBAdapter(BaseDatabaseAdapter):""
#     "DuckDB database adapter"

#     def __init__(self, config: DuckDBConfig):
#         super().__init__(config)
#         self.config = config
#         self.connection = None
#         self._connection_pool = []
#         self._pool_lock = threading.Lock()

#     async def connect(self):
# "Establish connection to DuckDB
#         if not DUCKDB_AVAILABLE:""
#             logger.error("DuckDB not available")
#             self.connection_status = ConnectionStatus.ERROR
#             return False
# "
#         try:
#             self.connection_status = ConnectionStatus.CONNECTING
# "
            # Ensure database directory exists if using file-based storage"
#             if self.config.database_path != ":memory:":
#                 db_path = Path(self.config.database_path)
#                 db_path.parent.mkdir(parents=True, exist_ok=True)
# "
            # Create DuckDB connection
#             loop = asyncio.get_event_loop()
#             self.connection = await loop.run_in_executor(
#                 None,
# lambda: duckdb.connect(
#                     self.config.database_path, read_only=self.config.read_only
# ),
# )

            # Configure DuckDB settings
#             await self._configure_duckdb()

            # Test connection"
# result = await loop.run_in_executor("
#                 None, lambda: self.connection.execute("SELECT 1").fetchone()
# )

#             if result:
#                 self.connection_status = ConnectionStatus.CONNECTED""
#                 logger.info(f"Connected to DuckDB at {self.config.database_path}")

                # Initialize connection pool
#                 await self._initialize_pool()

#                 return True
#             else:
#                 self.connection_status = ConnectionStatus.ERROR
#                 return False

#         except Exception as e:""
#             logger.error(f"Failed to connect to DuckDB: {e}")
#             self.connection_status = ConnectionStatus.ERROR
#             return False

#     async def disconnect(self):
#         "Disconnect from DuckDB"
#         try:
            # Close all pooled connections
#             with self._pool_lock:
#                 for connection in self._connection_pool:
#                     await connection.close()
#                 self._connection_pool.clear()

#             if self.connection:
#                 loop = asyncio.get_event_loop()
#                 await loop.run_in_executor(None, self.connection.close)
#                 self.connection = None

#             self.connection_status = ConnectionStatus.DISCONNECTED""
#             logger.info("Disconnected from DuckDB")
#             return True

#         except Exception as e:""
#             logger.error(f"Error disconnecting from DuckDB: {e}")
#             return False

#     async def get_connection(self):
# "Get connection from pool
#         if self.connection_status != ConnectionStatus.CONNECTED:""
#             raise RuntimeError("Not connected to DuckDB")
# "
#         with self._pool_lock:
#             if self._connection_pool:
#                 return self._connection_pool.pop()
# "
        # Create new connection if pool is empty
#         loop = asyncio.get_event_loop()
# new_conn = await loop.run_in_executor(
#             None,
# lambda: duckdb.connect(
#                 self.config.database_path, read_only=self.config.read_only
# ),
# )
#         return DuckDBConnection(new_conn, self.config)

# "

#     async def return_connection(self, connection: DuckDBConnection):
#         "Return connection to pool"
#         if not connection.is_closed():
#             with self._pool_lock:
#                 if len(self._connection_pool) < self.config.max_connections:
#                     self._connection_pool.append(connection)
#                 else:
#                     await connection.close()

#     async def execute_query(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
#         "Execute single query"
#         connection = await self.get_connection()
#         try:
#             result = await connection.execute(query, parameters)
#             self._update_metrics(
#                 result.query_type, result.execution_time_ms, result.error is None
# )
#             return result
#         finally:
#             await self.return_connection(connection)

#     async def execute_transaction(
# self, queries: List[tuple], isolation_level: Optional[str] = None
# ) -> List[QueryResult]:"
#         "Execute multiple queries in transaction"
#         connection = await self.get_connection()
#         try:
#             transaction = await connection.begin_transaction(isolation_level)
#             results = []

#             try:
#                 for query_info in queries:
#                     if len(query_info) == 2:
#                         query, parameters = query_info
#                     else:
#                         query = query_info[0]
#                         parameters = None

#                     result = await transaction.execute(query, parameters)
#                     results.append(result)

#                     if result.error:
#                         await transaction.rollback()
#                         return results

#                 await transaction.commit()
#                 return results

#             except Exception as e:
# await transaction.rollback()"
#                 logger.error(f"Transaction failed: {e}")
#                 raise

#         finally:
#             await self.return_connection(connection)

#     async def get_health_check(self):
#         "Perform health check"
#         start_time = datetime.now()

#         try:
#             if self.connection_status != ConnectionStatus.CONNECTED:
#                 return HealthCheck(
#                     database_type=DatabaseType.SQLITE,  # DuckDB is similar to SQLite
#                     database_name=self.config.database_path,
# is_healthy=False,"
#                     status_message="Not connected",
#                     last_check=datetime.now(timezone.utc),
#                     response_time_ms=0,
#                     active_connections=0,
# )

            # Test query"
#             result = await self.execute_query("SELECT 1")
#             response_time = (datetime.now() - start_time).total_seconds() * 1000

#             return HealthCheck(
#                 database_type=DatabaseType.SQLITE,
#                 database_name=self.config.database_path,
# is_healthy=result.error is None,"
# status_message="Healthy
#                 if result.error is None""
# else f"Error: {result.error}",
#                 last_check=datetime.now(timezone.utc),
#                 response_time_ms=response_time,
#                 active_connections=len(self._connection_pool),
# metrics={
# "pool_size": len(self._connection_pool),"
# "max_connections": self.config.max_connections,"
# "database_path": self.config.database_path,
# },
# )

#         except Exception as e:
#             response_time = (datetime.now() - start_time).total_seconds() * 1000
#             return HealthCheck(
#                 database_type=DatabaseType.SQLITE,
#                 database_name=self.config.database_path,
# is_healthy=False,"
#                 status_message=f"Health check failed: {e}",
#                 last_check=datetime.now(timezone.utc),
#                 response_time_ms=response_time,
#                 active_connections=0,
# )

#     async def _configure_duckdb(self):
#         "Configure DuckDB settings"
#         loop = asyncio.get_event_loop()

        # Set memory limit
#         if self.config.memory_limit:
# await loop.run_in_executor(
#                 None,
# lambda: self.connection.execute("'"'
#                     f"SET memory_limit = '{self.config.memory_limit}'"
# ),
# )

        # Set thread count
# await loop.run_in_executor(
# None,"
#             lambda: self.connection.execute(f"SET threads = {self.config.threads}"),
# )

        # Install and load extensions
#         for extension in self.config.extensions:
#             try:
# await loop.run_in_executor(
# None,"
#                     lambda ext=extension: self.connection.execute(f"INSTALL {ext}"),
# )
# await loop.run_in_executor("
#                     None, lambda ext=extension: self.connection.execute(f"LOAD {ext}")
# )"
#                 logger.info(f"Loaded DuckDB extension: {extension}")
#             except Exception as e:""
#                 logger.warning(f"Could not load DuckDB extension {extension}: {e}")

        # Set pragmas
#         for pragma, value in self.config.pragmas.items():
#             try:
# await loop.run_in_executor(
#                     None,
# lambda p=pragma, v=value: self.connection.execute("
#                         f"PRAGMA {p} = {v}"
# ),
# )
#             except Exception as e:""
#                 logger.warning(f"Could not set pragma {pragma}: {e}")

#     async def _initialize_pool(self):
#         "Initialize connection pool"
#         with self._pool_lock:
#             for _ in range(self.config.min_connections):
#                 loop = asyncio.get_event_loop()
# conn = await loop.run_in_executor(
#                     None,
# lambda: duckdb.connect(
#                         self.config.database_path, read_only=self.config.read_only
# ),
# )
#                 connection = DuckDBConnection(conn, self.config)
#                 self._connection_pool.append(connection)

# logger.info("
#             f"Initialized DuckDB connection pool with {self.config.min_connections} connections"
# )

    # DuckDB-specific methods

#     async def create_analytics_tables(self):
# "Create analytics and backtesting tables
# tables = {"
# "backtest_results":
# CREATE TABLE IF NOT EXISTS backtest_results (
# backtest_id VARCHAR PRIMARY KEY,
# strategy_name VARCHAR NOT NULL,
# start_date DATE NOT NULL,
# end_date DATE NOT NULL,
# initial_capital DECIMAL(18,2),
# final_value DECIMAL(18,2),
# total_return DECIMAL(10,4),
# sharpe_ratio DECIMAL(10,4),
# max_drawdown DECIMAL(10,4),
# win_rate DECIMAL(10,4),
# profit_factor DECIMAL(10,4),
# created_at TIMESTAMP DEFAULT NOW()
# )"
# ",
# "strategy_performance":
# CREATE TABLE IF NOT EXISTS strategy_performance (
# performance_id VARCHAR PRIMARY KEY,
# strategy_id VARCHAR NOT NULL,
# date DATE NOT NULL,
# portfolio_value DECIMAL(18,2),
# daily_return DECIMAL(10,6),
# cumulative_return DECIMAL(10,6),
# drawdown DECIMAL(10,6),
# volatility DECIMAL(10,6)
# )"
# ",
# "trade_analysis":
# CREATE TABLE IF NOT EXISTS trade_analysis (
# trade_id VARCHAR PRIMARY KEY,
# strategy_id VARCHAR NOT NULL,
# symbol VARCHAR NOT NULL,
# entry_time TIMESTAMP NOT NULL,
# exit_time TIMESTAMP,
# side VARCHAR NOT NULL,
# quantity DECIMAL(18,8),
# entry_price DECIMAL(18,8),
# exit_price DECIMAL(18,8),
# pnl DECIMAL(18,2),
# commission DECIMAL(18,2),
# duration_minutes INTEGER
# )"
# ",
# "portfolio_snapshots":
# CREATE TABLE IF NOT EXISTS portfolio_snapshots (
# snapshot_id VARCHAR PRIMARY KEY,
# timestamp TIMESTAMP NOT NULL,
# total_value DECIMAL(18,2),
# cash DECIMAL(18,2),
# positions JSON,
# metrics JSON
# )"
# ",
# }

#         for table_name, ddl in tables.items():
#             try:
# await self.execute_query(ddl)"
#                 logger.info(f"Created DuckDB table: {table_name}")
#             except Exception as e:""
#                 logger.error(f"Failed to create table {table_name}: {e}")

# "

#     async def insert_backtest_results(self, results: List[Dict[str, Any]]):
#         "Insert backtest results efficiently"
#         if not results:
#             return

        # Prepare insert query"
# query =
# INSERT INTO backtest_results (
#                 backtest_id, strategy_name, start_date, end_date,
#                 initial_capital, final_value, total_return, sharpe_ratio,
#                 max_drawdown, win_rate, profit_factor
# ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"


        # Convert to parameter list
#         parameters_list = []
#         for result in results:
# parameters_list.append(
# {"
# "backtest_id": result["backtest_id"],"
# "strategy_name": result["strategy_name"],"
# "start_date": result["start_date"],"
# "end_date": result["end_date"],"
# "initial_capital": result["initial_capital"],"
# "final_value": result["final_value"],"
# "total_return": result["total_return"],"
# "sharpe_ratio": result["sharpe_ratio"],"
# "max_drawdown": result["max_drawdown"],"
# "win_rate": result["win_rate"],"
# "profit_factor": result["profit_factor"],
# }
# )

#         connection = await self.get_connection()
#         try:
# await connection.execute_many(query, parameters_list)"
#             logger.info(f"Inserted {len(parameters_list)} backtest results")
#         finally:
#             await self.return_connection(connection)

#     async def query_strategy_performance(
# self, strategy_id: str, start_date: datetime, end_date: datetime
# ) -> List[Dict[str, Any]]:"
#         "Query strategy performance data"
# query =
# SELECT date, portfolio_value, daily_return, cumulative_return, drawdown, volatility
# FROM strategy_performance
# WHERE strategy_id = ?
# AND date >= ?
# AND date <= ?
# ORDER BY date"


# result = await self.execute_query(
#             query,
# {
# "strategy_id": strategy_id,"
# "start_date": start_date,"
# "end_date": end_date,
# },
# )

#         return result.data or []

#     async def analyze_trades(self, strategy_id: str):
#         "Analyze trades for a strategy"
# query =
#             SELECT
# COUNT(*) as total_trades,
# COUNT(CASE WHEN pnl > 0 THEN 1 END) as winning_trades,
# COUNT(CASE WHEN pnl < 0 THEN 1 END) as losing_trades,
# AVG(pnl) as avg_pnl,
# SUM(pnl) as total_pnl,
# MAX(pnl) as max_win,
# MIN(pnl) as max_loss,
# AVG(duration_minutes) as avg_duration_minutes
# FROM trade_analysis
# WHERE strategy_id = ?"
# "
# "
#         result = await self.execute_query(query, {"strategy_id": strategy_id})

#         if result.data and len(result.data) > 0:
#             return result.data[0]
#         return {}


# "

# def create_duckdb_adapter(config: Dict[str, Any]):
# "Factory function to create DuckDB adapter
# duckdb_config = DuckDBConfig("
#         host=config.get("host", "localhost"),  # Not used but required by base""
#         port=config.get("port", 0),  # Not used""
#         database=config.get("database", "analytics"),  # Not used""
# username=config.get("username", "),  # Not used"
#         password=config.get("password", "),  # Not used"
# database_path=config.get("database_path", ":memory:"),"
# read_only=config.get("read_only", False),"
# memory_limit=config.get("memory_limit", "1GB"),"
# threads=config.get("threads", 4),"
# extensions=config.get("extensions", ["httpfs", "parquet", "json"]),"
# max_connections=config.get("max_connections", 10),"
# min_connections=config.get("min_connections", 2),"
# connection_timeout=config.get("connection_timeout", 30.0),"
#         query_timeout=config.get("query_timeout", 30.0),
# )

#     return DuckDBAdapter(duckdb_config)
# "'"'