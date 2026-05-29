"""Transaction-cost models and the cost-model registry (master plan Phase 3.7 + 3.2).

A backtest is only as honest as its cost model. This module decomposes the cost
of a trade into four auditable components and combines them into a single
:class:`CostBreakdown`:

* **Commission** -- broker charge: per-share, per-trade, percent-of-notional,
  with a floor and (optionally) a cap. See :class:`CommissionSchedule`.
* **Regulatory/exchange fees** -- e.g. the US SEC fee and FINRA TAF, both
  charged on sells only. See :class:`RegulatoryFees`.
* **Slippage** -- the spread paid to cross plus a linear-in-participation term.
  See :class:`SpreadVolumeSlippage`.
* **Market impact** -- the Almgren-Chriss square-root model for the price move a
  parent order causes. See :class:`AlmgrenChrissImpact`.

Slippage and impact move the *fill price* adversely (a buy fills above the
reference, a sell below); commission and fees are charged as separate cash.
:class:`CostModel` ties them together, and a small registry exposes ready-made
broker profiles (``"ibkr"``, ``"ibkr_fixed"``, ``"zero"``, ``"commission_free"``).

Tax-lot accounting (FIFO/LIFO/HIFO) for realised-gain attribution lives in
:class:`TaxLotBook`.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from core_trading.backtest.orders import Side

__all__ = [
    "CommissionSchedule",
    "RegulatoryFees",
    "SpreadVolumeSlippage",
    "AlmgrenChrissImpact",
    "BorrowModel",
    "CostBreakdown",
    "CostModel",
    "LotMethod",
    "TaxLot",
    "RealisedLot",
    "TaxLotBook",
    "register_cost_model",
    "get_cost_model",
    "available_cost_models",
]


@dataclass(frozen=True)
class CommissionSchedule:
    """Broker commission as a function of quantity and notional.

    The charge is ``max(minimum, per_trade + per_share * qty + pct * notional)``,
    optionally capped at ``max_pct_of_notional`` of the trade value (Interactive
    Brokers, for example, caps tiered commissions at 1% of trade value).
    """

    per_share: float = 0.0
    per_trade: float = 0.0
    percent_of_notional: float = 0.0
    minimum: float = 0.0
    max_pct_of_notional: float | None = None

    def __post_init__(self) -> None:
        for name in ("per_share", "per_trade", "percent_of_notional", "minimum"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_pct_of_notional is not None and self.max_pct_of_notional <= 0:
            raise ValueError("max_pct_of_notional must be > 0 when set")

    def compute(self, quantity: float, price: float) -> float:
        """Commission in cash for ``quantity`` shares at ``price``."""
        notional = abs(quantity) * price
        charge = (
            self.per_trade + self.per_share * abs(quantity) + self.percent_of_notional * notional
        )
        charge = max(charge, self.minimum)
        if self.max_pct_of_notional is not None:
            charge = min(charge, self.max_pct_of_notional * notional)
        return charge


@dataclass(frozen=True)
class RegulatoryFees:
    """US-equity style regulatory fees, charged on sells only.

    * SEC Section 31 fee: a tiny fraction of the dollar value sold.
    * FINRA Trading Activity Fee (TAF): per share sold, with a per-trade cap.

    Defaults are zero so non-US asset classes simply pay nothing.
    """

    sec_fee_per_dollar: float = 0.0
    finra_taf_per_share: float = 0.0
    finra_taf_cap: float = 0.0

    def __post_init__(self) -> None:
        for name in ("sec_fee_per_dollar", "finra_taf_per_share", "finra_taf_cap"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")

    def compute(self, side: Side, quantity: float, notional: float) -> float:
        """Regulatory fee in cash. Buys are free; sells pay SEC + TAF."""
        if side is not Side.SELL:
            return 0.0
        sec = self.sec_fee_per_dollar * abs(notional)
        taf = self.finra_taf_per_share * abs(quantity)
        if self.finra_taf_cap > 0:
            taf = min(taf, self.finra_taf_cap)
        return sec + taf


@dataclass(frozen=True)
class SpreadVolumeSlippage:
    """Slippage as half the bid-ask spread plus a linear participation term.

    Per-share cost = ``price * (half_spread_bps + volume_coef_bps * participation)
    / 1e4`` where ``participation = quantity / bar_volume``. The spread term is
    the unavoidable cost of crossing; the participation term penalises taking a
    large share of a bar's traded volume.
    """

    half_spread_bps: float = 1.0
    volume_coef_bps: float = 10.0

    def __post_init__(self) -> None:
        if self.half_spread_bps < 0 or self.volume_coef_bps < 0:
            raise ValueError("slippage coefficients must be >= 0")

    def cost_per_share(self, price: float, quantity: float, bar_volume: float) -> float:
        participation = 0.0 if bar_volume <= 0 else abs(quantity) / bar_volume
        bps = self.half_spread_bps + self.volume_coef_bps * participation
        return price * bps / 1e4


@dataclass(frozen=True)
class AlmgrenChrissImpact:
    """Almgren-Chriss square-root temporary market-impact model.

    Per-share impact = ``eta * volatility * price * sqrt(participation)`` where
    ``participation = quantity / adv`` (average daily volume). The square-root
    dependence on participation is the empirically robust form for the price
    concession a parent order pays. ``volatility`` is the per-period return
    volatility (e.g. daily sigma). Setting ``eta = 0`` disables impact.
    """

    eta: float = 0.1

    def __post_init__(self) -> None:
        if self.eta < 0:
            raise ValueError("eta must be >= 0")

    def cost_per_share(self, price: float, quantity: float, adv: float, volatility: float) -> float:
        if adv <= 0 or volatility <= 0:
            return 0.0
        participation = abs(quantity) / adv
        return self.eta * volatility * price * math.sqrt(participation)


@dataclass(frozen=True)
class BorrowModel:
    """Annualised borrow cost for short positions, accrued per day.

    The rate is looked up per symbol with a fallback default. ``daily_cost``
    converts the annual rate to a daily charge on the absolute market value of a
    short position (``act/365`` convention).
    """

    default_annual_rate: float = 0.005
    per_symbol: dict[str, float] = field(default_factory=dict)
    financing_annual_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.default_annual_rate < 0 or self.financing_annual_rate < 0:
            raise ValueError("rates must be >= 0")

    def annual_rate(self, symbol: str) -> float:
        return self.per_symbol.get(symbol, self.default_annual_rate)

    def daily_borrow_cost(self, symbol: str, short_market_value: float, days: int = 1) -> float:
        """Borrow cost for holding ``short_market_value`` (>=0) for ``days``."""
        if short_market_value <= 0 or days <= 0:
            return 0.0
        return short_market_value * self.annual_rate(symbol) * days / 365.0

    def daily_financing_cost(self, borrowed_cash: float, days: int = 1) -> float:
        """Financing cost on ``borrowed_cash`` (>=0, margin debit) for ``days``."""
        if borrowed_cash <= 0 or days <= 0:
            return 0.0
        return borrowed_cash * self.financing_annual_rate * days / 365.0


@dataclass(frozen=True)
class CostBreakdown:
    """The full cost decomposition for a single (partial) fill."""

    reference_price: float
    fill_price: float
    commission: float
    fees: float
    slippage_cost: float
    impact_cost: float

    @property
    def explicit_cost(self) -> float:
        """Commission + fees (charged as separate cash)."""
        return self.commission + self.fees

    @property
    def implicit_cost(self) -> float:
        """Slippage + impact (embedded in the adverse fill price)."""
        return self.slippage_cost + self.impact_cost

    @property
    def total_cost(self) -> float:
        return self.explicit_cost + self.implicit_cost


@dataclass(frozen=True)
class CostModel:
    """Aggregate cost model combining all four components."""

    commission: CommissionSchedule = field(default_factory=CommissionSchedule)
    fees: RegulatoryFees = field(default_factory=RegulatoryFees)
    slippage: SpreadVolumeSlippage = field(default_factory=SpreadVolumeSlippage)
    impact: AlmgrenChrissImpact = field(default_factory=AlmgrenChrissImpact)
    borrow: BorrowModel = field(default_factory=BorrowModel)

    def price_with_costs(
        self,
        side: Side,
        quantity: float,
        reference_price: float,
        *,
        bar_volume: float = 0.0,
        adv: float = 0.0,
        volatility: float = 0.0,
    ) -> CostBreakdown:
        """Compute the adverse fill price and every cost component.

        Slippage and impact push the price *against* the trader: up for a buy,
        down for a sell. Commission and fees are returned separately as cash.
        """
        if reference_price <= 0:
            raise ValueError("reference_price must be > 0")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")

        slip_per_share = self.slippage.cost_per_share(reference_price, quantity, bar_volume)
        impact_per_share = self.impact.cost_per_share(reference_price, quantity, adv, volatility)
        adverse = (slip_per_share + impact_per_share) * side.sign
        fill_price = reference_price + adverse

        notional = fill_price * quantity
        commission = self.commission.compute(quantity, fill_price)
        fees = self.fees.compute(side, quantity, notional)
        return CostBreakdown(
            reference_price=reference_price,
            fill_price=fill_price,
            commission=commission,
            fees=fees,
            slippage_cost=slip_per_share * quantity,
            impact_cost=impact_per_share * quantity,
        )


# --------------------------------------------------------------------------- #
# Tax-lot accounting
# --------------------------------------------------------------------------- #
class LotMethod(str, Enum):
    """Lot-selection method when closing a position."""

    FIFO = "fifo"
    LIFO = "lifo"
    HIFO = "hifo"


@dataclass
class TaxLot:
    """An open lot: ``quantity`` units acquired at ``price``."""

    quantity: float
    price: float
    opened_at: object = None


@dataclass(frozen=True)
class RealisedLot:
    """A closed (matched) lot with its realised PnL."""

    quantity: float
    cost_basis: float
    proceeds: float

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost_basis


class TaxLotBook:
    """Open-lot book that realises gains by FIFO, LIFO or HIFO when reduced.

    ``add`` opens a lot; ``reduce`` closes ``quantity`` units against existing
    lots in the order dictated by ``method`` and returns the realised lots. The
    book is direction-agnostic: it tracks magnitude, so it serves both long
    (acquire then sell) and short (sell then cover) inventories with the cost
    basis interpreted accordingly by the caller.
    """

    def __init__(self, method: LotMethod = LotMethod.FIFO) -> None:
        self.method = method
        self._lots: deque[TaxLot] = deque()

    def __len__(self) -> int:
        return len(self._lots)

    @property
    def open_quantity(self) -> float:
        return sum(lot.quantity for lot in self._lots)

    def add(self, quantity: float, price: float, opened_at: object = None) -> None:
        if quantity <= 0:
            raise ValueError("lot quantity must be > 0")
        if price <= 0:
            raise ValueError("lot price must be > 0")
        self._lots.append(TaxLot(quantity=quantity, price=price, opened_at=opened_at))

    def _next_index(self) -> int:
        if self.method is LotMethod.FIFO:
            return 0
        if self.method is LotMethod.LIFO:
            return len(self._lots) - 1
        # HIFO: highest cost basis first.
        return max(range(len(self._lots)), key=lambda i: self._lots[i].price)

    def reduce(self, quantity: float, price: float) -> list[RealisedLot]:
        """Close ``quantity`` units at ``price``; return the realised lots.

        Raises ``ValueError`` if more is closed than is open.
        """
        if quantity <= 0:
            raise ValueError("reduce quantity must be > 0")
        if quantity > self.open_quantity + 1e-9:
            raise ValueError(f"cannot close {quantity}; only {self.open_quantity} open")
        remaining = quantity
        realised: list[RealisedLot] = []
        while remaining > 1e-12:
            idx = self._next_index()
            lot = self._lots[idx]
            matched = min(remaining, lot.quantity)
            realised.append(
                RealisedLot(
                    quantity=matched,
                    cost_basis=matched * lot.price,
                    proceeds=matched * price,
                )
            )
            lot.quantity -= matched
            remaining -= matched
            if lot.quantity <= 1e-12:
                del self._lots[idx]
        return realised


# --------------------------------------------------------------------------- #
# Registry of broker cost profiles
# --------------------------------------------------------------------------- #
def _ibkr_tiered() -> CostModel:
    """Interactive Brokers tiered US equities: $0.0035/share, $0.35 min, 1% cap,
    plus SEC + FINRA TAF regulatory fees on sells."""
    return CostModel(
        commission=CommissionSchedule(per_share=0.0035, minimum=0.35, max_pct_of_notional=0.01),
        fees=RegulatoryFees(
            sec_fee_per_dollar=8.0e-6,
            finra_taf_per_share=0.000166,
            finra_taf_cap=8.30,
        ),
    )


def _ibkr_fixed() -> CostModel:
    """Interactive Brokers fixed US equities: $0.005/share, $1.00 min, 1% cap."""
    return CostModel(
        commission=CommissionSchedule(per_share=0.005, minimum=1.0, max_pct_of_notional=0.01),
        fees=RegulatoryFees(
            sec_fee_per_dollar=8.0e-6,
            finra_taf_per_share=0.000166,
            finra_taf_cap=8.30,
        ),
    )


def _zero() -> CostModel:
    """Frictionless model: no commission, fees, slippage, impact, borrow or
    financing. For testing mode-agreement and analytic checks, not for honest
    backtests."""
    return CostModel(
        slippage=SpreadVolumeSlippage(half_spread_bps=0.0, volume_coef_bps=0.0),
        impact=AlmgrenChrissImpact(eta=0.0),
        borrow=BorrowModel(default_annual_rate=0.0, financing_annual_rate=0.0),
    )


def _commission_free() -> CostModel:
    """Retail commission-free (Alpaca-style): no commission, but realistic
    slippage/impact and SEC/TAF regulatory fees on sells still apply."""
    return CostModel(
        fees=RegulatoryFees(
            sec_fee_per_dollar=8.0e-6,
            finra_taf_per_share=0.000166,
            finra_taf_cap=8.30,
        ),
    )


_REGISTRY: dict[str, Callable[[], CostModel]] = {
    "ibkr": _ibkr_tiered,
    "ibkr_fixed": _ibkr_fixed,
    "zero": _zero,
    "commission_free": _commission_free,
}


def register_cost_model(name: str, factory: Callable[[], CostModel]) -> None:
    """Register a named cost-model factory (overwrites an existing name)."""
    _REGISTRY[name] = factory


def get_cost_model(name: str) -> CostModel:
    """Return a fresh cost model for ``name``; raises ``KeyError`` if unknown."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown cost model {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def available_cost_models() -> list[str]:
    return sorted(_REGISTRY)
