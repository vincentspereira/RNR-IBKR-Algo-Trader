"""GARCH-based volatility forecasting for the risk layer (master plan Phase 7.6).

This module is the *risk-layer integration* on top of the Phase 5 signal
module ``core_trading.signals.volatility.garch``.  It orchestrates per-asset
multi-step vol forecasts for a returns panel, applies EWMA as a fallback when
GARCH is unreliable, and builds a forward-looking covariance matrix suitable
for parametric VaR (``core_trading.risk.var``) and portfolio optimisation
(``core_trading.portfolio``).

Design overview
---------------
1. **Per-asset GARCH forecasts** -- :func:`forecast_panel_vols` fits one
   GARCH model per column of the returns panel and returns per-step and
   cumulative-horizon forecast variances for each asset.

2. **EWMA fallback** -- When a column has fewer observations than the
   configurable ``min_obs_garch`` threshold, or when the GARCH fit raises
   an exception, the module falls back to RiskMetrics (1996) EWMA with
   ``lambda=0.94`` (daily default).  The fallback is never silent: the
   ``VolForecastResult.fallback_assets`` field records every asset that used
   EWMA.

3. **Forward-looking covariance** -- :func:`forecast_cov_matrix` combines
   forecast volatilities with a correlation matrix under the Constant
   Conditional Correlation (CCC) model (Bollerslev 1990):
       Cov(t+h) = D(t+h) * R * D(t+h)
   where ``D(t+h)`` is the diagonal matrix of forecast standard deviations
   and ``R`` is the (constant) correlation matrix.  The correlation source
   is either the sample correlation or a Ledoit-Wolf shrinkage estimate
   (reused from ``core_trading.portfolio.covariance``; no reimplementation).
   The Dynamic Conditional Correlation (DCC) extension is explicitly deferred
   to a later phase: see the DCC note below.

4. **PSD guarantee** -- The output covariance is projected onto the PSD cone
   via eigenvalue clipping (Higham 1988, reused from
   ``core_trading.portfolio.covariance.nearest_psd``) whenever the matrix is
   found to be non-PSD.  Clipping is recorded in ``CCCCovResult.psd_clipped``.

5. **Horizon aggregation** -- h-step cumulative variance is the sum of per-step
   forecast variances (not the naive ``h * sigma_1^2`` rule, which would only
   hold for iid returns).  Both the per-step array and the cumulative scalar
   are exposed on each :class:`AssetVolForecast`.

DCC deferral note
-----------------
The Dynamic Conditional Correlation model (Engle 2002) allows the
conditional correlation to evolve over time alongside the conditional
variances.  While theoretically preferable to CCC for realistic equity
returns, it requires a two-step estimation procedure (GARCH per asset, then
DCC on the standardised residuals), significantly more data, and additional
infrastructure (rolling correlation estimation, DCC parameter fitting).  This
is deferred to a later phase; CCC is documented here as the implemented model.

Model selection rationale: GJR-GARCH as asymmetric default
-----------------------------------------------------------
GJR-GARCH (Glosten, Jagannathan & Runkle 1993) is the recommended asymmetric
model for equity returns because it captures the *leverage effect*: negative
return shocks increase conditional volatility more than positive shocks of the
same magnitude (Black 1976).  Standard symmetric GARCH (Bollerslev 1986)
systematically underestimates volatility following drawdowns and
overestimates it following rallies, which biases VaR and optimisation inputs
precisely when accuracy matters most.  The GJR-GARCH gamma coefficient adds
a single parameter (the leverage term) with a clear economic interpretation
and minimal overfitting cost.  EGARCH (Nelson 1991) is another asymmetric
option but lacks a closed-form multi-step forecast for horizons > 1 (requiring
simulation), so GJR-GARCH is preferred here for tractability and speed.

EWMA fallback rationale
-----------------------
GARCH maximum-likelihood estimation requires enough data for the log-likelihood
surface to be well-identified; practitioners typically require at least 250-500
observations (one to two years of daily data).  Below this threshold the GARCH
parameter estimates are highly variable and the conditional variance can diverge
or hit numerical bounds.  RiskMetrics EWMA (lambda=0.94) is a simple, robust
one-parameter model that is always well-defined even for very short histories
and is analytically equivalent to an I-GARCH(1,1) without a constant term.

Mathematical references
-----------------------
GARCH(1,1) -- Bollerslev, T. (1986). "Generalized autoregressive conditional
    heteroskedasticity." Journal of Econometrics, 31, 307-327.
GJR-GARCH -- Glosten, L.R., Jagannathan, R. & Runkle, D.E. (1993). "On the
    relation between the expected value and the volatility of the nominal
    excess return on stocks." Journal of Finance, 48, 1779-1801.
CCC -- Bollerslev, T. (1990). "Modelling the coherence in short-run nominal
    exchange rates: a multivariate generalized ARCH model." Review of
    Economics and Statistics, 72, 498-505.
EWMA / RiskMetrics -- RiskMetrics Group (1996). "RiskMetrics -- Technical
    Document." 4th ed. J.P. Morgan/Reuters.
PSD projection -- Higham, N.J. (1988). "Computing a nearest symmetric positive
    semidefinite matrix." Linear Algebra and its Applications, 103, 103-118.
Ledoit-Wolf -- Ledoit, O. & Wolf, M. (2004a). "A well-conditioned estimator
    for large-dimensional covariance matrices." Journal of Multivariate
    Analysis, 88(2), 365-411.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from core_trading.portfolio.covariance import (
    ledoit_wolf_covariance,
    nearest_psd,
    sample_covariance,
)
from core_trading.signals.volatility.garch import (
    GARCHConfig,
    fit_garch,
    forecast_variance,
)

__all__ = [
    "VolForecastConfig",
    "AssetVolForecast",
    "VolForecastResult",
    "CCCCovResult",
    "forecast_panel_vols",
    "forecast_cov_matrix",
    "ewma_variance",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

CorrelationSource = Literal["sample", "ledoit_wolf"]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolForecastConfig:
    """Configuration for the risk-layer volatility forecaster.

    Attributes
    ----------
    model:
        GARCH-family model to use when observations are sufficient.
        ``"GJR-GARCH"`` (default) captures equity leverage effects.
        ``"GARCH"`` is symmetric.  ``"EGARCH"`` is asymmetric but uses
        simulation-based multi-step forecasts, which is slower.
    horizon:
        Number of steps ahead to forecast.  Must be >= 1.
    min_obs_garch:
        Minimum number of finite observations required before attempting
        a GARCH fit.  When a column has fewer observations the module falls
        back to EWMA.  Default 252 (one year of daily data).
    ewma_lambda:
        Decay factor for the EWMA fallback (RiskMetrics lambda).
        Must be in (0, 1).  Default 0.94 (daily RiskMetrics 1996).
    correlation_source:
        How to estimate the correlation matrix for CCC.
        ``"sample"`` uses the plain sample correlation.
        ``"ledoit_wolf"`` (default) uses Ledoit-Wolf shrinkage, which
        is better conditioned when N is not small relative to T.
    """

    model: Literal["GARCH", "EGARCH", "GJR-GARCH"] = "GJR-GARCH"
    horizon: int = 1
    min_obs_garch: int = 252
    ewma_lambda: float = 0.94
    correlation_source: CorrelationSource = "ledoit_wolf"

    def __post_init__(self) -> None:
        if self.model not in ("GARCH", "EGARCH", "GJR-GARCH"):
            raise ValueError(
                f"model must be 'GARCH', 'EGARCH', or 'GJR-GARCH'; got {self.model!r}"
            )
        if self.horizon < 1:
            raise ValueError(f"horizon must be >= 1; got {self.horizon}")
        if self.min_obs_garch < 2:
            raise ValueError(
                f"min_obs_garch must be >= 2; got {self.min_obs_garch}"
            )
        if not (0.0 < self.ewma_lambda < 1.0):
            raise ValueError(
                f"ewma_lambda must be in (0, 1); got {self.ewma_lambda}"
            )
        if self.correlation_source not in ("sample", "ledoit_wolf"):
            raise ValueError(
                f"correlation_source must be 'sample' or 'ledoit_wolf'; "
                f"got {self.correlation_source!r}"
            )


# ---------------------------------------------------------------------------
# Per-asset result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetVolForecast:
    """Volatility forecast for a single asset.

    All variance values are in the same scale as the input returns
    (i.e., if returns are in decimal form such as 0.01 for 1%,
    variances are in (decimal return)^2 and volatilities in decimal
    return units).

    Attributes
    ----------
    asset:
        Asset identifier (column name from the returns panel).
    method:
        Which estimator produced the forecast: ``"garch"`` or ``"ewma"``.
    model:
        GARCH model used (e.g. ``"GJR-GARCH"``), or ``"ewma"`` if the
        EWMA fallback was used.
    per_step_variances:
        Shape ``(horizon,)`` array of per-step conditional variance
        forecasts.  ``per_step_variances[k]`` is the k+1 step-ahead
        variance at the original returns scale.
    cumulative_variance:
        Sum of ``per_step_variances``, the h-step cumulative variance.
        Use this for horizon-scaled VaR inputs (not the naive h * sigma_1^2
        rule, which incorrectly assumes iid returns).
    forecast_vol:
        Square root of ``cumulative_variance``.  This is the h-step
        cumulative volatility in the original returns scale.
    one_step_variance:
        The 1-step-ahead conditional variance (``per_step_variances[0]``),
        the most commonly needed scalar for VaR computation.
    """

    asset: str
    method: Literal["garch", "ewma"]
    model: str
    per_step_variances: np.ndarray = field(compare=False)
    cumulative_variance: float
    forecast_vol: float
    one_step_variance: float


# ---------------------------------------------------------------------------
# Panel-level result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolForecastResult:
    """Result of per-asset volatility forecasting over a returns panel.

    Attributes
    ----------
    config:
        The configuration used to produce this result.
    forecasts:
        Dict mapping asset name to its :class:`AssetVolForecast`.
    fallback_assets:
        List of asset names for which EWMA was used (short history or
        failed GARCH fit).  Empty when every asset used GARCH.
    assets:
        Ordered list of asset names (same order as input panel columns).
    one_step_vol_series:
        pandas Series of 1-step-ahead conditional volatilities (standard
        deviations), indexed by asset name.  This is the per-asset
        ``sqrt(one_step_variance)`` vector in input-return units.
    """

    config: VolForecastConfig
    forecasts: dict[str, AssetVolForecast] = field(compare=False)
    fallback_assets: list[str]
    assets: list[str]
    one_step_vol_series: pd.Series = field(compare=False)


# ---------------------------------------------------------------------------
# CCC covariance result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CCCCovResult:
    """Result of a Constant Conditional Correlation covariance forecast.

    The covariance matrix is shaped to be directly consumable by Phase 6
    portfolio optimisers (same conventions as
    ``core_trading.portfolio.covariance.CovarianceResult``) and by the
    parametric VaR in ``core_trading.risk.var.parametric_var`` Mode B
    (``weights + cov``).

    Attributes
    ----------
    covariance:
        N x N symmetric PSD forecast covariance matrix as a
        ``pandas.DataFrame`` indexed and columned by asset names.
        Units: (return units)^2, same as the input panel.
    correlation:
        N x N correlation matrix used (before PSD projection if any).
    forecast_vols:
        :class:`VolForecastResult` used to build the diagonal D.
    horizon:
        Forecast horizon (number of steps).  The diagonal of ``covariance``
        is the h-step cumulative variance (sum of per-step variances).
    psd_clipped:
        ``True`` if the assembled CCC matrix was non-PSD and required
        eigenvalue clipping.  Recorded for transparency.
    correlation_source:
        Which estimator was used for the correlation matrix.
    """

    covariance: pd.DataFrame = field(compare=False)
    correlation: pd.DataFrame = field(compare=False)
    forecast_vols: VolForecastResult
    horizon: int
    psd_clipped: bool
    correlation_source: str


# ---------------------------------------------------------------------------
# EWMA helper
# ---------------------------------------------------------------------------


def ewma_variance(
    returns: pd.Series | np.ndarray,
    *,
    lam: float = 0.94,
    horizon: int = 1,
) -> np.ndarray:
    """Compute RiskMetrics (1996) EWMA conditional variance forecast.

    The EWMA recursion is:
        sigma^2_t = lambda * sigma^2_{t-1} + (1 - lambda) * r_{t-1}^2

    The 1-step-ahead forecast is the current (last) conditional variance.
    For multi-step forecasts EWMA (which is I-GARCH without a constant)
    gives a flat forecast: the unconditional variance is undefined (or
    infinite), so each step-ahead forecast equals the last conditional
    variance.  The h-step cumulative variance is therefore:
        Cumvar_h = h * sigma^2_t

    This is a conservative, flat extrapolation.  It is strictly less
    sophisticated than GARCH but robust and well-defined for any sample size.

    Parameters
    ----------
    returns:
        1-D return series (decimal or percentage scale).  Must have at
        least 2 finite observations.
    lam:
        Exponential decay factor (RiskMetrics lambda).  Default 0.94.
    horizon:
        Number of steps ahead.  Must be >= 1.

    Returns
    -------
    np.ndarray
        Shape ``(horizon,)`` array of per-step conditional variances.  For
        EWMA every entry is the same value (flat forecast).

    Raises
    ------
    ValueError
        If ``returns`` has fewer than 2 finite observations, or if ``lam``
        is not in (0, 1), or if ``horizon < 1``.
    """
    if not (0.0 < lam < 1.0):
        raise ValueError(f"lam must be in (0, 1); got {lam}")
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1; got {horizon}")

    arr = np.asarray(returns, dtype=float).ravel()
    finite_arr = arr[np.isfinite(arr)]
    if finite_arr.size < 2:
        raise ValueError(
            f"ewma_variance requires at least 2 finite observations; got {finite_arr.size}"
        )

    # Initialise with sample variance of the first observation.
    sigma2 = float(np.var(finite_arr, ddof=1))
    one_minus_lam = 1.0 - lam
    for r in finite_arr:
        sigma2 = lam * sigma2 + one_minus_lam * float(r * r)

    # Flat forecast: every step-ahead variance equals the last conditional variance.
    result: np.ndarray = np.full(horizon, sigma2, dtype=float)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _forecast_one_asset(
    series: pd.Series,
    config: VolForecastConfig,
    asset: str,
) -> AssetVolForecast:
    """Produce a vol forecast for a single asset series.

    Attempts GARCH if the series has >= ``config.min_obs_garch`` finite
    observations; otherwise falls back to EWMA.  Any exception raised by
    the GARCH fit also triggers EWMA fallback.

    Parameters
    ----------
    series:
        Return series for the asset (may contain NaN; NaN rows are dropped
        before the fit).
    config:
        Forecasting configuration.
    asset:
        Asset identifier for the result.

    Returns
    -------
    AssetVolForecast
    """
    arr = series.dropna().to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    n_obs = arr.size

    method: Literal["garch", "ewma"]
    model_str: str
    per_step_vars: np.ndarray

    use_garch = n_obs >= config.min_obs_garch

    if use_garch:
        try:
            garch_cfg = GARCHConfig(model=config.model, p=1, q=1)
            garch_result = fit_garch(arr, config=garch_cfg)
            per_step_vars = forecast_variance(garch_result, horizon=config.horizon)
            method = "garch"
            model_str = config.model
        except Exception:
            use_garch = False

    if not use_garch:
        per_step_vars = ewma_variance(arr, lam=config.ewma_lambda, horizon=config.horizon)
        method = "ewma"
        model_str = "ewma"

    cumulative_var = float(np.sum(per_step_vars))
    forecast_vol_val = float(np.sqrt(max(cumulative_var, 0.0)))
    one_step_var = float(per_step_vars[0])

    return AssetVolForecast(
        asset=asset,
        method=method,
        model=model_str,
        per_step_variances=per_step_vars,
        cumulative_variance=cumulative_var,
        forecast_vol=forecast_vol_val,
        one_step_variance=one_step_var,
    )


# ---------------------------------------------------------------------------
# Public API: per-asset panel forecasting
# ---------------------------------------------------------------------------


def forecast_panel_vols(
    returns: pd.DataFrame,
    *,
    config: VolForecastConfig | None = None,
) -> VolForecastResult:
    """Forecast conditional volatility for every asset in a returns panel.

    Fits one GARCH-family model (or EWMA fallback) per column and returns
    per-step and cumulative-horizon variance forecasts for each asset.

    Parameters
    ----------
    returns:
        Returns panel.  Rows are time periods, columns are assets.  The
        panel may contain NaN (e.g. from different listing dates); NaN
        rows are dropped per-column before fitting.  Must have at least 2
        columns and at least 2 finite observations per column.
    config:
        :class:`VolForecastConfig` controlling model choice, horizon,
        EWMA parameters, and fallback threshold.  Defaults to
        ``VolForecastConfig()`` (GJR-GARCH, horizon=1, min_obs=252).

    Returns
    -------
    VolForecastResult
        Per-asset forecasts together with a ``fallback_assets`` list and
        a convenience ``one_step_vol_series`` Series.

    Raises
    ------
    ValueError
        If the panel has fewer than 1 column.
    """
    cfg = config if config is not None else VolForecastConfig()

    if returns.shape[1] < 1:
        raise ValueError(
            "returns panel must have at least 1 asset column; "
            f"got {returns.shape[1]}."
        )

    assets = list(returns.columns)
    forecasts: dict[str, AssetVolForecast] = {}
    fallback_assets: list[str] = []

    for asset in assets:
        af = _forecast_one_asset(returns[asset], cfg, str(asset))
        forecasts[asset] = af
        if af.method == "ewma":
            fallback_assets.append(asset)

    one_step_vols = pd.Series(
        {a: float(np.sqrt(max(forecasts[a].one_step_variance, 0.0))) for a in assets},
        name="one_step_vol",
    )

    return VolForecastResult(
        config=cfg,
        forecasts=forecasts,
        fallback_assets=fallback_assets,
        assets=assets,
        one_step_vol_series=one_step_vols,
    )


# ---------------------------------------------------------------------------
# Public API: CCC covariance
# ---------------------------------------------------------------------------


def forecast_cov_matrix(
    returns: pd.DataFrame,
    *,
    config: VolForecastConfig | None = None,
    vol_result: VolForecastResult | None = None,
) -> CCCCovResult:
    """Build a forward-looking CCC covariance matrix from GARCH vol forecasts.

    Implements the Constant Conditional Correlation (CCC) model
    (Bollerslev 1990):
        Cov(t+h) = D(t+h) * R * D(t+h)
    where ``D(t+h)`` is the diagonal matrix of h-step cumulative forecast
    standard deviations and ``R`` is the (constant) correlation matrix
    estimated from the historical returns panel.

    The output covariance matrix is in the same units and shape convention
    as ``core_trading.portfolio.covariance.CovarianceResult.covariance`` and
    is directly consumable by Phase 6 optimisers and by
    ``core_trading.risk.var.parametric_var`` Mode B.

    Parameters
    ----------
    returns:
        Historical returns panel (rows = time, columns = assets).  Must be
        NaN-free; align and fill upstream.  Must have at least 2 columns
        and at least 2 observation rows.
    config:
        :class:`VolForecastConfig`.  If ``None`` a default config is used.
        The ``correlation_source`` field controls whether the correlation
        matrix is estimated via sample or Ledoit-Wolf shrinkage.
    vol_result:
        Pre-computed :class:`VolForecastResult`.  Pass this to avoid
        redundant GARCH fits when you already have the per-asset forecasts.
        When ``None``, :func:`forecast_panel_vols` is called internally.

    Returns
    -------
    CCCCovResult
        Forecast covariance matrix (PSD guaranteed) together with the
        correlation matrix and diagnostic metadata.

    Raises
    ------
    ValueError
        If the panel is NaN-contaminated or has fewer than 2 columns or rows.
    """
    cfg = config if config is not None else VolForecastConfig()

    # Validate returns are NaN-free (required by the correlation estimators).
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; "
            "align and fill or drop missing data before building the covariance."
        )
    if returns.shape[1] < 2:
        raise ValueError(
            f"returns panel must have at least 2 asset columns; got {returns.shape[1]}."
        )
    if returns.shape[0] < 2:
        raise ValueError(
            f"returns panel must have at least 2 observation rows; got {returns.shape[0]}."
        )

    # Compute or reuse per-asset volatility forecasts.
    vol_res = forecast_panel_vols(returns, config=cfg) if vol_result is None else vol_result

    assets = list(returns.columns)

    # Build the diagonal of forecast standard deviations (h-step cumulative vol).
    d_vols = np.array(
        [vol_res.forecasts[str(a)].forecast_vol for a in assets],
        dtype=float,
    )

    # Estimate the correlation matrix.
    if cfg.correlation_source == "ledoit_wolf":
        lw_result = ledoit_wolf_covariance(returns)
        raw_cov = lw_result.covariance.to_numpy(dtype=float)
        # Convert shrunk covariance to a correlation matrix.
        diag_std = np.sqrt(np.maximum(np.diag(raw_cov), 1e-30))
        corr_matrix = raw_cov / np.outer(diag_std, diag_std)
        np.fill_diagonal(corr_matrix, 1.0)
    else:
        sample_result = sample_covariance(returns)
        raw_cov = sample_result.covariance.to_numpy(dtype=float)
        diag_std = np.sqrt(np.maximum(np.diag(raw_cov), 1e-30))
        corr_matrix = raw_cov / np.outer(diag_std, diag_std)
        np.fill_diagonal(corr_matrix, 1.0)

    # CCC: Cov = D * R * D.
    ccc_cov = np.outer(d_vols, d_vols) * corr_matrix

    # Symmetrise against float noise.
    ccc_cov = (ccc_cov + ccc_cov.T) / 2.0

    # PSD guarantee: check eigenvalues and clip if needed.
    eigenvalues = np.linalg.eigvalsh(ccc_cov)
    psd_clipped = bool(eigenvalues[0] < 0.0)
    if psd_clipped:
        ccc_cov = nearest_psd(ccc_cov, epsilon=0.0)

    cov_df = pd.DataFrame(ccc_cov, index=assets, columns=assets)
    corr_df = pd.DataFrame(corr_matrix, index=assets, columns=assets)

    return CCCCovResult(
        covariance=cov_df,
        correlation=corr_df,
        forecast_vols=vol_res,
        horizon=cfg.horizon,
        psd_clipped=psd_clipped,
        correlation_source=cfg.correlation_source,
    )
