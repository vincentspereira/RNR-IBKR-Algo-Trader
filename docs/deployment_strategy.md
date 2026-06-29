# Cost-Effective Deployment Strategy

## Agentic AI Algorithmic Trading System

**Document Version**: 1.0  
**Last Updated**: 2025-01-19  
**Purpose**: Step-by-step guide for setting up the most cost-effective deployment

---

## Table of Contents

1. [Deployment Strategy Overview](#deployment-strategy-overview)
2. [Phase 1: Development & Paper Trading Setup](#phase-1-development--paper-trading-setup)
3. [Phase 2: Initial Live Trading Setup](#phase-2-initial-live-trading-setup)
4. [Phase 3: Scaling Setup](#phase-3-scaling-setup)
5. [Migration Guides](#migration-guides)
6. [Troubleshooting](#troubleshooting)

---

## Deployment Strategy Overview

### Our Phased Approach

```
Phase 1 (0-6 months):     Laptop Only → $10-40/month
Phase 2 (6-12 months):    Laptop + VPS Backup → $50-100/month
Phase 3 (12+ months):     Laptop + Selective Cloud → $100-300/month
```

### Decision Criteria

**Move to Next Phase ONLY when:**

- ✅ Current phase proven successful (>3 months)
- ✅ Consistently profitable
- ✅ Clear technical need (not just "nice to have")
- ✅ ROI justifies additional cost

**Key Principle**: Start minimal, scale incrementally, measure continuously.

---

## Phase 1: Development & Paper Trading Setup

**Timeline**: Months 1-6  
**Monthly Cost**: $10-40 (electricity + internet)  
**Goal**: Build system, validate strategies, learn platform

### Prerequisites

**Hardware** (You already have!):

- ✅ Lenovo Legion 5 Pro (Ryzen 7, 64GB RAM, RTX 3060)
- ✅ 1TB+ storage
- ✅ Stable internet connection

**Software** (Free):

- ✅ Windows 11
- ✅ Docker Desktop
- ✅ VS Code
- ✅ Git

### Step-by-Step Setup

#### Step 1: Install Core Software

```powershell
# Install Chocolatey (Windows package manager)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install Docker Desktop
choco install docker-desktop -y

# Install VS Code
choco install vscode -y

# Install Git
choco install git -y

# Install Python 3.11
choco install python311 -y

# Restart PowerShell for PATH updates
```

#### Step 2: Clone Repository

```powershell
# Navigate to projects directory
cd C:\Users\vince\Projects\Trading

# Already have the repo!
cd "IBKR - Algo Trader"

# Verify structure
ls
```

#### Step 3: Set Up Docker Compose Environment

**Create `.env` file:**

```bash
# File: C:\Users\vince\Projects\Trading\IBKR - Algo Trader\.env

#-----------------------
# Environment Configuration
#-----------------------
ENVIRONMENT=development
DEPLOYMENT=laptop

# ----------------------
# Database Configuration
# ----------------------

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trading_db
POSTGRES_USER=trading_user
POSTGRES_PASSWORD=change_this_in_production_123!
POSTGRES_MAX_CONNECTIONS=100

# ClickHouse
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_DB=market_data
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=change_this_in_production_123!

# Neo4j
NEO4J_HOST=localhost
NEO4J_PORT=7687
NEO4J_HTTP_PORT=7474
NEO4J_USER=neo4j
NEO4J_PASSWORD=change_this_in_production_123!

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=change_this_in_production_123!

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_GRPC_PORT=6334

# ----------------------
# Kafka Configuration
# ----------------------
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_NUM_PARTITIONS=3
KAFKA_REPLICATION_FACTOR=1
KAFKA_LOG_RETENTION_HOURS=168
KAFKA_LOG_RETENTION_BYTES=1073741824

SCHEMA_REGISTRY_URL=http://localhost:8081

# ----------------------
# IBKR Configuration
# ----------------------
IBKR_MODE=paper
IBKR_TWS_PORT=7497
IBKR_CLIENT_ID=1
IBKR_ACCOUNT=DU123456  # Your paper trading account

# ----------------------
# AI Configuration
# ----------------------
AI_PROVIDER=local  # local (Ollama) or openai
OPENAI_API_KEY=  # Leave empty for local
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3

#----------------------
# Cognee Memory
# ----------------------
COGNEE_DIR=C:\Users\vince\Projects\AI Agents\RNR Enhanced Cognee
COGNEE_PORT=8000

# ----------------------
# Application Settings
# ----------------------
LOG_LEVEL=INFO
DEBUG=false
GPU_ENABLED=true
CUDA_VISIBLE_DEVICES=0
```

#### Step 4: Create Docker Compose File

**File**: `docker-compose.yml`

```yaml
version: "3.8"

services:
  # =====================
  # Databases
  # =====================

  postgres:
    image: pgvector/pgvector:pg17
    container_name: trading_postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_MAX_CONNECTIONS: ${POSTGRES_MAX_CONNECTIONS}
    ports:
      - "${POSTGRES_PORT}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts/postgres:/docker-entrypoint-initdb.d
    networks:
      - trading_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  clickhouse:
    image: clickhouse/clickhouse-server:24.8-alpine
    container_name: trading_clickhouse
    environment:
      CLICKHOUSE_DB: ${CLICKHOUSE_DB}
      CLICKHOUSE_USER: ${CLICKHOUSE_USER}
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}
    ports:
      - "${CLICKHOUSE_PORT}:9000"
      - "${CLICKHOUSE_HTTP_PORT}:8123"
    volumes:
      - clickhouse_data:/var/lib/clickhouse
      - ./config/clickhouse:/etc/clickhouse-server/config.d
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "clickhouse-client", "--query", "SELECT 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:5.25.0-community
    container_name: trading_neo4j
    environment:
      NEO4J_AUTH: ${NEO4J_USER}/${NEO4J_PASSWORD}
      NEO4J_server_memory_heap_max__size: 2G
      NEO4J_server_memory_pagecache_size: 1G
    ports:
      - "${NEO4J_PORT}:7687"
      - "${NEO4J_HTTP_PORT}:7474"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    networks:
      - trading_network
    healthcheck:
      test:
        [
          "CMD",
          "cypher-shell",
          "-u",
          "${NEO4J_USER}",
          "-p",
          "${NEO4J_PASSWORD}",
          "RETURN 1",
        ]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7.4-alpine
    container_name: trading_redis
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "${REDIS_PORT}:6379"
    volumes:
      - redis_data:/data
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:v1.12.0
    container_name: trading_qdrant
    ports:
      - "${QDRANT_PORT}:6333"
      - "${QDRANT_GRPC_PORT}:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/readyz"]
      interval: 10s
      timeout: 5s
      retries: 5

  # =====================
  # Message Queue
  # =====================

  kafka:
    image: apache/kafka:3.9.0
    container_name: trading_kafka
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_LOG_DIRS: /var/lib/kafka/data
      KAFKA_NUM_PARTITIONS: ${KAFKA_NUM_PARTITIONS}
      KAFKA_LOG_RETENTION_HOURS: ${KAFKA_LOG_RETENTION_HOURS}
      KAFKA_LOG_RETENTION_BYTES: ${KAFKA_LOG_RETENTION_BYTES}
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
          "kafka-broker-api-versions.sh",
          "--bootstrap-server",
          "localhost:9092",
        ]
      interval: 10s
      timeout: 10s
      retries: 5

  schema-registry:
    image: confluentinc/cp-schema-registry:7.7.0
    container_name: trading_schema_registry
    depends_on:
      kafka:
        condition: service_healthy
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092
      SCHEMA_REGISTRY_LISTENERS: http://0.0.0.0:8081
    ports:
      - "8081:8081"
    networks:
      - trading_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/subjects"]
      interval: 10s
      timeout: 5s
      retries: 5

  # =====================
  # AI Services
  # =====================

  ollama:
    image: ollama/ollama:latest
    container_name: trading_ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - trading_network
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  postgres_data:
  clickhouse_data:
  neo4j_data:
  neo4j_logs:
  redis_data:
  qdrant_data:
  kafka_data:
  ollama_data:

networks:
  trading_network:
    driver: bridge
```

#### Step 5: Start Infrastructure

```powershell
# Navigate to project root
cd "C:\Users\vince\Projects\Trading\IBKR - Algo Trader"

# Start all services
docker-compose up -d

# Verify all services are healthy
docker-compose ps

# Expected output: All services "healthy" or "running"

# View logs
docker-compose logs -f

# Check specific service
docker-compose logs postgres
```

#### Step 6: Install Ollama and Download Model

```powershell
# Pull LLaMA model
docker exec -it trading_ollama ollama pull llama3

# Test Ollama
curl http://localhost:11434/api/generate -d '{
  "model": "llama3",
  "prompt": "What is algorithmic trading?"
}'
```

#### Step 7: Set Up Python Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate
.\venv\Scripts\Activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install PyTorch with CUDA (for GPU support)
pip install torch==2.6.0+cu126 -f https://download.pytorch.org/whl/torch_stable.html
```

#### Step 8: Configure IBKR Paper Trading

**Steps:**

1. **Download TWS (Trader Workstation)**:
   - Visit: https://www.interactivebrokers.com/en/trading/tws.php
   - Download and install TWS

2 **Create Paper Trading Account**:

- Visit: https://www.interactivebrokers.com/en/trading/free-trial.php
- Sign up for paper trading account
- Note your account number (e.g., DU123456)

3. **Configure TWS for API Access**:

   - Open TWS
   - File → Global Configuration → API → Settings
   - ✅ Enable ActiveX and Socket Clients
   - ✅ Read-Only API: NO
   - Trusted IPs: 127.0.0.1
   - Socket port: 7497 (paper) or 7496 (live)
   - Click OK

4. **Update `.env` file**:
   ```bash
   IBKR_MODE=paper
   IBKR_TWS_PORT=7497
   IBKR_ACCOUNT=DU123456  # Your actual account number
   ```

#### Step 9: Initialize Databases

```powershell
# Run database migrations
python scripts/init_databases.py

# Verify tables created
docker exec -it trading_postgres psql -U trading_user -d trading_db -c "\dt"

# Expected: List of tables
```

#### Step 10: Verify Installation

**Health Check Script**:

```powershell
# Run health check
python scripts/health_check.py

# Expected output:
# ✅ PostgreSQL: Connected
# ✅ ClickHouse: Connected
# ✅ Neo4j: Connected
# ✅ Redis: Connected
# ✅ Qdrant: Connected
# ✅ Kafka: Connected
# ✅ Schema Registry: Connected
# ✅ Ollama: Connected
# ✅ IBKR TWS: Connected (if running)
```

### Phase 1 Cost Breakdown

| Item                          | Cost              |
| ----------------------------- | ----------------- |
| Laptop electricity (12hr/day) | $5/month          |
| Internet                      | $0 (existing)     |
| IBKR Paper Account            | $0                |
| Market Data                   | $0 (free sources) |
| Docker Desktop                | $0 (free)         |
| VS Code                       | $0 (free)         |
| Ollama (local AI)             | $0 (free)         |
| **Total**                     | **$5-10/month**   |

### Success Criteria for Phase 1

Before moving to Phase 2:

- ✅ All services running reliably on laptop
- ✅ Developed and back tested 3+ strategies
- ✅ Paper trading for >3 months
- ✅ At least 1 strategy showing consistent paper trading profits
- ✅ Comfortable with system operation
- ✅ Ready to commit capital ($5k-10k)

---

## Phase 2: Initial Live Trading Setup

**Timeline**: Months 6-12  
**Monthly Cost**: $50-100  
**Goal**: Start live trading with redundancy

### When to Start Phase 2

✅ **Prerequisites**:

- Completed Phase 1 (min 3 months)
- At least 1 consistently profitable strategy in paper trading
- Ready to commit $5k-10k capital
- Understand risks of live trading

### Step-by-Step Setup

#### Step 1: Open IBKR Live Account

1. **Application**:

   - Visit: https://www.interactivebrokers.com/en/home.php
   - Click "Open Account"
   - Choose "Individual" account
   - Complete application (15-30 minutes)

2. **Verification**:

   - Upload ID and address proof
   - Approval: 1-3 days

3. **Fund Account**:

   - Minimum: $0 (but recommend $5k-10k)
   - Pattern Day Trader requirement: $25k (US only, if >3 day trades/week)

4. **Enable API Access**:
   - Same as paper trading configuration
   - Port: 7496 (live) instead of 7497

#### Step 2: Set Up VPS Backup (Optional but Recommended)

**Provider: Hetzner (Best Value)**

**Steps**:

1. **Sign Up**:

   - Visit: https://www.hetzner.com/cloud
   - Create account
   - Verify email

2. **Create Server**:

   ```
   Location: Falkenstein, Germany (closest to Europe markets)
   Image: Ubuntu 24.04
   Type: CX32 (4 vCPU, 8GB RAM)
   Cost: €10.86/month (~$12)

   Add-ons:
   - Backups: Yes (+20% = €2.17)
   Total: €13.03/month (~$14)
   ```

3. **Initial Setup**:

   ```bash
   # SSH into server
   ssh root@<server-ip>

   # Update system
   apt update && apt upgrade -y

   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sh get-docker.sh

   # Install Docker Compose
   apt install docker-compose -y

   # Create project directory
   mkdir -p /opt/trading
   cd /opt/trading
   ```

4. **Deploy Critical Services Only**:

   ```yaml
   # docker-compose.yml (VPS - MINIMAL)
   version: "3.8"

   services:
     trading-engine:
       image: your-trading-engine:latest
       environment:
         - MODE=backup
         - PRIMARY_HOST=<laptop-ip>
       ports:
         - "8080:8080"
       restart: unless-stopped

     risk-manager:
       image: your-risk-manager:latest
       environment:
         - MODE=backup
       restart: unless-stopped

     order-management:
       image: your-oms:latest
       environment:
         - MODE=backup
         - IBKR_HOST=<laptop-ip>
       restart: unless-stopped

     redis:
       image: redis:7.4-alpine
       command: redis-server --appendonly yes
       volumes:
         - redis_data:/data
       restart: unless-stopped

   volumes:
     redis_data:
   ```

5. **Set Up Failover Logic**:
   ```python
   # In your main application
   def get_trading_endpoint():
       primary = "http://localhost:8080"  # Laptop
       backup = "http://<vps-ip>:8080"     # VPS

       try:
           response = requests.get(f"{primary}/health", timeout=2)
           if response.status_code == 200:
               return primary
       except:
           logger.warning("Primary unavailable, using backup")
           return backup
   ```

#### Step 3: Set Up Monitoring

**Install Prometheus + Grafana on Laptop:**

```powershell
# Add to docker-compose.yml

  prometheus:
    image: prom/prometheus:latest
    container_name: trading_prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    networks:
      - trading_network

  grafana:
    image: grafana/grafana:latest
    container_name: trading_grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards
    networks:
      - trading_network
```

**Prometheus Configuration** (`config/prometheus/prometheus.yml`):

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "trading-engine"
    static_configs:
      - targets: ["localhost:8080"]

  - job_name: "risk-manager"
    static_configs:
      - targets: ["localhost:8081"]

  - job_name: "postgres"
    static_configs:
      - targets: ["postgres-exporter:9187"]
```

#### Step 4: Configure Alerts

**Create Alert Rules** (`config/prometheus/alerts.yml`):

```yaml
groups:
  - name: trading_alerts
    rules:
      - alert: HighDrawdown
        expr: current_drawdown > 0.05  # 5% drawdown
        for: 1m
        annotations:
          summary: "Portfolio drawdown exceeded 5%"

      - alert: TradingEngineDown
        expr: up{job="trading-engine"} == 0
        for: 2m
        annotations:
          summary: "Trading engine is down"

      - alert: OrderExecutionSloworderExecution        expr: order_execution_latency_ms > 1000
        for: 5m
        annotations:
          summary: "Order execution is slow (>1s)"
```

#### Step 5: Update `.env` for Live Trading

```bash
# Update these values
ENVIRONMENT=production
IBKR_MODE=live
IBKR_TWS_PORT=7496
IBKR_ACCOUNT=U123456  # Your live account number

# Enable stricter risk limits
MAX_POSITION_SIZE=10000  # $10k max per position
MAX_DAILY_LOSS=500       # $500 max loss per day
ENABLE_RISK_ALERTS=true
```

### Phase 2 Cost Breakdown

| Item                            | Cost                                   |
| ------------------------------- | -------------------------------------- |
| Laptop electricity              | $5/month                               |
| VPS (Hetzner CX32 with backups) | $14/month                              |
| IBKR Live Account minimum       | $0                                     |
| IBKR monthly minimum fee        | $10/month (waived if commissions >$10) |
| Market data fees                | $0-20/month (usually waived)           |
| OpenAI API (optional)           | $20-30/month                           |
| **Total**                       | **$39-79/month**                       |

### Success Criteria for Phase 2

Before moving to Phase 3:

- ✅ Live trading for >6 months
- ✅ Consistently profitable (>3 consecutive profitable months)
- ✅ Managing capital >$25k
- ✅ Running multiple strategies simultaneously
- ✅ VPS backup working reliably
- ✅ Clear need for additional compute resources

---

## Phase 3: Scaling Setup

**Timeline**: Months 12+  
**Monthly Cost**: $100-300  
**Goal**: Scale to multiple strategies and larger capital

### When to Start Phase 3

✅ **Prerequisites**:

- Completed Phase 2 (min 6 months)
- Consistently profitable for >6 months
- Managing >$25k capital
- Running 3+ strategies simultaneously
- Clear compute bottleneck identified

### Step-by-Step Setup

#### Step 1: Choose Selective Cloud Services

**Recommended**: DigitalOcean (simplest) or Hetzner (cheapest)

**Deploy ONLY Production Components**:

```
Development/Backtesting: Keep on laptop
Production Trading: Move to cloud
```

#### Step 2: Set Up Kubernetes (Single Node)

**DigitalOcean Kubernetes Setup**:

1. **Create Kubernetes Cluster**:

   - Log in to DigitalOcean
   - Kubernetes → Create Cluster
   - Configuration:
     ```
     Node: 1x Basic Node (4 vCPU, 8GB = $48/month)
     Region: New York (closest to US markets)
     Version: Latest stable
     ```

2. **Install kubectl**:

   ```powershell
   choco install kubernetes-cli -y
   ```

3. **Connect to Cluster**:

   ```powershell
   # Download kubeconfig from DigitalOcean dashboard
   $env:KUBECONFIG="C:\Users\vince\.kube\config"

   # Verify connection
   kubectl get nodes
   ```

#### Step 3: Deploy Services to Kubernetes

**Create Deployment** (`k8s/trading-engine.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trading-engine
spec:
  replicas: 2
  selector:
    matchLabels:
      app: trading-engine
  template:
    metadata:
      labels:
        app: trading-engine
    spec:
      containers:
        - name: trading-engine
          image: your-registry/trading-engine:latest
          ports:
            - containerPort: 8080
          env:
            - name: ENVIRONMENT
              value: "production"
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: "kafka:9092"
          resources:
            requests:
              memory: "1Gi"
              cpu: "500m"
            limits:
              memory: "2Gi"
              cpu: "1000m"
---
apiVersion: v1
kind: Service
metadata:
  name: trading-engine
spec:
  selector:
    app: trading-engine
  ports:
    - port: 80
      targetPort: 8080
  type: ClusterIP
```

**Deploy**:

```powershell
kubectl apply -f k8s/trading-engine.yaml
kubectl get pods
kubectl logs -f deployment/trading-engine
```

#### Step 4: Set Up Managed Redis (Optional)

**DigitalOcean Managed Redis**:

```
Configuration:
- 1GB RAM
- Cost: $15/month
- Advantage: Automated backups, monitoring

vs Self-Hosted:
- Cost: $0 (on Kubernetes)
- Requires manual management
```

**Recommendation**: Start self-hosted, upgrade to managed if needed.

#### Step 5: Implement Auto-Scaling

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: trading-engine-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: trading-engine
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Phase 3 Cost Breakdown

| Item                     | Cost                      |
| ------------------------ | ------------------------- |
| Laptop (development)     | $5/month                  |
| Kubernetes (1 node)      | $48/month                 |
| Managed Redis (optional) | $0-15/month               |
| IBKR fees                | $0 (waived with volume)   |
| Market data              | $0 (waived)               |
| OpenAI API               | $30-50/month              |
| Monitoring               | $0 (Prometheus + Grafana) |
| **Total**                | **$83-118/month**         |

### Success Criteria for Phase 3

- ✅ Managing >$100k capital
- ✅ Running 5+ strategies
- ✅ Consistently profitable for 12+ months
- ✅ All systems monitored and automated
- ✅ Can handle market volatility

---

## Migration Guides

### Migrating from Laptop to VPS

**Data Migration**:

```powershell
# 1. Export databases from laptop
docker exec trading_postgres pg_dump -U trading_user trading_db > backup.sql

# 2. Transfer to VPS
scp backup.sql root@<vps-ip>:/opt/trading/

# 3. Import on VPS
ssh root@<vps-ip>
docker exec -i trading_postgres psql -U trading_user trading_db < /opt/trading/backup.sql
```

**Configuration Migration**:

```powershell
# Copy environment files
scp .env docker-compose.yml root@<vps-ip>:/opt/trading/

# Copy configuration directories
scp -r ./config root@<vps-ip>:/opt/trading/
```

### Migrating from VPS to Kubernetes

**Create Docker Images**:

```powershell
# Build images
docker build -t your-registry/trading-engine:latest ./services/trading-engine
docker build -t your-registry/risk-manager:latest ./services/risk-manager

# Push to registry
docker push your-registry/trading-engine:latest
docker push your-registry/risk-manager:latest
```

**Deploy to Kubernetes**:

```powershell
# Apply all configurations
kubectl apply -f k8s/

# Verify
kubectl get pods
kubectl get services
```

---

## Troubleshooting

### Common Issues

#### Issue 1: Docker Services Won't Start

**Symptoms**:

```
Error: Cannot start service postgres: driver failed programming external connectivity
```

**Solution**:

```powershell
# Check if ports are in use
netstat -ano | findstr :5432

# If port is occupied, change port in docker-compose.yml
# OR stop the conflicting service
```

#### Issue 2: High Memory Usage on Laptop

**Symptoms**:

- Laptop slowing down
- Docker containers crashing

**Solution**:

```powershell
# Check memory usage
docker stats

# Reduce database memory limits in docker-compose.yml
# Example for Neo4j:
NEO4J_server_memory_heap_max__size: 1G  # Instead of 2G
```

#### Issue 3: IBKR Connection Fails

**Symptoms**:

```
Error: Connection refused to TWS
```

**Solution**:

1. Ensure TWS is running
2. Verify API settings enabled in TWS
3. Check firewall isn't blocking port 7496/7497
4. Verify correct port in `.env`

#### Issue 4: Kafka Out of Diskspace

**Symptoms**:

```
Error: No space left on device
```

**Solution**:

```powershell
# Check Kafka logs size
docker exec trading_kafka du -sh /var/lib/kafka/data

# Reduce retention in docker-compose.yml
KAFKA_LOG_RETENTION_HOURS: 24  # Instead of 168 (1 week)

# Restart Kafka
docker-compose restart kafka
```

---

## Monitoring Checklist

### Daily Checks

```
□ All Docker containers running (docker-compose ps)
□ No critical alerts in Grafana
□ IBKR connection stable
□ Trading strategies executing as expected
□ No unusual errors in logs
```

### Weekly Checks

```
□ Disk space sufficient (>20% free)
□ Database performance acceptable
□ Backup completed successfully
□ Review trading performance
□ Check cost tracking (if using cloud)
```

### Monthly Checks

```
□ Update Docker images
□ Review and optimize database indexes
□ Clean up old logs and data
□ Review and update strategies
□ Validate backup restoration
□ Cost review and optimization
```

---

## Summary

### Recommended Path

**Months 1-6**: Laptop Only

- Cost: $5-10/month
- Focus: Learning, development, paper trading

**Months 6-12**: Laptop + VPS Backup

- Cost: $50-100/month
- Focus: Initial live trading, build confidence

**Months 12+**: Laptop + Selective Cloud

- Cost: $100-300/month
- Focus: Scaling, multiple strategies

### Key Takeaways

1. **Start Minimal**: Laptop-only deployment is sufficient for development and paper trading
2. **Scale Incrementally**: Add VPS backup only when moving to live trading
3. **Measure Before Scaling**: Move to cloud only when laptop is proven insufficient
4. **Optimize Continuously**: Monitor costs and performance weekly
5. **Focus on Trading**: Infrastructure should serve trading, not the other way around

### Total 3-Year Cost Comparison

| Approach                  | Year 1 | Year 2  | Year 3  | Total (3yr) |
| ------------------------- | ------ | ------- | ------- | ----------- |
| **Our Phased Approach**   | $360   | $900    | $1,200  | **$2,460**  |
| **Full Cloud from Day 1** | $8,400 | $12,000 | $12,000 | **$32,400** |
| **Savings**               | $8,040 | $11,100 | $10,800 | **$29,940** |

**That's $29,940 saved that can compound in your trading account!**

---

**Document Maintained By**: Trading System Team  
**Review Frequency**: Quarterly  
**Next Review**: 2025-04-19
