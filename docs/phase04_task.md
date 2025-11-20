# Phase 4: Shared Libraries Development (Weeks 5-6)

## Agentic AI Algorithmic Trading System v5.0

**Current Phase**: 4 of 28  
**Status**: In Progress  
**Last Updated**: 2025-11-20  
**Duration**: 1 week (Weeks 5-6 of 55-week project)

---

## Overview

Create reusable shared libraries that will be used across all 28 microservices. These libraries provide common functionality for event handling, authentication, logging, database access, and testing.

**Phase 3 Deliverables**: ✅ Complete

- All 5 databases deployed and operational
- Kafka with 43 topics created
- Monitoring stack (Prometheus, Grafana)
- Complete infrastructure verified

**Phase 4 Goal**: Production-ready shared libraries for all microservices.

---

## Shared Libraries Structure

```
libs/
├── common/              # Common utilities (all services)
│   ├── events/         # Event schemas and handlers
│   ├── auth/           # Authentication helpers
│   ├── logging/        # Structured logging
│   ├── config/         # Configuration management
│   ├── monitoring/     # Metrics and health checks
│   └── errors/         # Error handling
├── database/           # Database utilities
│   ├── postgres/       # PostgreSQL helpers
│   ├── clickhouse/     # ClickHouse helpers
│   ├── neo4j/          # Neo4j helpers
│   ├── redis/          # Redis helpers
│   └── qdrant/         # Qdrant helpers
├── messaging/          # Kafka utilities
│   ├── producers/      # Kafka producers
│   ├── consumers/      # Kafka consumers
│   └── schemas/        # Avro schemas
├── fundamental/        # Fundamental analysis utilities
│   ├── calculators/    # Ratio calculators
│   ├── models/         # Valuation models
│   └── scorers/        # Quality scorers
└── testing/            # Testing utilities
    ├── fixtures/       # Test fixtures
    ├── mocks/          # Mock objects
    └── factories/      # Data factories
```

---

## Library 1: Common Utilities (`libs/common/`)

### Events Module

- [ ] **Create Event Base Classes**

  - [ ] `BaseEvent` - Abstract base for all events
  - [ ] `MarketDataEvent` - Market data events
  - [ ] `TradingEvent` - Trading events
  - [ ] `RiskEvent` - Risk events
  - [ ] `FundamentalEvent` - Fundamental analysis events (NEW)
  - [ ] `AIEvent` - AI/ML events
  - [ ] `SystemEvent` - System events

- [ ] **Event Serialization**

  - [ ] JSON serializer
  - [ ] Avro serializer
  - [ ] Event validation
  - [ ] Schema evolution support

- [ ] **Event Utilities**
  - [ ] Event ID generation (UUID)
  - [ ] Timestamp utilities
  - [ ] Event correlation IDs
  - [ ] Event metadata handling

### Authentication Module

- [ ] **JWT Utilities**

  - [ ] Token generation
  - [ ] Token validation
  - [ ] Token refresh
  - [ ] Claims extraction
  - [ ] Token expiration handling

- [ ] **Keycloak Integration**

  - [ ] Keycloak client wrapper
  - [ ] User authentication
  - [ ] Role-based access control (RBAC)
  - [ ] Permission checking
  - [ ] Session management

- [ ] **API Key Management**
  - [ ] API key generation
  - [ ] API key validation
  - [ ] Rate limiting per key
  - [ ] Key rotation utilities

### Logging Module

- [ ] **Structured Logging**

  - [ ] JSON logger configuration
  - [ ] Log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - [ ] Context injection (request_id, user_id, service_name)
  - [ ] Performance logging (latency tracking)
  - [ ] Error logging with stack traces

- [ ] **Log Formatters**

  - [ ] JSON formatter
  - [ ] Human-readable formatter (development)
  - [ ] Correlation ID formatter
  - [ ] Timestamp formatting (ISO 8601)

- [ ] **Log Handlers**
  - [ ] Console handler
  - [ ] File handler (rotating)
  - [ ] Loki handler (for log aggregation)
  - [ ] Error notification handler

### Configuration Module

- [ ] **Environment Configuration**

  - [ ] `.env` file loader
  - [ ] Environment variable validation
  - [ ] Type conversion (string → int, bool, etc.)
  - [ ] Required vs. optional settings
  - [ ] Default values

- [ ] **Service Configuration**

  - [ ] Database connection configs
  - [ ] Kafka connection configs
  - [ ] API endpoint configs
  - [ ] Feature flags
  - [ ] Performance tuning parameters

- [ ] **Configuration Validation**
  - [ ] Pydantic models for config
  - [ ] Validation on startup
  - [ ] Configuration documentation
  - [ ] Environment-specific configs (dev, staging, prod)

### Monitoring Module

- [ ] **Metrics Collection**

  - [ ] Prometheus metrics wrapper
  - [ ] Counter metrics
  - [ ] Gauge metrics
  - [ ] Histogram metrics (latency)
  - [ ] Summary metrics

- [ ] **Health Checks**

  - [ ] Service health check endpoint
  - [ ] Database health checks
  - [ ] Kafka health checks
  - [ ] Dependency health checks
  - [ ] Readiness vs. liveness probes

- [ ] **Performance Tracking**
  - [ ] Request latency tracking
  - [ ] Database query timing
  - [ ] Kafka message timing
  - [ ] Function execution timing (decorators)

### Error Handling Module

- [ ] **Custom Exceptions**

  - [ ] `TradingSystemException` - Base exception
  - [ ] `DatabaseException` - Database errors
  - [ ] `KafkaException` - Kafka errors
  - [ ] `AuthenticationException` - Auth errors
  - [ ] `ValidationException` - Validation errors
  - [ ] `RateLimitException` - Rate limit errors

- [ ] **Error Handlers**
  - [ ] Global exception handler
  - [ ] Error response formatting
  - [ ] Error logging
  - [ ] Error notifications (critical errors)
  - [ ] Retry logic for transient errors

---

## Library 2: Database Utilities (`libs/database/`)

### PostgreSQL Module

- [ ] **Connection Management**

  - [ ] Connection pool configuration
  - [ ] Connection context manager
  - [ ] Transaction management
  - [ ] Connection health checks

- [ ] **Query Utilities**

  - [ ] Query builder helpers
  - [ ] Parameterized queries
  - [ ] Bulk insert utilities
  - [ ] Pagination helpers
  - [ ] Query performance logging

- [ ] **ORM Integration**

  - [ ] SQLAlchemy models base
  - [ ] Session management
  - [ ] Repository pattern implementation
  - [ ] Unit of Work pattern

- [ ] **Migration Utilities**
  - [ ] Alembic integration
  - [ ] Migration helpers
  - [ ] Schema versioning
  - [ ] Rollback utilities

### ClickHouse Module

- [ ] **Connection Management**

  - [ ] ClickHouse client wrapper
  - [ ] Connection pooling
  - [ ] Query execution
  - [ ] Batch insert optimization

- [ ] **Time-Series Utilities**

  - [ ] Time-series insert helpers
  - [ ] Partitioning utilities
  - [ ] TTL management
  - [ ] Aggregation queries

- [ ] **Performance Optimization**
  - [ ] Compression settings
  - [ ] Batch size optimization
  - [ ] Query optimization helpers
  - [ ] Index management

### Neo4j Module

- [ ] **Connection Management**

  - [ ] Neo4j driver wrapper
  - [ ] Session management
  - [ ] Transaction handling
  - [ ] Connection pooling

- [ ] **Graph Utilities**

  - [ ] Node creation helpers
  - [ ] Relationship creation helpers
  - [ ] Cypher query builders
  - [ ] Graph traversal utilities

- [ ] **Knowledge Graph Helpers**
  - [ ] Strategy graph utilities
  - [ ] Agent workflow utilities
  - [ ] Dependency graph utilities

### Redis Module

- [ ] **Connection Management**

  - [ ] Redis client wrapper
  - [ ] Connection pooling
  - [ ] Sentinel support (optional)
  - [ ] Cluster support (optional)

- [ ] **Caching Utilities**

  - [ ] Cache decorator
  - [ ] TTL management
  - [ ] Cache invalidation
  - [ ] Cache warming

- [ ] **Data Structures**

  - [ ] String operations
  - [ ] Hash operations
  - [ ] List operations
  - [ ] Set operations
  - [ ] Sorted set operations

- [ ] **Pub/Sub Utilities**
  - [ ] Publisher wrapper
  - [ ] Subscriber wrapper
  - [ ] Channel management

### Qdrant Module

- [ ] **Connection Management**

  - [ ] Qdrant client wrapper
  - [ ] Collection management
  - [ ] API key authentication

- [ ] **Vector Operations**

  - [ ] Vector insertion
  - [ ] Similarity search
  - [ ] Filtering utilities
  - [ ] Batch operations

- [ ] **Embedding Utilities**
  - [ ] Embedding generation
  - [ ] Embedding caching
  - [ ] Model management

---

## Library 3: Messaging Utilities (`libs/messaging/`)

### Kafka Producers

- [ ] **Producer Base Class**

  - [ ] Kafka producer wrapper
  - [ ] Serialization (JSON, Avro)
  - [ ] Error handling
  - [ ] Retry logic
  - [ ] Delivery guarantees

- [ ] **Specialized Producers**

  - [ ] Market data producer
  - [ ] Trading event producer
  - [ ] Risk event producer
  - [ ] Fundamental event producer (NEW)
  - [ ] AI event producer

- [ ] **Producer Utilities**
  - [ ] Batch sending
  - [ ] Compression
  - [ ] Partitioning strategies
  - [ ] Performance monitoring

### Kafka Consumers

- [ ] **Consumer Base Class**

  - [ ] Kafka consumer wrapper
  - [ ] Deserialization (JSON, Avro)
  - [ ] Error handling
  - [ ] Offset management
  - [ ] Consumer group management

- [ ] **Specialized Consumers**

  - [ ] Market data consumer
  - [ ] Trading event consumer
  - [ ] Risk event consumer
  - [ ] Fundamental event consumer (NEW)

- [ ] **Consumer Utilities**
  - [ ] Message batching
  - [ ] Dead letter queue handling
  - [ ] Poison pill handling
  - [ ] Consumer lag monitoring

### Avro Schemas

- [ ] **Schema Definitions**

  - [ ] Market data schemas
  - [ ] Trading event schemas
  - [ ] Risk event schemas
  - [ ] Fundamental event schemas (NEW)
  - [ ] AI event schemas
  - [ ] System event schemas

- [ ] **Schema Registry Integration**
  - [ ] Schema registration
  - [ ] Schema evolution
  - [ ] Schema compatibility checking
  - [ ] Schema versioning

---

## Library 4: Fundamental Analysis Utilities (`libs/fundamental/`)

### Calculators Module

- [ ] **Ratio Calculators**

  - [ ] Liquidity ratios calculator
  - [ ] Profitability ratios calculator
  - [ ] Leverage ratios calculator
  - [ ] Efficiency ratios calculator
  - [ ] Valuation ratios calculator

- [ ] **Calculator Base Class**
  - [ ] Input validation
  - [ ] Error handling (division by zero, missing data)
  - [ ] Result caching
  - [ ] Calculation logging

### Valuation Models Module

- [ ] **DCF Model**

  - [ ] Free cash flow projection
  - [ ] WACC calculation
  - [ ] Terminal value calculation
  - [ ] Present value calculation

- [ ] **DDM Model**

  - [ ] Dividend growth rate estimation
  - [ ] Required rate of return calculation
  - [ ] Intrinsic value calculation

- [ ] **Other Models**
  - [ ] Graham Number calculator
  - [ ] PEG ratio calculator
  - [ ] EV multiples calculator

### Quality Scorers Module

- [ ] **Piotroski F-Score**

  - [ ] 9-point scoring system
  - [ ] Component calculations
  - [ ] Score interpretation

- [ ] **Altman Z-Score**

  - [ ] Z-Score calculation
  - [ ] Bankruptcy risk assessment
  - [ ] Industry-specific adjustments

- [ ] **Beneish M-Score**
  - [ ] M-Score calculation
  - [ ] Earnings manipulation detection
  - [ ] Red flag identification

---

## Library 5: Testing Utilities (`libs/testing/`)

### Test Fixtures

- [ ] **Database Fixtures**

  - [ ] PostgreSQL test database setup
  - [ ] ClickHouse test database setup
  - [ ] Redis test instance
  - [ ] Test data cleanup

- [ ] **Kafka Fixtures**

  - [ ] Test Kafka broker (testcontainers)
  - [ ] Topic creation
  - [ ] Message production/consumption helpers

- [ ] **Service Fixtures**
  - [ ] Mock API responses
  - [ ] Test user creation
  - [ ] Test strategy creation

### Mock Objects

- [ ] **External Service Mocks**

  - [ ] IBKR TWS mock
  - [ ] Alpha Vantage API mock
  - [ ] Yahoo Finance mock
  - [ ] Keycloak mock

- [ ] **Database Mocks**
  - [ ] In-memory database mocks
  - [ ] Query result mocks
  - [ ] Connection mocks

### Data Factories

- [ ] **Model Factories**

  - [ ] User factory
  - [ ] Strategy factory
  - [ ] Order factory
  - [ ] Trade factory
  - [ ] Market data factory
  - [ ] Fundamental data factory (NEW)

- [ ] **Factory Utilities**
  - [ ] Random data generation
  - [ ] Realistic data generation
  - [ ] Bulk data creation

---

## Documentation

- [ ] **API Documentation**

  - [ ] Docstrings for all public functions
  - [ ] Type hints for all parameters
  - [ ] Usage examples
  - [ ] Sphinx documentation generation

- [ ] **Library Guides**

  - [ ] Getting started guide
  - [ ] Common patterns guide
  - [ ] Best practices guide
  - [ ] Troubleshooting guide

- [ ] **Code Examples**
  - [ ] Example usage for each library
  - [ ] Integration examples
  - [ ] Testing examples

---

## Testing

- [ ] **Unit Tests**

  - [ ] Test coverage >95% for all libraries
  - [ ] Pytest configuration
  - [ ] Test fixtures
  - [ ] Mocking strategies

- [ ] **Integration Tests**

  - [ ] Database integration tests
  - [ ] Kafka integration tests
  - [ ] End-to-end library tests

- [ ] **Performance Tests**
  - [ ] Benchmarking critical functions
  - [ ] Load testing
  - [ ] Memory profiling

---

## Deliverables Checklist

**Common Utilities**:

- [ ] Events module (base classes, serialization)
- [ ] Authentication module (JWT, Keycloak)
- [ ] Logging module (structured logging)
- [ ] Configuration module (env management)
- [ ] Monitoring module (metrics, health checks)
- [ ] Error handling module (exceptions, handlers)

**Database Utilities**:

- [ ] PostgreSQL module (connection, queries, ORM)
- [ ] ClickHouse module (time-series, optimization)
- [ ] Neo4j module (graph operations)
- [ ] Redis module (caching, pub/sub)
- [ ] Qdrant module (vector operations)

**Messaging Utilities**:

- [ ] Kafka producers (base + specialized)
- [ ] Kafka consumers (base + specialized)
- [ ] Avro schemas (all event types)

**Fundamental Analysis Utilities**:

- [ ] Ratio calculators (50+ ratios)
- [ ] Valuation models (DCF, DDM, Graham, PEG)
- [ ] Quality scorers (Piotroski, Altman, Beneish)

**Testing Utilities**:

- [ ] Test fixtures (databases, Kafka)
- [ ] Mock objects (external services)
- [ ] Data factories (model creation)

**Documentation**:

- [ ] API documentation (Sphinx)
- [ ] Library guides
- [ ] Code examples

---

## Success Criteria

- ✅ All libraries implemented and tested
- ✅ Test coverage >95%
- ✅ Documentation complete
- ✅ Code examples provided
- ✅ Integration tests passing
- ✅ Performance benchmarks met
- ✅ Ready for use in microservices (Phase 5+)

---

## Timeline & Progress

**Week 5** (Days 1-5):

- Days 1-2: Common utilities (events, auth, logging, config)
- Days 3-4: Database utilities (all 5 databases)
- Day 5: Messaging utilities (Kafka producers/consumers)

**Week 6** (Days 1-5):

- Days 1-2: Fundamental analysis utilities
- Days 3-4: Testing utilities
- Day 5: Documentation, final testing, Phase 4 completion

**Dependencies**:

- Phase 3 complete ✅

**Blockers**:

- None identified

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-20  
**Status**: Active
