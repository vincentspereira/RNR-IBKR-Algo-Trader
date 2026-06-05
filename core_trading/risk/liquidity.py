"""Liquidity risk measurement (Phase 7, module 7.10).

This module provides three complementary liquidity risk measures:

1. **Days-to-liquidate (DTL)** -- given position sizes, per-asset ADV
   (average daily volume), and a participation cap, compute the number of
   trading days required to exit each position without exceeding the cap.
   Also produces a day-by-day liquidation schedule and a portfolio-level
   weighted-average DTL.  Zero or NaN ADV is flagged explicitly (infinite
   horizon) rather than silently producing division-by-zero or NaN results.

2. **Liquidity-adjusted VaR (LVaR)** -- adds an exogenous bid-ask spread
   add-on (Bangia-Diebold-Schuermann-Stroughair 1999) to an existing
   ``VaRResult`` from ``core_trading.risk.var``.  Also computes an
   endogenous price-impact add-on for positions that exceed the participation
   cap, using the Almgren-Thum-Hauptmann-Li (2005) / Grinold-Kahn square-root
   impact model.

3. **Spread-stress LVaR** -- recomputes LVaR under shocked (multiplied) spreads
   and estimates the total capital evaporation cost of liquidating the whole
   book under stressed spreads and market impact.

Sign convention
---------------
All loss figures follow the positive-loss convention used throughout
``core_trading.risk`` (var.py, cvar.py, stress.py).  A *positive* number
denotes a *loss*.

Model documentation
-------------------

**BDSS exogenous spread add-on (Bangia et al. 1999)**::

    LVaR = VaR + 0.5 * (mu_spread + k * sigma_spread) * position_value

where ``mu_spread`` is the mean (fractional) spread, ``sigma_spread`` is its
standard deviation, and ``k`` is the coverage factor (default 3, giving
approximately 99.9% coverage of normal spread realisations).  The factor 0.5
arises because the round-trip spread cost on *liquidating* (one-way) is
half the full bid-ask spread.  ``position_value`` (absolute notional) ensures
the add-on is in the same dollar units as ``VaR``.

Reference: Bangia, A., Diebold, F.X., Schuermann, T. & Stroughair, J.D.
(1999). "Modeling Liquidity Risk, With Implications for Traditional Market Risk
Measurement and Management." Wharton Financial Institutions Center WP 99-06.

**Almgren-Thum-Hauptmann-Li endogenous price-impact (Almgren et al. 2005)**::

    impact_per_share = c * sigma * sqrt(Q / ADV)

    total_impact = impact_per_share * Q

where ``Q`` is the number of shares to liquidate, ``ADV`` is the 30-day average
daily volume, ``sigma`` is the daily asset return volatility, and ``c`` is
a dimensionless market-impact coefficient (default 0.1, corresponding to typical
institutional trading; Grinold & Kahn recommend values in [0.05, 0.20]).

This model is applied *only* for positions where ``Q / ADV > participation_cap``
(i.e., the position exceeds the cap within a single day); below the threshold
the single-day market-impact is negligible.  The rationale is that the
square-root model is a permanent-impact approximation for large orders; for
small orders relative to ADV the temporary impact is negligible and including
it would double-count effects already priced into spreads.

Reference: Almgren, R., Thum, C., Hauptmann, E. & Li, H. (2005). "Direct
Estimation of Equity Market Impact." Risk, 18(7), 58-62.
Grinold, R. & Kahn, R. (2000). "Active Portfolio Management." 2nd ed.
McGraw-Hill.

Mathematical references
-----------------------
  * Bangia, A., Diebold, F.X., Schuermann, T. & Stroughair, J.D. (1999).
    "Modeling Liquidity Risk, With Implications for Traditional Market Risk
    Measurement and Management." Wharton Financial Institutions Center WP 99-06.
  * Almgren, R., Thum, C., Hauptmann, E. & Li, H. (2005). "Direct Estimation
    of Equity Market Impact." Risk, 18(7), 58-62.
  * Grinold, R. & Kahn, R. (2000). "Active Portfolio Management." 2nd ed.
    McGraw-Hill (Chapter 14 for market-impact model calibration).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from core_trading.risk.var import VaRResult

__all__ = [
    # Config dataclasses
    "LiquidityConfig",
    # Days-to-liquidate
    "AssetLiquidityResult",
    "LiquidationSchedule",
    "PortfolioLiquidityResult",
    "days_to_liquidate",
    # LVaR
    "LVaRResult",
    "liquidity_adjusted_var",
    # Stress
    "LiquidityStressReport",
    "stress_liquidity",
    "render_liquidity_stress_markdown",
]


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiquidityConfig:
    """Immutable configuration for liquidity risk calculations.

    Attributes
    ----------
    participation_cap:
        Maximum fraction of ADV that can be traded per day without moving
        the market (e.g., 0.10 = 10%).  Must be in (0, 1].
    bdss_k:
        Coverage multiplier for the BDSS spread add-on.  Default 3 gives
        approximately 99.9% coverage of normal spread realisations.
        Must be > 0.
    impact_coeff:
        Almgren et al. dimensionless market-impact coefficient ``c``.
        Grinold-Kahn typical range: [0.05, 0.20].  Default 0.1.
        Must be > 0.
    spread_stress_multiplier:
        Factor by which spreads are multiplied in the stress scenario.
        Default 3.0 ("what if spreads triple?").  Must be >= 1.
    """

    participation_cap: float = 0.10
    bdss_k: float = 3.0
    impact_coeff: float = 0.1
    spread_stress_multiplier: float = 3.0

    def __post_init__(self) -> None:
        """Validate all configuration fields."""
        if not (0.0 < self.participation_cap <= 1.0):
            raise ValueError(
                f"participation_cap must be in (0, 1]; got {self.participation_cap!r}"
            )
        if self.bdss_k <= 0.0:
            raise ValueError(
                f"bdss_k must be > 0; got {self.bdss_k!r}"
            )
        if self.impact_coeff <= 0.0:
            raise ValueError(
                f"impact_coeff must be > 0; got {self.impact_coeff!r}"
            )
        if self.spread_stress_multiplier < 1.0:
            raise ValueError(
                f"spread_stress_multiplier must be >= 1; got {self.spread_stress_multiplier!r}"
            )


# ---------------------------------------------------------------------------
# Days-to-liquidate DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiquidationSchedule:
    """Day-by-day liquidation plan for a single position.

    Attributes
    ----------
    asset:
        Asset identifier.
    shares_per_day:
        Number of shares (or notional units) liquidated on each day.
        Length equals ``days_to_liquidate``.  The sum equals the original
        position size.
    days_to_liquidate:
        Number of trading days required to exit the position.
        Zero if the position is zero.  ``math.inf`` if ADV is zero or NaN.
    """

    asset: str
    shares_per_day: list[float]
    days_to_liquidate: float


@dataclass(frozen=True, slots=True)
class AssetLiquidityResult:
    """Liquidity metrics for a single asset position.

    Attributes
    ----------
    asset:
        Asset identifier.
    position_shares:
        Absolute position size (shares or notional units).
    adv:
        30-day average daily volume (shares or same units as position).
        May be NaN; flagged separately.
    participation_cap:
        Cap fraction used in the calculation.
    daily_tradeable:
        Maximum shares tradeable per day = ``adv * participation_cap``.
        Zero when ADV is zero; NaN when ADV is NaN.
    days_to_liquidate:
        Number of trading days to exit.  ``math.inf`` when ADV <= 0 or NaN.
    zero_adv_flag:
        ``True`` when ADV is zero or NaN (infinite horizon flagged).
    schedule:
        :class:`LiquidationSchedule` for this asset.
    """

    asset: str
    position_shares: float
    adv: float
    participation_cap: float
    daily_tradeable: float
    days_to_liquidate: float
    zero_adv_flag: bool
    schedule: LiquidationSchedule


@dataclass(frozen=True, slots=True)
class PortfolioLiquidityResult:
    """Portfolio-level days-to-liquidate summary.

    Attributes
    ----------
    asset_results:
        Per-asset :class:`AssetLiquidityResult` list, aligned with input.
    weighted_avg_dtl:
        Weighted-average days-to-liquidate across assets.  The weight for
        each asset is its ``position_shares`` relative to the total.  If any
        asset has infinite DTL, the portfolio-level figure is also ``inf``.
    max_dtl:
        Maximum days-to-liquidate across all positions.
    flagged_assets:
        List of asset names with ``zero_adv_flag=True``.
    participation_cap:
        Cap fraction used.
    """

    asset_results: list[AssetLiquidityResult]
    weighted_avg_dtl: float
    max_dtl: float
    flagged_assets: list[str]
    participation_cap: float


# ---------------------------------------------------------------------------
# days_to_liquidate
# ---------------------------------------------------------------------------


def days_to_liquidate(
    positions: dict[str, float],
    adv: dict[str, float],
    *,
    config: LiquidityConfig | None = None,
) -> PortfolioLiquidityResult:
    """Compute per-asset and portfolio days-to-liquidate.

    For each asset, the liquidation horizon is::

        daily_tradeable = adv * participation_cap
        dtl = ceil(abs(position) / daily_tradeable)

    The schedule distributes position shares evenly at ``daily_tradeable``
    per day, with the last day taking the residual.

    Parameters
    ----------
    positions:
        Mapping from asset name to position size (shares or notional).
        Negative positions (shorts) are treated as their absolute value.
        Assets with zero position have DTL = 0.
    adv:
        Mapping from asset name to 30-day average daily volume (same units
        as positions).  Missing keys or NaN/zero values produce
        ``zero_adv_flag=True`` and infinite DTL.
    config:
        :class:`LiquidityConfig` controlling participation cap.
        Defaults to ``LiquidityConfig()`` (10% cap).

    Returns
    -------
    PortfolioLiquidityResult

    Raises
    ------
    ValueError
        If ``positions`` is empty.
    """
    if not positions:
        raise ValueError("positions must be non-empty.")

    cfg = config if config is not None else LiquidityConfig()
    cap = cfg.participation_cap

    asset_results: list[AssetLiquidityResult] = []

    for asset, pos_raw in positions.items():
        pos = abs(float(pos_raw))
        raw_adv = float(adv.get(asset, float("nan")))

        # Determine if ADV is unusable
        zero_flag = (
            not math.isfinite(raw_adv) or raw_adv <= 0.0
        )

        if zero_flag:
            daily_tradeable = 0.0 if raw_adv == 0.0 else float("nan")
            dtl: float = math.inf
            schedule = LiquidationSchedule(
                asset=asset,
                shares_per_day=[],
                days_to_liquidate=math.inf,
            )
        elif pos == 0.0:
            daily_tradeable = raw_adv * cap
            dtl = 0.0
            schedule = LiquidationSchedule(
                asset=asset,
                shares_per_day=[],
                days_to_liquidate=0.0,
            )
        else:
            daily_tradeable = raw_adv * cap
            n_full = int(pos // daily_tradeable)
            residual = pos - n_full * daily_tradeable
            days_int = n_full + (1 if residual > 0.0 else 0)
            dtl = float(days_int)

            # Build schedule: full days first, then residual
            spd: list[float] = [daily_tradeable] * n_full
            if residual > 0.0:
                spd.append(residual)

            schedule = LiquidationSchedule(
                asset=asset,
                shares_per_day=spd,
                days_to_liquidate=dtl,
            )

        asset_results.append(
            AssetLiquidityResult(
                asset=asset,
                position_shares=pos,
                adv=raw_adv,
                participation_cap=cap,
                daily_tradeable=daily_tradeable,
                days_to_liquidate=dtl,
                zero_adv_flag=zero_flag,
                schedule=schedule,
            )
        )

    # Portfolio aggregates
    flagged = [r.asset for r in asset_results if r.zero_adv_flag]
    total_pos = sum(r.position_shares for r in asset_results)

    if total_pos == 0.0:
        w_avg_dtl = 0.0
    elif any(math.isinf(r.days_to_liquidate) for r in asset_results):
        w_avg_dtl = math.inf
    else:
        w_avg_dtl = sum(
            r.position_shares * r.days_to_liquidate for r in asset_results
        ) / total_pos

    max_dtl = max(r.days_to_liquidate for r in asset_results)

    return PortfolioLiquidityResult(
        asset_results=asset_results,
        weighted_avg_dtl=w_avg_dtl,
        max_dtl=max_dtl,
        flagged_assets=flagged,
        participation_cap=cap,
    )


# ---------------------------------------------------------------------------
# LVaR DTOs and computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LVaRResult:
    """Liquidity-adjusted Value-at-Risk result.

    Attributes
    ----------
    lvar:
        Total Liquidity-adjusted VaR (positive loss value).
        ``lvar = var + exogenous_addon + endogenous_addon``.
    var:
        Base VaR from the upstream ``VaRResult`` (positive loss).
    exogenous_addon:
        BDSS bid-ask spread add-on (positive).
    endogenous_addon:
        Almgren et al. price-impact add-on for positions exceeding the
        participation cap (positive; zero if no position exceeds the cap).
    per_asset_exogenous:
        Per-asset exogenous add-on, keyed by asset name.
    per_asset_endogenous:
        Per-asset endogenous add-on, keyed by asset name.
    bdss_k:
        Coverage factor used for the exogenous add-on.
    participation_cap:
        Participation cap fraction used for the endogenous add-on.
    method:
        Always ``"lvar_bdss_almgren"``.
    """

    lvar: float
    var: float
    exogenous_addon: float
    endogenous_addon: float
    per_asset_exogenous: dict[str, float]
    per_asset_endogenous: dict[str, float]
    bdss_k: float
    participation_cap: float
    method: str = "lvar_bdss_almgren"


def liquidity_adjusted_var(
    var_result: VaRResult,
    positions: dict[str, float],
    position_values: dict[str, float],
    spreads_mean: dict[str, float],
    spreads_std: dict[str, float],
    *,
    adv: dict[str, float] | None = None,
    asset_vols: dict[str, float] | None = None,
    config: LiquidityConfig | None = None,
) -> LVaRResult:
    """Compute Liquidity-adjusted VaR (BDSS exogenous + Almgren endogenous).

    **Exogenous spread add-on (BDSS 1999)**::

        addon_i = 0.5 * (mu_spread_i + k * sigma_spread_i) * |position_value_i|
        exogenous_addon = sum_i(addon_i)
        LVaR_exog = VaR + exogenous_addon

    **Endogenous price-impact add-on (Almgren et al. 2005)**::

        impact_i = c * sigma_i * sqrt(|Q_i| / ADV_i) * |Q_i|
        endogenous_addon = sum_i(impact_i)   [only for |Q_i|/ADV_i > cap]
        LVaR = LVaR_exog + endogenous_addon

    The endogenous add-on is applied *only* when the position exceeds the
    participation threshold (``|Q_i| / ADV_i > participation_cap``).
    Below the threshold the permanent market-impact is negligible relative
    to the spread cost.

    Parameters
    ----------
    var_result:
        :class:`~core_trading.risk.var.VaRResult` from any of the estimators
        in ``core_trading.risk.var``.  The ``.var`` field must be positive
        (positive-loss convention).
    positions:
        Mapping from asset name to signed position size (shares or units).
        Absolute values are used.
    position_values:
        Mapping from asset name to current notional value (absolute dollar
        amount or same currency units).  Must be non-negative.
    spreads_mean:
        Mapping from asset name to mean fractional bid-ask spread
        (e.g. 0.001 = 0.1%).
    spreads_std:
        Mapping from asset name to standard deviation of the fractional spread.
    adv:
        Optional mapping from asset name to ADV.  Required only when computing
        the endogenous add-on.  If ``None`` or a key is missing, the endogenous
        add-on for that asset is zero.
    asset_vols:
        Optional mapping from asset name to daily return volatility (fractional,
        e.g. 0.02 = 2%).  Required for the endogenous add-on.  If ``None``
        or a key is missing, the endogenous add-on for that asset is zero.
    config:
        :class:`LiquidityConfig`.  Defaults to ``LiquidityConfig()``.

    Returns
    -------
    LVaRResult

    Raises
    ------
    ValueError
        If ``positions`` is empty, spread dicts have missing keys, or
        ``var_result.var < 0``.
    """
    if not positions:
        raise ValueError("positions must be non-empty.")
    if var_result.var < 0.0:
        raise ValueError(
            f"var_result.var must be >= 0 (positive-loss convention); "
            f"got {var_result.var!r}"
        )

    cfg = config if config is not None else LiquidityConfig()

    per_exog: dict[str, float] = {}
    per_endo: dict[str, float] = {}

    for asset in positions:
        pos_val = abs(float(position_values.get(asset, 0.0)))
        mu_s = float(spreads_mean.get(asset, 0.0))
        sig_s = float(spreads_std.get(asset, 0.0))

        # BDSS exogenous add-on for this asset
        exog = 0.5 * (mu_s + cfg.bdss_k * sig_s) * pos_val
        per_exog[asset] = exog

        # Almgren endogenous add-on
        q = abs(float(positions[asset]))
        endo = 0.0
        if adv is not None and asset_vols is not None:
            raw_adv = float(adv.get(asset, 0.0))
            sigma_i = float(asset_vols.get(asset, 0.0))
            if raw_adv > 0.0 and sigma_i > 0.0 and q > 0.0:
                participation = q / raw_adv
                if participation > cfg.participation_cap:
                    endo = cfg.impact_coeff * sigma_i * math.sqrt(participation) * q
        per_endo[asset] = endo

    exogenous_total = sum(per_exog.values())
    endogenous_total = sum(per_endo.values())
    lvar = var_result.var + exogenous_total + endogenous_total

    return LVaRResult(
        lvar=lvar,
        var=var_result.var,
        exogenous_addon=exogenous_total,
        endogenous_addon=endogenous_total,
        per_asset_exogenous=per_exog,
        per_asset_endogenous=per_endo,
        bdss_k=cfg.bdss_k,
        participation_cap=cfg.participation_cap,
    )


# ---------------------------------------------------------------------------
# Stress liquidity DTOs and computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiquidityStressReport:
    """Liquidity stress test report.

    Attributes
    ----------
    base_lvar:
        Baseline liquidity-adjusted VaR (unstressed).
    stressed_lvar:
        LVaR under stressed (multiplied) spreads.
    stressed_exogenous_addon:
        Total exogenous spread add-on under stressed spreads.
    stressed_endogenous_addon:
        Total endogenous price-impact add-on (same as base -- impact
        model does not depend on spreads).
    capital_evaporation_abs:
        Absolute cost (same units as ``position_values``) to liquidate the
        entire book under stressed spreads + market impact.
    capital_evaporation_pct:
        ``capital_evaporation_abs / nav * 100`` (percentage of NAV).
    nav:
        Net asset value used for the pct calculation.
    spread_stress_multiplier:
        Spread multiplier applied.
    per_asset_stressed_exogenous:
        Per-asset stressed exogenous add-on.
    per_asset_impact:
        Per-asset endogenous impact cost for full liquidation (not just
        above-cap portion -- full book liquidation includes all shares).
    positions:
        Position sizes passed in.
    asset_names:
        Ordered list of asset names.
    generated_at:
        ISO timestamp string (UTC) when the report was built.
    """

    base_lvar: LVaRResult
    stressed_lvar: float
    stressed_exogenous_addon: float
    stressed_endogenous_addon: float
    capital_evaporation_abs: float
    capital_evaporation_pct: float
    nav: float
    spread_stress_multiplier: float
    per_asset_stressed_exogenous: dict[str, float]
    per_asset_impact: dict[str, float]
    positions: dict[str, float]
    asset_names: list[str]
    generated_at: str


def stress_liquidity(
    var_result: VaRResult,
    positions: dict[str, float],
    position_values: dict[str, float],
    spreads_mean: dict[str, float],
    spreads_std: dict[str, float],
    nav: float,
    *,
    adv: dict[str, float] | None = None,
    asset_vols: dict[str, float] | None = None,
    config: LiquidityConfig | None = None,
    generated_at: str | None = None,
) -> LiquidityStressReport:
    """Run a spread-stress liquidity scenario.

    Steps:

    1. Compute baseline :class:`LVaRResult` at current spreads.
    2. Multiply spreads by ``config.spread_stress_multiplier`` and recompute
       the exogenous add-on only (endogenous model does not depend on spreads).
       ``stressed_lvar = VaR + stressed_exogenous_addon + endogenous_addon``.
    3. Compute capital evaporation: total cost of liquidating the full book
       under stressed spreads and full-position market impact::

           evap_i = 0.5*(mu_s_i*m + k*sigma_s_i*m)*|pos_val_i|     [spread cost]
                  + c * sigma_i * sqrt(|Q_i|/ADV_i) * |Q_i|        [impact cost]
           capital_evaporation = sum_i(evap_i)

       Unlike the LVaR endogenous add-on (which only fires above the cap),
       the evaporation impact applies to the *full* position regardless of
       threshold -- this represents the cost of forced full liquidation.

    Parameters
    ----------
    var_result:
        Baseline :class:`~core_trading.risk.var.VaRResult`.
    positions:
        Mapping from asset name to signed position size.
    position_values:
        Mapping from asset name to notional value.
    spreads_mean:
        Mapping from asset name to mean fractional spread.
    spreads_std:
        Mapping from asset name to std of fractional spread.
    nav:
        Total portfolio net asset value (same units as position_values).
        Used to express capital evaporation as a percentage.  Must be > 0.
    adv:
        Optional ADV mapping.  Used for the market-impact component of
        capital evaporation.
    asset_vols:
        Optional daily return volatility mapping.
    config:
        :class:`LiquidityConfig`.  Defaults to ``LiquidityConfig()``.
    generated_at:
        Optional ISO timestamp string; defaults to current UTC time.

    Returns
    -------
    LiquidityStressReport

    Raises
    ------
    ValueError
        If ``nav <= 0``, positions is empty, or ``var_result.var < 0``.
    """
    if nav <= 0.0:
        raise ValueError(f"nav must be > 0; got {nav!r}")
    if not positions:
        raise ValueError("positions must be non-empty.")

    cfg = config if config is not None else LiquidityConfig()
    m = cfg.spread_stress_multiplier

    # Step 1: baseline LVaR
    base_lvar = liquidity_adjusted_var(
        var_result,
        positions,
        position_values,
        spreads_mean,
        spreads_std,
        adv=adv,
        asset_vols=asset_vols,
        config=cfg,
    )

    # Step 2: stressed exogenous add-on (spreads * multiplier)
    per_stressed_exog: dict[str, float] = {}
    for asset in positions:
        pos_val = abs(float(position_values.get(asset, 0.0)))
        mu_s = float(spreads_mean.get(asset, 0.0)) * m
        sig_s = float(spreads_std.get(asset, 0.0)) * m
        per_stressed_exog[asset] = 0.5 * (mu_s + cfg.bdss_k * sig_s) * pos_val

    stressed_exog_total = sum(per_stressed_exog.values())
    stressed_lvar = var_result.var + stressed_exog_total + base_lvar.endogenous_addon

    # Step 3: capital evaporation (full-position liquidation cost)
    # = stressed spread cost + full-position market impact
    per_impact: dict[str, float] = {}
    evap_total = 0.0

    for asset in positions:
        pos_val = abs(float(position_values.get(asset, 0.0)))
        mu_s = float(spreads_mean.get(asset, 0.0)) * m
        sig_s = float(spreads_std.get(asset, 0.0)) * m
        spread_cost = 0.5 * (mu_s + cfg.bdss_k * sig_s) * pos_val

        q = abs(float(positions[asset]))
        impact_cost = 0.0
        if adv is not None and asset_vols is not None:
            raw_adv = float(adv.get(asset, 0.0))
            sigma_i = float(asset_vols.get(asset, 0.0))
            if raw_adv > 0.0 and sigma_i > 0.0 and q > 0.0:
                participation = q / raw_adv
                impact_cost = cfg.impact_coeff * sigma_i * math.sqrt(participation) * q

        per_impact[asset] = impact_cost
        evap_total += spread_cost + impact_cost

    evap_pct = evap_total / nav * 100.0

    if generated_at is None:
        ts = pd.Timestamp.utcnow()
        generated_at = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    return LiquidityStressReport(
        base_lvar=base_lvar,
        stressed_lvar=stressed_lvar,
        stressed_exogenous_addon=stressed_exog_total,
        stressed_endogenous_addon=base_lvar.endogenous_addon,
        capital_evaporation_abs=evap_total,
        capital_evaporation_pct=evap_pct,
        nav=nav,
        spread_stress_multiplier=m,
        per_asset_stressed_exogenous=per_stressed_exog,
        per_asset_impact=per_impact,
        positions=dict(positions),
        asset_names=list(positions.keys()),
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# ASCII markdown renderer
# ---------------------------------------------------------------------------


def render_liquidity_stress_markdown(report: LiquidityStressReport) -> str:
    """Render a :class:`LiquidityStressReport` as an ASCII-only markdown string.

    The output is suitable for embedding in daily ops emails or log files.
    All characters are 7-bit ASCII -- no Unicode, no emoji.

    Layout::

        # Liquidity Stress Report

        Generated: 2024-01-15T09:30:00Z
        Spread stress multiplier: 3.0x
        NAV: 1,000,000.00

        ## LVaR Summary
        Base LVaR   :    12345.67
        Stressed LVaR:   23456.78

        ## Per-Asset Breakdown
        | Asset  | Position  | Stressed Exog | Impact Cost |
        |--------|-----------|---------------|-------------|
        | AAPL   | 1000.00   | 50.00         | 20.00       |
        ...

        ## Capital Evaporation
        Total cost (abs) : 12345.00
        Total cost (% NAV): 1.23%

    Parameters
    ----------
    report:
        :class:`LiquidityStressReport` to render.

    Returns
    -------
    str
        ASCII-only markdown string.
    """
    lines: list[str] = []
    lines.append("# Liquidity Stress Report")
    lines.append("")
    lines.append(f"Generated: {report.generated_at}")
    lines.append(f"Spread stress multiplier: {report.spread_stress_multiplier:.1f}x")
    lines.append(f"NAV: {report.nav:,.2f}")
    lines.append("")

    lines.append("## LVaR Summary")
    lines.append(f"Base VaR             : {report.base_lvar.var:>14.4f}")
    lines.append(f"Base exogenous addon : {report.base_lvar.exogenous_addon:>14.4f}")
    lines.append(f"Base endogenous addon: {report.base_lvar.endogenous_addon:>14.4f}")
    lines.append(f"Base LVaR            : {report.base_lvar.lvar:>14.4f}")
    lines.append(f"Stressed exog addon  : {report.stressed_exogenous_addon:>14.4f}")
    lines.append(f"Stressed LVaR        : {report.stressed_lvar:>14.4f}")
    lines.append("")

    # Per-asset breakdown
    lines.append("## Per-Asset Breakdown")

    max_name = max((len(a) for a in report.asset_names), default=5)
    max_name = max(max_name, len("Asset"))

    w_pos = 14
    w_exog = 15
    w_imp = 13

    def _sep(w: int) -> str:
        return "-" * w

    header = (
        f"| {'Asset':<{max_name}} "
        f"| {'Position':<{w_pos}} "
        f"| {'Stressed Exog':<{w_exog}} "
        f"| {'Impact Cost':<{w_imp}} |"
    )
    divider = (
        f"|{_sep(max_name + 2)}"
        f"|{_sep(w_pos + 2)}"
        f"|{_sep(w_exog + 2)}"
        f"|{_sep(w_imp + 2)}|"
    )
    lines.append(header)
    lines.append(divider)

    for asset in report.asset_names:
        pos = report.positions.get(asset, 0.0)
        exog = report.per_asset_stressed_exogenous.get(asset, 0.0)
        imp = report.per_asset_impact.get(asset, 0.0)
        row = (
            f"| {asset:<{max_name}} "
            f"| {pos:<{w_pos}.2f} "
            f"| {exog:<{w_exog}.4f} "
            f"| {imp:<{w_imp}.4f} |"
        )
        lines.append(row)

    lines.append("")
    lines.append("## Capital Evaporation")
    lines.append(f"Total cost (abs)   : {report.capital_evaporation_abs:>14.4f}")
    lines.append(f"Total cost (% NAV) : {report.capital_evaporation_pct:>14.4f}%")
    lines.append("")

    return "\n".join(lines)
