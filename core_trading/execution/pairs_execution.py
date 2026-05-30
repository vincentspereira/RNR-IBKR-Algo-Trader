"""Pairs execution engine (master plan Phase 4.7).

Self-contained, deterministic, backtest/sim-friendly execution module for
pairs trades.  The module is synchronous and broker-agnostic: all fills are
supplied by a pluggable :class:`FillModel`, making the logic fully unit-testable
without a live broker connection.

Design goals
------------
* Both-legs-or-none atomicity: if either leg cannot be fully filled, neither
  fill is reported (in a live system the filled leg would be
  cancelled/flattened before returning).
* TWAP slicing for large orders: if the absolute quantity exceeds
  ``max_participation * bar_volume`` the order is split into
  ``twap_slices`` near-equal child quantities.
* Implementation shortfall tracking per leg and notional-weighted across the
  pair.

Shortfall sign convention (POSITIVE = COST)
-------------------------------------------
For a BUY (quantity > 0)::

    shortfall_bps = (avg_price / decision_price - 1) * 1e4

For a SELL (quantity < 0)::

    shortfall_bps = (decision_price / avg_price - 1) * 1e4

A worse execution price always produces a *positive* shortfall regardless of
direction.  The two formulas are equivalent to::

    shortfall_bps = sign(quantity) * (avg_price / decision_price - 1) * 1e4

where ``sign`` is +1 for buys and -1 for sells -- but the explicit
buy/sell branching is used in the code to make the intent unambiguous.

Pair-level shortfall is the notional-weighted average::

    pair_shortfall = sum(|qty_i| * price_i * shortfall_i) / sum(|qty_i| * price_i)
"""
from __future__ import annotations

import math
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "Leg",
    "PairOrder",
    "LegFill",
    "PairExecutionResult",
    "FillModel",
    "DeterministicFillModel",
    "ExecutionConfig",
    "twap_schedule",
    "PairExecutor",
]

# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Leg:
    """One leg of a pairs trade.

    Attributes
    ----------
    symbol:
        Ticker symbol.
    quantity:
        Signed quantity -- positive means BUY, negative means SELL.
    decision_price:
        Mid/last price at the moment the trade was decided.  Used as the
        reference for implementation shortfall calculation.
    """

    symbol: str
    quantity: float
    decision_price: float


@dataclass(frozen=True, slots=True)
class PairOrder:
    """Two-leg pairs order.

    Attributes
    ----------
    pair_id:
        Unique identifier for this pair trade instance.
    leg_y:
        The *y* (dependent) leg.
    leg_x:
        The *x* (independent / hedge) leg.
    """

    pair_id: str
    leg_y: Leg
    leg_x: Leg

    @property
    def legs(self) -> tuple[Leg, Leg]:
        """Return both legs as ``(leg_y, leg_x)``."""
        return (self.leg_y, self.leg_x)


@dataclass(frozen=True, slots=True)
class LegFill:
    """Execution outcome for a single leg.

    Attributes
    ----------
    symbol:
        Ticker symbol.
    quantity:
        Signed total quantity filled.
    avg_price:
        Volume-weighted average fill price across all slices.
    n_slices:
        Number of TWAP slices used (1 when no slicing was needed).
    shortfall_bps:
        Implementation shortfall in basis points relative to
        ``decision_price``.  Defined so that a WORSE fill is always a
        POSITIVE cost:

        * BUY  (quantity > 0): ``(avg_price / decision_price - 1) * 1e4``
        * SELL (quantity < 0): ``(decision_price / avg_price - 1) * 1e4``
    """

    symbol: str
    quantity: float
    avg_price: float
    n_slices: int
    shortfall_bps: float


@dataclass(frozen=True, slots=True)
class PairExecutionResult:
    """Outcome of executing a :class:`PairOrder`.

    Attributes
    ----------
    pair_id:
        Mirrors ``PairOrder.pair_id``.
    filled:
        ``True`` only when *both* legs were fully filled.
    fills:
        Per-leg fill details; empty tuple when ``filled`` is ``False``.
    shortfall_bps:
        Notional-weighted average implementation shortfall across both legs
        (basis points, positive = cost).  ``0.0`` when not filled.
    reason:
        ``"filled"`` | ``"leg_failed"`` | ``"empty"``.
    """

    pair_id: str
    filled: bool
    fills: tuple[LegFill, ...]
    shortfall_bps: float
    reason: str


# ---------------------------------------------------------------------------
# Fill protocol and deterministic implementation
# ---------------------------------------------------------------------------


class FillModel(typing.Protocol):
    """Injectable fill abstraction enabling deterministic backtesting.

    Parameters
    ----------
    symbol:
        Ticker being filled.
    quantity:
        Signed quantity for this child slice (positive = BUY, negative = SELL).
    decision_price:
        Reference price from :class:`Leg`; used by concrete implementations
        to compute a realistic fill price.
    bar_volume:
        Total bar volume for the symbol; provided for implementations that
        want to model market impact or participation constraints.

    Returns
    -------
    ``(filled_qty, fill_price)`` on success, or ``None`` when the slice is
    rejected (e.g. halted symbol, insufficient liquidity).
    """

    def fill_slice(
        self,
        symbol: str,
        quantity: float,
        decision_price: float,
        bar_volume: float,
    ) -> tuple[float, float] | None:
        """Attempt to fill one TWAP child slice.

        Returns ``(filled_qty, fill_price)`` or ``None`` for rejection.
        """
        ...


@dataclass
class DeterministicFillModel:
    """Concrete fill model with fixed slippage for testing and simulation.

    Fills at ``decision_price`` adjusted by ``slippage_bps`` in the *adverse*
    direction:

    * BUY:  ``fill_price = decision_price * (1 + slippage_bps / 1e4)``
    * SELL: ``fill_price = decision_price * (1 - slippage_bps / 1e4)``

    Parameters
    ----------
    slippage_bps:
        Adverse slippage in basis points applied to every slice.
    reject_symbols:
        Symbols for which every fill attempt returns ``None``.
    max_fill_ratio:
        Fraction of the requested slice quantity actually filled (1.0 = full
        fill, 0.5 = half fill).  Useful for testing partial-fill logic.
    """

    slippage_bps: float = 0.0
    reject_symbols: frozenset[str] = field(default_factory=frozenset)
    max_fill_ratio: float = 1.0

    def fill_slice(
        self,
        symbol: str,
        quantity: float,
        decision_price: float,
        bar_volume: float,  # noqa: ARG002
    ) -> tuple[float, float] | None:
        """Fill one slice deterministically.

        Returns ``None`` when *symbol* is in ``reject_symbols``.
        Otherwise returns ``(filled_qty, fill_price)``.
        """
        if symbol in self.reject_symbols:
            return None
        filled_qty = quantity * self.max_fill_ratio
        if quantity >= 0.0:
            fill_price = decision_price * (1.0 + self.slippage_bps / 1e4)
        else:
            fill_price = decision_price * (1.0 - self.slippage_bps / 1e4)
        return filled_qty, fill_price


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-9  # fractional tolerance for "fully filled" check


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Parameters controlling pairs execution behaviour.

    Attributes
    ----------
    max_participation:
        Participation rate threshold.  When ``|qty| > max_participation *
        bar_volume``, the leg is split into ``twap_slices`` child orders.
        Must be in ``(0, 1]``.
    twap_slices:
        Number of TWAP child slices for large legs.  Must be >= 1.
    require_full_fill:
        When ``True`` (default), a leg that cannot accumulate the full
        requested quantity (within floating-point tolerance) is treated as a
        failure, triggering both-legs-or-none cancellation.
    """

    max_participation: float = 0.20
    twap_slices: int = 5
    require_full_fill: bool = True

    def __post_init__(self) -> None:
        if not (0.0 < self.max_participation <= 1.0):
            raise ValueError(
                f"max_participation must be in (0, 1]; got {self.max_participation}"
            )
        if self.twap_slices < 1:
            raise ValueError(
                f"twap_slices must be >= 1; got {self.twap_slices}"
            )


_DEFAULT_CONFIG = ExecutionConfig()

# ---------------------------------------------------------------------------
# TWAP schedule helper
# ---------------------------------------------------------------------------


def twap_schedule(total_qty: float, n_slices: int) -> list[float]:
    """Split *total_qty* into *n_slices* near-equal signed child quantities.

    The sign of each child equals the sign of *total_qty*.  The last slice
    absorbs any floating-point remainder so that the sum of child quantities
    is *exactly* equal to *total_qty*.

    Parameters
    ----------
    total_qty:
        Signed total quantity to be executed.
    n_slices:
        Number of child slices.  Must be >= 1.

    Returns
    -------
    List of signed child quantities with length *n_slices*.

    Raises
    ------
    ValueError:
        When *n_slices* < 1.

    Examples
    --------
    >>> twap_schedule(100.0, 4)
    [25.0, 25.0, 25.0, 25.0]
    >>> twap_schedule(101.0, 4)  # last slice absorbs remainder
    [25.25, 25.25, 25.25, 25.25]
    >>> twap_schedule(-90.0, 3)
    [-30.0, -30.0, -30.0]
    """
    if n_slices < 1:
        raise ValueError(f"n_slices must be >= 1; got {n_slices}")
    base = total_qty / n_slices
    slices = [base] * (n_slices - 1)
    last = total_qty - sum(slices)
    slices.append(last)
    return slices


# ---------------------------------------------------------------------------
# Leg execution helper
# ---------------------------------------------------------------------------


def _execute_leg(
    leg: Leg,
    fill_model: FillModel,
    config: ExecutionConfig,
    bar_vol: float,
) -> LegFill | None:
    """Attempt to fully execute one leg.

    Returns a :class:`LegFill` on success or ``None`` on failure.  Failure
    means:

    * Any slice returned ``None`` from the fill model, or
    * ``require_full_fill`` is ``True`` and the accumulated quantity is less
      than the requested quantity (outside floating-point tolerance).
    """
    qty = leg.quantity
    abs_qty = abs(qty)

    n_slices = config.twap_slices if abs_qty > config.max_participation * bar_vol else 1

    schedule = twap_schedule(qty, n_slices)

    total_filled_qty = 0.0
    total_notional = 0.0

    for child_qty in schedule:
        result = fill_model.fill_slice(
            leg.symbol, child_qty, leg.decision_price, bar_vol
        )
        if result is None:
            return None
        filled_qty, fill_price = result
        total_filled_qty += filled_qty
        total_notional += abs(filled_qty) * fill_price

    if config.require_full_fill and abs(total_filled_qty) < abs_qty * (1.0 - _TOLERANCE):
        return None

    avg_price = total_notional / abs(total_filled_qty) if total_filled_qty != 0.0 else 0.0

    if qty >= 0.0:
        shortfall_bps = (avg_price / leg.decision_price - 1.0) * 1e4
    else:
        shortfall_bps = (leg.decision_price / avg_price - 1.0) * 1e4

    return LegFill(
        symbol=leg.symbol,
        quantity=total_filled_qty,
        avg_price=avg_price,
        n_slices=n_slices,
        shortfall_bps=shortfall_bps,
    )


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


class PairExecutor:
    """Execute a :class:`PairOrder` using an injectable :class:`FillModel`.

    Both legs must be filled before any fill is reported (both-legs-or-none
    semantics).  In a live system, when one leg has been filled but the other
    fails, the filled leg must be cancelled or flattened before returning
    the ``"leg_failed"`` result -- that logic is the responsibility of the
    live trading harness, not this module.

    Parameters
    ----------
    fill_model:
        Implementation of :class:`FillModel` that supplies fill prices.
    config:
        Execution parameters.  Defaults to :class:`ExecutionConfig` with
        all default values.
    """

    def __init__(
        self,
        fill_model: FillModel,
        config: ExecutionConfig = _DEFAULT_CONFIG,
    ) -> None:
        self._fill_model = fill_model
        self._config = config

    def execute(
        self,
        order: PairOrder,
        *,
        bar_volume: Mapping[str, float] | None = None,
    ) -> PairExecutionResult:
        """Execute a pairs order and return the aggregated result.

        Parameters
        ----------
        order:
            The two-leg pairs order to execute.
        bar_volume:
            Optional mapping of ``symbol -> bar_volume``.  When provided, any
            leg whose ``|qty|`` exceeds ``config.max_participation *
            bar_volume[symbol]`` is automatically split into TWAP slices.
            Missing symbols default to a very large volume so that no
            unintended slicing occurs for unknown symbols.

        Returns
        -------
        :class:`PairExecutionResult` with ``filled=True`` only when both
        legs were fully filled.

        Notes
        -----
        Zero-quantity orders (both legs zero) return
        ``filled=False, reason="empty"`` without calling the fill model.
        """
        leg_y, leg_x = order.legs

        # Guard: zero-quantity order.
        if leg_y.quantity == 0.0 and leg_x.quantity == 0.0:
            return PairExecutionResult(
                pair_id=order.pair_id,
                filled=False,
                fills=(),
                shortfall_bps=0.0,
                reason="empty",
            )

        def _bar_vol(symbol: str) -> float:
            if bar_volume is None:
                return math.inf
            return bar_volume.get(symbol, math.inf)

        fill_y = _execute_leg(leg_y, self._fill_model, self._config, _bar_vol(leg_y.symbol))
        fill_x = _execute_leg(leg_x, self._fill_model, self._config, _bar_vol(leg_x.symbol))

        if fill_y is None or fill_x is None:
            # Both-legs-or-none: in live trading the filled leg is flattened.
            return PairExecutionResult(
                pair_id=order.pair_id,
                filled=False,
                fills=(),
                shortfall_bps=0.0,
                reason="leg_failed",
            )

        pair_shortfall = _notional_weighted_shortfall(
            [(fill_y, leg_y.decision_price), (fill_x, leg_x.decision_price)]
        )

        return PairExecutionResult(
            pair_id=order.pair_id,
            filled=True,
            fills=(fill_y, fill_x),
            shortfall_bps=pair_shortfall,
            reason="filled",
        )


# ---------------------------------------------------------------------------
# Shortfall aggregation
# ---------------------------------------------------------------------------


def _notional_weighted_shortfall(
    fills_with_prices: list[tuple[LegFill, float]],
) -> float:
    """Compute notional-weighted shortfall across a collection of leg fills.

    Parameters
    ----------
    fills_with_prices:
        Sequence of ``(LegFill, decision_price)`` pairs.

    Returns
    -------
    Notional-weighted average ``shortfall_bps`` (basis points).
    """
    total_weight = 0.0
    weighted_sum = 0.0
    for leg_fill, decision_price in fills_with_prices:
        weight = abs(leg_fill.quantity) * decision_price
        total_weight += weight
        weighted_sum += weight * leg_fill.shortfall_bps
    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight
