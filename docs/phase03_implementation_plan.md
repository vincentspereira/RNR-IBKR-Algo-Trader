# Implementation Plan: Phase 3 - Infrastructure & Database Setup

## Agentic AI Algorithmic Trading System v5.0

**Phase**: 3 of 28  
**Duration**: 2 weeks (Weeks 3-5)  
**Status**: In Progress  
**Last Updated**: 2025-11-20

---

## Executive Summary

Phase 3 establishes the complete infrastructure foundation for the trading system. This includes deploying and configuring all 5 databases (polyglot persistence), Apache Kafka event bus, GPU acceleration for ML/DL workloads, and a comprehensive monitoring stack.

### Key Objectives

1. **Deploy 5 Databases** - PostgreSQL, ClickHouse, Neo4j, Redis, Qdrant
2. **Configure Event Bus** - Apache Kafka 3.9 (KRaft mode) + Schema Registry
3. **Set Up GPU Acceleration** - NVIDIA Container Toolkit for ML/DL services
4. **Implement Monitoring** - Prometheus, Grafana, Loki for observability
5. **Performance Verification** - Ensure all benchmarks met

**Phase 2 Deliverables**: ✅ Complete

- README.md (comprehensive, badges fixed)
- 2 OpenAPI specs (Trading Engine, Fundamental Analysis)
- Getting Started guide

---

## Proposed Changes

### Component 1: Docker Compose Infrastructure

#### [MODIFY] docker-compose.yml

**Current State**: Partial configuration  
**Target State**: Complete production-ready infrastructure

**Changes**:

```yaml
version: "3.9"

networks:
  trading_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16

volumes:
  postgres_data:
  clickhouse_data:
  neo4j_data:
  redis_data:
  qdrant_data:
  kafka_data:
  prometheus_data:
  grafana_data:

services:
  # ==================== DATABASES ====================

  postgres:
    image: pgvector/pgvector:pg17
    container_name: trading-postgres
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trading_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_INITDB_ARGS: "-E UTF8"
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infrastructure/postgres/init:/docker-entrypoint-initdb.d
    networks:
      - trading_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trading_user -d trading"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G

  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    container_name: trading-clickhouse
    environment:
      CLICKHOUSE_DB: trading
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}
    ports:
      - "8123:8123" # HTTP
      - "9000:9000" # Native
    volumes:
      - clickhouse_data:/var/lib/clickhouse
      - ./infrastructure/clickhouse/config:/etc/clickhouse-server/config.d
      - ./infrastructure/clickhouse/init:/docker-entrypoint-initdb.d
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "clickhouse-client", "--query", "SELECT 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G

  neo4j:
    image: neo4j:5.25.0-community
    container_name: trading-neo4j
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_memory_heap_max__size: 8G
      NEO4J_dbms_memory_pagecache_size: 4G
    ports:
      - "7474:7474" # HTTP
      - "7687:7687" # Bolt
    volumes:
      - neo4j_data:/data
      - ./infrastructure/neo4j/init:/import
    networks:
      - trading_network
    healthcheck:
      test:
        ["CMD-SHELL", "cypher-shell -u neo4j -p ${NEO4J_PASSWORD} 'RETURN 1'"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 12G
        reservations:
          memory: 8G

  redis:
    image: redis:7.4-alpine
    container_name: trading-redis
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --maxmemory 8gb
      --maxmemory-policy allkeys-lru
      --appendonly yes
      --appendfsync everysec
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G

  qdrant:
    image: qdrant/qdrant:v1.12.0
    container_name: trading-qdrant
    ports:
      - "6333:6333" # REST API
      - "6334:6334" # gRPC
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY}
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

  # ==================== EVENT BUS ====================

  kafka:
    image: confluentinc/cp-kafka:7.7.0
    container_name: trading-kafka
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_LOG_DIRS: /var/lib/kafka/data
      CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qk # Random but fixed for KRaft
    ports:
      - "9092:9092"
    volumes:
      - kafka_data:/var/lib/kafka/data
    networks:
      - trading_network
    healthcheck:
      test:
        [
          "CMD",
          "kafka-broker-api-versions",
          "--bootstrap-server",
          "localhost:9092",
        ]
      interval: 10s
      timeout: 10s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

  schema-registry:
    image: confluentinc/cp-schema-registry:7.7.0
    container_name: trading-schema-registry
    depends_on:
      - kafka
    environment:
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_LISTENERS: http://0.0.0.0:8081
    ports:
      - "8081:8081"
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ==================== MONITORING ====================

  prometheus:
    image: prom/prometheus:v2.48.1
    container_name: trading-prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"
    ports:
      - "9090:9090"
    volumes:
      - ./infrastructure/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    networks:
      - trading_network
    healthcheck:
      test:
        [
          "CMD",
          "wget",
          "--quiet",
          "--tries=1",
          "--spider",
          "http://localhost:9090/-/healthy",
        ]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 2G

  grafana:
    image: grafana/grafana:10.2.3
    container_name: trading-grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
    ports:
      - "3001:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./infrastructure/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./infrastructure/grafana/datasources:/etc/grafana/provisioning/datasources
    networks:
      - trading_network
    depends_on:
      - prometheus
    healthcheck:
      test:
        [
          "CMD",
          "wget",
          "--quiet",
          "--tries=1",
          "--spider",
          "http://localhost:3000/api/health",
        ]
      interval: 10s
      timeout: 5s
      retries: 5

  loki:
    image: grafana/loki:2.9.3
    container_name: trading-loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - ./infrastructure/loki/loki-config.yaml:/etc/loki/local-config.yaml
    networks:
      - trading_network

  promtail:
    image: grafana/promtail:2.9.3
    container_name: trading-promtail
    volumes:
      - /var/log:/var/log
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./infrastructure/promtail/promtail-config.yaml:/etc/promtail/config.yml
    command: -config.file=/etc/promtail/config.yml
    networks:
      - trading_network
    depends_on:
      - loki

  # ==================== AUTHENTICATION ====================

  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    container_name: trading-keycloak
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD}
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: trading_user
      KC_DB_PASSWORD: ${POSTGRES_PASSWORD}
    command: start-dev
    ports:
      - "8080:8080"
    networks:
      - trading_network
    depends_on:
      - postgres
```

**Key Improvements**:

1. All 5 databases configured with proper health checks
2. Kafka in KRaft mode (no ZooKeeper dependency)
3. Schema Registry for event validation
4. Complete monitoring stack (Prometheus, Grafana, Loki)
5. Resource limits for stability
6. Persistent volumes for data
7. Dedicated network for isolation

---

### Component 2: Database Initialization Scripts

#### [NEW] PostgreSQL Initialization

**File**: `infrastructure/postgres/init/01-create-schemas.sql`

```sql
-- Trading Schema
CREATE SCHEMA IF NOT EXISTS trading;

CREATE TABLE trading.orders (
    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    strategy_id UUID,
    symbol VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL,  -- MARKET, LIMIT, STOP, etc.
    side VARCHAR(4) NOT NULL,  -- BUY, SELL
    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8),
    status VARCHAR(20) NOT NULL,  -- PENDING, SUBMITTED, FILLED, CANCELLED, REJECTED
    broker_order_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP WITH TIME ZONE,
    filled_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT check_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX idx_orders_user_id ON trading.orders(user_id);
CREATE INDEX idx_orders_strategy_id ON trading.orders(strategy_id);
CREATE INDEX idx_orders_symbol ON trading.orders(symbol);
CREATE INDEX idx_orders_status ON trading.orders(status);
CREATE INDEX idx_orders_created_at ON trading.orders(created_at DESC);

-- More tables defined in detailed SQL script...
```

#### [NEW] ClickHouse Initialization

**File**: `infrastructure/clickhouse/init/01-create-tables.sql`

```sql
-- Market Data Tick Table
CREATE TABLE IF NOT EXISTS market_data_tick (
    symbol LowCardinality(String),
    timestamp DateTime64(6, 'UTC'),
    price Decimal(18, 8),
    volume UInt64,
    bid Decimal(18, 8),
    ask Decimal(18, 8),
    bid_size UInt32,
    ask_size UInt32,
    exchange LowCardinality(String),
    INDEX idx_symbol symbol TYPE minmax GRANULARITY 4,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 8192
)
ENGINE = MergeTree()
PARTITION BY (toYYYYMMDD(timestamp), symbol)
ORDER BY (timestamp, symbol)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192, compress_marks = 1, compress_primary_key = 1;

-- More tables defined in detailed SQL script...
```

---

### Component 3: Kafka Topic Creation Script

#### [NEW] Kafka Topic Initialization

**File**: `infrastructure/kafka/create-topics.sh`

```bash
#!/bin/bash

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
kafka-broker-api-versions --bootstrap-server localhost:9092

# Create Market Data Topics
kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic marketdata.tick.NYSE.AAPL --partitions 16 --replication-factor 1 --config retention.ms=86400000
kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic marketdata.bar.1m.NYSE.AAPL --partitions 8 --replication-factor 1 --config retention.ms=604800000

# Create Trading Topics
kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic trading.order.created --partitions 8 --replication-factor 1 --config retention.ms=604800000 --config min.insync.replicas=1

# More topics created in detailed script...

echo "All Kafka topics created successfully!"
```

---

### Component 4: Monitoring Configuration

#### [NEW] Prometheus Configuration

**File**: `infrastructure/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
      labels:
        database: 'trading'

  - job_name: 'clickhouse'
    static_configs:
      - targets: ['clickhouse:9363']

  - job_name: 'kafka'
    static_configs:
      - targets: ['kafka:9092']

  # Service endpoints will be added as services are implemented
  - job_name: 'trading-engine'
    static_configs:
      - targets: ['trading-engine:8001']
```

#### [NEW] Grafana Dashboards

**File**: `infrastructure/grafana/dashboards/trading-overview.json`

Dashboards will be created with:

- Trading system overview
- Database performance
- Service health
- Business metrics

---

## Verification Plan

### Automated Tests

```bash
# Test database connectivity
docker-compose exec postgres psql -U trading_user -d trading -c "SELECT 1;"
docker-compose exec clickhouse clickhouse-client --query "SELECT 1"
docker-compose exec neo4j cypher-shell -u neo4j -p password "RETURN 1"
docker-compose exec redis redis-cli -a password ping

# Test Kafka
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Test monitoring
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3001/api/health  # Grafana
```

### Performance Benchmarks

- PostgreSQL: <10ms query time (p95)
- ClickHouse: <100ms for 1B row queries
- Redis: <1ms reads
- Kafka: >1M events/sec throughput

### Success Criteria

- ✅ All 5 databases running and accessible
- ✅ Database schemas created
- ✅ Kafka topics created
- ✅ Monitoring stack operational
- ✅ All health checks passing
- ✅ Performance benchmarks met

---

## Timeline & Dependencies

**Week 3** (Days 1-5):

- Days 1-2: Update docker-compose.yml, deploy all databases
- Days 3-4: Create database schemas, Kafka setup
- Day 5: Initial testing

**Week 4** (Days 1-5):

- Days 1-2: Monitoring stack setup
- Days 3-4: Dashboards creation
- Day 5: Performance testing

**Week 5** (Days 1-2):

- Days 1-2: Final verification, documentation

**Dependencies**:

- Docker Desktop running ✅
- Phase 2 complete ✅

---

## Next Steps

After Phase 3:

1. **Phase 4: Shared Libraries Development** (Weeks 5-6)
2. Begin implementing common utilities
3. Create event schemas
4. Build authentication helpers

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-20  
**Status**: Active
