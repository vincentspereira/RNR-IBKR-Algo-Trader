"""Portfolio stress testing -- historical scenarios, hypothetical shocks,
reverse stress tests, and stress reports (Phase 7, module 7.5).

Sign convention
---------------
All P&L figures follow the positive-loss convention used throughout
``core_trading.risk`` (var.py, cvar.py): a *positive* number means a *loss*.
``scenario_pnl > 0`` => the portfolio loses money under that scenario.

Module overview
---------------
1. ``FactorShock``           -- immutable record for one named factor shock.
2. ``HistoricalScenario``    -- dated scenario window + canonical factor shocks.
3. ``HISTORICAL_SCENARIOS``  -- built-in library (GFC, flash crash, etc.).
4. ``apply_scenario``        -- map a scenario onto portfolio P&L.
5. ``hypothetical_shock``    -- parametric single- and multi-factor shocks.
6. ``reverse_stress_linear`` -- analytic Mahalanobis-norm reverse stress test
                                for linear portfolios.
7. ``reverse_stress_numeric``-- grid / numeric fallback for nonlinear P&L.
8. ``ScenarioResult``        -- per-scenario P&L DTO.
9. ``StressReport``          -- full report DTO.
10. ``build_stress_report``  -- assemble a StressReport from scenarios.
11. ``render_stress_report_markdown`` -- ASCII markdown table for ops reports.

Historical scenario data
------------------------
Factor shock magnitudes are sourced from well-known public sources and cited
inline.  Factors are:

    equity_return   -- total return of a broad equity index (e.g. S&P 500)
                       over the scenario window (fractional, negative = fall).
    vol_change      -- absolute change in implied vol (e.g. VIX points).
    rate_change     -- absolute change in 10-year Treasury yield (pp).
    credit_spread   -- absolute change in IG credit spread (bps, positive=wide).
    usd_move        -- DXY percentage change (positive = USD strengthens).

Mathematical references
-----------------------
Studer, G. (1997). "Maximum Loss for Measurement of Market Risk."
    Dissertation, ETH Zurich.  Derives the worst-case factor-shock under a
    Mahalanobis-norm budget as the closed-form solution to a constrained
    quadratic programme; see :func:`reverse_stress_linear`.

Breuer, T., Jandacka, M., Rheinberger, K. & Summer, M. (2009).
    "How to find plausible, severe and useful stress scenarios."
    International Journal of Central Banking, 5(3), 205-224.
    Provides the rigorous theoretical framework connecting Mahalanobis distance
    to scenario plausibility.

BIS (2009). "Principles for sound stress testing practices and supervision."
    Basel Committee on Banking Supervision, Basel.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.optimize as sp_opt

__all__ = [
    "FactorShock",
    "HistoricalScenario",
    "HISTORICAL_SCENARIOS",
    "apply_scenario",
    "hypothetical_shock",
    "reverse_stress_linear",
    "reverse_stress_numeric",
    "ScenarioResult",
    "StressReport",
    "build_stress_report",
    "render_stress_report_markdown",
]

# ---------------------------------------------------------------------------
# Factor shock DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorShock:
    """A single named factor shock.

    Attributes
    ----------
    name:
        Factor identifier (e.g. ``"equity_return"``).
    magnitude:
        Shock magnitude in the factor's natural units.
        Equity return: fractional (e.g. -0.30 = -30%).
        Vol change: absolute VIX points (e.g. +30.0).
        Rate change: percentage points (e.g. +0.50 = +50 bps).
        Credit spread: basis points (e.g. +200.0).
        USD move: fractional DXY return (e.g. +0.05 = +5%).
    """

    name: str
    magnitude: float


# ---------------------------------------------------------------------------
# Historical scenario DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistoricalScenario:
    """A historical stress scenario defined by a dated window and factor shocks.

    Attributes
    ----------
    name:
        Human-readable scenario label (ASCII only).
    start:
        Scenario window start date (inclusive) as ``"YYYY-MM-DD"``.
    end:
        Scenario window end date (inclusive) as ``"YYYY-MM-DD"``.
    shocks:
        Mapping from factor name to :class:`FactorShock`.  The canonical
        factors are ``equity_return``, ``vol_change``, ``rate_change``,
        ``credit_spread``, and ``usd_move``.
    description:
        One-line description for reports.
    """

    name: str
    start: str
    end: str
    shocks: dict[str, FactorShock]
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in historical scenario library
# ---------------------------------------------------------------------------
# Sources for magnitudes:
#   GFC 2008   : S&P 500 Sep-Nov 2008 = -30.5% (Bloomberg);
#                VIX peak Nov 20 2008 ~ 80 vs ~24 start Sep = +56 pts but
#                window change ~+40 pts; 10yr UST Sep->Nov 08 ~5.0->3.5 = -150bps
#                (Fed H.15); IG spread +~250bps (Merrill JULI Sep-Nov 08);
#                DXY Sep-Nov 2008 approx +8% (safe-haven USD bid).
#   Flash crash: May 6 2010 S&P 500 intraday low ~-9.2% from open, closed ~-3.2%
#                (SEC/CFTC "Flash Crash" report Oct 2010).  1-day, minimal
#                rate/spread move; VIX intraday spike ~+15 pts; DXY +0.5%.
#   CNY Aug 2015: Aug 2015 S&P 500 -11.2% over ~Aug 18-26 (Bloomberg);
#                 VIX Aug 18->24 approx +15 pts; 10yr UST -20bps (flight to quality);
#                 IG spread +40bps (Barclays data); DXY -2% (USD unwound).
#   Q4 2018    : S&P 500 Oct-Dec 2018 = -19.8% (Bloomberg);
#                VIX Dec 24 2018 ~36 vs Oct 1 ~12 = +24pts;
#                10yr UST Oct->Dec 2018 3.23%->2.68% = -55bps;
#                IG spread +~60bps (ICE BofA); DXY +3% (modest safe-haven).
#   COVID 2020 : S&P 500 Feb 19 - Mar 23 2020 = -33.9% (Bloomberg);
#                VIX Feb 19 ~15 -> Mar 16 peak 82.7 = +67pts (intraperiod +~50 by Mar 23);
#                10yr UST Feb 19 1.58% -> Mar 9 low 0.54% ~-100bps;
#                IG spread +~240bps (ICE BofA IG); DXY Feb-Mar 2020 +4%.
#   2022 rates : Jan 3 - Dec 30 2022 S&P 500 = -19.4% (Bloomberg);
#                VIX year-avg ~25 vs 2021 ~17, end-of-year ~21; use window
#                +5pts; 10yr UST Jan 2022 1.51% -> Dec 2022 3.88% = +237bps;
#                IG spread +~50bps (ICE BofA); DXY Jan-Sep 2022 +15% (OECD).

def _mk_shocks(**kwargs: float) -> dict[str, FactorShock]:
    """Build a shocks dict from keyword factor->magnitude pairs."""
    return {k: FactorShock(name=k, magnitude=v) for k, v in kwargs.items()}


HISTORICAL_SCENARIOS: dict[str, HistoricalScenario] = {
    "gfc_2008": HistoricalScenario(
        name="GFC 2008 (Sep-Nov 2008)",
        start="2008-09-01",
        end="2008-11-30",
        shocks=_mk_shocks(
            equity_return=-0.305,   # S&P 500 Sep-Nov 2008 ~ -30.5%
            vol_change=40.0,        # VIX approx +40 pts over window
            rate_change=-1.50,      # 10yr UST -150bps (flight to quality)
            credit_spread=250.0,    # IG spread +250bps (Merrill JULI)
            usd_move=0.08,          # DXY +8% (safe-haven USD)
        ),
        description="Global Financial Crisis: Lehman collapse and credit freeze",
    ),
    "flash_crash_2010": HistoricalScenario(
        name="Flash Crash (2010-05-06)",
        start="2010-05-06",
        end="2010-05-06",
        shocks=_mk_shocks(
            equity_return=-0.032,   # S&P 500 close-to-close ~ -3.2%
            vol_change=15.0,        # VIX intraday spike ~+15 pts
            rate_change=-0.05,      # minimal Treasury move ~ -5bps
            credit_spread=10.0,     # minimal spread widening ~ +10bps
            usd_move=0.005,         # DXY +0.5%
        ),
        description="May 6 2010 flash crash: rapid algorithmic liquidity withdrawal",
    ),
    "cny_deval_2015": HistoricalScenario(
        name="CNY Devaluation Aug 2015",
        start="2015-08-18",
        end="2015-08-26",
        shocks=_mk_shocks(
            equity_return=-0.112,   # S&P 500 ~ -11.2% Aug 18-26
            vol_change=15.0,        # VIX approx +15 pts
            rate_change=-0.20,      # 10yr UST -20bps (flight to quality)
            credit_spread=40.0,     # IG spread +40bps
            usd_move=-0.02,         # DXY -2% (USD risk-off unwind)
        ),
        description="China CNY devaluation and emerging-market selloff",
    ),
    "q4_2018": HistoricalScenario(
        name="Q4 2018 Selloff (Oct-Dec 2018)",
        start="2018-10-01",
        end="2018-12-31",
        shocks=_mk_shocks(
            equity_return=-0.198,   # S&P 500 ~ -19.8%
            vol_change=24.0,        # VIX +24pts (12->36)
            rate_change=-0.55,      # 10yr UST -55bps (Fed pivot expectations)
            credit_spread=60.0,     # IG spread +60bps (ICE BofA)
            usd_move=0.03,          # DXY +3%
        ),
        description="Q4 2018: Fed tightening fears and trade-war driven equity rout",
    ),
    "covid_2020": HistoricalScenario(
        name="COVID Crash (Feb 19 - Mar 23 2020)",
        start="2020-02-19",
        end="2020-03-23",
        shocks=_mk_shocks(
            equity_return=-0.339,   # S&P 500 ~ -33.9%
            vol_change=50.0,        # VIX 15->~65 during window ~ +50pts
            rate_change=-1.00,      # 10yr UST -100bps (Fed emergency cuts)
            credit_spread=240.0,    # IG spread +240bps (ICE BofA IG)
            usd_move=0.04,          # DXY +4% (initial safe-haven)
        ),
        description="COVID-19 pandemic crash: synchronized global risk-off",
    ),
    "inflation_rates_2022": HistoricalScenario(
        name="Inflation/Rates Shock 2022 (Jan-Dec 2022)",
        start="2022-01-03",
        end="2022-12-30",
        shocks=_mk_shocks(
            equity_return=-0.194,   # S&P 500 ~ -19.4%
            vol_change=5.0,         # VIX modest +5pts (not a spike year)
            rate_change=2.37,       # 10yr UST +237bps (1.51% -> 3.88%)
            credit_spread=50.0,     # IG spread +50bps
            usd_move=0.10,          # DXY +10% (broad USD strength)
        ),
        description="2022 inflation shock: fastest Fed hiking cycle since 1980",
    ),
}


# ---------------------------------------------------------------------------
# Scenario result DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """P&L outcome of a single stress scenario.

    Attributes
    ----------
    scenario_name:
        Label of the scenario (``HistoricalScenario.name`` or user label).
    pnl:
        Portfolio P&L as a *positive loss* fraction of NAV.
        Positive = portfolio loses; negative = portfolio gains.
    method:
        How the P&L was computed: ``"replay"`` (actual returns panel) or
        ``"factor_beta"`` (factor-beta mapping from shocks).
    details:
        Optional dict of per-asset or per-factor attribution details.
    """

    scenario_name: str
    pnl: float
    method: str
    details: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# apply_scenario -- historical scenario P&L
# ---------------------------------------------------------------------------


def apply_scenario(
    scenario: HistoricalScenario,
    weights: np.ndarray | pd.Series,
    *,
    returns_panel: pd.DataFrame | None = None,
    betas: np.ndarray | None = None,
    factor_names: list[str] | None = None,
) -> ScenarioResult:
    """Compute portfolio P&L under a historical stress scenario.

    Two modes:

    **Replay mode** (preferred when historical data covers the window):
        Pass ``returns_panel``.  The panel must include dates spanning
        ``[scenario.start, scenario.end]``.  The portfolio return over the
        window is the dot product of weights with the *compounded* multi-day
        asset returns (product of (1 + r_t) - 1 over dates in window).
        The result is negated to convert gain -> loss (positive loss convention).

    **Factor-beta mode** (when panel data is unavailable):
        Pass ``betas`` (shape N x F) and ``factor_names`` (length F, matching
        the keys of ``scenario.shocks``).  The P&L per asset is::

            pnl_i = sum_f  betas[i, f] * shocks[factor_names[f]]

        Portfolio P&L = weights @ pnl_per_asset.  Positive loss convention.

    Parameters
    ----------
    scenario:
        The :class:`HistoricalScenario` to apply.
    weights:
        Portfolio weights, shape (N,).  Need not sum to 1.
    returns_panel:
        Optional DataFrame (rows = dates, columns = assets) of simple returns.
        Dates must span the scenario window; NaN not permitted in the window.
    betas:
        Optional factor-beta matrix, shape (N, F).  Required when
        ``returns_panel`` is None.  ``betas[i, f]`` is the sensitivity of
        asset i's return to a unit shock in factor f.
    factor_names:
        List of factor names of length F, aligned with columns of ``betas``.
        Each name must be a key in ``scenario.shocks``.

    Returns
    -------
    ScenarioResult

    Raises
    ------
    ValueError
        On invalid or inconsistent inputs, missing dates, or NaN values.
    """
    w = np.asarray(weights, dtype=float).ravel()
    n_assets = w.shape[0]

    if returns_panel is not None:
        # -- Replay mode -------------------------------------------------------
        start = pd.Timestamp(scenario.start)
        end = pd.Timestamp(scenario.end)
        panel = returns_panel
        if not isinstance(panel.index, pd.DatetimeIndex):
            raise ValueError(
                "returns_panel must have a DatetimeIndex when using replay mode."
            )
        window = panel.loc[start:end]
        if window.shape[0] == 0:
            raise ValueError(
                f"returns_panel contains no dates in [{scenario.start}, {scenario.end}]; "
                "cannot replay scenario."
            )
        if window.shape[1] != n_assets:
            raise ValueError(
                f"returns_panel has {window.shape[1]} columns but weights has "
                f"{n_assets} elements."
            )
        arr = window.to_numpy(dtype=float)
        if not np.isfinite(arr).all():
            raise ValueError(
                "returns_panel contains NaN or Inf values within the scenario window."
            )
        # Compound returns: (1+r_1)*(1+r_2)*...(1+r_T) - 1 per asset
        compounded: np.ndarray = np.prod(1.0 + arr, axis=0) - 1.0
        # Portfolio return (positive = gain)
        port_return = float(w @ compounded)
        # Convert gain to positive-loss convention
        pnl = -port_return
        details: dict[str, float] = {
            str(col): float(compounded[i])
            for i, col in enumerate(window.columns)
        }
        return ScenarioResult(
            scenario_name=scenario.name,
            pnl=pnl,
            method="replay",
            details=details,
        )

    # -- Factor-beta mode ------------------------------------------------------
    if betas is None or factor_names is None:
        raise ValueError(
            "Provide returns_panel for replay mode, or betas + factor_names "
            "for factor-beta mode."
        )
    beta_arr = np.asarray(betas, dtype=float)
    if beta_arr.ndim != 2:
        raise ValueError(
            f"betas must be a 2-D array (N x F); got shape {beta_arr.shape}."
        )
    n_b, n_f = beta_arr.shape
    if n_b != n_assets:
        raise ValueError(
            f"betas has {n_b} rows but weights has {n_assets} elements."
        )
    if len(factor_names) != n_f:
        raise ValueError(
            f"factor_names has {len(factor_names)} entries but betas has {n_f} columns."
        )
    # Build factor shock vector from scenario.shocks
    shock_vec = np.zeros(n_f, dtype=float)
    for j, fname in enumerate(factor_names):
        if fname not in scenario.shocks:
            raise ValueError(
                f"Factor '{fname}' not found in scenario shocks; "
                f"available: {list(scenario.shocks.keys())}."
            )
        shock_vec[j] = scenario.shocks[fname].magnitude

    # Per-asset P&L from factor betas (positive = gain for equity-return factor)
    # For equity_return factor: if shock = -0.30 and beta = 1.0 then return = -0.30
    # portfolio_return = w @ (betas @ shock_vec); loss = -portfolio_return
    per_asset_return = beta_arr @ shock_vec
    port_return = float(w @ per_asset_return)
    pnl = -port_return   # positive loss convention
    factor_attr: dict[str, float] = {}
    for j, fname in enumerate(factor_names):
        contrib = float(w @ (beta_arr[:, j] * shock_vec[j]))
        factor_attr[fname] = -contrib  # loss attribution per factor
    return ScenarioResult(
        scenario_name=scenario.name,
        pnl=pnl,
        method="factor_beta",
        details=factor_attr,
    )


# ---------------------------------------------------------------------------
# hypothetical_shock -- parametric single- and multi-factor shocks
# ---------------------------------------------------------------------------


def hypothetical_shock(
    weights: np.ndarray | pd.Series,
    betas: np.ndarray,
    factor_shocks: dict[str, float],
    factor_names: list[str],
    *,
    factor_cov: np.ndarray | None = None,
    scenario_name: str = "hypothetical",
) -> ScenarioResult:
    """Apply a parametric (hypothetical) multi-factor shock to a portfolio.

    The portfolio P&L under the shock is::

        pnl = -(weights @ (betas @ shock_vector))

    (positive = loss, consistent with the module sign convention).

    If ``factor_cov`` is provided, the function also computes a VaR-under-
    stress figure: the portfolio vol is scaled by the ratio of stressed-vol
    to baseline-vol (where vol = sqrt(w'C_f w) with C_f the factor covariance).
    The ``details`` dict includes ``"stressed_port_vol"``.

    Built-in standard shocks (use ``factor_shocks`` with these values):

    * equity_return:  +/-0.10  (+/-10% equity shock)
    * rate_change:    +/-0.005 (+/-50bp rate shock; in pp units: +/-0.50)
    * vol_change:     +/-20.0  (+/-20 VIX pts)

    Parameters
    ----------
    weights:
        Portfolio weights, shape (N,).
    betas:
        Factor-beta matrix, shape (N, F).
    factor_shocks:
        Mapping from factor name to shock magnitude.  Factors absent from
        this dict receive a zero shock.
    factor_names:
        List of length F naming the columns of ``betas``.
    factor_cov:
        Optional factor covariance matrix, shape (F, F).  When supplied,
        the effective portfolio vol under the shock is appended to ``details``.
    scenario_name:
        Label for the :class:`ScenarioResult`.

    Returns
    -------
    ScenarioResult
        ``method="factor_beta"``.

    Raises
    ------
    ValueError
        On dimension mismatches or invalid inputs.
    """
    w = np.asarray(weights, dtype=float).ravel()
    n_assets = w.shape[0]
    beta_arr = np.asarray(betas, dtype=float)
    if beta_arr.ndim != 2:
        raise ValueError(
            f"betas must be 2-D (N x F); got shape {beta_arr.shape}."
        )
    n_b, n_f = beta_arr.shape
    if n_b != n_assets:
        raise ValueError(
            f"betas has {n_b} rows but weights has {n_assets} elements."
        )
    if len(factor_names) != n_f:
        raise ValueError(
            f"factor_names has {len(factor_names)} entries but betas has {n_f} columns."
        )
    # Build shock vector (zero-pad factors not in factor_shocks)
    shock_vec = np.zeros(n_f, dtype=float)
    for j, fname in enumerate(factor_names):
        shock_vec[j] = factor_shocks.get(fname, 0.0)

    per_asset_return = beta_arr @ shock_vec
    port_return = float(w @ per_asset_return)
    pnl = -port_return

    details: dict[str, float] = {}
    for j, fname in enumerate(factor_names):
        contrib = float(w @ (beta_arr[:, j] * shock_vec[j]))
        details[f"pnl_{fname}"] = -contrib

    if factor_cov is not None:
        fc = np.asarray(factor_cov, dtype=float)
        if fc.shape != (n_f, n_f):
            raise ValueError(
                f"factor_cov must be shape ({n_f}, {n_f}); got {fc.shape}."
            )
        # Effective portfolio factor-loading: g = (B' w)  shape (F,)
        g = beta_arr.T @ w
        port_factor_var = float(g @ fc @ g)
        stressed_port_vol = float(np.sqrt(max(port_factor_var, 0.0)))
        details["stressed_port_vol"] = stressed_port_vol

    return ScenarioResult(
        scenario_name=scenario_name,
        pnl=pnl,
        method="factor_beta",
        details=details,
    )


# ---------------------------------------------------------------------------
# Reverse stress test -- analytic (linear portfolios)
# ---------------------------------------------------------------------------
# Derivation (Studer 1997 / Breuer et al. 2009):
#
# For a linear portfolio P&L:
#     L(f) = -(w @ B @ f) = -g' f    where g = B' w  (shape F)
#
# We seek the smallest Mahalanobis-norm factor shock f* that achieves a loss
# of at least lambda (target loss as a positive fraction of NAV):
#
#     min  f' Sigma_f^{-1} f   subject to  -g' f >= lambda
#
# Lagrangian:  L = f' Sigma_f^{-1} f - mu (g' f + lambda)
# First-order: 2 Sigma_f^{-1} f = mu g
#              => f* = (mu/2) Sigma_f g
# Constraint:  -g' f* = lambda
#              -g' (mu/2) Sigma_f g = lambda
#              mu = -2 lambda / (g' Sigma_f g)
# So:
#     f* = -(lambda / (g' Sigma_f g)) * Sigma_f g
#
# And the minimum Mahalanobis norm:
#     ||f*||_M^2 = lambda^2 / (g' Sigma_f g)
#
# This is equation (3) / Proposition 1 in Breuer et al. (2009), and
# corresponds to Studer's (1997) "maximum loss" direction.


def reverse_stress_linear(
    weights: np.ndarray | pd.Series,
    betas: np.ndarray,
    factor_cov: np.ndarray,
    factor_names: list[str],
    loss_target: float,
) -> tuple[dict[str, float], float]:
    """Analytic reverse stress test for linear portfolios (Studer 1997).

    Finds the minimum-Mahalanobis-norm factor shock ``f*`` such that the
    portfolio loss equals ``loss_target`` (positive loss fraction of NAV).

    The closed-form solution is::

        g    = B' w                            (effective factor loading, F-vec)
        f*   = -(lambda / (g' Sigma g)) * Sigma g
        m*^2 = lambda^2 / (g' Sigma g)        (squared Mahalanobis norm)

    where ``Sigma = factor_cov``, ``lambda = loss_target``, and ``B`` is the
    beta matrix (N x F).  See module docstring for full derivation.

    Parameters
    ----------
    weights:
        Portfolio weights, shape (N,).
    betas:
        Factor-beta matrix, shape (N, F).
    factor_cov:
        Factor covariance matrix, shape (F, F).  Must be positive definite.
    factor_names:
        Names of the F factors, length F.
    loss_target:
        Target loss as a positive fraction of NAV (e.g. 0.10 = 10% loss).
        Must be > 0.

    Returns
    -------
    tuple[dict[str, float], float]
        ``(shock_dict, mahalanobis_norm)`` where ``shock_dict`` maps each
        factor name to its optimal shock magnitude, and ``mahalanobis_norm``
        is the Mahalanobis norm ``||f*||_M = sqrt(f*' Sigma^{-1} f*)``.

    Raises
    ------
    ValueError
        If ``loss_target <= 0``, dimension mismatches, or the effective
        factor loading ``g`` is zero (portfolio has no factor exposure).
    """
    if loss_target <= 0.0:
        raise ValueError(
            f"loss_target must be > 0; got {loss_target!r}"
        )
    w = np.asarray(weights, dtype=float).ravel()
    n_assets = w.shape[0]
    B = np.asarray(betas, dtype=float)
    if B.ndim != 2 or B.shape[0] != n_assets:
        raise ValueError(
            f"betas must be 2-D shape (N, F) with N={n_assets}; got {B.shape}."
        )
    n_f = B.shape[1]
    if len(factor_names) != n_f:
        raise ValueError(
            f"factor_names length {len(factor_names)} != betas columns {n_f}."
        )
    Sigma = np.asarray(factor_cov, dtype=float)
    if Sigma.shape != (n_f, n_f):
        raise ValueError(
            f"factor_cov must be ({n_f}, {n_f}); got {Sigma.shape}."
        )

    # Effective portfolio factor loading: g = B' w
    g = B.T @ w   # shape (F,)
    Sigma_g = Sigma @ g   # shape (F,)
    g_Sigma_g = float(g @ Sigma_g)

    if g_Sigma_g <= 0.0:
        raise ValueError(
            "Portfolio has zero factor exposure (g' Sigma g = 0); "
            "reverse stress test is undefined."
        )

    # Analytic worst-case shock: f* = -(lambda / (g' Sigma g)) * Sigma g
    f_star = -(loss_target / g_Sigma_g) * Sigma_g

    # Mahalanobis norm: ||f*||_M^2 = f*' Sigma^{-1} f*
    # = (lambda^2 / (g'Sg)^2) * g'S S^{-1} S g
    # = lambda^2 / (g' Sigma g)
    mahal_norm = float(math.sqrt(loss_target**2 / g_Sigma_g))

    shock_dict = {
        factor_names[j]: float(f_star[j]) for j in range(n_f)
    }
    return shock_dict, mahal_norm


# ---------------------------------------------------------------------------
# Reverse stress test -- numeric fallback (nonlinear P&L)
# ---------------------------------------------------------------------------


def reverse_stress_numeric(
    pnl_fn: Callable[[dict[str, float]], float],
    factor_names: list[str],
    factor_cov: np.ndarray,
    loss_target: float,
    *,
    grid_steps: int = 15,
    refine: bool = True,
    rng_seed: int = 42,
) -> tuple[dict[str, float], float]:
    """Numeric reverse stress test for nonlinear P&L functions.

    Finds an approximate minimum-Mahalanobis-norm factor shock that achieves
    ``loss_target`` using a two-phase approach:

    **Phase 1 -- Mahalanobis ball grid search:**
        Draw random directions on the F-dimensional unit sphere; scale each to
        a target Mahalanobis radius; evaluate ``pnl_fn``; record all directions
        that achieve >= ``loss_target``; return the one with the smallest radius.

    **Phase 2 -- scipy minimisation (optional):**
        If ``refine=True``, use ``scipy.optimize.minimize`` (SLSQP) starting
        from the best grid point to minimise the Mahalanobis norm subject to
        ``pnl_fn(f) >= loss_target``.

    The Mahalanobis-norm ball is parameterised as:
        f(r, d) = r * L d    where L = chol(Sigma), d is a unit vector,
        ||f||_M = r

    Parameters
    ----------
    pnl_fn:
        Callable mapping a ``dict[factor_name -> shock_magnitude]`` to a
        scalar portfolio P&L (positive = loss).  Will be called O(grid_steps^2)
        times during the grid search.
    factor_names:
        List of F factor names.
    factor_cov:
        Factor covariance matrix, shape (F, F).  Must be positive definite.
    loss_target:
        Target loss as a positive fraction of NAV.  Must be > 0.
    grid_steps:
        Number of radii and directions to explore per dimension in the grid
        search.  Total evaluations ~ ``grid_steps ** 2`` for 2-D; more
        directions are sampled for higher dimensions.
    refine:
        If True (default), refine the best grid point with SLSQP.
    rng_seed:
        Seed for the numpy Generator used to sample random directions.

    Returns
    -------
    tuple[dict[str, float], float]
        ``(shock_dict, mahalanobis_norm)`` -- same semantics as
        :func:`reverse_stress_linear`.

    Raises
    ------
    ValueError
        On invalid inputs or if no grid point achieves ``loss_target``.
    """
    if loss_target <= 0.0:
        raise ValueError(f"loss_target must be > 0; got {loss_target!r}")
    n_f = len(factor_names)
    if n_f < 1:
        raise ValueError("factor_names must be non-empty.")
    Sigma = np.asarray(factor_cov, dtype=float)
    if Sigma.shape != (n_f, n_f):
        raise ValueError(
            f"factor_cov must be ({n_f}, {n_f}); got {Sigma.shape}."
        )

    # Cholesky decomposition: Sigma = L L'; f = L d for unit d => ||f||_M = ||d||
    try:
        L = np.linalg.cholesky(Sigma)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "factor_cov is not positive definite; Cholesky failed."
        ) from exc

    rng = np.random.default_rng(rng_seed)
    n_dirs = max(grid_steps * grid_steps, 100)
    # Sample random unit directions in R^F via normalised Gaussian
    raw_dirs = rng.standard_normal((n_dirs, n_f))
    norms = np.linalg.norm(raw_dirs, axis=1, keepdims=True)
    norms = np.where(norms < 1e-12, 1.0, norms)
    unit_dirs = raw_dirs / norms   # shape (n_dirs, F)

    # Radii to test: log-spaced from small to reasonably large
    max_radius = float(math.sqrt(n_f)) * 5.0
    radii = np.exp(np.linspace(math.log(1e-3), math.log(max_radius), grid_steps))

    best_f: np.ndarray | None = None
    best_radius = math.inf

    for d in unit_dirs:
        for r in radii:
            f_vec = r * (L @ d)   # map to factor space
            shock_dict = {factor_names[j]: float(f_vec[j]) for j in range(n_f)}
            pnl_val = pnl_fn(shock_dict)
            if pnl_val >= loss_target and r < best_radius:
                best_radius = r
                best_f = f_vec.copy()

    if best_f is None:
        raise ValueError(
            f"Grid search found no shock achieving loss_target={loss_target:.4f}; "
            "increase grid_steps or check pnl_fn."
        )

    if refine:
        # SLSQP: minimise Mahalanobis norm s.t. pnl_fn(f) >= loss_target
        L_inv = np.linalg.inv(L)

        def _obj(x: np.ndarray) -> float:
            # Mahalanobis norm^2 = x' Sigma^{-1} x = ||L^{-1} x||^2
            v = L_inv @ x
            return float(v @ v)

        def _obj_grad(x: np.ndarray) -> np.ndarray:
            # grad of ||L^{-1} x||^2 = 2 Sigma^{-1} x
            Sigma_inv = L_inv.T @ L_inv
            return np.asarray(2.0 * (Sigma_inv @ x), dtype=float)

        def _con(x: np.ndarray) -> float:
            sd = {factor_names[j]: float(x[j]) for j in range(n_f)}
            return pnl_fn(sd) - loss_target

        constraints = {"type": "ineq", "fun": _con}
        result = sp_opt.minimize(
            _obj,
            best_f,
            jac=_obj_grad,
            method="SLSQP",
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 500},
        )
        if result.success or result.fun < (_obj(best_f) + 1e-6):
            best_f = np.asarray(result.x, dtype=float)

    # Compute final Mahalanobis norm
    L_inv_final = np.linalg.inv(L)
    v = L_inv_final @ best_f
    mahal = float(math.sqrt(float(v @ v)))
    shock_dict_out = {factor_names[j]: float(best_f[j]) for j in range(n_f)}
    return shock_dict_out, mahal


# ---------------------------------------------------------------------------
# Stress report DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StressReport:
    """Assembled stress test report.

    Attributes
    ----------
    results:
        List of :class:`ScenarioResult` for each scenario run.
    worst_scenario:
        The scenario with the highest (worst) P&L loss.
    loss_limit:
        Configurable loss threshold (positive fraction of NAV).  Scenarios
        breaching this are flagged in ``breaches``.
    breaches:
        List of scenario names where ``pnl >= loss_limit``.
    generated_at:
        ISO timestamp string (UTC) when the report was built.
    """

    results: list[ScenarioResult]
    worst_scenario: ScenarioResult
    loss_limit: float
    breaches: list[str]
    generated_at: str


# ---------------------------------------------------------------------------
# build_stress_report
# ---------------------------------------------------------------------------


def build_stress_report(
    scenario_results: list[ScenarioResult],
    *,
    loss_limit: float = 0.10,
    generated_at: str | None = None,
) -> StressReport:
    """Assemble a :class:`StressReport` from a list of scenario results.

    Parameters
    ----------
    scenario_results:
        Ordered list of :class:`ScenarioResult` objects produced by
        :func:`apply_scenario` or :func:`hypothetical_shock`.
    loss_limit:
        Loss threshold as a positive fraction of NAV.  Scenarios with
        ``pnl >= loss_limit`` are flagged as breaches.  Default 0.10 (10%).
    generated_at:
        Optional ISO timestamp string (e.g. ``"2024-01-15T09:30:00Z"``).
        If ``None``, the current UTC time in ``YYYY-MM-DDTHH:MM:SSZ`` format
        is used via ``pd.Timestamp.utcnow()``.

    Returns
    -------
    StressReport

    Raises
    ------
    ValueError
        If ``scenario_results`` is empty, or ``loss_limit`` is not in (0, 1].
    """
    if not scenario_results:
        raise ValueError("scenario_results must not be empty.")
    if not (0.0 < loss_limit <= 1.0):
        raise ValueError(
            f"loss_limit must be in (0, 1]; got {loss_limit!r}"
        )
    if generated_at is None:
        ts = pd.Timestamp.utcnow()
        generated_at = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    worst = max(scenario_results, key=lambda r: r.pnl)
    breaches = [r.scenario_name for r in scenario_results if r.pnl >= loss_limit]

    return StressReport(
        results=scenario_results,
        worst_scenario=worst,
        loss_limit=loss_limit,
        breaches=breaches,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# render_stress_report_markdown -- ASCII markdown table
# ---------------------------------------------------------------------------


def render_stress_report_markdown(report: StressReport) -> str:
    """Render a :class:`StressReport` as an ASCII-only markdown table string.

    The output is suitable for embedding in a daily ops email or Slack
    message.  All characters are 7-bit ASCII -- no Unicode, no emoji.

    Layout::

        # Stress Test Report

        Generated: 2024-01-15T09:30:00Z
        Loss limit: 10.00%

        | Scenario                     | P&L (loss%)  | Method       | Breach |
        |------------------------------|--------------|--------------|--------|
        | GFC 2008 (Sep-Nov 2008)      |  +30.50%     | factor_beta  | YES    |
        ...

        Worst scenario: GFC 2008 (Sep-Nov 2008) (+30.50% loss)
        Breach count: 2 / 6

    Parameters
    ----------
    report:
        :class:`StressReport` to render.

    Returns
    -------
    str
        ASCII-only markdown string.
    """
    lines: list[str] = []
    lines.append("# Stress Test Report")
    lines.append("")
    lines.append(f"Generated: {report.generated_at}")
    lines.append(f"Loss limit: {report.loss_limit * 100.0:.2f}%")
    lines.append("")

    # Column headers and widths
    # Scenario name column: fit the longest name
    max_name = max(len(r.scenario_name) for r in report.results)
    max_name = max(max_name, len("Scenario"))
    # Fixed widths for other columns
    w_pnl = 14
    w_method = 14
    w_breach = 8

    def _sep(w: int) -> str:
        return "-" * w

    header = (
        f"| {'Scenario':<{max_name}} "
        f"| {'P&L (loss%)':<{w_pnl}} "
        f"| {'Method':<{w_method}} "
        f"| {'Breach':<{w_breach}} |"
    )
    divider = (
        f"|{_sep(max_name + 2)}"
        f"|{_sep(w_pnl + 2)}"
        f"|{_sep(w_method + 2)}"
        f"|{_sep(w_breach + 2)}|"
    )
    lines.append(header)
    lines.append(divider)

    for r in report.results:
        # P&L: positive loss is shown as positive percentage
        pnl_pct = r.pnl * 100.0
        sign = "+" if pnl_pct >= 0.0 else ""
        pnl_str = f"{sign}{pnl_pct:.2f}%"
        breach_str = "YES" if r.scenario_name in report.breaches else "no"
        row = (
            f"| {r.scenario_name:<{max_name}} "
            f"| {pnl_str:<{w_pnl}} "
            f"| {r.method:<{w_method}} "
            f"| {breach_str:<{w_breach}} |"
        )
        lines.append(row)

    lines.append("")
    worst = report.worst_scenario
    worst_pct = worst.pnl * 100.0
    sign = "+" if worst_pct >= 0.0 else ""
    lines.append(
        f"Worst scenario: {worst.scenario_name} "
        f"({sign}{worst_pct:.2f}% loss)"
    )
    n_breach = len(report.breaches)
    n_total = len(report.results)
    lines.append(f"Breach count: {n_breach} / {n_total}")
    lines.append("")

    return "\n".join(lines)
