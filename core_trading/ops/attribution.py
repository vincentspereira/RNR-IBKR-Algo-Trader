"""Performance attribution report generator (master plan Phase 11.4).

This module is a *pure generator* -- it never touches the clock, filesystem,
or any live data source.  The ``generated_at`` timestamp is injectable, and the
only data source on the CLI is ``--demo``.  It mirrors the structure of
:mod:`core_trading.risk.daily_report` and
:mod:`core_trading.research.robustness_report`.

Four attribution lenses are provided:

1. **Factor attribution** -- OLS-decomposes daily portfolio returns into
   per-factor contributions plus an alpha residual.  The caller supplies a
   factor return ``DataFrame``; no implicit dependency on Fama-French data is
   required, but the output integrates naturally with
   ``core_trading.signals.factors.fama_french`` outputs.

2. **Strategy attribution** -- given per-strategy daily return series and
   capital weights, computes each strategy's additive contribution to total
   portfolio PnL.  The contributions sum to the total within a configurable
   tolerance.

3. **Trade attribution** -- given a day's fills and close-to-close marks,
   identifies which positions drove the session's PnL via realised and
   unrealised per-symbol contributions.  Top-N movers are surfaced.

4. **Cost attribution** -- decomposes execution cost per trade into spread
   cost, commission, and timing/slippage residual.  Accepts cost components
   as inputs and aggregates to per-day totals and basis-point summaries.

CLI entry point
---------------
``python -m core_trading.ops.attribution --demo``
    Runs seeded synthetic data through all four attributions and prints the
    full ASCII report.

``python -m core_trading.ops.attribution --demo --output <path>``
    Same as ``--demo`` but also writes the report to the given file path.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    # Config
    "AttributionConfig",
    # Factor attribution
    "FactorAttributionResult",
    "factor_attribution",
    # Strategy attribution
    "StrategyAttributionResult",
    "strategy_attribution",
    # Trade attribution
    "TradeAttributionResult",
    "SymbolPnL",
    "trade_attribution",
    # Cost attribution
    "CostAttributionResult",
    "CostBreakdown",
    "cost_attribution",
    # Renderer + CLI
    "render_attribution_report",
    "main",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttributionConfig:
    """Configuration for all attribution lenses.

    Attributes
    ----------
    annualise_factor:
        Number of periods per year used to annualise alpha and other
        per-period quantities.  Default 252 (trading days).
    contribution_tol:
        Absolute tolerance when verifying that strategy contributions sum
        to the total portfolio return.  Default 1e-8.
    top_n_movers:
        Number of top (and bottom) symbol movers surfaced in the trade
        attribution section.  Default 5.
    generated_at:
        Optional override for the UTC timestamp embedded in the report.
        ``None`` means the caller should supply it explicitly to
        :func:`render_attribution_report`.
    bps_scale:
        Multiplier for converting a fractional cost to basis points.
        Default 10_000.0.
    """

    annualise_factor: int = 252
    contribution_tol: float = 1e-8
    top_n_movers: int = 5
    generated_at: str | None = None
    bps_scale: float = 10_000.0

    def __post_init__(self) -> None:
        if self.annualise_factor < 1:
            raise ValueError(
                f"annualise_factor must be >= 1; got {self.annualise_factor!r}."
            )
        if self.contribution_tol <= 0.0:
            raise ValueError(
                f"contribution_tol must be > 0; got {self.contribution_tol!r}."
            )
        if self.top_n_movers < 1:
            raise ValueError(
                f"top_n_movers must be >= 1; got {self.top_n_movers!r}."
            )
        if self.bps_scale <= 0.0:
            raise ValueError(
                f"bps_scale must be > 0; got {self.bps_scale!r}."
            )


# ---------------------------------------------------------------------------
# Factor attribution DTOs and engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorAttributionResult:
    """Result of OLS factor attribution on a portfolio return series.

    Attributes
    ----------
    betas:
        Per-factor OLS regression coefficients, keyed by factor name.
    contributions:
        Per-factor daily contribution to portfolio return
        (factor_return * beta), keyed by factor name.  Each value is a
        ``pd.Series`` aligned with the input index.
    alpha_annualised:
        Annualised intercept from the OLS regression (annualise_factor *
        per-period alpha).
    r_squared:
        Coefficient of determination of the OLS fit.
    residuals:
        Series of daily OLS residuals (actual - fitted), indexed as input.
    n_obs:
        Number of observations used in the regression.
    factor_names:
        Ordered list of factor names (same order as ``betas``).
    """

    betas: dict[str, float]
    contributions: dict[str, pd.Series]
    alpha_annualised: float
    r_squared: float
    residuals: pd.Series
    n_obs: int
    factor_names: list[str]


def factor_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
    *,
    config: AttributionConfig | None = None,
) -> FactorAttributionResult:
    """OLS-decompose daily portfolio returns into per-factor contributions.

    Aligns ``portfolio_returns`` and ``factor_returns`` on their shared index
    (inner join), drops rows with any NaN, then fits an OLS model:

        r_portfolio = alpha + sum_f(beta_f * r_factor_f) + epsilon

    Parameters
    ----------
    portfolio_returns:
        Daily portfolio return series.  Index must be monotone; NaN rows are
        dropped after alignment.
    factor_returns:
        DataFrame of daily factor returns, shape (T, F).  Columns are factor
        names.  Must share at least 2 index dates with ``portfolio_returns``
        after NaN-dropping.
    config:
        :class:`AttributionConfig`.  Defaults to ``AttributionConfig()``.

    Returns
    -------
    FactorAttributionResult
        Fitted betas, per-factor contributions, annualised alpha, R-squared,
        residuals.

    Raises
    ------
    ValueError
        When fewer than 2 usable observations remain after alignment and
        NaN-dropping, or when ``factor_returns`` has zero columns.
    """
    cfg = config if config is not None else AttributionConfig()

    if factor_returns.shape[1] == 0:
        raise ValueError("factor_returns must have at least one column.")

    # Align on shared dates and drop NaN rows
    combined = pd.concat(
        [portfolio_returns.rename("__port__"), factor_returns], axis=1
    ).dropna()

    n_obs = len(combined)
    if n_obs < 2:
        raise ValueError(
            f"Need at least 2 clean observations for OLS; got {n_obs}."
        )

    y: np.ndarray = combined["__port__"].to_numpy(dtype=float)
    factor_names: list[str] = [c for c in combined.columns if c != "__port__"]
    X_raw: np.ndarray = combined[factor_names].to_numpy(dtype=float)

    # Add intercept column
    ones: np.ndarray = np.ones((n_obs, 1), dtype=float)
    X: np.ndarray = np.concatenate([ones, X_raw], axis=1)

    # OLS via least-squares: solve X @ coef = y
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha_per_period: float = float(coef[0])
    betas_arr: np.ndarray = coef[1:]

    fitted: np.ndarray = X @ coef
    residuals_arr: np.ndarray = y - fitted

    # R-squared
    ss_res: float = float(np.dot(residuals_arr, residuals_arr))
    y_mean: float = float(y.mean())
    ss_tot: float = float(np.dot(y - y_mean, y - y_mean))
    r_squared: float = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0

    # Per-factor daily contributions
    betas: dict[str, float] = {}
    contributions: dict[str, pd.Series] = {}
    for i, name in enumerate(factor_names):
        b: float = float(betas_arr[i])
        betas[name] = b
        factor_col: np.ndarray = combined[name].to_numpy(dtype=float)
        contrib_arr: np.ndarray = b * factor_col
        contributions[name] = pd.Series(
            contrib_arr, index=combined.index, name=f"contrib_{name}"
        )

    residuals_series = pd.Series(
        residuals_arr, index=combined.index, name="residual"
    )

    return FactorAttributionResult(
        betas=betas,
        contributions=contributions,
        alpha_annualised=alpha_per_period * float(cfg.annualise_factor),
        r_squared=r_squared,
        residuals=residuals_series,
        n_obs=n_obs,
        factor_names=factor_names,
    )


# ---------------------------------------------------------------------------
# Strategy attribution DTOs and engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategyAttributionResult:
    """Additive decomposition of total portfolio PnL by strategy.

    Attributes
    ----------
    contributions:
        Per-strategy PnL contribution series, keyed by strategy name.
        Each value is the strategy's daily return weighted by its capital
        allocation: ``weight * strategy_return``.
    total_return:
        Weighted sum of all strategy contributions (scalar, the total
        period PnL over all dates).
    weights:
        Capital weights used, keyed by strategy name.
    strategy_names:
        Ordered list of strategy names.
    n_obs:
        Number of date observations after alignment and NaN-dropping.
    verified:
        True when the sum of all contributions equals ``total_return``
        within ``config.contribution_tol``.
    """

    contributions: dict[str, pd.Series]
    total_return: float
    weights: dict[str, float]
    strategy_names: list[str]
    n_obs: int
    verified: bool


def strategy_attribution(
    strategy_returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    config: AttributionConfig | None = None,
) -> StrategyAttributionResult:
    """Compute each strategy's additive contribution to portfolio PnL.

    Parameters
    ----------
    strategy_returns:
        DataFrame of daily strategy returns, shape (T, S).  Columns are
        strategy names.  NaN rows are dropped after alignment.
    weights:
        Capital weight for each strategy, keyed by strategy name.  Keys
        must match the columns of ``strategy_returns``.  Weights need not
        sum to 1; they are applied as-is.
    config:
        :class:`AttributionConfig`.  Defaults to ``AttributionConfig()``.

    Returns
    -------
    StrategyAttributionResult
        Per-strategy contribution series and total return.

    Raises
    ------
    ValueError
        When ``weights`` keys do not match ``strategy_returns`` columns, or
        when fewer than 1 clean observation remains.
    """
    cfg = config if config is not None else AttributionConfig()

    strat_cols = list(strategy_returns.columns)
    weight_keys = set(weights.keys())
    strat_set = set(strat_cols)
    if weight_keys != strat_set:
        extra_w = weight_keys - strat_set
        extra_s = strat_set - weight_keys
        msg_parts: list[str] = []
        if extra_w:
            msg_parts.append(f"weights keys not in returns: {sorted(extra_w)}")
        if extra_s:
            msg_parts.append(f"returns columns not in weights: {sorted(extra_s)}")
        raise ValueError("; ".join(msg_parts))

    clean = strategy_returns.dropna()
    n_obs = len(clean)
    if n_obs < 1:
        raise ValueError("Need at least 1 clean observation for strategy attribution.")

    contributions: dict[str, pd.Series] = {}
    contrib_sum: np.ndarray = np.zeros(n_obs, dtype=float)

    for name in strat_cols:
        w: float = float(weights[name])
        col: np.ndarray = clean[name].to_numpy(dtype=float)
        contrib_arr: np.ndarray = w * col
        contributions[name] = pd.Series(
            contrib_arr, index=clean.index, name=f"contrib_{name}"
        )
        contrib_sum = contrib_sum + contrib_arr

    total_return: float = float(contrib_sum.sum())

    # Verify additive decomposition
    actual_total: float = float(
        sum(float(s.sum()) for s in contributions.values())
    )
    verified: bool = abs(actual_total - total_return) <= cfg.contribution_tol

    return StrategyAttributionResult(
        contributions=contributions,
        total_return=total_return,
        weights={k: float(v) for k, v in weights.items()},
        strategy_names=strat_cols,
        n_obs=n_obs,
        verified=verified,
    )


# ---------------------------------------------------------------------------
# Trade attribution DTOs and engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolPnL:
    """Per-symbol PnL breakdown for one trading session.

    Attributes
    ----------
    symbol:
        Ticker or instrument identifier.
    realised_pnl:
        PnL from trades that opened and closed within the session (or net
        position change valued at fill prices).  Positive = profit.
    unrealised_pnl:
        Mark-to-market PnL on net open position (net_position *
        (close_price - avg_fill_price)).  Positive = profit.
    total_pnl:
        Sum of realised and unrealised PnL.
    net_position:
        Net signed position after fills (+long, -short).
    avg_fill_price:
        Average fill price across all fills for this symbol, weighted by
        absolute quantity.
    close_price:
        Reference close price used for mark-to-market.
    """

    symbol: str
    realised_pnl: float
    unrealised_pnl: float
    total_pnl: float
    net_position: float
    avg_fill_price: float
    close_price: float


@dataclass(frozen=True, slots=True)
class TradeAttributionResult:
    """Session-level trade PnL attribution.

    Attributes
    ----------
    symbol_pnl:
        Per-symbol PnL breakdown, keyed by symbol.
    total_pnl:
        Sum of all per-symbol total_pnl values.
    top_gainers:
        Top-N symbols by total_pnl (highest first).
    top_losers:
        Bottom-N symbols by total_pnl (lowest first, i.e. largest losses).
    n_symbols:
        Number of symbols with at least one fill.
    """

    symbol_pnl: dict[str, SymbolPnL]
    total_pnl: float
    top_gainers: list[SymbolPnL]
    top_losers: list[SymbolPnL]
    n_symbols: int


def trade_attribution(
    fills: list[dict[str, Any]],
    close_prices: dict[str, float],
    *,
    config: AttributionConfig | None = None,
) -> TradeAttributionResult:
    """Attribute session PnL to symbols from a list of fills.

    Each fill is a ``dict`` with the following required keys:

    * ``symbol`` (str) -- instrument identifier
    * ``side`` (str) -- ``"BUY"`` or ``"SELL"`` (case-insensitive)
    * ``quantity`` (float) -- unsigned quantity of shares/units
    * ``price`` (float) -- fill execution price

    Parameters
    ----------
    fills:
        List of fill dicts as described above.  Multiple fills for the
        same symbol are aggregated.
    close_prices:
        Reference close-to-close price for each symbol.  Symbols in fills
        but absent from ``close_prices`` receive a close_price of the
        average fill price (mark = cost; unrealised_pnl = 0).
    config:
        :class:`AttributionConfig`.  Defaults to ``AttributionConfig()``.

    Returns
    -------
    TradeAttributionResult
        Per-symbol PnL and top-N mover lists.

    Raises
    ------
    ValueError
        When a fill dict is missing required keys or ``side`` is unrecognised.
    """
    cfg = config if config is not None else AttributionConfig()

    # --- Aggregate fills per symbol ---
    # We track: sum of (signed_qty * price) and net signed qty.
    # signed_qty > 0 for BUY, < 0 for SELL.
    agg: dict[str, dict[str, float]] = {}

    for idx, fill in enumerate(fills):
        for key in ("symbol", "side", "quantity", "price"):
            if key not in fill:
                raise ValueError(
                    f"Fill at index {idx} is missing required key '{key}'."
                )
        sym: str = str(fill["symbol"])
        side_str: str = str(fill["side"]).upper()
        qty: float = float(fill["quantity"])
        price: float = float(fill["price"])

        if side_str == "BUY":
            signed_qty: float = qty
        elif side_str == "SELL":
            signed_qty = -qty
        else:
            raise ValueError(
                f"Fill at index {idx} has unrecognised side {fill['side']!r}; "
                "expected 'BUY' or 'SELL'."
            )

        if sym not in agg:
            agg[sym] = {"net_qty": 0.0, "cost_basis": 0.0, "abs_qty": 0.0}
        agg[sym]["net_qty"] += signed_qty
        # cost_basis tracks sum of signed_qty * price for realised PnL
        agg[sym]["cost_basis"] += signed_qty * price
        agg[sym]["abs_qty"] += abs(signed_qty)

    symbol_pnl: dict[str, SymbolPnL] = {}
    for sym, data in agg.items():
        net_pos: float = data["net_qty"]
        abs_qty: float = data["abs_qty"]
        cost: float = data["cost_basis"]

        # Average fill price: weighted by absolute quantity
        avg_fill: float = abs(cost) / abs_qty if abs_qty > 0.0 else 0.0

        close: float = close_prices.get(sym, avg_fill)

        # Realised PnL: for a round-trip the net is zero; for a net position
        # the cost basis of the traded notional is compared against the close.
        # Convention: realised = -(cost) for completed round trips, where
        # cost = sum(signed_qty * price). If we bought 10 @ 100 and sold 10
        # @ 110, cost = 10*100 + (-10)*110 = 1000 - 1100 = -100,
        # realised = -(-100) = 100 (profit). For a net open position
        # the close-side is not yet executed, so realised = 0.
        # Simpler unified formula: the fill cash flow is -cost (negative =
        # cash paid out, positive = cash received). Unrealised = net_pos *
        # close_price. Total = -cost + net_pos * close_price.
        # Splitting: realised = total for the closed portion, unrealised = rest.
        # We use: total = -cost + net_pos * close
        # unrealised = net_pos * (close - avg_fill) [open position MTM]
        # realised = total - unrealised

        total_pnl: float = -cost + net_pos * close
        unrealised: float = net_pos * (close - avg_fill)
        realised: float = total_pnl - unrealised

        symbol_pnl[sym] = SymbolPnL(
            symbol=sym,
            realised_pnl=realised,
            unrealised_pnl=unrealised,
            total_pnl=total_pnl,
            net_position=net_pos,
            avg_fill_price=avg_fill,
            close_price=close,
        )

    # Sort by total PnL for movers
    sorted_by_pnl = sorted(symbol_pnl.values(), key=lambda s: s.total_pnl, reverse=True)
    top_n = cfg.top_n_movers
    top_gainers = sorted_by_pnl[:top_n]
    top_losers = list(reversed(sorted_by_pnl[-top_n:]))

    grand_total: float = sum(s.total_pnl for s in symbol_pnl.values())

    return TradeAttributionResult(
        symbol_pnl=symbol_pnl,
        total_pnl=grand_total,
        top_gainers=top_gainers,
        top_losers=top_losers,
        n_symbols=len(symbol_pnl),
    )


# ---------------------------------------------------------------------------
# Cost attribution DTOs and engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Cost breakdown for a single trade.

    Attributes
    ----------
    symbol:
        Instrument identifier.
    notional:
        Gross traded notional (quantity * reference_price).
    spread_cost:
        Half-spread cost = quantity * abs(fill_price - reference_mid) where
        ``reference_mid`` is the supplied reference price (mid or close).
    commission:
        Explicit broker commission for the trade (always positive).
    slippage:
        Timing/slippage residual = total_cost - spread_cost - commission.
        May be negative if fill improved on the mid.
    total_cost:
        Sum of spread_cost + commission + slippage.
    spread_bps:
        spread_cost expressed in basis points of notional.
    commission_bps:
        commission expressed in basis points of notional.
    slippage_bps:
        slippage expressed in basis points of notional.
    total_bps:
        total_cost expressed in basis points of notional.
    """

    symbol: str
    notional: float
    spread_cost: float
    commission: float
    slippage: float
    total_cost: float
    spread_bps: float
    commission_bps: float
    slippage_bps: float
    total_bps: float


@dataclass(frozen=True, slots=True)
class CostAttributionResult:
    """Aggregated cost attribution across all trades.

    Attributes
    ----------
    breakdowns:
        Per-trade cost breakdown list.
    total_notional:
        Sum of all trade notionals.
    total_spread_cost:
        Sum of per-trade spread costs.
    total_commission:
        Sum of per-trade commissions.
    total_slippage:
        Sum of per-trade slippage residuals.
    total_cost:
        Sum of all cost components.
    spread_bps:
        total_spread_cost / total_notional in basis points.
    commission_bps:
        total_commission / total_notional in basis points.
    slippage_bps:
        total_slippage / total_notional in basis points.
    total_bps:
        total_cost / total_notional in basis points.
    n_trades:
        Number of trades processed.
    """

    breakdowns: list[CostBreakdown] = field(repr=False)
    total_notional: float
    total_spread_cost: float
    total_commission: float
    total_slippage: float
    total_cost: float
    spread_bps: float
    commission_bps: float
    slippage_bps: float
    total_bps: float
    n_trades: int


def cost_attribution(
    trades: list[dict[str, Any]],
    *,
    config: AttributionConfig | None = None,
) -> CostAttributionResult:
    """Decompose execution cost per trade into spread, commission, and slippage.

    Each trade is a ``dict`` with the following required keys:

    * ``symbol`` (str) -- instrument identifier
    * ``quantity`` (float) -- unsigned quantity traded
    * ``fill_price`` (float) -- actual execution price
    * ``reference_price`` (float) -- reference mid or close price
    * ``commission`` (float) -- broker commission (non-negative)
    * ``total_cost`` (float) -- observed total cost of execution (positive
      means money spent; may include market impact)

    The slippage residual is computed as:
    ``slippage = total_cost - spread_cost - commission``

    where ``spread_cost = quantity * abs(fill_price - reference_price)``.

    Parameters
    ----------
    trades:
        List of trade dicts as described above.
    config:
        :class:`AttributionConfig`.  Defaults to ``AttributionConfig()``.

    Returns
    -------
    CostAttributionResult
        Per-trade breakdowns and aggregate totals in both absolute terms and
        basis points of traded notional.

    Raises
    ------
    ValueError
        When a trade dict is missing required keys.
    """
    cfg = config if config is not None else AttributionConfig()

    required_keys = ("symbol", "quantity", "fill_price", "reference_price",
                     "commission", "total_cost")

    breakdowns: list[CostBreakdown] = []

    for idx, trade in enumerate(trades):
        for key in required_keys:
            if key not in trade:
                raise ValueError(
                    f"Trade at index {idx} is missing required key '{key}'."
                )
        sym: str = str(trade["symbol"])
        qty: float = float(trade["quantity"])
        fill: float = float(trade["fill_price"])
        ref: float = float(trade["reference_price"])
        comm: float = float(trade["commission"])
        total_c: float = float(trade["total_cost"])

        notional: float = qty * ref
        spread_c: float = qty * abs(fill - ref)
        slippage: float = total_c - spread_c - comm

        if notional > 0.0:
            scale: float = cfg.bps_scale / notional
        else:
            scale = 0.0

        breakdowns.append(CostBreakdown(
            symbol=sym,
            notional=notional,
            spread_cost=spread_c,
            commission=comm,
            slippage=slippage,
            total_cost=total_c,
            spread_bps=spread_c * scale,
            commission_bps=comm * scale,
            slippage_bps=slippage * scale,
            total_bps=total_c * scale,
        ))

    total_notional: float = sum(b.notional for b in breakdowns)
    total_spread: float = sum(b.spread_cost for b in breakdowns)
    total_comm: float = sum(b.commission for b in breakdowns)
    total_slip: float = sum(b.slippage for b in breakdowns)
    total_cost: float = sum(b.total_cost for b in breakdowns)

    if total_notional > 0.0:
        agg_scale: float = cfg.bps_scale / total_notional
    else:
        agg_scale = 0.0

    return CostAttributionResult(
        breakdowns=breakdowns,
        total_notional=total_notional,
        total_spread_cost=total_spread,
        total_commission=total_comm,
        total_slippage=total_slip,
        total_cost=total_cost,
        spread_bps=total_spread * agg_scale,
        commission_bps=total_comm * agg_scale,
        slippage_bps=total_slip * agg_scale,
        total_bps=total_cost * agg_scale,
        n_trades=len(breakdowns),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_str() -> str:
    ts = pd.Timestamp.utcnow()
    return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _fmt_float(value: float, decimals: int = 4) -> str:
    """Format a float for ASCII tables; handles inf and nan."""
    if value != value:  # NaN check
        return "n/a"
    if value == float("inf"):
        return "+inf"
    if value == float("-inf"):
        return "-inf"
    fmt = f"{{:.{decimals}f}}"
    return fmt.format(value)


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def render_attribution_report(
    factor_result: FactorAttributionResult | None,
    strategy_result: StrategyAttributionResult | None,
    trade_result: TradeAttributionResult | None,
    cost_result: CostAttributionResult | None,
    *,
    generated_at: str | None = None,
    config: AttributionConfig | None = None,
) -> str:
    """Render all attribution results as a single ASCII-only report string.

    All output is 7-bit ASCII (``ord < 128``), suitable for Windows cp1252
    consoles, ops email bodies, and log files.  Mirrors the renderer pattern
    of :func:`core_trading.risk.daily_report.render_daily_risk_report_markdown`.

    Parameters
    ----------
    factor_result:
        Output of :func:`factor_attribution`, or ``None`` to skip section.
    strategy_result:
        Output of :func:`strategy_attribution`, or ``None`` to skip section.
    trade_result:
        Output of :func:`trade_attribution`, or ``None`` to skip section.
    cost_result:
        Output of :func:`cost_attribution`, or ``None`` to skip section.
    generated_at:
        ISO UTC timestamp string embedded in the report header.  ``None``
        falls back to the config value, then to an empty string.
    config:
        :class:`AttributionConfig` for display parameters.  Defaults to
        ``AttributionConfig()``.

    Returns
    -------
    str
        ASCII-only multi-line string.
    """
    cfg = config if config is not None else AttributionConfig()
    stamp = (
        generated_at
        if generated_at is not None
        else (cfg.generated_at if cfg.generated_at is not None else "")
    )

    lines: list[str] = []
    lines.append("# Performance Attribution Report")
    lines.append("")
    lines.append(f"Generated : {stamp}")
    lines.append("")

    # --- Section 1: Factor attribution ---
    lines.append("## 1. Factor Attribution")
    lines.append("")
    if factor_result is None:
        lines.append("Not available: no factor attribution result supplied.")
    else:
        fa = factor_result
        lines.append(f"Observations       : {fa.n_obs}")
        lines.append(f"Factors            : {', '.join(fa.factor_names)}")
        lines.append(f"R-squared          : {_fmt_float(fa.r_squared)}")
        lines.append(f"Alpha (annualised) : {_fmt_float(fa.alpha_annualised)}")
        lines.append("")
        lines.append("### Factor Betas and Mean Daily Contributions")
        lines.append("")
        w_f = max(len(n) for n in fa.factor_names) + 2
        w_f = max(w_f, 18)
        w_b = 14
        w_c = 20
        header = (
            f"| {'Factor':<{w_f}} "
            f"| {'Beta':<{w_b}} "
            f"| {'Mean Contribution':<{w_c}} |"
        )
        divider = (
            f"|{'-' * (w_f + 2)}"
            f"|{'-' * (w_b + 2)}"
            f"|{'-' * (w_c + 2)}|"
        )
        lines.append(header)
        lines.append(divider)
        for name in fa.factor_names:
            b = fa.betas[name]
            mean_c = float(fa.contributions[name].mean())
            row = (
                f"| {name:<{w_f}} "
                f"| {_fmt_float(b):<{w_b}} "
                f"| {_fmt_float(mean_c):<{w_c}} |"
            )
            lines.append(row)
        lines.append("")

    # --- Section 2: Strategy attribution ---
    lines.append("## 2. Strategy Attribution")
    lines.append("")
    if strategy_result is None:
        lines.append("Not available: no strategy attribution result supplied.")
    else:
        sa = strategy_result
        lines.append(f"Observations : {sa.n_obs}")
        lines.append(f"Total Return : {_fmt_float(sa.total_return)}")
        verified_str = "YES" if sa.verified else "NO (decomposition drift)"
        lines.append(f"Additive sum verified : {verified_str}")
        lines.append("")
        lines.append("### Per-Strategy Contributions")
        lines.append("")
        w_s = max(len(n) for n in sa.strategy_names) + 2
        w_s = max(w_s, 20)
        w_w = 12
        w_c = 20
        w_t = 16
        header = (
            f"| {'Strategy':<{w_s}} "
            f"| {'Weight':<{w_w}} "
            f"| {'Total Contrib':<{w_t}} "
            f"| {'Mean Daily Contrib':<{w_c}} |"
        )
        divider = (
            f"|{'-' * (w_s + 2)}"
            f"|{'-' * (w_w + 2)}"
            f"|{'-' * (w_t + 2)}"
            f"|{'-' * (w_c + 2)}|"
        )
        lines.append(header)
        lines.append(divider)
        for name in sa.strategy_names:
            w_val = sa.weights[name]
            total_c = float(sa.contributions[name].sum())
            mean_c = float(sa.contributions[name].mean())
            row = (
                f"| {name:<{w_s}} "
                f"| {_fmt_float(w_val):<{w_w}} "
                f"| {_fmt_float(total_c):<{w_t}} "
                f"| {_fmt_float(mean_c):<{w_c}} |"
            )
            lines.append(row)
        lines.append("")

    # --- Section 3: Trade attribution ---
    lines.append("## 3. Trade Attribution")
    lines.append("")
    if trade_result is None:
        lines.append("Not available: no trade attribution result supplied.")
    else:
        ta = trade_result
        lines.append(f"Symbols traded : {ta.n_symbols}")
        lines.append(f"Session PnL    : {_fmt_float(ta.total_pnl)}")
        lines.append("")

        lines.append("### Top Gainers")
        lines.append("")
        _render_symbol_pnl_table(lines, ta.top_gainers)
        lines.append("")

        lines.append("### Top Losers")
        lines.append("")
        _render_symbol_pnl_table(lines, ta.top_losers)
        lines.append("")

    # --- Section 4: Cost attribution ---
    lines.append("## 4. Cost Attribution")
    lines.append("")
    if cost_result is None:
        lines.append("Not available: no cost attribution result supplied.")
    else:
        ca = cost_result
        lines.append(f"Trades          : {ca.n_trades}")
        lines.append(f"Total Notional  : {_fmt_float(ca.total_notional, 2)}")
        lines.append(f"Total Cost      : {_fmt_float(ca.total_cost, 4)}")
        lines.append("")
        lines.append("### Cost Summary (bps of notional)")
        lines.append("")
        w_lbl = 20
        w_abs = 14
        w_bps = 14
        header = (
            f"| {'Component':<{w_lbl}} "
            f"| {'Absolute':<{w_abs}} "
            f"| {'bps':<{w_bps}} |"
        )
        divider = (
            f"|{'-' * (w_lbl + 2)}"
            f"|{'-' * (w_abs + 2)}"
            f"|{'-' * (w_bps + 2)}|"
        )
        lines.append(header)
        lines.append(divider)
        rows = [
            ("Spread cost", ca.total_spread_cost, ca.spread_bps),
            ("Commission", ca.total_commission, ca.commission_bps),
            ("Slippage", ca.total_slippage, ca.slippage_bps),
            ("Total", ca.total_cost, ca.total_bps),
        ]
        for lbl, abs_val, bps_val in rows:
            row = (
                f"| {lbl:<{w_lbl}} "
                f"| {_fmt_float(abs_val):<{w_abs}} "
                f"| {_fmt_float(bps_val):<{w_bps}} |"
            )
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


def _render_symbol_pnl_table(lines: list[str], symbols: list[SymbolPnL]) -> None:
    """Append an ASCII table of SymbolPnL entries to ``lines`` (in-place)."""
    if not symbols:
        lines.append("(none)")
        return
    w_sym = max(len(s.symbol) for s in symbols) + 2
    w_sym = max(w_sym, 10)
    w_pnl = 14
    header = (
        f"| {'Symbol':<{w_sym}} "
        f"| {'Realised PnL':<{w_pnl}} "
        f"| {'Unrealised PnL':<{w_pnl}} "
        f"| {'Total PnL':<{w_pnl}} "
        f"| {'Net Pos':<{w_pnl}} |"
    )
    divider = (
        f"|{'-' * (w_sym + 2)}"
        f"|{'-' * (w_pnl + 2)}"
        f"|{'-' * (w_pnl + 2)}"
        f"|{'-' * (w_pnl + 2)}"
        f"|{'-' * (w_pnl + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for s in symbols:
        row = (
            f"| {s.symbol:<{w_sym}} "
            f"| {_fmt_float(s.realised_pnl):<{w_pnl}} "
            f"| {_fmt_float(s.unrealised_pnl):<{w_pnl}} "
            f"| {_fmt_float(s.total_pnl):<{w_pnl}} "
            f"| {_fmt_float(s.net_position):<{w_pnl}} |"
        )
        lines.append(row)


# ---------------------------------------------------------------------------
# Demo synthetic data builder
# ---------------------------------------------------------------------------


def _build_demo_data(
    seed: int = 42,
    n_days: int = 252,
) -> dict[str, Any]:
    """Build fully synthetic demo data for CLI smoke-testing.

    Parameters
    ----------
    seed:
        RNG seed for full determinism.
    n_days:
        Number of trading days to simulate.

    Returns
    -------
    dict
        Keys: ``factor_returns``, ``portfolio_returns``, ``strategy_returns``,
        ``strategy_weights``, ``fills``, ``close_prices``, ``trades``,
        ``generated_at``.
    """
    rng = np.random.default_rng(seed)

    dates = pd.date_range("2024-01-02", periods=n_days, freq="B")

    # --- Factor returns (market, value, momentum) ---
    factor_names = ["market", "value", "momentum"]
    factor_arr = rng.normal(0.0, 1.0, (n_days, 3)) * np.array([0.01, 0.004, 0.005])
    factor_returns = pd.DataFrame(factor_arr, index=dates, columns=factor_names)

    # --- Portfolio returns: linear combination of factors + alpha + noise ---
    true_betas = np.array([0.85, 0.20, 0.35])
    true_alpha_per_day = 0.0002
    noise = rng.normal(0.0, 0.003, n_days)
    port_arr = (
        factor_arr @ true_betas
        + true_alpha_per_day
        + noise
    )
    portfolio_returns = pd.Series(port_arr, index=dates, name="portfolio")

    # --- Strategy returns (3 strategies with separate returns) ---
    strat_names = ["momentum_strat", "mean_reversion_strat", "pairs_strat"]
    strat_arr = rng.normal(0.0, 1.0, (n_days, 3)) * np.array([0.008, 0.006, 0.005])
    strat_arr[:, 0] += 0.0003  # momentum has positive drift
    strategy_returns = pd.DataFrame(strat_arr, index=dates, columns=strat_names)
    strategy_weights = {
        "momentum_strat": 0.50,
        "mean_reversion_strat": 0.30,
        "pairs_strat": 0.20,
    }

    # --- Day's fills (10 fills across 5 symbols) ---
    symbols = ["AAPL", "MSFT", "SPY", "QQQ", "GLD"]
    base_prices = {s: float(rng.uniform(50.0, 400.0)) for s in symbols}
    fills: list[dict[str, Any]] = []
    for sym in symbols:
        price = base_prices[sym]
        fills.append({
            "symbol": sym,
            "side": "BUY",
            "quantity": float(rng.integers(10, 100)),
            "price": price * float(rng.uniform(0.999, 1.001)),
        })
    # Add some sells to create round trips on two symbols
    for sym in ["AAPL", "MSFT"]:
        fills.append({
            "symbol": sym,
            "side": "SELL",
            "quantity": float(rng.integers(5, 50)),
            "price": base_prices[sym] * float(rng.uniform(1.001, 1.005)),
        })

    # Close prices (small random move from base)
    close_prices = {
        s: base_prices[s] * float(rng.uniform(0.995, 1.005))
        for s in symbols
    }

    # --- Cost attribution trades ---
    trades: list[dict[str, Any]] = []
    for fill in fills:
        sym = fill["symbol"]
        qty = fill["quantity"]
        ref = close_prices[sym]
        fill_p = fill["price"]
        spread_c = qty * abs(fill_p - ref)
        comm = qty * 0.005  # $0.005/share commission
        slippage = qty * abs(fill_p - ref) * float(rng.uniform(0.0, 0.5))
        total_c = spread_c + comm + slippage
        trades.append({
            "symbol": sym,
            "quantity": qty,
            "fill_price": fill_p,
            "reference_price": ref,
            "commission": comm,
            "total_cost": total_c,
        })

    return {
        "factor_returns": factor_returns,
        "portfolio_returns": portfolio_returns,
        "strategy_returns": strategy_returns,
        "strategy_weights": strategy_weights,
        "fills": fills,
        "close_prices": close_prices,
        "trades": trades,
        "generated_at": "1970-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the attribution report generator.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``).  Testable without a
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.ops.attribution",
        description=(
            "Performance attribution report generator.  "
            "Use --demo to run on seeded synthetic data."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on seeded synthetic data (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (wiring live portfolio state into the CLI "
            "is a later operational concern; see module docstring)."
        )

    demo = _build_demo_data(seed=42)

    cfg = AttributionConfig(generated_at=demo["generated_at"])

    fa = factor_attribution(
        demo["portfolio_returns"],
        demo["factor_returns"],
        config=cfg,
    )
    sa = strategy_attribution(
        demo["strategy_returns"],
        demo["strategy_weights"],
        config=cfg,
    )
    ta = trade_attribution(
        demo["fills"],
        demo["close_prices"],
        config=cfg,
    )
    ca = cost_attribution(
        demo["trades"],
        config=cfg,
    )

    report = render_attribution_report(
        fa, sa, ta, ca,
        generated_at=demo["generated_at"],
        config=cfg,
    )
    print(report)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"[attribution] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
