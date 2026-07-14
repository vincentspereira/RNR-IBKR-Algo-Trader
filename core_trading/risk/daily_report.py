"""Daily risk report generator for the live/paper-trading operations workflow
(Phase 7, DOD closure: 'Stress test report auto-generated daily').

This module is a *pure generator* -- it does not touch the clock, filesystem,
or any live data source.  The recommended scheduling approaches are:

* **cron** (operator task):
      Create a "Daily Trigger" action that runs
      ``python -m core_trading.risk.daily_report --output <path>``
      once per trading day after market close.  The operator is responsible for
      wiring live portfolio state (returns panel, weights, NAV, etc.) into the
      CLI call or wrapping this module in an ops script.

* **Linux cron** (server deployment):
      ``30 16 * * 1-5  cd /path/to/repo && .venv/bin/python -m core_trading.risk.daily_report --output /reports/daily_risk.md``

* **Direct import** (programmatic use):
      Import :func:`generate_daily_risk_report` and call it directly from any
      ops script or monitoring agent; the result is a fully populated
      :class:`DailyRiskReport` DTO that can be persisted, emailed, or pushed
      to a dashboard.

CLI entry point
---------------
``python -m core_trading.risk.daily_report --demo``
    Runs a seeded synthetic portfolio and prints the full markdown report.
    Suitable for verifying the installation end-to-end without a live feed.

``python -m core_trading.risk.daily_report --demo --output <path>``
    Same as --demo but also writes the markdown to the given file path.

Reading live portfolio state into the CLI is a later operational-wiring
concern; the ``--demo`` mode is the only CLI-driven data source here.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core_trading.risk.cvar import ESConfig, historical_es
from core_trading.risk.liquidity import (
    LiquidityConfig,
    LiquidityStressReport,
    PortfolioLiquidityResult,
    days_to_liquidate,
    render_liquidity_stress_markdown,
    stress_liquidity,
)
from core_trading.risk.stress import (
    HISTORICAL_SCENARIOS,
    ScenarioResult,
    StressReport,
    apply_scenario,
    build_stress_report,
    hypothetical_shock,
    render_stress_report_markdown,
)
from core_trading.risk.var import VaRConfig, VaRResult, historical_var, parametric_var

__all__ = [
    "DailyRiskConfig",
    "VaRSection",
    "ESSection",
    "StressSection",
    "LiquiditySection",
    "DailyRiskReport",
    "generate_daily_risk_report",
    "render_daily_risk_report_markdown",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DailyRiskConfig:
    """Operational configuration for the daily risk report.

    Attributes
    ----------
    var_confidences:
        Confidence levels for which VaR (and ES) are computed.
        Default: [0.95, 0.99].
    horizon:
        Holding-period horizon in days for VaR/ES.  Default 1.
    stress_loss_limit:
        Loss fraction (positive) at which stress scenarios are flagged as
        breaches in the report.  Default 0.10 (10%).
    liquidity_config:
        Liquidity calculation parameters.  ``None`` uses module defaults.
    generated_at:
        Optional override for the UTC timestamp embedded in the report.
        ``None`` uses ``pd.Timestamp.utcnow()``.
    rng_seed:
        RNG seed forwarded to VaR estimators.
    """

    var_confidences: tuple[float, ...] = (0.95, 0.99)
    horizon: int = 1
    stress_loss_limit: float = 0.10
    liquidity_config: LiquidityConfig | None = None
    generated_at: str | None = None
    rng_seed: int | None = 42

    def __post_init__(self) -> None:
        if not self.var_confidences:
            raise ValueError("var_confidences must be non-empty.")
        for c in self.var_confidences:
            if not (0.0 < c < 1.0):
                raise ValueError(
                    f"Each confidence level must be in (0, 1); got {c!r}."
                )
        if self.horizon < 1:
            raise ValueError(f"horizon must be >= 1; got {self.horizon!r}.")
        if not (0.0 < self.stress_loss_limit <= 1.0):
            raise ValueError(
                f"stress_loss_limit must be in (0, 1]; got {self.stress_loss_limit!r}."
            )


# ---------------------------------------------------------------------------
# Report section DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VaRSection:
    """VaR section of the daily risk report.

    Attributes
    ----------
    parametric:
        Parametric VaR results keyed by confidence level.
    historical:
        Historical simulation VaR results keyed by confidence level.
    horizon:
        Holding-period horizon in days.
    """

    parametric: dict[float, VaRResult]
    historical: dict[float, VaRResult]
    horizon: int


@dataclass(frozen=True, slots=True)
class ESSection:
    """Expected Shortfall section.

    Attributes
    ----------
    historical:
        Historical ES results keyed by confidence level (positive loss).
    horizon:
        Holding-period horizon in days.
    """

    historical: dict[float, float]
    horizon: int


@dataclass(frozen=True, slots=True)
class StressSection:
    """Stress test section wrapping the full :class:`StressReport`."""

    report: StressReport


@dataclass(frozen=True, slots=True)
class LiquiditySection:
    """Liquidity section, populated only when ADV/spread data are supplied.

    Attributes
    ----------
    dtl_result:
        Portfolio days-to-liquidate summary.
    stress_report:
        Liquidity stress report (spread shock).
    """

    dtl_result: PortfolioLiquidityResult
    stress_report: LiquidityStressReport


@dataclass(frozen=True, slots=True)
class DailyRiskReport:
    """Assembled daily risk report.

    Attributes
    ----------
    var_section:
        VaR estimates at configured confidence levels.
    es_section:
        Expected Shortfall estimates.
    stress_section:
        Stress test results (historical + hypothetical scenarios).
    liquidity_section:
        Liquidity risk results.  ``None`` when ADV/spread data are absent.
    generated_at:
        ISO UTC timestamp of report generation.
    config:
        The :class:`DailyRiskConfig` used to produce this report.
    """

    var_section: VaRSection
    es_section: ESSection
    stress_section: StressSection
    liquidity_section: LiquiditySection | None
    generated_at: str
    config: DailyRiskConfig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_str() -> str:
    ts = pd.Timestamp.utcnow()
    return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _portfolio_returns_1d(
    returns_panel: pd.DataFrame,
    weights: np.ndarray,
) -> np.ndarray:
    """Compute daily portfolio return series from a panel and weight vector."""
    w = np.asarray(weights, dtype=float).ravel()
    r_mat = returns_panel.to_numpy(dtype=float)
    port_rets: np.ndarray = r_mat @ w
    finite_mask: np.ndarray = np.isfinite(port_rets)
    result: np.ndarray = port_rets[finite_mask]
    return result


def _build_hypothetical_scenarios(
    weights: np.ndarray,
    betas: np.ndarray,
    factor_names: list[str],
    factor_cov: np.ndarray,
) -> list[ScenarioResult]:
    """Build the standard set of hypothetical single-factor shock scenarios."""
    standard_shocks: list[tuple[str, dict[str, float]]] = [
        ("Equity -10%",  {"equity_return": -0.10}),
        ("Equity +10%",  {"equity_return":  0.10}),
        ("Vol +20 pts",  {"vol_change":     20.0}),
        ("Vol -20 pts",  {"vol_change":    -20.0}),
        ("Rates +50bps", {"rate_change":    0.50}),
        ("Rates -50bps", {"rate_change":   -0.50}),
    ]
    results: list[ScenarioResult] = []
    for name, shocks in standard_shocks:
        res = hypothetical_shock(
            weights,
            betas,
            shocks,
            factor_names,
            factor_cov=factor_cov,
            scenario_name=name,
        )
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------


def generate_daily_risk_report(
    returns_panel: pd.DataFrame,
    weights: np.ndarray,
    nav: float,
    *,
    betas: np.ndarray,
    factor_names: list[str],
    factor_cov: np.ndarray,
    spreads_mean: dict[str, float] | None = None,
    spreads_std: dict[str, float] | None = None,
    adv: dict[str, float] | None = None,
    positions: dict[str, float] | None = None,
    position_values: dict[str, float] | None = None,
    asset_vols: dict[str, float] | None = None,
    config: DailyRiskConfig | None = None,
) -> DailyRiskReport:
    """Generate a complete daily risk report.

    Parameters
    ----------
    returns_panel:
        Historical returns DataFrame, shape (T, N): rows are dates/bars,
        columns are asset symbols.  Must be NaN-free.
    weights:
        Current portfolio weights, shape (N,).  Aligned with panel columns.
    nav:
        Current portfolio net asset value (dollar or index units).
    betas:
        Factor-beta matrix, shape (N, F).  ``betas[i, f]`` is the sensitivity
        of asset ``i``'s return to a unit shock in factor ``f``.
    factor_names:
        List of F factor names, aligned with columns of ``betas``.
        Canonical set: ``["equity_return", "vol_change", "rate_change",
        "credit_spread", "usd_move"]``.
    factor_cov:
        Factor covariance matrix, shape (F, F).
    spreads_mean:
        Optional per-asset mean fractional bid-ask spread.  Required for the
        liquidity section; omit to skip liquidity calculations.
    spreads_std:
        Optional per-asset std of fractional bid-ask spread.
    adv:
        Optional per-asset 30-day average daily volume.
    positions:
        Optional per-asset signed position sizes (shares/units).
    position_values:
        Optional per-asset notional value (absolute dollar amount).
    asset_vols:
        Optional per-asset daily return volatility (fractional, e.g. 0.02 = 2%).
    config:
        :class:`DailyRiskConfig` controlling confidence levels, horizon, etc.
        Defaults to ``DailyRiskConfig()`` (95/99% confidence, 1-day horizon).

    Returns
    -------
    DailyRiskReport
        Fully populated DTO.  The liquidity section is ``None`` when any of
        the required liquidity inputs (spreads_mean, spreads_std, positions,
        position_values) are absent.

    Raises
    ------
    ValueError
        On invalid inputs or dimension mismatches.
    """
    cfg = config if config is not None else DailyRiskConfig()

    generated_at = cfg.generated_at if cfg.generated_at is not None else _utcnow_str()

    # --- compute portfolio return series ---
    port_rets = _portfolio_returns_1d(returns_panel, weights)

    # --- VaR section ---
    parametric_vars: dict[float, VaRResult] = {}
    historical_vars: dict[float, VaRResult] = {}
    for conf in cfg.var_confidences:
        var_cfg = VaRConfig(
            confidence=conf,
            horizon=cfg.horizon,
            rng_seed=cfg.rng_seed,
        )
        parametric_vars[conf] = parametric_var(port_rets, config=var_cfg)
        historical_vars[conf] = historical_var(port_rets, config=var_cfg)

    var_section = VaRSection(
        parametric=parametric_vars,
        historical=historical_vars,
        horizon=cfg.horizon,
    )

    # --- ES section ---
    historical_es_vals: dict[float, float] = {}
    for conf in cfg.var_confidences:
        es_cfg = ESConfig(alpha=conf, horizon=cfg.horizon)
        es_result = historical_es(port_rets, es_cfg)
        historical_es_vals[conf] = es_result.es

    es_section = ESSection(historical=historical_es_vals, horizon=cfg.horizon)

    # --- Stress section ---
    scenario_results: list[ScenarioResult] = []

    # Historical scenarios via factor-beta mode
    for scenario in HISTORICAL_SCENARIOS.values():
        res = apply_scenario(
            scenario,
            weights,
            betas=betas,
            factor_names=factor_names,
        )
        scenario_results.append(res)

    # Standard hypothetical shocks
    hypo_results = _build_hypothetical_scenarios(
        weights, betas, factor_names, factor_cov
    )
    scenario_results.extend(hypo_results)

    stress_report = build_stress_report(
        scenario_results,
        loss_limit=cfg.stress_loss_limit,
        generated_at=generated_at,
    )
    stress_section = StressSection(report=stress_report)

    # --- Liquidity section (optional) ---
    liquidity_section: LiquiditySection | None = None
    _have_liquidity_inputs = (
        spreads_mean is not None
        and spreads_std is not None
        and positions is not None
        and position_values is not None
    )
    if _have_liquidity_inputs:
        assert spreads_mean is not None
        assert spreads_std is not None
        assert positions is not None
        assert position_values is not None

        liq_cfg = cfg.liquidity_config

        dtl_result = days_to_liquidate(
            positions,
            adv if adv is not None else {},
            config=liq_cfg,
        )

        # Use the 95% parametric VaR as the base for LVaR
        base_conf = min(cfg.var_confidences)
        base_var_result = parametric_vars[base_conf]

        liq_stress = stress_liquidity(
            base_var_result,
            positions,
            position_values,
            spreads_mean,
            spreads_std,
            nav,
            adv=adv,
            asset_vols=asset_vols,
            config=liq_cfg,
            generated_at=generated_at,
        )

        liquidity_section = LiquiditySection(
            dtl_result=dtl_result,
            stress_report=liq_stress,
        )

    return DailyRiskReport(
        var_section=var_section,
        es_section=es_section,
        stress_section=stress_section,
        liquidity_section=liquidity_section,
        generated_at=generated_at,
        config=cfg,
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _render_var_es_table(report: DailyRiskReport) -> str:
    """Render the VaR/ES table as ASCII markdown."""
    lines: list[str] = []
    lines.append("## VaR and Expected Shortfall")
    lines.append("")
    lines.append(f"Horizon   : {report.var_section.horizon} day(s)")
    lines.append(f"Generated : {report.generated_at}")
    lines.append("")

    confidences = sorted(report.var_section.parametric.keys())

    # Header row
    w_conf = 10
    w_var  = 18
    header = (
        f"| {'Confidence':<{w_conf}} "
        f"| {'Parametric VaR':<{w_var}} "
        f"| {'Historical VaR':<{w_var}} "
        f"| {'Historical ES':<{w_var}} |"
    )
    divider = (
        f"|{'-' * (w_conf + 2)}"
        f"|{'-' * (w_var + 2)}"
        f"|{'-' * (w_var + 2)}"
        f"|{'-' * (w_var + 2)}|"
    )
    lines.append(header)
    lines.append(divider)

    for conf in confidences:
        para_var = report.var_section.parametric[conf].var
        hist_var = report.var_section.historical[conf].var
        hist_es  = report.es_section.historical[conf]

        conf_str = f"{conf * 100.0:.0f}%"
        row = (
            f"| {conf_str:<{w_conf}} "
            f"| {para_var:<{w_var}.6f} "
            f"| {hist_var:<{w_var}.6f} "
            f"| {hist_es:<{w_var}.6f} |"
        )
        lines.append(row)

    lines.append("")
    return "\n".join(lines)


def _render_dtl_summary(liq_section: LiquiditySection) -> str:
    """Render a compact days-to-liquidate summary."""
    lines: list[str] = []
    dtl = liq_section.dtl_result
    lines.append("## Days-to-Liquidate Summary")
    lines.append("")
    lines.append(f"Participation cap     : {dtl.participation_cap * 100.0:.1f}%")

    wadtl = dtl.weighted_avg_dtl
    wadtl_str = "inf" if wadtl == float("inf") else f"{wadtl:.2f}"
    lines.append(f"Weighted avg DTL      : {wadtl_str}")
    lines.append(f"Max DTL               : {dtl.max_dtl:.2f}")
    if dtl.flagged_assets:
        flags = ", ".join(dtl.flagged_assets)
        lines.append(f"Zero-ADV flagged      : {flags}")
    lines.append("")
    return "\n".join(lines)


def render_daily_risk_report_markdown(report: DailyRiskReport) -> str:
    """Render a :class:`DailyRiskReport` as an ASCII-only markdown string.

    Reuses the canonical renderers from :mod:`core_trading.risk.stress` and
    :mod:`core_trading.risk.liquidity` for their respective sections, and
    prepends a VaR/ES table.

    All output is 7-bit ASCII (ord < 128) -- suitable for terminal portability
    consoles, ops email bodies, and log files.

    Parameters
    ----------
    report:
        The :class:`DailyRiskReport` to render.

    Returns
    -------
    str
        ASCII-only markdown string.
    """
    parts: list[str] = []

    parts.append("# Daily Risk Report")
    parts.append("")
    parts.append(f"Generated : {report.generated_at}")
    parts.append("NAV       : (see liquidity section below)")
    parts.append("")

    # --- VaR / ES table ---
    parts.append(_render_var_es_table(report))

    # --- Stress section ---
    parts.append(render_stress_report_markdown(report.stress_section.report))

    # --- Liquidity section ---
    if report.liquidity_section is not None:
        parts.append(_render_dtl_summary(report.liquidity_section))
        parts.append(
            render_liquidity_stress_markdown(report.liquidity_section.stress_report)
        )
    else:
        parts.append("## Liquidity Section")
        parts.append("")
        parts.append(
            "Not available: requires spreads_mean, spreads_std, positions, position_values."
        )
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Demo synthetic portfolio builder
# ---------------------------------------------------------------------------


def _build_demo_portfolio(
    seed: int = 42,
    n_obs: int = 504,
    n_assets: int = 4,
) -> dict[str, Any]:
    """Build a fully synthetic demo portfolio for CLI smoke-testing."""
    rng = np.random.default_rng(seed)

    # --- returns panel ---
    dates = pd.date_range("2022-01-03", periods=n_obs, freq="B")
    sigmas = rng.uniform(0.008, 0.020, size=n_assets)
    returns_arr = rng.normal(0.0, 1.0, size=(n_obs, n_assets)) * sigmas
    asset_names = [f"ASSET{i + 1}" for i in range(n_assets)]
    returns_panel = pd.DataFrame(returns_arr, index=dates, columns=asset_names)

    # --- equal weights ---
    weights = np.full(n_assets, 1.0 / n_assets, dtype=float)

    # --- factor model (5 canonical factors) ---
    factor_names: list[str] = [
        "equity_return",
        "vol_change",
        "rate_change",
        "credit_spread",
        "usd_move",
    ]
    n_f = len(factor_names)
    # Synthetic betas in each factor's NATURAL units (the stress.py beta
    # contract: asset return per unit factor shock).  Scenario shocks use
    # heterogeneous units -- equity/usd in decimal returns, vol in VIX
    # points, rates in percentage points, credit in basis points -- so the
    # beta scales must match or scenario P&L is inflated by orders of
    # magnitude.
    betas = np.empty((n_assets, n_f), dtype=float)
    betas[:, 0] = rng.uniform(0.7, 1.2, size=n_assets)        # per 1.0 equity ret
    betas[:, 1] = rng.uniform(-0.002, 0.0, size=n_assets)     # per VIX point
    betas[:, 2] = rng.uniform(-0.01, 0.01, size=n_assets)     # per pct point
    betas[:, 3] = rng.uniform(-2e-4, 0.0, size=n_assets)      # per basis point
    betas[:, 4] = rng.uniform(-0.2, 0.2, size=n_assets)       # per 1.0 USD ret

    # Positive-definite factor covariance, variances on the same natural
    # units as the betas above (daily scales: equity/usd in decimal
    # returns, vol in VIX pts, rates in pct pts, credit in bps).
    factor_scales = np.array([0.01, 1.5, 0.05, 5.0, 0.005])
    raw = rng.normal(0.0, 1.0, size=(n_f, n_f))
    corr = raw @ raw.T / float(n_f) + np.eye(n_f) * 0.5
    d_inv = 1.0 / np.sqrt(np.diag(corr))
    corr = corr * np.outer(d_inv, d_inv)
    factor_cov = corr * np.outer(factor_scales, factor_scales)

    # --- liquidity inputs ---
    nav = 1_000_000.0
    base_price = rng.uniform(20.0, 200.0, size=n_assets)
    shares = (nav * weights / base_price).astype(float)
    position_values = {a: float(shares[i] * base_price[i]) for i, a in enumerate(asset_names)}
    positions = {a: float(shares[i]) for i, a in enumerate(asset_names)}
    adv_vals = {a: float(rng.uniform(500_000, 5_000_000)) for a in asset_names}
    spreads_mean_vals = {a: float(rng.uniform(0.0005, 0.002)) for a in asset_names}
    spreads_std_vals = {a: float(spreads_mean_vals[a] * 0.3) for a in asset_names}
    asset_vols_vals = {a: float(sigmas[i]) for i, a in enumerate(asset_names)}

    return {
        "returns_panel": returns_panel,
        "weights": weights,
        "nav": nav,
        "betas": betas,
        "factor_names": factor_names,
        "factor_cov": factor_cov,
        "spreads_mean": spreads_mean_vals,
        "spreads_std": spreads_std_vals,
        "adv": adv_vals,
        "positions": positions,
        "position_values": position_values,
        "asset_vols": asset_vols_vals,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the daily risk report generator.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``).  Testable without
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.risk.daily_report",
        description=(
            "Daily risk report generator.  "
            "Use --demo to run on a seeded synthetic portfolio."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on a seeded synthetic portfolio (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the markdown report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (reading live portfolio state is a "
            "later operational-wiring concern; see module docstring)."
        )

    demo = _build_demo_portfolio(seed=42)
    report = generate_daily_risk_report(
        demo["returns_panel"],
        demo["weights"],
        demo["nav"],
        betas=demo["betas"],
        factor_names=demo["factor_names"],
        factor_cov=demo["factor_cov"],
        spreads_mean=demo["spreads_mean"],
        spreads_std=demo["spreads_std"],
        adv=demo["adv"],
        positions=demo["positions"],
        position_values=demo["position_values"],
        asset_vols=demo["asset_vols"],
    )
    markdown = render_daily_risk_report_markdown(report)
    print(markdown)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        print(f"[daily_report] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
