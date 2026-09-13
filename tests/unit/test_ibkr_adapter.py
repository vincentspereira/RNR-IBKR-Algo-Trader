"""Unit tests for the IBKR Adapter.

These tests exercise the CURRENT adapter contract (post 2026-05-21
security/honesty remediation):

* The constructor REQUIRES an account id -- either passed explicitly or via the
  ``IBKR_ACCOUNT_ID`` environment variable -- otherwise it raises ``ValueError``.
* There is NO silent simulation fallback.  ``connect()`` raises ``RuntimeError``
  if ``ib_insync`` is not installed, and otherwise drives a real ``ib_insync.IB``
  instance.  Connection failures surface (return ``False`` / raise) rather than
  pretending to be connected.

Every test runs WITHOUT a real TWS/Gateway by patching the module-level ``IB``
symbol with a fake whose ``connectAsync`` is an ``AsyncMock``.  No network, no
sleeps, no real account ids (only the ``DU_TEST_ACCOUNT`` sentinel value).
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core_trading.adapters.ibkr_adapter as mod
from core_trading.adapters.base import ConnectionStatus
from core_trading.adapters.ibkr_adapter import (
    AssetClass,
    IBKRAdapter,
    PerformanceMetrics,
    RiskLimits,
    get_ibkr_adapter,
    initialize_ibkr_adapter,
)

TEST_ACCOUNT = "DU_TEST_ACCOUNT"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _account_env(monkeypatch):
    """Provide an account id for every test so construction never raises.

    Individual tests that exercise the missing-account-id path delete this
    env var themselves via monkeypatch.
    """
    monkeypatch.setenv("IBKR_ACCOUNT_ID", TEST_ACCOUNT)


@pytest.fixture
def fake_ib():
    """A fake ``ib_insync.IB`` instance with the methods the adapter calls.

    ``connectAsync`` is async; ``isConnected`` reports True so subsequent
    health checks and operations see a live connection.  The IBKR event
    objects (``disconnectedEvent`` etc.) support ``+=`` registration.
    """
    ib = MagicMock(name="IBInstance")
    ib.connectAsync = AsyncMock(return_value=True)
    ib.isConnected = MagicMock(return_value=True)
    ib.disconnect = MagicMock()
    # ib_insync Event objects support += ; MagicMock does via __iadd__.
    ib.disconnectedEvent = MagicMock()
    ib.errorEvent = MagicMock()
    ib.execDetailsEvent = MagicMock()
    ib.orderStatusEvent = MagicMock()
    return ib


@pytest.fixture
def patched_ib(fake_ib):
    """Patch the module-level ``IB`` class so ``IB()`` returns ``fake_ib`` and
    ``IBKR_AVAILABLE`` is True.  Yields the fake instance for assertions."""
    ib_class = MagicMock(name="IBClass", return_value=fake_ib)
    with patch.object(mod, "IB", ib_class), \
         patch.object(mod, "IBKR_AVAILABLE", True):
        yield fake_ib


async def _connected_adapter(**kwargs):
    """Build an adapter and drive it to CONNECTED.

    The caller must already have the ``patched_ib`` fixture active so that
    ``IB()`` returns the fake instance instead of opening a real socket.
    """
    adapter = IBKRAdapter(**kwargs)
    result = await adapter.connect()
    assert result is True
    assert adapter.is_connected
    return adapter


# ---------------------------------------------------------------------------
# Constructor / configuration contract
# ---------------------------------------------------------------------------


class TestIBKRAdapterConstruction:
    """Constructor validation and configuration."""

    def test_requires_account_id(self, monkeypatch):
        """Without account_id and without IBKR_ACCOUNT_ID env, raises ValueError."""
        monkeypatch.delenv("IBKR_ACCOUNT_ID", raising=False)
        with pytest.raises(ValueError, match="IBKR_ACCOUNT_ID"):
            IBKRAdapter()

    def test_accepts_explicit_account_id(self, monkeypatch):
        """Explicit account_id satisfies the requirement even with no env var."""
        monkeypatch.delenv("IBKR_ACCOUNT_ID", raising=False)
        adapter = IBKRAdapter(account_id=TEST_ACCOUNT)
        assert adapter.account_id == TEST_ACCOUNT

    def test_reads_account_id_from_env(self, monkeypatch):
        """IBKR_ACCOUNT_ID environment variable is honored."""
        monkeypatch.setenv("IBKR_ACCOUNT_ID", TEST_ACCOUNT)
        adapter = IBKRAdapter()
        assert adapter.account_id == TEST_ACCOUNT

    def test_explicit_account_id_overrides_env(self, monkeypatch):
        """An explicit account_id takes precedence over the env var."""
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU_ENV_ACCOUNT")
        adapter = IBKRAdapter(account_id="DU_EXPLICIT_ACCOUNT")
        assert adapter.account_id == "DU_EXPLICIT_ACCOUNT"

    def test_default_connection_parameters(self):
        """Default host/port/client_id/paper_trading match the contract."""
        adapter = IBKRAdapter()
        assert adapter.host == "127.0.0.1"
        assert adapter.port == 7497
        assert adapter.client_id == 1
        assert adapter.paper_trading is True

    def test_custom_connection_parameters(self):
        """Constructor arguments are stored verbatim."""
        adapter = IBKRAdapter(
            host="10.0.0.5",
            port=7496,
            client_id=7,
            account_id=TEST_ACCOUNT,
            paper_trading=False,
        )
        assert adapter.host == "10.0.0.5"
        assert adapter.port == 7496
        assert adapter.client_id == 7
        assert adapter.paper_trading is False

    def test_starts_disconnected(self):
        """A freshly constructed adapter is DISCONNECTED with no IB handle."""
        adapter = IBKRAdapter()
        assert adapter.status == ConnectionStatus.DISCONNECTED
        assert adapter.is_connected is False
        assert adapter.ib is None
        assert adapter.connection_start_time is None


class TestIBKRAdapterRiskConfiguration:
    """Risk configuration loading from environment variables."""

    def test_default_risk_limits(self, monkeypatch):
        """RiskLimits defaults when no risk env vars are set."""
        for var in (
            "IBKR_PAPER_MAX_POSITION_SIZE",
            "IBKR_PAPER_MAX_DAILY_LOSS_PERCENTAGE",
            "IBKR_PAPER_MAX_DAILY_TRADES",
            "IBKR_MAX_CONCURRENT_POSITIONS",
            "IBKR_STOP_LOSS_MANDATORY",
            "IBKR_AI_CONFIDENCE_THRESHOLD",
        ):
            monkeypatch.delenv(var, raising=False)

        rl = IBKRAdapter().risk_limits
        assert rl.max_position_size == 1000.0
        assert rl.daily_loss_limit_percentage == 2.0
        assert rl.max_daily_trades == 10
        assert rl.max_concurrent_positions == 5
        assert rl.stop_loss_mandatory is True
        assert rl.ai_confidence_threshold == 0.9

    def test_risk_limits_from_environment(self, monkeypatch):
        """RiskLimits reads values from environment variables."""
        monkeypatch.setenv("IBKR_PAPER_MAX_POSITION_SIZE", "5000.0")
        monkeypatch.setenv("IBKR_PAPER_MAX_DAILY_LOSS_PERCENTAGE", "5.0")
        monkeypatch.setenv("IBKR_PAPER_MAX_DAILY_TRADES", "20")
        monkeypatch.setenv("IBKR_MAX_CONCURRENT_POSITIONS", "10")
        monkeypatch.setenv("IBKR_STOP_LOSS_MANDATORY", "false")
        monkeypatch.setenv("IBKR_AI_CONFIDENCE_THRESHOLD", "0.75")

        rl = IBKRAdapter().risk_limits
        assert rl.max_position_size == 5000.0
        assert rl.daily_loss_limit_percentage == 5.0
        assert rl.max_daily_trades == 20
        assert rl.max_concurrent_positions == 10
        assert rl.stop_loss_mandatory is False
        assert rl.ai_confidence_threshold == 0.75


class TestPerformanceMetrics:
    """PerformanceMetrics dataclass."""

    def test_default_metrics(self):
        m = IBKRAdapter().performance_metrics
        assert m.order_latency_ms == 0.0
        assert m.connection_uptime == 0.0
        assert m.daily_trades == 0
        assert m.daily_pnl == 0.0
        assert m.data_quality_score == 1.0
        assert m.error_count == 0

    def test_metrics_mutable(self):
        m = PerformanceMetrics()
        m.order_latency_ms = 12.5
        m.daily_trades = 5
        m.error_count = 2
        assert m.order_latency_ms == 12.5
        assert m.daily_trades == 5
        assert m.error_count == 2

    def test_risk_limits_dataclass_defaults(self):
        rl = RiskLimits()
        assert rl.max_position_size == 1000.0
        assert rl.max_daily_trades == 10


# ---------------------------------------------------------------------------
# Connection contract -- NO silent simulation fallback
# ---------------------------------------------------------------------------


class TestIBKRAdapterConnect:
    """Connection management against the current (honest) contract."""

    @pytest.mark.asyncio
    async def test_connect_raises_when_ib_insync_unavailable(self):
        """connect() must raise RuntimeError -- never silently simulate -- when
        ib_insync is not installed."""
        adapter = IBKRAdapter()
        with patch.object(mod, "IBKR_AVAILABLE", False), \
             pytest.raises(RuntimeError, match="ib_insync is not installed"):
            await adapter.connect()
        assert adapter.status == ConnectionStatus.ERROR

    @pytest.mark.asyncio
    async def test_connect_success_sets_connected(self, patched_ib):
        """A successful connectAsync drives status to CONNECTED."""
        adapter = IBKRAdapter()
        result = await adapter.connect()
        assert result is True
        assert adapter.status == ConnectionStatus.CONNECTED
        patched_ib.connectAsync.assert_awaited_once_with(
            "127.0.0.1", 7497, clientId=1
        )

    @pytest.mark.asyncio
    async def test_connect_uses_configured_host_port_client_id(self, patched_ib):
        """connectAsync is called with the constructor's host/port/clientId."""
        adapter = IBKRAdapter(
            host="10.1.2.3", port=4001, client_id=9, account_id=TEST_ACCOUNT
        )
        await adapter.connect()
        patched_ib.connectAsync.assert_awaited_once_with("10.1.2.3", 4001, clientId=9)

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_connect_records_connection_start_time(self):
        """A successful connect records connection_start_time."""
        adapter = IBKRAdapter()
        assert adapter.connection_start_time is None
        await adapter.connect()
        assert adapter.connection_start_time is not None

    @pytest.mark.asyncio
    async def test_connect_failure_returns_false_sets_error(self, patched_ib):
        """A connectAsync exception surfaces as a failure (False + ERROR status),
        NOT a silent simulated success."""
        patched_ib.connectAsync.side_effect = ConnectionRefusedError("no TWS")
        adapter = IBKRAdapter()
        result = await adapter.connect()
        assert result is False
        assert adapter.status == ConnectionStatus.ERROR
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_registers_ib_callbacks(self, patched_ib):
        """Successful connect wires the IBKR event callbacks.

        ib_insync Event objects use ``+=`` to add handlers. On a MagicMock,
        ``+=`` rebinds the attribute to the ``__iadd__`` return value, so we
        capture the original event mocks before connect and assert their
        ``__iadd__`` was invoked.
        """
        disconnected = patched_ib.disconnectedEvent
        error = patched_ib.errorEvent
        exec_details = patched_ib.execDetailsEvent
        order_status = patched_ib.orderStatusEvent

        adapter = IBKRAdapter()
        await adapter.connect()

        disconnected.__iadd__.assert_called_once()
        error.__iadd__.assert_called_once()
        exec_details.__iadd__.assert_called_once()
        order_status.__iadd__.assert_called_once()

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_disconnect_sets_disconnected(self):
        adapter = await _connected_adapter()
        result = await adapter.disconnect()
        assert result is True
        assert adapter.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_calls_ib_disconnect(self, patched_ib):
        adapter = await _connected_adapter()
        await adapter.disconnect()
        patched_ib.disconnect.assert_called_once()

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_disconnect_cancels_heartbeat_task(self):
        adapter = await _connected_adapter()
        fake_heartbeat = MagicMock()
        adapter._heartbeat_task = fake_heartbeat
        await adapter.disconnect()
        fake_heartbeat.cancel.assert_called_once()

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_disconnect_cancels_reconnect_task(self):
        adapter = await _connected_adapter()
        fake_reconnect = MagicMock()
        adapter._reconnect_task = fake_reconnect
        await adapter.disconnect()
        fake_reconnect.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_never_connected(self):
        """disconnect() is safe when ib is None (never connected)."""
        adapter = IBKRAdapter()
        result = await adapter.disconnect()
        assert result is True
        assert adapter.status == ConnectionStatus.DISCONNECTED


class TestIBKRAdapterHealthCheck:
    """Health check reflects the real underlying IB connection state."""

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_health_check_connected(self):
        adapter = await _connected_adapter()
        hc = await adapter.health_check()
        assert hc.status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_health_check_when_ib_none(self):
        """No IB handle -> health check reports DISCONNECTED with a message."""
        adapter = IBKRAdapter()
        hc = await adapter.health_check()
        assert hc.status == ConnectionStatus.DISCONNECTED
        assert hc.error_message == "Not connected to IBKR"

    @pytest.mark.asyncio
    async def test_health_check_when_ib_lost(self, patched_ib):
        """If the underlying IB reports not connected, health is DISCONNECTED."""
        adapter = await _connected_adapter()
        patched_ib.isConnected.return_value = False
        hc = await adapter.health_check()
        assert hc.status == ConnectionStatus.DISCONNECTED


# ---------------------------------------------------------------------------
# Order placement / cancel / status
# ---------------------------------------------------------------------------


def _make_trade(order_id="1001", status="Submitted", filled=0, remaining=10,
                avg_fill_price=0.0):
    """Build a fake ib_insync Trade as returned by IB.placeOrder."""
    trade = MagicMock(name="Trade")
    trade.order = MagicMock()
    trade.order.orderId = order_id
    trade.orderStatus = MagicMock()
    trade.orderStatus.status = status
    trade.orderStatus.filled = filled
    trade.orderStatus.remaining = remaining
    trade.orderStatus.avgFillPrice = avg_fill_price
    return trade


class TestIBKRAdapterOrders:
    """Order placement through the mocked IB."""

    @pytest.mark.asyncio
    async def test_place_market_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade(order_id="2001")
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "price": 90.0,  # sizing reference (10 * 90 = 900 <= 1000)
        })
        assert result["status"] == "submitted"
        assert result["order_id"] is not None
        assert result["broker_order_id"] == "2001"
        patched_ib.placeOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_limit_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "limit",
            "price": 150.0,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_stop_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "stop",
            "stop_price": 140.0,  # 5 * 140 = 700 <= 1000 (sizing reference)
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_stop_limit_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
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
    async def test_place_sell_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 5,
            "price": 160.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"
        # SELL action mapped onto the ib_insync Order.
        order_arg = patched_ib.placeOrder.call_args.args[1]
        assert order_arg.action == "SELL"

    @pytest.mark.asyncio
    async def test_place_order_with_string_asset_class(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
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
    async def test_place_order_with_enum_asset_class(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 150.0,
            "order_type": "limit",
            "asset_class": AssetClass.OPTIONS,
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_place_order_not_connected_raises(self):
        """Placing an order while disconnected raises RuntimeError."""
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.place_order(
                {"symbol": "AAPL", "side": "buy", "quantity": 10}
            )

    @pytest.mark.asyncio
    async def test_place_order_ib_exception_rejected(self, patched_ib):
        """If IB.placeOrder raises, the order is recorded as rejected."""
        adapter = await _connected_adapter()
        patched_ib.placeOrder.side_effect = RuntimeError("broker boom")
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"
        assert "broker boom" in result["reason"]

    @pytest.mark.asyncio
    async def test_order_id_increments(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
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
    async def test_order_stored_internally(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 10, "order_type": "market",
            "price": 90.0,
        })
        order_id = result["order_id"]
        assert order_id in adapter._orders
        assert adapter._orders[order_id]["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_daily_trades_tracking(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        for _ in range(3):
            await adapter.place_order({
                "symbol": "AAPL", "side": "buy", "quantity": 1,
                "price": 10.0, "order_type": "limit",
            })
        assert len(adapter._daily_trades) == 3


class TestIBKRAdapterOrderManagement:
    """Cancel and order-status behavior."""

    @pytest.mark.asyncio
    async def test_cancel_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 10, "order_type": "market",
            "price": 90.0,
        })
        cancel_result = await adapter.cancel_order(result["order_id"])
        assert cancel_result is True
        patched_ib.cancelOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_order_updates_status(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        order_id = result["order_id"]
        await adapter.cancel_order(order_id)
        assert adapter._orders[order_id]["status"] == "cancelled"

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self):
        adapter = await _connected_adapter()
        cancel_result = await adapter.cancel_order("nonexistent")
        assert cancel_result is False

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.cancel_order("1")

    @pytest.mark.asyncio
    async def test_get_order_status_reads_trade(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade(
            status="Submitted", filled=0, remaining=10, avg_fill_price=0.0
        )
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 10, "order_type": "market",
            "price": 90.0,  # 10 * 90 = 900 <= 1000 sizing limit
        })
        status = await adapter.get_order_status(result["order_id"])
        # status string is lower-cased from the ib_insync OrderStatus.status.
        assert status["status"] == "submitted"
        # BrokerLike contract: consumers read filled_quantity, not "filled".
        assert status["filled_quantity"] == 0
        assert status["avg_fill_price"] == 0.0
        assert status["remaining"] == 10

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_get_order_status_unknown_order(self):
        adapter = await _connected_adapter()
        status = await adapter.get_order_status("nonexistent")
        assert status["status"] == "unknown"
        assert "error" in status

    @pytest.mark.asyncio
    async def test_get_order_status_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_order_status("1")


# ---------------------------------------------------------------------------
# Risk limit enforcement
# ---------------------------------------------------------------------------


class TestIBKRAdapterRiskLimits:
    """Risk limits gate orders before they reach the broker."""

    @pytest.mark.asyncio
    async def test_rejects_over_position_size(self, patched_ib):
        adapter = await _connected_adapter()
        # Default max_position_size = $1000; 100 * $200 = $20,000.
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100,
            "price": 200.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"
        assert result["reason"] == "Risk limit violated"
        assert result["order_id"] is None
        # Broker was never contacted for a rejected order.
        patched_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_small_order(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "price": 100.0,  # $500 < $1000 limit
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_daily_trade_limit(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        for i in range(10):  # default max_daily_trades = 10
            await adapter.place_order({
                "symbol": f"TST{i}", "side": "buy", "quantity": 1,
                "price": 10.0, "order_type": "limit",
            })
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_daily_loss_limit(self):
        adapter = await _connected_adapter()
        # -1500 / 50000 = 3% > 2% default limit.
        adapter._daily_pnl = -1500.0
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_max_concurrent_positions(self):
        adapter = await _connected_adapter()
        for i in range(5):  # default max_concurrent_positions = 5
            adapter._positions[f"SYM{i}"] = {"symbol": f"SYM{i}", "quantity": 1}
        result = await adapter.place_order({
            "symbol": "NEW", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_zero_equity_skips_loss_check(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        adapter._account_balance = 0.0
        adapter._daily_pnl = -1000.0  # would be infinite %, but guarded.
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_negative_equity_skips_loss_check(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.placeOrder.return_value = _make_trade()
        adapter._account_balance = -500.0
        adapter._daily_pnl = -1000.0
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1, "price": 10.0,
            "order_type": "limit",
        })
        assert result["status"] == "submitted"

    def test_daily_counter_resets_on_new_day(self):
        from datetime import UTC, datetime, timedelta

        adapter = IBKRAdapter()
        adapter._daily_trades = [{"symbol": "X"}]
        adapter._daily_pnl = -500.0
        adapter._last_reset_date = (datetime.now(UTC) - timedelta(days=1)).date()

        adapter._check_risk_limits({"quantity": 1, "price": 10.0})

        assert len(adapter._daily_trades) == 0
        assert adapter._daily_pnl == 0.0


# ---------------------------------------------------------------------------
# Positions / account info / portfolio value
# ---------------------------------------------------------------------------


class TestIBKRAdapterPositions:
    """Position and account queries through the mocked IB."""

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.positions.return_value = []
        positions = await adapter.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_positions_populated(self, patched_ib):
        adapter = await _connected_adapter()

        def _pos(symbol, qty, cost):
            p = MagicMock()
            p.contract = MagicMock()
            p.contract.symbol = symbol
            p.position = qty
            p.avgCost = cost
            return p

        patched_ib.positions.return_value = [
            _pos("AAPL", 100, 150.0),
            _pos("MSFT", 50, 300.0),
        ]
        positions = await adapter.get_positions()
        assert len(positions) == 2
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_get_positions_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_positions()

    @pytest.mark.asyncio
    async def test_get_account_info(self, patched_ib):
        adapter = await _connected_adapter(account_id=TEST_ACCOUNT)

        def _av(tag, value):
            v = MagicMock()
            v.tag = tag
            v.value = value
            return v

        patched_ib.accountValues.return_value = [
            _av("TotalCashValue", "12345.0"),
            _av("BuyingPower", "67890.0"),
            _av("NetLiquidation", "55555.0"),
        ]
        info = await adapter.get_account_info()
        assert info["account_id"] == TEST_ACCOUNT
        assert info["balance"] == 12345.0
        assert info["buying_power"] == 67890.0
        assert info["net_liquidation"] == 55555.0
        assert info["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_account_info()

    @pytest.mark.asyncio
    async def test_get_portfolio_value(self, patched_ib):
        adapter = await _connected_adapter()

        def _av(tag, value):
            v = MagicMock()
            v.tag = tag
            v.value = value
            return v

        patched_ib.accountValues.return_value = [_av("NetLiquidation", "99999.0")]
        value = await adapter.get_portfolio_value()
        assert value == 99999.0

    @pytest.mark.asyncio
    async def test_get_portfolio_value_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_portfolio_value()


# ---------------------------------------------------------------------------
# Market data and historical data
# ---------------------------------------------------------------------------


class TestIBKRAdapterMarketData:
    """Market data subscription and callback handling."""

    @pytest.mark.asyncio
    async def test_subscribe_market_data_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.subscribe_market_data("AAPL", lambda _d: None)

    @pytest.mark.asyncio
    async def test_subscribe_market_data_registers_callback(self, patched_ib):
        adapter = await _connected_adapter()
        ticker = MagicMock()
        ticker.updateEvent = MagicMock()
        patched_ib.reqMktData.return_value = ticker

        await adapter.subscribe_market_data("AAPL", MagicMock())
        await adapter.subscribe_market_data("AAPL", MagicMock())
        assert len(adapter._market_data_callbacks["AAPL"]) == 2

    @pytest.mark.asyncio
    async def test_subscribe_market_data_multiple_symbols(self, patched_ib):
        adapter = await _connected_adapter()
        ticker = MagicMock()
        ticker.updateEvent = MagicMock()
        patched_ib.reqMktData.return_value = ticker

        await adapter.subscribe_market_data("AAPL", lambda _d: None)
        await adapter.subscribe_market_data("MSFT", lambda _d: None)
        assert "AAPL" in adapter._market_data_callbacks
        assert "MSFT" in adapter._market_data_callbacks

    def test_on_market_data_invokes_callbacks(self):
        adapter = IBKRAdapter()
        received = []
        adapter._market_data_callbacks["AAPL"] = [received.append, received.append]

        ticker = MagicMock()
        ticker.bid = 149.5
        ticker.ask = 150.0
        ticker.last = 149.75
        ticker.volume = 1000

        adapter._on_market_data("AAPL", ticker)
        assert len(received) == 2
        assert received[0]["symbol"] == "AAPL"
        assert received[0]["bid"] == 149.5
        assert received[0]["ask"] == 150.0
        assert received[0]["last"] == 149.75
        assert received[0]["volume"] == 1000

    def test_on_market_data_handles_nan_values(self):
        adapter = IBKRAdapter()
        received = []
        adapter._market_data_callbacks["AAPL"] = [received.append]

        ticker = MagicMock()
        ticker.bid = float("nan")
        ticker.ask = float("nan")
        ticker.last = float("nan")
        ticker.volume = 0

        adapter._on_market_data("AAPL", ticker)
        data = received[0]
        assert data["bid"] is None
        assert data["ask"] is None
        assert data["last"] is None

    def test_on_market_data_callback_exception_is_caught(self):
        adapter = IBKRAdapter()
        good_cb = MagicMock()
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        adapter._market_data_callbacks["AAPL"] = [bad_cb, good_cb]

        ticker = MagicMock()
        ticker.bid = 100.0
        ticker.ask = 101.0
        ticker.last = 100.5
        ticker.volume = 500

        adapter._on_market_data("AAPL", ticker)  # must not raise
        good_cb.assert_called_once()


class TestIBKRAdapterHistoricalData:
    """Historical OHLCV retrieval."""

    @pytest.mark.asyncio
    async def test_get_historical_data_not_connected_raises(self):
        adapter = IBKRAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_historical_data("AAPL")

    @pytest.mark.asyncio
    async def test_get_historical_data_maps_bars(self, patched_ib):
        adapter = await _connected_adapter()

        def _bar(d, o, h, lo, c, v):
            b = MagicMock()
            b.date = d
            b.open = o
            b.high = h
            b.low = lo
            b.close = c
            b.volume = v
            return b

        patched_ib.reqHistoricalDataAsync = AsyncMock(return_value=[
            _bar("2026-06-01", 100.0, 105.0, 99.0, 104.0, 1000),
            _bar("2026-06-02", 104.0, 106.0, 103.0, 105.0, 1500),
        ])
        bars = await adapter.get_historical_data("AAPL", duration="2 D", bar_size="1 day")
        assert len(bars) == 2
        assert bars[0]["open"] == 100.0
        assert bars[0]["close"] == 104.0
        assert bars[1]["volume"] == 1500

    @pytest.mark.asyncio
    async def test_get_historical_data_exception_returns_empty(self, patched_ib):
        adapter = await _connected_adapter()
        patched_ib.reqHistoricalDataAsync = AsyncMock(side_effect=RuntimeError("boom"))
        bars = await adapter.get_historical_data("AAPL")
        assert bars == []


# ---------------------------------------------------------------------------
# Contract creation (only meaningful when ib_insync symbols are available)
# ---------------------------------------------------------------------------


class TestIBKRAdapterContractCreation:
    """_create_contract dispatches to the correct ib_insync security type."""

    def test_create_contract_all_asset_classes(self):
        mock_stock = MagicMock(name="Stock")
        mock_option = MagicMock(name="Option")
        mock_future = MagicMock(name="Future")
        mock_forex = MagicMock(name="Forex")

        with patch.object(mod, "IBKR_AVAILABLE", True), \
             patch.object(mod, "Stock", mock_stock, create=True), \
             patch.object(mod, "Option", mock_option, create=True), \
             patch.object(mod, "Future", mock_future, create=True), \
             patch.object(mod, "Forex", mock_forex, create=True):

            adapter = IBKRAdapter()

            adapter._create_contract("AAPL", AssetClass.EQUITIES)
            mock_stock.assert_called_with("AAPL", "SMART", "USD")

            adapter._create_contract(
                "AAPL", AssetClass.OPTIONS, expiry="20260116", strike=150, right="C"
            )
            mock_option.assert_called_with(
                "AAPL", "20260116", 150, "C", "SMART", "USD"
            )

            adapter._create_contract("ES", AssetClass.FUTURES, exchange="GLOBEX")
            mock_future.assert_called_with("ES", exchange="GLOBEX")

            adapter._create_contract("EURUSD", AssetClass.FOREX)
            mock_forex.assert_called_with("EURUSD")

            adapter._create_contract("GC", AssetClass.COMMODITIES)
            mock_stock.assert_called_with("GC", "SMART", "USD")

            adapter._create_contract("BTC", AssetClass.CRYPTOCURRENCIES)
            mock_stock.assert_called_with("BTC", "PAXOS", "USD")


# ---------------------------------------------------------------------------
# IBKR event callbacks (error / disconnect / fill / order status routing)
# ---------------------------------------------------------------------------


class TestIBKRAdapterErrorCallback:
    """_on_error event handling."""

    def test_on_error_increments_error_count(self):
        adapter = IBKRAdapter()
        initial = adapter.performance_metrics.error_count
        adapter._on_error(1, 502, "Couldn't connect to TWS", None)
        assert adapter.performance_metrics.error_count == initial + 1

    def test_on_error_emits_error_event(self):
        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("error", lambda d: received.append(d))
        adapter._on_error(1, 502, "Couldn't connect to TWS", None)
        assert len(received) == 1
        assert received[0]["code"] == 502
        assert received[0]["message"] == "Couldn't connect to TWS"
        assert received[0]["contract"] is None

    def test_on_error_with_contract(self):
        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("error", lambda d: received.append(d))
        contract = MagicMock()
        contract.__str__ = lambda _self: "Stock(symbol='AAPL')"
        adapter._on_error(10, 201, "Order rejected", contract)
        assert received[0]["contract"] is not None

    def test_error_count_tracks_cumulatively(self):
        adapter = IBKRAdapter()
        adapter._on_error(1, 100, "first", None)
        adapter._on_error(2, 200, "second", None)
        adapter._on_error(3, 300, "third", None)
        assert adapter.performance_metrics.error_count == 3


class TestIBKRAdapterDisconnectCallback:
    """_on_disconnected event handling."""

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_on_disconnected_sets_status_and_emits(self):
        adapter = await _connected_adapter()
        assert adapter.status == ConnectionStatus.CONNECTED

        received = []
        adapter.register_callback("disconnected", lambda d: received.append(d))
        adapter._on_disconnected()

        assert adapter.status == ConnectionStatus.DISCONNECTED
        assert len(received) == 1


class TestIBKRAdapterFillRouting:
    """on_fill / on_order_status callback registration and routing."""

    def test_on_fill_registers_callback(self):
        adapter = IBKRAdapter()
        cb = AsyncMock()
        adapter.on_fill(cb)
        assert adapter._fill_callback is cb

    def test_on_order_status_registers_callback(self):
        adapter = IBKRAdapter()
        cb = AsyncMock()
        adapter.on_order_status(cb)
        assert adapter._status_callback is cb

    @pytest.mark.asyncio
    async def test_exec_details_routes_to_fill_callback(self):
        adapter = IBKRAdapter()
        calls = []

        async def fill_cb(broker_order_id, qty, price):
            calls.append((broker_order_id, qty, price))

        adapter.on_fill(fill_cb)

        fill = MagicMock()
        fill.execution = MagicMock()
        fill.execution.orderId = 4242
        fill.execution.shares = 10
        fill.execution.price = 150.5

        adapter._on_exec_details(MagicMock(), fill)
        # The callback is scheduled via asyncio.create_task; let it run.
        await asyncio.sleep(0)
        assert calls == [("4242", 10.0, 150.5)]

    @pytest.mark.asyncio
    async def test_order_status_routes_to_status_callback(self):
        adapter = IBKRAdapter()
        calls = []

        async def status_cb(broker_order_id, ib_status):
            calls.append((broker_order_id, ib_status))

        adapter.on_order_status(status_cb)

        trade = MagicMock()
        trade.order = MagicMock()
        trade.order.orderId = 7
        trade.orderStatus = MagicMock()
        trade.orderStatus.status = "Filled"

        adapter._on_order_status(trade)
        await asyncio.sleep(0)
        assert calls == [("7", "Filled")]

    def test_exec_details_no_callback_is_safe(self):
        adapter = IBKRAdapter()
        fill = MagicMock()
        fill.execution = MagicMock()
        fill.execution.orderId = 1
        fill.execution.shares = 1
        fill.execution.price = 1.0
        # No fill callback registered -- must not raise.
        adapter._on_exec_details(MagicMock(), fill)


# ---------------------------------------------------------------------------
# Reconnection / heartbeat
# ---------------------------------------------------------------------------


class TestIBKRAdapterReconnect:
    """reconnect_with_backoff and heartbeat task management."""

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_reconnect_succeeds_first_attempt(self):
        adapter = IBKRAdapter()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await adapter.reconnect_with_backoff()
        assert result is True

    @pytest.mark.asyncio
    async def test_reconnect_all_attempts_fail(self):
        adapter = IBKRAdapter()

        async def _always_fail():
            adapter._set_status(ConnectionStatus.ERROR)
            return False

        with patch.object(adapter, "connect", side_effect=_always_fail), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await adapter.reconnect_with_backoff()
        assert result is False

    @pytest.mark.usefixtures("patched_ib")
    @pytest.mark.asyncio
    async def test_start_heartbeat_creates_task(self):
        adapter = await _connected_adapter()
        await adapter.start_heartbeat()
        assert isinstance(adapter._heartbeat_task, asyncio.Task)
        adapter._heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await adapter._heartbeat_task


# ---------------------------------------------------------------------------
# Base-adapter event machinery
# ---------------------------------------------------------------------------


class TestIBKRAdapterEvents:
    """register_callback / _emit_event / _set_status from the base adapter."""

    def test_register_callback(self):
        adapter = IBKRAdapter()
        cb = MagicMock()
        adapter.register_callback("test_event", cb)
        assert cb in adapter._callbacks["test_event"]

    def test_emit_event_invokes_callbacks(self):
        adapter = IBKRAdapter()
        results = []
        adapter.register_callback("evt", lambda d: results.append(d))
        adapter._emit_event("evt", {"key": "value"})
        assert results == [{"key": "value"}]

    def test_emit_event_unregistered_is_noop(self):
        adapter = IBKRAdapter()
        adapter._emit_event("nonexistent", None)  # must not raise

    def test_emit_event_callback_exception_is_caught(self):
        adapter = IBKRAdapter()
        adapter.register_callback(
            "evt", lambda _d: (_ for _ in ()).throw(ValueError("boom"))
        )
        good = MagicMock()
        adapter.register_callback("evt", good)
        adapter._emit_event("evt", None)
        good.assert_called_once()

    def test_set_status_emits_on_change(self):
        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("status_changed", lambda d: received.append(d))
        adapter._set_status(ConnectionStatus.CONNECTING)
        assert len(received) == 1
        assert received[0]["old_status"] == ConnectionStatus.DISCONNECTED
        assert received[0]["new_status"] == ConnectionStatus.CONNECTING

    def test_set_status_no_event_when_unchanged(self):
        adapter = IBKRAdapter()
        received = []
        adapter.register_callback("status_changed", lambda d: received.append(d))
        adapter._set_status(ConnectionStatus.DISCONNECTED)  # already disconnected
        assert received == []

    def test_register_ib_callbacks_noop_without_ib(self):
        adapter = IBKRAdapter()
        adapter.ib = None
        adapter._register_ib_callbacks()  # must not raise


# ---------------------------------------------------------------------------
# Module-level factory functions
# ---------------------------------------------------------------------------


class TestIBKRAdapterModuleFunctions:
    """get_ibkr_adapter and initialize_ibkr_adapter."""

    def setup_method(self):
        mod._ibkr_adapter = None

    def teardown_method(self):
        mod._ibkr_adapter = None

    def test_get_ibkr_adapter_creates_instance(self):
        adapter = get_ibkr_adapter()
        assert adapter is not None

    def test_get_ibkr_adapter_returns_singleton(self):
        a1 = get_ibkr_adapter()
        a2 = get_ibkr_adapter()
        assert a1 is a2

    def test_initialize_ibkr_adapter_custom_params(self):
        adapter = initialize_ibkr_adapter(
            host="192.168.1.1",
            port=7496,
            client_id=42,
            account_id="DU_INIT_ACCOUNT",
            paper_trading=False,
        )
        assert adapter.host == "192.168.1.1"
        assert adapter.port == 7496
        assert adapter.client_id == 42
        assert adapter.account_id == "DU_INIT_ACCOUNT"
        assert adapter.paper_trading is False

    def test_initialize_ibkr_adapter_replaces_singleton(self):
        old = get_ibkr_adapter()
        new = initialize_ibkr_adapter(account_id="DU_REPLACED")
        assert old is not new
        assert new.account_id == "DU_REPLACED"
        assert get_ibkr_adapter() is new
