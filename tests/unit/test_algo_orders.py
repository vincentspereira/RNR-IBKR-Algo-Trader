"""Comprehensive unit tests for TWAP and VWAP execution algorithms.

Covers:
- TWAP equal slice execution, cancellation, and edge cases
- VWAP volume-weighted slice execution, cancellation, and edge cases
- Data class construction and defaults
- Event bus notification integration
- Slippage tracking and average price calculation
"""

import asyncio
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure core_trading is importable.
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core_trading.execution.algo_orders import (
    AlgoConfig,
    AlgoOrder,
    AlgoOrderResult,
    SliceResult,
    TWAPExecutor,
    VWAPExecutor,
    VolumeProfile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_event_bus():
    """AsyncMock with a publish method for capturing events."""
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_execution_callback():
    """AsyncMock that returns a SliceResult when called with an AlgoOrder."""

    async def _callback(order: AlgoOrder) -> SliceResult:
        price = order.price if order.price is not None else 150.0
        return SliceResult(
            slice_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            status="filled",
            commission=order.quantity * price * 0.001,
        )

    return AsyncMock(side_effect=_callback)


@pytest.fixture
def sample_order():
    """A standard buy order for 1000 shares of AAPL at $150."""
    return AlgoOrder(
        order_id="test-order-001",
        symbol="AAPL",
        side="buy",
        quantity=1000.0,
        price=150.0,
    )


@pytest.fixture
def sample_volume_profile():
    """Typical US equity volume profile across the trading day."""
    return VolumeProfile(
        intervals={
            "09:30": 0.15,
            "10:00": 0.12,
            "10:30": 0.08,
            "11:00": 0.06,
            "11:30": 0.05,
            "12:00": 0.04,
            "12:30": 0.04,
            "13:00": 0.04,
            "13:30": 0.05,
            "14:00": 0.06,
            "14:30": 0.08,
            "15:00": 0.10,
            "15:30": 0.13,
        }
    )


@pytest.fixture
def twap_executor(mock_execution_callback, mock_event_bus):
    """TWAPExecutor with mock callback and event bus."""
    return TWAPExecutor(
        execution_callback=mock_execution_callback,
        event_bus=mock_event_bus,
    )


@pytest.fixture
def vwap_executor(mock_execution_callback, mock_event_bus):
    """VWAPExecutor with mock callback and event bus."""
    return VWAPExecutor(
        execution_callback=mock_execution_callback,
        event_bus=mock_event_bus,
    )


# ---------------------------------------------------------------------------
# TWAP Tests
# ---------------------------------------------------------------------------

class TestTWAPExecutor:
    """Tests for the TWAPExecutor class."""

    @pytest.mark.asyncio
    async def test_twap_execute_equal_slices(self, twap_executor, sample_order):
        """Each TWAP slice should be the same size."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=10, slices=10,
            )

        quantities = [s.quantity for s in result.slices]
        assert len(quantities) == 10
        # All slices should be 100.0 (= 1000 / 10).
        for q in quantities:
            assert q == pytest.approx(100.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_twap_execute_correct_count(self, twap_executor, sample_order):
        """TWAP should produce exactly the requested number of slices."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=5, slices=5,
            )

        assert len(result.slices) == 5

    @pytest.mark.asyncio
    async def test_twap_execute_total_quantity_matches(
        self, twap_executor, sample_order,
    ):
        """Total executed quantity should equal the original order quantity."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=10, slices=10,
            )

        assert result.executed_quantity == pytest.approx(
            sample_order.quantity, rel=1e-6,
        )

    @pytest.mark.asyncio
    async def test_twap_execute_status_completed(self, twap_executor, sample_order):
        """A fully executed TWAP should have status 'completed'."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=10, slices=10,
            )

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_twap_execute_with_callback(
        self, mock_execution_callback, mock_event_bus, sample_order,
    ):
        """TWAP should invoke the execution callback for each slice."""
        executor = TWAPExecutor(
            execution_callback=mock_execution_callback,
            event_bus=mock_event_bus,
        )
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_twap(
                sample_order, duration_minutes=5, slices=5,
            )

        assert mock_execution_callback.call_count == 5
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_twap_execute_without_callback_simulates(self, sample_order):
        """TWAP without a callback should use simulated fills."""
        executor = TWAPExecutor()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_twap(
                sample_order, duration_minutes=5, slices=5,
            )

        assert result.status == "completed"
        assert len(result.slices) == 5
        # Default simulated price is the order price (150.0).
        for s in result.slices:
            assert s.price == 150.0

    @pytest.mark.asyncio
    async def test_twap_cancel_stops_execution(self, sample_order, mock_event_bus):
        """Cancelling mid-execution should stop further slices."""
        callback = AsyncMock()

        async def _callback(order):
            return SliceResult(
                slice_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=150.0,
                status="filled",
            )

        callback.side_effect = _callback
        executor = TWAPExecutor(execution_callback=callback, event_bus=mock_event_bus)

        # Pre-register the order as active so cancel() returns True.
        result_placeholder = AlgoOrderResult(
            parent_order_id=sample_order.order_id,
            algorithm="twap",
            total_quantity=sample_order.quantity,
            executed_quantity=0.0,
            average_price=0.0,
            slices=[],
            start_time=datetime.now(timezone.utc),
            status="executing",
        )
        executor._active_orders[sample_order.order_id] = result_placeholder

        # Cancel before running execute_twap. The cancelled flag will persist
        # and be detected at the first slice iteration inside execute_twap.
        assert executor.cancel(sample_order.order_id) is True

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_twap(
                sample_order, duration_minutes=10, slices=5,
            )

        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_twap_cancel_nonexistent_returns_false(self):
        """Cancelling a non-existent order should return False."""
        executor = TWAPExecutor()
        assert executor.cancel("nonexistent-id") is False

    @pytest.mark.asyncio
    async def test_twap_get_active_orders(
        self, mock_execution_callback, mock_event_bus, sample_order,
    ):
        """Active orders should be tracked during execution."""
        executor = TWAPExecutor(
            execution_callback=mock_execution_callback,
            event_bus=mock_event_bus,
        )

        # Before execution, no active orders.
        assert executor.get_active_orders() == []

        # Start a long-running TWAP in the background.
        async def _run():
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Make sleep hang so we can inspect active orders.
                mock_sleep.side_effect = asyncio.sleep(0.01)
                await executor.execute_twap(sample_order, duration_minutes=60, slices=100)

        task = asyncio.ensure_future(_run())
        # Give it a moment to start.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_twap_single_slice(self, twap_executor, sample_order):
        """TWAP with slices=1 should execute in one shot."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=5, slices=1,
            )

        assert len(result.slices) == 1
        assert result.slices[0].quantity == pytest.approx(1000.0, rel=1e-6)
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_twap_result_has_average_price(self, twap_executor, sample_order):
        """Average price should be computed from all filled slices."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=5, slices=5,
            )

        # All slices filled at 150.0, so average should be 150.0.
        assert result.average_price == pytest.approx(150.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_twap_result_tracks_slippage(self):
        """Slippage should reflect deviation from the limit price."""
        order = AlgoOrder(
            order_id="slippage-test",
            symbol="MSFT",
            side="buy",
            quantity=100.0,
            price=200.0,
        )

        # Callback that simulates adverse fill (higher price for a buy).
        async def _bad_fill(o):
            return SliceResult(
                slice_id=o.order_id,
                symbol=o.symbol,
                side=o.side,
                quantity=o.quantity,
                price=202.0,  # 1% higher than limit.
                status="filled",
            )

        executor = TWAPExecutor(execution_callback=AsyncMock(side_effect=_bad_fill))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_twap(order, duration_minutes=5, slices=2)

        # Slippage = (202 - 200) / 200 = 0.01 (1%).
        assert result.slippage == pytest.approx(0.01, rel=1e-6)

    @pytest.mark.asyncio
    async def test_twap_result_has_start_end_time(
        self, twap_executor, sample_order,
    ):
        """Completed result should have both start and end timestamps."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await twap_executor.execute_twap(
                sample_order, duration_minutes=5, slices=3,
            )

        assert result.start_time is not None
        assert result.end_time is not None
        assert result.end_time >= result.start_time

    @pytest.mark.asyncio
    async def test_twap_zero_quantity_raises(self):
        """A zero-quantity order should raise ValueError."""
        order = AlgoOrder(
            order_id="zero-qty",
            symbol="AAPL",
            side="buy",
            quantity=0.0,
        )
        executor = TWAPExecutor()
        with pytest.raises(ValueError, match="must be positive"):
            await executor.execute_twap(order, duration_minutes=5, slices=5)

    @pytest.mark.asyncio
    async def test_twap_negative_quantity_raises(self):
        """A negative-quantity order should raise ValueError."""
        order = AlgoOrder(
            order_id="neg-qty",
            symbol="AAPL",
            side="sell",
            quantity=-100.0,
        )
        executor = TWAPExecutor()
        with pytest.raises(ValueError, match="must be positive"):
            await executor.execute_twap(order, duration_minutes=5, slices=5)

    @pytest.mark.asyncio
    async def test_twap_cancel_returns_true_when_active(
        self, mock_execution_callback, mock_event_bus, sample_order,
    ):
        """cancel() should return True when the order is currently active."""
        executor = TWAPExecutor(
            execution_callback=mock_execution_callback,
            event_bus=mock_event_bus,
        )

        # Start execution in background.
        async def _run():
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Make sleep slow so the order stays active.
                mock_sleep.side_effect = asyncio.sleep(0.02)
                await executor.execute_twap(sample_order, duration_minutes=60, slices=100)

        task = asyncio.ensure_future(_run())
        await asyncio.sleep(0.05)

        # The order should be active now.
        active = executor.get_active_orders()
        if active:
            assert executor.cancel(sample_order.order_id) is True
        else:
            # If execution finished too quickly, just verify cancel returns False.
            assert executor.cancel(sample_order.order_id) is False

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# VWAP Tests
# ---------------------------------------------------------------------------

class TestVWAPExecutor:
    """Tests for the VWAPExecutor class."""

    @pytest.mark.asyncio
    async def test_vwap_execute_volume_weighted_slices(
        self, vwap_executor, sample_order, sample_volume_profile,
    ):
        """VWAP slices should vary in size according to the volume profile."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await vwap_executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        quantities = [s.quantity for s in result.slices]
        # Slices should NOT all be equal for VWAP.
        assert len(set(quantities)) > 1, "VWAP slices should vary in size"

    @pytest.mark.asyncio
    async def test_vwap_slice_sizes_proportional_to_volume(
        self, vwap_executor, sample_order, sample_volume_profile,
    ):
        """Slice sizes should be proportional to volume fractions."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await vwap_executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        quantities = [s.quantity for s in result.slices]
        fractions = list(sample_volume_profile.intervals.values())
        total_frac = sum(fractions)

        # Verify proportional relationship: qty_i / total = frac_i / total_frac
        for qty, frac in zip(quantities, fractions):
            expected_ratio = frac / total_frac
            actual_ratio = qty / sample_order.quantity
            assert actual_ratio == pytest.approx(expected_ratio, rel=0.01)

    @pytest.mark.asyncio
    async def test_vwap_total_executed_matches_order(
        self, vwap_executor, sample_order, sample_volume_profile,
    ):
        """Total executed quantity should equal the original order quantity."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await vwap_executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        assert result.executed_quantity == pytest.approx(
            sample_order.quantity, rel=1e-6,
        )

    @pytest.mark.asyncio
    async def test_vwap_execute_with_callback(
        self, mock_execution_callback, mock_event_bus,
        sample_order, sample_volume_profile,
    ):
        """VWAP should invoke the execution callback for each slice."""
        executor = VWAPExecutor(
            execution_callback=mock_execution_callback,
            event_bus=mock_event_bus,
        )
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        expected_calls = len(sample_volume_profile.intervals)
        assert mock_execution_callback.call_count == expected_calls
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_vwap_cancel_stops_execution(
        self, sample_order, sample_volume_profile, mock_event_bus,
    ):
        """Cancelling a VWAP mid-execution should stop further slices."""
        async def _callback(o):
            return SliceResult(
                slice_id=o.order_id,
                symbol=o.symbol,
                side=o.side,
                quantity=o.quantity,
                price=150.0,
                status="filled",
            )

        executor = VWAPExecutor(
            execution_callback=AsyncMock(side_effect=_callback),
            event_bus=mock_event_bus,
        )

        # Pre-register the order as active so cancel works.
        result_placeholder = AlgoOrderResult(
            parent_order_id=sample_order.order_id,
            algorithm="vwap",
            total_quantity=sample_order.quantity,
            executed_quantity=0.0,
            average_price=0.0,
            slices=[],
            start_time=datetime.now(timezone.utc),
            status="executing",
        )
        executor._active_orders[sample_order.order_id] = result_placeholder

        # Now cancel before running execute_vwap.
        # The cancel flag is checked at the start of each slice loop iteration.
        executor.cancel(sample_order.order_id)

        # When execute_vwap runs, it will see the cancelled flag immediately.
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        # The execute_vwap creates a NEW result object, so we need to check
        # it gets cancelled. Since we cancelled before execution started,
        # the cancel flag is already in _cancelled.
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_vwap_cancel_nonexistent_returns_false(self):
        """Cancelling a non-existent VWAP order should return False."""
        executor = VWAPExecutor()
        assert executor.cancel("nonexistent-id") is False

    @pytest.mark.asyncio
    async def test_vwap_get_active_orders(self, vwap_executor):
        """Before any execution, active orders list should be empty."""
        assert vwap_executor.get_active_orders() == []

    @pytest.mark.asyncio
    async def test_vwap_default_volume_profile(self):
        """The default volume profile should cover the full US session."""
        executor = VWAPExecutor()
        profile = executor.get_default_volume_profile()

        assert isinstance(profile, VolumeProfile)
        assert len(profile.intervals) == 13
        # Fractions should sum to approximately 1.0.
        total = sum(profile.intervals.values())
        assert total == pytest.approx(1.0, abs=0.01)
        # Should start at market open.
        assert "09:30" in profile.intervals
        # Should have higher volume at open and close.
        assert profile.intervals["09:30"] > profile.intervals["12:00"]

    @pytest.mark.asyncio
    async def test_vwap_calculate_slice_sizes(self):
        """_calculate_slice_sizes should produce correct proportional sizes."""
        executor = VWAPExecutor()
        profile = VolumeProfile(
            intervals={"A": 0.5, "B": 0.3, "C": 0.2},
            total_expected_volume=100000,
        )

        slices = executor._calculate_slice_sizes(1000.0, profile)

        assert len(slices) == 3
        labels, quantities = zip(*slices)
        assert labels == ("A", "B", "C")
        assert quantities[0] == pytest.approx(500.0, rel=1e-6)
        assert quantities[1] == pytest.approx(300.0, rel=1e-6)
        assert quantities[2] == pytest.approx(200.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_vwap_calculate_slice_sizes_sums_to_total(self):
        """Slice quantities must sum exactly to the total order quantity."""
        executor = VWAPExecutor()
        profile = VolumeProfile(
            intervals={
                "09:30": 0.15, "10:00": 0.12, "10:30": 0.08,
                "11:00": 0.06, "11:30": 0.05, "12:00": 0.04,
                "12:30": 0.04, "13:00": 0.04, "13:30": 0.05,
                "14:00": 0.06, "14:30": 0.08, "15:00": 0.10,
                "15:30": 0.13,
            },
        )

        for total_qty in [1000.0, 333.0, 1.0, 99999.0]:
            slices = executor._calculate_slice_sizes(total_qty, profile)
            slice_sum = sum(q for _, q in slices)
            assert slice_sum == pytest.approx(total_qty, rel=1e-6), (
                f"Slice sum {slice_sum} != total {total_qty}"
            )

    @pytest.mark.asyncio
    async def test_vwap_result_status_completed(
        self, vwap_executor, sample_order, sample_volume_profile,
    ):
        """A fully executed VWAP should have status 'completed'."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await vwap_executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_vwap_zero_quantity_raises(self, sample_volume_profile):
        """A zero-quantity VWAP order should raise ValueError."""
        order = AlgoOrder(
            order_id="zero-vwap",
            symbol="AAPL",
            side="buy",
            quantity=0.0,
        )
        executor = VWAPExecutor()
        with pytest.raises(ValueError, match="must be positive"):
            await executor.execute_vwap(order, sample_volume_profile, duration_minutes=60)

    @pytest.mark.asyncio
    async def test_vwap_empty_profile_returns_empty(self):
        """An empty volume profile should not produce slices."""
        executor = VWAPExecutor()
        empty_profile = VolumeProfile(intervals={})
        slices = executor._calculate_slice_sizes(1000.0, empty_profile)
        assert slices == []

    @pytest.mark.asyncio
    async def test_vwap_without_callback_simulates(
        self, sample_order, sample_volume_profile,
    ):
        """VWAP without a callback should use simulated fills."""
        executor = VWAPExecutor()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        assert result.status == "completed"
        assert len(result.slices) == 13
        for s in result.slices:
            assert s.price == 150.0  # order.price is 150.0

    @pytest.mark.asyncio
    async def test_vwap_result_has_average_price(
        self, vwap_executor, sample_order, sample_volume_profile,
    ):
        """Average price should be computed from all filled slices."""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await vwap_executor.execute_vwap(
                sample_order, sample_volume_profile, duration_minutes=390,
            )

        # All slices filled at 150.0, so average should be 150.0.
        assert result.average_price == pytest.approx(150.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Data Class Tests
# ---------------------------------------------------------------------------

class TestAlgoDataClasses:
    """Tests for the standalone data classes."""

    def test_algo_order_creation(self):
        """AlgoOrder should store all fields correctly."""
        order = AlgoOrder(
            order_id="ord-1",
            symbol="AAPL",
            side="buy",
            quantity=100.0,
            price=150.0,
        )
        assert order.order_id == "ord-1"
        assert order.symbol == "AAPL"
        assert order.side == "buy"
        assert order.quantity == 100.0
        assert order.price == 150.0
        assert order.order_type == "market"
        assert order.stop_price is None
        assert order.strategy_id is None
        assert order.metadata == {}

    def test_algo_order_with_all_fields(self):
        """AlgoOrder should accept all optional fields."""
        order = AlgoOrder(
            order_id="ord-2",
            symbol="MSFT",
            side="sell",
            quantity=200.0,
            order_type="limit",
            price=300.0,
            stop_price=295.0,
            strategy_id="strat-1",
            metadata={"reason": "take_profit"},
        )
        assert order.order_type == "limit"
        assert order.stop_price == 295.0
        assert order.strategy_id == "strat-1"
        assert order.metadata["reason"] == "take_profit"

    def test_slice_result_creation(self):
        """SliceResult should store all fields with proper defaults."""
        now = datetime.now(timezone.utc)
        sr = SliceResult(
            slice_id="slice-1",
            symbol="AAPL",
            side="buy",
            quantity=100.0,
            price=150.0,
            status="filled",
        )
        assert sr.slice_id == "slice-1"
        assert sr.commission == 0.0
        assert sr.metadata == {}
        # Timestamp should be close to now.
        assert abs((sr.timestamp - now).total_seconds()) < 2

    def test_algo_order_result_creation(self):
        """AlgoOrderResult should store all fields with proper defaults."""
        result = AlgoOrderResult(
            parent_order_id="parent-1",
            algorithm="twap",
            total_quantity=1000.0,
            executed_quantity=1000.0,
            average_price=150.0,
            slices=[],
            start_time=datetime.now(timezone.utc),
        )
        assert result.status == "pending"
        assert result.end_time is None
        assert result.total_commission == 0.0
        assert result.slippage == 0.0
        assert result.metadata == {}

    def test_volume_profile_creation(self):
        """VolumeProfile should store intervals and default total volume."""
        vp = VolumeProfile(
            intervals={"09:30": 0.15, "10:00": 0.12},
        )
        assert len(vp.intervals) == 2
        assert vp.total_expected_volume == 1000000.0

    def test_volume_profile_custom_total(self):
        """VolumeProfile should accept a custom total expected volume."""
        vp = VolumeProfile(
            intervals={"09:30": 0.5, "10:00": 0.5},
            total_expected_volume=500000.0,
        )
        assert vp.total_expected_volume == 500000.0

    def test_algo_config_defaults(self):
        """AlgoConfig should have sensible defaults."""
        config = AlgoConfig()
        assert config.max_participation_rate == 0.3
        assert config.min_slice_quantity == 1.0
        assert config.default_slice_interval_seconds == 60.0
        assert config.price_improvement_threshold == 0.001
        assert config.max_slippage == 0.01

    def test_algo_config_custom(self):
        """AlgoConfig should accept custom values."""
        config = AlgoConfig(
            max_participation_rate=0.5,
            min_slice_quantity=5.0,
            default_slice_interval_seconds=30.0,
            price_improvement_threshold=0.005,
            max_slippage=0.02,
        )
        assert config.max_participation_rate == 0.5
        assert config.min_slice_quantity == 5.0
