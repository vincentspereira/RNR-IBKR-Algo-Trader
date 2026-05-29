"""Order, fill and trade primitives (master plan Phase 3.2).

The backtest engine speaks in three immutable records:

* :class:`Order` -- an instruction to trade. It carries everything the
  execution simulator needs to decide *whether* and *at what price* it fills:
  side, quantity, type and (where relevant) limit/stop prices and a schedule
  for the algorithmic types (TWAP/VWAP).
* :class:`Fill` -- the result of (part of) an order executing. It records the
  executed price together with every cost component charged against it
  (commission, exchange/regulatory fees, slippage and market impact) so the
  full transaction cost is always auditable.
* :class:`Trade` -- a realised round-trip (open then close of a position),
  produced by the portfolio when a position is reduced. It is the unit the
  performance metrics consume (win rate, profit factor, average win/loss).

All three are frozen: the engine never mutates a record after creating it,
which keeps a backtest deterministic and its audit trail trustworthy. Mutable
fill *progress* (how much of an order is done) lives on the engine side, not
on the order itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

__all__ = [
    "Side",
    "OrderType",
    "OrderStatus",
    "TimeInForce",
    "LiquidityFlag",
    "Order",
    "Fill",
    "Trade",
    "ALGO_ORDER_TYPES",
    "PRICED_ORDER_TYPES",
]


class Side(str, Enum):
    """Trade direction. ``sign`` maps the side to a position-delta sign."""

    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """+1 for a buy, -1 for a sell."""
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    """Supported order types, matching real broker capabilities."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    MOC = "market_on_close"
    LOC = "limit_on_close"
    TWAP = "twap"
    VWAP = "vwap"


class OrderStatus(str, Enum):
    """Lifecycle state of an order within a backtest run."""

    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    """How long an order rests before it is cancelled if unfilled."""

    DAY = "day"
    GTC = "good_till_cancel"
    IOC = "immediate_or_cancel"
    FOK = "fill_or_kill"


class LiquidityFlag(str, Enum):
    """Whether a fill removed (taker) or added (maker) liquidity."""

    TAKER = "taker"
    MAKER = "maker"


#: Order types that execute over a schedule of child slices rather than at once.
ALGO_ORDER_TYPES: frozenset[OrderType] = frozenset({OrderType.TWAP, OrderType.VWAP})

#: Order types that require a limit price.
PRICED_ORDER_TYPES: frozenset[OrderType] = frozenset(
    {OrderType.LIMIT, OrderType.STOP_LIMIT, OrderType.LOC}
)

#: Order types that require a stop (trigger) price.
_STOP_ORDER_TYPES: frozenset[OrderType] = frozenset({OrderType.STOP, OrderType.STOP_LIMIT})


@dataclass(frozen=True)
class Order:
    """An instruction to trade ``quantity`` units of ``symbol``.

    Quantity is always strictly positive; direction is carried by ``side``.
    Validation in :meth:`__post_init__` rejects orders that cannot execute
    (missing limit/stop prices, non-positive sizes, bad schedules) so an
    ill-formed order fails loudly at creation rather than silently mis-filling.
    """

    order_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    created_at: pd.Timestamp | None = None
    n_slices: int = 1
    tag: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"order quantity must be > 0, got {self.quantity}")
        if self.order_type in PRICED_ORDER_TYPES and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} order requires a limit_price")
        if self.order_type in _STOP_ORDER_TYPES and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} order requires a stop_price")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError(f"limit_price must be > 0, got {self.limit_price}")
        if self.stop_price is not None and self.stop_price <= 0:
            raise ValueError(f"stop_price must be > 0, got {self.stop_price}")
        if self.order_type in ALGO_ORDER_TYPES and self.n_slices < 1:
            raise ValueError(f"{self.order_type.value} order needs n_slices >= 1")

    @property
    def is_algo(self) -> bool:
        """True for schedule-based (TWAP/VWAP) orders."""
        return self.order_type in ALGO_ORDER_TYPES

    @property
    def signed_quantity(self) -> float:
        """Quantity with the side's sign (+ for buy, - for sell)."""
        return self.side.sign * self.quantity


@dataclass(frozen=True)
class Fill:
    """The execution of ``quantity`` units of an order at ``price``.

    Every cost the trade incurred is recorded alongside the price. ``price`` is
    the raw execution price *before* commission/fees but *after* slippage and
    market impact have moved it away from the reference price; ``slippage_cost``
    and ``impact_cost`` record how much those two effects cost in cash so the
    decomposition can be audited and the reference (mid) price recovered.
    """

    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    timestamp: pd.Timestamp
    commission: float = 0.0
    fees: float = 0.0
    slippage_cost: float = 0.0
    impact_cost: float = 0.0
    liquidity: LiquidityFlag = LiquidityFlag.TAKER
    is_partial: bool = False

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"fill quantity must be > 0, got {self.quantity}")
        if self.price <= 0:
            raise ValueError(f"fill price must be > 0, got {self.price}")

    @property
    def signed_quantity(self) -> float:
        return self.side.sign * self.quantity

    @property
    def total_cost(self) -> float:
        """Total explicit transaction cost (commission + fees) in cash."""
        return self.commission + self.fees

    @property
    def gross_value(self) -> float:
        """Notional traded at the execution price (always positive)."""
        return self.price * self.quantity

    @property
    def cash_flow(self) -> float:
        """Signed cash impact: negative when buying, positive when selling,
        net of commission and fees (which always reduce cash)."""
        return -self.signed_quantity * self.price - self.total_cost


@dataclass(frozen=True)
class Trade:
    """A realised round-trip: a position opened at ``entry`` and (partly)
    closed at ``exit``. ``quantity`` is the size closed by this record.

    ``direction`` is +1 for a long round-trip and -1 for a short one. ``pnl``
    is net of the entry and exit costs apportioned to ``quantity``.
    """

    symbol: str
    direction: int
    quantity: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    pnl: float
    costs: float = 0.0
    bars_held: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be +1 or -1, got {self.direction}")
        if self.quantity <= 0:
            raise ValueError(f"trade quantity must be > 0, got {self.quantity}")

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def return_pct(self) -> float:
        """Return on the entry notional for this round-trip."""
        notional = self.entry_price * self.quantity
        if notional == 0:
            return 0.0
        return self.pnl / notional

    @property
    def gross_pnl(self) -> float:
        """PnL before the apportioned costs were deducted."""
        return self.pnl + self.costs
