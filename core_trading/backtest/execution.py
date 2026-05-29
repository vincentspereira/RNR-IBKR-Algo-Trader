"""Order-fill simulation against price bars (master plan Phase 3.2).

:class:`ExecutionSimulator` decides, for one order against one OHLCV bar,
*whether* it fills, at *what reference price*, and for *how much* (liquidity
permitting). It then asks the :class:`~core_trading.backtest.costs.CostModel`
to move that reference adversely (slippage + impact) and charge commission and
fees, producing a :class:`~core_trading.backtest.orders.Fill`.

Order-type semantics implemented here:

* **Market** -- fills at the bar open (configurable) regardless of price path.
* **Limit** -- fills only if the bar trades through the limit, at the limit or
  the (better) open.
* **Stop / Stop-Limit** -- triggers when the bar reaches the stop; a stop-limit
  additionally refuses to fill worse than its limit.
* **MOC / LOC** -- fill at the close (the LOC honouring its limit).
* **TWAP / VWAP** -- single-bar approximations: TWAP at the bar's OHLC average,
  VWAP at the typical price (H+L+C)/3. Multi-bar scheduling of these is the
  engine's job; here we price one slice.

Liquidity: a fill is capped at ``max_participation_rate`` of the bar volume, so
large orders fill **partially** and the remainder is reported back for the
engine to carry over or cancel per the order's time-in-force.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core_trading.backtest.costs import CostModel
from core_trading.backtest.orders import Fill, LiquidityFlag, Order, OrderStatus, OrderType, Side

__all__ = ["Bar", "ExecutionConfig", "ExecutionResult", "ExecutionSimulator"]


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar plus the statistics the impact model needs."""

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    adv: float = 0.0
    volatility: float = 0.0

    def __post_init__(self) -> None:
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"inconsistent OHLC at {self.timestamp}: "
                f"O={self.open} H={self.high} L={self.low} C={self.close}"
            )

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def ohlc_average(self) -> float:
        return (self.open + self.high + self.low + self.close) / 4.0


@dataclass
class ExecutionConfig:
    """Knobs controlling fill realism."""

    max_participation_rate: float = 0.1
    allow_partial_fills: bool = True
    market_fill_price: str = "open"

    def __post_init__(self) -> None:
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")
        if self.market_fill_price not in ("open", "close"):
            raise ValueError("market_fill_price must be 'open' or 'close'")


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of attempting to fill an order against a bar."""

    status: OrderStatus
    fill: Fill | None = None
    remaining_quantity: float = 0.0
    reason: str = ""


class ExecutionSimulator:
    """Stateless per-bar order matcher driven by a :class:`CostModel`."""

    def __init__(self, cost_model: CostModel, config: ExecutionConfig | None = None) -> None:
        self.cost_model = cost_model
        self.config = config or ExecutionConfig()

    def execute(self, order: Order, bar: Bar) -> ExecutionResult:
        """Attempt to fill ``order`` against ``bar``."""
        reference = self._reference_price(order, bar)
        if reference is None:
            return ExecutionResult(
                status=OrderStatus.PENDING,
                remaining_quantity=order.quantity,
                reason="not triggered / no cross this bar",
            )

        fillable = self._fillable_quantity(order, bar)
        if fillable <= 0:
            return ExecutionResult(
                status=OrderStatus.PENDING,
                remaining_quantity=order.quantity,
                reason="no liquidity this bar",
            )

        breakdown = self.cost_model.price_with_costs(
            order.side,
            fillable,
            reference,
            bar_volume=bar.volume,
            adv=bar.adv,
            volatility=bar.volatility,
        )
        remaining = order.quantity - fillable
        is_partial = remaining > 1e-9
        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fillable,
            price=breakdown.fill_price,
            timestamp=bar.timestamp,
            commission=breakdown.commission,
            fees=breakdown.fees,
            slippage_cost=breakdown.slippage_cost,
            impact_cost=breakdown.impact_cost,
            liquidity=LiquidityFlag.TAKER,
            is_partial=is_partial,
        )
        status = OrderStatus.PARTIALLY_FILLED if is_partial else OrderStatus.FILLED
        return ExecutionResult(status=status, fill=fill, remaining_quantity=max(remaining, 0.0))

    # ------------------------------------------------------------- internals
    def _fillable_quantity(self, order: Order, bar: Bar) -> float:
        if not self.config.allow_partial_fills:
            # Liquidity-unaware mode: fill the full order regardless of volume.
            return order.quantity
        if bar.volume <= 0:
            # Liquidity-aware mode with no volume this bar: nothing to fill.
            return 0.0
        cap = self.config.max_participation_rate * bar.volume
        return min(order.quantity, cap)

    def _reference_price(self, order: Order, bar: Bar) -> float | None:
        """The pre-cost execution price, or ``None`` if the order does not fill
        this bar."""
        otype = order.order_type
        if otype is OrderType.MARKET:
            return bar.open if self.config.market_fill_price == "open" else bar.close
        if otype is OrderType.MOC:
            return bar.close
        if otype is OrderType.LOC:
            return self._loc_price(order, bar)
        if otype is OrderType.LIMIT:
            return self._limit_price(order, bar)
        if otype is OrderType.STOP:
            return self._stop_price(order, bar)
        if otype is OrderType.STOP_LIMIT:
            return self._stop_limit_price(order, bar)
        if otype is OrderType.TWAP:
            return bar.ohlc_average
        if otype is OrderType.VWAP:
            return bar.typical_price
        raise ValueError(f"unsupported order type {otype}")  # pragma: no cover

    def _limit_price(self, order: Order, bar: Bar) -> float | None:
        limit = order.limit_price
        assert limit is not None  # guaranteed by Order validation
        if order.side is Side.BUY:
            if bar.low <= limit:
                return min(bar.open, limit)
            return None
        if bar.high >= limit:
            return max(bar.open, limit)
        return None

    def _stop_price(self, order: Order, bar: Bar) -> float | None:
        stop = order.stop_price
        assert stop is not None
        if order.side is Side.BUY:
            if bar.high >= stop:
                return max(bar.open, stop)
            return None
        if bar.low <= stop:
            return min(bar.open, stop)
        return None

    def _stop_limit_price(self, order: Order, bar: Bar) -> float | None:
        triggered = self._stop_price(order, bar)
        if triggered is None:
            return None
        limit = order.limit_price
        assert limit is not None
        if order.side is Side.BUY:
            return triggered if triggered <= limit else None
        return triggered if triggered >= limit else None

    def _loc_price(self, order: Order, bar: Bar) -> float | None:
        limit = order.limit_price
        assert limit is not None
        if order.side is Side.BUY:
            return bar.close if bar.close <= limit else None
        return bar.close if bar.close >= limit else None
