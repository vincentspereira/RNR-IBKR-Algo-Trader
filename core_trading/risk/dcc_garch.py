"""Dynamic Conditional Correlation GARCH (Engle 2002) for the risk layer.

This module implements the two-stage Dynamic Conditional Correlation (DCC)
model of Engle (2002).  It is the deferred upgrade path named in the
``core_trading.risk.vol_forecast`` DCC deferral note (replacing the Constant
Conditional Correlation / CCC forward covariance with a *time-varying*
correlation) and in ``core_trading.risk.correlation_regime`` (supplying a
model-based correlation path for regime timing rather than a rolling-window
estimate).

Model
-----
DCC decomposes the conditional covariance ``H_t`` of an N-asset return vector
into a diagonal volatility part and a time-varying correlation part::

    H_t = D_t R_t D_t

where ``D_t = diag(sigma_{1,t}, ..., sigma_{N,t})`` holds the per-asset
conditional standard deviations and ``R_t`` is the conditional correlation
matrix.  Estimation is in two stages (Engle 2002; Engle & Sheppard 2001):

**Stage 1 (univariate GARCH).**  Fit a univariate GARCH(1,1) per asset on its
return column, extract the conditional sigma path, and form standardized
residuals ``eps_t = r_t / sigma_t``.  Each ``eps`` series is (asymptotically)
unit-variance.

**Stage 2 (DCC recursion).**  Drive a quasi-correlation matrix ``Q_t`` with the
scalar-DCC(1,1) recursion on the standardized residuals::

    Q_t = (1 - a - b) * Q_bar + a * (eps_{t-1} eps_{t-1}') + b * Q_{t-1}
    R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}

with ``Q_bar`` the sample covariance of the standardized residuals (the
"correlation targeting" intercept), and constraints ``a >= 0``, ``b >= 0``,
``a + b < 1`` for covariance stationarity.  The pair ``(a, b)`` is estimated by
maximising the second-stage Gaussian quasi log-likelihood

    L_c = -1/2 * sum_t [ log|R_t| + eps_t' R_t^{-1} eps_t - eps_t' eps_t ]

via ``scipy.optimize.minimize`` (SLSQP with the linear inequality
``a + b <= 1 - eps_stat`` and box bounds).  The recursion is initialised at
``Q_0 = Q_bar`` and started from the deterministic, documented values
``a0 = 0.02``, ``b0 = 0.97`` (a common empirical regime: low news impact, high
persistence; see Engle 2002 Table 2).

Integration choice: reuse vs direct ``arch``
--------------------------------------------
Stage 1 *reuses* ``core_trading.signals.volatility.garch.fit_garch`` -- the
same univariate entry point that ``core_trading.risk.vol_forecast`` builds on --
rather than calling ``arch`` directly.  ``fit_garch`` already handles the
percentage-return rescaling that suppresses ``arch``'s ``DataScaleWarning`` and
returns a ``conditional_volatility`` Series in the original return scale.  The
standardized residuals required by DCC are then simply ``r_t / sigma_t``, which
this module derives from that Series; no GARCH internals are reimplemented and
no second rescaling convention is introduced.  This keeps the univariate
machinery single-sourced with vol_forecast, which is the stated design goal.

``arch`` *can* emit ``ConvergenceWarning`` when the inner optimiser stops on a
loose gradient.  Because the quality bar runs under ``-W error``, that warning
is caught and filtered **inside** :func:`_fit_univariate` only (a narrow,
documented scope) and surfaced via the per-asset ``converged`` flags on
:class:`DCCResult` rather than blanket-suppressed; the DataScaleWarning is
already neutralised by ``fit_garch``'s rescaling.

NaN policy
----------
The returns panel must be NaN-free after alignment (raise otherwise).  DCC is a
*joint* model: a missing observation for one asset on a given date invalidates
the cross-product ``eps_t eps_t'`` for that date for every asset, so silent
per-column dropping (as the univariate vol_forecast does) is not sound here.
Callers must align and fill upstream; constant (zero-variance) columns are
rejected because their standardized residuals are undefined.

Forecasting
-----------
The h-step correlation forecast uses the standard DCC mean-reversion recursion
(Engle 2002, Sec. 2.3; Engle & Sheppard 2001, eq. 24).  With ``Q_bar_star`` the
correlation-scaled long-run target (``diag(Q_bar)^{-1/2} Q_bar
diag(Q_bar)^{-1/2}``) and one-step quasi-correlation ``Q_{t+1}``::

    E[Q_{t+h}] = (1 - (a+b)^{h-1}) * Q_bar_star + (a+b)^{h-1} * Q_{t+1},  h >= 1

(the ``h = 1`` case returns ``R`` implied by ``Q_{t+1}`` exactly).  The forecast
correlation is the diagonal-rescaled ``E[Q_{t+h}]``.  This is an approximation
because ``E[R_{t+h}] != correlation(E[Q_{t+h}])`` in general, but it is the
convention used throughout the DCC literature for tractable multi-step
correlation forecasts.

Forward covariance (drop-in for vol_forecast's CCC)
---------------------------------------------------
:func:`dcc_forward_covariance` combines the DCC h-step correlation forecast with
*externally supplied* per-asset volatility forecasts (e.g. the
``one_step_vol_series`` or h-step ``forecast_vol`` from
``core_trading.risk.vol_forecast``) into a forward covariance
``Cov = D_fcst R_fcst D_fcst``.  It is PSD-guaranteed by eigenvalue clipping
(Higham 1988) reusing ``core_trading.portfolio.covariance.nearest_psd`` with the
same ``epsilon = 0.0`` tolerance and the same "check eigenvalues, clip only if
the smallest is negative" pattern as ``vol_forecast.forecast_cov_matrix``.  This
function is the documented drop-in upgrade for the CCC covariance produced by
``vol_forecast.forecast_cov_matrix``: same units, same shape conventions, same
PSD contract, but with a time-/horizon-varying correlation instead of a
constant one.

Mathematical references
-----------------------
Engle, R. (2002). "Dynamic Conditional Correlation: A Simple Class of
    Multivariate Generalized Autoregressive Conditional Heteroskedasticity
    Models." Journal of Business & Economic Statistics, 20(3), 339-350.
Engle, R. & Sheppard, K. (2001). "Theoretical and Empirical Properties of
    Dynamic Conditional Correlation Multivariate GARCH." NBER Working Paper
    8554.
Bollerslev, T. (1986). "Generalized autoregressive conditional
    heteroskedasticity." Journal of Econometrics, 31, 307-327.
Higham, N.J. (1988). "Computing a nearest symmetric positive semidefinite
    matrix." Linear Algebra and its Applications, 103, 103-118.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core_trading.portfolio.covariance import nearest_psd
from core_trading.signals.volatility.garch import GARCHConfig, fit_garch

__all__ = [
    "DCCConfig",
    "DCCResult",
    "fit_dcc",
    "dcc_forecast_correlation",
    "dcc_forward_covariance",
    "dcc_correlation_series",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DCCConfig:
    """Configuration for the two-stage DCC-GARCH estimator.

    Attributes
    ----------
    univariate_model:
        GARCH-family model fitted per asset in stage 1.  One of ``"GARCH"``,
        ``"EGARCH"``, ``"GJR-GARCH"``.  Default ``"GARCH"`` (the symmetric
        Engle 2002 baseline); ``"GJR-GARCH"`` adds the equity leverage term.
    horizon:
        Default forecast horizon (number of steps).  Must be >= 1.  May be
        overridden per call on the forecast functions.
    min_observations:
        Minimum number of (NaN-free) observation rows required to fit the
        model.  DCC needs enough data both for stable univariate GARCH fits
        and for a well-conditioned ``Q_bar``.  Default 250.
    a0:
        Deterministic starting value for the DCC news coefficient ``a`` in the
        stage-2 optimisation.  Default 0.02.
    b0:
        Deterministic starting value for the DCC persistence coefficient
        ``b``.  Default 0.97.
    stationarity_eps:
        Strict-stationarity margin: the optimiser enforces
        ``a + b <= 1 - stationarity_eps``.  Must be in (0, 1).  Default 1e-4.
    optimizer:
        ``scipy.optimize.minimize`` method for stage 2.  ``"SLSQP"`` (default)
        supports the ``a + b`` inequality constraint directly; ``"L-BFGS-B"``
        is also accepted (the sum constraint is then enforced only via the
        box bounds and a penalty barrier in the objective).
    max_iter:
        Maximum optimiser iterations.  Default 200.
    """

    univariate_model: str = "GARCH"
    horizon: int = 1
    min_observations: int = 250
    a0: float = 0.02
    b0: float = 0.97
    stationarity_eps: float = 1e-4
    optimizer: str = "SLSQP"
    max_iter: int = 200

    def __post_init__(self) -> None:
        if self.univariate_model not in ("GARCH", "EGARCH", "GJR-GARCH"):
            raise ValueError(
                "univariate_model must be 'GARCH', 'EGARCH', or 'GJR-GARCH'; "
                f"got {self.univariate_model!r}"
            )
        if self.horizon < 1:
            raise ValueError(f"horizon must be >= 1; got {self.horizon}")
        if self.min_observations < 2:
            raise ValueError(
                f"min_observations must be >= 2; got {self.min_observations}"
            )
        if self.a0 < 0.0:
            raise ValueError(f"a0 must be >= 0; got {self.a0}")
        if self.b0 < 0.0:
            raise ValueError(f"b0 must be >= 0; got {self.b0}")
        if not (0.0 < self.a0 + self.b0 < 1.0):
            raise ValueError(
                f"a0 + b0 must lie in (0, 1); got {self.a0 + self.b0}"
            )
        if not (0.0 < self.stationarity_eps < 1.0):
            raise ValueError(
                f"stationarity_eps must be in (0, 1); got {self.stationarity_eps}"
            )
        if self.optimizer not in ("SLSQP", "L-BFGS-B"):
            raise ValueError(
                f"optimizer must be 'SLSQP' or 'L-BFGS-B'; got {self.optimizer!r}"
            )
        if self.max_iter < 1:
            raise ValueError(f"max_iter must be >= 1; got {self.max_iter}")


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DCCResult:
    """Result of a two-stage DCC-GARCH fit.

    Attributes
    ----------
    config:
        The :class:`DCCConfig` used to produce this result.
    assets:
        Ordered list of asset names (matching the input panel column order).
    a:
        Fitted DCC news coefficient ``a`` (>= 0).
    b:
        Fitted DCC persistence coefficient ``b`` (>= 0, with ``a + b < 1``).
    q_bar:
        N x N sample covariance of the standardized residuals (the
        correlation-targeting intercept ``Q_bar``).
    sigmas:
        T x N array of per-asset conditional standard deviations from stage 1,
        in the original return scale.  Row ``t`` aligns with input row ``t``.
    std_resid:
        T x N array of standardized residuals ``eps_t = r_t / sigma_t``.
    garch_params:
        Dict mapping asset name to the stage-1 univariate GARCH parameter dict
        (as returned by :func:`core_trading.signals.volatility.garch.fit_garch`).
    garch_converged:
        Dict mapping asset name to the stage-1 convergence flag (``True`` when
        the univariate fit completed without an ``arch`` ConvergenceWarning).
    correlations:
        ``(T, N, N)`` array holding the full conditional correlation path
        ``R_t``.  ``correlations[t]`` is a valid correlation matrix.
    q_path:
        ``(T, N, N)`` array of the quasi-correlation matrices ``Q_t`` (used to
        seed multi-step forecasts via ``q_path[-1]`` -> ``Q_{t+1}``).
    loglikelihood:
        Stage-2 Gaussian quasi log-likelihood at the optimum.
    converged:
        ``True`` when the stage-2 optimiser reported success and every stage-1
        univariate fit converged.
    n_obs:
        Number of observation rows used.
    """

    config: DCCConfig
    assets: list[str]
    a: float
    b: float
    q_bar: np.ndarray = field(compare=False)
    sigmas: np.ndarray = field(compare=False)
    std_resid: np.ndarray = field(compare=False)
    garch_params: dict[str, dict[str, float | list[float]]] = field(compare=False)
    garch_converged: dict[str, bool] = field(compare=False)
    correlations: np.ndarray = field(compare=False)
    q_path: np.ndarray = field(compare=False)
    loglikelihood: float
    converged: bool
    n_obs: int

    @property
    def n_assets(self) -> int:
        """Number of assets N in the panel."""
        return len(self.assets)

    def correlation_at(self, t: int) -> np.ndarray:
        """Return the ``N x N`` conditional correlation matrix ``R_t`` at row ``t``.

        Parameters
        ----------
        t:
            Row index into the correlation path.  Negative indices are
            supported (``-1`` is the last in-sample correlation).

        Returns
        -------
        numpy.ndarray
            A copy of the correlation matrix at time ``t``.
        """
        return np.array(self.correlations[t], dtype=float)


# ---------------------------------------------------------------------------
# Stage 1 -- univariate GARCH (reusing the signals-layer fit_garch)
# ---------------------------------------------------------------------------


def _fit_univariate(
    returns_col: np.ndarray,
    config: DCCConfig,
) -> tuple[np.ndarray, dict[str, float | list[float]], bool]:
    """Fit one univariate GARCH and return (sigmas, params, converged).

    Reuses :func:`core_trading.signals.volatility.garch.fit_garch` so the
    percentage-return rescaling (DataScaleWarning suppression) and the
    return-scale conditional volatility convention are single-sourced with
    ``core_trading.risk.vol_forecast``.

    ``arch``'s ``ConvergenceWarning`` is caught and recorded here (narrow,
    documented scope) so the module is safe under ``-W error``; the warning is
    surfaced as ``converged=False`` rather than suppressed globally.

    Parameters
    ----------
    returns_col:
        1-D return series for one asset (NaN-free, decimal scale).
    config:
        DCC configuration (the univariate model choice is read from it).

    Returns
    -------
    sigmas:
        1-D conditional standard deviation path (original return scale).
    params:
        The univariate GARCH parameter dict.
    converged:
        ``True`` when no ConvergenceWarning was raised by the inner fit.
    """
    from arch.utility.exceptions import ConvergenceWarning

    garch_cfg = GARCHConfig(model=config.univariate_model, p=1, q=1)  # type: ignore[arg-type]
    converged = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fit_garch(returns_col, config=garch_cfg)
        for w in caught:
            if issubclass(w.category, ConvergenceWarning):
                converged = False

    sigmas = result.conditional_volatility.to_numpy(dtype=float)
    return sigmas, result.params, converged


# ---------------------------------------------------------------------------
# Stage 2 -- DCC recursion and quasi-likelihood
# ---------------------------------------------------------------------------


def _correlation_from_q(q_mat: np.ndarray) -> np.ndarray:
    """Rescale a quasi-correlation matrix ``Q`` to a correlation matrix ``R``.

    ``R = diag(Q)^{-1/2} Q diag(Q)^{-1/2}``, with the diagonal forced to unity
    and off-diagonals symmetrised against float noise.
    """
    inv_sqrt = 1.0 / np.sqrt(np.maximum(np.diag(q_mat), 1e-300))
    r_mat = q_mat * np.outer(inv_sqrt, inv_sqrt)
    r_mat = (r_mat + r_mat.T) / 2.0
    np.fill_diagonal(r_mat, 1.0)
    out: np.ndarray = r_mat
    return out


def _dcc_recursion(
    eps: np.ndarray,
    q_bar: np.ndarray,
    a: float,
    b: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the scalar-DCC(1,1) recursion over the standardized residuals.

    Parameters
    ----------
    eps:
        ``T x N`` standardized residuals.
    q_bar:
        ``N x N`` correlation-targeting intercept (sample covariance of eps).
    a, b:
        DCC coefficients.

    Returns
    -------
    q_path:
        ``(T, N, N)`` quasi-correlation matrices ``Q_t``.
    r_path:
        ``(T, N, N)`` conditional correlation matrices ``R_t``.
    """
    n_obs, n_assets = eps.shape
    q_path = np.empty((n_obs, n_assets, n_assets), dtype=float)
    r_path = np.empty((n_obs, n_assets, n_assets), dtype=float)
    omega = (1.0 - a - b) * q_bar

    q_prev = q_bar.copy()
    for t in range(n_obs):
        if t == 0:
            q_t = q_bar.copy()
        else:
            e_prev = eps[t - 1]
            q_t = omega + a * np.outer(e_prev, e_prev) + b * q_prev
        q_path[t] = q_t
        r_path[t] = _correlation_from_q(q_t)
        q_prev = q_t

    return q_path, r_path


def _dcc_negloglik(
    params: np.ndarray,
    eps: np.ndarray,
    q_bar: np.ndarray,
    stationarity_eps: float,
) -> float:
    """Stage-2 negative Gaussian quasi log-likelihood for the DCC recursion.

    L_c = -1/2 sum_t [ log|R_t| + eps_t' R_t^{-1} eps_t - eps_t' eps_t ].

    A large finite penalty is returned when the parameters violate the
    stationarity region (so ``L-BFGS-B`` without an explicit constraint still
    avoids the non-stationary boundary).
    """
    a = float(params[0])
    b = float(params[1])
    if a < 0.0 or b < 0.0 or (a + b) > (1.0 - stationarity_eps):
        return 1e12

    n_obs = eps.shape[0]
    omega = (1.0 - a - b) * q_bar
    q_prev = q_bar.copy()
    total = 0.0
    for t in range(n_obs):
        if t == 0:
            q_t = q_bar.copy()
        else:
            e_prev = eps[t - 1]
            q_t = omega + a * np.outer(e_prev, e_prev) + b * q_prev
        r_t = _correlation_from_q(q_t)
        e_t = eps[t]
        sign, logdet = np.linalg.slogdet(r_t)
        if sign <= 0.0 or not np.isfinite(logdet):
            return 1e12
        try:
            solved = np.linalg.solve(r_t, e_t)
        except np.linalg.LinAlgError:
            return 1e12
        quad = float(e_t @ solved)
        total += logdet + quad - float(e_t @ e_t)
        q_prev = q_t

    return 0.5 * total


# ---------------------------------------------------------------------------
# Public API -- fit
# ---------------------------------------------------------------------------


def _validate_panel(returns: pd.DataFrame, config: DCCConfig) -> None:
    """Validate the returns panel for a DCC fit (shape, NaN, constant columns)."""
    if returns.shape[1] < 2:
        raise ValueError(
            f"DCC requires at least 2 asset columns; got {returns.shape[1]}."
        )
    if returns.shape[0] < config.min_observations:
        raise ValueError(
            f"DCC requires at least min_observations={config.min_observations} "
            f"rows; got {returns.shape[0]}."
        )
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; DCC is a joint model and "
            "requires an aligned, NaN-free panel (align and fill upstream)."
        )
    stds = returns.std(axis=0, ddof=1).to_numpy(dtype=float)
    if np.any(stds <= 1e-15):
        bad = [
            str(c)
            for c, s in zip(returns.columns, stds, strict=True)
            if s <= 1e-15
        ]
        raise ValueError(
            f"returns panel has constant (zero-variance) column(s): {bad}; "
            "standardized residuals are undefined."
        )


def fit_dcc(returns: pd.DataFrame, *, config: DCCConfig | None = None) -> DCCResult:
    """Fit a two-stage DCC-GARCH model (Engle 2002) to a returns panel.

    Stage 1 fits a univariate GARCH(1,1) per asset (reusing
    :func:`core_trading.signals.volatility.garch.fit_garch`) and forms
    standardized residuals.  Stage 2 estimates the scalar-DCC coefficients
    ``(a, b)`` by maximising the second-stage Gaussian quasi-likelihood on the
    standardized residuals via ``scipy.optimize.minimize`` from the
    deterministic start ``(config.a0, config.b0)``.

    Parameters
    ----------
    returns:
        Returns panel; rows are time periods, columns are assets.  Must be
        NaN-free (DCC is a joint model -- see the module NaN policy), have at
        least 2 columns and at least ``config.min_observations`` rows, and have
        no constant columns.  Returns are decimal fractions.
    config:
        :class:`DCCConfig`.  Defaults to ``DCCConfig()`` (symmetric GARCH(1,1)
        margins, horizon 1, min_observations 250).

    Returns
    -------
    DCCResult
        Fitted coefficients, ``Q_bar``, per-asset sigmas / params / convergence
        flags, the full ``R_t`` and ``Q_t`` paths, the stage-2 log-likelihood,
        and an overall convergence flag.

    Raises
    ------
    ValueError
        If the panel fails validation (too few columns/rows, NaN, constant
        column).
    """
    cfg = config if config is not None else DCCConfig()
    _validate_panel(returns, cfg)

    assets = [str(c) for c in returns.columns]
    ret_arr = returns.to_numpy(dtype=float)
    n_obs, n_assets = ret_arr.shape

    # ---- Stage 1: univariate GARCH per asset -> sigmas + standardized resid.
    sigmas = np.empty((n_obs, n_assets), dtype=float)
    garch_params: dict[str, dict[str, float | list[float]]] = {}
    garch_converged: dict[str, bool] = {}
    for j, asset in enumerate(assets):
        sig_j, params_j, conv_j = _fit_univariate(ret_arr[:, j], cfg)
        sigmas[:, j] = sig_j
        garch_params[asset] = params_j
        garch_converged[asset] = conv_j

    std_resid = ret_arr / sigmas

    # ---- Q_bar: sample covariance of standardized residuals (targeting).
    q_bar = np.cov(std_resid, rowvar=False, ddof=1)
    q_bar = np.atleast_2d(q_bar)
    q_bar = (q_bar + q_bar.T) / 2.0

    # ---- Stage 2: estimate (a, b) by quasi-MLE.
    x0 = np.array([cfg.a0, cfg.b0], dtype=float)
    bounds = [(0.0, 1.0 - cfg.stationarity_eps), (0.0, 1.0 - cfg.stationarity_eps)]

    if cfg.optimizer == "SLSQP":
        constraints = [
            {
                "type": "ineq",
                "fun": lambda p: (1.0 - cfg.stationarity_eps) - p[0] - p[1],
            }
        ]
        opt_res = minimize(
            _dcc_negloglik,
            x0,
            args=(std_resid, q_bar, cfg.stationarity_eps),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": cfg.max_iter, "ftol": 1e-9},
        )
    else:  # L-BFGS-B (sum constraint via penalty in the objective).
        opt_res = minimize(
            _dcc_negloglik,
            x0,
            args=(std_resid, q_bar, cfg.stationarity_eps),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": cfg.max_iter, "ftol": 1e-12},
        )

    a_hat = float(opt_res.x[0])
    b_hat = float(opt_res.x[1])
    loglik = -float(opt_res.fun)

    # ---- Reconstruct the full R_t / Q_t paths at the optimum.
    q_path, r_path = _dcc_recursion(std_resid, q_bar, a_hat, b_hat)

    converged = bool(opt_res.success) and all(garch_converged.values())

    return DCCResult(
        config=cfg,
        assets=assets,
        a=a_hat,
        b=b_hat,
        q_bar=q_bar,
        sigmas=sigmas,
        std_resid=std_resid,
        garch_params=garch_params,
        garch_converged=garch_converged,
        correlations=r_path,
        q_path=q_path,
        loglikelihood=loglik,
        converged=converged,
        n_obs=n_obs,
    )


# ---------------------------------------------------------------------------
# Public API -- forecasting
# ---------------------------------------------------------------------------


def dcc_forecast_correlation(result: DCCResult, *, horizon: int | None = None) -> np.ndarray:
    """Forecast the h-step-ahead conditional correlation matrix ``R_{t+h}``.

    Uses the standard DCC mean-reversion recursion (Engle 2002, Sec. 2.3;
    Engle & Sheppard 2001, eq. 24).  Let ``rho = a + b`` and ``Q_bar_star`` be
    the correlation-scaled long-run target.  The one-step quasi-correlation is

        Q_{t+1} = (1 - a - b) Q_bar + a eps_t eps_t' + b Q_t

    and for ``h >= 1``

        E[Q_{t+h}] = (1 - rho^{h-1}) Q_bar_star + rho^{h-1} Q_{t+1}.

    The returned correlation is the diagonal-rescaling of ``E[Q_{t+h}]``.  For
    ``h = 1`` this is exactly the correlation implied by ``Q_{t+1}``.  As
    ``h -> infinity`` it mean-reverts to ``Q_bar_star`` (the long-run
    correlation).  The approximation
    ``E[R_{t+h}] ~ correlation(E[Q_{t+h}])`` is the standard tractable DCC
    multi-step convention.

    Parameters
    ----------
    result:
        A fitted :class:`DCCResult`.
    horizon:
        Steps ahead (>= 1).  Defaults to ``result.config.horizon``.

    Returns
    -------
    numpy.ndarray
        ``N x N`` forecast correlation matrix (unit diagonal, symmetric).

    Raises
    ------
    ValueError
        If ``horizon < 1``.
    """
    h = result.config.horizon if horizon is None else horizon
    if h < 1:
        raise ValueError(f"horizon must be >= 1; got {h}")

    a = result.a
    b = result.b
    q_bar = result.q_bar
    q_bar_star = _correlation_from_q(q_bar)

    # One-step quasi-correlation Q_{t+1} from the last in-sample state.
    e_last = result.std_resid[-1]
    q_last = result.q_path[-1]
    q_next = (1.0 - a - b) * q_bar + a * np.outer(e_last, e_last) + b * q_last

    rho = a + b
    weight = rho ** (h - 1)
    q_fcst = (1.0 - weight) * q_bar_star + weight * q_next
    return _correlation_from_q(q_fcst)


def dcc_forward_covariance(
    result: DCCResult,
    vol_forecasts: pd.Series | np.ndarray,
    *,
    horizon: int | None = None,
) -> np.ndarray:
    """Combine the DCC correlation forecast with external vol forecasts.

    Builds a forward covariance ``Cov = D_fcst R_fcst D_fcst`` where
    ``R_fcst`` is :func:`dcc_forecast_correlation` at the requested horizon and
    ``D_fcst`` is the diagonal of the externally supplied per-asset volatility
    forecasts (e.g. from ``core_trading.risk.vol_forecast`` --
    ``VolForecastResult.one_step_vol_series`` for the 1-step case, or the
    per-asset ``forecast_vol`` for the h-step cumulative case).

    This is the documented **drop-in upgrade** for the CCC covariance produced
    by ``core_trading.risk.vol_forecast.forecast_cov_matrix``: same units,
    same shape conventions, and the same PSD contract (eigenvalue clip via
    ``core_trading.portfolio.covariance.nearest_psd`` with ``epsilon = 0.0``),
    but with a time-/horizon-varying correlation in place of a constant one.

    Parameters
    ----------
    result:
        A fitted :class:`DCCResult`.
    vol_forecasts:
        Per-asset volatility (standard deviation) forecasts, length ``N`` and
        in the same asset order as ``result.assets``.  A pandas Series is
        reindexed by ``result.assets``; an array is used positionally.  Values
        must be finite and non-negative.
    horizon:
        Steps ahead for the correlation forecast.  Defaults to
        ``result.config.horizon``.

    Returns
    -------
    numpy.ndarray
        ``N x N`` symmetric PSD forecast covariance matrix.  The diagonal is
        ``vol_forecasts**2`` (up to PSD-clip adjustment, which only ever
        increases negative eigenvalues and leaves an already-PSD matrix
        unchanged).

    Raises
    ------
    ValueError
        If ``vol_forecasts`` has the wrong length, contains non-finite or
        negative entries, or (Series form) is missing an asset.
    """
    assets = result.assets
    n_assets = len(assets)

    if isinstance(vol_forecasts, pd.Series):
        missing = [a for a in assets if a not in vol_forecasts.index]
        if missing:
            raise ValueError(
                f"vol_forecasts Series is missing asset(s): {missing}."
            )
        vols = vol_forecasts.reindex(assets).to_numpy(dtype=float)
    else:
        vols = np.asarray(vol_forecasts, dtype=float).ravel()
        if vols.size != n_assets:
            raise ValueError(
                f"vol_forecasts length {vols.size} does not match number of "
                f"assets {n_assets}."
            )

    if not np.all(np.isfinite(vols)):
        raise ValueError("vol_forecasts contains non-finite values.")
    if np.any(vols < 0.0):
        raise ValueError("vol_forecasts contains negative values.")

    r_fcst = dcc_forecast_correlation(result, horizon=horizon)
    cov: np.ndarray = np.outer(vols, vols) * r_fcst
    cov = (cov + cov.T) / 2.0

    eigenvalues = np.linalg.eigvalsh(cov)
    if bool(eigenvalues[0] < 0.0):
        cov = nearest_psd(cov, epsilon=0.0)

    return cov


def dcc_correlation_series(result: DCCResult, pair: tuple[str, str]) -> pd.Series:
    """Extract the time-varying conditional correlation path for one pair.

    Returns the in-sample ``R_t[i, j]`` series for the two named assets,
    suitable for feeding ``core_trading.risk.correlation_regime``-style
    monitoring (e.g. delta-AR / regime-shift detection on a model-based
    correlation rather than a rolling-window estimate).

    Parameters
    ----------
    result:
        A fitted :class:`DCCResult`.
    pair:
        ``(asset_i, asset_j)`` names; both must be in ``result.assets`` and
        must be distinct.

    Returns
    -------
    pandas.Series
        Length-``T`` correlation path named ``"corr_<i>_<j>"``.  The index is a
        plain ``RangeIndex`` over the in-sample rows (the fit operates on the
        panel's positional rows).

    Raises
    ------
    ValueError
        If either asset is unknown or the two assets are identical.
    """
    asset_i, asset_j = pair
    if asset_i == asset_j:
        raise ValueError(f"pair must name two distinct assets; got {pair!r}.")
    if asset_i not in result.assets:
        raise ValueError(f"unknown asset {asset_i!r}; not in {result.assets}.")
    if asset_j not in result.assets:
        raise ValueError(f"unknown asset {asset_j!r}; not in {result.assets}.")

    i = result.assets.index(asset_i)
    j = result.assets.index(asset_j)
    path = result.correlations[:, i, j]
    return pd.Series(
        np.asarray(path, dtype=float),
        name=f"corr_{asset_i}_{asset_j}",
    )
