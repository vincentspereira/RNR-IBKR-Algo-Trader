"""Test suite for base adapter abstract classes."""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from core_trading.adapters.base import (
    AdapterConfig,
    AdapterType,
    BaseAdapter,
    BaseBrokerAdapter,
    BaseDataFeedAdapter,
    BaseDatabaseAdapter,
    ConnectionStatus,
    HealthCheck,
)


# --- Concrete test implementations ---

class ConcreteAdapter(BaseAdapter):
    """Concrete adapter for testing."""

    async def connect(self) -> bool:
        self._set_status(ConnectionStatus.CONNECTED)
        return True

    async def disconnect(self) -> bool:
        self._set_status(ConnectionStatus.DISCONNECTED)
        return True

    async def health_check(self) -> HealthCheck:
        return HealthCheck(
            status=self._status,
            timestamp=datetime.now(),
            latency_ms=1.0,
        )


class ConcreteBrokerAdapter(BaseBrokerAdapter):
    """Concrete broker adapter for testing."""

    async def connect(self): return True
    async def disconnect(self): return True
    async def health_check(self): return HealthCheck(status=ConnectionStatus.CONNECTED, timestamp=datetime.now())
    async def place_order(self, order_data): return {"order_id": "1"}
    async def cancel_order(self, order_id): return True
    async def get_order_status(self, order_id): return {"status": "filled"}
    async def get_positions(self): return []
    async def get_account_info(self): return {"balance": 100000}
    async def get_portfolio_value(self): return 100000.0


class ConcreteDataFeedAdapter(BaseDataFeedAdapter):
    """Concrete data feed adapter for testing."""

    async def connect(self): return True
    async def disconnect(self): return True
    async def health_check(self): return HealthCheck(status=ConnectionStatus.CONNECTED, timestamp=datetime.now())
    async def subscribe_real_time(self, symbols): yield {"symbol": symbols[0], "price": 100.0}
    async def get_historical_data(self, symbol, start_date, end_date, timeframe): return []
    async def get_quote(self, symbol): return {"last": 150.0}
    async def search_symbols(self, query): return []


class ConcreteDatabaseAdapter(BaseDatabaseAdapter):
    """Concrete database adapter for testing."""

    async def connect(self): return True
    async def disconnect(self): return True
    async def health_check(self): return HealthCheck(status=ConnectionStatus.CONNECTED, timestamp=datetime.now())
    async def execute_query(self, query, params=None): return []
    async def insert_data(self, table, data): return True
    async def update_data(self, table, data, where_clause): return True
    async def delete_data(self, table, where_clause): return True
    async def create_table(self, table_name, schema): return True


# --- Tests ---

class TestConnectionStatusEnum:
    def test_all_status_values(self):
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.CONNECTING.value == "connecting"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.RECONNECTING.value == "reconnecting"
        assert ConnectionStatus.ERROR.value == "error"
        assert ConnectionStatus.MAINTENANCE.value == "maintenance"


class TestAdapterTypeEnum:
    def test_all_type_values(self):
        assert AdapterType.BROKER.value == "broker"
        assert AdapterType.DATA_FEED.value == "data_feed"
        assert AdapterType.DATABASE.value == "database"


class TestAdapterConfig:
    def test_config_defaults(self):
        config = AdapterConfig(name="test", adapter_type=AdapterType.BROKER)
        assert config.name == "test"
        assert config.enabled is True
        assert config.auto_reconnect is True
        assert config.max_reconnect_attempts == 5
        assert config.credentials == {}

    def test_config_custom(self):
        config = AdapterConfig(
            name="custom",
            adapter_type=AdapterType.DATABASE,
            enabled=False,
            max_reconnect_attempts=10,
        )
        assert config.enabled is False
        assert config.max_reconnect_attempts == 10


class TestHealthCheckDataclass:
    def test_health_check_creation(self):
        hc = HealthCheck(
            status=ConnectionStatus.CONNECTED,
            timestamp=datetime.now(),
            latency_ms=5.0,
        )
        assert hc.status == ConnectionStatus.CONNECTED
        assert hc.latency_ms == 5.0
        assert hc.error_message is None
        assert hc.metadata == {}


class TestBaseAdapter:
    @pytest.fixture
    def adapter(self):
        config = AdapterConfig(name="test_adapter", adapter_type=AdapterType.BROKER)
        return ConcreteAdapter(config)

    def test_initial_status_disconnected(self, adapter):
        assert adapter.status == ConnectionStatus.DISCONNECTED

    def test_is_connected_false_initially(self, adapter):
        assert adapter.is_connected is False

    def test_metrics_empty_initially(self, adapter):
        assert adapter.metrics == {}

    @pytest.mark.asyncio
    async def test_connect_sets_status(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect_sets_status(self, adapter):
        await adapter.connect()
        await adapter.disconnect()
        assert adapter.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_health_check(self, adapter):
        hc = await adapter.health_check()
        assert isinstance(hc, HealthCheck)
        assert hc.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_success(self, adapter):
        await adapter.connect()
        result = await adapter.reconnect()
        assert result is True
        assert adapter._reconnect_count == 0

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts_exceeded(self, adapter):
        adapter._reconnect_count = adapter.config.max_reconnect_attempts
        result = await adapter.reconnect()
        assert result is False

    def test_register_callback(self, adapter):
        callback = MagicMock()
        adapter.register_callback("test_event", callback)
        assert "test_event" in adapter._callbacks
        assert callback in adapter._callbacks["test_event"]

    def test_emit_event(self, adapter):
        callback = MagicMock()
        adapter.register_callback("test_event", callback)
        adapter._emit_event("test_event", {"key": "value"})
        callback.assert_called_once_with({"key": "value"})

    def test_emit_event_no_callbacks(self, adapter):
        # Should not raise
        adapter._emit_event("nonexistent_event", {"data": 123})

    def test_emit_event_callback_exception_caught(self, adapter):
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        good_callback = MagicMock()
        adapter.register_callback("test", bad_callback)
        adapter.register_callback("test", good_callback)
        adapter._emit_event("test", None)
        good_callback.assert_called_once()

    def test_update_metrics(self, adapter):
        adapter._update_metrics("requests", 42)
        assert adapter.metrics["requests"] == 42
        assert "last_updated" in adapter.metrics

    def test_set_status_emits_event(self, adapter):
        callback = MagicMock()
        adapter.register_callback("status_changed", callback)
        adapter._set_status(ConnectionStatus.CONNECTED)
        callback.assert_called_once()
        data = callback.call_args[0][0]
        assert data["new_status"] == ConnectionStatus.CONNECTED

    def test_set_status_no_event_when_same(self, adapter):
        callback = MagicMock()
        adapter.register_callback("status_changed", callback)
        adapter._set_status(ConnectionStatus.DISCONNECTED)  # same as initial
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_context_manager(self, adapter):
        async with adapter.connection_context() as a:
            assert a.is_connected is True
        assert adapter.status == ConnectionStatus.DISCONNECTED


class TestAbstractMethods:
    def test_base_adapter_cannot_instantiate(self):
        config = AdapterConfig(name="test", adapter_type=AdapterType.BROKER)
        with pytest.raises(TypeError):
            BaseAdapter(config)

    def test_base_broker_adapter_cannot_instantiate(self):
        config = AdapterConfig(name="test", adapter_type=AdapterType.BROKER)
        with pytest.raises(TypeError):
            BaseBrokerAdapter(config)

    def test_base_data_feed_adapter_cannot_instantiate(self):
        config = AdapterConfig(name="test", adapter_type=AdapterType.DATA_FEED)
        with pytest.raises(TypeError):
            BaseDataFeedAdapter(config)

    def test_base_database_adapter_cannot_instantiate(self):
        config = AdapterConfig(name="test", adapter_type=AdapterType.DATABASE)
        with pytest.raises(TypeError):
            BaseDatabaseAdapter(config)


class TestConcreteBrokerAdapter:
    @pytest.fixture
    def broker(self):
        config = AdapterConfig(name="broker", adapter_type=AdapterType.BROKER)
        return ConcreteBrokerAdapter(config)

    @pytest.mark.asyncio
    async def test_place_order(self, broker):
        result = await broker.place_order({"symbol": "AAPL", "quantity": 10})
        assert "order_id" in result

    @pytest.mark.asyncio
    async def test_cancel_order(self, broker):
        result = await broker.cancel_order("1")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_positions(self, broker):
        result = await broker.get_positions()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_account_info(self, broker):
        result = await broker.get_account_info()
        assert "balance" in result

    @pytest.mark.asyncio
    async def test_get_portfolio_value(self, broker):
        result = await broker.get_portfolio_value()
        assert result == 100000.0


class TestConcreteDataFeedAdapter:
    @pytest.fixture
    def feed(self):
        config = AdapterConfig(name="feed", adapter_type=AdapterType.DATA_FEED)
        return ConcreteDataFeedAdapter(config)

    @pytest.mark.asyncio
    async def test_get_quote(self, feed):
        result = await feed.get_quote("AAPL")
        assert "last" in result

    @pytest.mark.asyncio
    async def test_search_symbols(self, feed):
        result = await feed.search_symbols("AAPL")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_historical_data(self, feed):
        result = await feed.get_historical_data("AAPL", datetime.now(), datetime.now(), "1d")
        assert isinstance(result, list)


class TestConcreteDatabaseAdapter:
    @pytest.fixture
    def db(self):
        config = AdapterConfig(name="db", adapter_type=AdapterType.DATABASE)
        return ConcreteDatabaseAdapter(config)

    @pytest.mark.asyncio
    async def test_execute_query(self, db):
        result = await db.execute_query("SELECT 1")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_insert_data(self, db):
        result = await db.insert_data("table", {"key": "value"})
        assert result is True

    @pytest.mark.asyncio
    async def test_update_data(self, db):
        result = await db.update_data("table", {"key": "value"}, {"id": 1})
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_data(self, db):
        result = await db.delete_data("table", {"id": 1})
        assert result is True

    @pytest.mark.asyncio
    async def test_create_table(self, db):
        result = await db.create_table("test", {"id": "INTEGER"})
        assert result is True
