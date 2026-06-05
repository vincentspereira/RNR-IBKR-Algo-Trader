"""Pairs-trading risk manager (master plan Phase 4.6).

Pre-trade position-limit checks, real-time spread-divergence alerts, and
daily VaR / drawdown circuit breakers for a pairs-trading strategy.

Design notes
------------
* All limit checks collect every violation before returning so the caller
  receives a complete picture in one call rather than discovering violations
  one at a time.
* ``value_at_risk`` from :mod:`core_trading.backtest.metrics` returns a
  **positive** loss fraction (it internally negates the left-tail quantile).
  ``var_check`` therefore treats the returned value directly as a loss
  magnitude and compares it against ``RiskLimits.var_limit`` without further
  sign manipulation.
* ``max_drawdown`` from the same module also returns a **positive** fraction.
  ``daily_check`` computes the most-recent one-day return directly from the
  equity series and compares ``-return`` against ``daily_drawdown_limit`` so
  that a day with a -6% move registers as a 0.06 loss against a 0.05 limit.
* The per-symbol weight check in ``pre_trade`` is documented as a proxy for
  the per-pair cap: in a dollar-neutral pairs book the net weight of each
  leg is the signed pair weight, so capping each symbol's absolute weight
  caps each pair's exposure.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from core_trading.backtest.metrics import max_drawdown, value_at_risk

__all__ = [
    "RiskLimits",
    "RiskCheck",
    "DivergenceAlert",
    "PairsRiskManager",
    "DEFAULT_LIMITS",
]

# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Immutable configuration for all pairs-trading risk gates.

    Attributes
    ----------
    per_pair_cap:
        Maximum absolute weight allowed for any single symbol (proxy for the
        per-pair notional cap).  Default 2% of NAV.
    sector_cap:
        Maximum gross exposure in any one sector as a fraction of total gross
        exposure.  Only enforced when sector labels are supplied.  Default 30%.
    gross_leverage_cap:
        Maximum sum of absolute weights across all symbols.  Default 2.0x.
    divergence_z:
        Z-score magnitude at which a spread is considered to have critically
        diverged.  Default 3.5.
    daily_drawdown_limit:
        Maximum one-day loss (as a positive fraction of NAV) before the daily
        circuit breaker trips.  Default 5%.
    monthly_drawdown_limit:
        Maximum peak-to-trough drawdown over the most recent ~21 observations
        (one calendar month of trading days) before the monthly gate trips.
        Default 10%.
    var_limit:
        Maximum acceptable one-day historical VaR loss (positive fraction of
        NAV) at confidence level ``1 - var_alpha``.  Default 5%.
    var_alpha:
        Left-tail probability for VaR / CVaR calculations.  Default 0.05
        (i.e. 95% confidence).
    """

    per_pair_cap: float = 0.02
    sector_cap: float = 0.30
    gross_leverage_cap: float = 2.0
    divergence_z: float = 3.5
    daily_drawdown_limit: float = 0.05
    monthly_drawdown_limit: float = 0.10
    var_limit: float = 0.05
    var_alpha: float = 0.05
    # Materiality floor for the sector-concentration check: the check is
    # skipped while total gross exposure is below this fraction of NAV. A
    # *relative* concentration measure is meaningless for a sparse book --
    # the first pair to enter is always ~100% of a tiny gross. 0.0 (the
    # default) preserves the original always-on behaviour.
    sector_check_min_gross: float = 0.0

    def __post_init__(self) -> None:
        """Validate limits (strictly positive; the materiality floor may be 0)."""
        for attr in (
            "per_pair_cap",
            "sector_cap",
            "gross_leverage_cap",
            "divergence_z",
            "daily_drawdown_limit",
            "monthly_drawdown_limit",
            "var_limit",
            "var_alpha",
        ):
            val = getattr(self, attr)
            if val <= 0:
                raise ValueError(f"RiskLimits.{attr} must be > 0, got {val!r}")
        if self.sector_check_min_gross < 0:
            raise ValueError(
                "RiskLimits.sector_check_min_gross must be >= 0, got "
                f"{self.sector_check_min_gross!r}"
            )


# Module-level singleton used as the default for PairsRiskManager.
DEFAULT_LIMITS: RiskLimits = RiskLimits()


@dataclass(frozen=True, slots=True)
class RiskCheck:
    """Outcome of a risk gate evaluation.

    Attributes
    ----------
    passed:
        ``True`` when no limits were breached.
    violations:
        Tuple of human-readable ASCII violation strings; empty when passed.
    """

    passed: bool
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Alias for :attr:`passed`; returns ``True`` when no violations exist."""
        return self.passed


@dataclass(frozen=True, slots=True)
class DivergenceAlert:
    """Spread-divergence alert for a single pair.

    Attributes
    ----------
    pair_id:
        Identifier for the pair (e.g. ``"GLD/SLV"``).
    zscore:
        Current standardised spread z-score.
    breached:
        ``True`` when ``|zscore| > limits.divergence_z``.
    severity:
        One of ``"none"``, ``"warning"``, or ``"critical"``; ``"critical"``
        when breached, ``"warning"`` when ``|z| > 0.8 * divergence_z``.
    """

    pair_id: str
    zscore: float
    breached: bool
    severity: Literal["none", "warning", "critical"]


# ---------------------------------------------------------------------------
# Risk manager
# ---------------------------------------------------------------------------


class PairsRiskManager:
    """Pre-trade, real-time, and daily risk gates for pairs trading.

    Parameters
    ----------
    limits:
        Risk configuration.  Defaults to :data:`DEFAULT_LIMITS` (module-level
        singleton) so the default argument is never a mutable object.

    Examples
    --------
    >>> mgr = PairsRiskManager()
    >>> chk = mgr.pre_trade({"AAPL": 0.01, "MSFT": -0.01})
    >>> chk.ok
    True
    """

    def __init__(self, limits: RiskLimits = DEFAULT_LIMITS) -> None:
        self._limits = limits

    # ------------------------------------------------------------------
    # Pre-trade limit check
    # ------------------------------------------------------------------

    def pre_trade(
        self,
        proposed_weights: Mapping[str, float],
        *,
        sectors: Mapping[str, str] | None = None,
    ) -> RiskCheck:
        """Check proposed portfolio weights against pre-trade limits.

        Three checks are applied (all violations are collected):

        (a) **Per-symbol cap**: ``|weight[symbol]| <= per_pair_cap``.  In a
            dollar-neutral pairs book each leg's weight equals the signed
            pair weight, so this is equivalent to a per-pair notional cap.
        (b) **Gross leverage**: ``sum(|weights|) <= gross_leverage_cap``.
        (c) **Sector concentration** (only when *sectors* is provided):
            gross exposure of each sector ``<= sector_cap * total_gross``.

        Parameters
        ----------
        proposed_weights:
            Mapping of symbol -> signed portfolio weight (fraction of NAV).
        sectors:
            Optional mapping of symbol -> sector label.  If ``None`` the
            sector check is skipped.

        Returns
        -------
        RiskCheck
            ``passed=True`` when no limits are breached.
        """
        limits = self._limits
        violations: list[str] = []

        # (a) Per-symbol / per-pair cap
        for sym, w in proposed_weights.items():
            abs_w = abs(w)
            if abs_w > limits.per_pair_cap:
                violations.append(
                    f"Symbol {sym}: |weight| {abs_w:.4f} exceeds per_pair_cap"
                    f" {limits.per_pair_cap:.4f}"
                )

        # (b) Gross leverage
        gross = sum(abs(w) for w in proposed_weights.values())
        if gross > limits.gross_leverage_cap:
            violations.append(
                f"Gross leverage {gross:.4f} exceeds gross_leverage_cap"
                f" {limits.gross_leverage_cap:.4f}"
            )

        # (c) Sector concentration (only once the book is material; see
        # RiskLimits.sector_check_min_gross)
        if sectors is not None and gross > 0 and gross >= limits.sector_check_min_gross:
            sector_gross: dict[str, float] = {}
            for sym, w in proposed_weights.items():
                sec = sectors.get(sym, "UNKNOWN")
                sector_gross[sec] = sector_gross.get(sec, 0.0) + abs(w)
            for sec, sec_g in sector_gross.items():
                ratio = sec_g / gross
                if ratio > limits.sector_cap:
                    violations.append(
                        f"Sector {sec}: gross fraction {ratio:.4f} exceeds"
                        f" sector_cap {limits.sector_cap:.4f}"
                    )

        passed = len(violations) == 0
        return RiskCheck(passed=passed, violations=tuple(violations))

    # ------------------------------------------------------------------
    # Divergence alert
    # ------------------------------------------------------------------

    def check_divergence(self, pair_id: str, zscore: float) -> DivergenceAlert:
        """Evaluate whether a spread z-score has diverged beyond safe bounds.

        Severity thresholds
        -------------------
        * ``"critical"``: ``|zscore| > divergence_z``
        * ``"warning"``:  ``|zscore| > 0.8 * divergence_z``
        * ``"none"``:     otherwise

        Parameters
        ----------
        pair_id:
            Human-readable pair identifier (e.g. ``"GLD/SLV"``).
        zscore:
            Current standardised spread z-score.

        Returns
        -------
        DivergenceAlert
        """
        limits = self._limits
        abs_z = abs(zscore)
        breached = abs_z > limits.divergence_z
        if breached:
            severity: Literal["none", "warning", "critical"] = "critical"
        elif abs_z > 0.8 * limits.divergence_z:
            severity = "warning"
        else:
            severity = "none"
        return DivergenceAlert(
            pair_id=pair_id,
            zscore=zscore,
            breached=breached,
            severity=severity,
        )

    # ------------------------------------------------------------------
    # Daily drawdown / loss check
    # ------------------------------------------------------------------

    def daily_check(self, equity: pd.Series) -> RiskCheck:
        """Check today's one-day loss and trailing monthly drawdown.

        Two checks are applied (all violations collected):

        * **Daily loss**: the most recent one-period return loss must not
          exceed ``daily_drawdown_limit``.
        * **Monthly drawdown**: the peak-to-trough drawdown over the last
          21 observations must not exceed ``monthly_drawdown_limit``.

        Sign convention: a positive return is a gain; a negative return is a
        loss.  Both limits are expressed as positive fractions, consistent
        with :func:`~core_trading.backtest.metrics.max_drawdown`.

        Parameters
        ----------
        equity:
            Equity curve (price-like, e.g. NAV).  Must have at least 2
            observations.

        Returns
        -------
        RiskCheck

        Raises
        ------
        ValueError
            If ``equity`` has fewer than 2 observations.
        """
        if len(equity) < 2:
            raise ValueError(
                f"daily_check requires at least 2 equity observations, got {len(equity)}"
            )
        limits = self._limits
        violations: list[str] = []

        # One-day loss: negative return means a loss
        today_ret = float(equity.iloc[-1] / equity.iloc[-2] - 1.0)
        if today_ret < -limits.daily_drawdown_limit:
            violations.append(
                f"Daily loss {-today_ret:.4f} exceeds daily_drawdown_limit"
                f" {limits.daily_drawdown_limit:.4f}"
            )

        # Monthly drawdown: peak-to-trough over last ~21 observations
        window = equity.iloc[-21:]
        monthly_dd = max_drawdown(window)
        if monthly_dd > limits.monthly_drawdown_limit:
            violations.append(
                f"Monthly drawdown {monthly_dd:.4f} exceeds monthly_drawdown_limit"
                f" {limits.monthly_drawdown_limit:.4f}"
            )

        passed = len(violations) == 0
        return RiskCheck(passed=passed, violations=tuple(violations))

    # ------------------------------------------------------------------
    # VaR check
    # ------------------------------------------------------------------

    def var_check(self, returns: pd.Series) -> RiskCheck:
        """Check whether historical VaR exceeds the configured limit.

        Sign convention (mirrors :func:`~core_trading.backtest.metrics.value_at_risk`):
        ``value_at_risk`` returns a **positive** loss fraction (it internally
        computes ``-quantile(returns, alpha)``).  This method compares that
        positive magnitude directly against ``var_limit`` -- no additional
        sign manipulation.

        Parameters
        ----------
        returns:
            Series of period returns.  Must have at least ``ceil(1 / var_alpha)``
            observations (e.g. 20 observations for alpha=0.05) so the quantile
            estimate has at least one data point in the tail.

        Returns
        -------
        RiskCheck

        Raises
        ------
        ValueError
            If ``returns`` has fewer observations than ``ceil(1 / var_alpha)``.
        """
        limits = self._limits
        min_obs = int(np.ceil(1.0 / limits.var_alpha))
        if len(returns) < min_obs:
            raise ValueError(
                f"var_check requires at least {min_obs} return observations"
                f" (1 / var_alpha = 1 / {limits.var_alpha}), got {len(returns)}"
            )

        # value_at_risk returns a positive loss fraction
        var_loss = value_at_risk(returns, limits.var_alpha)
        violations: list[str] = []
        if var_loss > limits.var_limit:
            violations.append(
                f"Historical VaR loss {var_loss:.4f} (alpha={limits.var_alpha})"
                f" exceeds var_limit {limits.var_limit:.4f}"
            )

        passed = len(violations) == 0
        return RiskCheck(passed=passed, violations=tuple(violations))

    # ------------------------------------------------------------------
    # Master circuit breaker
    # ------------------------------------------------------------------

    def circuit_breaker(
        self,
        equity: pd.Series,
        returns: pd.Series | None = None,
        *,
        sectors: Mapping[str, str] | None = None,
        proposed_weights: Mapping[str, float] | None = None,
    ) -> RiskCheck:
        """Convenience gate that merges daily, VaR, and pre-trade checks.

        Runs :meth:`daily_check` unconditionally, :meth:`var_check` when
        *returns* is provided, and :meth:`pre_trade` when *proposed_weights* is
        provided.  All violations from every active check are merged into a
        single :class:`RiskCheck`.  A ``False`` result from any sub-check
        fails the whole gate.

        Parameters
        ----------
        equity:
            Equity curve passed to :meth:`daily_check`.
        returns:
            Period returns passed to :meth:`var_check`.  Skipped when ``None``.
        sectors:
            Sector labels forwarded to :meth:`pre_trade`.
        proposed_weights:
            Proposed weights forwarded to :meth:`pre_trade`.  Skipped when
            ``None``.

        Returns
        -------
        RiskCheck
            Merged result; ``passed=True`` only when every active sub-check
            passes.
        """
        all_violations: list[str] = []

        daily = self.daily_check(equity)
        all_violations.extend(daily.violations)

        if returns is not None:
            var = self.var_check(returns)
            all_violations.extend(var.violations)

        if proposed_weights is not None:
            pre = self.pre_trade(proposed_weights, sectors=sectors)
            all_violations.extend(pre.violations)

        passed = len(all_violations) == 0
        return RiskCheck(passed=passed, violations=tuple(all_violations))
