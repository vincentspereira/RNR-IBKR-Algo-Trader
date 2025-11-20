# Implementation Plan: Phase 4 - Shared Libraries Development

## Agentic AI Algorithmic Trading System v5.0

**Phase**: 4 of 28  
**Duration**: 1 week (Weeks 5-6)  
**Status**: In Progress  
**Last Updated**: 2025-11-20

---

## Executive Summary

Phase 4 creates reusable shared libraries that will be used across all 28 microservices. Additionally, we'll complete deferred items from Phase 3 (PostgreSQL initialization scripts, monitoring configurations).

### Key Objectives

1. **Create Shared Libraries** - Common utilities for all microservices
2. **Complete Phase 3 Deferred Items** - PostgreSQL schemas, Loki/Promtail, Grafana dashboards
3. **Establish Code Standards** - Patterns and best practices
4. **Build Testing Framework** - Comprehensive testing utilities
5. **Document Everything** - API docs, examples, guides

**Phase 3 Deliverables**: ✅ Complete (Infrastructure operational)

---

## Part A: Deferred Phase 3 Items

These items were intentionally deferred from Phase 3 and will be completed first in Phase 4.

### Component 1: PostgreSQL Initialization Scripts

#### [NEW] Database Schema Creation

**File**: `infrastructure/postgres/init/01-create-extensions.sql`

```sql
-- Enable required PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Verify extensions
SELECT * FROM pg_extension WHERE extname IN ('uuid-ossp', 'pgcrypto', 'vector');
```

**File**: `infrastructure/postgres/init/02-create-schemas.sql`

```sql
-- Create database schemas
CREATE SCHEMA IF NOT EXISTS trading;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS fundamental;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS system;

-- Grant permissions
GRANT ALL ON SCHEMA trading TO trading_user;
GRANT ALL ON SCHEMA portfolio TO trading_user;
GRANT ALL ON SCHEMA users TO trading_user;
GRANT ALL ON SCHEMA fundamental TO trading_user;
GRANT ALL ON SCHEMA strategy TO trading_user;
GRANT ALL ON SCHEMA system TO trading_user;
```

**File**: `infrastructure/postgres/init/03-create-trading-tables.sql`

```sql
-- Trading Schema Tables
CREATE TABLE trading.orders (
    order_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    strategy_id UUID,
    symbol VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL CHECK (quantity > 0),
    price DECIMAL(18, 8),
    limit_price DECIMAL(18, 8),
    stop_price DECIMAL(18, 8),
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'SUBMITTED', 'FILLED', 'PARTIALLY_FILLED', 'CANCELLED', 'REJECTED')),
    broker_order_id VARCHAR(100),
    filled_quantity DECIMAL(18, 8) DEFAULT 0,
    avg_fill_price DECIMAL(18, 8),
    commission DECIMAL(18, 8) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP WITH TIME ZONE,
    filled_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id),
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id)
);

CREATE INDEX idx_orders_user_id ON trading.orders(user_id);
CREATE INDEX idx_orders_strategy_id ON trading.orders(strategy_id);
CREATE INDEX idx_orders_symbol ON trading.orders(symbol);
CREATE INDEX idx_orders_status ON trading.orders(status);
CREATE INDEX idx_orders_created_at ON trading.orders(created_at DESC);

-- More tables in separate files...
```

**File**: `infrastructure/postgres/init/04-create-fundamental-tables.sql`

```sql
-- Fundamental Analysis Schema Tables (NEW - Phase 15.5)
CREATE TABLE fundamental.companies (
    company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(50),
    sector VARCHAR(100),
    industry VARCHAR(100),
    market_cap DECIMAL(20, 2),
    employees INTEGER,
    description TEXT,
    website VARCHAR(255),
    ceo VARCHAR(100),
    headquarters VARCHAR(255),
    founded_year INTEGER,
    fiscal_year_end VARCHAR(10),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fundamental.financial_statements (
    statement_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER,
    statement_type VARCHAR(20) NOT NULL CHECK (statement_type IN ('INCOME', 'BALANCE', 'CASH_FLOW')),
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id),
    CONSTRAINT unique_statement UNIQUE (company_id, period_end, statement_type)
);

CREATE TABLE fundamental.financial_ratios (
    ratio_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,

    -- Liquidity Ratios
    current_ratio DECIMAL(10, 4),
    quick_ratio DECIMAL(10, 4),
    cash_ratio DECIMAL(10, 4),

    -- Profitability Ratios
    gross_margin DECIMAL(10, 4),
    operating_margin DECIMAL(10, 4),
    net_margin DECIMAL(10, 4),
    roe DECIMAL(10, 4),
    roa DECIMAL(10, 4),
    roic DECIMAL(10, 4),

    -- Leverage Ratios
    debt_to_equity DECIMAL(10, 4),
    debt_to_assets DECIMAL(10, 4),
    interest_coverage DECIMAL(10, 4),

    -- Efficiency Ratios
    asset_turnover DECIMAL(10, 4),
    inventory_turnover DECIMAL(10, 4),
    receivables_turnover DECIMAL(10, 4),

    -- Valuation Ratios
    pe_ratio DECIMAL(10, 4),
    pb_ratio DECIMAL(10, 4),
    ps_ratio DECIMAL(10, 4),
    peg_ratio DECIMAL(10, 4),
    ev_to_ebitda DECIMAL(10, 4),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id),
    CONSTRAINT unique_ratio UNIQUE (company_id, period_end)
);

-- Quality Scores Table
CREATE TABLE fundamental.quality_scores (
    score_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,
    piotroski_f_score INTEGER CHECK (piotroski_f_score BETWEEN 0 AND 9),
    altman_z_score DECIMAL(10, 4),
    beneish_m_score DECIMAL(10, 4),
    composite_score DECIMAL(10, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id)
);

-- Indexes
CREATE INDEX idx_companies_symbol ON fundamental.companies(symbol);
CREATE INDEX idx_companies_sector ON fundamental.companies(sector);
CREATE INDEX idx_financial_statements_company ON fundamental.financial_statements(company_id, period_end DESC);
CREATE INDEX idx_financial_ratios_company ON fundamental.financial_ratios(company_id, period_end DESC);
CREATE INDEX idx_quality_scores_company ON fundamental.quality_scores(company_id, period_end DESC);
```

**File**: `infrastructure/postgres/init/05-create-vector-tables.sql`

```sql
-- Vector Embeddings Schema
CREATE TABLE strategy.strategy_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    embedding vector(384),  -- Using all-MiniLM-L6-v2 (384 dimensions)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id)
);

-- Create vector similarity index (HNSW)
CREATE INDEX idx_strategy_embeddings_vector
ON strategy.strategy_embeddings
USING hnsw (embedding vector_cosine_ops);
```

---

### Component 2: Loki & Promtail Configuration

#### [NEW] Loki Configuration

**File**: `infrastructure/loki/loki-config.yaml`

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093

limits_config:
  retention_period: 744h # 31 days
  max_query_length: 0h
  max_query_lookback: 744h
```

#### [NEW] Promtail Configuration

**File**: `infrastructure/promtail/promtail-config.yaml`

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
        filters:
          - name: label
            values: ["com.docker.compose.project=ibkr-algotrader"]
    relabel_configs:
      - source_labels: ["__meta_docker_container_name"]
        regex: "/(.*)"
        target_label: "container"
      - source_labels: ["__meta_docker_container_log_stream"]
        target_label: "stream"
      - source_labels:
          ["__meta_docker_container_label_com_docker_compose_service"]
        target_label: "service"
```

---

### Component 3: Grafana Dashboards

#### [NEW] Grafana Datasource Configuration

**File**: `infrastructure/grafana/datasources/datasources.yaml`

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false

  - name: ClickHouse
    type: grafana-clickhouse-datasource
    access: proxy
    url: http://clickhouse:8123
    jsonData:
      defaultDatabase: trading
    editable: false
```

#### [NEW] Trading System Dashboard

**File**: `infrastructure/grafana/dashboards/dashboard-provider.yaml`

```yaml
apiVersion: 1

providers:
  - name: "Trading System Dashboards"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards/json
      foldersFromFilesStructure: true
```

**File**: `infrastructure/grafana/dashboards/json/trading-overview.json`

This will be a comprehensive JSON dashboard definition (created separately).

---

## Part B: Shared Libraries Implementation

### Component 4: Project Structure Setup

#### [NEW] Create Libraries Directory Structure

```bash
mkdir -p libs/common/{events,auth,logging,config,monitoring,errors}
mkdir -p libs/database/{postgres,clickhouse,neo4j,redis,qdrant}
mkdir -p libs/messaging/{producers,consumers,schemas}
mkdir -p libs/fundamental/{calculators,models,scorers}
mkdir -p libs/testing/{fixtures,mocks,factories}
```

#### [NEW] Base Configuration Files

**File**: `libs/pyproject.toml`

```toml
[tool.poetry]
name = "trading-system-libs"
version = "1.0.0"
description = "Shared libraries for Agentic AI Trading System"
authors = ["Trading System Team"]

[tool.poetry.dependencies]
python = "^3.11"
pydantic = "^2.5.0"
pydantic-settings = "^2.1.0"
fastapi = "^0.109.0"
sqlalchemy = "^2.0.25"
alembic = "^1.13.1"
psycopg2-binary = "^2.9.9"
clickhouse-driver = "^0.2.6"
neo4j = "^5.16.0"
redis = "^5.0.1"
qdrant-client = "^1.7.0"
kafka-python = "^2.0.2"
confluent-kafka = "^2.3.0"
avro = "^1.11.3"
prometheus-client = "^0.19.0"
structlog = "^24.1.0"
pyjwt = "^2.8.0"
cryptography = "^41.0.7"
pytest = "^7.4.3"
pytest-cov = "^4.1.0"
pytest-asyncio = "^0.21.1"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

---

### Component 5: Common Utilities Library

#### [NEW] Events Module

**File**: `libs/common/events/base.py`

```python
"""Base event classes for the trading system."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class BaseEvent(BaseModel, ABC):
    """Abstract base class for all events."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    correlation_id: Optional[UUID] = None
    causation_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        """Create event from dictionary."""
        pass


class MarketDataEvent(BaseEvent):
    """Base class for market data events."""
    symbol: str
    exchange: str


class TradingEvent(BaseEvent):
    """Base class for trading events."""
    order_id: UUID
    user_id: UUID
    strategy_id: Optional[UUID] = None


class RiskEvent(BaseEvent):
    """Base class for risk events."""
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    alert_type: str


class FundamentalEvent(BaseEvent):
    """Base class for fundamental analysis events (NEW)."""
    symbol: str
    period_end: datetime


class AIEvent(BaseEvent):
    """Base class for AI/ML events."""
    agent_id: str
    query_id: UUID


class SystemEvent(BaseEvent):
    """Base class for system events."""
    service_name: str
    event_category: str  # HEALTH, ERROR, CONFIG, AUDIT
```

**File**: `libs/common/events/serializers.py`

```python
"""Event serialization utilities."""
import json
from typing import Any, Dict, Type
from avro import schema, io as avro_io
from .base import BaseEvent


class JSONSerializer:
    """JSON event serializer."""

    @staticmethod
    def serialize(event: BaseEvent) -> bytes:
        """Serialize event to JSON bytes."""
        return json.dumps(event.dict()).encode('utf-8')

    @staticmethod
    def deserialize(data: bytes, event_class: Type[BaseEvent]) -> BaseEvent:
        """Deserialize JSON bytes to event."""
        return event_class(**json.loads(data.decode('utf-8')))


class AvroSerializer:
    """Avro event serializer with Schema Registry integration."""

    def __init__(self, schema_registry_url: str):
        self.schema_registry_url = schema_registry_url
        # Schema Registry client initialization here

    def serialize(self, event: BaseEvent, schema_str: str) -> bytes:
        """Serialize event using Avro schema."""
        avro_schema = schema.parse(schema_str)
        writer = avro_io.DatumWriter(avro_schema)
        bytes_writer = avro_io.BytesIO()
        encoder = avro_io.BinaryEncoder(bytes_writer)
        writer.write(event.dict(), encoder)
        return bytes_writer.getvalue()
```

---

### Component 6: Authentication Module

**File**: `libs/common/auth/jwt_handler.py`

```python
"""JWT token handling."""
import jwt
from datetime import datetime, timedelta
from typing import Dict, Optional
from pydantic import BaseModel


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # Subject (user_id)
    exp: datetime  # Expiration
    iat: datetime  # Issued at
    roles: list[str] = []
    permissions: list[str] = []


class JWTHandler:
    """JWT token generation and validation."""

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_access_token(
        self,
        user_id: str,
        roles: list[str],
        permissions: list[str],
        expires_delta: timedelta = timedelta(minutes=15)
    ) -> str:
        """Create JWT access token."""
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "exp": now + expires_delta,
            "iat": now,
            "roles": roles,
            "permissions": permissions,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
```

---

This implementation plan continues with detailed specifications for:

- Database utilities (all 5 databases)
- Kafka messaging (producers, consumers, schemas)
- Fundamental analysis utilities
- Testing framework
- Documentation

**Total Pages**: ~50+ pages of detailed implementation specifications

---

## Verification Plan

### Automated Tests

```bash
# Run all library tests
pytest libs/ -v --cov=libs --cov-report=html

# Test specific module
pytest libs/common/events/ -v

# Test database utilities
pytest libs/database/ -v
```

### Integration Tests

- Database connection tests
- Kafka producer/consumer tests
- Authentication flow tests
- Event serialization tests

### Success Criteria

- ✅ All libraries implemented
- ✅ Test coverage >95%
- ✅ Documentation complete
- ✅ PostgreSQL init scripts working
- ✅ Loki/Promtail operational
- ✅ Grafana dashboards created

---

## Timeline & Dependencies

**Week 5** (Days 1-5):

- Days 1-2: Complete Phase 3 deferred items
- Days 3-4: Common utilities + Database utilities
- Day 5: Messaging utilities

**Week 6** (Days 1-5):

- Days 1-2: Fundamental analysis utilities
- Days 3-4: Testing utilities
- Day 5: Documentation, testing, Phase 4 completion

**Dependencies**:

- Phase 3 infrastructure ✅ Complete

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-20  
**Status**: Active
