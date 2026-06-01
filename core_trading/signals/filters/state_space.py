"""Unobserved-components (structural time series) models (master plan Phase 5.A.3).

Wraps the statsmodels ``UnobservedComponents`` state-space framework to provide
a clean, frozen-dataclass interface for fitting and decomposing financial time
series into trend, seasonal, and cycle components.

Models provided
---------------
* Local level            -- level that follows a random walk.
* Local linear trend     -- level + slope, both following random walks.
* Basic structural model -- local linear trend + stochastic seasonal component.
* General interface      -- flexible ``fit_unobserved_components`` that accepts
                            arbitrary component combinations.

The state-space model for an unobserved-components process is:

    Observation:    y_t = mu_t + gamma_t + psi_t + epsilon_t
    Level:          mu_t   = mu_{t-1}   + nu_{t-1} + xi_t
    Slope:          nu_t   = nu_{t-1}   + zeta_t
    Seasonal:       gamma_t = -sum_{j=1}^{s-1} gamma_{t-j} + omega_t
    Cycle:          psi_t   = rho*(psi_{t-1}*cos(lambda) + psi*_{t-1}*sin(lambda)) + kappa_t

where xi, zeta, omega, kappa, epsilon are independent Gaussian white-noise
disturbances.

Design notes
------------
* ``statsmodels`` is lazy-imported inside each function so the module is
  importable even in environments without statsmodels.
* :class:`StateSpaceResult` stores the live statsmodels result object in the
  private ``_fitted_result`` field so that :meth:`StateSpaceResult.forecast`
  can delegate to the native statsmodels ``forecast`` method.
* Component arrays are extracted from ``smoothed_state`` (the RTS-smoothed
  state via the Kalman filter; ``res.states.smoothed`` in statsmodels).
* All series inputs are coerced to numpy arrays before passing to
  ``UnobservedComponents`` to avoid the pandas integer-indexing FutureWarning
  from statsmodels 0.14.x.

Mathematical references
-----------------------
Harvey (1989) structural time series:
    Harvey, A.C. (1989). "Forecasting, Structural Time Series Models and the
    Kalman Filter." Cambridge University Press.

Durbin and Koopman (2012) state-space methods:
    Durbin, J. and Koopman, S.J. (2012). "Time Series Analysis by State Space
    Methods." 2nd ed. Oxford University Press.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "StateSpaceResult",
    "fit_local_level",
    "fit_local_linear_trend",
    "fit_basic_structural",
    "fit_unobserved_components",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------

_EMPTY: np.ndarray = np.empty(0, dtype=float)


@dataclass(frozen=True, slots=True)
class StateSpaceResult:
    """Fitted unobserved-components (structural time series) model output.

    Attributes
    ----------
    level:
        Smoothed level component, shape (T,).  Always present.
    trend:
        Smoothed slope/trend component, shape (T,).  Empty array (shape (0,))
        when no trend was modelled.
    seasonal:
        Smoothed seasonal component, shape (T,).  Empty array when no
        seasonal component was modelled.
    cycle:
        Smoothed cycle component, shape (T,).  Empty array when no cycle
        was modelled.
    params:
        Dictionary of estimated variance (and other) parameters, e.g.
        ``{"sigma2.irregular": 0.5, "sigma2.level": 0.01}``.
    loglikelihood:
        Log-likelihood of the fitted model.
    aic:
        Akaike information criterion.
    _fitted_result:
        The live statsmodels ``UnobservedComponentsResults`` wrapper.
        Excluded from repr and equality checks.  Required by
        :meth:`forecast`.

    Notes
    -----
    Component arrays are extracted from the RTS-smoothed state sequence
    (``res.states.smoothed`` in statsmodels).  They reflect all-data
    posterior estimates.
    """

    level: np.ndarray
    trend: np.ndarray = field(default_factory=lambda: _EMPTY.copy())
    seasonal: np.ndarray = field(default_factory=lambda: _EMPTY.copy())
    cycle: np.ndarray = field(default_factory=lambda: _EMPTY.copy())
    params: dict[str, float] = field(default_factory=dict)
    loglikelihood: float = 0.0
    aic: float = 0.0
    _fitted_result: Any = field(default=None, repr=False, compare=False)

    def forecast(self, steps: int) -> np.ndarray:
        """Produce out-of-sample point forecasts.

        Delegates to the stored statsmodels fitted result.

        Parameters
        ----------
        steps:
            Number of steps ahead to forecast.  Must be >= 1.

        Returns
        -------
        np.ndarray
            Point forecast array of shape (steps,).

        Raises
        ------
        ValueError
            If ``steps < 1``.
        AttributeError
            If ``_fitted_result`` is None (should not happen when constructed
            via the module's public factory functions).

        Mathematical references
        -----------------------
        Harvey (1989) Chapter 4 (forecasting from state-space models).
        """
        if steps < 1:
            raise ValueError(f"steps must be >= 1, got {steps}")
        if self._fitted_result is None:
            raise AttributeError(
                "StateSpaceResult._fitted_result is None; use a factory "
                "function (fit_local_level, etc.) to obtain a live result."
            )
        return np.asarray(self._fitted_result.forecast(steps), dtype=float)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MIN_OBS = 10  # minimum observations required to fit any UC model


def _validate_series(y: pd.Series, min_obs: int = _MIN_OBS) -> np.ndarray:
    """Validate and coerce the input series to a 1-D float64 array.

    Parameters
    ----------
    y:
        Input time series.
    min_obs:
        Minimum required length after dropping NaN.

    Returns
    -------
    np.ndarray
        Clean 1-D float64 array (NaN dropped).

    Raises
    ------
    ValueError
        If fewer than ``min_obs`` finite observations remain.
    """
    arr = np.asarray(y.dropna(), dtype=float)
    if arr.size < min_obs:
        raise ValueError(
            f"Series has only {arr.size} finite observations; "
            f"need at least {min_obs} to fit an unobserved-components model."
        )
    return arr


def _fit_model(mod: Any) -> Any:
    """Fit a statsmodels UnobservedComponents model, suppressing known benign warnings.

    Statsmodels emits ``ConvergenceWarning`` when the optimizer does not
    formally converge (very common for structural models with near-zero
    variances) and ``SpecificationWarning`` when a model is constructed with
    a specification that lacks a stochastic element (statsmodels auto-adds an
    irregular term).  Both warnings are informational and do not indicate an
    unusable fit; suppressing them allows the test suite to run under
    ``-W error`` without false failures.

    Parameters
    ----------
    mod:
        An un-fitted ``UnobservedComponents`` model instance.

    Returns
    -------
    Any
        The fitted ``UnobservedComponentsResults`` wrapper.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="statsmodels")
        return mod.fit(disp=False)


def _extract_result(fitted_res: Any, *, has_trend: bool, has_seasonal: bool, has_cycle: bool) -> StateSpaceResult:
    """Build a :class:`StateSpaceResult` from a fitted statsmodels result.

    Parameters
    ----------
    fitted_res:
        A fitted ``UnobservedComponentsResults`` instance.
    has_trend:
        Whether a slope/trend component is in the model.
    has_seasonal:
        Whether a seasonal component is in the model.
    has_cycle:
        Whether a cycle component is in the model.

    Returns
    -------
    StateSpaceResult
        Frozen DTO populated from the smoothed states.
    """
    # states.smoothed is (T, k_states); state_names maps indices to names
    ss = fitted_res.states.smoothed  # shape (T, k_states)
    state_names: list[str] = list(fitted_res.model.state_names)

    def _get_component(name: str) -> np.ndarray:
        """Extract the smoothed state column matching the given name."""
        if name in state_names:
            idx = state_names.index(name)
            return np.asarray(ss[:, idx], dtype=float)
        return _EMPTY.copy()  # pragma: no cover

    level_arr = _get_component("level")

    trend_arr = _get_component("trend") if has_trend else _EMPTY.copy()

    if has_seasonal and "seasonal" in state_names:
        seasonal_arr = _get_component("seasonal")
    else:
        seasonal_arr = _EMPTY.copy()

    cycle_arr = _get_component("cycle") if has_cycle and "cycle" in state_names else _EMPTY.copy()

    params_dict: dict[str, float] = {
        name: float(val)
        for name, val in zip(fitted_res.param_names, fitted_res.params, strict=False)
    }

    return StateSpaceResult(
        level=level_arr,
        trend=trend_arr,
        seasonal=seasonal_arr,
        cycle=cycle_arr,
        params=params_dict,
        loglikelihood=float(fitted_res.llf),
        aic=float(fitted_res.aic),
        _fitted_result=fitted_res,
    )


# ---------------------------------------------------------------------------
# Public factory functions
# ---------------------------------------------------------------------------


def fit_local_level(y: pd.Series) -> StateSpaceResult:
    """Fit a local-level (random-walk + noise) model.

    The model is:
        y_t   = mu_t + epsilon_t,  epsilon_t ~ N(0, sigma2_epsilon)
        mu_t  = mu_{t-1} + xi_t,  xi_t ~ N(0, sigma2_xi)

    This is the simplest structural time series model; it corresponds to
    exponential smoothing.

    Parameters
    ----------
    y:
        Univariate time series.  NaN values are dropped before fitting.

    Returns
    -------
    StateSpaceResult
        Fitted result with ``level`` populated.  ``trend``, ``seasonal``,
        and ``cycle`` are empty arrays.

    Raises
    ------
    ValueError
        If fewer than 10 finite observations are available.

    Mathematical references
    -----------------------
    Harvey (1989) Section 2.3 (local level model).
    Durbin and Koopman (2012) Section 3.2.
    """
    from statsmodels.tsa.statespace.structural import (  # lazy import
        UnobservedComponents as _UC,
    )

    arr = _validate_series(y)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="statsmodels")
        mod = _UC(arr, "local level")
        res = _fit_model(mod)
    return _extract_result(res, has_trend=False, has_seasonal=False, has_cycle=False)


def fit_local_linear_trend(y: pd.Series) -> StateSpaceResult:
    """Fit a local-linear-trend (level + slope random walk) model.

    The model is:
        y_t  = mu_t + epsilon_t
        mu_t = mu_{t-1} + nu_{t-1} + xi_t
        nu_t = nu_{t-1} + zeta_t

    where all disturbances are independent Gaussian white noise.  This model
    allows both the level and slope to evolve stochastically.

    Parameters
    ----------
    y:
        Univariate time series.  NaN values are dropped before fitting.

    Returns
    -------
    StateSpaceResult
        Fitted result with ``level`` and ``trend`` (slope) populated.
        ``seasonal`` and ``cycle`` are empty arrays.

    Raises
    ------
    ValueError
        If fewer than 10 finite observations are available.

    Mathematical references
    -----------------------
    Harvey (1989) Section 2.4 (local linear trend model).
    Durbin and Koopman (2012) Section 3.3.
    """
    from statsmodels.tsa.statespace.structural import (  # lazy import
        UnobservedComponents as _UC,
    )

    arr = _validate_series(y)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="statsmodels")
        mod = _UC(arr, "local linear trend")
        res = _fit_model(mod)
    return _extract_result(res, has_trend=True, has_seasonal=False, has_cycle=False)


def fit_basic_structural(
    y: pd.Series,
    *,
    seasonal_periods: int,
) -> StateSpaceResult:
    """Fit a basic structural model (BSM): local linear trend + seasonal.

    The BSM decomposes the series into trend, slope, and seasonal components,
    all subject to stochastic evolution.  This is the standard Harvey (1989)
    BSM for seasonal financial data.

    Parameters
    ----------
    y:
        Univariate time series.  NaN values are dropped before fitting.
    seasonal_periods:
        Number of periods in a full seasonal cycle (e.g. 12 for monthly
        data with annual seasonality, 4 for quarterly).  Must be >= 2.

    Returns
    -------
    StateSpaceResult
        Fitted result with ``level``, ``trend``, and ``seasonal`` populated.
        ``cycle`` is an empty array.

    Raises
    ------
    ValueError
        If ``seasonal_periods < 2`` or if fewer than ``max(10, seasonal_periods * 2)``
        finite observations are available.

    Mathematical references
    -----------------------
    Harvey (1989) Section 2.5 (basic structural model).
    Durbin and Koopman (2012) Section 3.4.
    """
    from statsmodels.tsa.statespace.structural import (  # lazy import
        UnobservedComponents as _UC,
    )

    if seasonal_periods < 2:
        raise ValueError(f"seasonal_periods must be >= 2, got {seasonal_periods}")
    min_obs = max(_MIN_OBS, seasonal_periods * 2)
    arr = _validate_series(y, min_obs=min_obs)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="statsmodels")
        mod = _UC(arr, "local linear trend", seasonal=seasonal_periods)
        res = _fit_model(mod)
    return _extract_result(res, has_trend=True, has_seasonal=True, has_cycle=False)


def fit_unobserved_components(
    y: pd.Series,
    *,
    level: bool | str = True,
    trend: bool = False,
    seasonal: int | None = None,
    cycle: bool = False,
) -> StateSpaceResult:
    """Fit a general unobserved-components model with configurable components.

    Parameters
    ----------
    y:
        Univariate time series.  NaN values are dropped before fitting.
    level:
        Whether to include a stochastic level.  Pass ``True`` (default) for
        a local-level model or a statsmodels model string such as
        ``"local level"`` or ``"local linear trend"`` to use that preset.
        Pass ``False`` only if a different top-level string is provided.
    trend:
        Whether to include a stochastic slope component.  Ignored when
        ``level`` is a string that already implies a trend (e.g.
        ``"local linear trend"``).
    seasonal:
        Seasonal period (e.g. 12).  Pass ``None`` (default) for no seasonal
        component.  Must be >= 2 when specified.
    cycle:
        Whether to include a stochastic cycle (damped cosine) component.

    Returns
    -------
    StateSpaceResult
        Fitted result.  Components present in the model are populated;
        others are empty arrays.

    Raises
    ------
    ValueError
        If the series is too short or ``seasonal < 2`` when provided.

    Notes
    -----
    When ``level`` is ``True`` and ``trend`` is ``True``, this is equivalent
    to ``fit_local_linear_trend``.  When ``seasonal`` is also provided, it
    is equivalent to ``fit_basic_structural``.

    Mathematical references
    -----------------------
    Harvey (1989); Durbin and Koopman (2012).
    """
    from statsmodels.tsa.statespace.structural import (  # lazy import
        UnobservedComponents as _UC,
    )

    if seasonal is not None and seasonal < 2:
        raise ValueError(f"seasonal must be >= 2 when specified, got {seasonal}")

    min_obs = max(_MIN_OBS, (seasonal * 2) if seasonal is not None else 0)
    arr = _validate_series(y, min_obs=min_obs)

    # Determine whether to use a string model spec or keyword arguments
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", module="statsmodels")
        if isinstance(level, str):
            # Use the string model spec; trend/seasonal/cycle are additive kwargs
            model_str = level
            has_trend_flag = "trend" in model_str.lower()
            mod = _UC(
                arr,
                model_str,
                seasonal=seasonal,
                cycle=cycle,
                stochastic_cycle=cycle,
            )
        else:
            # Use keyword arguments
            has_trend_flag = trend
            mod = _UC(
                arr,
                level=bool(level),
                trend=trend,
                seasonal=seasonal,
                cycle=cycle,
                stochastic_cycle=cycle,
            )
        res = _fit_model(mod)

    has_seasonal = seasonal is not None
    return _extract_result(
        res,
        has_trend=has_trend_flag,
        has_seasonal=has_seasonal,
        has_cycle=cycle,
    )
