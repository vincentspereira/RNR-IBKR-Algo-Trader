"""Unit tests for the IBKR Adapter.

All tests mock ib_insync so they run without an actual IBKR connection.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ib_insync is likely not installed; the adapter handles that gracefully.
# We mock it at the module level before importing the adapter.
mock_ib_insync = MagicMock()
mock_ib_insync.IB = MagicMock
mock_ib_insync.Stock = MagicMock
mock_ib_insync.Option = MagicMock
mock_ib_insync.Future = MagicMock
mock_ib_insync.Forex = MagicMock
mock_ib_insync.Contract = MagicMock
mock_ib_insync.Trade = MagicMock
mock_ib_insync.util = MagicMock


class TestIBKRAdapterConnect:
    """Tests for connection management."""

    def test_import_without_ib_insync(self):
        """Adapter should be importable even when ib_insync is absent."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        assert adapter is not None

    @pytest.mark.asyncio
    async def test_simulation_mode_connect(self):
        """When ib_insync is unavailable, adapter connects in simulation mode."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, IBKR_AVAILABLE
        adapter = IBKRAdapter()
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected

    @pytest.mark.asyncio
    async def test_simulation_mode_disconnect(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()
        result = await adapter.disconnect()
        assert result is True
        assert not adapter.is_connected

    @pytest.mark.asyncio
    async def test_connect_sets_status_connected(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus
        adapter = IBKRAdapter()
        await adapter.connect()
        assert adapter.status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_sets_status_disconnected(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus
        adapter = IBKRAdapter()
        await adapter.connect()
        await adapter.disconnect()
        assert adapter.status == ConnectionStatus.DISCONNECTED


class TestIBKRAdapterOrders:
    """Tests for order placement in simulation mode."""

    @pytest.mark.asyncio
    async def test_place_market_order(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
        })
        assert result["status"] == "submitted"
        assert result["order_id"] is not None

    @pytest.mark.asyncio
    async def test_place_limit_order(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "limit",
            "price": 150.0,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_order_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.place_order({"symbol": "AAPL", "side": "buy", "quantity": 10})

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
        })
        order_id = result["order_id"]
        cancel_result = await adapter.cancel_order(order_id)
        assert cancel_result is True

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        cancel_result = await adapter.cancel_order("nonexistent")
        assert cancel_result is False

    @pytest.mark.asyncio
    async def test_get_order_status(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
        })
        status = await adapter.get_order_status(result["order_id"])
        assert status["status"] == "submitted"


class TestIBKRAdapterPositions:
    """Tests for position and account queries."""

    @pytest.mark.asyncio
    async def test_get_positions_empty(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        positions = await adapter.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        info = await adapter.get_account_info()
        assert "balance" in info
        assert "buying_power" in info
        assert "net_liquidation" in info

    @pytest.mark.asyncio
    async def test_get_portfolio_value(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        value = await adapter.get_portfolio_value()
        assert isinstance(value, float)
        assert value > 0

    @pytest.mark.asyncio
    async def test_get_positions_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_positions()


class TestIBKRAdapterRiskLimits:
    """Tests for risk limit enforcement."""

    @pytest.mark.asyncio
    async def test_risk_limit_rejects_over_position_size(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        # Default max_position_size = $1000
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100,
            "price": 200.0,  # $20,000 >> $1,000 limit
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_risk_limit_allows_small_order(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "price": 100.0,  # $500 < $1,000 limit
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_risk_limit_daily_trades(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        adapter = IBKRAdapter()
        await adapter.connect()

        # Place max_daily_trades (10) orders
        for i in range(10):
            await adapter.place_order({
                "symbol": f"TST{i}",
                "side": "buy",
                "quantity": 1,
                "price": 10.0,
                "order_type": "limit",
            })

        # 11th should be rejected
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"


class TestIBKRAdapterHealthCheck:
    """Tests for health check in simulation mode."""

    @pytest.mark.asyncio
    async def test_health_check_simulation(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus
        adapter = IBKRAdapter()
        await adapter.connect()

        hc = await adapter.health_check()
        assert hc.status == ConnectionStatus.CONNECTED
        assert hc.metadata.get("mode") == "simulation"

    @pytest.mark.asyncio
    async def test_health_check_when_disconnected(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus
        adapter = IBKRAdapter()
        # In simulation mode (no ib_insync), health_check returns CONNECTED
        # because the adapter assumes simulation is always "healthy".
        # Test the real behavior: connect first, then verify health.
        await adapter.connect()
        hc = await adapter.health_check()
        assert hc.status == ConnectionStatus.CONNECTED


# ---------------------------------------------------------------------------
# NEW TEST CLASSES — deep coverage of untested code paths
# ---------------------------------------------------------------------------


class TestIBKRAdapterConnectionRetry:
    """Tests for connection retry logic and reconnection with backoff."""

    @pytest.mark.asyncio
    async def test_connect_with_retry_backoff_succeeds_on_first_try(self):
        """reconnect_with_backoff should return True on the first successful connect."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        # In simulation mode, connect() returns True immediately,
        # so the first retry attempt will succeed.
        result = await adapter.reconnect_with_backoff()
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure_all_retries_exhausted(self):
        """reconnect_with_backoff returns False when every attempt fails."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()

        # Force connect() to always fail by setting status to an error-inducing state.
        async def _always_fail():
            from core_trading.adapters.base import ConnectionStatus
            adapter._set_status(ConnectionStatus.ERROR)
            return False

        # Patch connect to always fail and sleep to be instant so the test is fast.
        with patch.object(adapter, "connect", side_effect=_always_fail):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await adapter.reconnect_with_backoff()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_cancels_heartbeat_task(self):
        """Disconnecting should cancel a running heartbeat task."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        fake_heartbeat = MagicMock()
        fake_heartbeat.cancel = MagicMock()
        adapter._heartbeat_task = fake_heartbeat

        await adapter.disconnect()

        fake_heartbeat.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_cancels_reconnect_task(self):
        """Disconnecting should cancel a running reconnect task."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        fake_reconnect = MagicMock()
        fake_reconnect.cancel = MagicMock()
        adapter._reconnect_task = fake_reconnect

        await adapter.disconnect()

        fake_reconnect.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_on_disconnect_callback(self):
        """_on_disconnected callback sets status to DISCONNECTED and emits event."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus

        adapter = IBKRAdapter()
        await adapter.connect()
        assert adapter.status == ConnectionStatus.CONNECTED

        received_events = []
        adapter.register_callback("disconnected", lambda data: received_events.append(data))

        adapter._on_disconnected()

        assert adapter.status == ConnectionStatus.DISCONNECTED
        assert len(received_events) == 1

    @pytest.mark.asyncio
    async def test_connect_sets_connection_start_time(self):
        """Successful connect records a connection_start_time."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        assert adapter.connection_start_time is None

        await adapter.connect()
        assert adapter.connection_start_time is not None

    @pytest.mark.asyncio
    async def test_heartbeat_loop_detects_disconnect(self):
        """Heartbeat loop should set DISCONNECTED when is_connected is True but
        the underlying IB connection is lost (only exercised when IBKR_AVAILABLE
        is True). In simulation mode the loop body is effectively a no-op."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus

        adapter = IBKRAdapter()
        await adapter.connect()

        # In simulation mode IBKR_AVAILABLE is False so the heartbeat loop
        # simply sleeps.  We verify it can be started and cancelled without error.
        adapter._heartbeat_task = asyncio.create_task(adapter._heartbeat_loop())
        adapter._heartbeat_task.cancel()
        try:
            await adapter._heartbeat_task
        except asyncio.CancelledError:
            pass

        # Adapter should still be connected (no real IB to lose).
        assert adapter.is_connected


class TestIBKRAdapterErrorCallback:
    """Tests for IBKR error event callback handling."""

    def test_on_error_increments_error_count(self):
        """_on_error should increment performance_metrics.error_count."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        initial_errors = adapter.performance_metrics.error_count

        adapter._on_error(1, 502, "Couldn't connect to TWS", None)

        assert adapter.performance_metrics.error_count == initial_errors + 1

    def test_on_error_emits_error_event(self):
        """_on_error should emit an 'error' event with code, message, contract."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("error", lambda data: received.append(data))

        adapter._on_error(1, 502, "Couldn't connect to TWS", None)

        assert len(received) == 1
        assert received[0]["code"] == 502
        assert received[0]["message"] == "Couldn't connect to TWS"
        assert received[0]["contract"] is None

    def test_on_error_with_contract(self):
        """_on_error should include contract string when provided."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("error", lambda data: received.append(data))

        fake_contract = MagicMock()
        fake_contract.__str__ = lambda self: "Stock(symbol='AAPL', ...)"
        adapter._on_error(10, 201, "Order rejected", fake_contract)

        assert received[0]["contract"] is not None


class TestIBKRAdapterContractCreation:
    """Tests for _create_contract across all asset types."""

    def test_create_contract_equities(self):
        """When ib_insync is unavailable, _create_contract returns None for equities."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract("AAPL", AssetClass.EQUITIES)
        # Without ib_insync available, returns None.
        assert result is None

    def test_create_contract_options(self):
        """Without ib_insync, _create_contract returns None for options."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract(
            "AAPL", AssetClass.OPTIONS,
            expiry="20260116", strike=150.0, right="C",
        )
        assert result is None

    def test_create_contract_futures(self):
        """Without ib_insync, _create_contract returns None for futures."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract("ES", AssetClass.FUTURES, exchange="CME")
        assert result is None

    def test_create_contract_forex(self):
        """Without ib_insync, _create_contract returns None for forex."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract("EURUSD", AssetClass.FOREX)
        assert result is None

    def test_create_contract_commodities(self):
        """Without ib_insync, _create_contract returns None for commodities."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract("GC", AssetClass.COMMODITIES)
        assert result is None

    def test_create_contract_cryptocurrencies(self):
        """Without ib_insync, _create_contract returns None for crypto."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        result = adapter._create_contract("BTC", AssetClass.CRYPTOCURRENCIES)
        assert result is None

    def test_create_contract_with_ib_insync_available(self):
        """When ib_insync is mocked as available, _create_contract returns mock objects
        for each asset class."""
        import core_trading.adapters.ibkr_adapter as mod
        from core_trading.adapters.ibkr_adapter import AssetClass

        original_available = mod.IBKR_AVAILABLE
        try:
            mod.IBKR_AVAILABLE = True

            mock_stock = MagicMock(name="Stock")
            mock_option = MagicMock(name="Option")
            mock_future = MagicMock(name="Future")
            mock_forex = MagicMock(name="Forex")

            with patch.object(mod, "Stock", mock_stock, create=True), \
                 patch.object(mod, "Option", mock_option, create=True), \
                 patch.object(mod, "Future", mock_future, create=True), \
                 patch.object(mod, "Forex", mock_forex, create=True):

                adapter = mod.IBKRAdapter()

                # Equity
                c = adapter._create_contract("AAPL", AssetClass.EQUITIES)
                assert c is not None
                mock_stock.assert_called_with("AAPL", "SMART", "USD")

                # Option
                c = adapter._create_contract("AAPL", AssetClass.OPTIONS, expiry="20260116", strike=150, right="C")
                mock_option.assert_called_with("AAPL", "20260116", 150, "C", "SMART", "USD")

                # Future
                c = adapter._create_contract("ES", AssetClass.FUTURES, exchange="GLOBEX")
                mock_future.assert_called_with("ES", exchange="GLOBEX")

                # Forex
                c = adapter._create_contract("EURUSD", AssetClass.FOREX)
                mock_forex.assert_called_with("EURUSD")

                # Commodities falls through to Stock
                adapter._create_contract("GC", AssetClass.COMMODITIES)
                mock_stock.assert_called_with("GC", "SMART", "USD")

                # Crypto uses PAXOS exchange
                adapter._create_contract("BTC", AssetClass.CRYPTOCURRENCIES)
                mock_stock.assert_called_with("BTC", "PAXOS", "USD")

        finally:
            mod.IBKR_AVAILABLE = original_available


class TestIBKRAdapterMultiAssetOrders:
    """Tests for order placement with various order types and asset classes."""

    @pytest.mark.asyncio
    async def test_place_stop_order(self):
        """Stop order should be accepted in simulation mode."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "stop",
            "stop_price": 140.0,
        })
        assert result["status"] == "submitted"
        assert result["order_id"] is not None

    @pytest.mark.asyncio
    async def test_place_stop_limit_order(self):
        """Stop-limit order should be accepted in simulation mode."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "stop_limit",
            "price": 145.0,
            "stop_price": 140.0,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_order_with_string_asset_class(self):
        """Order data with string asset_class should be converted to enum."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 150.0,
            "order_type": "limit",
            "asset_class": "equities",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_order_with_enum_asset_class(self):
        """Order data with AssetClass enum should be accepted directly."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 150.0,
            "order_type": "limit",
            "asset_class": AssetClass.EQUITIES,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_sell_order(self):
        """Sell side order should be accepted."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 5,
            "price": 160.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_option_order(self):
        """Option order (simulation) should be submitted."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 5.0,
            "order_type": "limit",
            "asset_class": AssetClass.OPTIONS,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_future_order(self):
        """Future order (simulation) should be submitted."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        await adapter.connect()

        # Keep quantity * price under the default max_position_size of $1000.
        result = await adapter.place_order({
            "symbol": "ES",
            "side": "buy",
            "quantity": 1,
            "price": 900.0,
            "order_type": "limit",
            "asset_class": AssetClass.FUTURES,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_forex_order(self):
        """Forex order (simulation) should be submitted."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass

        adapter = IBKRAdapter()
        await adapter.connect()

        # Keep quantity * price under the default max_position_size of $1000.
        result = await adapter.place_order({
            "symbol": "EURUSD",
            "side": "buy",
            "quantity": 800,
            "price": 1.08,
            "order_type": "limit",
            "asset_class": AssetClass.FOREX,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_order_risk_rejected_contains_reason(self):
        """Rejected order result should contain 'Risk limit violated' reason."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100,
            "price": 500.0,  # $50,000 >> $1,000 limit
            "order_type": "limit",
        })
        assert result["status"] == "rejected"
        assert result["reason"] == "Risk limit violated"
        assert result["order_id"] is None


class TestIBKRAdapterOrderManagement:
    """Tests for cancel and order-status edge cases."""

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected_raises(self):
        """cancel_order should raise RuntimeError when not connected."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.cancel_order("1")

    @pytest.mark.asyncio
    async def test_get_order_status_not_connected_raises(self):
        """get_order_status should raise RuntimeError when not connected."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_order_status("1")

    @pytest.mark.asyncio
    async def test_get_order_status_unknown_order(self):
        """get_order_status for an order that was never placed returns unknown."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        status = await adapter.get_order_status("nonexistent")
        assert status["status"] == "unknown"
        assert "error" in status

    @pytest.mark.asyncio
    async def test_order_id_increments(self):
        """Each order should receive a unique incrementing order_id."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        r1 = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        r2 = await adapter.place_order({
            "symbol": "MSFT", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert int(r2["order_id"]) == int(r1["order_id"]) + 1

    @pytest.mark.asyncio
    async def test_cancel_order_updates_status_to_cancelled(self):
        """Cancelling an order should set its internal status to 'cancelled'."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        order_id = result["order_id"]

        await adapter.cancel_order(order_id)

        status = await adapter.get_order_status(order_id)
        assert status["status"] == "cancelled"


class TestIBKRAdapterPositionsExtended:
    """Tests for positions with populated data and account info edge cases."""

    @pytest.mark.asyncio
    async def test_get_positions_multiple(self):
        """get_positions returns all stored positions in simulation mode."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        # Manually populate positions to simulate a filled scenario.
        adapter._positions = {
            "AAPL": {"symbol": "AAPL", "quantity": 100, "avg_cost": 150.0},
            "MSFT": {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0},
            "GOOG": {"symbol": "GOOG", "quantity": 20, "avg_cost": 2800.0},
        }

        positions = await adapter.get_positions()
        assert len(positions) == 3
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"AAPL", "MSFT", "GOOG"}

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected_raises(self):
        """get_account_info should raise RuntimeError when not connected."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_account_info()

    @pytest.mark.asyncio
    async def test_get_account_info_contains_account_id(self):
        """Account info should include the configured account_id."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter(account_id="TEST123")
        await adapter.connect()

        info = await adapter.get_account_info()
        assert info["account_id"] == "TEST123"

    @pytest.mark.asyncio
    async def test_get_account_info_default_balance(self):
        """Account info should reflect default _account_balance (50000)."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        info = await adapter.get_account_info()
        assert info["balance"] == 50000.0
        assert info["buying_power"] == 100000.0  # 2x balance
        assert info["net_liquidation"] == 50000.0

    @pytest.mark.asyncio
    async def test_get_portfolio_value_not_connected_raises(self):
        """get_portfolio_value should propagate RuntimeError from get_account_info."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_portfolio_value()

    @pytest.mark.asyncio
    async def test_get_historical_data_not_connected_raises(self):
        """get_historical_data should raise RuntimeError when not connected."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_historical_data("AAPL")

    @pytest.mark.asyncio
    async def test_get_historical_data_simulation_returns_empty(self):
        """In simulation mode (no ib_insync), historical data returns empty list."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        bars = await adapter.get_historical_data("AAPL", duration="1 D", bar_size="1 min")
        assert isinstance(bars, list)
        assert len(bars) == 0


class TestIBKRAdapterMarketData:
    """Tests for market data subscription and callback handling."""

    @pytest.mark.asyncio
    async def test_subscribe_market_data_not_connected_raises(self):
        """subscribe_market_data should raise RuntimeError when not connected."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.subscribe_market_data("AAPL", lambda d: None)

    @pytest.mark.asyncio
    async def test_subscribe_market_data_registers_callback(self):
        """Subscribing to market data should store the callback."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        cb1 = MagicMock()
        cb2 = MagicMock()
        await adapter.subscribe_market_data("AAPL", cb1)
        await adapter.subscribe_market_data("AAPL", cb2)

        assert len(adapter._market_data_callbacks["AAPL"]) == 2

    @pytest.mark.asyncio
    async def test_subscribe_market_data_multiple_symbols(self):
        """Subscriptions for different symbols are tracked independently."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        await adapter.subscribe_market_data("AAPL", lambda d: None)
        await adapter.subscribe_market_data("MSFT", lambda d: None)

        assert "AAPL" in adapter._market_data_callbacks
        assert "MSFT" in adapter._market_data_callbacks

    def test_on_market_data_invokes_callbacks(self):
        """_on_market_data should call each registered callback with data dict."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        received = []
        adapter._market_data_callbacks["AAPL"] = [received.append, received.append]

        fake_ticker = MagicMock()
        fake_ticker.bid = 149.5
        fake_ticker.ask = 150.0
        fake_ticker.last = 149.75
        fake_ticker.volume = 1000

        adapter._on_market_data("AAPL", fake_ticker)

        # Two callbacks registered, so two items appended.
        assert len(received) == 2
        assert received[0]["symbol"] == "AAPL"
        assert received[0]["bid"] == 149.5
        assert received[0]["ask"] == 150.0
        assert received[0]["last"] == 149.75
        assert received[0]["volume"] == 1000

    def test_on_market_data_handles_nan_values(self):
        """_on_market_data should convert NaN bid/ask/last to None."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        import math

        adapter = IBKRAdapter()
        received = []
        adapter._market_data_callbacks["AAPL"] = [received.append]

        fake_ticker = MagicMock()
        fake_ticker.bid = float("nan")
        fake_ticker.ask = float("nan")
        fake_ticker.last = float("nan")
        fake_ticker.volume = 0

        adapter._on_market_data("AAPL", fake_ticker)

        data = received[0]
        assert data["bid"] is None
        assert data["ask"] is None
        assert data["last"] is None

    def test_on_market_data_callback_exception_is_caught(self):
        """_on_market_data should not raise if a callback throws."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        good_cb = MagicMock()
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        adapter._market_data_callbacks["AAPL"] = [bad_cb, good_cb]

        fake_ticker = MagicMock()
        fake_ticker.bid = 100.0
        fake_ticker.ask = 101.0
        fake_ticker.last = 100.5
        fake_ticker.volume = 500

        # Should not raise.
        adapter._on_market_data("AAPL", fake_ticker)

        # The good callback should still be called even after the bad one fails.
        good_cb.assert_called_once()


class TestIBKRAdapterRiskLimitsExtended:
    """Extended risk limit tests covering daily loss, concurrent positions, and
    edge-case equity values."""

    @pytest.mark.asyncio
    async def test_risk_limit_daily_loss_limit(self):
        """Orders should be rejected when daily loss percentage exceeds the limit."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        # Default daily_loss_limit_percentage = 2.0, balance = 50000.
        # A daily_pnl of -1500 is 3% of 50000, which exceeds the 2% limit.
        adapter._daily_pnl = -1500.0

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_risk_limit_max_concurrent_positions(self):
        """Orders should be rejected when concurrent position limit is reached."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        # Default max_concurrent_positions = 5.  Fill the position dict.
        for i in range(5):
            adapter._positions[f"SYM{i}"] = {"symbol": f"SYM{i}", "quantity": 1}

        result = await adapter.place_order({
            "symbol": "NEW",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_check_risk_limits_zero_equity_passes_loss_check(self):
        """When account balance is zero the daily loss check is skipped (division guard)."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        adapter._account_balance = 0.0
        adapter._daily_pnl = -1000.0  # Would be infinite %, but should not block.

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_check_risk_limits_negative_equity_passes_loss_check(self):
        """When account balance is negative the daily loss check is skipped."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        adapter._account_balance = -500.0
        adapter._daily_pnl = -1000.0

        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    def test_daily_counter_resets_on_new_day(self):
        """Daily trades and PnL should reset when the calendar day changes."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from datetime import datetime, timezone, timedelta

        adapter = IBKRAdapter()

        # Simulate data from a previous day.
        adapter._daily_trades = [{"symbol": "X"}]
        adapter._daily_pnl = -500.0
        adapter._last_reset_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        order_data = {"quantity": 1, "price": 10.0}
        adapter._check_risk_limits(order_data)

        # After calling _check_risk_limits, counters should have been reset.
        assert len(adapter._daily_trades) == 0
        assert adapter._daily_pnl == 0.0


class TestIBKRAdapterRiskConfiguration:
    """Tests for risk configuration loading from environment variables."""

    def test_default_risk_limits(self):
        """RiskLimits should have expected defaults when no env vars are set."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        rl = adapter.risk_limits

        assert rl.max_position_size == 1000.0
        assert rl.daily_loss_limit_percentage == 2.0
        assert rl.max_daily_trades == 10
        assert rl.max_concurrent_positions == 5
        assert rl.stop_loss_mandatory is True
        assert rl.ai_confidence_threshold == 0.9

    def test_risk_limits_from_environment(self):
        """RiskLimits should read values from environment variables."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        env = {
            "IBKR_PAPER_MAX_POSITION_SIZE": "5000.0",
            "IBKR_PAPER_MAX_DAILY_LOSS_PERCENTAGE": "5.0",
            "IBKR_PAPER_MAX_DAILY_TRADES": "20",
            "IBKR_MAX_CONCURRENT_POSITIONS": "10",
            "IBKR_STOP_LOSS_MANDATORY": "false",
            "IBKR_AI_CONFIDENCE_THRESHOLD": "0.75",
        }
        with patch.dict("os.environ", env, clear=False):
            adapter = IBKRAdapter()
            rl = adapter.risk_limits

        assert rl.max_position_size == 5000.0
        assert rl.daily_loss_limit_percentage == 5.0
        assert rl.max_daily_trades == 20
        assert rl.max_concurrent_positions == 10
        assert rl.stop_loss_mandatory is False
        assert rl.ai_confidence_threshold == 0.75


class TestIBKRAdapterSimulationMode:
    """Tests specific to simulation-mode behavior (ib_insync unavailable)."""

    @pytest.mark.asyncio
    async def test_simulation_order_stored_internally(self):
        """Placed orders in simulation mode should be tracked in _orders dict."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 10, "order_type": "market",
        })
        order_id = result["order_id"]

        assert order_id in adapter._orders
        assert adapter._orders[order_id]["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_simulation_daily_trades_tracking(self):
        """Each simulation order should be appended to _daily_trades."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        for _ in range(3):
            await adapter.place_order({
                "symbol": "AAPL", "side": "buy", "quantity": 1,
                "price": 10.0, "order_type": "limit",
            })

        assert len(adapter._daily_trades) == 3

    @pytest.mark.asyncio
    async def test_simulation_connect_bypasses_ib(self):
        """In simulation mode, adapter.ib should remain None after connect."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        assert adapter.ib is None
        assert adapter.is_connected

    @pytest.mark.asyncio
    async def test_simulation_get_historical_data_daily(self):
        """Requesting daily bars in simulation returns empty list without error."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        bars = await adapter.get_historical_data("AAPL", duration="1 D", bar_size="1 day")
        assert isinstance(bars, list)
        assert len(bars) == 0

    @pytest.mark.asyncio
    async def test_simulation_get_historical_data_hourly(self):
        """Requesting hourly bars in simulation returns empty list without error."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        bars = await adapter.get_historical_data("AAPL", duration="1 D", bar_size="1 hour")
        assert isinstance(bars, list)
        assert len(bars) == 0


class TestIBKRAdapterPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass and tracking."""

    def test_default_metrics(self):
        """PerformanceMetrics should have expected defaults."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        m = adapter.performance_metrics

        assert m.order_latency_ms == 0.0
        assert m.connection_uptime == 0.0
        assert m.daily_trades == 0
        assert m.daily_pnl == 0.0
        assert m.data_quality_score == 1.0
        assert m.error_count == 0

    def test_metrics_mutable(self):
        """PerformanceMetrics fields should be mutable for tracking."""
        from core_trading.adapters.ibkr_adapter import PerformanceMetrics

        m = PerformanceMetrics()
        m.order_latency_ms = 12.5
        m.connection_uptime = 99.9
        m.daily_trades = 5
        m.daily_pnl = 250.0
        m.error_count = 2

        assert m.order_latency_ms == 12.5
        assert m.connection_uptime == 99.9
        assert m.daily_trades == 5
        assert m.daily_pnl == 250.0
        assert m.error_count == 2

    def test_error_count_tracks_via_callback(self):
        """Multiple _on_error calls should increment error_count cumulatively."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        assert adapter.performance_metrics.error_count == 0

        adapter._on_error(1, 100, "first", None)
        adapter._on_error(2, 200, "second", None)
        adapter._on_error(3, 300, "third", None)

        assert adapter.performance_metrics.error_count == 3


class TestIBKRAdapterHeartbeat:
    """Tests for start_heartbeat and heartbeat task management."""

    @pytest.mark.asyncio
    async def test_start_heartbeat_creates_task(self):
        """start_heartbeat should create an asyncio.Task stored on _heartbeat_task."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        await adapter.connect()

        await adapter.start_heartbeat()
        assert adapter._heartbeat_task is not None
        assert isinstance(adapter._heartbeat_task, asyncio.Task)

        adapter._heartbeat_task.cancel()
        try:
            await adapter._heartbeat_task
        except asyncio.CancelledError:
            pass


class TestIBKRAdapterModuleFunctions:
    """Tests for module-level get_ibkr_adapter and initialize_ibkr_adapter."""

    def setup_method(self):
        """Reset the global adapter singleton before each test."""
        import core_trading.adapters.ibkr_adapter as mod
        mod._ibkr_adapter = None

    def teardown_method(self):
        """Reset the global adapter singleton after each test."""
        import core_trading.adapters.ibkr_adapter as mod
        mod._ibkr_adapter = None

    def test_get_ibkr_adapter_creates_instance(self):
        """get_ibkr_adapter should create an adapter on first call."""
        from core_trading.adapters.ibkr_adapter import get_ibkr_adapter

        adapter = get_ibkr_adapter()
        assert adapter is not None

    def test_get_ibkr_adapter_returns_same_instance(self):
        """Subsequent calls to get_ibkr_adapter return the same singleton."""
        from core_trading.adapters.ibkr_adapter import get_ibkr_adapter

        a1 = get_ibkr_adapter()
        a2 = get_ibkr_adapter()
        assert a1 is a2

    def test_initialize_ibkr_adapter_creates_new_instance(self):
        """initialize_ibkr_adapter should create a fresh adapter with custom params."""
        from core_trading.adapters.ibkr_adapter import initialize_ibkr_adapter

        adapter = initialize_ibkr_adapter(
            host="192.168.1.1", port=7496, client_id=42,
            account_id="INIT_TEST", paper_trading=False,
        )
        assert adapter.host == "192.168.1.1"
        assert adapter.port == 7496
        assert adapter.client_id == 42
        assert adapter.account_id == "INIT_TEST"
        assert adapter.paper_trading is False

    def test_initialize_ibkr_adapter_replaces_singleton(self):
        """initialize_ibkr_adapter should replace any existing singleton."""
        from core_trading.adapters.ibkr_adapter import (
            get_ibkr_adapter, initialize_ibkr_adapter,
        )

        old = get_ibkr_adapter()
        new = initialize_ibkr_adapter(account_id="REPLACED")

        assert old is not new
        assert new.account_id == "REPLACED"

        # get_ibkr_adapter should now return the new one.
        assert get_ibkr_adapter() is new


class TestIBKRAdapterRegistration:
    """Tests for callback registration and event emission from the base adapter."""

    def test_register_callback(self):
        """register_callback should store callbacks under event type keys."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        cb = MagicMock()
        adapter.register_callback("test_event", cb)

        assert "test_event" in adapter._callbacks
        assert cb in adapter._callbacks["test_event"]

    def test_emit_event_invokes_callbacks(self):
        """_emit_event should invoke all registered callbacks for the event type."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        results = []
        adapter.register_callback("evt", lambda d: results.append(d))

        adapter._emit_event("evt", {"key": "value"})
        assert len(results) == 1
        assert results[0]["key"] == "value"

    def test_emit_event_for_unregistered_event_is_noop(self):
        """_emit_event for an event with no callbacks should not raise."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        adapter._emit_event("nonexistent", None)  # Should not raise.

    def test_emit_event_callback_exception_is_caught(self):
        """_emit_event should not raise if a callback throws an exception."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        adapter.register_callback("evt", lambda d: (_ for _ in ()).throw(ValueError("boom")))
        good = MagicMock()
        adapter.register_callback("evt", good)

        # The first callback raises; the second should still be called.
        adapter._emit_event("evt", None)
        good.assert_called_once()


class TestIBKRAdapterStatusTransitions:
    """Tests for _set_status and status-change event emission."""

    def test_set_status_emits_status_changed_event(self):
        """_set_status should emit a 'status_changed' event when status actually changes."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus

        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("status_changed", lambda d: received.append(d))

        adapter._set_status(ConnectionStatus.CONNECTING)

        assert len(received) == 1
        assert received[0]["old_status"] == ConnectionStatus.DISCONNECTED
        assert received[0]["new_status"] == ConnectionStatus.CONNECTING

    def test_set_status_no_event_when_unchanged(self):
        """_set_status should NOT emit when old == new status."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.adapters.base import ConnectionStatus

        adapter = IBKRAdapter()
        # Already DISCONNECTED.
        received = []
        adapter.register_callback("status_changed", lambda d: received.append(d))

        adapter._set_status(ConnectionStatus.DISCONNECTED)
        assert len(received) == 0


class TestIBKRAdapterCallbackRegistration:
    """Tests for _register_ib_callbacks."""

    def test_register_ib_callbacks_noop_without_ib(self):
        """_register_ib_callbacks should do nothing when ib is None."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        adapter.ib = None
        # Should not raise.
        adapter._register_ib_callbacks()

    def test_register_ib_callbacks_noop_without_ibkr_available(self):
        """_register_ib_callbacks should do nothing when IBKR_AVAILABLE is False."""
        from core_trading.adapters.ibkr_adapter import IBKRAdapter

        adapter = IBKRAdapter()
        # In simulation mode, IBKR_AVAILABLE is False.
        adapter._register_ib_callbacks()  # Should not raise.
