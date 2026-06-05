"""Universal pre-trade risk gate (master plan Phase 7, module 7.1).

This module implements a general-purpose pre-trade risk gate that evaluates a
proposed order against live portfolio state before any order reaches the broker.
It serves as the universal choke point for all order flow, regardless of
strategy.

Regulatory motivation
---------------------
The SEC Rule 15c3-5 (Market Access Rule, 2010) requires broker-dealers to
implement risk management controls that include pre-trade checks for order
size, capital thresholds, credit limits, and restricted securities.  This
module provides a strategy-layer implementation of analogous controls suitable
for proprietary algorithmic trading.

Reference: SEC Release No. 34-63241 (2010). "Risk Management Controls for
Brokers or Dealers with Market Access."

Design notes
------------
* All six checks always run.  The gate collects every violation before
  returning so the caller receives a complete picture in one call.
* The gate is pure evaluation: no I/O, no network calls, no side effects.
* ``RiskCheck`` from :mod:`core_trading.risk.pairs_risk` is reused for each
  individual sub-check.  The aggregate result is a richer ``PreTradeDecision``
  that bundles all per-check outcomes, machine-readable violation metadata, and
  a summary ``passed`` flag.
* Margin calculation uses a simple Reg-T-style model: the margin requirement
  for a new position is ``abs(notional) * margin_rate``.  This is a
  conservative simplification -- it does not model portfolio margining, offsets
  between correlated positions, or real-time SPAN/TIMS calculations.  A live
  system should replace ``GateConfig.margin_rates`` with broker API margin
  queries.

Six checks
----------
1. Liquidity     -- order size <= ``adv_participation_cap * adv_30d``
2. Concentration -- resulting position value / NAV <= ``concentration_cap``
3. Exposure      -- resulting gross and net exposure within configured caps
4. Margin        -- post-trade margin requirement <= available margin
5. Restricted    -- symbol not on restricted / insider list (case-insensitive)
6. Kill switch   -- global halt flag overrides all orders when active
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Literal

from core_trading.execution.pairs_execution import (
    Leg,
    PairExecutionResult,
    PairExecutor,
    PairOrder,
)

# Export the pairs-risk RiskCheck as part of our public surface so callers
# can import it from either module without a circular dependency.
from core_trading.risk.pairs_risk import RiskCheck

__all__ = [
    "AssetClass",
    "ProposedOrder",
    "PortfolioState",
    "GateConfig",
    "CheckDetail",
    "PreTradeDecision",
    "PreTradeGate",
    "gate_pair_order",
    "PairGateResult",
    "DEFAULT_CONFIG",
]

# ---------------------------------------------------------------------------
# Domain enums / literals
# ---------------------------------------------------------------------------

AssetClass = Literal["equity", "futures", "fx", "crypto", "other"]

# ---------------------------------------------------------------------------
# Input data objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposedOrder:
    """Description of a single order to be evaluated by the gate.

    Attributes
    ----------
    symbol:
        Ticker symbol (case-preserved; comparison is case-insensitive for the
        restricted-list check only).
    side:
        ``"buy"`` or ``"sell"``.
    quantity:
        Absolute order size (shares, contracts, or units).  Must be > 0.
    price:
        Estimated execution price per unit.  Used to compute order notional.
    asset_class:
        Asset class label; controls the margin rate lookup in
        :class:`GateConfig`.
    """

    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    asset_class: AssetClass = "equity"

    def __post_init__(self) -> None:
        if self.quantity <= 0.0:
            raise ValueError(
                f"ProposedOrder.quantity must be > 0; got {self.quantity!r}"
            )
        if self.price <= 0.0:
            raise ValueError(
                f"ProposedOrder.price must be > 0; got {self.price!r}"
            )
        if self.side not in ("buy", "sell"):
            raise ValueError(
                f"ProposedOrder.side must be 'buy' or 'sell'; got {self.side!r}"
            )

    @property
    def notional(self) -> float:
        """Signed notional value of the order.

        Positive for buys, negative for sells.
        """
        return self.quantity * self.price if self.side == "buy" else -(self.quantity * self.price)

    @property
    def abs_notional(self) -> float:
        """Absolute notional value (always positive)."""
        return self.quantity * self.price


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """Snapshot of current portfolio state used to evaluate proposed orders.

    Attributes
    ----------
    nav:
        Net asset value (total portfolio equity).  Must be > 0.
    positions:
        Mapping of symbol -> signed current position size (shares / units).
        Positive = long, negative = short.  Missing symbols are treated as
        zero position.
    available_margin:
        Cash or margin capacity available for new positions.  Must be >= 0.
    adv:
        Optional mapping of symbol -> 30-day average daily volume (same units
        as position sizes).  When a symbol is absent, the liquidity check is
        skipped for that order (pass-through; this is logged in the decision).
    position_prices:
        Optional mapping of symbol -> current price per unit.  Used to compute
        existing position values for the concentration and exposure checks.
        When absent, ``order.price`` is used as a fallback for the ordered
        symbol; others are estimated at zero (conservative approach: current
        positions are under-counted, which relaxes the check).
    """

    nav: float
    positions: dict[str, float]
    available_margin: float
    adv: dict[str, float] | None = None
    position_prices: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.nav <= 0.0:
            raise ValueError(
                f"PortfolioState.nav must be > 0; got {self.nav!r}"
            )
        if self.available_margin < 0.0:
            raise ValueError(
                f"PortfolioState.available_margin must be >= 0; got {self.available_margin!r}"
            )

    def position_value(self, symbol: str, fallback_price: float) -> float:
        """Return signed notional value of current position in *symbol*.

        Parameters
        ----------
        symbol:
            Symbol to look up.
        fallback_price:
            Price to use when ``position_prices`` does not contain *symbol*.

        Returns
        -------
        float
            Signed position value (positive = long value, negative = short
            value).  Zero when no position.
        """
        pos = self.positions.get(symbol, 0.0)
        if pos == 0.0:
            return 0.0
        prices = self.position_prices or {}
        price = prices.get(symbol, fallback_price)
        return pos * price

    def post_trade_position(self, order: ProposedOrder) -> float:
        """Compute the position size in *order.symbol* after the order fills.

        Parameters
        ----------
        order:
            Proposed order.

        Returns
        -------
        float
            Signed post-trade position size.
        """
        current = self.positions.get(order.symbol, 0.0)
        delta = order.quantity if order.side == "buy" else -order.quantity
        return current + delta

    def post_trade_position_value(self, order: ProposedOrder) -> float:
        """Signed notional value of the post-trade position in *order.symbol*."""
        return self.post_trade_position(order) * order.price

    def gross_exposure(self, order: ProposedOrder) -> float:
        """Sum of absolute notional values across all positions after the order.

        Uses ``order.price`` as the price for the ordered symbol and falls back
        to ``position_prices`` for others; unknown prices are treated as zero.

        Parameters
        ----------
        order:
            Proposed order to include in the post-trade picture.

        Returns
        -------
        float
            Post-trade gross exposure as a dollar amount.
        """
        prices = self.position_prices or {}
        total = 0.0
        # All existing positions (updated for the ordered symbol below)
        for sym, qty in self.positions.items():
            p = prices.get(sym, order.price if sym == order.symbol else 0.0)
            total += abs(qty) * p

        # Adjust for the order on top of existing position
        delta = order.quantity if order.side == "buy" else -order.quantity
        current = self.positions.get(order.symbol, 0.0)
        old_abs = abs(current) * order.price
        new_abs = abs(current + delta) * order.price
        total += new_abs - old_abs
        return total

    def net_exposure(self, order: ProposedOrder) -> float:
        """Signed sum of notional values across all positions after the order.

        Longs add, shorts subtract.  Uses same price logic as
        :meth:`gross_exposure`.

        Parameters
        ----------
        order:
            Proposed order to include in the post-trade picture.

        Returns
        -------
        float
            Post-trade net exposure as a dollar amount (positive = net long).
        """
        prices = self.position_prices or {}
        total = 0.0
        for sym, qty in self.positions.items():
            p = prices.get(sym, order.price if sym == order.symbol else 0.0)
            total += qty * p

        delta = order.quantity if order.side == "buy" else -order.quantity
        current = self.positions.get(order.symbol, 0.0)
        old_signed = current * order.price
        new_signed = (current + delta) * order.price
        total += new_signed - old_signed
        return total


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateConfig:
    """Immutable configuration for the universal pre-trade gate.

    Attributes
    ----------
    adv_participation_cap:
        Maximum fraction of 30-day ADV that a single order may represent.
        Default 0.10 (10%).  Must be in (0, 1].
    concentration_cap:
        Maximum absolute post-trade position value as a fraction of NAV,
        per single symbol.  Default 0.05 (5%).  Must be in (0, 1].
    gross_exposure_cap:
        Maximum allowable post-trade gross exposure as a multiple of NAV.
        E.g. 2.0 means gross leverage up to 2x.  Default 2.0.  Must be > 0.
    net_exposure_cap:
        Maximum allowable absolute post-trade net exposure as a fraction of
        NAV.  Default 1.0.  Must be > 0.
    margin_rates:
        Mapping of asset class label -> Reg-T-style margin rate (fraction of
        notional).  For example ``{"equity": 0.50}`` means 50% margin is
        required.  Asset classes not in the map default to
        ``default_margin_rate``.
    default_margin_rate:
        Fallback margin rate for asset classes not in ``margin_rates``.
        Default 0.50.  Must be in (0, 1].
    restricted_symbols:
        Frozenset of symbols that may not be traded (insider / restricted
        list).  Comparison is always case-insensitive.
    """

    adv_participation_cap: float = 0.10
    concentration_cap: float = 0.05
    gross_exposure_cap: float = 2.0
    net_exposure_cap: float = 1.0
    margin_rates: dict[str, float] = field(default_factory=dict)
    default_margin_rate: float = 0.50
    restricted_symbols: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not (0.0 < self.adv_participation_cap <= 1.0):
            raise ValueError(
                f"adv_participation_cap must be in (0, 1]; got {self.adv_participation_cap!r}"
            )
        if not (0.0 < self.concentration_cap <= 1.0):
            raise ValueError(
                f"concentration_cap must be in (0, 1]; got {self.concentration_cap!r}"
            )
        if self.gross_exposure_cap <= 0.0:
            raise ValueError(
                f"gross_exposure_cap must be > 0; got {self.gross_exposure_cap!r}"
            )
        if self.net_exposure_cap <= 0.0:
            raise ValueError(
                f"net_exposure_cap must be > 0; got {self.net_exposure_cap!r}"
            )
        if not (0.0 < self.default_margin_rate <= 1.0):
            raise ValueError(
                f"default_margin_rate must be in (0, 1]; got {self.default_margin_rate!r}"
            )
        for cls, rate in self.margin_rates.items():
            if not (0.0 < rate <= 1.0):
                raise ValueError(
                    f"margin_rates[{cls!r}] must be in (0, 1]; got {rate!r}"
                )

    def margin_rate_for(self, asset_class: str) -> float:
        """Look up the margin rate for *asset_class*, falling back to default."""
        return self.margin_rates.get(asset_class, self.default_margin_rate)


DEFAULT_CONFIG: GateConfig = GateConfig()

# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckDetail:
    """Machine-readable detail for one sub-check.

    Attributes
    ----------
    check_name:
        Short identifier, e.g. ``"liquidity"`` or ``"kill_switch"``.
    passed:
        ``True`` when the check did not fire.
    limit:
        The configured threshold value (None when not applicable, e.g. for
        the kill switch).
    observed:
        The measured value that was compared against *limit* (None when not
        applicable).
    message:
        Human-readable ASCII description of the outcome.
    """

    check_name: str
    passed: bool
    limit: float | None
    observed: float | None
    message: str


@dataclass(frozen=True, slots=True)
class PreTradeDecision:
    """Aggregate result of the universal pre-trade gate evaluation.

    All six checks always run; every violation is collected.

    Attributes
    ----------
    passed:
        ``True`` only when every sub-check passed.
    checks:
        Tuple of :class:`CheckDetail` in evaluation order:
        liquidity, concentration, exposure, margin, restricted, kill_switch.
    violations:
        Tuple of human-readable ASCII violation messages (empty when passed).
    symbol:
        Symbol of the evaluated order.
    side:
        ``"buy"`` or ``"sell"`` of the evaluated order.
    quantity:
        Absolute quantity of the evaluated order.
    """

    passed: bool
    checks: tuple[CheckDetail, ...]
    violations: tuple[str, ...]
    symbol: str
    side: str
    quantity: float

    @property
    def ok(self) -> bool:
        """Alias for :attr:`passed`."""
        return self.passed

    def as_risk_check(self) -> RiskCheck:
        """Convert to a :class:`~core_trading.risk.pairs_risk.RiskCheck`.

        Returns a ``RiskCheck`` summarising all violations.  Useful for
        passing into existing gate infrastructure that expects the pairs-risk
        result shape.
        """
        return RiskCheck(passed=self.passed, violations=self.violations)


# ---------------------------------------------------------------------------
# Kill-switch implementation
# ---------------------------------------------------------------------------


class _KillSwitch:
    """Thread-safe global kill switch.

    The switch can be injected as a constructor argument to :class:`PreTradeGate`
    so that multiple gate instances can share one switch.  All operations are
    protected by a ``threading.Lock``.
    """

    def __init__(self, *, active: bool = False) -> None:
        self._lock = threading.Lock()
        self._active = active

    @property
    def active(self) -> bool:
        """Return ``True`` when the kill switch is engaged."""
        with self._lock:
            return self._active

    def set(self) -> None:
        """Engage the kill switch; all subsequent gate evaluations fail."""
        with self._lock:
            self._active = True

    def clear(self) -> None:
        """Disengage the kill switch; evaluations resume normally."""
        with self._lock:
            self._active = False


# ---------------------------------------------------------------------------
# Main gate
# ---------------------------------------------------------------------------


class PreTradeGate:
    """Universal pre-trade risk gate.

    Evaluates a :class:`ProposedOrder` against the current
    :class:`PortfolioState` and a set of risk limits in :class:`GateConfig`.

    All six checks (liquidity, concentration, exposure, margin, restricted,
    kill switch) always run.  Every violation is collected before returning
    so that operators receive a complete picture of gate failures in a single
    call.

    Parameters
    ----------
    config:
        Risk limit configuration.  Defaults to :data:`DEFAULT_CONFIG`.
    kill_switch:
        External :class:`_KillSwitch` instance.  When ``None`` (default) a
        fresh switch is created per gate instance.  Pass a shared instance to
        coordinate across multiple strategies.

    Examples
    --------
    >>> gate = PreTradeGate()
    >>> order = ProposedOrder("AAPL", "buy", 100.0, 150.0)
    >>> state = PortfolioState(nav=100_000.0, positions={}, available_margin=50_000.0)
    >>> decision = gate.evaluate(order, state)
    >>> decision.ok
    True
    """

    def __init__(
        self,
        config: GateConfig = DEFAULT_CONFIG,
        *,
        kill_switch: _KillSwitch | None = None,
    ) -> None:
        self._config = config
        self._ks = kill_switch if kill_switch is not None else _KillSwitch()

    # ------------------------------------------------------------------
    # Public kill-switch interface
    # ------------------------------------------------------------------

    def set_kill_switch(self) -> None:
        """Engage the kill switch.  All subsequent evaluations will fail."""
        self._ks.set()

    def clear_kill_switch(self) -> None:
        """Disengage the kill switch.  Normal evaluation resumes."""
        self._ks.clear()

    @property
    def kill_switch_active(self) -> bool:
        """Return ``True`` when the kill switch is currently engaged."""
        return self._ks.active

    # ------------------------------------------------------------------
    # Primary evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        order: ProposedOrder,
        state: PortfolioState,
    ) -> PreTradeDecision:
        """Evaluate *order* against *state* and return a gate decision.

        All six checks are always evaluated.  The order in which checks are
        listed in the returned ``checks`` tuple is fixed:
        1. liquidity, 2. concentration, 3. exposure, 4. margin,
        5. restricted, 6. kill_switch.

        Parameters
        ----------
        order:
            Proposed order to gate.
        state:
            Current portfolio state.

        Returns
        -------
        PreTradeDecision
            ``passed=True`` only when all six checks pass.
        """
        cfg = self._config

        details: list[CheckDetail] = []

        # 1. Liquidity check
        details.append(self._check_liquidity(order, state, cfg))

        # 2. Concentration check
        details.append(self._check_concentration(order, state, cfg))

        # 3. Aggregate exposure check (gross + net combined into one detail entry)
        details.extend(self._check_exposure(order, state, cfg))

        # 4. Margin sufficiency
        details.append(self._check_margin(order, state, cfg))

        # 5. Restricted list
        details.append(self._check_restricted(order, cfg))

        # 6. Kill switch
        details.append(self._check_kill_switch())

        violations = tuple(d.message for d in details if not d.passed)
        passed = len(violations) == 0

        return PreTradeDecision(
            passed=passed,
            checks=tuple(details),
            violations=violations,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_liquidity(
        order: ProposedOrder,
        state: PortfolioState,
        cfg: GateConfig,
    ) -> CheckDetail:
        """Check 1: Order size vs ADV participation cap.

        limit  = adv_participation_cap * adv_30d
        observed = order.quantity
        pass iff observed <= limit
        """
        if state.adv is None or order.symbol not in state.adv:
            # No ADV data available -- pass-through with informational note.
            return CheckDetail(
                check_name="liquidity",
                passed=True,
                limit=None,
                observed=order.quantity,
                message=(
                    f"[liquidity] PASS (no ADV data for {order.symbol}; "
                    "check skipped)"
                ),
            )

        adv_val = float(state.adv[order.symbol])
        limit = cfg.adv_participation_cap * adv_val
        observed = order.quantity
        passed = observed <= limit

        if passed:
            msg = (
                f"[liquidity] PASS symbol={order.symbol} qty={observed:.4g}"
                f" <= cap={limit:.4g}"
                f" (adv={adv_val:.4g} * cap_pct={cfg.adv_participation_cap:.4g})"
            )
        else:
            msg = (
                f"[liquidity] FAIL symbol={order.symbol} qty={observed:.4g}"
                f" > cap={limit:.4g}"
                f" (adv={adv_val:.4g} * cap_pct={cfg.adv_participation_cap:.4g})"
            )

        return CheckDetail(
            check_name="liquidity",
            passed=passed,
            limit=limit,
            observed=observed,
            message=msg,
        )

    @staticmethod
    def _check_concentration(
        order: ProposedOrder,
        state: PortfolioState,
        cfg: GateConfig,
    ) -> CheckDetail:
        """Check 2: Resulting position value vs NAV concentration cap.

        limit    = concentration_cap * nav
        observed = abs(post_trade_position_value) / nav
        pass iff observed <= concentration_cap
        """
        post_val = state.post_trade_position_value(order)
        abs_pos_frac = abs(post_val) / state.nav
        limit = cfg.concentration_cap

        passed = abs_pos_frac <= limit

        if passed:
            msg = (
                f"[concentration] PASS symbol={order.symbol}"
                f" pos_frac={abs_pos_frac:.4g} <= cap={limit:.4g}"
            )
        else:
            msg = (
                f"[concentration] FAIL symbol={order.symbol}"
                f" pos_frac={abs_pos_frac:.4g} > cap={limit:.4g}"
                f" (post_trade_notional={post_val:.4g},"
                f" nav={state.nav:.4g})"
            )

        return CheckDetail(
            check_name="concentration",
            passed=passed,
            limit=limit,
            observed=abs_pos_frac,
            message=msg,
        )

    @staticmethod
    def _check_exposure(
        order: ProposedOrder,
        state: PortfolioState,
        cfg: GateConfig,
    ) -> list[CheckDetail]:
        """Check 3: Post-trade gross and net exposure limits.

        Gross check:
            limit    = gross_exposure_cap * nav
            observed = post_trade_gross_exposure
            pass iff observed <= limit

        Net check:
            limit    = net_exposure_cap * nav
            observed = abs(post_trade_net_exposure)
            pass iff observed <= limit

        Returns a list of two CheckDetail entries (gross, net).
        """
        gross = state.gross_exposure(order)
        net = state.net_exposure(order)
        abs_net = abs(net)

        gross_limit = cfg.gross_exposure_cap * state.nav
        net_limit = cfg.net_exposure_cap * state.nav

        gross_passed = gross <= gross_limit
        net_passed = abs_net <= net_limit

        if gross_passed:
            gross_msg = (
                f"[exposure_gross] PASS gross={gross:.4g} <= cap={gross_limit:.4g}"
            )
        else:
            gross_msg = (
                f"[exposure_gross] FAIL gross={gross:.4g} > cap={gross_limit:.4g}"
                f" (nav={state.nav:.4g},"
                f" gross_cap_mult={cfg.gross_exposure_cap:.4g})"
            )

        if net_passed:
            net_msg = (
                f"[exposure_net] PASS abs_net={abs_net:.4g} <= cap={net_limit:.4g}"
            )
        else:
            net_msg = (
                f"[exposure_net] FAIL abs_net={abs_net:.4g} > cap={net_limit:.4g}"
                f" (nav={state.nav:.4g},"
                f" net_cap_mult={cfg.net_exposure_cap:.4g})"
            )

        return [
            CheckDetail(
                check_name="exposure_gross",
                passed=gross_passed,
                limit=gross_limit,
                observed=gross,
                message=gross_msg,
            ),
            CheckDetail(
                check_name="exposure_net",
                passed=net_passed,
                limit=net_limit,
                observed=abs_net,
                message=net_msg,
            ),
        ]

    @staticmethod
    def _check_margin(
        order: ProposedOrder,
        state: PortfolioState,
        cfg: GateConfig,
    ) -> CheckDetail:
        """Check 4: Post-trade margin requirement vs available margin.

        Simplification note
        -------------------
        The margin requirement is computed as::

            required_margin = abs(order.notional) * margin_rate(asset_class)

        This is a Reg-T-style initial margin approximation.  It does NOT
        model: portfolio margining (netting correlated positions), SPAN/TIMS
        calculations for derivatives, maintenance margin, or intra-day margin
        calls.  For a production system these should be replaced by real-time
        broker margin queries.

        limit    = state.available_margin
        observed = required_margin
        pass iff observed <= limit
        """
        margin_rate = cfg.margin_rate_for(order.asset_class)
        required = order.abs_notional * margin_rate

        passed = required <= state.available_margin

        if passed:
            msg = (
                f"[margin] PASS required={required:.4g}"
                f" <= available={state.available_margin:.4g}"
                f" (notional={order.abs_notional:.4g},"
                f" rate={margin_rate:.4g},"
                f" asset_class={order.asset_class})"
            )
        else:
            msg = (
                f"[margin] FAIL required={required:.4g}"
                f" > available={state.available_margin:.4g}"
                f" (notional={order.abs_notional:.4g},"
                f" rate={margin_rate:.4g},"
                f" asset_class={order.asset_class})"
            )

        return CheckDetail(
            check_name="margin",
            passed=passed,
            limit=state.available_margin,
            observed=required,
            message=msg,
        )

    @staticmethod
    def _check_restricted(
        order: ProposedOrder,
        cfg: GateConfig,
    ) -> CheckDetail:
        """Check 5: Symbol not on restricted / insider list.

        Comparison is always case-insensitive.
        """
        sym_upper = order.symbol.upper()
        restricted_upper = frozenset(s.upper() for s in cfg.restricted_symbols)
        on_list = sym_upper in restricted_upper

        if not on_list:
            msg = f"[restricted] PASS symbol={order.symbol} not on restricted list"
        else:
            msg = (
                f"[restricted] FAIL symbol={order.symbol} is on the restricted list"
            )

        return CheckDetail(
            check_name="restricted",
            passed=not on_list,
            limit=None,
            observed=None,
            message=msg,
        )

    def _check_kill_switch(self) -> CheckDetail:
        """Check 6: Kill switch.

        When the kill switch is active, ALL orders fail regardless of any other
        check outcome.
        """
        active = self._ks.active

        if not active:
            msg = "[kill_switch] PASS kill switch is not active"
        else:
            msg = "[kill_switch] FAIL kill switch is active; all orders blocked"

        return CheckDetail(
            check_name="kill_switch",
            passed=not active,
            limit=None,
            observed=None,
            message=msg,
        )


# ---------------------------------------------------------------------------
# Execution-layer integration adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairGateResult:
    """Result of gating a two-leg pairs order.

    Attributes
    ----------
    passed:
        ``True`` only when both legs pass the gate AND the combined exposure
        check passes.
    leg_decisions:
        Individual :class:`PreTradeDecision` for each leg, in ``(leg_y,
        leg_x)`` order.
    combined_exposure_check:
        :class:`RiskCheck` for the aggregate gross-exposure change from both
        legs combined.
    violations:
        All violation messages aggregated across legs and combined check.
    execution_result:
        The :class:`PairExecutionResult` if *executor* was provided and the
        gate passed; ``None`` otherwise.
    """

    passed: bool
    leg_decisions: tuple[PreTradeDecision, PreTradeDecision]
    combined_exposure_check: RiskCheck
    violations: tuple[str, ...]
    execution_result: PairExecutionResult | None


def gate_pair_order(
    gate: PreTradeGate,
    pair_order: PairOrder,
    state: PortfolioState,
    *,
    executor: PairExecutor | None = None,
) -> PairGateResult:
    """Decompose a :class:`PairOrder` into legs and evaluate each through the gate.

    The function:

    1. Converts ``pair_order.leg_y`` and ``pair_order.leg_x`` to
       :class:`ProposedOrder` objects, preserving signed quantity as ``side``
       and ``quantity``.
    2. Evaluates each leg independently through *gate*.
    3. Checks the **combined** gross-exposure change from both legs against
       the gate's ``gross_exposure_cap``.
    4. If *executor* is provided and the gate passes, calls
       ``executor.execute(pair_order)`` and includes the result.

    Parameters
    ----------
    gate:
        Configured :class:`PreTradeGate` instance.
    pair_order:
        The pairs order whose legs are to be evaluated.
    state:
        Current portfolio snapshot.
    executor:
        Optional :class:`~core_trading.execution.pairs_execution.PairExecutor`.
        When provided and the gate passes, the order is forwarded to execution.
        When the gate fails, the executor is NOT called.

    Returns
    -------
    PairGateResult
        Aggregate gate result including per-leg decisions and optional
        execution result.
    """
    leg_y, leg_x = pair_order.legs

    # Convert each Leg to a ProposedOrder.
    def _leg_to_order(leg: Leg, asset_class: AssetClass = "equity") -> ProposedOrder:
        side: Literal["buy", "sell"] = "buy" if leg.quantity >= 0.0 else "sell"
        return ProposedOrder(
            symbol=leg.symbol,
            side=side,
            quantity=abs(leg.quantity),
            price=leg.decision_price,
            asset_class=asset_class,
        )

    order_y = _leg_to_order(leg_y)
    order_x = _leg_to_order(leg_x)

    dec_y = gate.evaluate(order_y, state)
    dec_x = gate.evaluate(order_x, state)

    # Combined exposure check: sum the notional changes from both legs.
    # We check whether gross exposure after BOTH legs settle stays within cap.
    delta_gross = order_y.abs_notional + order_x.abs_notional
    prices = state.position_prices or {}

    # Current gross exposure (before this pair trade)
    current_gross = sum(
        abs(qty) * prices.get(sym, 0.0)
        for sym, qty in state.positions.items()
    )
    post_gross = current_gross + delta_gross
    gross_cap = gate._config.gross_exposure_cap * state.nav  # noqa: SLF001
    combined_passed = post_gross <= gross_cap

    if combined_passed:
        combined_msg = (
            f"[combined_exposure] PASS post_pair_gross={post_gross:.4g}"
            f" <= cap={gross_cap:.4g}"
        )
    else:
        combined_msg = (
            f"[combined_exposure] FAIL post_pair_gross={post_gross:.4g}"
            f" > cap={gross_cap:.4g}"
        )

    combined_check = RiskCheck(
        passed=combined_passed,
        violations=() if combined_passed else (combined_msg,),
    )

    # Aggregate all violations
    all_violations: list[str] = []
    all_violations.extend(dec_y.violations)
    all_violations.extend(dec_x.violations)
    all_violations.extend(combined_check.violations)

    overall_passed = dec_y.passed and dec_x.passed and combined_check.passed

    # Forward to execution only when gate passes
    exec_result: PairExecutionResult | None = None
    if overall_passed and executor is not None:
        exec_result = executor.execute(pair_order)

    return PairGateResult(
        passed=overall_passed,
        leg_decisions=(dec_y, dec_x),
        combined_exposure_check=combined_check,
        violations=tuple(all_violations),
        execution_result=exec_result,
    )
