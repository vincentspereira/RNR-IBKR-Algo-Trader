#!/bin/bash
# ====================================================================================
# Kafka Topics Creation Script
# Agentic AI Algorithmic Trading System v5.0
# ====================================================================================
#
# This script creates all Kafka topics required for the trading system.
# Run this after Kafka is up and running.
#
# Usage: docker-compose exec kafka-init /bin/bash /scripts/create-topics.sh
# ====================================================================================

set -e

KAFKA_BROKER="kafka:9092"

echo "=========================================="
echo "Creating Kafka Topics for Trading System"
echo "=========================================="
echo ""

# Wait for Kafka to be ready
echo "Waiting for Kafka broker to be ready..."
kafka-broker-api-versions --bootstrap-server $KAFKA_BROKER > /dev/null 2>&1
while [ $? -ne 0 ]; do
  sleep 2
  echo "Still waiting for Kafka..."
  kafka-broker-api-versions --bootstrap-server $KAFKA_BROKER > /dev/null 2>&1
done
echo "✓ Kafka broker is ready!"
echo ""

# Function to create topic
create_topic() {
  local topic=$1
  local partitions=$2
  local retention=$3
  local replication=${4:-1}
  
  echo "Creating topic: $topic (partitions=$partitions, retention=$retention)"
  
  kafka-topics --bootstrap-server $KAFKA_BROKER \
    --create \
    --if-not-exists \
    --topic $topic \
    --partitions $partitions \
    --replication-factor $replication \
    --config retention.ms=$retention \
    --config compression.type=lz4 \
    --config min.insync.replicas=1
}

echo "==================== MARKET DATA TOPICS ===================="
create_topic "marketdata.tick.NYSE.AAPL" 16 86400000     #24 hours
create_topic "marketdata.tick.NASDAQ.GOOGL" 16 86400000
create_topic "marketdata.bar.1m.NYSE.AAPL" 8 604800000    # 7 days
create_topic "marketdata.bar.5m.NYSE.AAPL" 4 604800000
create_topic "marketdata.bar.1h.NYSE.AAPL" 4 2592000000   # 30 days
create_topic "marketdata.bar.1d.NYSE.AAPL" 4 2592000000
create_topic "marketdata.options.chain.AAPL" 4 604800000

echo ""
echo "==================== TRADING TOPICS ===================="
create_topic "trading.order.created" 8 604800000        # 7 days
create_topic "trading.order.submitted" 8 604800000
create_topic "trading.order.filled" 8 604800000
create_topic "trading.order.cancelled" 8 604800000
create_topic "trading.order.rejected" 8 604800000
create_topic "trading.position.opened" 8 604800000
create_topic "trading.position.modified" 8 604800000
create_topic "trading.position.closed" 8 604800000
create_topic "trading.signal.generated" 8 604800000
create_topic "trading.strategy.deployed" 4 604800000
create_topic "trading.strategy.stopped" 4 604800000

echo ""
echo "==================== RISK TOPICS ===================="
create_topic "risk.limit.breached" 4 2592000000         # 30 days
create_topic "risk.var.calculated" 4 2592000000
create_topic "risk.alert.triggered" 4 2592000000
create_topic "risk.circuit_breaker.activated" 4 2592000000
create_topic "risk.position.warning" 4 2592000000

echo ""
echo "==================== FUNDAMENTAL TOPICS (NEW - Phase 15.5) ===================="
create_topic "fundamental.data.updated" 4 7776000000     # 90 days
create_topic "fundamental.statement.published" 4 7776000000
create_topic "fundamental.ratio.calculated" 4 7776000000
create_topic "fundamental.score.computed" 4 7776000000
create_topic "fundamental.valuation.updated" 4 7776000000
create_topic "fundamental.earnings.announced" 4 7776000000
create_topic "fundamental.earnings.surprise" 4 7776000000
create_topic "fundamental.insider.transaction" 4 7776000000
create_topic "fundamental.esg.updated" 4 7776000000

echo ""
echo "==================== AI TOPICS ===================="
create_topic "ai.query.received" 4 604800000            # 7 days
create_topic "ai.agent.processing" 4 604800000
create_topic "ai.agent.completed" 4 604800000
create_topic "ai.rag.retrieved" 4 604800000
create_topic "ai.guidance.suggested" 4 604800000
create_topic "ai.strategy.generated" 4 604800000

echo ""
echo "==================== SYSTEM TOPICS ===================="
create_topic "system.health.service" 2 2592000000       # 30 days
create_topic "system.error" 2 2592000000
create_topic "system.audit" 2 7776000000                # 90 days
create_topic "system.config.updated" 2 2592000000

echo ""
echo "=========================================="
echo "✓ All Kafka topics created successfully!"
echo "=========================================="
echo ""

# List all topics
echo "Created topics:"
kafka-topics --bootstrap-server $KAFKA_BROKER --list

echo ""
echo "Topic details:"
kafka-topics --bootstrap-server $KAFKA_BROKER --describe

echo ""
echo "✓ Kafka setup complete!"
