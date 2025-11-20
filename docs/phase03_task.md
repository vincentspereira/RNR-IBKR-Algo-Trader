# Phase 3: Infrastructure & Database Setup (Weeks 3-5)

## Agentic AI Algorithmic Trading System v5.0

**Current Phase**: 3 of 28  
**Status**: In Progress  
**Last Updated**: 2025-11-20  
**Duration**: 2 weeks (Weeks 3-5 of 55-week project)

---

## Overview

Deploy and configure all infrastructure components for the trading system: 5 databases, Apache Kafka event bus, GPU acceleration, and comprehensive monitoring stack.

**Phase 2 Deliverables**: ✅ Complete

- README.md comprehensive update
- 2 OpenAPI specs (Trading Engine, Fundamental Analysis)
- Getting Started guide
- Documentation framework

**Phase 3 Goal**: Production-ready infrastructure foundation for all 28 microservices.

---

## Database Setup

### PostgreSQL 17 + pgvector

- [ ] **Deploy PostgreSQL Container**

  - [ ] Pull official PostgreSQL 17 image
  - [ ] Configure docker-compose service
  - [ ] Set environment variables (password, database name)
  - [ ] Configure volume mounts for data persistence
  - [ ] Set resource limits (memory, CPU)
  - [ ] Expose port 5432

- [ ] **Install pgvector Extension**

  - [ ] Build custom Docker image with pgvector
  - [ ] Enable pgvector extension in database
  - [ ] Verify vector operations work
  - [ ] Test vector similarity search

- [ ] **Create Database Schemas**

  - [ ] Trading schema
    - [ ] `orders` table
    - [ ] `trades` table
    - [ ] `positions` table
    - [ ] `strategies` table
  - [ ] Portfolio schema
    - [ ] `portfolios` table
    - [ ] `holdings` table
    - [ ] `performance` table
    - [ ] `transactions` table
  - [ ] User schema
    - [ ] `users` table
    - [ ] `roles` table
    - [ ] `user_roles` table
    - [ ] `sessions` table
    - [ ] `api_keys` table
  - [ ] Fundamental schema (NEW - Phase 15.5)
    - [ ] `companies` table
    - [ ] `financial_statements` table
    - [ ] `financial_ratios` table
    - [ ] `valuation_models` table
    - [ ] `quality_scores` table
    - [ ] `fundamental_scores` table
    - [ ] `earnings_data` table
    - [ ] `insider_transactions` table
    - [ ] `industry_metrics` table
    - [ ] `esg_scores` table
  - [ ] Strategy schema
    - [ ] `strategy_versions` table
    - [ ] `backtest_results` table
    - [ ] `deployed_strategies` table
  - [ ] Vector schema
    - [ ] `strategy_embeddings` table (with vector column)
    - [ ] `conversation_embeddings` table
    - [ ] Create vector indexes

- [ ] **Configure Database**

  - [ ] Set max_connections = 200
  - [ ] Configure shared_buffers (4GB)
  - [ ] Set effective_cache_size (16GB)
  - [ ] Enable query logging for slow queries (>100ms)
  - [ ] Configure autovacuum settings
  - [ ] Set up replication (optional for production)

- [ ] **Create Database Migrations**

  - [ ] Set up Alembic migration framework
  - [ ] Create initial migration scripts
  - [ ] Document migration procedures
  - [ ] Test migration rollback

- [ ] **Database Security**
  - [ ] Create database users with minimal privileges
  - [ ] Set up SSL/TLS connections
  - [ ] Configure pg_hba.conf for access control
  - [ ] Enable audit logging
  - [ ] Implement row-level security policies

---

### ClickHouse 24.8

- [ ] **Deploy ClickHouse Container**

  - [ ] Pull official ClickHouse 24.8 image
  - [ ] Configure docker-compose service
  - [ ] Set environment variables
  - [ ] Configure volume mounts
  - [ ] Expose ports (8123 HTTP, 9000 native)

- [ ] **Create ClickHouse Tables**

  - [ ] **market_data_tick** (partitioned by day + symbol)

    - Columns: symbol, timestamp, price, volume, bid, ask, bid_size, ask_size
    - Partition key: toYYYYMMDD(timestamp), symbol
    - Order by: timestamp, symbol
    - TTL: 90 days
    - Compression: LZ4

  - [ ] **market_data_1min** (partitioned by month + symbol)

    - Columns: symbol, timestamp, open, high, low, close, volume
    - Partition key: toYYYYMM(timestamp), symbol
    - TTL: 2 years
    - Compression: ZSTD

  - [ ] **market_data_daily** (partitioned by year + symbol)

    - Columns: symbol, date, open, high, low, close, volume, adj_close
    - Partition key: toYear(date), symbol
    - TTL: 10 years
    - Compression: ZSTD

  - [ ] **audit_log** (partitioned by month)

    - Columns: log_id, timestamp, user_id, action, entity_type, entity_id, details, ip_address
    - Partition key: toYYYYMM(timestamp)
    - TTL: 7 years (regulatory compliance)
    - Compression: LZ4

  - [ ] **performance_metrics** (partitioned by day)
    - Columns: timestamp, service_name, metric_name, value, tags
    - Partition key: toYYYYMMDD(timestamp)
    - TTL: 1 year
    - Compression: LZ4

- [ ] **Configure ClickHouse**

  - [ ] Set max_memory_usage (32GB)
  - [ ] Configure max_threads (CPU cores)
  - [ ] Set compression method (ZSTD for cold data)
  - [ ] Configure distributed_ddl settings
  - [ ] Enable query logging
  - [ ] Set up materialized views for aggregations

- [ ] **Optimize for Time-Series**
  - [ ] Create merge tree optimizations
  - [ ] Configure partitioning strategies
  - [ ] Set up data retention policies
  - [ ] Implement compression levels
  - [ ] Create aggregation tables for common queries

---

### Neo4j 5.25.0 Community

- [ ] **Deploy Neo4j Container**

  - [ ] Pull Neo4j 5.25.0 Community image
  - [ ] Configure docker-compose service
  - [ ] Set environment variables (password, plugins)
  - [ ] Configure volume mounts
  - [ ] Expose ports (7474 HTTP, 7687 Bolt)

- [ ] **Create Graph Data Model**

  - [ ] Node types:

    - [ ] User nodes (properties: user_id, name, experience_level)
    - [ ] Strategy nodes (properties: strategy_id, name, type, performance_score)
    - [ ] Agent nodes (properties: agent_id, name, type, capabilities)
    - [ ] Workflow nodes (properties: workflow_id, name, stages)
    - [ ] Tool nodes (properties: tool_id, name, category, complexity)
    - [ ] Market nodes (properties: symbol, asset_class, exchange)

  - [ ] Relationship types:
    - [ ] (User)-[:CREATED]->(Strategy)
    - [ ] (User)-[:OWNS]->(Portfolio)
    - [ ] (Strategy)-[:USES]->(Tool)
    - [ ] (Strategy)-[:TRADES]->(Market)
    - [ ] (Agent)-[:EXECUTES]->(Workflow)
    - [ ] (Agent)-[:RECOMMENDS]->(Tool)
    - [ ] (Workflow)-[:NEXT_STEP]->(Workflow)
    - [ ] (Strategy)-[:DEPENDS_ON]->(Strategy)

- [ ] **Create Indexes**

  - [ ] Index on User.user_id
  - [ ] Index on Strategy.strategy_id
  - [ ] Index on Agent.agent_id
  - [ ] Index on Market.symbol
  - [ ] Full-text index on Strategy.name

- [ ] **Configure Neo4j**

  - [ ] Set dbms.memory.heap.max_size (8GB)
  - [ ] Configure dbms.memory.pagecache.size (4GB)
  - [ ] Enable query logging
  - [ ] Set up backup schedule
  - [ ] Configure APOC procedures

- [ ] **Load Initial Data**
  - [ ] Create sample users
  - [ ] Create agent workflow graph
  - [ ] Create tool dependency graph
  - [ ] Create market/symbol nodes

---

### Redis 7.4 Alpine

- [ ] **Deploy Redis Container**

  - [ ] Pull Redis 7.4 Alpine image
  - [ ] Configure docker-compose service
  - [ ] Set append-only file (AOF) persistence
  - [ ] Configure volume mounts
  - [ ] Expose port 6379

- [ ] **Configure Redis**

  - [ ] Set maxmemory (8GB)
  - [ ] Configure maxmemory-policy (allkeys-lru)
  - [ ] Enable AOF persistence
  - [ ] Set appendfsync (everysec)
  - [ ] Configure save points for RDB snapshots
  - [ ] Set requirepass for authentication

- [ ] **Define Key Naming Conventions**

  - [ ] `market:realtime:{symbol}` - Latest market data (Hash)
  - [ ] `session:{session_id}` - User session data (String, TTL: 24h)
  - [ ] `cache:indicator:{symbol}:{indicator}:{params}` - Computed indicators (String)
  - [ ] `signal:latest:{strategy_id}` - Latest trading signals (Hash, TTL: 5min)
  - [ ] `ratelimit:{api}:{user_id}` - API rate limiting (String, TTL varies)
  - [ ] `lock:{resource}` - Distributed locks (String)

- [ ] **Set Up TTL Policies**

  - [ ] Real-time market data: 5 seconds
  - [ ] Session data: 24 hours
  - [ ] Indicator cache: 1 minute (intraday) to 1 day (daily)
  - [ ] Signals: 5 minutes
  - [ ] Rate limits: per endpoint configuration

- [ ] **Configure Redis Modules**
  - [ ] Enable RedisJSON (optional)
  - [ ] Enable RedisSearch (optional for full-text search)
  - [ ] Enable RedisTimeSeries (optional for metrics)

---

### Qdrant 1.12.0

- [ ] **Deploy Qdrant Container**

  - [ ] Pull Qdrant 1.12.0 image
  - [ ] Configure docker-compose service
  - [ ] Configure volume mounts
  - [ ] Expose port 6333 (REST API)
  - [ ] Expose port 6334 (gRPC)

- [ ] **Create Vector Collections**

  - [ ] **strategy_embeddings**

    - Vector size: 384 (sentence-transformers/all-MiniLM-L6-v2)
    - Distance metric: Cosine
    - Payload schema:
      - strategy_id (string)
      - name (string)
      - description (string)
      - code (string)
      - parameters (json)
      - created_at (timestamp)
    - Indexing: HNSW (Hierarchical Navigable Small World)
    - Purpose: Strategy discovery, similar strategy recommendations

  - [ ] **document_embeddings**

    - Vector size: 384
    - Distance metric: Cosine
    - Payload schema:
      - document_id (string)
      - title (string)
      - content (string)
      - type (string) - "tutorial", "api_doc", "guide"
      - url (string)
    - Purpose: RAG-based question answering, documentation search

  - [ ] **conversation_embeddings**

    - Vector size: 384
    - Distance metric: Cosine
    - Payload schema:
      - conversation_id (string)
      - user_id (string)
      - query (string)
      - response (string)
      - timestamp (timestamp)
    - Purpose: Context-aware AI responses, conversation history

  - [ ] **market_pattern_embeddings**
    - Vector size: 768 (larger model for complex patterns)
    - Distance metric: Euclidean
    - Payload schema:
      - pattern_id (string)
      - symbol (string)
      - pattern_type (string)
      - timeframe (string)
      - features (json)
    - Purpose: Pattern recognition, similar market conditions

- [ ] **Configure Qdrant**

  - [ ] Set storage path
  - [ ] Configure HNSW parameters (m=16, ef_construct=100)
  - [ ] Enable API key authentication
  - [ ] Set up collection aliases
  - [ ] Configure snapshot schedule

- [ ] **Create Sample Embeddings**
  - [ ] Generate embeddings for strategy templates
  - [ ] Index documentation pages
  - [ ] Create initial conversation context

---

## Event Bus Setup (Apache Kafka)

### Kafka 3.9 (KRaft Mode)

- [ ] **Deploy Kafka Cluster**

  - [ ] Pull Confluent Kafka 7.7.0 image (includes Kafka 3.9)
  - [ ] Configure KRaft mode (no ZooKeeper)
  - [ ] Set up 3-broker cluster (or single broker for development)
  - [ ] Configure broker IDs and listeners
  - [ ] Set up controller quorum
  - [ ] Expose port 9092 (internal), 9093 (external)

- [ ] **Create Kafka Topics**

  **Market Data Topics**:

  - [ ] `marketdata.tick.{exchange}.{symbol}` (16 partitions, 24h retention)
  - [ ] `marketdata.quote.{exchange}.{symbol}` (8 partitions, 24h retention)
  - [ ] `marketdata.trade.{exchange}.{symbol}` (16 partitions, 24h retention)
  - [ ] `marketdata.bar.1m.{exchange}.{symbol}` (8 partitions, 7d retention)
  - [ ] `marketdata.bar.5m.{exchange}.{symbol}` (4 partitions, 7d retention)
  - [ ] `marketdata.bar.1h.{exchange}.{symbol}` (4 partitions, 30d retention)
  - [ ] `marketdata.bar.1d.{exchange}.{symbol}` (4 partitions, 30d retention)
  - [ ] `marketdata.options.chain.{symbol}` (4 partitions, 7d retention)

  **Trading Topics**:

  - [ ] `trading.order.created` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.order.submitted` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.order.filled` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.order.cancelled` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.position.opened` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.position.modified` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.position.closed` (8 partitions, 7d retention, replication=3)
  - [ ] `trading.signal.generated` (8 partitions, 7d retention)

  **Risk Topics**:

  - [ ] `risk.limit.breached` (4 partitions, 30d retention, replication=3)
  - [ ] `risk.var.calculated` (4 partitions, 30d retention)
  - [ ] `risk.alert.triggered` (4 partitions, 30d retention, replication=3)
  - [ ] `risk.circuit_breaker.activated` (4 partitions, 30d retention, replication=3)

  **Fundamental Topics** (NEW):

  - [ ] `fundamental.data.updated` (4 partitions, 90d retention)
  - [ ] `fundamental.statement.published` (4 partitions, 90d retention)
  - [ ] `fundamental.ratio.calculated` (4 partitions, 90d retention)
  - [ ] `fundamental.score.computed` (4 partitions, 90d retention)
  - [ ] `fundamental.valuation.updated` (4 partitions, 90d retention)
  - [ ] `fundamental.earnings.announced` (4 partitions, 90d retention)
  - [ ] `fundamental.insider.transaction` (4 partitions, 90d retention)

  **AI Topics**:

  - [ ] `ai.query.received` (4 partitions, 7d retention)
  - [ ] `ai.agent.processing` (4 partitions, 7d retention)
  - [ ] `ai.agent.completed` (4 partitions, 7d retention)
  - [ ] `ai.guidance.suggested` (4 partitions, 7d retention)

  **System Topics**:

  - [ ] `system.health.service.{service_name}` (2 partitions, 30d retention)
  - [ ] `system.error.{service_name}` (2 partitions, 30d retention)
  - [ ] `system.audit.{action_type}` (2 partitions, 90d retention, replication=3)

- [ ] **Configure Topic Settings**
  - [ ] Set compression type (LZ4 for performance, ZSTD for higher compression)
  - [ ] Configure min.insync.replicas=2 (for critical topics)
  - [ ] Set segment.ms for log rotation
  - [ ] Configure cleanup.policy (delete vs compact)
  - [ ] Set max.message.bytes (1MB default, increase if needed)

### Schema Registry 7.7

- [ ] **Deploy Schema Registry**

  - [ ] Pull Confluent Schema Registry image
  - [ ] Configure docker-compose service
  - [ ] Connect to Kafka cluster
  - [ ] Expose port 8081

- [ ] **Create Event Schemas (Avro)**

  - [ ] **OrderFilledEvent** schema

    ```json
    {
      "namespace": "com.trading.events",
      "type": "record",
      "name": "OrderFilled",
      "fields": [
        { "name": "event_id", "type": "string" },
        { "name": "event_type", "type": "string" },
        { "name": "timestamp", "type": "long" },
        { "name": "order_id", "type": "string" },
        { "name": "symbol", "type": "string" },
        { "name": "quantity", "type": "double" },
        { "name": "fill_price", "type": "double" },
        { "name": "commission", "type": "double" }
      ]
    }
    ```

  - [ ] **MarketDataTick** schema
  - [ ] **TradingSignal** schema
  - [ ] **RiskAlert** schema
  - [ ] **FundamentalDataUpdated** schema (NEW)

- [ ] **Configure Schema Registry**
  - [ ] Set compatibility mode (BACKWARD for evolution)
  - [ ] Enable schema validation
  - [ ] Configure schema caching
  - [ ] Set up schema versioning

---

## GPU Acceleration Setup

- [ ] **Install NVIDIA Container Toolkit**

  - [ ] Verify NVIDIA drivers installed (nvidia-smi)
  - [ ] Install NVIDIA Container Toolkit
  - [ ] Configure Docker to use NVIDIA runtime
  - [ ] Test GPU access in container

- [ ] **Configure GPU Services**

  - [ ] **ML/DL Service**:
    - [ ] Set GPU device allocation (NVIDIA_VISIBLE_DEVICES=0)
    - [ ] Configure memory limits (3GB VRAM)
    - [ ] Test PyTorch CUDA availability
  - [ ] **Backtesting Service**:
    - [ ] Allocate 1GB VRAM
    - [ ] Configure VectorBT GPU backend
  - [ ] **RL Service**:
    - [ ] Allocate 2GB VRAM
    - [ ] Configure FinRL GPU settings

- [ ] **Test GPU Acceleration**
  - [ ] Run PyTorch GPU test
  - [ ] Benchmark LSTM training (CPU vs GPU)
  - [ ] Verify 10-50x speedup achieved

---

## Monitoring Stack Setup

### Prometheus 2.48

- [ ] **Deploy Prometheus**

  - [ ] Pull Prometheus 2.48 image
  - [ ] Configure docker-compose service
  - [ ] Mount configuration file
  - [ ] Mount storage volume
  - [ ] Expose port 9090

- [ ] **Configure Prometheus**

  - [ ] Set scrape interval (15s)
  - [ ] Configure retention (30 days)
  - [ ] Add scrape targets for all 28 services
  - [ ] Configure service discovery
  - [ ] Set up recording rules for common queries

- [ ] **Define Metrics**
  - [ ] Service health metrics
  - [ ] API request metrics (count, latency, errors)
  - [ ] Kafka consumer lag
  - [ ] Database connection pool metrics
  - [ ] Order execution latency
  - [ ] GPU utilization metrics

### Grafana 10.2

- [ ] **Deploy Grafana**

  - [ ] Pull Grafana 10.2 image
  - [ ] Configure docker-compose service
  - [ ] Mount dashboards directory
  - [ ] Expose port 3001

- [ ] **Configure Grafana**

  - [ ] Add Prometheus data source
  - [ ] Add Loki data source (logs)
  - [ ] Add ClickHouse data source (optional)
  - [ ] Set up user authentication

- [ ] **Create Dashboards**
  - [ ] **Trading System Overview**:
    - Orders per minute
    - Order latency (p50, p95, p99)
    - Active strategies count
    - Kafka consumer lag
  - [ ] **Database Performance**:
    - PostgreSQL query time
    - ClickHouse query time
    - Redis hit rate
    - Connection pool utilization
  - [ ] **Service Health**:
    - Service uptime
    - Error rates
    - Request rates
    - Response times
  - [ ] **Business Metrics**:
    - Total trades executed
    - Total P&L
    - Strategy performance
    - Risk limit breaches

### Loki 2.9

- [ ] **Deploy Loki**

  - [ ] Pull Loki 2.9 image
  - [ ] Configure docker-compose service
  - [ ] Mount configuration file
  - [ ] Expose port 3100

- [ ] **Deploy Promtail**

  - [ ] Pull Promtail image
  - [ ] Configure to scrape Docker logs
  - [ ] Add service labels
  - [ ] Configure log parsing

- [ ] **Configure Log Aggregation**
  - [ ] Set retention (14 days)
  - [ ] Configure log levels
  - [ ] Set up log queries in Grafana
  - [ ] Create log-based alerts

---

## Network Configuration

- [ ] **Create Docker Network**

  - [ ] Create `trading_network` bridge network
  - [ ] Configure DNS resolution
  - [ ] Set up network aliases for services

- [ ] **Configure Service Communication**

  - [ ] Internal service-to-service communication
  - [ ] External API exposure (API Gateway only)
  - [ ] Database access restrictions

- [ ] **Set Up Load Balancing** (Optional)
  - [ ] Configure NGINX reverse proxy
  - [ ] Set up health checks
  - [ ] Configure failover

---

## Testing & Verification

- [ ] **Database Connectivity Tests**

  - [ ] Test PostgreSQL connection from services
  - [ ] Test ClickHouse insert and query
  - [ ] Test Neo4j graph queries
  - [ ] Test Redis get/set operations
  - [ ] Test Qdrant vector search

- [ ] **Kafka Tests**

  - [ ] Produce test messages to topics
  - [ ] Consume messages from topics
  - [ ] Test Schema Registry validation
  - [ ] Measure throughput (target: >1M events/sec)

- [ ] **Performance Benchmarks**

  - [ ] PostgreSQL: <10ms query time (p95)
  - [ ] ClickHouse: <100ms for 1B rows
  - [ ] Redis: <1ms reads
  - [ ] Kafka: >1M events/sec throughput

- [ ] **Monitoring Tests**

  - [ ] Verify Prometheus scraping all targets
  - [ ] Verify Grafana dashboards displaying data
  - [ ] Test Loki log aggregation
  - [ ] Verify alerts triggering correctly

- [ ] **GPU Tests** (if applicable)
  - [ ] Verify GPU accessible in ML/DL containers
  - [ ] Benchmark training performance (CPU vs GPU)
  - [ ] Test CUDA memory allocation

---

## Documentation (Create as We Build)

- [ ] **Database Documentation**

  - [ ] PostgreSQL schema documentation
  - [ ] ClickHouse table documentation
  - [ ] Neo4j graph model documentation
  - [ ] Redis key documentation
  - [ ] Qdrant collection documentation

- [ ] **Kafka Documentation**

  - [ ] Topic hierarchy documentation
  - [ ] Event schema documentation
  - [ ] Consumer group documentation

- [ ] **Operations Guide**
  - [ ] Database backup/restore procedures
  - [ ] Kafka topic management
  - [ ] Monitoring dashboard guide
  - [ ] Troubleshooting guide

---

## Deliverables Checklist

**Databases**:

- [ ] PostgreSQL 17 + pgvector deployed and configured
- [ ] ClickHouse 24.8 deployed with all tables
- [ ] Neo4j 5.25.0 deployed with graph model
- [ ] Redis 7.4 deployed with key conventions
- [ ] Qdrant 1.12.0 deployed with collections

**Event Bus**:

- [ ] Apache Kafka 3.9 (KRaft) deployed
- [ ] Schema Registry 7.7 deployed
- [ ] All topics created with correct configuration
- [ ] Event schemas registered

**GPU**:

- [ ] NVIDIA Container Toolkit installed
- [ ] GPU accessible in ML/DL services
- [ ] GPU acceleration verified

**Monitoring**:

- [ ] Prometheus deployed and scraping
- [ ] Grafana deployed with dashboards
- [ ] Loki deployed for log aggregation
- [ ] Alerts configured

**Verification**:

- [ ] All databases accessible and tested
- [ ] Kafka producing/consuming messages
- [ ] Monitoring stack operational
- [ ] Performance benchmarks met

---

## Timeline & Progress

**Week 3** (Days 1-5):

- Days 1-2: Deploy and configure all 5 databases
- Days 3-4: Set up Kafka and Schema Registry
- Day 5: GPU setup and initial testing

**Week 4** (Days 1-5):

- Days 1-2: Deploy monitoring stack (Prometheus, Grafana, Loki)
- Days 3-4: Create dashboards and alerts
- Day 5: Performance testing and verification

**Week 5** (Days 1-2):

- Days 1-2: Final testing, documentation, and Phase 3 completion

**Dependencies**:

- Phase 2 complete ✅
- Docker Desktop installed ✅
- NVIDIA drivers installed (for GPU)

**Blockers**:

- None identified

---

## Success Criteria

- ✅ All 5 databases deployed and accessible
- ✅ Database schemas created and tested
- ✅ Apache Kafka cluster running (>1M events/sec)
- ✅ All Kafka topics created
- ✅ Schema Registry operational
- ✅ GPU acceleration working (optional but recommended)
- ✅ Monitoring stack operational
- ✅ Dashboards created and displaying metrics
- ✅ Performance benchmarks met
- ✅ All infrastructure documented

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-20  
**Status**: Active
