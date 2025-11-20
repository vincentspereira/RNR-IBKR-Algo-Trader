# Architecture Diagrams

## Phase 1: Agentic AI Algorithmic Trading System v5.0

**Document Version**: 1.0  
**Last Updated**: 2025-11-20  
**Status**: Active

---

## Table of Contents

1. [High-Level System Architecture](#1-high-level-system-architecture)
2. [Microservices Architecture](#2-microservices-architecture)
3. [Data Flow Architecture](#3-data-flow-architecture)
4. [Event-Driven Architecture](#4-event-driven-architecture)
5. [Database Architecture](#5-database-architecture)
6. [Network Topology](#6-network-topology)
7. [Deployment Architecture](#7-deployment-architecture)
8. [Security Architecture](#8-security-architecture)
9. [AI/ML Pipeline Architecture](#9-aiml-pipeline-architecture)
10. [Fundamental Analysis System Architecture](#10-fundamental-analysis-system-architecture)

---

## 1. High-Level System Architecture

### Overview

The system is designed as a cloud-native, microservices-based trading platform with event-driven architecture.

```mermaid
graph TB
    subgraph "User Layer"
        WEB[Web App<br/>Next.js + React]
        MOBILE[Mobile App<br/>React Native]
        API_CLIENT[API Clients<br/>Python/REST]
    end

    subgraph "API Gateway Layer"
        API_GW[API Gateway<br/>FastAPI<br/>REST + WebSocket]
    end

    subgraph "Core Trading Services"
        TRADING[Trading Engine<br/>NautilusTrader]
        MARKET_DATA[Market Data<br/>Multi-source]
        RISK[Risk Manager<br/>VaR + Limits]
        PORTFOLIO[Portfolio Manager<br/>Optimization]
        OMS[Order Management<br/>IBKR Integration]
    end

    subgraph "Analysis Services"
        FA[Fundamental Analysis<br/>50+ Ratios]
        SCANNER[Market Scanner<br/>Screening]
        OPTIONS[Options Service<br/>QuantLib]
        ML[ML/DL Service<br/>FinRL + LSTM]
    end

    subgraph "AI Services"
        AI_ASSISTANT[AI Assistant<br/>LangGraph]
        GUIDANCE[Guidance Service<br/>Recommendations]
        CHARTING[Charting Service<br/>TradingView Charts]
    end

    subgraph "Event Bus"
        KAFKA[Apache Kafka 3.9<br/>Event Streaming]
    end

    subgraph "Data Layer"
        POSTGRES[(PostgreSQL 17<br/>Transactional)]
        CLICKHOUSE[(ClickHouse 24.8<br/>Time-Series)]
        NEO4J[(Neo4j 5.25<br/>Knowledge Graph)]
        REDIS[(Redis 7.4<br/>Cache)]
        QDRANT[(Qdrant 1.12<br/>Vector DB)]
    end

    subgraph "Infrastructure"
        MONITORING[Prometheus +<br/>Grafana]
        LOGGING[Loki]
        AUTH[Keycloak<br/>OAuth2]
    end

    WEB --> API_GW
    MOBILE --> API_GW
    API_CLIENT --> API_GW

    API_GW --> TRADING
    API_GW --> MARKET_DATA
    API_GW --> FA
    API_GW --> AI_ASSISTANT

    TRADING --> KAFKA
    MARKET_DATA --> KAFKA
    RISK --> KAFKA
    FA --> KAFKA

    KAFKA --> POSTGRES
    KAFKA --> CLICKHOUSE

    TRADING --> POSTGRES
    FA --> POSTGRES
    MARKET_DATA --> CLICKHOUSE
    AI_ASSISTANT --> NEO4J
    API_GW --> REDIS
    AI_ASSISTANT --> QDRANT

    API_GW --> AUTH
    TRADING --> MONITORING
    MARKET_DATA --> MONITORING
```

### Technology Summary

| Layer              | Technology                                   | Purpose                    |
| ------------------ | -------------------------------------------- | -------------------------- |
| **Frontend**       | Next.js 14, React 18, TypeScript             | Web UI                     |
| **API Gateway**    | FastAPI, WebSocket API is                    | REST + Real-time API       |
| **Trading Engine** | NautilusTrader 1.195+                        | High-performance execution |
| **Event Bus**      | Apache Kafka 3.9 (KRaft)                     | Event streaming            |
| **Databases**      | PostgreSQL, ClickHouse, Neo4j, Redis, Qdrant | Polyglot persistence       |
| **AI Framework**   | LangGraph, LangChain, PyTorch                | Multi-agent AI             |
| **Monitoring**     | Prometheus, Grafana, Loki                    | Observability              |

---

## 2. Microservices Architecture

### All 28 Microservices

```mermaid
graph TB
    subgraph "Core Trading Domain - 6 Services"
        S1[1. Trading Engine<br/>Strategy Execution]
        S2[2. Market Data<br/>Data Aggregation]
        S3[3. Risk Manager<br/>Risk Monitoring]
        S4[4. Portfolio Manager<br/>Optimization]
        S5[5. Order Management<br/>Order Lifecycle]
        S6[6. Backtesting Engine<br/>Strategy Testing]
    end

    subgraph "Analysis Domain - 4 Services"
        S7[7. Fundamental Analysis<br/>Ratios + Valuations]
        S8[8. Market Scanner<br/>Stock Screening]
        S9[9. Options Service<br/>Options Analytics]
        S10[10. ML/DL Strategy<br/>Machine Learning]
    end

    subgraph "AI  UX Domain - 5 Services"
        S11[11. AI Assistant<br/>Multi-Agent Orchestration]
        S12[12. Guidance Service<br/>User Recommendations]
        S13[13. Charting Service<br/>TradingView Charts]
        S14[14. Journal Service<br/>Trade Logging]
        S15[15. Educational Content<br/>Tutorials]
    end

    subgraph "Infrastructure Domain - 9 Services"
        S16[16. API Gateway<br/>Request Routing]
        S17[17. Data Pipeline<br/>ETL Workflows]
        S18[18. Event Processing<br/>Event Routing]
        S19[19. Authentication<br/>Keycloak Integration]
        S20[20. Notification<br/>Multi-Channel Alerts]
        S21[21. Analytics<br/>Business Intelligence]
        S22[22. Reporting<br/>Report Generation]
        S23[23. Configuration<br/>Settings Management]
        S24[24. Monitoring<br/>Health Checks]
    end

    subgraph "Compliance Domain - 4 Services"
        S25[25. Compliance<br/>Regulatory Checks]
        S26[26. Audit<br/>Immutable Logging]
        S27[27. Strategy Versioning<br/>Git-based Versioning]
        S28[28. Backup  Recovery<br/>Data Protection]
    end

    style S7 fill:#90EE90
    style S1 fill:#87CEEB
    style S11 fill:#FFB6C1
```

Legend:

- 🟦 Blue: Core Trading Services
- 🟩 Green: Analysis Services (includes Fundamental Analysis - NEW)
- 🟥 Pink: AI & UX Services
- ⬜ Gray: Infrastructure & Compliance

### Service Communication Patterns

```mermaid
sequenceDiagram
    participant User
    participant API_GW as API Gateway
    participant Trading as Trading Engine
    participant Market as Market Data
    participant Risk as Risk Manager
    participant Kafka
    participant DB as PostgreSQL

    Note over User,DB: Order Creation Flow

    User->>API_GW: POST /api/v1/orders
    API_GW->>Trading: Create order
    Trading->>Risk: Pre-trade risk check
    Risk-->>Trading: Risk approved
    Trading->>DB: Save order
    Trading->>Kafka: Publish trading.order.created
    Trading-->>API_GW: Order created
    API_GW-->>User: 201 Created

    Note over User,DB: Market Data Flow

    Market->>Kafka: Publish marketdata.tick.AAPL
    Kafka->>Trading: Consume tick event
    Trading->>Trading: Process signal
    Trading->>KB: Publish trading.signal.generated
```

---

## 3. Data Flow Architecture

### Real-Time Market Data Flow

```mermaid
flowchart LR
    subgraph "Data Sources"
        YAHOO[Yahoo Finance<br/>Primary]
        ALPHA[Alpha Vantage<br/>Fallback]
        FINNHUB[Finnhub<br/>Fallback]
    end

    subgraph "Market Data Service"
        AGGREGATOR[Data Aggregator]
        NORMALIZER[Data Normalizer]
        VALIDATOR[Quality Validator]
    end

    subgraph "Kafka Topics"
        TICK[marketdata.tick.*]
        BAR_1M[marketdata.bar.1m.*]
        BAR_1D[marketdata.bar.1d.*]
    end

    subgraph "Consumers"
        TRADING[Trading Engine<br/>Real-time signals]
        CLICKHOUSE[ClickHouse<br/>Historical storage]
        CHARTING[Charting Service<br/>UI display]
        FA_SERVICE[Fundamental Analysis<br/>Price-based ratios]
    end

    YAHOO --> AGGREGATOR
    ALPHA --> AGGREGATOR
    FINNHUB --> AGGREGATOR

    AGGREGATOR --> NORMALIZER
    NORMALIZER --> VALIDATOR

    VALIDATOR --> TICK
    VALIDATOR --> BAR_1M
    VALIDATOR --> BAR_1D

    TICK --> TRADING
    BAR_1M --> CLICKHOUSE
    BAR_1D --> CHARTING
    BAR_1D --> FA_SERVICE
```

### Order Execution Data Flow

```mermaid
flowchart TB
    START[User Creates Order] --> VALIDATE[Validate Order]
    VALIDATE --> PRE_RISK[Pre-Trade Risk Check]
    PRE_RISK -->|Approved| SUBMIT[Submit to Broker]
    PRE_RISK -->|Rejected| REJECT[Reject Order]

    SUBMIT --> BROKER{Broker<br/>IBKR TWS}
    BROKER -->|Filled| FILL[Process Fill]
    BROKER -->|Partial| PARTIAL[Process Partial Fill]
    BROKER -->|Rejected| BROKER_REJECT[Handle Rejection]

    FILL --> POST_RISK[Post-Trade Risk Update]
    PARTIAL --> POST_RISK

    POST_RISK --> UPDATE_PORTFOLIO[Update Portfolio]
    UPDATE_PORTFOLIO --> NOTIFY[Notify User]
    UPDATE_PORTFOLIO --> AUDIT[Audit Log]

    REJECT --> AUDIT
    BROKER_REJECT --> AUDIT
```

---

## 4. Event-Driven Architecture

### Kafka Topic Hierarchy

```mermaid
graph TB
    subgraph "Market Data Topics"
        MD1[marketdata.tick.*]
        MD2[marketdata.quote.*]
        MD3[marketdata.trade.*]
        MD4[marketdata.bar.1m.*]
        MD5[marketdata.bar.5m.*]
        MD6[marketdata.bar.1d.*]
        MD7[marketdata.options.chain.*]
    end

    subgraph "Trading Topics"
        T1[trading.order.created]
        T2[trading.order.filled]
        T3[trading.order.cancelled]
        T4[trading.position.opened]
        T5[trading.position.closed]
        T6[trading.signal.generated]
    end

    subgraph "Risk Topics"
        R1[risk.limit.breached]
        R2[risk.var.calculated]
        R3[risk.circuit_breaker.activated]
    end

    subgraph "Fundamental Topics - NEW"
        F1[fundamental.data.updated]
        F2[fundamental.ratio.calculated]
        F3[fundamental.score.computed]
        F4[fundamental.earnings.announced]
        F5[fundamental.insider.transaction]
    end

    subgraph "AI Topics"
        A1[ai.query.received]
        A2[ai.agent.processing]
        A3[ai.guidance.suggested]
        A4[ai.strategy.generated]
    end

    subgraph "System Topics"
        S1[system.healthsubject]
        S2[system.error.*]
        S3[system.audit.*]
    end
```

### Event Flow Pattern

```mermaid
sequenceDiagram
    participant Producer
    participant Kafka
    participant Schema_Registry
    participant Consumer1
    participant Consumer2
    participant DLQ as Dead Letter Queue

    Note over Producer,DLQ: Event Publishing & Consumption

    Producer->>Schema_Registry: Validate schema
    Schema_Registry-->>Producer: Schema valid
    Producer->>Kafka: Publish event

    Kafka->>Consumer1: Deliver event
    Kafka->>Consumer2: Deliver event

    Consumer1->>Consumer1: Process successfully
    Consumer1->>Kafka: Commit offset

    Consumer2->>Consumer2: Processing failed
    Consumer2->>DLQ: Send to DLQ
    Consumer2->>Kafka: Commit offset (poison pill handled)
```

---

## 5. Database Architecture

### Polyglot Persistence Strategy

```mermaid
graph TB
    subgraph "Application Services"
        APP[28 Microservices]
    end

    subgraph "Database 1: PostgreSQL 17 + pgvector"
        PG_TRADING[Trading Schema<br/>orders, trades, positions]
        PG_PORTFOLIO[Portfolio Schema<br/>holdings, performance]
        PG_USER[User Schema<br/>users, roles, sessions]
        PG_FUNDAMENTAL[Fundamental Schema<br/>statements, ratios, scores]
        PG_VECTOR[Vector Embeddings<br/>pgvector extension]
    end

    subgraph "Database 2: ClickHouse 24.8"
        CH_TICK[market_data_tick<br/>90 days retention]
        CH_1MIN[market_data_1min<br/>2 years retention]
        CH_DAILY[market_data_daily<br/>10 years retention]
        CH_AUDIT[audit_log<br/>7 years retention]
    end

    subgraph "Database 3: Neo4j 5.25.0"
        NEO_STRATEGY[Strategy Nodes]
        NEO_AGENT[Agent Nodes]
        NEO_WORKFLOW[Workflow Relationships]
    end

    subgraph "Database 4: Redis 7.4"
        REDIS_MARKET[Real-time Market Cache<br/>5s TTL]
        REDIS_SESSION[User Sessions<br/>24h TTL]
        REDIS_INDICATORS[Indicator Cache<br/>1min-1day TTL]
    end

    subgraph "Database 5: Qdrant 1.12.0"
        QDRANT_STRATEGY[Strategy Embeddings]
        QDRANT_DOCS[Document Embeddings]
        QDRANT_CONVERSATION[Conversation Embeddings]
    end

    APP --> PG_TRADING
    APP --> PG_FUNDAMENTAL
    APP --> CH_TICK
    APP --> NEO_STRATEGY
    APP --> REDIS_MARKET
    APP --> QDRANT_STRATEGY
```

### Data Synchronization

```mermaid
sequenceDiagram
    participant PostgreSQL
    participant Kafka
    participant ClickHouse
    participant Redis
    participant Qdrant

    Note over PostgreSQL,Qdrant: Change Data Capture (CDC)

    PostgreSQL->>Kafka: CDC: Order inserted
    Kafka->>ClickHouse: Replicate to audit log
    Kafka->>Redis: Invalidate cache

    Note over PostgreSQL,Qdrant: Embedding Generation

    PostgreSQL->>PostgreSQL: Strategy created
    PostgreSQL->>Kafka: Publish strategy.created
    Kafka->>Qdrant: Generate + store embedding
```

---

## 6. Network Topology

### Docker Compose Network (Development)

```mermaid
graph TB
    subgraph "Host: Lenovo Legion 5 Pro"
        subgraph "Docker Network: trading_network"
            subgraph "Application Tier"
                API[API Gateway<br/>:8000]
                TRADING[Trading Engine<br/>:8001]
                MARKET[Market Data<br/>:8002]
                FA[Fundamental Analysis<br/>:8003]
            end

            subgraph"Data Tier"
                PG[(PostgreSQL<br/>:5432)]
                CH[(ClickHouse<br/>:8123)]
                KAFKA[Kafka<br/>:9092]
                REDIS[(Redis<br/>:6379)]
            end

            subgraph "Monitoring Tier"
                PROM[Prometheus<br/>:9090]
                GRAFANA[Grafana<br/>:3000]
            end
        end

        GPU[NVIDIA RTX 3060<br/>GPU Access]
    end

    EXTERNAL[External APIs<br/>Yahoo, Alpha Vantage, IBKR] -.TLS 1.3.-> API

    API --> TRADING
    API --> MARKET
    API --> FA

    TRADING --> KAFKA
    MARKET --> KAFKA

    KAFKA --> PG
    KAFKA --> CH

    TRADING --> REDIS

    TRADING -.GPU.-> GPU
    FA -.metrics.-> PROM
    PROM --> GRAFANA
```

### Production Network (Kubernetes - Optional)

```mermaid
graph TB
    subgraph "Internet"
        USER[Users]
        EXTERNAL_API[External APIs]
    end

    subgraph "Load Balancer"
        LB[Cloud Load Balancer]
    end

    subgraph "Kubernetes Cluster"
        subgraph "Ingress"
            INGRESS[NGINX Ingress<br/>TLS Termination]
        end

        subgraph "Application Pods"
            API_POD1[API Gateway Pod 1]
            API_POD2[API Gateway Pod 2]
            TRADING_POD[Trading Engine Pod]
            MARKET_POD[Market Data Pod]
        end

        subgraph "StatefulSets"
            KAFKA_SET[Kafka StatefulSet<br/>3 replicas]
            PG_SET[PostgreSQL StatefulSet<br/>Primary + Replica]
        end

        subgraph "Services"
            API_SVC[API Gateway Service]
            KAFKA_SVC[Kafka Service]
            PG_SVC[PostgreSQL Service]
        end
    end

    USER --> LB
    LB --> INGRESS
    INGRESS --> API_SVC
    API_SVC --> API_POD1
    API_SVC --> API_POD2

    API_POD1 --> KAFKA_SVC
    KAFKA_SVC --> KAFKA_SET

    TRADING_POD --> PG_SVC
    PG_SVC --> PG_SET
```

---

## 7. Deployment Architecture

### Deployment Profiles

```mermaid
graph TB
    subgraph "Profile 1: Local Development"
        LAPTOP1[Lenovo Legion 5 Pro<br/>64GB RAM, RTX 3060]
        DOCKER_COMPOSE1[Docker Compose<br/>28 services + 5 databases]
        LAPTOP1 --> DOCKER_COMPOSE1
    end

    subgraph "Profile 2: Paper Trading"
        LAPTOP2[Lenovo Legion 5 Pro]
        DOCKER_COMPOSE2[Docker Compose<br/>Production mode]
        BACKUP_VPS[Optional VPS Backup<br/>$50/month]

        LAPTOP2 --> DOCKER_COMPOSE2
        DOCKER_COMPOSE2 -.optional backup.-> BACKUP_VPS
    end

    subgraph "Profile 3: Live Trading (Small)"
        LAPTOP3[Lenovo Legion 5 Pro<br/>Primary]
        VPS1[VPS Backup<br/>DigitalOcean/Vultr<br/>$50-100/month]

        LAPTOP3 --> VPS1
    end

    subgraph "Profile 4: Production (Scaling)"
        K8S_CLUSTER[Kubernetes Cluster<br/>AWS/GCP/DO<br/>$100-300/month]
        MULTI_REGION[Multi-Region<br/>Low Latency]

        K8S_CLUSTER --> MULTI_REGION
    end

    style LAPTOP1 fill:#90EE90
    style LAPTOP2 fill:#87CEEB
    style LAPTOP3 fill:#FFD700
    style K8S_CLUSTER fill:#FFB6C1
```

**Cost Progression**:

- Development: $0-10/month (laptop-only)
- Paper Trading: $10-40/month (laptop + optional backup)
- Live Trading: $50-100/month (laptop + VPS)
- Production: $100-300/month (Kubernetes cluster)

### CI/CD Pipeline

```mermaid
flowchart LR
    CODE[Code Push<br/>GitHub] --> LINT[Linting<br/>Black, isort]
    LINT --> UNIT[Unit Tests<br/>pytest]
    UNIT --> INTEGRATION[Integration Tests<br/>testcontainers]
    INTEGRATION --> SECURITY[Security Scan<br/>Bandit, Safety]
    SECURITY --> BUILD[Build Docker Images]
    BUILD --> PUSH[Push to Registry]

    PUSH --> DEPLOY_DEV{Deploy to Dev?}
    DEPLOY_DEV -->|Auto| DEV[Dev Environment<br/>Docker Compose]

    DEV --> DEPLOY_STAGING{Deploy to Staging?}
    DEPLOY_STAGING -->|Manual Approval| STAGING[Staging Environment<br/>Kubernetes]

    STAGING --> E2E[E2E Tests]
    E2E --> DEPLOY_PROD{Deploy to Prod?}
    DEPLOY_PROD -->|Manual Approval| PROD[Production<br/>Kubernetes]
```

---

## 8. Security Architecture

### Defense-in-Depth Layers

```mermaid
graph TB
    subgraph "Layer 1: Network Security"
        FW[Firewall<br/>UFW]
        WAF[Web Application Firewall<br/>ModSecurity]
        DDoS[DDoS Protection]
    end

    subgraph "Layer 2: Authentication"
        KEYCLOAK[Keycloak<br/>OAuth2 + OIDC]
        MFA[Multi-Factor Auth<br/>TOTP]
        JWT[JWT Tokens<br/>15min expiry]
    end

    subgraph "Layer 3: Authorization"
        RBAC[Role-Based Access Control]
        POLICY[Policy Engine]
        RATE_LIMIT[API Rate Limiting]
    end

    subgraph "Layer 4: Data Protection"
        TLS[TLS 1.3<br/>In Transit]
        AES[AES-256<br/>At Rest]
        VAULT[HashиCorp Vault<br/>Secrets]
    end

    subgraph "Layer 5: Monitoring"
        AUDIT_LOG[Audit Logging<br/>Click House]
        IDS[Intrusion Detection]
        SIEM[SIEM<br/>ELK Stack]
    end

    USER[User Request] --> FW
    FW --> WAF
    WAF --> KEYCLOAK
    KEYCLOAK --> MFA
    MFA --> JWT
    JWT --> RBAC
    RBAC --> POLICY
    POLICY --> RATE_LIMIT
    RATE_LIMIT --> TLS
    TLS --> AES
    AES --> VAULT

    KEYCLOAK -.logs.-> AUDIT_LOG
    RBAC -.logs.-> AUDIT_LOG
    TLS -.logs.-> AUDIT_LOG
    AUDIT_LOG --> IDS
    IDS --> SIEM
```

### Authentication Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant API_GW
    participant Keycloak
    participant Backend
    participant DB

    Note over User,DB: Login Flow

    User->>Frontend: Enter credentials
    Frontend->>Keycloak: POST /auth/login
    Keycloak->>Keycloak: Verify credentials
    Keycloak->>DB: Check user
    DB-->>Keycloak: User found
    Keycloak->>User: Request MFA code
    User->>Keycloak: Submit MFA code
    Keycloak->>Keycloak: Verify MFA
    Keycloak-->>Frontend: JWT + Refresh Token
    Frontend->>Frontend: Store tokens

    Note over User,DB: API Request with Auth

    Frontend->>API_GW: GET /api/v1/portfolio<br/>Authorization: Bearer JWT
    API_GW->>API_GW: Validate JWT signature
    API_GW->>Keycloak: Verify token (if needed)
    Keycloak-->>API_GW: Token valid
    API_GW->>Backend: Forward request + user_id
    Backend->>DB: Query data
    DB-->>Backend: Data
    Backend-->>API_GW: Response
    API_GW-->>Frontend: Response
```

---

## 9. AI/ML Pipeline Architecture

### Multi-Agent AI System

```mermaid
graph TB
    subgraph "User Interface"
        USER_QUERY[User Natural Language Query]
    end

    subgraph "LangGraph Orchestrator"
        INTENT[Intent Router Agent<br/>Classifies user query]

        subgraph "Specialist Agents"
            direction LR
            ANALYST[Market Analyst Agent<br/>Price analysis, technicals]
            STRATEGIST[Strategy Developer Agent<br/>Creates trading strategies]
            RISK_AGENT[Risk Analyzer Agent<br/>Risk assessment]
            FUNDAMENTAL[Fundamental Analyst Agent<br/>Company analysis]
            EDUCATOR[Educator Agent<br/>Teaching & tutorials]
        end

        ORCHESTRATOR[Response Orchestrator<br/>Aggregates responses]
    end

    subgraph "Knowledge & Context"
        NEO4J_GRAPH[(Neo4j<br/>Agent workflows)]
        QDRANT_VEC[(Qdrant<br/>RAG documents)]
        COGNEE[Cognee Memory<br/>Long-term memory]
    end

    subgraph "External Tools"
        OPENBB[OpenBB<br/>Financial data]
        TALIB[TA-Lib<br/>Technical indicators]
        NAUTILUS[NautilusTrader<br/>Backtesting]
    end

    USER_QUERY --> INTENT

    INTENT -->|Market question| ANALYST
    INTENT -->|Strategy request| STRATEGIST
    INTENT -->|Risk query| RISK_AGENT
    INTENT -->|Fundamental query| FUNDAMENTAL
    INTENT -->|Learning request| EDUCATOR

    ANALYST --> ORCHESTRATOR
    STRATEGIST --> ORCHESTRATOR
    RISK_AGENT --> ORCHESTRATOR
    FUNDAMENTAL --> ORCHESTRATOR
    EDUCATOR --> ORCHESTRATOR

    ORCHESTRATOR --> USER_QUERY

    INTENT -.reads.-> NEO4J_GRAPH
    ANALYST -.queries.-> QDRANT_VEC
    STRATEGIST -.uses.-> COGNEE

    ANALYST -.calls.-> TALIB
    FUNDAMENTAL -.calls.-> OPENBB
    STRATEGIST -.calls.-> NAUTILUS
```

### ML/DL Training Pipeline

```mermaid
flowchart TB
    START[Raw Market Data] --> FETCH[Fetch from APIs<br/>Yahoo, Alpha Vantage]
    FETCH --> STORE_RAW[Store in ClickHouse<br/>Raw data]

    STORE_RAW --> FEATURE_ENG[Feature Engineering<br/>Technical indicators, ratios]
    FEATURE_ENG --> NORMALIZE[Normalization<br/>MinMax, StandardScaler]

    NORMALIZE --> SPLIT[Train/Val/Test Split<br/>Chronological]

    SPLIT --> TRAIN{Model Type?}

    TRAIN -->|LSTM/GRU| LSTM_TRAIN[LSTM Training<br/>PyTorch + GPU]
    TRAIN -->|RL| RL_TRAIN[RL Training<br/>FinRL + PPO/A2C]
    TRAIN -->|XGBoost| XGBOOST_TRAIN[XGBoost Training<br/>CPU]

    LSTM_TRAIN --> VALIDATE[Validation]
    RL_TRAIN --> VALIDATE
    XGBOOST_TRAIN --> VALIDATE

    VALIDATE -->|Metrics good?| SAVE[Save Model<br/>Model Registry]
    VALIDATE -->|Metrics bad?| HYPERPARAMETER[Hyperparameter Tuning]
    HYPERPARAMETER --> TRAIN

    SAVE --> DEPLOY[Deploy to Inference<br/>ML/DL Service]
    DEPLOY --> MONITOR[Monitor Performance<br/>Prometheus]
```

---

## 10. Fundamental Analysis System Architecture

### Phase 15.5 Architecture (NEW)

```mermaid
graph TB
    subgraph "Data Sources"
        ALPHA_V[Alpha Vantage API<br/>5 calls/min]
        YAHOO[Yahoo Finance<br/>Unlimited]
        FMP[Financial Modeling Prep<br/>Premium, optional]
        SEC[SEC EDGAR<br/>Direct filing parser]
        INSIDER[OpenInsider.com<br/>Form 4 scraper]
    end

    subgraph "Fundamental Analysis Service"
        direction TB

        subgraph "Data Ingestion"
            INGESTION[Data Ingestion Service<br/>Multi-source fallback]
            EDGAR_PARSER[SEC EDGAR Parser<br/>10-K, 10-Q, 8-K]
            INSIDER_PARSER[Insider Trading Parser<br/>Form 4]
        end

        subgraph "Calculation Engines"
            RATIO_CALC[Ratio Calculator<br/>50+ ratios]
            VALUATION_CALC[Valuation Calculator<br/>DCF, DDM, Graham, PEG]
            QUALITY_CALC[Quality Scorer<br/>Piotroski, Altman, Beneish]
            COMPOSITE_CALC[Composite Scorer<br/>0-100 score]
        end

        subgraph "Advanced Analyzers - NEW"
            EARNINGS_ANALYZER[Earnings Analyzer<br/>Surprises, quality, guidance]
            INSIDER_ANALYZER[Insider Analyzer<br/>Sentiment, patterns]
            INDUSTRY_ANALYZER[Industry Analyzer<br/>Sector rotation, peers]
            HEALTH_MONITOR[Health Monitor<br/>Early warnings, bankruptcy]
            ESG_ANALYZER[ESG Analyzer<br/>ESG scores, trends]
        end
    end

    subgraph "Storage"
        PG_FUNDAMENTAL[(PostgreSQL<br/>Fundamental Schema<br/>statements, ratios, scores)]
    end

    subgraph "Event Bus"
        KAFKA_FUNDAMENTAL[Kafka Topics<br/>fundamental.*]
    end

    subgraph "Consumers"
        SCANNER[Market Scanner<br/>Fundamental screening]
        OPTIONS[Options Service<br/>Earnings analysis]
        AI[AI Assistant<br/>Fundamental insights]
    end

    ALPHA_V --> INGESTION
    YAHOO --> INGESTION
    FMP --> INGESTION
    SEC --> EDGAR_PARSER
    INSIDER --> INSIDER_PARSER

    INGESTION --> RATIO_CALC
    INGESTION --> VALUATION_CALC
    EDGAR_PARSER --> RATIO_CALC

    RATIO_CALC --> QUALITY_CALC
    VALUATION_CALC --> COMPOSITE_CALC
    QUALITY_CALC --> COMPOSITE_CALC

    COMPOSITE_CALC --> EARNINGS_ANALYZER
    INSIDER_PARSER --> INSIDER_ANALYZER
    COMPOSITE_CALC --> INDUSTRY_ANALYZER
    COMPOSITE_CALC --> HEALTH_MONITOR
    COMPOSITE_CALC --> ESG_ANALYZER

    EARNINGS_ANALYZER --> PG_FUNDAMENTAL
    INSIDER_ANALYZER --> PG_FUNDAMENTAL
    INDUSTRY_ANALYZER --> PG_FUNDAMENTAL
    HEALTH_MONITOR --> PG_FUNDAMENTAL
    ESG_ANALYZER --> PG_FUNDAMENTAL

    EARNINGS_ANALYZER --> KAFKA_FUNDAMENTAL
    INSIDER_ANALYZER --> KAFKA_FUNDAMENTAL

    KAFKA_FUNDAMENTAL --> SCANNER
    KAFKA_FUNDAMENTAL --> OPTIONS
    KAFKA_FUNDAMENTAL --> AI
```

### Fundamental Data Flow

```mermaid
sequenceDiagram
    participant User
    participant API
    participant FA_Service
    participant Data_Provider
    participant Calculator
    participant PostgreSQL
    participant Kafka
    participant Scanner

    Note over User,Scanner: Request Fundamental Analysis

    User->>API: GET /api/v1/fundamental/AAPL
    API->>FA_Service: Fetch fundamentals (AAPL)

    FA_Service->>PostgreSQL: Check cache
    PostgreSQL-->>FA_Service: Data age: 2 days (stale)

    FA_Service->>Data_Provider: Fetch latest financials
    Data_Provider-->>FA_Service: Financial statements

    FA_Service->>Calculator: Calculate 50+ ratios
    Calculator-->>FA_Service: Ratios computed

    FA_Service->>Calculator: Run valuation models
    Calculator-->>FA_Service: DCF, DDM, Graham values

    FA_Service->>Calculator: Calculate quality scores
    Calculator-->>FA_Service: Piotroski: 8, Altman: 3.2

    FA_Service->>PostgreSQL: Store results
    FA_Service->>Kafka: Publish fundamental.ratio.calculated
    FA_Service-->>API: Fundamental data
    API-->>User: Response

    Kafka->>Scanner: fundamental.ratio.calculated event
    Scanner->>Scanner: Update screening results
```

---

## Appendix: Key Performance Targets

| Component                      | Target         | Measurement                      |
| ------------------------------ | -------------- | -------------------------------- |
| **Order Execution Latency**    | <100μs         | p95 latency from signal to order |
| **Market Data Ingestion**      | >1M events/sec | Kafka throughput                 |
| **Real-Time UI Updates**       | <100ms         | WebSocket latency                |
| **Database Query (OLTP)**      | <10ms          | PostgreSQL p95                   |
| **Database Query (Analytics)** | <100ms         | ClickHouse 1B rows               |
| **API Response Time**          | <200ms         | REST API p95                     |
| **Test Coverage**              | >95%           | All microservices                |
| **System Uptime**              | 99.9%          | During market hours              |

---

**Document Status**: All 10 Architecture Diagrams Complete  
**Created**: 2025-11-20  
**Tools**: Mermaid diagrams for all visualizations  
**Next**: Implementation execution
