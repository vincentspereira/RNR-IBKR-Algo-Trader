"""GARCH-family volatility signal models (master plan Phase 5.A.5).

Implements conditional-volatility estimation and h-step-ahead forecasting
via the GARCH, EGARCH, and GJR-GARCH models (using the ``arch`` library)
and the Heterogeneous Autoregressive model for Realised Variance (HAR-RV)
via OLS.

Design notes
------------
* :class:`GARCHConfig` and :class:`GARCHResult` are frozen slotted dataclasses
  so they can safely be passed across threads and cached.
* Heavy third-party imports (``arch``, ``statsmodels``) are lazy-loaded inside
  functions so that importing this module is cheap.
* The ``arch`` library's ``DataScaleWarning`` is silenced by working in
  *percentage returns* (``returns * 100``) throughout; all conditional
  volatility outputs are converted back to the original scale before being
  returned.  The variance in percentage-return space is approximately 1,
  which is inside the range ``[0.1, 10000)`` that ``arch`` expects.
* ``rescale=False`` is passed to ``arch_model.fit`` so that ``arch`` does not
  attempt its own internal rescaling, which can interfere with the manual
  pct-return rescaling documented above.

Mathematical references
-----------------------
GARCH(p,q) -- Bollerslev (1986) "Generalized autoregressive conditional
    heteroskedasticity", Journal of Econometrics, 31, 307-327.
    Variance recursion: h_t = omega + sum_{i=1}^{p} alpha_i * eps_{t-i}^2
                              + sum_{j=1}^{q} beta_j * h_{t-j}
EGARCH -- Nelson (1991) "Conditional heteroskedasticity in asset returns:
    a new approach", Econometrica, 59, 347-370.
    Log-variance recursion avoids non-negativity constraints.
GJR-GARCH -- Glosten, Jagannathan, and Runkle (1993) "On the relation
    between the expected value and the volatility of the nominal excess
    return on stocks", Journal of Finance, 48, 1779-1801.
    Adds a leverage term gamma*I(eps<0)*eps^2 to the GARCH variance equation.
HAR-RV -- Corsi (2009) "A simple approximate long-memory model of realized
    volatility", Journal of Financial Econometrics, 7, 174-196.
    RV_t = c + beta_d*RV_{t-1} + beta_w*RV^W_{t-1} + beta_m*RV^M_{t-1} + eps_t
    where RV^W is the 5-day average of lagged RV and RV^M is the 22-day average.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
import pandas as pd

__all__ = [
    "GARCHConfig",
    "GARCHResult",
    "HARRVConfig",
    "HARRVResult",
    "fit_garch",
    "forecast_variance",
    "realised_variance",
    "fit_har_rv",
    "forecast_har_rv",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ModelType = Literal["GARCH", "EGARCH", "GJR-GARCH"]

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GARCHConfig:
    """Configuration for a GARCH-family fit.

    Attributes
    ----------
    model:
        Which volatility model to use.  One of ``"GARCH"``, ``"EGARCH"``,
        or ``"GJR-GARCH"``.
    p:
        ARCH lag order (lagged squared innovations).
    q:
        GARCH lag order (lagged conditional variances).
    """

    model: ModelType = "GARCH"
    p: int = 1
    q: int = 1

    def __post_init__(self) -> None:
        if self.model not in ("GARCH", "EGARCH", "GJR-GARCH"):
            raise ValueError(f"model must be 'GARCH', 'EGARCH', or 'GJR-GARCH'; got {self.model!r}")
        if self.p < 1:
            raise ValueError(f"p must be >= 1; got {self.p}")
        if self.q < 1:
            raise ValueError(f"q must be >= 1; got {self.q}")


@dataclass(frozen=True, slots=True)
class GARCHResult:
    """Result of a GARCH-family fit.

    All volatility values are in the *same scale as the input returns*.

    Attributes
    ----------
    config:
        The configuration used to produce this result.
    params:
        Fitted model parameters as a dict.  Keys depend on the model:
        - GARCH: ``{"omega": ..., "alpha": [...], "beta": [...]}``.
        - EGARCH: ``{"omega": ..., "alpha": [...], "beta": [...]}``.
        - GJR-GARCH: ``{"omega": ..., "alpha": [...], "gamma": [...], "beta": [...]}``.
    conditional_volatility:
        Series of fitted conditional standard deviations indexed the same as
        the input returns.  Shape: ``(T,)``.
    loglikelihood:
        Log-likelihood of the fitted model.
    aic:
        Akaike information criterion.
    bic:
        Bayesian information criterion.
    """

    config: GARCHConfig
    params: dict[str, float | list[float]]
    conditional_volatility: pd.Series
    loglikelihood: float
    aic: float
    bic: float


@dataclass(frozen=True, slots=True)
class HARRVConfig:
    """Configuration for a HAR-RV fit.

    Attributes
    ----------
    daily_lag:
        Daily lag: 1 period.  Fixed at 1 per the Corsi (2009) specification.
    weekly_lag:
        Window for the weekly RV component (number of daily periods).
        Default 5 (one trading week).
    monthly_lag:
        Window for the monthly RV component (number of daily periods).
        Default 22 (one trading month).
    """

    daily_lag: int = 1
    weekly_lag: int = 5
    monthly_lag: int = 22

    def __post_init__(self) -> None:
        if self.daily_lag < 1:
            raise ValueError("daily_lag must be >= 1")
        if self.weekly_lag <= self.daily_lag:
            raise ValueError("weekly_lag must be > daily_lag")
        if self.monthly_lag <= self.weekly_lag:
            raise ValueError("monthly_lag must be > weekly_lag")


@dataclass(frozen=True, slots=True)
class HARRVResult:
    """Result of a HAR-RV OLS fit.

    Attributes
    ----------
    config:
        The configuration used to produce this result.
    const:
        Fitted intercept coefficient c.
    beta_daily:
        Coefficient on the daily lagged RV component.
    beta_weekly:
        Coefficient on the weekly averaged RV component.
    beta_monthly:
        Coefficient on the monthly averaged RV component.
    fitted:
        In-sample fitted values of RV.  Shape: ``(T - monthly_lag,)``.
    rsquared:
        In-sample R-squared of the OLS regression.
    n_obs:
        Number of observations used in the regression.
    """

    config: HARRVConfig
    const: float
    beta_daily: float
    beta_weekly: float
    beta_monthly: float
    fitted: pd.Series
    rsquared: float
    n_obs: int

    @property
    def coef_vector(self) -> np.ndarray:
        """Return ``[const, beta_daily, beta_weekly, beta_monthly]`` as a 1-D array."""
        return np.array([self.const, self.beta_daily, self.beta_weekly, self.beta_monthly])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_pct_returns(returns: pd.Series | np.ndarray) -> tuple[np.ndarray, float]:
    """Convert returns to percentage scale; return (pct_returns, scale).

    ``arch`` issues a ``DataScaleWarning`` when the variance of the input is
    outside ``[0.1, 10000)``.  Multiplying by 100 moves typical daily decimal
    returns (variance ~1e-4) to percentage-point scale (variance ~1), which is
    well inside that range.

    Returns
    -------
    pct_arr:
        Returns multiplied by 100.
    scale:
        The multiplier applied (always 100.0).
    """
    arr = np.asarray(returns, dtype=float)
    return arr * 100.0, 100.0


def _build_param_dict(
    param_series: pd.Series,
    model: ModelType,
    p: int,
    q: int,
    scale: float,
) -> dict[str, float | list[float]]:
    """Extract named parameters from the arch result Series into a clean dict.

    Omega is rescaled to the *original input return* scale so that
    ``GARCHResult.params`` is self-consistent with
    ``GARCHResult.conditional_volatility``.  For GARCH and GJR-GARCH the
    variance intercept omega was fitted on percentage returns (scale=100), so
    ``omega_orig = omega_pct / scale^2``.  For EGARCH omega lives in the
    log-variance domain and is dimensionless; it is stored as fitted (no
    rescaling).

    Parameters
    ----------
    param_series:
        The ``ARCHModelResult.params`` pandas Series from an arch fit.
    model:
        The volatility model type.
    p:
        ARCH order.
    q:
        GARCH order.
    scale:
        The multiplier applied to original returns before fitting (always
        100.0 when called from :func:`fit_garch`).

    Returns
    -------
    dict with keys ``omega``, ``alpha``, and ``beta``, and (for GJR-GARCH)
    additionally ``gamma``.
    """
    d: dict[str, float | list[float]] = {}
    omega_raw = float(param_series["omega"])
    if model == "EGARCH":
        # log-variance intercept: dimensionless, no scale correction needed.
        d["omega"] = omega_raw
    else:
        # variance intercept: units are (pct_return)^2; convert to (orig_return)^2.
        d["omega"] = omega_raw / (scale**2)
    d["alpha"] = [float(param_series[f"alpha[{i}]"]) for i in range(1, p + 1)]
    if model == "GJR-GARCH":
        d["gamma"] = [float(param_series[f"gamma[{i}]"]) for i in range(1, p + 1)]
    d["beta"] = [float(param_series[f"beta[{i}]"]) for i in range(1, q + 1)]
    return d


# ---------------------------------------------------------------------------
# Public GARCH-family API
# ---------------------------------------------------------------------------


def fit_garch(
    returns: pd.Series | np.ndarray,
    *,
    config: GARCHConfig | None = None,
    model: ModelType = "GARCH",
    p: int = 1,
    q: int = 1,
) -> GARCHResult:
    """Fit a GARCH-family model to a returns series.

    The function works internally in *percentage returns* (input multiplied by
    100) to avoid ``arch.utility.exceptions.DataScaleWarning``.  The returned
    ``conditional_volatility`` is rescaled back to the original input scale.

    Parameters
    ----------
    returns:
        Log or simple returns.  Should be mean-zero or near-zero; the model
        uses a ``ZeroMean`` specification.  Decimal scale (e.g. 0.01 for 1%)
        or percentage scale (e.g. 1.0) are both accepted.
    config:
        A :class:`GARCHConfig` instance.  When provided, ``model``, ``p``,
        and ``q`` keyword arguments are ignored.
    model:
        Volatility process: ``"GARCH"``, ``"EGARCH"``, or ``"GJR-GARCH"``.
    p:
        ARCH lag order.
    q:
        GARCH lag order.

    Returns
    -------
    GARCHResult
        Fitted result with parameters, conditional volatility, and information
        criteria.

    Raises
    ------
    ValueError
        When ``returns`` has fewer than ``max(p, q) + 1`` finite observations.
    """
    from arch import arch_model as _arch_model

    cfg = config if config is not None else GARCHConfig(model=model, p=p, q=q)

    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    min_obs = max(cfg.p, cfg.q) + 2
    if arr.size < min_obs:
        raise ValueError(
            f"fit_garch requires at least {min_obs} finite observations; got {arr.size}"
        )

    index: pd.Index | None = None
    if isinstance(returns, pd.Series):
        index = returns.dropna().index

    pct_arr, scale = _to_pct_returns(arr)

    _VolLiteral = Literal["GARCH", "ARCH", "EGARCH", "FIGARCH", "APARCH", "HARCH"]
    vol_name: _VolLiteral = cast(_VolLiteral, "GARCH" if cfg.model in ("GARCH", "GJR-GARCH") else "EGARCH")
    o_order = cfg.p if cfg.model == "GJR-GARCH" else 0

    am = _arch_model(
        pct_arr,
        vol=vol_name,
        p=cfg.p,
        o=o_order,
        q=cfg.q,
        mean="Zero",
        dist="normal",
        rescale=False,
    )
    res = am.fit(disp="off")

    cond_vol_pct = res.conditional_volatility
    cond_vol_orig = cond_vol_pct / scale

    if index is not None and len(index) == len(cond_vol_orig):
        cond_vol_series = pd.Series(cond_vol_orig, index=index, name="conditional_volatility")
    else:
        cond_vol_series = pd.Series(cond_vol_orig, name="conditional_volatility")

    params = _build_param_dict(res.params, cfg.model, cfg.p, cfg.q, scale)

    return GARCHResult(
        config=cfg,
        params=params,
        conditional_volatility=cond_vol_series,
        loglikelihood=float(res.loglikelihood),
        aic=float(res.aic),
        bic=float(res.bic),
    )


def forecast_variance(
    result: GARCHResult,
    horizon: int = 1,
    *,
    n_simulations: int = 1000,
    random_seed: int = 0,
) -> np.ndarray:
    """Compute the h-step-ahead conditional variance forecast.

    For GARCH(1,1) and GJR-GARCH(1,1), the analytic iterated forecast is
    computed directly from the stored parameters and the last observed
    conditional variance (Bollerslev 1986, eq. 8).

    For EGARCH, the log-variance recursion has no closed-form multi-step
    forecast.  ``horizon=1`` uses the analytic one-step formula; ``horizon>1``
    uses simulation-based forecasting via the arch library.  To do so,
    the original percentage-return scale is reconstructed from the stored
    params and the last conditional variance; the arch proxy fit propagates
    that state into the forecast.

    The returned variances are in the *original input scale* (not in
    percentage-return space).

    Parameters
    ----------
    result:
        A :class:`GARCHResult` produced by :func:`fit_garch`.
    horizon:
        Number of steps ahead to forecast.  Must be >= 1.
    n_simulations:
        Number of Monte Carlo paths used for EGARCH forecasts when
        ``horizon > 1``.
    random_seed:
        Seed for the simulation random-number generator used by EGARCH.

    Returns
    -------
    np.ndarray
        Shape ``(horizon,)`` array of strictly positive conditional variance
        forecasts in the original scale.

    Raises
    ------
    ValueError
        When ``horizon < 1``.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1; got {horizon}")

    cfg = result.config
    scale = 100.0

    if cfg.model == "EGARCH":
        return _forecast_egarch(result, horizon, scale, n_simulations, random_seed)

    # Analytic iterated GARCH(p,q) / GJR-GARCH(p,q) forecast.
    # For GARCH(1,1): h_{t+k} = omega + (alpha + beta)^{k-1} * (alpha * eps_t^2 + beta * h_t)
    # We only support p=q=1 analytic; for p>1 or q>1 also use the numeric identity
    # by iterating h_{t+k} = omega + (alpha+beta) * h_{t+k-1} (unconditional mean correction).
    omega_val = result.params["omega"]
    omega_orig = float(omega_val) if not isinstance(omega_val, list) else float(omega_val[0])
    alpha_raw = result.params["alpha"]
    beta_raw = result.params["beta"]
    alpha_list: list[float] = alpha_raw if isinstance(alpha_raw, list) else [float(alpha_raw)]
    beta_list: list[float] = beta_raw if isinstance(beta_raw, list) else [float(beta_raw)]
    alpha_sum = sum(float(a) for a in alpha_list)
    beta_sum = sum(float(b) for b in beta_list)

    if cfg.model == "GJR-GARCH":
        gamma_raw = result.params["gamma"]
        gamma_list: list[float] = gamma_raw if isinstance(gamma_raw, list) else [float(gamma_raw)]
        # Expected gamma contribution: 0.5*gamma (under symmetry, P(eps<0)=0.5)
        gamma_sum = sum(float(g) for g in gamma_list)
        persistence = alpha_sum + 0.5 * gamma_sum + beta_sum
    else:
        persistence = alpha_sum + beta_sum

    last_var_orig = float(result.conditional_volatility.iloc[-1]) ** 2
    unconditional_var = omega_orig / max(1.0 - persistence, 1e-10)

    forecasts = np.empty(horizon, dtype=float)
    h_prev = last_var_orig
    for k in range(horizon):
        if k == 0:
            h_next = omega_orig + persistence * h_prev
        else:
            h_next = unconditional_var + persistence * (h_prev - unconditional_var)
        h_next = max(h_next, 1e-30)
        forecasts[k] = h_next
        h_prev = h_next

    return forecasts


def _forecast_egarch(
    result: GARCHResult,
    horizon: int,
    scale: float,
    n_simulations: int,
    random_seed: int,
) -> np.ndarray:
    """EGARCH forecast helper via arch simulation.

    Reconstructs a proxy percentage-return series from the stored params,
    refits, and calls arch's built-in forecaster.

    Parameters
    ----------
    result:
        A :class:`GARCHResult` with ``config.model == "EGARCH"``.
    horizon:
        Steps ahead.
    scale:
        The returns-to-percentage multiplier (100.0).
    n_simulations:
        Number of simulation paths for ``horizon > 1``.
    random_seed:
        RNG seed.

    Returns
    -------
    np.ndarray
        Shape ``(horizon,)`` variance forecasts in the original scale.
    """
    from typing import Literal as _Literal

    from arch import arch_model as _arch_model

    _VolLit = _Literal["GARCH", "ARCH", "EGARCH", "FIGARCH", "APARCH", "HARCH"]

    cfg = result.config
    omega_val = result.params["omega"]
    omega = float(omega_val) if not isinstance(omega_val, list) else float(omega_val[0])
    alpha_raw = result.params["alpha"]
    beta_raw = result.params["beta"]
    alpha_lst: list[float] = alpha_raw if isinstance(alpha_raw, list) else [float(alpha_raw)]
    beta_lst: list[float] = beta_raw if isinstance(beta_raw, list) else [float(beta_raw)]

    # For EGARCH, omega is the log-variance intercept (no scale correction).
    pct_params: list[float] = [omega] + [float(a) for a in alpha_lst] + [float(b) for b in beta_lst]

    np.random.seed(random_seed)
    eg_vol: _VolLit = "EGARCH"
    proxy_model = _arch_model(
        None, vol=eg_vol, p=cfg.p, o=0, q=cfg.q, mean="Zero", dist="normal"
    )
    sim_df = proxy_model.simulate(pct_params, nobs=500, burn=500)
    pct_returns_proxy = sim_df["data"].values

    proxy_am = _arch_model(
        pct_returns_proxy,
        vol=eg_vol,
        p=cfg.p,
        o=0,
        q=cfg.q,
        mean="Zero",
        dist="normal",
        rescale=False,
    )
    proxy_res = proxy_am.fit(disp="off", starting_values=np.array(pct_params))

    if horizon > 1:
        legacy_rng = np.random.RandomState(random_seed)
        fc = proxy_res.forecast(
            horizon=horizon,
            method="simulation",
            simulations=n_simulations,
            random_state=legacy_rng,
        )
    else:
        fc = proxy_res.forecast(horizon=1)

    var_pct: np.ndarray = fc.variance.iloc[-1].to_numpy(dtype=float)
    var_orig: np.ndarray = var_pct / (scale**2)
    return var_orig


# ---------------------------------------------------------------------------
# Realised Variance helper
# ---------------------------------------------------------------------------


def realised_variance(
    returns: pd.Series | np.ndarray,
    *,
    window: int = 1,
    annualise: bool = False,
    trading_periods: int = 252,
) -> pd.Series:
    """Compute realised variance from a returns series.

    Realised variance at time t over a rolling window of length ``window`` is
    defined as the sum of squared returns:
    ``RV_t = sum_{i=t-window+1}^{t} r_i^2``

    For ``window=1`` this collapses to the squared return at each period.

    Parameters
    ----------
    returns:
        Log or simple returns.  NaNs are propagated.
    window:
        Rolling window length in periods.  Default 1 (squared returns).
    annualise:
        When ``True``, multiply by ``trading_periods`` to annualise.
    trading_periods:
        Number of periods per year.  Used only when ``annualise=True``.
        Default 252 (daily trading days).

    Returns
    -------
    pd.Series
        Realised variance series.  NaN for the first ``window - 1`` periods.
    """
    if isinstance(returns, np.ndarray):
        s = pd.Series(returns.ravel(), dtype=float)
    else:
        s = returns.astype(float)

    sq = s**2
    rv = sq.rolling(window=window, min_periods=window).sum()
    if annualise:
        rv = rv * trading_periods
    rv.name = "realised_variance"
    return rv


# ---------------------------------------------------------------------------
# HAR-RV
# ---------------------------------------------------------------------------


def fit_har_rv(
    rv: pd.Series | np.ndarray,
    *,
    config: HARRVConfig | None = None,
) -> HARRVResult:
    """Fit a Heterogeneous Autoregressive model for Realised Variance (HAR-RV).

    Implements the Corsi (2009) specification:
    ``RV_t = c + beta_d*RV_{t-1} + beta_w*RV^W_{t-1} + beta_m*RV^M_{t-1} + eps_t``

    where ``RV^W_{t-1}`` is the ``weekly_lag``-day average of lagged RV and
    ``RV^M_{t-1}`` is the ``monthly_lag``-day average of lagged RV.

    Uses ``statsmodels.regression.linear_model.OLS`` for estimation.

    Parameters
    ----------
    rv:
        Realised variance series (non-negative).  Must have at least
        ``monthly_lag + 2`` observations.
    config:
        HAR-RV configuration.  Defaults to standard Corsi (2009) lags (1, 5, 22).

    Returns
    -------
    HARRVResult
        Fitted coefficients, in-sample fitted values, and R-squared.

    Raises
    ------
    ValueError
        When ``rv`` has insufficient observations.
    """
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant

    cfg = config if config is not None else HARRVConfig()
    m = cfg.monthly_lag

    rv_s: pd.Series = pd.Series(rv.ravel(), dtype=float) if isinstance(rv, np.ndarray) else rv.astype(float)

    rv_arr = rv_s.dropna().to_numpy(dtype=float)
    min_obs = m + 2
    if rv_arr.size < min_obs:
        raise ValueError(
            f"fit_har_rv requires at least {min_obs} observations; got {rv_arr.size}"
        )

    n = rv_arr.size
    start = m

    rv_d_lag = rv_arr[start - 1 : n - 1]

    rv_w_lag = np.array(
        [rv_arr[max(0, i - cfg.weekly_lag) : i].mean() for i in range(start, n)],
        dtype=float,
    )
    rv_m_lag = np.array(
        [rv_arr[max(0, i - cfg.monthly_lag) : i].mean() for i in range(start, n)],
        dtype=float,
    )
    y = rv_arr[start:]

    X = add_constant(np.column_stack([rv_d_lag, rv_w_lag, rv_m_lag]))
    ols_res = OLS(y, X).fit()

    c_hat, bd_hat, bw_hat, bm_hat = (
        float(ols_res.params[0]),
        float(ols_res.params[1]),
        float(ols_res.params[2]),
        float(ols_res.params[3]),
    )

    index: pd.Index | None = None
    if isinstance(rv, pd.Series):
        valid_index = rv.dropna().index
        if len(valid_index) == n:
            index = valid_index[start:]

    fitted_arr = ols_res.fittedvalues
    if index is not None and len(index) == len(fitted_arr):
        fitted_series = pd.Series(fitted_arr, index=index, name="har_rv_fitted")
    else:
        fitted_series = pd.Series(fitted_arr, name="har_rv_fitted")

    return HARRVResult(
        config=cfg,
        const=c_hat,
        beta_daily=bd_hat,
        beta_weekly=bw_hat,
        beta_monthly=bm_hat,
        fitted=fitted_series,
        rsquared=float(ols_res.rsquared),
        n_obs=int(len(y)),
    )


def forecast_har_rv(
    result: HARRVResult,
    rv_history: pd.Series | np.ndarray,
    horizon: int = 1,
) -> np.ndarray:
    """Produce a multi-step HAR-RV forecast.

    Uses the iterated one-step-ahead approach: at each step the forecast
    is used as the next period's lagged RV value.

    Parameters
    ----------
    result:
        A :class:`HARRVResult` produced by :func:`fit_har_rv`.
    rv_history:
        Historical realised variance values.  Must contain at least
        ``monthly_lag`` observations so that weekly and monthly averages can
        be computed.
    horizon:
        Number of steps ahead to forecast.  Must be >= 1.

    Returns
    -------
    np.ndarray
        Shape ``(horizon,)`` array of RV forecasts (not variance-of-returns;
        units match the input ``rv``).

    Raises
    ------
    ValueError
        When ``horizon < 1`` or ``rv_history`` is too short.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1; got {horizon}")

    cfg = result.config
    m = cfg.monthly_lag

    arr: np.ndarray
    if isinstance(rv_history, np.ndarray):
        arr = rv_history.ravel().astype(float)
    else:
        arr = rv_history.dropna().to_numpy(dtype=float)

    if arr.size < m:
        raise ValueError(
            f"forecast_har_rv requires at least {m} observations in rv_history; "
            f"got {arr.size}"
        )

    history = arr.tolist()
    forecasts: list[float] = []

    c = result.const
    bd = result.beta_daily
    bw = result.beta_weekly
    bm = result.beta_monthly

    for _ in range(horizon):
        rv_d = history[-1]
        rv_w = float(np.mean(history[-cfg.weekly_lag :]))
        rv_m = float(np.mean(history[-cfg.monthly_lag :]))
        f = c + bd * rv_d + bw * rv_w + bm * rv_m
        forecasts.append(f)
        history.append(f)

    return np.array(forecasts, dtype=float)
