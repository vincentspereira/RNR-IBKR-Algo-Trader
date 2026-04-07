"""Test suite for library modules."""

import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import unittest
from datetime import datetime
from uuid import uuid4

# Import from libs if available
try:
    from libs.common.events.base import (
        BaseEvent,
        MarketDataEvent,
        TradingEvent,
        RiskEvent,
        FundamentalEvent,
        AIEvent,
        SystemEvent,
        OrderCreatedEvent,
        OrderFilledEvent,
        PositionOpenedEvent,
        SignalGeneratedEvent,
        FundamentalDataUpdatedEvent,
        RiskLimitBreachedEvent
    )
    LIBS_AVAILABLE = True
except ImportError:
    LIBS_AVAILABLE = False


@unittest.skipIf(not LIBS_AVAILABLE, "libs.common.events not available")
class TestBaseEvent(unittest.TestCase):
    """Test BaseEvent class and subclasses."""
    
    def test_base_event_creation(self):
        """Test creating a basic event."""
        event = BaseEvent(event_type="test.event")
        
        self.assertIsInstance(event.event_id, type(uuid4()))
        self.assertEqual(event.event_type, "test.event")
        self.assertIsInstance(event.timestamp, datetime)
        self.assertEqual(event.version, "1.0.0")
        self.assertIsNone(event.correlation_id)
        self.assertIsNone(event.causation_id)
        self.assertEqual(event.metadata, {})
    
    def test_base_event_with_correlation(self):
        """Test event with correlation IDs."""
        correlation_id = uuid4()
        causation_id = uuid4()
        metadata = {"source": "test"}
        
        event = BaseEvent(
            event_type="test.event",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata=metadata
        )
        
        self.assertEqual(event.correlation_id, correlation_id)
        self.assertEqual(event.causation_id, causation_id)
        self.assertEqual(event.metadata, metadata)
    
    def test_base_event_serialization(self):
        """Test event to_dict and from_dict methods."""
        event = BaseEvent(event_type="test.event")
        data = event.to_dict()
        
        self.assertIsInstance(data, dict)
        self.assertIn("event_id", data)
        self.assertIn("event_type", data)
        
        # Test deserialization
        event2 = BaseEvent.from_dict(data)
        self.assertEqual(event.event_type, event2.event_type)
    
    def test_market_data_event(self):
        """Test MarketDataEvent."""
        event = MarketDataEvent(symbol="AAPL", exchange="NASDAQ")
        
        self.assertEqual(event.symbol, "AAPL")
        self.assertEqual(event.exchange, "NASDAQ")
        self.assertEqual(event.event_type, "market_data")
    
    def test_trading_event(self):
        """Test TradingEvent."""
        order_id = uuid4()
        user_id = uuid4()
        strategy_id = uuid4()
        
        event = TradingEvent(order_id=order_id, user_id=user_id, strategy_id=strategy_id)
        
        self.assertEqual(event.order_id, order_id)
        self.assertEqual(event.user_id, user_id)
        self.assertEqual(event.strategy_id, strategy_id)
        self.assertEqual(event.event_type, "trading")
    
    def test_risk_event(self):
        """Test RiskEvent."""
        event = RiskEvent(severity="HIGH", alert_type="position_limit")
        
        self.assertEqual(event.severity, "HIGH")
        self.assertEqual(event.alert_type, "position_limit")
        self.assertEqual(event.event_type, "risk")
    
    def test_fundamental_event(self):
        """Test FundamentalEvent."""
        event = FundamentalEvent(
            symbol="AAPL",
            period_end=datetime(2024, 12, 31)
        )
        
        self.assertEqual(event.symbol, "AAPL")
        self.assertEqual(event.period_end, datetime(2024, 12, 31))
        self.assertEqual(event.event_type, "fundamental")
    
    def test_ai_event(self):
        """Test AIEvent."""
        event = AIEvent(agent_id="analyzer-1", query_id=uuid4())
        
        self.assertEqual(event.agent_id, "analyzer-1")
        self.assertEqual(event.event_type, "ai")
    
    def test_system_event(self):
        """Test SystemEvent."""
        event = SystemEvent(
            service_name="trading-engine",
            event_category="HEALTH"
        )
        
        self.assertEqual(event.service_name, "trading-engine")
        self.assertEqual(event.event_category, "HEALTH")
        self.assertEqual(event.event_type, "system")
    
    def test_order_created_event(self):
        """Test OrderCreatedEvent."""
        event = OrderCreatedEvent(
            order_id=uuid4(),
            user_id=uuid4(),
            symbol="AAPL",
            order_type="LIMIT",
            side="BUY",
            quantity=100,
            price=150.0
        )
        
        self.assertEqual(event.symbol, "AAPL")
        self.assertEqual(event.order_type, "LIMIT")
        self.assertEqual(event.side, "BUY")
        self.assertEqual(event.quantity, 100)
        self.assertEqual(event.price, 150.0)
        self.assertEqual(event.event_type, "trading.order.created")
    
    def test_order_filled_event(self):
        """Test OrderFilledEvent."""
        event = OrderFilledEvent(
            order_id=uuid4(),
            user_id=uuid4(),
            symbol="AAPL",
            filled_quantity=100,
            fill_price=150.50,
            commission=0.99
        )
        
        self.assertEqual(event.filled_quantity, 100)
        self.assertEqual(event.fill_price, 150.50)
        self.assertEqual(event.commission, 0.99)
        self.assertEqual(event.event_type, "trading.order.filled")
    
    def test_position_opened_event(self):
        """Test PositionOpenedEvent."""
        event = PositionOpenedEvent(
            order_id=uuid4(),
            user_id=uuid4(),
            symbol="TSLA",
            quantity=50,
            entry_price=850.0
        )
        
        self.assertEqual(event.symbol, "TSLA")
        self.assertEqual(event.quantity, 50)
        self.assertEqual(event.entry_price, 850.0)
        self.assertEqual(event.event_type, "trading.position.opened")
    
    def test_signal_generated_event(self):
        """Test SignalGeneratedEvent."""
        indicators = {"rsi": 75, "macd": 0.5}
        event = SignalGeneratedEvent(
            order_id=uuid4(),
            user_id=uuid4(),
            symbol="MSFT",
            signal_type="BUY",
            strength=0.85,
            reasoning="RSI overbought reversal signal",
            indicators=indicators
        )
        
        self.assertEqual(event.symbol, "MSFT")
        self.assertEqual(event.signal_type, "BUY")
        self.assertEqual(event.strength, 0.85)
        self.assertEqual(event.indicators, indicators)
        self.assertEqual(event.event_type, "trading.signal.generated")
    
    def test_fundamental_data_updated_event(self):
        """Test FundamentalDataUpdatedEvent."""
        data = {"pe_ratio": 25.5, "revenue": "1000000000"}
        event = FundamentalDataUpdatedEvent(
            symbol="AAPL",
            period_end=datetime(2024, 9, 30),
            data_type="RATIO",
            data=data
        )
        
        self.assertEqual(event.data_type, "RATIO")
        self.assertEqual(event.data, data)
        self.assertEqual(event.event_type, "fundamental.data.updated")
    
    def test_risk_limit_breached_event(self):
        """Test RiskLimitBreachedEvent."""
        event = RiskLimitBreachedEvent(
            severity="CRITICAL",
            alert_type="position_limit",
            limit_type="max_position_size",
            current_value=1100000.0,
            limit_value=1000000.0
        )
        
        self.assertEqual(event.limit_type, "max_position_size")
        self.assertEqual(event.current_value, 1100000.0)
        self.assertEqual(event.limit_value, 1000000.0)
        self.assertEqual(event.event_type, "risk.limit.breached")


@unittest.skipIf(not LIBS_AVAILABLE, "libs modules not available")
class TestJSONSerializer(unittest.TestCase):
    """Tests for JSONSerializer."""

    def test_serialize_event(self):
        from libs.common.events.serializers import JSONSerializer
        event = MarketDataEvent(
            symbol="AAPL",
            exchange="SMART",
        )
        result = JSONSerializer.serialize(event)
        self.assertIsInstance(result, bytes)
        self.assertIn(b"AAPL", result)

    def test_deserialize_event(self):
        import json
        from libs.common.events.serializers import JSONSerializer
        data = json.dumps({
            "symbol": "AAPL",
            "exchange": "SMART",
            "event_type": "market_data",
        }).encode("utf-8")
        result = JSONSerializer.deserialize(data, MarketDataEvent)
        self.assertEqual(result.symbol, "AAPL")
        self.assertEqual(result.exchange, "SMART")

    def test_serialize_deserialize_roundtrip(self):
        from libs.common.events.serializers import JSONSerializer
        event = MarketDataEvent(
            symbol="GOOG",
            exchange="NASDAQ",
        )
        serialized = JSONSerializer.serialize(event)
        deserialized = JSONSerializer.deserialize(serialized, MarketDataEvent)
        self.assertEqual(deserialized.symbol, event.symbol)
        self.assertEqual(deserialized.exchange, event.exchange)

    def test_avro_serializer_not_implemented(self):
        from libs.common.events.serializers import AvroSerializer
        serializer = AvroSerializer(schema_registry_url="http://localhost:8081")
        event = MarketDataEvent(symbol="AAPL", exchange="SMART")
        with self.assertRaises(NotImplementedError):
            serializer.serialize(event, schema_id=1)
        with self.assertRaises(NotImplementedError):
            serializer.deserialize(b"data", MarketDataEvent)


if __name__ == '__main__':
    unittest.main()
