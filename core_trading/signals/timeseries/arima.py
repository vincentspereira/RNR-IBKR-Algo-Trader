"""ARIMA/SARIMA short-term forecasting and fractional differencing (Phase 5.A.4).

Provides ARIMA and SARIMA model fitting via the state-space SARIMAX
implementation from statsmodels, plus fractional differencing utilities that
preserve long memory while transforming a non-stationary price series into a
stationary one.

Design notes
------------
* :class:`ArimaConfig` and :class:`ArimaResult` are frozen dataclasses so
  they can be safely passed across threads and cached.
* ``statsmodels`` is lazy-imported inside each function and method so that the
  module is importable even when statsmodels is not installed (e.g., in
  minimal test environments).
* All series inputs are coerced to numpy arrays before passing to SARIMAX.
  This avoids the pandas ``Series.__getitem__`` FutureWarning that statsmodels
  0.14.x triggers when it internally indexes a pandas Series by integer
  position.
* :func:`frac_diff_ffd` implements the fixed-width-window (FFD) method from
  Lopez de Prado (2018).  The filter window is determined by a weight-
  truncation threshold; callers must ensure the series is long enough to
  produce at least one valid output observation.
* :func:`frac_diff` implements the standard expanding-window fractional
  differencing for comparison.
* :func:`min_frac_diff` finds the minimum differencing order d that produces
  a stationary series (ADF test), grid-searching d in [0, 1] with a
  configurable step.

Mathematical references
-----------------------
ARIMA/SARIMA model:
    Box, G.E.P. and Jenkins, G.M. (1970). "Time Series Analysis: Forecasting
    and Control." Holden-Day.

Fractional differencing (ARFIMA long memory):
    Hosking, J.R.M. (1981). "Fractional differencing." Biometrika, 68(1),
    165-176.

Fixed-width-window fractional differencing:
    Lopez de Prado, M. (2018). "Advances in Financial Machine Learning."
    Wiley. Chapter 5 (Fractionally Differentiated Features).
    The FFD method computes weights w_k = prod_{i=0}^{k-1} (d-i)/(i+1) and
    truncates the filter at the first k where |w_k| < threshold, giving a
    fixed window of length w_len.  For each observation t >= w_len-1 the
    output is sum_{k=0}^{w_len-1} w_k * x[t-k].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "ArimaConfig",
    "ArimaResult",
    "FracDiffResult",
    "fit_arima",
    "frac_diff_ffd",
    "frac_diff",
    "min_frac_diff",
]


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArimaConfig:
    """Configuration for an ARIMA or SARIMA model.

    Attributes
    ----------
    order:
        Non-seasonal (p, d, q) order tuple.  p is the AR lag count, d is the
        integration order, q is the MA lag count.
    seasonal_order:
        Seasonal (P, D, Q, s) order tuple.  s is the seasonal period.
        Pass ``(0, 0, 0, 0)`` (the default) to fit a non-seasonal ARIMA.
    trend:
        Deterministic trend specification passed to SARIMAX.  ``"n"``
        (no trend/intercept) or ``"c"`` (constant intercept).  Default
        ``"n"``.
    """

    order: tuple[int, int, int] = (1, 0, 0)
    seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0)
    trend: str = "n"


@dataclass(frozen=True, slots=True)
class ArimaResult:
    """Fitted ARIMA/SARIMA model output.

    Attributes
    ----------
    config:
        The model configuration used for fitting.
    params:
        Dictionary mapping parameter name to estimated value (e.g.
        ``{"ar.L1": 0.72, "sigma2": 0.98}``).
    loglikelihood:
        Log-likelihood of the fitted model evaluated at the parameters.
    aic:
        Akaike information criterion: ``-2 * loglikelihood + 2 * k`` where
        k is the number of free parameters.
    bic:
        Bayesian information criterion: ``-2 * loglikelihood + k * log(n)``.
    fitted_values:
        In-sample one-step-ahead fitted values as a 1-D numpy array.
    n_obs:
        Number of observations used for fitting.
    _fitted_result:
        The live statsmodels SARIMAXResultsWrapper object.  This field is
        set by :func:`fit_arima` and is required by :meth:`forecast`.  It
        is excluded from repr and equality checks.
    """

    config: ArimaConfig
    params: dict[str, float] = field(default_factory=dict)
    loglikelihood: float = 0.0
    aic: float = 0.0
    bic: float = 0.0
    fitted_values: np.ndarray = field(default_factory=lambda: np.empty(0))
    n_obs: int = 0
    _fitted_result: Any = field(default=None, repr=False, compare=False)

    def forecast(
        self,
        horizon: int,
        *,
        conf_int: bool = False,
        alpha: float = 0.05,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
        """Produce out-of-sample point forecasts (and optional intervals).

        The method re-fits the model from the stored result object.  The
        returned forecast is based on the posterior state at the end of the
        in-sample period.

        Parameters
        ----------
        horizon:
            Number of steps ahead to forecast.  Must be >= 1.
        conf_int:
            When ``True`` also return a ``(2, horizon)`` array of lower and
            upper confidence-interval bounds.
        alpha:
            Significance level for the confidence interval.  Default 0.05
            gives a 95% interval.

        Returns
        -------
        np.ndarray
            Point forecast array of shape ``(horizon,)`` when
            ``conf_int=False``.
        tuple[np.ndarray, np.ndarray]
            ``(point_forecast, ci)`` where ``ci`` has shape ``(horizon, 2)``
            with columns ``[lower, upper]`` when ``conf_int=True``.

        Raises
        ------
        ValueError
            If ``horizon < 1``.
        AttributeError
            If the internal fitted result is ``None`` (should not occur in
            normal use; only when the DTO is constructed outside
            :func:`fit_arima`).
        """
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        if self._fitted_result is None:
            raise AttributeError(
                "ArimaResult._fitted_result is None; use fit_arima() to create "
                "a result with a live model attached."
            )
        fc = self._fitted_result.get_forecast(steps=horizon)
        mean = np.asarray(fc.predicted_mean, dtype=float)
        if conf_int:
            ci_df = fc.conf_int(alpha=alpha)
            ci = np.asarray(ci_df, dtype=float)
            return mean, ci
        return mean


@dataclass(frozen=True, slots=True)
class FracDiffResult:
    """Output of a fractional differencing operation.

    Attributes
    ----------
    series:
        The fractionally differenced series.  For FFD this contains NaN for
        the first ``window_length - 1`` positions; for expanding-window
        differencing all positions are finite.
    d:
        The differencing order used.
    threshold:
        The weight-truncation threshold used.
    window_length:
        Number of weights in the filter (FFD) or ``None`` for expanding.
    method:
        Either ``"ffd"`` (fixed-width window) or ``"expanding"``.
    """

    series: np.ndarray
    d: float
    threshold: float
    window_length: int | None
    method: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ffd_weights(d: float, threshold: float) -> np.ndarray:
    """Compute FFD filter weights until the weight drops below ``threshold``.

    The k-th weight is defined by the binomial expansion of (1-B)^d:

        w_0 = 1
        w_k = -w_{k-1} * (d - k + 1) / k

    Iteration stops when ``|w_k| < threshold``.

    Parameters
    ----------
    d:
        Fractional differencing order in [0, 1].
    threshold:
        Minimum absolute weight magnitude.  Smaller values yield longer
        windows and more accurate approximations at the cost of requiring
        longer series.

    Returns
    -------
    np.ndarray
        1-D array of filter weights ``[w_0, w_1, ..., w_{L-1}]``.
    """
    if not (0.0 <= d <= 1.0):
        raise ValueError("d must be in [0, 1]")
    if threshold <= 0.0:
        raise ValueError("threshold must be positive")
    weights: list[float] = [1.0]
    k = 1
    while True:
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < threshold:
            break
        weights.append(w)
        k += 1
    return np.array(weights, dtype=float)


def _expanding_weights(d: float, length: int, threshold: float) -> np.ndarray:
    """Compute expanding-window weights of a given ``length``.

    Weights are computed up to ``length`` entries; iteration also stops early
    if the weight falls below ``threshold`` (remaining positions are set to
    zero).

    Parameters
    ----------
    d:
        Fractional differencing order in [0, 1].
    length:
        Desired number of weights.
    threshold:
        Early-stop threshold for negligible weights.

    Returns
    -------
    np.ndarray
        1-D array of length ``length`` containing the filter weights.
    """
    weights: list[float] = [1.0]
    for k in range(1, length):
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < threshold:
            weights.extend([0.0] * (length - len(weights)))
            break
        weights.append(w)
    return np.array(weights[:length], dtype=float)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fit_arima(
    series: pd.Series | np.ndarray,
    order: tuple[int, int, int] = (1, 0, 0),
    seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0),
    trend: str = "n",
) -> ArimaResult:
    """Fit an ARIMA or SARIMA model using the SARIMAX state-space framework.

    Parameters
    ----------
    series:
        Univariate time series.  Passed as a numpy array to the SARIMAX
        constructor to avoid the statsmodels/pandas integer-indexing
        FutureWarning.  If a :class:`pandas.Series` is provided it is
        converted to a numpy array before fitting.
    order:
        Non-seasonal ARIMA order ``(p, d, q)``.
    seasonal_order:
        Seasonal order ``(P, D, Q, s)``.  Use ``(0, 0, 0, 0)`` (default)
        for a non-seasonal model.
    trend:
        Deterministic trend.  ``"n"`` for no intercept, ``"c"`` for a
        constant.

    Returns
    -------
    ArimaResult
        Frozen result DTO containing parameters, information criteria,
        fitted values, and an attached :meth:`ArimaResult.forecast` method.

    Raises
    ------
    ValueError
        If the series has fewer than ``p + q + P + Q + 2`` observations, or
        if any order tuple contains negative values.

    Notes
    -----
    statsmodels is lazy-imported inside this function.  The series is coerced
    to a numpy array to prevent FutureWarning from statsmodels 0.14.x.

    Examples
    --------
    >>> import numpy as np
    >>> rng = np.random.default_rng(0)
    >>> y = rng.normal(size=200)
    >>> result = fit_arima(y, order=(1, 0, 0))
    >>> result.aic > 0
    True
    """
    from statsmodels.tsa.statespace.sarimax import SARIMAX as _SARIMAX

    arr = np.asarray(series, dtype=float)
    n = arr.size
    p, d_int, q = order
    P, D, Q, s = seasonal_order
    min_obs = p + q + P + Q + max(d_int, D) + 2
    if n < min_obs:
        raise ValueError(
            f"Series has {n} observations but order {order} / seasonal_order "
            f"{seasonal_order} requires at least {min_obs}."
        )
    for val, label in [
        (p, "p"), (d_int, "d"), (q, "q"), (P, "P"), (D, "D"), (Q, "Q"), (s, "s"),
    ]:
        if val < 0:
            raise ValueError(f"Order parameter {label} must be non-negative, got {val}.")

    config = ArimaConfig(order=order, seasonal_order=seasonal_order, trend=trend)

    mod = _SARIMAX(
        arr,
        order=order,
        seasonal_order=seasonal_order,
        trend=trend,
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    fitted_res = mod.fit(disp=False)

    params_dict: dict[str, float] = {
        name: float(val)
        for name, val in zip(fitted_res.param_names, fitted_res.params, strict=False)
    }
    fitted_values = np.asarray(fitted_res.fittedvalues, dtype=float)

    return ArimaResult(
        config=config,
        params=params_dict,
        loglikelihood=float(fitted_res.llf),
        aic=float(fitted_res.aic),
        bic=float(fitted_res.bic),
        fitted_values=fitted_values,
        n_obs=int(n),
        _fitted_result=fitted_res,
    )


def frac_diff_ffd(
    series: pd.Series | np.ndarray,
    d: float,
    threshold: float = 1e-3,
) -> FracDiffResult:
    """Fixed-width-window (FFD) fractional differencing.

    Implements the method of Lopez de Prado (2018, Chapter 5).  The filter
    window length is determined by truncating binomial weights at
    ``threshold``; only observations at index >= ``window_length - 1`` have
    valid (non-NaN) output.

    The FFD method is preferred over expanding-window differencing for
    financial series because it uses a FIXED window of length L, which:
    (a) does not let distant past observations accumulate unbounded weight,
    (b) preserves the maximum amount of memory in the original level series
        while achieving stationarity when d is chosen appropriately.

    Parameters
    ----------
    series:
        Input time series.  May be a pandas Series (index is preserved) or
        a 1-D numpy array.
    d:
        Fractional differencing order in [0, 1].  d=0 returns the original
        series (no differencing); d=1 approximates the ordinary first
        difference.
    threshold:
        Minimum absolute weight magnitude for filter truncation.  Smaller
        values give a longer window and a more accurate approximation but
        require longer series.  Default 1e-3 (window length ~11-100
        depending on d).

    Returns
    -------
    FracDiffResult
        Result DTO containing the fractionally differenced series as a numpy
        array (or pandas Series when the input was a pandas Series).

    Raises
    ------
    ValueError
        If ``d`` is outside [0, 1], ``threshold`` is non-positive, or the
        series is shorter than the filter window.

    Notes
    -----
    For d=0 the weight vector is ``[1.0]`` and the output equals the input
    (no NaN padding).  For d=1 the weight vector is ``[1.0, -1.0]`` and the
    output equals the ordinary first difference (NaN at position 0).

    Mathematical reference:
        w_k = prod_{i=0}^{k-1} (d-i)/(i+1),  k = 0, 1, 2, ...
        output_t = sum_{k=0}^{L-1} w_k * x_{t-k}

    Examples
    --------
    >>> import numpy as np
    >>> rng = np.random.default_rng(0)
    >>> x = np.cumsum(rng.normal(size=500))
    >>> result = frac_diff_ffd(x, d=0.4)
    >>> result.method
    'ffd'
    """
    if not (0.0 <= d <= 1.0):
        raise ValueError(f"d must be in [0, 1], got {d}.")
    if threshold <= 0.0:
        raise ValueError(f"threshold must be positive, got {threshold}.")

    arr = np.asarray(series, dtype=float)
    n = len(arr)
    weights = _ffd_weights(d, threshold)
    w_len = len(weights)

    if w_len > n:
        raise ValueError(
            f"Series length {n} is shorter than the filter window {w_len}. "
            f"Use a larger threshold or provide a longer series."
        )

    out = np.full(n, np.nan, dtype=float)
    for t in range(w_len - 1, n):
        out[t] = float(np.dot(weights, arr[t - w_len + 1 : t + 1][::-1]))

    out_series: np.ndarray | pd.Series
    if isinstance(series, pd.Series):
        out_series = pd.Series(out, index=series.index, name=series.name)
    else:
        out_series = out

    return FracDiffResult(
        series=out_series,
        d=d,
        threshold=threshold,
        window_length=w_len,
        method="ffd",
    )


def frac_diff(
    series: pd.Series | np.ndarray,
    d: float,
    threshold: float = 1e-3,
) -> FracDiffResult:
    """Expanding-window fractional differencing.

    Standard fractional integration operator (1-B)^d applied with an
    expanding window: at each time t all past observations contribute with
    weights that decay but never hit a hard truncation cutoff.  Weights
    below ``threshold`` are set to zero (early-stop per time step).

    This method was described by Hosking (1981) and is the classical approach
    before the FFD approximation.  It produces fully finite output for all
    observations (no NaN warm-up period) but allows ancient observations to
    exert small residual influence.

    Parameters
    ----------
    series:
        Input time series.
    d:
        Fractional differencing order in [0, 1].
    threshold:
        Early-stop threshold per time step; weights smaller in absolute
        value than this are treated as zero.  Default 1e-3.

    Returns
    -------
    FracDiffResult
        Result DTO with ``method="expanding"`` and ``window_length=None``.

    Raises
    ------
    ValueError
        If ``d`` is outside [0, 1] or ``threshold`` is non-positive.

    Examples
    --------
    >>> import numpy as np
    >>> rng = np.random.default_rng(0)
    >>> x = np.cumsum(rng.normal(size=200))
    >>> result = frac_diff(x, d=0.4)
    >>> result.method
    'expanding'
    """
    if not (0.0 <= d <= 1.0):
        raise ValueError(f"d must be in [0, 1], got {d}.")
    if threshold <= 0.0:
        raise ValueError(f"threshold must be positive, got {threshold}.")

    arr = np.asarray(series, dtype=float)
    n = len(arr)
    out = np.empty(n, dtype=float)

    for t in range(n):
        w = _expanding_weights(d, t + 1, threshold)
        out[t] = float(np.dot(w, arr[: t + 1][::-1]))

    out_series: np.ndarray | pd.Series
    if isinstance(series, pd.Series):
        out_series = pd.Series(out, index=series.index, name=series.name)
    else:
        out_series = out

    return FracDiffResult(
        series=out_series,
        d=d,
        threshold=threshold,
        window_length=None,
        method="expanding",
    )


def min_frac_diff(
    series: pd.Series | np.ndarray,
    *,
    threshold_fd: float = 1e-3,
    adf_alpha: float = 0.05,
    d_step: float = 0.05,
    min_valid_obs: int = 30,
) -> float:
    """Find the minimum fractional differencing order d that achieves stationarity.

    Grid-searches d in ``{0, d_step, 2*d_step, ..., 1.0}`` using the FFD
    method and the Augmented Dickey-Fuller test.  Returns the smallest d for
    which the ADF p-value is below ``adf_alpha``.

    Preserving memory is the core motivation: the minimum d that achieves
    stationarity retains the maximum amount of serial correlation from the
    original level series.

    Parameters
    ----------
    series:
        Input (typically non-stationary) time series.
    threshold_fd:
        FFD weight-truncation threshold passed to :func:`frac_diff_ffd`.
    adf_alpha:
        Significance level for the ADF test.  Default 0.05.
    d_step:
        Grid step size for the d search.  Default 0.05.
    min_valid_obs:
        Minimum number of non-NaN observations required for the ADF test to
        proceed.  Default 30.

    Returns
    -------
    float
        Minimum d (from the grid) at which the FFD-differenced series passes
        the ADF stationarity test, or ``1.0`` if no grid point achieves
        stationarity.

    Raises
    ------
    ValueError
        If ``d_step <= 0`` or ``d_step > 1``.

    Notes
    -----
    At d=0 the test is applied to the original series.  If the original
    series is already stationary, 0.0 is returned.  The series is coerced to
    a numpy array; the statsmodels adfuller function is lazy-imported.

    Examples
    --------
    >>> import numpy as np
    >>> rng = np.random.default_rng(0)
    >>> x = np.cumsum(rng.normal(size=1000))
    >>> d = min_frac_diff(x)
    >>> 0.0 <= d <= 1.0
    True
    """
    from statsmodels.tsa.stattools import adfuller as _adfuller

    if d_step <= 0.0 or d_step > 1.0:
        raise ValueError(f"d_step must be in (0, 1], got {d_step}.")

    arr = np.asarray(series, dtype=float)
    n_steps = int(round(1.0 / d_step))
    d_grid = [round(i * d_step, 10) for i in range(n_steps + 1)]

    for d in d_grid:
        if d == 0.0:
            candidate = arr[np.isfinite(arr)]
        else:
            try:
                fd_result = frac_diff_ffd(arr, d, threshold=threshold_fd)
            except ValueError:
                continue
            fd_arr = np.asarray(fd_result.series, dtype=float)
            candidate = fd_arr[np.isfinite(fd_arr)]

        if len(candidate) < min_valid_obs:
            continue

        _, pval, *_ = _adfuller(candidate, autolag="AIC")
        if float(pval) < adf_alpha:
            return float(d)

    return 1.0
