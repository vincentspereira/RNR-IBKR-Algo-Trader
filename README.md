# Agentic AI Algorithmic Trading System

## Overview

An enterprise-grade, Agentic AI-based Algorithmic Trading System designed for the **Interactive Brokers TWS** platform. This system leverages a microservices architecture, event-driven design (Kafka), and state-of-the-art AI (LangGraph, RAG) to execute sophisticated trading strategies.

## Architecture

The system runs on a **Lenovo Legion 5 Pro** (Ryzen 7, 64GB RAM, RTX 3060) using **Docker Compose** for orchestration.

### Core Components

- **AI Assistant (`services/ai-assistant`)**: The "Brain" of the system. Uses LangGraph and PyTorch (CUDA 12.6) for decision making.
- **Trading Engine (`services/trading-engine`)**: Executes trades via NautilusTrader.
- **Market Data (`services/market-data`)**: Aggregates data from Yahoo, AlphaVantage, etc., with fallback logic.
- **Backtesting Engine (`services/backtesting-engine`)**: Dual-engine setup (VectorBT for research, NautilusTrader for validation).

### Infrastructure (Docker)

- **Kafka (3.9.0)**: Event Bus (KRaft mode).
- **PostgreSQL (17)**: Transactional DB with `pgvector`.
- **ClickHouse (24.8)**: Time-series data and Audit Logs.
- **Redis (7.4)**: Caching.
- **Qdrant (1.12)**: Vector Database for RAG.
- **Neo4j (5.25 Community)**: Knowledge Graph.
- **Keycloak (26.0)**: Authentication.

## Setup & Installation

### Prerequisites

- **Docker Desktop** (with WSL2 backend).
- **NVIDIA Container Toolkit** (for GPU support).
- **Python 3.11**.

### Local Development

**DO NOT install dependencies globally.** Use the provided scripts or Docker.

1.  **Infrastructure**:

    ```bash
    docker-compose up -d
    ```

2.  **Python Environment**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt
    ```

## Project Structure

- `libs/`: Shared libraries (`core`, `quant`, `domain`).
- `services/`: Microservices.
- `core_trading/`: Legacy codebase (migrated).

## Status

- [x] Infrastructure Setup
- [x] Core Code Migration
- [x] Market Data Service (Basic)
- [ ] Backtesting Engine
- [ ] AI Assistant Integration
