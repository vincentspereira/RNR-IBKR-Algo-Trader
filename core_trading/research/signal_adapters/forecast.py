"""ARIMA one-step-forecast directional signal adapter (Phase 5 DOD application).

Wires the already-shipped ARIMA fitter
(:func:`core_trading.signals.timeseries.arima.fit_arima`) through the standard
signal-evaluation gate
(:func:`core_trading.research.signal_evaluation.evaluate_signal`), closing DOD
items 3-5 (backtest run + deflated Sharpe + PROMOTE/ARCHIVE verdict) for a
one-step-ahead directional signal based on a rolling ARIMA model of log-returns.

How it works
------------
An AR(p) model (ARIMA order ``(p, 0, 0)``) is fit on a trailing window of
log-returns ending at bar t.  The model's one-step-ahead forecast (the predicted return at t+1) is
normalised by a trailing standard deviation of realised returns so that the
signal is scale-free.  A threshold on this standardised forecast determines the
direction of the position: go long when the forecast exceeds +entry, go short
when it is below -entry, otherwise stay flat.

Look-ahead-free design
----------------------
The expensive computation (rolling SARIMAX fits, one per ``refit_every`` bars)
is performed ONCE in :func:`forecast_signal_series`.  Between refit bars the
stale AR coefficients are applied to the CURRENT returns at each bar to produce
a proper one-step-ahead forecast -- this is look-ahead-free because the
coefficients were estimated from past data only and the current return r[t] is
in-sample (known at bar t when forecasting r[t+1]).

Specifically, for an AR(p) model with estimated coefficients (phi_1, ..., phi_p)
the forecast at bar t is::

    forecast(r[t+1]) = phi_1 * r[t] + phi_2 * r[t-1] + ... + phi_p * r[t-p+1]

This is evaluated at every bar using the stale coefficients from the most recent
refit, so the forecast updates each bar (responding to new returns) without
requiring an expensive SARIMAX solve.  Truncation to any prefix of the series
yields exactly the same signal values for the overlapping region.

Performance note
----------------
Rolling SARIMAX fits are slow (each call to :func:`fit_arima` is O(lookback *
SARIMAX-solve)).  Keep ``refit_every`` >= 20 and series lengths <= ~1500 bars
for test suites.  The default ``refit_every=20`` is 20x cheaper than per-bar
refitting.

Mathematical references
-----------------------
* Box, G.E.P. and Jenkins, G.M. (1970). "Time Series Analysis: Forecasting and
  Control." Holden-Day.  (ARIMA one-step-ahead forecast, the classic reference.)
* Bailey, D. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting
  for Selection Bias, Backtest Overfitting, and Non-Normality." Journal of
  Portfolio Management 40(5).  (Deflated Sharpe gate.)
* One-step-ahead forecast trading rule: fit AR(p) on returns -> sign of predicted
  return gives the directional trade (momentum / mean-reversion depending on
  the AR coefficient sign).
"""
from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from core_trading.research.signal_evaluation import positions_to_weights
from core_trading.signals.timeseries.arima import fit_arima

__all__ = [
    "forecast_signal_series",
    "forecast_positions",
    "build_forecast_weight_fn",
    "forecast_grid",
]

# A weight rule maps (price panel, parameter configuration) -> target weights.
WeightRule = Callable[[pd.DataFrame, Mapping[str, float]], pd.DataFrame]


def forecast_signal_series(
    close: pd.Series,
    *,
    order: tuple[int, int, int] = (1, 0, 0),
    lookback: int = 250,
    refit_every: int = 20,
) -> pd.DataFrame:
    """Look-ahead-free ARIMA one-step-ahead standardised forecast series.

    At each refit bar ``t`` (warmup permitting) an ARIMA(p,d,q) model is fit on
    the trailing window of log-returns ending at ``t`` via
    :func:`core_trading.signals.timeseries.arima.fit_arima`.  The AR
    coefficients (phi_1, ..., phi_p) extracted from the fitted model are then
    applied at EVERY subsequent bar (until the next refit) to produce the
    one-step-ahead forecast::

        forecast(r[t+1]) = phi_1 * r[t] + phi_2 * r[t-1] + ... + phi_p * r[t-p+1]

    This lets the forecast respond to new incoming returns each bar without
    triggering an expensive SARIMAX solve.  The raw forecast is then divided by
    a trailing standard deviation of realised log-returns (expanding window,
    using only data available at ``t``) to produce a scale-free signal.

    Look-ahead-freedom is guaranteed because:

    * the ARIMA fit uses only returns ``r[t - lookback + 1 : t + 1]``;
    * the AR-coefficient application uses only returns ``r[t-p+1], ..., r[t]``;
    * the trailing std uses only returns ``r[1 : t + 1]``;
    * no information from ``t+1`` or later enters the signal at bar ``t``.

    Truncation to any prefix ``close.iloc[:k]`` yields the same signal values
    at indices ``< k`` as the full-series computation (the refit schedule is
    deterministic from bar 0).

    Parameters
    ----------
    close:
        Price series (strictly positive).
    order:
        Pure AR order ``(p, 0, 0)`` passed to :func:`fit_arima`.  Only the
        autoregressive part is supported (see Raises); the differencing ``d`` and
        moving-average ``q`` terms must both be 0.
    lookback:
        Length of the trailing return window used for fitting (must be >= 60).
        Also the warm-up length before the first forecast can be emitted.
    refit_every:
        Number of bars between successive SARIMAX solves (must be >= 1).  The
        AR coefficients from the last refit are applied at every bar between
        refits to produce fresh forecasts.  Larger values are much faster;
        default 20 is recommended for test suites.

    Returns
    -------
    pd.DataFrame
        Single column ``signal`` (standardised one-step forecast) indexed like
        ``close``; values are NaN during the warmup period and where no valid
        model exists.

    Raises
    ------
    ValueError
        If ``lookback < 60``, ``refit_every < 1``, or ``order`` has a non-zero
        differencing (``d``) or moving-average (``q``) term.
    """
    if lookback < 60:
        raise ValueError("lookback must be >= 60 for a stable ARIMA estimate")
    if refit_every < 1:
        raise ValueError("refit_every must be >= 1")

    p, d_int, q = order
    if d_int != 0 or q != 0:
        raise ValueError(
            "forecast_signal_series supports pure AR(p, 0, 0) orders only: the "
            "fast per-bar recursion applies the fitted AR coefficients directly "
            "and cannot represent the differencing (d) or moving-average (q) "
            f"terms in order={order!r}"
        )
    prices = np.asarray(close.to_numpy(), dtype=float)
    n = prices.size

    # Log-returns: log_ret[t] = log(close[t] / close[t-1]), defined from index 1.
    # log_ret[0] is NaN.  All ARIMA fitting and forecasting works on log_ret.
    log_ret = np.full(n, np.nan, dtype=float)
    log_ret[1:] = np.log(prices[1:] / prices[:-1])

    signal = np.full(n, np.nan, dtype=float)

    # Stale AR coefficients extracted from the last SARIMAX fit.
    # ar_coefs[k] is the coefficient for lag k+1 (k=0 -> lag 1).
    # For an AR(p) model: forecast(r[t+1]) = sum_{k=0}^{p-1} ar_coefs[k] * r[t-k]
    # This is re-evaluated at EVERY bar using the stale coefficients, so the
    # forecast responds to new returns without requiring a new SARIMAX solve.
    ar_coefs: np.ndarray = np.empty(0, dtype=float)
    has_model = False

    bars_since_fit = refit_every  # force a fit on the first eligible bar

    for t in range(lookback, n):
        # Step 1: decide whether to refit on this bar (expensive).
        if bars_since_fit >= refit_every:
            window = log_ret[t - lookback + 1 : t + 1]
            # window[0] corresponds to log_ret[t-lookback+1] which is finite
            # when t >= lookback >= 60 (log_ret[0]=NaN is excluded for lookback>0).
            if np.isfinite(window).all():
                try:
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", module="statsmodels")
                        result = fit_arima(
                            pd.Series(window),
                            order=order,
                            seasonal_order=(0, 0, 0, 0),
                            trend="n",
                        )
                    # Extract AR coefficients from the fitted parameter dict.
                    # statsmodels names them "ar.L1", "ar.L2", ..., "ar.Lp".
                    new_coefs = np.zeros(max(p, 1), dtype=float)
                    for lag in range(1, p + 1):
                        key = f"ar.L{lag}"
                        if key in result.params:
                            new_coefs[lag - 1] = float(result.params[key])
                    ar_coefs = new_coefs
                    has_model = True
                except Exception:  # noqa: BLE001
                    # Carry stale coefficients on convergence failure.
                    pass
            bars_since_fit = 0
        else:
            bars_since_fit += 1

        if not has_model:
            continue

        # Step 2: compute the one-step-ahead forecast at bar t using the stale
        # AR coefficients applied to the most recent p returns ending at t.
        # forecast(r[t+1]) = sum_{k=1}^{p} phi_k * r[t-k+1]
        # This uses only data available at or before bar t -> look-ahead-free.
        p_eff = len(ar_coefs)
        recent_returns = log_ret[t - p_eff + 1 : t + 1]  # r[t-p+1], ..., r[t]
        if not np.isfinite(recent_returns).all():
            continue
        # Dot product: phi_1*r[t] + phi_2*r[t-1] + ... (ar_coefs order: lag1 first)
        raw_fc = float(np.dot(ar_coefs, recent_returns[::-1]))

        # Step 3: standardise by trailing std of log_ret up to t (look-ahead-free).
        # Use nanstd so that any embedded NaN prices in earlier bars do not
        # permanently corrupt the standardisation once the NaN is out of the
        # recent-returns window.
        trailing_std = float(np.nanstd(log_ret[1 : t + 1], ddof=1))
        if trailing_std <= 0.0 or not np.isfinite(trailing_std):
            continue
        signal[t] = raw_fc / trailing_std

    return pd.DataFrame({"signal": signal}, index=close.index)


def forecast_positions(
    signal: pd.Series,
    *,
    entry: float = 0.25,
) -> pd.Series:
    """Convert a standardised forecast signal into a {-1, 0, +1} position series.

    Go long (+1) when the standardised forecast exceeds ``+entry`` (predicted
    positive return), go short (-1) when it is below ``-entry`` (predicted
    negative return), otherwise stay flat (0).  NaN signal values map to 0.

    Parameters
    ----------
    signal:
        Standardised one-step forecast series from :func:`forecast_signal_series`.
    entry:
        Entry threshold (must be >= 0).  A threshold of 0 trades every bar with
        a finite signal; higher values filter out weak forecasts.

    Returns
    -------
    pd.Series
        Position in ``{-1.0, 0.0, 1.0}`` indexed like ``signal``.

    Raises
    ------
    ValueError
        If ``entry < 0``.
    """
    if entry < 0:
        raise ValueError("entry threshold must be >= 0")

    values = np.asarray(signal.to_numpy(), dtype=float)
    positions = np.where(
        ~np.isfinite(values),
        0.0,
        np.where(values > entry, 1.0, np.where(values < -entry, -1.0, 0.0)),
    )
    return pd.Series(positions, index=signal.index, name="position")


def build_forecast_weight_fn(
    close: pd.Series,
    *,
    symbol: str = "SIM",
    order: tuple[int, int, int] = (1, 0, 0),
    lookback: int = 250,
    refit_every: int = 20,
) -> WeightRule:
    """Build a :data:`WeightRule` for the ARIMA one-step-forecast directional rule.

    The expensive rolling SARIMAX computation is performed ONCE here (via
    :func:`forecast_signal_series`).  The returned closure applies only the
    cheap threshold logic (via :func:`forecast_positions`) for each parameter
    configuration in the grid sweep, so all configurations reuse the same
    pre-computed signal series.

    Parameters
    ----------
    close:
        Price series used to compute the signal.
    symbol:
        Symbol label for the weight column (must match the panel symbol).
    order:
        ARIMA (p, d, q) order; see :func:`forecast_signal_series`.
    lookback:
        Trailing return window length; see :func:`forecast_signal_series`.
    refit_every:
        Refit interval; see :func:`forecast_signal_series`.

    Returns
    -------
    WeightRule
        Callable ``(panel, params) -> weight_frame``.  Each ``params`` dict
        must contain ``"entry"`` (float >= 0).
    """
    sig_df = forecast_signal_series(close, order=order, lookback=lookback, refit_every=refit_every)

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        positions = forecast_positions(sig_df["signal"], entry=params["entry"])
        # Defensively align positions onto the panel's own per-symbol timestamp
        # index.  The signal was computed from ``close`` whose index may differ
        # from the panel's MultiIndex; both carry the same chronological
        # observations in the same order, so positional reindex is correct and
        # prevents a silent all-zero misalignment.
        sym_index = panel.xs(symbol, level="symbol").index
        if len(sym_index) == len(positions):
            positions = pd.Series(
                positions.to_numpy(), index=sym_index, name="position"
            )
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


def forecast_grid(
    *,
    entries: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 0.75),
) -> list[dict[str, float]]:
    """Standard entry-threshold grid for the ARIMA forecast sweep.

    Returns one configuration per entry threshold value.  At least five
    configurations are supplied by default so the deflated Sharpe corrects
    meaningfully for selection bias.

    Parameters
    ----------
    entries:
        Iterable of entry threshold values (>= 0).

    Returns
    -------
    list[dict[str, float]]
        Each dict contains a single key ``"entry"``.
    """
    return [{"entry": float(e)} for e in entries]
