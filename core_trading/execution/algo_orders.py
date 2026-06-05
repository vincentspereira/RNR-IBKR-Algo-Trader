"""TWAP and VWAP Execution Algorithms.

Standalone execution algorithm module providing Time-Weighted Average Price (TWAP)
and Volume-Weighted Average Price (VWAP) order slicing strategies. Uses its own
simple data classes to avoid circular imports with the main execution engine.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class AlgoOrder:
    """Simple order representation for algo execution."""

    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str = "market"
    price: float | None = None
    stop_price: float | None = None
    strategy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SliceResult:
    """Result of a single order slice execution."""

    slice_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str  # "filled", "rejected", "pending"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    commission: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlgoOrderResult:
    """Result of an algo order execution."""

    parent_order_id: str
    algorithm: str  # "twap" or "vwap"
    total_quantity: float
    executed_quantity: float
    average_price: float
    slices: list[SliceResult]
    start_time: datetime
    end_time: datetime | None = None
    status: str = "pending"  # "pending", "executing", "completed", "failed", "cancelled"
    total_commission: float = 0.0
    slippage: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VolumeProfile:
    """Expected volume distribution across time intervals.

    The intervals dict maps time labels (e.g. "09:30") to the fraction of
    total daily volume expected in that interval. Values should sum to
    approximately 1.0.
    """

    intervals: dict[str, float]  # time_label -> volume_fraction (should sum to ~1.0)
    total_expected_volume: float = 1000000.0


@dataclass
class AlgoConfig:
    """Configuration for algo execution."""

    max_participation_rate: float = 0.3
    min_slice_quantity: float = 1.0
    default_slice_interval_seconds: float = 60.0
    price_improvement_threshold: float = 0.001
    max_slippage: float = 0.01


# ---------------------------------------------------------------------------
# TWAP Executor
# ---------------------------------------------------------------------------

class TWAPExecutor:
    """Time-Weighted Average Price execution.

    Splits an order into equal-sized slices executed at regular time intervals.
    Designed for situations where the trader wants to minimise market impact by
    participating steadily over a time window rather than executing in one clip.
    """

    def __init__(
        self,
        execution_callback: Callable | None = None,
        event_bus: Any = None,
        config: AlgoConfig | None = None,
    ):
        self._execute_callback = execution_callback
        self._event_bus = event_bus
        self._config = config or AlgoConfig()
        self._active_orders: dict[str, AlgoOrderResult] = {}
        self._cancelled: set[str] = set()
        self._logger = logging.getLogger(__name__)

    async def execute_twap(
        self,
        order: AlgoOrder,
        duration_minutes: int,
        slices: int = 10,
    ) -> AlgoOrderResult:
        """Split order into equal slices over a time window.

        If an execution_callback is set it is called for each slice; otherwise a
        simulated fill is generated for testing / preview purposes.

        Args:
            order: The parent order to slice.
            duration_minutes: Total execution window in minutes.
            slices: Number of equal-sized slices (default 10).

        Returns:
            AlgoOrderResult with execution details.

        Raises:
            ValueError: If order quantity is zero or negative.
        """
        if order.quantity <= 0:
            raise ValueError(
                f"Order quantity must be positive, got {order.quantity}"
            )

        slice_size = order.quantity / slices
        interval_seconds = (duration_minutes * 60) / slices

        result = AlgoOrderResult(
            parent_order_id=order.order_id,
            algorithm="twap",
            total_quantity=order.quantity,
            executed_quantity=0.0,
            average_price=0.0,
            slices=[],
            start_time=datetime.now(UTC),
            status="executing",
            metadata={
                "duration_minutes": duration_minutes,
                "num_slices": slices,
                "slice_size": slice_size,
                "interval_seconds": interval_seconds,
                "symbol": order.symbol,
                "side": order.side,
            },
        )

        self._active_orders[order.order_id] = result
        total_value = 0.0

        try:
            for i in range(slices):
                # Check for cancellation before each slice.
                if order.order_id in self._cancelled:
                    result.status = "cancelled"
                    result.end_time = datetime.now(UTC)
                    self._cancelled.discard(order.order_id)
                    self._logger.info(
                        "TWAP cancelled after slice %d/%d for order %s",
                        i, slices, order.order_id,
                    )
                    await self._notify_event("twap_cancelled", {
                        "order_id": order.order_id,
                        "slice_index": i,
                    })
                    return result

                # Build the slice order.
                slice_order = AlgoOrder(
                    order_id=f"{order.order_id}_slice_{i}",
                    symbol=order.symbol,
                    side=order.side,
                    quantity=slice_size,
                    order_type=order.order_type,
                    price=order.price,
                    stop_price=order.stop_price,
                    strategy_id=order.strategy_id,
                    metadata={
                        **order.metadata,
                        "parent_order_id": order.order_id,
                        "slice_index": i,
                        "total_slices": slices,
                        "algorithm": "twap",
                    },
                )

                # Execute or simulate the slice.
                if self._execute_callback is not None:
                    fill = await self._execute_callback(slice_order)
                else:
                    fill = self._simulate_fill(slice_order)

                result.slices.append(fill)
                result.executed_quantity += fill.quantity

                if fill.status == "filled":
                    total_value += fill.quantity * fill.price
                    result.total_commission += fill.commission

                # Notify progress.
                await self._notify_event("twap_slice_filled", {
                    "order_id": order.order_id,
                    "slice_index": i,
                    "fill_price": fill.price,
                    "fill_quantity": fill.quantity,
                    "fill_status": fill.status,
                })

                # Sleep between slices (skip after the last one).
                if i < slices - 1:
                    await asyncio.sleep(interval_seconds)

            # Finalise result.
            if result.executed_quantity > 0:
                result.average_price = total_value / result.executed_quantity

            if order.price is not None and result.average_price > 0:
                if order.side == "buy":
                    result.slippage = (
                        (result.average_price - order.price) / order.price
                    )
                else:
                    result.slippage = (
                        (order.price - result.average_price) / order.price
                    )

            result.status = "completed"
            result.end_time = datetime.now(UTC)

            await self._notify_event("twap_completed", {
                "order_id": order.order_id,
                "executed_quantity": result.executed_quantity,
                "average_price": result.average_price,
                "slippage": result.slippage,
            })

        except Exception:
            result.status = "failed"
            result.end_time = datetime.now(UTC)
            self._logger.exception(
                "TWAP execution failed for order %s", order.order_id,
            )
            raise
        finally:
            self._active_orders.pop(order.order_id, None)

        return result

    def cancel(self, order_id: str) -> bool:
        """Cancel an active TWAP execution.

        Returns True if the order was found and marked for cancellation,
        False otherwise.
        """
        if order_id in self._active_orders:
            self._cancelled.add(order_id)
            self._logger.info("TWAP cancel requested for order %s", order_id)
            return True
        return False

    def get_active_orders(self) -> list[AlgoOrderResult]:
        """Get currently executing TWAP orders."""
        return list(self._active_orders.values())

    def _simulate_fill(self, order: AlgoOrder) -> SliceResult:
        """Simulate a fill for testing / preview purposes.

        Uses order.price if set, otherwise falls back to 100.0.
        """
        price = order.price if order.price is not None else 100.0
        return SliceResult(
            slice_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            status="filled",
            commission=order.quantity * price * 0.001,
        )

    async def _notify_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish event to event bus if available."""
        if self._event_bus is not None and hasattr(self._event_bus, "publish"):
            try:
                await self._event_bus.publish({
                    "type": event_type,
                    "data": data,
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            except Exception:
                self._logger.warning(
                    "Failed to publish event %s", event_type, exc_info=True,
                )


# ---------------------------------------------------------------------------
# VWAP Executor
# ---------------------------------------------------------------------------

class VWAPExecutor:
    """Volume-Weighted Average Price execution.

    Splits an order into slices whose sizes are proportional to expected volume
    at each time interval, aiming to execute alongside natural liquidity.
    """

    def __init__(
        self,
        execution_callback: Callable | None = None,
        event_bus: Any = None,
        config: AlgoConfig | None = None,
    ):
        self._execute_callback = execution_callback
        self._event_bus = event_bus
        self._config = config or AlgoConfig()
        self._active_orders: dict[str, AlgoOrderResult] = {}
        self._cancelled: set[str] = set()
        self._logger = logging.getLogger(__name__)

    async def execute_vwap(
        self,
        order: AlgoOrder,
        volume_profile: VolumeProfile,
        duration_minutes: int,
    ) -> AlgoOrderResult:
        """Split order proportional to expected volume profile.

        Each slice size is proportional to the volume fraction for that interval.
        Slices are executed sequentially with even time spacing.

        Args:
            order: The parent order to slice.
            volume_profile: Expected volume distribution across intervals.
            duration_minutes: Total execution window in minutes.

        Returns:
            AlgoOrderResult with execution details.

        Raises:
            ValueError: If order quantity is zero or negative.
        """
        if order.quantity <= 0:
            raise ValueError(
                f"Order quantity must be positive, got {order.quantity}"
            )

        slice_sizes = self._calculate_slice_sizes(order.quantity, volume_profile)
        num_intervals = len(slice_sizes)
        interval_seconds = (
            (duration_minutes * 60) / num_intervals if num_intervals > 0 else 0
        )

        result = AlgoOrderResult(
            parent_order_id=order.order_id,
            algorithm="vwap",
            total_quantity=order.quantity,
            executed_quantity=0.0,
            average_price=0.0,
            slices=[],
            start_time=datetime.now(UTC),
            status="executing",
            metadata={
                "duration_minutes": duration_minutes,
                "num_intervals": num_intervals,
                "interval_seconds": interval_seconds,
                "symbol": order.symbol,
                "side": order.side,
            },
        )

        self._active_orders[order.order_id] = result
        total_value = 0.0

        try:
            for i, (time_label, slice_qty) in enumerate(slice_sizes):
                # Check for cancellation.
                if order.order_id in self._cancelled:
                    result.status = "cancelled"
                    result.end_time = datetime.now(UTC)
                    self._cancelled.discard(order.order_id)
                    self._logger.info(
                        "VWAP cancelled after slice %d/%d for order %s",
                        i, num_intervals, order.order_id,
                    )
                    await self._notify_event("vwap_cancelled", {
                        "order_id": order.order_id,
                        "slice_index": i,
                    })
                    return result

                # Build the slice order.
                slice_order = AlgoOrder(
                    order_id=f"{order.order_id}_vwap_{i}",
                    symbol=order.symbol,
                    side=order.side,
                    quantity=slice_qty,
                    order_type=order.order_type,
                    price=order.price,
                    stop_price=order.stop_price,
                    strategy_id=order.strategy_id,
                    metadata={
                        **order.metadata,
                        "parent_order_id": order.order_id,
                        "slice_index": i,
                        "time_label": time_label,
                        "total_intervals": num_intervals,
                        "algorithm": "vwap",
                    },
                )

                # Execute or simulate.
                if self._execute_callback is not None:
                    fill = await self._execute_callback(slice_order)
                else:
                    fill = self._simulate_fill(slice_order)

                result.slices.append(fill)
                result.executed_quantity += fill.quantity

                if fill.status == "filled":
                    total_value += fill.quantity * fill.price
                    result.total_commission += fill.commission

                # Notify progress.
                await self._notify_event("vwap_slice_filled", {
                    "order_id": order.order_id,
                    "slice_index": i,
                    "time_label": time_label,
                    "fill_price": fill.price,
                    "fill_quantity": fill.quantity,
                    "fill_status": fill.status,
                })

                # Sleep between slices (skip after the last one).
                if i < num_intervals - 1:
                    await asyncio.sleep(interval_seconds)

            # Finalise result.
            if result.executed_quantity > 0:
                result.average_price = total_value / result.executed_quantity

            if order.price is not None and result.average_price > 0:
                if order.side == "buy":
                    result.slippage = (
                        (result.average_price - order.price) / order.price
                    )
                else:
                    result.slippage = (
                        (order.price - result.average_price) / order.price
                    )

            result.status = "completed"
            result.end_time = datetime.now(UTC)

            await self._notify_event("vwap_completed", {
                "order_id": order.order_id,
                "executed_quantity": result.executed_quantity,
                "average_price": result.average_price,
                "slippage": result.slippage,
            })

        except Exception:
            result.status = "failed"
            result.end_time = datetime.now(UTC)
            self._logger.exception(
                "VWAP execution failed for order %s", order.order_id,
            )
            raise
        finally:
            self._active_orders.pop(order.order_id, None)

        return result

    def _calculate_slice_sizes(
        self,
        total_quantity: float,
        volume_profile: VolumeProfile,
    ) -> list[tuple[str, float]]:
        """Calculate slice sizes based on volume distribution.

        Returns a list of (time_label, quantity) tuples. Ensures the total
        adds up exactly to total_quantity by adjusting the last slice.
        """
        intervals = volume_profile.intervals
        if not intervals:
            return []

        total_fraction = sum(intervals.values())
        if total_fraction == 0:
            return []

        slices: list[tuple[str, float]] = []
        accumulated = 0.0

        sorted_intervals = sorted(intervals.items(), key=lambda x: x[0])

        for i, (time_label, fraction) in enumerate(sorted_intervals):
            normalised = fraction / total_fraction

            if i < len(sorted_intervals) - 1:
                qty = round(total_quantity * normalised, 8)
                slices.append((time_label, qty))
                accumulated += qty
            else:
                # Last slice absorbs rounding remainder.
                slices.append((time_label, round(total_quantity - accumulated, 8)))

        return slices

    def cancel(self, order_id: str) -> bool:
        """Cancel an active VWAP execution.

        Returns True if the order was found and marked for cancellation,
        False otherwise.
        """
        if order_id in self._active_orders:
            self._cancelled.add(order_id)
            self._logger.info("VWAP cancel requested for order %s", order_id)
            return True
        return False

    def get_active_orders(self) -> list[AlgoOrderResult]:
        """Get currently executing VWAP orders."""
        return list(self._active_orders.values())

    def get_default_volume_profile(self) -> VolumeProfile:
        """Return a typical US equity volume profile.

        The distribution covers the regular session (09:30-16:00) with
        higher weight at the open and close to reflect typical volume patterns.
        """
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

    def _simulate_fill(self, order: AlgoOrder) -> SliceResult:
        """Simulate a fill for testing / preview purposes.

        Uses order.price if set, otherwise falls back to 100.0.
        """
        price = order.price if order.price is not None else 100.0
        return SliceResult(
            slice_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            status="filled",
            commission=order.quantity * price * 0.001,
        )

    async def _notify_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish event to event bus if available."""
        if self._event_bus is not None and hasattr(self._event_bus, "publish"):
            try:
                await self._event_bus.publish({
                    "type": event_type,
                    "data": data,
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            except Exception:
                self._logger.warning(
                    "Failed to publish event %s", event_type, exc_info=True,
                )
