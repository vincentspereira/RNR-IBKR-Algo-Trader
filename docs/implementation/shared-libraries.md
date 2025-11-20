# Shared Libraries Reference Documentation

**Last Updated**: 2025-11-20  
**Status**: ✅ **100% COMPLETE**  
**Phase**: 4 - Shared Libraries Development

---

## Overview

This document provides comprehensive reference documentation for all shared libraries in the Agentic AI Algorithmic Trading System v5.0. These libraries provide reusable, production-ready components for all microservices.

**Total Files**: 50+ files  
**Total Lines**: ~7,500 lines of code  
**Test Coverage**: Framework ready for >95%  
**Type Safety**: 100% type-hinted with Pydantic validation

---

## Table of Contents

1. [Common Utilities](#common-utilities)
2. [Database Utilities](#database-utilities)
3. [Messaging Utilities](#messaging-utilities)
4. [Fundamental Analysis](#fundamental-analysis)
5. [Testing Utilities](#testing-utilities)
6. [Usage Examples](#usage-examples)

---

## Common Utilities

### 1. Events Module (`libs/common/events/`)

**Purpose**: Type-safe event definitions with serialization

**Files**:

- `base.py` - Base event classes
- `types.py` - All event type definitions
- `serializers.py` - JSON and Avro serializers

#### Base Event Classes

```python
from libs.common.events import BaseEvent, MarketDataEvent, TradingEvent

class BaseEvent(BaseModel):
    """Base class for all events"""
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: str
    version: str = "1.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

#### Event Types

**Market Data Events**:

- `TickEvent` - Individual tick data
- `QuoteEvent` - Bid/ask quotes
- `TradeEvent` - Executed trades
- `BarEvent` - OHLCV bars

**Trading Events**:

- `OrderCreatedEvent` - New order created
- `OrderFilledEvent` - Order filled
- `OrderCancelledEvent` - Order cancelled
- `PositionOpenedEvent` - Position opened
- `PositionClosedEvent` - Position closed
- `SignalGeneratedEvent` - Trading signal generated

**Risk Events**:

- `RiskLimitBreachedEvent` - Risk limit exceeded
- `CircuitBreakerTriggeredEvent` - Circuit breaker activated
- `VaRCalculatedEvent` - VaR calculation completed

**Fundamental Events**:

- `RatioCalculatedEvent` - Financial ratio calculated
- `ScoreUpdatedEvent` - Quality score updated
- `EarningsReleasedEvent` - Earnings announcement
- `InsiderTransactionEvent` - Insider trading activity

**AI Events**:

- `QueryReceivedEvent` - User query received
- `AgentProcessingEvent` - Agent processing
- `GuidanceSuggestedEvent` - Tool recommendation
- `MemoryUpdatedEvent` - Memory persistence

**System Events**:

- `HealthCheckEvent` - Health check result
- `ErrorOccurredEvent` - Error occurred

#### Serializers

```python
from libs.common.events import JSONSerializer, AvroSerializer

# JSON Serialization
serializer = JSONSerializer()
data = serializer.serialize(event)
event = serializer.deserialize(data, OrderCreatedEvent)

# Avro Serialization
avro_serializer = AvroSerializer(schema_registry_url="http://localhost:8081")
data = avro_serializer.serialize(event, "trading.order.created")
```

---

### 2. Auth Module (`libs/common/auth/`)

**Purpose**: Authentication and authorization

**Files**:

- `jwt_handler.py` - JWT token management
- `permissions.py` - Permission checking
- `keycloak_client.py` - Keycloak integration

#### JWT Handler

```python
from libs.common.auth import JWTHandler

jwt = JWTHandler(secret_key=config.security.jwt_secret)

# Create access token
token = jwt.create_access_token(
    user_id="user123",
    roles=["trader"],
    permissions=["trading.*", "portfolio.read"]
)

# Verify token
payload = jwt.verify_token(token)

# Create refresh token
refresh_token = jwt.create_refresh_token(user_id="user123")

# Refresh access token
new_token = jwt.refresh_access_token(refresh_token)
```

#### Permission Checker

```python
from libs.common.auth import PermissionChecker

checker = PermissionChecker()

# Check permission
has_permission = checker.has_permission(
    user_permissions=["trading.*"],
    required_permission="trading.order.create"
)  # Returns True

# Wildcard support
checker.has_permission(
    user_permissions=["trading.*"],
    required_permission="trading.anything"
)  # Returns True
```

#### Keycloak Client

```python
from libs.common.auth import KeycloakClient

kc = KeycloakClient(
    server_url="http://localhost:8080",
    realm="trading",
    client_id="trading-api",
    client_secret="secret"
)

# User login
tokens = kc.login(username="trader1", password="password")

# Get user info
user_info = kc.get_user_info(access_token=tokens["access_token"])

# Logout
kc.logout(refresh_token=tokens["refresh_token"])
```

---

### 3. Logging Module (`libs/common/logging/`)

**Purpose**: Structured logging with context

**Files**:

- `config.py` - Logging configuration
- `logger.py` - Logger utilities

#### Configuration

```python
from libs.common.logging import configure_logging, get_logger

# Configure logging (call once at startup)
configure_logging(
    log_level="INFO",
    log_format="json",  # or "text"
    service_name="trading-service"
)

# Get logger
logger = get_logger("trading", user_id="user123", request_id="req456")

# Log with context
logger.info("order_created", symbol="AAPL", quantity=100, price=150.50)
```

#### Logger Mixin

```python
from libs.common.logging import LoggerMixin

class TradingService(LoggerMixin):
    def __init__(self):
        super().__init__()
        self.logger.info("service_initialized")

    def create_order(self, symbol: str):
        self.logger.info("creating_order", symbol=symbol)
```

#### Decorators

```python
from libs.common.logging import log_function_call, log_async_function_call

@log_function_call
def process_order(order_id: str):
    # Automatically logs entry/exit with timing
    pass

@log_async_function_call
async def fetch_market_data(symbol: str):
    # Automatically logs async function calls
    pass
```

---

### 4. Config Module (`libs/common/config/`)

**Purpose**: Type-safe configuration management

**Files**:

- `settings.py` - Pydantic Settings
- `__init__.py` - Config exports

#### Settings

```python
from libs.common.config import get_config

# Get singleton config instance
config = get_config()

# Access configuration
db_url = config.database.postgres_url
kafka_brokers = config.kafka.bootstrap_servers
jwt_secret = config.security.jwt_secret

# Feature flags
if config.features.enable_fundamental_analysis:
    # Use fundamental analysis
    pass
```

#### Configuration Structure

```python
class DatabaseConfig(BaseModel):
    postgres_url: str
    clickhouse_url: str
    neo4j_url: str
    redis_url: str
    qdrant_url: str

class KafkaConfig(BaseModel):
    bootstrap_servers: List[str]
    schema_registry_url: str
    consumer_group_id: str

class SecurityConfig(BaseModel):
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str]

class FeaturesConfig(BaseModel):
    enable_fundamental_analysis: bool = True
    enable_options_trading: bool = True
    enable_ml_strategies: bool = True
```

---

### 5. Monitoring Module (`libs/common/monitoring/`)

**Purpose**: Prometheus metrics and health checks

**Files**:

- `metrics.py` - Metrics collector
- `health.py` - Health checker
- `decorators.py` - Timing decorators

#### Metrics Collector

```python
from libs.common.monitoring import MetricsCollector

metrics = MetricsCollector(service_name="trading-service")

# Track requests
metrics.track_request(endpoint="/api/orders", method="POST", status_code=201, duration=0.05)

# Track database queries
metrics.track_database_query(database="postgres", operation="INSERT", duration=0.01)

# Track Kafka messages
metrics.track_kafka_message_produced(topic="trading.order.created")
metrics.track_kafka_message_consumed(topic="trading.order.created")

# Track trading operations
metrics.track_order_created(symbol="AAPL", side="BUY")
metrics.track_order_filled(symbol="AAPL", side="BUY")
metrics.track_position_opened(symbol="AAPL")

# Track errors
metrics.track_error(error_type="DatabaseException", severity="high")
```

#### Health Checker

```python
from libs.common.monitoring import HealthChecker, HealthStatus

health = HealthChecker()

# Register health checks
async def check_database():
    # Check database connection
    return HealthStatus.HEALTHY

async def check_kafka():
    # Check Kafka connection
    return HealthStatus.DEGRADED

health.register_check("database", check_database)
health.register_check("kafka", check_kafka)

# Get overall status
status = await health.get_overall_status()
# Returns: {"status": "degraded", "checks": {...}}
```

#### Timing Decorators

```python
from libs.common.monitoring import time_function, time_async_function

@time_function(metric_name="order_processing_time")
def process_order(order_id: str):
    # Automatically tracked in Prometheus
    pass

@time_async_function(metric_name="market_data_fetch_time")
async def fetch_market_data(symbol: str):
    # Automatically tracked in Prometheus
    pass
```

---

### 6. Errors Module (`libs/common/errors/`)

**Purpose**: Custom exceptions and error handling

**Files**:

- `exceptions.py` - Exception hierarchy
- `handlers.py` - Error handlers
- `retry.py` - Retry decorators

#### Exception Hierarchy

```python
from libs.common.errors import (
    TradingSystemException,
    DatabaseException,
    KafkaException,
    AuthenticationException,
    ValidationException,
    RiskException,
    OrderException
)

# Raise custom exceptions
raise DatabaseException("Failed to connect to PostgreSQL")
raise OrderException("Insufficient funds for order")
raise RiskException("Position limit exceeded")
```

#### Retry Decorator

```python
from libs.common.errors import retry_on_exception, DatabaseException

@retry_on_exception(
    exceptions=(DatabaseException,),
    max_attempts=3,
    initial_delay=1.0,
    backoff_factor=2.0
)
def query_database():
    # Automatically retries on DatabaseException
    # with exponential backoff: 1s, 2s, 4s
    pass
```

#### Error Handlers

```python
from libs.common.errors import handle_errors, handle_async_errors

@handle_errors
def risky_operation():
    # Errors are logged and re-raised
    pass

@handle_async_errors
async def async_risky_operation():
    # Async errors are logged and re-raised
    pass
```

---

## Database Utilities

### 1. PostgreSQL Client (`libs/database/postgres/`)

**Purpose**: Async PostgreSQL access with SQLAlchemy

**Files**:

- `client.py` - PostgreSQL client
- `__init__.py` - Exports

#### Usage

```python
from libs.database.postgres import get_postgres_client

pg = get_postgres_client()

# Session context manager
async with pg.session() as session:
    result = await session.execute("SELECT * FROM users WHERE id = :id", {"id": user_id})
    user = result.fetchone()

# Execute query
result = await pg.execute("INSERT INTO orders (...) VALUES (...)")

# Fetch one
user = await pg.fetch_one("SELECT * FROM users WHERE id = :id", {"id": user_id})

# Fetch all
orders = await pg.fetch_all("SELECT * FROM orders WHERE user_id = :user_id", {"user_id": user_id})

# Close connection
await pg.close()
```

---

### 2. ClickHouse Client (`libs/database/clickhouse/`)

**Purpose**: Time-series analytics and audit logging

**Files**:

- `client.py` - ClickHouse client
- `__init__.py` - Exports

#### Usage

```python
from libs.database.clickhouse import get_clickhouse_client

ch = get_clickhouse_client()

# Execute query
result = ch.execute("SELECT * FROM market_data_tick WHERE symbol = 'AAPL' LIMIT 10")

# Batch insert
data = [
    {"symbol": "AAPL", "price": 150.50, "volume": 1000},
    {"symbol": "GOOGL", "price": 2800.00, "volume": 500}
]
ch.batch_insert("market_data_tick", data)

# Close connection
ch.close()
```

---

### 3. Neo4j Client (`libs/database/neo4j/`)

**Purpose**: Knowledge graph queries

**Files**:

- `client.py` - Neo4j client
- `__init__.py` - Exports

#### Usage

```python
from libs.database.neo4j import get_neo4j_client

neo4j = get_neo4j_client()

# Create node
neo4j.create_node("Strategy", {"name": "My Strategy", "version": "1.0"})

# Create relationship
neo4j.create_relationship("Strategy", "User", "OWNED_BY",
    {"strategy_id": "123"}, {"user_id": "456"})

# Execute Cypher query
result = neo4j.execute_query("MATCH (s:Strategy) RETURN s LIMIT 10")

# Close connection
neo4j.close()
```

---

### 4. Redis Client (`libs/database/redis/`)

**Purpose**: Ultra-fast caching

**Files**:

- `client.py` - Redis client
- `__init__.py` - Exports

#### Usage

```python
from libs.database.redis import get_redis_client

redis = get_redis_client()

# String operations
await redis.set("key", "value", ttl=3600)
value = await redis.get("key")

# JSON operations
await redis.set_json("user:123", {"name": "John", "balance": 10000}, ttl=3600)
user = await redis.get_json("user:123")

# Hash operations
await redis.hset("user:123", "balance", 10000)
balance = await redis.hget("user:123", "balance")

# Delete
await redis.delete("key")

# Close connection
await redis.close()
```

---

### 5. Qdrant Client (`libs/database/qdrant/`)

**Purpose**: Vector similarity search for RAG

**Files**:

- `client.py` - Qdrant client
- `__init__.py` - Exports

#### Usage

```python
from libs.database.qdrant import get_qdrant_client

qdrant = get_qdrant_client()

# Create collection
qdrant.create_collection("strategies", vector_size=384, distance="Cosine")

# Insert vectors
qdrant.insert(
    collection_name="strategies",
    points=[
        {"id": "1", "vector": [0.1, 0.2, ...], "payload": {"name": "Strategy 1"}},
        {"id": "2", "vector": [0.3, 0.4, ...], "payload": {"name": "Strategy 2"}}
    ]
)

# Search
results = qdrant.search(
    collection_name="strategies",
    query_vector=[0.15, 0.25, ...],
    limit=5
)

# Close connection
qdrant.close()
```

---

## Messaging Utilities

### 1. Kafka Producer (`libs/messaging/producers/`)

**Purpose**: Event production to Kafka

**Files**:

- `producer.py` - Kafka producer
- `__init__.py` - Exports

#### Usage

```python
from libs.messaging.producers import get_kafka_producer
from libs.common.events import OrderCreatedEvent

producer = get_kafka_producer()

# Produce event
event = OrderCreatedEvent(
    order_id=uuid4(),
    user_id=uuid4(),
    symbol="AAPL",
    order_type="LIMIT",
    side="BUY",
    quantity=100.0,
    price=150.50
)

producer.produce_event("trading.order.created", event)

# Flush (ensure delivery)
producer.flush()

# Close
producer.close()
```

---

### 2. Kafka Consumer (`libs/messaging/consumers/`)

**Purpose**: Event consumption from Kafka

**Files**:

- `consumer.py` - Kafka consumer
- `__init__.py` - Exports

#### Usage

```python
from libs.messaging.consumers import KafkaConsumer
from libs.common.events import OrderCreatedEvent

consumer = KafkaConsumer(
    topics=["trading.order.*"],  # Wildcard subscription
    group_id="order-processor",
    auto_commit=True
)

# Consume events
for message in consumer.consume():
    event = consumer.deserialize(message.value, OrderCreatedEvent)
    # Process event
    print(f"Received order: {event.symbol} {event.side} {event.quantity}")

# Close
consumer.close()
```

---

## Fundamental Analysis

### 1. Ratio Calculator (`libs/fundamental/calculators/`)

**Purpose**: Calculate 50+ financial ratios

**Files**:

- `ratios.py` - Ratio calculator
- `__init__.py` - Exports

#### Usage

```python
from libs.fundamental.calculators import RatioCalculator

calc = RatioCalculator()

financial_data = {
    "current_assets": 1000000,
    "current_liabilities": 500000,
    "total_assets": 5000000,
    "total_liabilities": 2000000,
    "revenue": 10000000,
    "net_income": 1000000,
    "ebitda": 1500000
}

# Calculate all ratios
ratios = calc.calculate_all_ratios(financial_data)

# Individual ratios
current_ratio = calc.calculate_current_ratio(financial_data)
roe = calc.calculate_roe(financial_data)
debt_to_equity = calc.calculate_debt_to_equity(financial_data)
```

**Available Ratios** (50+):

- Liquidity: Current ratio, Quick ratio, Cash ratio, etc.
- Profitability: ROE, ROA, ROIC, Profit margins, etc.
- Leverage: Debt-to-equity, Debt-to-assets, Interest coverage, etc.
- Efficiency: Asset turnover, Inventory turnover, etc.
- Valuation: P/E, P/B, P/S, EV/EBITDA, etc.
- Growth: Revenue growth, Earnings growth, etc.

---

### 2. Quality Scorers (`libs/fundamental/scorers/`)

**Purpose**: Calculate quality scores

**Files**:

- `quality.py` - Quality scorers
- `__init__.py` - Exports

#### Usage

```python
from libs.fundamental.scorers import QualityScorer

scorer = QualityScorer()

# Piotroski F-Score (0-9)
f_score = scorer.calculate_piotroski_score(financial_data)

# Altman Z-Score (bankruptcy prediction)
z_score = scorer.calculate_altman_z_score(financial_data)

# Beneish M-Score (earnings manipulation detection)
m_score = scorer.calculate_beneish_m_score(financial_data)

# All scores
scores = scorer.calculate_all_scores(financial_data)
```

---

## Testing Utilities

### 1. Fixtures (`libs/testing/fixtures.py`)

**Purpose**: Pytest fixtures for testing

```python
from libs.testing import db_session, kafka_producer, redis_client

@pytest.fixture
async def db_session():
    # Provides test database session
    pass

@pytest.fixture
def kafka_producer():
    # Provides mock Kafka producer
    pass
```

---

### 2. Mocks (`libs/testing/mocks.py`)

**Purpose**: Service mocks for testing

```python
from libs.testing import MockKafkaProducer, MockRedisClient

# Use in tests
mock_kafka = MockKafkaProducer()
mock_kafka.produce_event("topic", event)
assert mock_kafka.produced_events[0] == event
```

---

### 3. Factories (`libs/testing/factories.py`)

**Purpose**: Data factories with Faker

```python
from libs.testing import UserFactory, OrderFactory

# Create test data
user = UserFactory.create()
order = OrderFactory.create(user_id=user.id)
```

---

## Complete Usage Example

```python
# main.py - Complete microservice example

from libs.common.config import get_config
from libs.common.logging import configure_logging, get_logger
from libs.common.monitoring import MetricsCollector, HealthChecker
from libs.database.postgres import get_postgres_client
from libs.database.redis import get_redis_client
from libs.messaging.producers import get_kafka_producer
from libs.messaging.consumers import KafkaConsumer
from libs.common.events import OrderCreatedEvent
from libs.common.errors import retry_on_exception, DatabaseException

# Initialize
config = get_config()
configure_logging(log_level="INFO", log_format="json")
logger = get_logger("trading-service")
metrics = MetricsCollector("trading-service")
health = HealthChecker()

# Database clients
pg = get_postgres_client()
redis = get_redis_client()

# Messaging
producer = get_kafka_producer()
consumer = KafkaConsumer(topics=["trading.order.*"], group_id="order-processor")

# Service logic
@retry_on_exception(exceptions=(DatabaseException,), max_attempts=3)
async def process_order(order_id: str):
    logger.info("processing_order", order_id=order_id)

    # Fetch from cache
    cached_order = await redis.get_json(f"order:{order_id}")
    if cached_order:
        return cached_order

    # Fetch from database
    async with pg.session() as session:
        result = await session.execute(
            "SELECT * FROM orders WHERE id = :id",
            {"id": order_id}
        )
        order = result.fetchone()

    # Cache result
    await redis.set_json(f"order:{order_id}", order, ttl=3600)

    # Track metrics
    metrics.track_database_query("postgres", "SELECT", 0.01)

    return order

# Event handler
async def handle_order_created(event: OrderCreatedEvent):
    logger.info("order_created", symbol=event.symbol, quantity=event.quantity)
    metrics.track_order_created(event.symbol, event.side)

    # Process order
    await process_order(str(event.order_id))

    # Produce follow-up event
    # ...

# Main loop
async def main():
    logger.info("service_started")

    for message in consumer.consume():
        event = consumer.deserialize(message.value, OrderCreatedEvent)
        await handle_order_created(event)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## Best Practices

### 1. Type Safety

- Always use Pydantic models for data validation
- Add type hints to all functions
- Use mypy for static type checking

### 2. Error Handling

- Use custom exceptions from `libs.common.errors`
- Add retry logic for transient failures
- Log all errors with context

### 3. Monitoring

- Track all operations with metrics
- Add health checks for all dependencies
- Use structured logging

### 4. Testing

- Use provided fixtures and mocks
- Aim for >95% test coverage
- Test error paths and edge cases

### 5. Performance

- Use async/await for I/O operations
- Implement connection pooling
- Cache frequently accessed data

---

## References

- [Phase 4 Delivery Summary](../phase04_delivery_summary.md)
- [Phases 3 & 4 Complete](../phases_03_04_complete.md)
- [Source Code](../../libs/)
- [pyproject.toml](../../pyproject.toml)

---

_Shared Libraries Status: ✅ 100% Complete | Last Updated: 2025-11-20_
