"""Portfolio and position accounting (master plan Phase 3.3).

:class:`Portfolio` is the book of record for a backtest. It holds cash and a
:class:`Position` per symbol, applies :class:`~core_trading.backtest.orders.Fill`
records to update both, and realises PnL through a tax-lot book so the closing
method (FIFO/LIFO/HIFO) is honoured. It marks positions to market, accrues
borrow and financing costs, and exposes the exposure/leverage statistics the
risk layer needs.

Sign convention: a position ``quantity`` is signed (positive long, negative
short). Cash decreases when buying and increases when selling, always net of
the explicit costs already embedded in :attr:`Fill.cash_flow`. Equity is
``cash + sum(quantity * mark_price)``, which correctly subtracts the value of
short positions (shares owed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core_trading.backtest.costs import BorrowModel, LotMethod, TaxLotBook
from core_trading.backtest.orders import Fill, Trade

__all__ = ["Position", "Portfolio"]


@dataclass
class Position:
    """A signed position in one symbol with a tax-lot cost-basis book."""

    symbol: str
    lot_method: LotMethod = LotMethod.FIFO
    quantity: float = 0.0
    realised_pnl: float = 0.0
    _book: TaxLotBook = field(init=False, repr=False)
    _entry_time: pd.Timestamp | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._book = TaxLotBook(self.lot_method)

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) <= 1e-12

    @property
    def direction(self) -> int:
        if self.quantity > 0:
            return 1
        if self.quantity < 0:
            return -1
        return 0

    @property
    def avg_price(self) -> float:
        """Volume-weighted entry price of the open inventory (0 when flat)."""
        open_qty = self._book.open_quantity
        if open_qty <= 0:
            return 0.0
        basis = sum(lot.quantity * lot.price for lot in self._book._lots)
        return basis / open_qty

    def market_value(self, price: float) -> float:
        """Signed mark-to-market value at ``price``."""
        return self.quantity * price

    def unrealised_pnl(self, price: float) -> float:
        if self.is_flat:
            return 0.0
        return self.direction * (price - self.avg_price) * abs(self.quantity)


class Portfolio:
    """Cash + positions book that applies fills and tracks equity over time."""

    def __init__(
        self,
        initial_cash: float,
        lot_method: LotMethod = LotMethod.FIFO,
        borrow_model: BorrowModel | None = None,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.lot_method = lot_method
        self.borrow_model = borrow_model or BorrowModel()
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.total_costs = 0.0
        self.total_borrow_cost = 0.0
        self.equity_curve: list[tuple[pd.Timestamp, float]] = []
        self.position_history: list[tuple[pd.Timestamp, str, float, float]] = []

    # ------------------------------------------------------------------ access
    def position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol, lot_method=self.lot_method)
        return self.positions[symbol]

    @property
    def realised_pnl(self) -> float:
        return sum(p.realised_pnl for p in self.positions.values())

    def equity(self, prices: dict[str, float]) -> float:
        """Total equity = cash + marked value of all positions."""
        mtm = 0.0
        for sym, pos in self.positions.items():
            if pos.is_flat:
                continue
            price = prices.get(sym)
            if price is not None:
                mtm += pos.market_value(price)
        return self.cash + mtm

    def gross_exposure(self, prices: dict[str, float]) -> float:
        return sum(
            abs(pos.market_value(prices[sym]))
            for sym, pos in self.positions.items()
            if not pos.is_flat and sym in prices
        )

    def net_exposure(self, prices: dict[str, float]) -> float:
        return sum(
            pos.market_value(prices[sym])
            for sym, pos in self.positions.items()
            if not pos.is_flat and sym in prices
        )

    def leverage(self, prices: dict[str, float]) -> float:
        equity = self.equity(prices)
        if equity <= 0:
            return float("inf")
        return self.gross_exposure(prices) / equity

    # -------------------------------------------------------------------- fills
    def apply_fill(self, fill: Fill, bars_held: int = 0) -> list[Trade]:
        """Apply ``fill`` to cash and the relevant position.

        Returns any :class:`Trade` records realised when the fill reduced or
        flipped an existing position. A fill that grows a position (or opens a
        new one) realises nothing and returns an empty list.
        """
        pos = self.position(fill.symbol)
        self.cash += fill.cash_flow
        self.total_costs += fill.total_cost

        fill_signed = fill.signed_quantity
        realised: list[Trade] = []

        if pos.is_flat or (pos.direction == fill.side.sign):
            # Opening or adding in the same direction: just record a lot.
            pos._book.add(fill.quantity, fill.price, fill.timestamp)
            if pos.is_flat:
                pos._entry_time = fill.timestamp
            pos.quantity += fill_signed
            return realised

        # Opposite direction: reduce, possibly flipping.
        closing_qty = min(abs(fill_signed), abs(pos.quantity))
        direction = pos.direction
        entry_time = pos._entry_time or fill.timestamp
        realised_lots = pos._book.reduce(closing_qty, fill.price)
        trade_pnl = 0.0
        closed = 0.0
        for lot in realised_lots:
            entry_price = lot.cost_basis / lot.quantity
            trade_pnl += direction * (fill.price - entry_price) * lot.quantity
            closed += lot.quantity
        pos.realised_pnl += trade_pnl
        pos.quantity += fill_signed

        # Apportion this fill's explicit cost to the closed fraction.
        apportioned_cost = fill.total_cost * (closed / fill.quantity)
        avg_entry = (
            sum(lot.cost_basis for lot in realised_lots) / closed if closed > 0 else fill.price
        )
        realised.append(
            Trade(
                symbol=fill.symbol,
                direction=direction,
                quantity=closed,
                entry_time=entry_time,
                exit_time=fill.timestamp,
                entry_price=avg_entry,
                exit_price=fill.price,
                pnl=trade_pnl - apportioned_cost,
                costs=apportioned_cost,
                bars_held=bars_held,
            )
        )
        self.trades.extend(realised)

        # If the fill flipped the position, open the remainder the other way.
        leftover = abs(fill_signed) - closing_qty
        if leftover > 1e-12:
            pos._book.add(leftover, fill.price, fill.timestamp)
            pos._entry_time = fill.timestamp
        elif pos.is_flat:
            pos._entry_time = None
        return realised

    # -------------------------------------------------------- carrying costs
    def accrue_carry(self, prices: dict[str, float], days: int = 1) -> float:
        """Deduct borrow cost on shorts and financing on margin debit.

        Returns the total cash charged. Called once per bar/day by the engine.
        """
        charge = 0.0
        for sym, pos in self.positions.items():
            if pos.is_short and sym in prices:
                smv = abs(pos.market_value(prices[sym]))
                charge += self.borrow_model.daily_borrow_cost(sym, smv, days)
        if self.cash < 0:
            charge += self.borrow_model.daily_financing_cost(-self.cash, days)
        self.cash -= charge
        self.total_borrow_cost += charge
        self.total_costs += charge
        return charge

    # ------------------------------------------------------------- recording
    def record(self, timestamp: pd.Timestamp, prices: dict[str, float]) -> float:
        """Snapshot equity and open positions; return the equity value."""
        equity = self.equity(prices)
        self.equity_curve.append((timestamp, equity))
        for sym, pos in self.positions.items():
            if not pos.is_flat:
                price = prices.get(sym, pos.avg_price)
                self.position_history.append((timestamp, sym, pos.quantity, price))
        return equity

    def equity_series(self) -> pd.Series:
        """The recorded equity curve as a time-indexed Series."""
        if not self.equity_curve:
            return pd.Series(dtype=float, name="equity")
        idx = pd.DatetimeIndex([t for t, _ in self.equity_curve])
        return pd.Series([v for _, v in self.equity_curve], index=idx, name="equity")
