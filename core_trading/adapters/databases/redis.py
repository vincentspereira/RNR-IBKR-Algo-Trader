import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union
# from .base import ()

# Redis Database Adapter

# This module implements the Redis adapter for the trading system,
# providing high-performance caching, pub/sub messaging, and data storage
# operations with connection pooling and comprehensive monitoring.

# Key Features:
# - AsyncIO-based connection pooling
# - Pub/Sub messaging support
# - Caching operations with TTL
# - Pipeline operations for bulk commands
# - Connection health monitoring
# - Event-driven synchronization
# - Performance metrics and monitoring"



# try:
#     import redis.asyncio as aioredis
# except ImportError:
#     import aioredis

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


# @dataclass
class RedisConfig(DatabaseConfig):""
#     "Redis-specific configuration"

    # Redis specific settings
#     db: int = 0
# decode_responses: bool = True"
#     encoding: str = "utf-8"

    # Connection pool settings
#     pool_min_size: int = 5
#     pool_max_size: int = 20

    # Retry settings
#     retry_on_timeout: bool = True
#     health_check_interval: float = 30.0

    # Pub/Sub settings
#     pubsub_timeout: float = 1.0

    # Serialization"
#     json_serializer: str = "json"  # or "orjson", "ujson"

    # Clustering (for Redis Cluster)
#     cluster_mode: bool = False
#     cluster_nodes: List[Dict[str, Any]] = field(default_factory=list)

    # Sentinel (for Redis Sentinel)"
# sentinel_mode: bool = False"
#     sentinel_service_name: str = "mymaster"
#     sentinel_nodes: List[Dict[str, str]] = field(default_factory=list)


class RedisConnection(BaseDatabaseConnection):""
#     "Redis connection wrapper"

#     def __init__(self, connection: aioredis.Redis, config: RedisConfig):
#         self._connection = connection
#         self._config = config
#         self._closed = False
#         self._pipeline = None
#         self.logger = logging.getLogger(self.__class__.__name__)

#     async def execute(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
#         "Execute a Redis command"
#         start_time = datetime.now(timezone.utc)

#         try:
            # Parse Redis command
#             command_parts = query.strip().split()
#             command = command_parts[0].upper()
#             args = command_parts[1:] if len(command_parts) > 1 else []

            # Add parameters if provided
#             if parameters:
#                 for key, value in parameters.items():
#                     if isinstance(value, (dict, list)):
#                         value = json.dumps(value)
#                     args.append(str(value))

            # Execute command
#             result = await self._connection.execute_command(command, *args)

# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

            # Determine rows affected based on command type"
# rows_affected = 1 if result else 0"
#             if command in ["MSET", "MGET", "DEL"] and isinstance(result, (list, int)):
#                 rows_affected = len(result) if isinstance(result, list) else result

#             return QueryResult(
#                 query_type=self._get_query_type(command),
#                 rows_affected=rows_affected,
# execution_time_ms=execution_time,"
#                 data=[{"result": result}] if result is not None else None,
# )

#         except Exception as e:
# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000"
#             self.logger.error(f"Redis command execution error: {e}")

#             return QueryResult(
#                 query_type=QueryType.SELECT,  # Default
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#     async def execute_many(
# self, query: str, parameters_list: List[Dict[str, Any]]
# ) -> QueryResult:"
#         "Execute multiple Redis commands using pipeline"
#         start_time = datetime.now(timezone.utc)

#         try:
#             async with self._connection.pipeline() as pipe:
#                 for parameters in parameters_list:
                    # Parse command for each parameter set
#                     command_parts = query.strip().split()
#                     command = command_parts[0].upper()
#                     args = command_parts[1:] if len(command_parts) > 1 else []

                    # Add parameters
#                     if parameters:
#                         for key, value in parameters.items():
#                             if isinstance(value, (dict, list)):
#                                 value = json.dumps(value)
#                             args.append(str(value))

                    # Add command to pipeline
#                     pipe.execute_command(command, *args)

                # Execute pipeline
#                 results = await pipe.execute()

# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

#             return QueryResult(
#                 query_type=self._get_query_type(query.split()[0].upper()),
#                 rows_affected=len(results),
# execution_time_ms=execution_time,"
#                 data=[{"result": result} for result in results],
# )

#         except Exception as e:
# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000"
#             self.logger.error(f"Redis pipeline execution error: {e}")

#             return QueryResult(
#                 query_type=QueryType.SELECT,
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#     async def fetch_one(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> Optional[Dict[str, Any]]:"
#         "Fetch a single value from Redis"
#         try:
#             result = await self.execute(query, parameters)
#             if result.data and len(result.data) > 0:
#                 return result.data[0]
#             return None
#         except Exception as e:""
#             self.logger.error(f"Redis fetch one error: {e}")
#             return None

#     async def fetch_all(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> List[Dict[str, Any]]:"
#         "Fetch all values from Redis"
#         try:
#             result = await self.execute(query, parameters)
#             return result.data if result.data else []
#         except Exception as e:""
#             self.logger.error(f"Redis fetch all error: {e}")
#             return []

#     async def fetch_many(
# self, query: str, size: int, parameters: Optional[Dict[str, Any]] = None
# ) -> List[Dict[str, Any]]:"
#         "Fetch multiple values from Redis"
        # Redis doesn't have a direct equivalent, so we use fetch_all and limit
#         results = await self.fetch_all(query, parameters)
#         return results[:size] if results else []

#     async def begin_transaction(
# self, isolation_level: Optional[str] = None, read_only: bool = False"
# ):"
#         "Begin a Redis transaction (MULTI/EXEC)"
#         return RedisTransaction(self._connection, self._config)

#     async def close(self):
#         "Close the Redis connection"
#         if not self._closed:
#             await self._connection.close()
#             self._closed = True

#     def is_closed(self):
#         "Check if connection is closed"
#         return self._closed

#     def _get_query_type(self, command: str):
#         "Determine query type from Redis command"
#         command_upper = command.upper()

        # Read operations"
#         if command_upper in [""
# "GET","
# "MGET","
# "HGET","
# "HGETALL","
# "LRANGE","
# "SMEMBERS","
# "ZRANGE","
# "EXISTS","
#             "TTL",
# ]:
#             return QueryType.SELECT
        # Write operations"
#         elif command_upper in ["SET", "MSET", "HSET", "LPUSH", "RPUSH", "SADD", "ZADD"]:
#             return QueryType.INSERT
        # Update operations"
#         elif command_upper in ["INCR", "DECR", "HINCRBY", "EXPIRE", "PERSIST"]:
#             return QueryType.UPDATE
        # Delete operations"
#         elif command_upper in ["DEL", "HDEL", "LPOP", "RPOP", "SREM", "ZREM"]:
#             return QueryType.DELETE
#         else:
#             return QueryType.SELECT  # Default


class RedisTransaction(BaseDatabaseTransaction):""
#     "Redis transaction wrapper (MULTI/EXEC)"

#     def __init__(self, connection: aioredis.Redis, config: RedisConfig):
#         self._connection = connection
#         self._config = config
#         self._transaction_id = str(uuid.uuid4())
#         self._start_time = datetime.now(timezone.utc)
#         self._status = TransactionStatus.ACTIVE
#         self._pipeline = None
#         self.logger = logging.getLogger(self.__class__.__name__)

#     async def __aenter__(self):
#         "Start transaction"
#         self._pipeline = self._connection.pipeline()
#         await self._pipeline.multi()
#         return self

#     async def __aexit__(self, exc_type, exc_val, exc_tb):
#         "End transaction"
#         if exc_type is None:
#             await self.commit()
#         else:
#             await self.rollback()

#     async def execute(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
#         "Execute a command within the transaction"
#         start_time = datetime.now(timezone.utc)

#         try:
#             if not self._pipeline:""
#                 raise RuntimeError("Transaction not started")

            # Parse Redis command
#             command_parts = query.strip().split()
#             command = command_parts[0].upper()
#             args = command_parts[1:] if len(command_parts) > 1 else []

            # Add parameters if provided
#             if parameters:
#                 for key, value in parameters.items():
#                     if isinstance(value, (dict, list)):
#                         value = json.dumps(value)
#                     args.append(str(value))

            # Add command to pipeline
#             self._pipeline.execute_command(command, *args)

# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

#             return QueryResult(
#                 query_type=self._get_query_type(command),
#                 rows_affected=1,  # Will be determined after EXEC
#                 execution_time_ms=execution_time,
# )

#         except Exception as e:
# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000"
#             self.logger.error(f"Redis transaction command error: {e}")
#             self._status = TransactionStatus.ERROR

#             return QueryResult(
#                 query_type=QueryType.SELECT,
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#     async def execute_many(
# self, query: str, parameters_list: List[Dict[str, Any]]
# ) -> QueryResult:"
#         "Execute multiple commands within the transaction"
#         start_time = datetime.now(timezone.utc)

#         try:
#             if not self._pipeline:""
#                 raise RuntimeError("Transaction not started")

#             for parameters in parameters_list:
#                 command_parts = query.strip().split()
#                 command = command_parts[0].upper()
#                 args = command_parts[1:] if len(command_parts) > 1 else []

#                 if parameters:
#                     for key, value in parameters.items():
#                         if isinstance(value, (dict, list)):
#                             value = json.dumps(value)
#                         args.append(str(value))

#                 self._pipeline.execute_command(command, *args)

# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

#             return QueryResult(
#                 query_type=self._get_query_type(query.split()[0].upper()),
#                 rows_affected=len(parameters_list),
#                 execution_time_ms=execution_time,
# )

#         except Exception as e:
# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000"
#             self.logger.error(f"Redis transaction execute many error: {e}")
#             self._status = TransactionStatus.ERROR

#             return QueryResult(
#                 query_type=QueryType.SELECT,
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#     async def commit(self):
#         "Commit the transaction (EXEC)"
#         try:
#             if self._pipeline:
#                 results = await self._pipeline.execute()
#                 self._status = TransactionStatus.COMMITTED
#                 return results
#         except Exception as e:""
#             self.logger.error(f"Redis transaction commit error: {e}")
#             self._status = TransactionStatus.ERROR
#             raise

#     async def rollback(self):
#         "Rollback the transaction (DISCARD)"
#         try:
#             if self._pipeline:
#                 await self._pipeline.discard()
#                 self._status = TransactionStatus.ROLLED_BACK
#         except Exception as e:""
#             self.logger.error(f"Redis transaction rollback error: {e}")
#             self._status = TransactionStatus.ERROR
#             raise

#     async def savepoint(self, name: str):':'
#         "Redis doesn't support savepoints"'"''
#         raise NotImplementedError("Redis doesn't support savepoints")'

#     async def rollback_to_savepoint(self, name: str):':'
#         "Redis doesn't support savepoints"'"''
#         raise NotImplementedError("Redis doesn't support savepoints")'

#     async def release_savepoint(self, name: str):':'
#         "Redis doesn't support savepoints"'"''
#         raise NotImplementedError("Redis doesn't support savepoints")'

#     def get_info(self):
#         "Get transaction information"
#         return TransactionInfo(
#             transaction_id=self._transaction_id,
#             status=self._status,
#             start_time=self._start_time,
#             read_only=False,  # Redis transactions are not read-only
# )

#     def _get_query_type(self, command: str):
#         "Determine query type from Redis command"
#         command_upper = command.upper()

#         if command_upper in [""
# "GET","
# "MGET","
# "HGET","
# "HGETALL","
# "LRANGE","
# "SMEMBERS","
#             "ZRANGE",
# ]:
#             return QueryType.SELECT""
#         elif command_upper in ["SET", "MSET", "HSET", "LPUSH", "RPUSH", "SADD", "ZADD"]:
#             return QueryType.INSERT""
#         elif command_upper in ["INCR", "DECR", "HINCRBY", "EXPIRE"]:
#             return QueryType.UPDATE""
#         elif command_upper in ["DEL", "HDEL", "LPOP", "RPOP", "SREM", "ZREM"]:
#             return QueryType.DELETE
#         else:
#             return QueryType.SELECT


class RedisAdapter(BaseDatabaseAdapter):""

# Redis database adapter implementation

# Provides high-performance Redis operations with connection pooling,
# pub/sub messaging, caching, and comprehensive monitoring."


#     def __init__(self, config: RedisConfig):
#         super().__init__(config)
#         self.config: RedisConfig = config
#         self._pool: Optional[aioredis.ConnectionPool] = None
#         self._redis: Optional[aioredis.Redis] = None
#         self._pubsub: Optional[aioredis.client.PubSub] = None
#         self.database_type = DatabaseType.REDIS

        # Pub/Sub callbacks
#         self._pubsub_callbacks: Dict[str, List[Callable]] = {}

#     async def connect(self):
#         "Connect to Redis database"
#         try:
#             self._connection_status = ConnectionStatus.CONNECTING

            # Build connection parameters
#             if self.config.cluster_mode:
                # Redis Cluster mode
# startup_nodes = [
# aioredis.ConnectionPool.from_url("'"'
#                         f"redis://{node['host']}:{node['port']}"
# )
#                     for node in self.config.cluster_nodes
# ]
#                 self._redis = aioredis.RedisCluster(startup_nodes=startup_nodes)
#             elif self.config.sentinel_mode:
                # Redis Sentinel mode
# sentinel = aioredis.Sentinel(
# ["
#                         (node["host"], int(node["port"]))
#                         for node in self.config.sentinel_nodes
# ]
# )
#                 self._redis = sentinel.master_for(
#                     self.config.sentinel_service_name,
#                     decode_responses=self.config.decode_responses,
#                     encoding=self.config.encoding,
# )
#             else:
                # Standard Redis connection"
# connection_params = {
# "host": self.config.host,"
# "port": self.config.port,"
# "db": self.config.db,"
# "password": self.config.password,"
# "decode_responses": self.config.decode_responses,"
# "encoding": self.config.encoding,"
# "max_connections": self.config.pool_max_size,"
# "retry_on_timeout": self.config.retry_on_timeout,
# }

                # Add SSL settings if enabled"
#                 if self.config.ssl_enabled:""
#                     connection_params["ssl"] = True
#                     if self.config.ssl_cert_path:""
#                         connection_params["ssl_certfile"] = self.config.ssl_cert_path
#                     if self.config.ssl_key_path:""
#                         connection_params["ssl_keyfile"] = self.config.ssl_key_path
#                     if self.config.ssl_ca_path:""
#                         connection_params["ssl_ca_certs"] = self.config.ssl_ca_path

#                 self._redis = aioredis.from_url(""
#                     f"redis://{self.config.username}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.db}",
# **{
#                         k: v
#                         for k, v in connection_params.items()""
#                         if k not in ["host", "port", "db", "password"]
# },
# )

            # Test connection
#             await self._redis.ping()

#             self._connection_status = ConnectionStatus.CONNECTED
#             self.logger.info(""
#                 f"Connected to Redis: {self.config.host}:{self.config.port}/{self.config.db}"
# )

            # Start health monitoring
#             await self.start_health_monitoring()

            # Notify connection event"
# await self._notify_event("
# "connection","
#                 {"status": "connected", "database_type": self.database_type},
# )

#             return True

#         except Exception as e:
#             self._connection_status = ConnectionStatus.ERROR""
#             self.logger.error(f"Redis connection error: {e}")""
#             await self._notify_event("error", {"type": "connection", "error": str(e)})
#             return False

#     async def disconnect(self):
#         "Disconnect from Redis database"
#         try:
            # Stop health monitoring
#             await self.stop_health_monitoring()

            # Close pub/sub if active
#             if self._pubsub:
#                 await self._pubsub.close()
#                 self._pubsub = None

            # Close Redis connection
#             if self._redis:
#                 await self._redis.close()
#                 self._redis = None

#             self._connection_status = ConnectionStatus.DISCONNECTED""
#             self.logger.info("Disconnected from Redis")

            # Notify disconnection event"
# await self._notify_event("
# "connection","
#                 {"status": "disconnected", "database_type": self.database_type},
# )

#             return True

#         except Exception as e:""
#             self.logger.error(f"Redis disconnection error: {e}")
#             return False

#     async def get_connection(self):
# "Get a Redis connection
#         if not self._redis:""
#             raise RuntimeError("Not connected to Redis")

#         return RedisConnection(self._redis, self.config)

# "

#     async def return_connection(self, connection: RedisConnection):
#         "Return a Redis connection (no-op for Redis)"
        # Redis connections are managed by the pool automatically
#         pass

#     async def execute_query(
# self, query: str, parameters: Optional[Dict[str, Any]] = None
# ) -> QueryResult:"
#         "Execute a Redis command"
#         start_time = datetime.now(timezone.utc)

#         try:
#             connection = await self.get_connection()
#             result = await connection.execute(query, parameters)

            # Update metrics
#             self._update_metrics(
#                 result.query_type, result.execution_time_ms, result.error is None
# )

            # Notify query event"
# await self._notify_event("
#                 "query",
# {
# "query_type": result.query_type.value,"
# "execution_time_ms": result.execution_time_ms,"
# "success": result.error is None,
# },
# )

#             return result

#         except Exception as e:
# execution_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000"
#             self.logger.error(f"Redis query execution error: {e}")

# result = QueryResult(
#                 query_type=QueryType.SELECT,
#                 rows_affected=0,
#                 execution_time_ms=execution_time,
#                 error=str(e),
# )

#             self._update_metrics(result.query_type, execution_time, False)""
#             await self._notify_event("error", {"type": "query", "error": str(e)})

#             return result

#     async def execute_transaction(
# self, queries: List[tuple], isolation_level: Optional[str] = None
# ) -> List[QueryResult]:"
#         "Execute multiple Redis commands in a transaction"
#         results = []

#         try:
#             connection = await self.get_connection()

#             async with await connection.begin_transaction() as transaction:
#                 for query_data in queries:
#                     if len(query_data) == 2:
#                         query, parameters = query_data
#                     else:
#                         query = query_data[0]
#                         parameters = None

#                     result = await transaction.execute(query, parameters)
#                     results.append(result)

                # Commit transaction
#                 await transaction.commit()

            # Notify transaction event"
# await self._notify_event("
#                 "transaction", {"queries_count": len(queries), "success": True}
# )

#         except Exception as e:""
#             self.logger.error(f"Redis transaction error: {e}")

#             if not results or not results[-1].error:
# results.append(
# QueryResult(
#                         query_type=QueryType.SELECT,
#                         rows_affected=0,
#                         execution_time_ms=0,
#                         error=str(e),
# )
# )
# "
#             await self._notify_event("error", {"type": "transaction", "error": str(e)})

#         return results

#     async def get_health_check(self):
#         "Get Redis health status"
#         start_time = datetime.now(timezone.utc)

#         try:
#             if not self._redis:
#                 return HealthCheck(
# database_type=self.database_type,"
#                     database_name=f"db{self.config.db}",
# is_healthy=False,"
#                     status_message="Not connected",
#                     last_check=start_time,
#                     response_time_ms=0,
#                     active_connections=0,
# )

            # Test connection with PING
#             await self._redis.ping()

            # Get Redis info
#             info = await self._redis.info()

# response_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

#             return HealthCheck(
# database_type=self.database_type,"
#                 database_name=f"db{self.config.db}",
# is_healthy=True,"
#                 status_message="Connected and healthy",
#                 last_check=start_time,
# response_time_ms=response_time,"
#                 active_connections=info.get("connected_clients", 0),
# metrics={
# "redis_version": info.get("redis_version"),"
# "used_memory": info.get("used_memory"),"
# "used_memory_human": info.get("used_memory_human"),"
# "connected_clients": info.get("connected_clients"),"
# "total_commands_processed": info.get("total_commands_processed"),"
# "keyspace_hits": info.get("keyspace_hits"),"
# "keyspace_misses": info.get("keyspace_misses"),
# },
# )

#         except Exception as e:
# response_time = (
#                 datetime.now(timezone.utc) - start_time
# ).total_seconds() * 1000

#             return HealthCheck(
# database_type=self.database_type,"
#                 database_name=f"db{self.config.db}",
# is_healthy=False,"
#                 status_message=f"Health check failed: {str(e)}",
#                 last_check=start_time,
#                 response_time_ms=response_time,
# active_connections=0,"
#                 metrics={"error": str(e)},
# )

    # Redis-specific methods

#     async def set_cache(self, key: str, value: Any, ttl: Optional[int] = None):
#         "Set a cache value with optional TTL"
#         try:
#             if isinstance(value, (dict, list)):
#                 value = json.dumps(value)

#             if ttl:
#                 await self._redis.setex(key, ttl, value)
#             else:
#                 await self._redis.set(key, value)

#             return True
#         except Exception as e:""
#             self.logger.error(f"Cache set error: {e}")
#             return False

#     async def get_cache(self, key: str):
#         "Get a cache value"
#         try:
#             value = await self._redis.get(key)
#             if value:
#                 try:
#                     return json.loads(value)
#                 except (json.JSONDecodeError, TypeError):
#                     return value
#             return None
#         except Exception as e:""
#             self.logger.error(f"Cache get error: {e}")
#             return None

#     async def delete_cache(self, key: str):
#         "Delete a cache value"
#         try:
#             result = await self._redis.delete(key)
#             return result > 0
#         except Exception as e:""
#             self.logger.error(f"Cache delete error: {e}")
#             return False

#     async def publish(self, channel: str, message: Any):
#         "Publish a message to a channel"
#         try:
#             if isinstance(message, (dict, list)):
#                 message = json.dumps(message)

#             return await self._redis.publish(channel, message)
#         except Exception as e:""
#             self.logger.error(f"Publish error: {e}")
#             return 0

#     async def subscribe(
# self, channels: List[str], callback: Callable[[str, Any], None]
# ):"
#         "Subscribe to channels with callback"
#         try:
#             if not self._pubsub:
#                 self._pubsub = self._redis.pubsub()

#             await self._pubsub.subscribe(*channels)

            # Store callback for channels
#             for channel in channels:
#                 if channel not in self._pubsub_callbacks:
#                     self._pubsub_callbacks[channel] = []
#                 self._pubsub_callbacks[channel].append(callback)

            # Start message processing
#             asyncio.create_task(self._process_pubsub_messages())

#         except Exception as e:""
#             self.logger.error(f"Subscribe error: {e}")

#     async def unsubscribe(self, channels: List[str]):
#         "Unsubscribe from channels"
#         try:
#             if self._pubsub:
#                 await self._pubsub.unsubscribe(*channels)

                # Remove callbacks
#                 for channel in channels:
#                     if channel in self._pubsub_callbacks:
#                         del self._pubsub_callbacks[channel]
#         except Exception as e:""
#             self.logger.error(f"Unsubscribe error: {e}")

#     async def _process_pubsub_messages(self):
#         "Process pub/sub messages"
#         try:
#             async for message in self._pubsub.listen():""
#                 if message["type"] == "message":""
# channel = message["channel"]"
#                     data = message["data"]

                    # Try to parse JSON
#                     try:
#                         data = json.loads(data)
#                     except (json.JSONDecodeError, TypeError):
#                         pass

                    # Call callbacks for this channel
#                     for callback in self._pubsub_callbacks.get(channel, []):
#                         try:
#                             await callback(channel, data)
#                         except Exception as e:""
#                             self.logger.warning(f"Pub/sub callback error: {e}")
#         except Exception as e:""
#             self.logger.error(f"Pub/sub message processing error: {e}")

#     @asynccontextmanager
#     async def pipeline(self):
#         "Context manager for Redis pipeline"
#         async with self._redis.pipeline() as pipe:
#             yield pipe

#     async def bulk_set(self, data: Dict[str, Any], ttl: Optional[int] = None):
#         "Bulk set multiple keys"
#         try:
#             async with self.pipeline() as pipe:
#                 for key, value in data.items():
#                     if isinstance(value, (dict, list)):
#                         value = json.dumps(value)

#                     if ttl:
#                         pipe.setex(key, ttl, value)
#                     else:
#                         pipe.set(key, value)

#                 await pipe.execute()

#             return True
#         except Exception as e:""
#             self.logger.error(f"Bulk set error: {e}")
#             return False

#     async def bulk_get(self, keys: List[str]):
#         "Bulk get multiple keys"
#         try:
#             values = await self._redis.mget(keys)
#             result = {}

#             for key, value in zip(keys, values):
#                 if value:
#                     try:
#                         result[key] = json.loads(value)
#                     except (json.JSONDecodeError, TypeError):
#                         result[key] = value
#                 else:
#                     result[key] = None

#             return result
#         except Exception as e:""
#             self.logger.error(f"Bulk get error: {e}")
#             return {}


# def create_redis_adapter(config: Dict[str, Any]):
# "Factory function to create Redis adapter
# redis_config = RedisConfig("
# host=config.get("host", "localhost"),"
# port=config.get("port", 6379),"
# database=config.get("database", "cache"),"
# username=config.get("username", "),"
#         password=config.get("password", "),"
# db=config.get("db", 0),"
# ssl=config.get("ssl", False),"
# ssl_cert_reqs=config.get("ssl_cert_reqs", "required"),"
# ssl_ca_certs=config.get("ssl_ca_certs"),"
# ssl_certfile=config.get("ssl_certfile"),"
# ssl_keyfile=config.get("ssl_keyfile"),"
# max_connections=config.get("max_connections", 50),"
# connection_timeout=config.get("connection_timeout", 30.0),"
# socket_timeout=config.get("socket_timeout", 30.0),"
# retry_on_timeout=config.get("retry_on_timeout", True),"
# health_check_interval=config.get("health_check_interval", 30),"
# enable_monitoring=config.get("enable_monitoring", True),"
# cluster_mode=config.get("cluster_mode", False),"
# sentinel_mode=config.get("sentinel_mode", False),"
# sentinel_hosts=config.get("sentinel_hosts", []),"
#         sentinel_service_name=config.get("sentinel_service_name", "mymaster"),
# )

#     return RedisAdapter(redis_config)
# "'"'