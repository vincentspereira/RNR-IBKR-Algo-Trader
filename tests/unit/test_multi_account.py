"""Unit tests for Multi-Account Manager.

Tests cover dataclasses, account context operations, multi-account
registration, order submission, broadcast allocation, aggregate
position/P&L tracking, and health monitoring.
"""

import pytest

from core_trading.accounts.multi_account_manager import (
    AccountContext,
    AccountInfo,
    AccountStatus,
    AggregatePnL,
    AggregatePosition,
    HealthStatus,
    MockAdapter,
    MultiAccountManager,
    OrderRequest,
    OrderResult,
    Position,
)


# ---------------------------------------------------------------------------
# Helper: Mock adapter that returns configurable data
# ---------------------------------------------------------------------------


class MockAdapterWithData(MockAdapter):
    """Mock adapter with configurable positions and account info."""

    def __init__(self, positions=None, account_info=None):
        super().__init__()
        self._positions = positions or []
        self._account_info = account_info or {
            "equity": 100000.0,
            "cash": 50000.0,
            "buying_power": 200000.0,
        }

    async def get_positions(self):
        return self._positions

    async def get_account_info(self):
        return self._account_info


class FailingAdapter(MockAdapter):
    """Mock adapter that raises exceptions."""

    async def get_account_info(self):
        raise ConnectionError("broker unreachable")

    async def get_positions(self):
        raise ConnectionError("broker unreachable")

    async def place_order(self, order):
        raise RuntimeError("order rejected by broker")

    async def health_check(self):
        raise ConnectionError("connection lost")


# ---------------------------------------------------------------------------
# TestDataClasses
# ---------------------------------------------------------------------------


class TestOrderRequest:
    """Tests for OrderRequest dataclass."""

    def test_order_request_creation(self):
        order = OrderRequest(
            symbol="AAPL",
            side="buy",
            quantity=100,
            order_type="limit",
            price=150.0,
        )
        assert order.symbol == "AAPL"
        assert order.side == "buy"
        assert order.quantity == 100
        assert order.order_type == "limit"
        assert order.price == 150.0

    def test_order_request_defaults(self):
        order = OrderRequest(symbol="MSFT", side="sell", quantity=50)
        assert order.order_type == "market"
        assert order.price is None
        assert order.strategy_id is None
        assert order.metadata == {}


class TestOrderResult:
    """Tests for OrderResult dataclass."""

    def test_order_result_creation(self):
        result = OrderResult(
            account_id="ACC001",
            symbol="AAPL",
            side="buy",
            quantity=100,
            status="submitted",
        )
        assert result.account_id == "ACC001"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.quantity == 100
        assert result.status == "submitted"
        assert result.error_message == ""

    def test_order_result_auto_generates_order_id(self):
        result = OrderResult()
        assert len(result.order_id) == 12

    def test_order_result_default_status(self):
        result = OrderResult()
        assert result.status == "submitted"

    def test_order_result_has_utc_timestamp(self):
        result = OrderResult()
        assert result.timestamp.tzinfo is not None


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_cost=145.0,
            market_price=150.0,
            unrealized_pnl=500.0,
        )
        assert pos.symbol == "AAPL"
        assert pos.quantity == 100
        assert pos.avg_cost == 145.0
        assert pos.market_price == 150.0
        assert pos.unrealized_pnl == 500.0

    def test_position_market_value(self):
        pos = Position(symbol="AAPL", quantity=100, avg_cost=145.0, market_price=150.0)
        assert pos.market_value == 15000.0

    def test_position_market_value_zero_quantity(self):
        pos = Position(symbol="AAPL", quantity=0, avg_cost=145.0, market_price=150.0)
        assert pos.market_value == 0.0

    def test_position_market_value_default_price(self):
        pos = Position(symbol="AAPL", quantity=50, avg_cost=100.0)
        assert pos.market_value == 0.0


class TestAccountInfo:
    """Tests for AccountInfo dataclass."""

    def test_account_info_creation(self):
        info = AccountInfo(account_id="ACC001", equity=100000.0, cash=50000.0)
        assert info.account_id == "ACC001"
        assert info.equity == 100000.0
        assert info.cash == 50000.0

    def test_account_info_total_position_value_empty(self):
        info = AccountInfo(account_id="ACC001")
        assert info.total_position_value == 0.0

    def test_account_info_total_position_value_with_positions(self):
        positions = {
            "AAPL": Position(symbol="AAPL", quantity=100, avg_cost=145.0, market_price=150.0),
            "MSFT": Position(symbol="MSFT", quantity=50, avg_cost=300.0, market_price=310.0),
        }
        info = AccountInfo(account_id="ACC001", positions=positions)
        # 100*150 + 50*310 = 15000 + 15500 = 30500
        assert info.total_position_value == 30500.0

    def test_account_info_default_status(self):
        info = AccountInfo(account_id="ACC001")
        assert info.status == AccountStatus.ACTIVE


class TestAggregatePosition:
    """Tests for AggregatePosition dataclass."""

    def test_aggregate_position_creation(self):
        agg = AggregatePosition(
            symbol="AAPL",
            total_quantity=300,
            weighted_avg_cost=148.0,
            total_market_value=45000.0,
            total_unrealized_pnl=600.0,
            account_breakdown={"ACC001": 200, "ACC002": 100},
        )
        assert agg.symbol == "AAPL"
        assert agg.total_quantity == 300
        assert agg.weighted_avg_cost == 148.0
        assert agg.total_market_value == 45000.0
        assert agg.total_unrealized_pnl == 600.0
        assert agg.account_breakdown["ACC001"] == 200
        assert agg.account_breakdown["ACC002"] == 100

    def test_aggregate_position_empty_breakdown(self):
        agg = AggregatePosition(
            symbol="AAPL",
            total_quantity=0,
            weighted_avg_cost=0.0,
            total_market_value=0.0,
            total_unrealized_pnl=0.0,
        )
        assert agg.account_breakdown == {}


class TestAggregatePnL:
    """Tests for AggregatePnL dataclass."""

    def test_aggregate_pnl_creation(self):
        pnl = AggregatePnL(
            total_equity=500000.0,
            total_unrealized_pnl=5000.0,
            total_realized_pnl=2000.0,
            total_market_value=200000.0,
            account_count=3,
        )
        assert pnl.total_equity == 500000.0
        assert pnl.total_unrealized_pnl == 5000.0
        assert pnl.total_realized_pnl == 2000.0
        assert pnl.total_market_value == 200000.0
        assert pnl.account_count == 3

    def test_aggregate_pnl_default_breakdown(self):
        pnl = AggregatePnL(
            total_equity=0.0,
            total_unrealized_pnl=0.0,
            total_realized_pnl=0.0,
            total_market_value=0.0,
            account_count=0,
        )
        assert pnl.account_breakdown == {}


class TestHealthStatus:
    """Tests for HealthStatus dataclass."""

    def test_health_status_creation(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        hs = HealthStatus(
            account_id="ACC001",
            status=AccountStatus.ACTIVE,
            last_heartbeat=now,
            latency_ms=12.5,
        )
        assert hs.account_id == "ACC001"
        assert hs.status == AccountStatus.ACTIVE
        assert hs.last_heartbeat == now
        assert hs.latency_ms == 12.5

    def test_health_status_defaults(self):
        hs = HealthStatus(account_id="ACC001", status=AccountStatus.ERROR)
        assert hs.last_heartbeat is None
        assert hs.latency_ms == 0.0
        assert hs.error_message == ""


# ---------------------------------------------------------------------------
# TestAccountContext
# ---------------------------------------------------------------------------


class TestAccountContext:
    """Tests for AccountContext operations."""

    def test_account_context_creation(self):
        ctx = AccountContext("ACC001")
        assert ctx.account_id == "ACC001"
        assert ctx.status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_account_context_get_info(self):
        positions = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 500.0},
        ]
        adapter = MockAdapterWithData(
            positions=positions,
            account_info={"equity": 150000.0, "cash": 50000.0, "buying_power": 200000.0},
        )
        ctx = AccountContext("ACC001", adapter=adapter)
        info = await ctx.get_info()

        assert info.account_id == "ACC001"
        assert info.equity == 150000.0
        assert info.cash == 50000.0
        assert "AAPL" in info.positions
        assert info.positions["AAPL"].quantity == 100
        assert info.positions["AAPL"].avg_cost == 145.0

    @pytest.mark.asyncio
    async def test_account_context_get_info_failure_sets_error_status(self):
        adapter = FailingAdapter()
        ctx = AccountContext("ACC001", adapter=adapter)
        with pytest.raises(ConnectionError):
            await ctx.get_info()
        assert ctx.status == AccountStatus.ERROR

    @pytest.mark.asyncio
    async def test_account_context_submit_order(self):
        ctx = AccountContext("ACC001")
        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await ctx.submit_order(order)

        assert result.account_id == "ACC001"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.quantity == 100
        assert result.status == "submitted"

    @pytest.mark.asyncio
    async def test_account_context_submit_order_failure(self):
        adapter = FailingAdapter()
        ctx = AccountContext("ACC001", adapter=adapter)
        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await ctx.submit_order(order)

        assert result.status == "failed"
        assert "order rejected by broker" in result.error_message

    @pytest.mark.asyncio
    async def test_account_context_health_check(self):
        ctx = AccountContext("ACC001")
        health = await ctx.health_check()

        assert health.account_id == "ACC001"
        assert health.status == AccountStatus.ACTIVE
        assert health.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_account_context_health_check_failure(self):
        adapter = FailingAdapter()
        ctx = AccountContext("ACC001", adapter=adapter)
        health = await ctx.health_check()

        assert health.status == AccountStatus.ERROR
        assert "connection lost" in health.error_message
        assert ctx.status == AccountStatus.ERROR

    @pytest.mark.asyncio
    async def test_account_context_adapter_property(self):
        custom_adapter = MockAdapter()
        ctx = AccountContext("ACC001", adapter=custom_adapter)
        assert ctx.adapter is custom_adapter


# ---------------------------------------------------------------------------
# TestMultiAccountManager
# ---------------------------------------------------------------------------


class TestMultiAccountManager:
    """Tests for MultiAccountManager."""

    def test_initialization(self):
        manager = MultiAccountManager()
        assert manager.get_account_ids() == []

    @pytest.mark.asyncio
    async def test_register_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        assert "ACC001" in manager.get_account_ids()

    @pytest.mark.asyncio
    async def test_register_account_with_custom_adapter(self):
        adapter = MockAdapterWithData()
        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter)
        account = manager.get_account("ACC001")
        assert account is not None
        assert account.adapter is adapter

    @pytest.mark.asyncio
    async def test_register_account_duplicate_raises(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        with pytest.raises(ValueError, match="already registered"):
            await manager.register_account("ACC001")

    @pytest.mark.asyncio
    async def test_unregister_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        result = manager.unregister_account("ACC001")
        assert result is True
        assert "ACC001" not in manager.get_account_ids()

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self):
        manager = MultiAccountManager()
        result = manager.unregister_account("NONEXISTENT")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        account = manager.get_account("ACC001")
        assert account is not None
        assert account.account_id == "ACC001"

    def test_get_account_nonexistent(self):
        manager = MultiAccountManager()
        assert manager.get_account("MISSING") is None

    @pytest.mark.asyncio
    async def test_get_account_ids(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002")
        ids = manager.get_account_ids()
        assert set(ids) == {"ACC001", "ACC002"}

    @pytest.mark.asyncio
    async def test_submit_order_success(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await manager.submit_order("ACC001", order)

        assert result.account_id == "ACC001"
        assert result.symbol == "AAPL"
        assert result.status == "submitted"

    @pytest.mark.asyncio
    async def test_submit_order_unknown_account(self):
        manager = MultiAccountManager()
        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await manager.submit_order("UNKNOWN", order)

        assert result.status == "rejected"
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_submit_order_suspended_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        # Manually suspend the account
        manager.get_account("ACC001")._status = AccountStatus.SUSPENDED

        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await manager.submit_order("ACC001", order)

        assert result.status == "rejected"
        assert "suspended" in result.error_message

    @pytest.mark.asyncio
    async def test_submit_order_error_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        manager.get_account("ACC001")._status = AccountStatus.ERROR

        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        result = await manager.submit_order("ACC001", order)

        assert result.status == "rejected"
        assert "error" in result.error_message

    @pytest.mark.asyncio
    async def test_broadcast_order(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002")

        order = OrderRequest(symbol="AAPL", side="buy", quantity=200)
        allocation = {"ACC001": 100, "ACC002": 100}
        results = await manager.broadcast_order(order, allocation)

        assert len(results) == 2
        assert results["ACC001"].status == "submitted"
        assert results["ACC002"].status == "submitted"
        assert results["ACC001"].quantity == 100
        assert results["ACC002"].quantity == 100

    @pytest.mark.asyncio
    async def test_broadcast_order_uneven_allocation(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002")

        order = OrderRequest(symbol="MSFT", side="sell", quantity=300)
        allocation = {"ACC001": 200, "ACC002": 100}
        results = await manager.broadcast_order(order, allocation)

        assert results["ACC001"].quantity == 200
        assert results["ACC002"].quantity == 100

    @pytest.mark.asyncio
    async def test_broadcast_order_partial_failure(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002")
        # Make ACC002 use a failing adapter
        manager.get_account("ACC002")._adapter = FailingAdapter()

        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        allocation = {"ACC001": 50, "ACC002": 50}
        results = await manager.broadcast_order(order, allocation)

        assert results["ACC001"].status == "submitted"
        assert results["ACC002"].status == "failed"

    @pytest.mark.asyncio
    async def test_broadcast_order_unknown_account(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")

        order = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        allocation = {"ACC001": 50, "UNKNOWN": 50}
        results = await manager.broadcast_order(order, allocation)

        assert results["ACC001"].status == "submitted"
        assert results["UNKNOWN"].status == "rejected"

    @pytest.mark.asyncio
    async def test_get_aggregate_positions(self):
        positions_acc1 = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 500.0},
            {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0, "market_price": 310.0, "unrealized_pnl": 500.0},
        ]
        positions_acc2 = [
            {"symbol": "AAPL", "quantity": 200, "avg_cost": 148.0, "market_price": 150.0, "unrealized_pnl": 400.0},
        ]
        adapter1 = MockAdapterWithData(positions=positions_acc1)
        adapter2 = MockAdapterWithData(positions=positions_acc2)

        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter1)
        await manager.register_account("ACC002", adapter=adapter2)

        agg = await manager.get_aggregate_positions()

        assert "AAPL" in agg
        assert "MSFT" in agg
        assert agg["AAPL"].total_quantity == 300  # 100 + 200
        assert agg["AAPL"].total_unrealized_pnl == 900.0  # 500 + 400
        assert agg["MSFT"].total_quantity == 50
        # Weighted avg cost for AAPL: (145*100 + 148*200) / 300 = (14500 + 29600) / 300 = 147.0
        assert agg["AAPL"].weighted_avg_cost == pytest.approx(147.0)
        assert agg["AAPL"].account_breakdown == {"ACC001": 100, "ACC002": 200}

    @pytest.mark.asyncio
    async def test_get_aggregate_positions_empty(self):
        manager = MultiAccountManager()
        agg = await manager.get_aggregate_positions()
        assert agg == {}

    @pytest.mark.asyncio
    async def test_get_aggregate_positions_no_positions(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")  # MockAdapter returns empty positions
        agg = await manager.get_aggregate_positions()
        assert agg == {}

    @pytest.mark.asyncio
    async def test_get_aggregate_positions_with_failing_account(self):
        positions = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 500.0},
        ]
        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=MockAdapterWithData(positions=positions))
        await manager.register_account("ACC002", adapter=FailingAdapter())

        agg = await manager.get_aggregate_positions()
        # ACC001 should still return data; ACC002 should be skipped
        assert "AAPL" in agg
        assert agg["AAPL"].total_quantity == 100

    @pytest.mark.asyncio
    async def test_get_aggregate_pnl(self):
        positions_acc1 = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 500.0},
        ]
        positions_acc2 = [
            {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0, "market_price": 310.0, "unrealized_pnl": 500.0},
        ]
        adapter1 = MockAdapterWithData(
            positions=positions_acc1,
            account_info={"equity": 150000.0, "cash": 50000.0, "buying_power": 200000.0},
        )
        adapter2 = MockAdapterWithData(
            positions=positions_acc2,
            account_info={"equity": 200000.0, "cash": 80000.0, "buying_power": 300000.0},
        )

        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter1)
        await manager.register_account("ACC002", adapter=adapter2)

        pnl = await manager.get_aggregate_pnl()

        assert pnl.total_equity == 350000.0  # 150000 + 200000
        assert pnl.total_unrealized_pnl == 1000.0  # 500 + 500
        assert pnl.account_count == 2
        assert pnl.account_breakdown["ACC001"] == 500.0
        assert pnl.account_breakdown["ACC002"] == 500.0

    @pytest.mark.asyncio
    async def test_get_aggregate_pnl_empty(self):
        manager = MultiAccountManager()
        pnl = await manager.get_aggregate_pnl()

        assert pnl.total_equity == 0.0
        assert pnl.total_unrealized_pnl == 0.0
        assert pnl.account_count == 0
        assert pnl.account_breakdown == {}

    @pytest.mark.asyncio
    async def test_get_aggregate_pnl_with_failing_account(self):
        adapter1 = MockAdapterWithData(
            account_info={"equity": 150000.0, "cash": 50000.0, "buying_power": 200000.0},
        )
        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter1)
        await manager.register_account("ACC002", adapter=FailingAdapter())

        pnl = await manager.get_aggregate_pnl()
        # Only ACC001 should contribute
        assert pnl.total_equity == 150000.0
        assert pnl.account_count == 2  # Both accounts are registered
        assert "ACC001" in pnl.account_breakdown
        assert "ACC002" not in pnl.account_breakdown

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002")

        health = await manager.health_check_all()

        assert len(health) == 2
        assert health["ACC001"].status == AccountStatus.ACTIVE
        assert health["ACC002"].status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_health_check_all_empty(self):
        manager = MultiAccountManager()
        health = await manager.health_check_all()
        assert health == {}

    @pytest.mark.asyncio
    async def test_health_check_all_with_failure(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        await manager.register_account("ACC002", adapter=FailingAdapter())

        health = await manager.health_check_all()

        assert health["ACC001"].status == AccountStatus.ACTIVE
        assert health["ACC002"].status == AccountStatus.ERROR
        assert "connection lost" in health["ACC002"].error_message

    @pytest.mark.asyncio
    async def test_multiple_accounts_full_workflow(self):
        """End-to-end test: register, submit orders, aggregate, health check."""
        positions_acc1 = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 500.0},
        ]
        positions_acc2 = [
            {"symbol": "AAPL", "quantity": 200, "avg_cost": 148.0, "market_price": 150.0, "unrealized_pnl": 400.0},
            {"symbol": "TSLA", "quantity": 50, "avg_cost": 200.0, "market_price": 210.0, "unrealized_pnl": 500.0},
        ]
        adapter1 = MockAdapterWithData(
            positions=positions_acc1,
            account_info={"equity": 150000.0, "cash": 50000.0, "buying_power": 200000.0},
        )
        adapter2 = MockAdapterWithData(
            positions=positions_acc2,
            account_info={"equity": 250000.0, "cash": 100000.0, "buying_power": 400000.0},
        )

        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter1)
        await manager.register_account("ACC002", adapter=adapter2)

        # Verify both accounts are registered
        assert set(manager.get_account_ids()) == {"ACC001", "ACC002"}

        # Submit individual orders
        order_result = await manager.submit_order(
            "ACC001", OrderRequest(symbol="GOOG", side="buy", quantity=10)
        )
        assert order_result.status == "submitted"

        # Broadcast an order
        broadcast_results = await manager.broadcast_order(
            OrderRequest(symbol="MSFT", side="buy", quantity=300),
            {"ACC001": 100, "ACC002": 200},
        )
        assert broadcast_results["ACC001"].quantity == 100
        assert broadcast_results["ACC002"].quantity == 200

        # Aggregate positions
        agg = await manager.get_aggregate_positions()
        assert agg["AAPL"].total_quantity == 300
        assert agg["AAPL"].weighted_avg_cost == pytest.approx(147.0)
        assert agg["TSLA"].total_quantity == 50

        # Aggregate P&L
        pnl = await manager.get_aggregate_pnl()
        assert pnl.total_equity == 400000.0
        assert pnl.total_unrealized_pnl == 1400.0  # 500 + 400 + 500

        # Health check
        health = await manager.health_check_all()
        assert all(h.status == AccountStatus.ACTIVE for h in health.values())

    @pytest.mark.asyncio
    async def test_register_unregister_register(self):
        """Verify re-registration after unregister works."""
        manager = MultiAccountManager()
        await manager.register_account("ACC001")
        manager.unregister_account("ACC001")
        # Should not raise
        await manager.register_account("ACC001")
        assert "ACC001" in manager.get_account_ids()

    @pytest.mark.asyncio
    async def test_broadcast_order_preserves_metadata(self):
        manager = MultiAccountManager()
        await manager.register_account("ACC001")

        order = OrderRequest(
            symbol="AAPL",
            side="buy",
            quantity=100,
            metadata={"strategy": "momentum"},
        )
        results = await manager.broadcast_order(order, {"ACC001": 100})

        assert results["ACC001"].status == "submitted"
        # The broadcast internally creates a new OrderRequest with parent_broadcast metadata
        # The original order's metadata should not be modified
        assert order.metadata == {"strategy": "momentum"}

    @pytest.mark.asyncio
    async def test_manager_with_event_bus(self):
        """Verify event_bus is stored but not used directly (future extension point)."""

        class SimpleEventBus:
            pass

        bus = SimpleEventBus()
        manager = MultiAccountManager(event_bus=bus)
        assert manager._event_bus is bus

    @pytest.mark.asyncio
    async def test_aggregate_position_zero_quantity_weighted_avg(self):
        """Edge case: positions with zero quantity should produce zero weighted avg cost."""
        positions = [
            {"symbol": "AAPL", "quantity": 0, "avg_cost": 145.0, "market_price": 150.0, "unrealized_pnl": 0.0},
        ]
        adapter = MockAdapterWithData(positions=positions)
        manager = MultiAccountManager()
        await manager.register_account("ACC001", adapter=adapter)

        agg = await manager.get_aggregate_positions()
        assert "AAPL" in agg
        assert agg["AAPL"].weighted_avg_cost == 0.0
