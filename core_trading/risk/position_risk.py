"""Position-level risk measures (Phase 7, module 7.2).

Provides four families of position-level risk tools that feed the daily risk
report (PositionRiskSnapshot):

1. Stop-losses -- absolute-%, ATR-based, and volatility-based stop levels
   for long and short positions, plus a checker that evaluates whether any
   stop has been hit on a given price path.

2. Trailing stops -- high-watermark trailing by % or ATR multiple.

3. Position-level VaR contribution -- Euler decomposition of parametric
   portfolio VaR into marginal and component VaR per position (Jorion 2006).

4. Option Greeks -- BSM greeks for European calls/puts with continuous
   dividend yield (Merton 1973).

ATR implementation
------------------
Wilder (1978) smoothing: ATR_t = ATR_{t-1}*(1-1/n) + TR_t*(1/n).
Seeded with mean(TR[1..n]).  Equivalent to EWM with com=n-1 (alpha=1/n).

ATR reuse decision: existing ATR helpers are all private strategy methods
(TurtleTradingStrategy._calculate_atr, SupertrendStrategy._calculate_atr,
feature_store._atr, risk_management_utils.calculate_atr).  None are
importable as a public risk-layer utility with type annotations.
Therefore wilder_atr is implemented here.

Sign convention: VaR is a positive loss fraction (core_trading.risk.var).

Mathematical references
-----------------------
Wilder, J.W. (1978). New Concepts in Technical Trading Systems. Trend Research.
Jorion, P. (2006). Value at Risk. 3rd ed. McGraw-Hill. Chapter 7.
Black, F. & Scholes, M. (1973). Journal of Political Economy, 81, 637-654.
Merton, R.C. (1973). Bell Journal of Economics, 4, 141-183.
Hull, J.C. (2022). Options, Futures, and Other Derivatives. 11th ed. Pearson.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import scipy.stats as _st

__all__ = [
    "StopLevel",
    "StopHitResult",
    "absolute_stop",
    "atr_stop",
    "volatility_stop",
    "check_stop_hit",
    "wilder_atr",
    "TrailingStopResult",
    "trailing_stop",
    "ComponentVaRResult",
    "component_var",
    "GreeksResult",
    "PositionGreeksResult",
    "bsm_greeks",
    "position_greeks",
    "PositionRiskSnapshot",
    "build_snapshot",
]


# ---------------------------------------------------------------------------
# Section 1: Stop-losses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StopLevel:
    """Stop price for a single position."""

    entry: float
    stop: float
    direction: Literal["long", "short"]
    method: Literal["absolute", "atr", "volatility"]
    distance_pct: float


@dataclass(frozen=True, slots=True)
class StopHitResult:
    """Result of check_stop_hit."""

    hit: bool
    hit_index: int | None
    stop: StopLevel


def absolute_stop(
    entry: float,
    pct: float,
    direction: Literal["long", "short"] = "long",
) -> StopLevel:
    """Compute a fixed-percentage stop level.

    stop_long  = entry * (1 - pct)
    stop_short = entry * (1 + pct)
    """
    if entry <= 0.0:
        raise ValueError(f"entry must be > 0; got {entry!r}")
    if not (0.0 < pct < 1.0):
        raise ValueError(f"pct must be in (0, 1); got {pct!r}")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short'; got {direction!r}")
    stop = entry * (1.0 - pct) if direction == "long" else entry * (1.0 + pct)
    return StopLevel(
        entry=entry,
        stop=stop,
        direction=direction,
        method="absolute",
        distance_pct=abs(entry - stop) / entry,
    )


def atr_stop(
    entry: float,
    atr_value: float,
    multiplier: float = 2.0,
    direction: Literal["long", "short"] = "long",
) -> StopLevel:
    """Compute an ATR-based stop level (Wilder 1978).

    stop_long  = entry - k * ATR
    stop_short = entry + k * ATR
    """
    if entry <= 0.0:
        raise ValueError(f"entry must be > 0; got {entry!r}")
    if atr_value <= 0.0:
        raise ValueError(f"atr_value must be > 0; got {atr_value!r}")
    if multiplier <= 0.0:
        raise ValueError(f"multiplier must be > 0; got {multiplier!r}")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short'; got {direction!r}")
    offset = multiplier * atr_value
    stop = entry - offset if direction == "long" else entry + offset
    return StopLevel(
        entry=entry,
        stop=stop,
        direction=direction,
        method="atr",
        distance_pct=abs(entry - stop) / entry,
    )


def volatility_stop(
    entry: float,
    sigma: float,
    multiplier: float = 2.0,
    horizon: int = 1,
    direction: Literal["long", "short"] = "long",
) -> StopLevel:
    """Compute a volatility-based stop level.

    stop_long  = entry - k * sigma * sqrt(h) * entry
    stop_short = entry + k * sigma * sqrt(h) * entry

    sigma is per-period vol fraction (e.g. 0.015 for 1.5% daily).
    """
    if entry <= 0.0:
        raise ValueError(f"entry must be > 0; got {entry!r}")
    if sigma <= 0.0:
        raise ValueError(f"sigma must be > 0; got {sigma!r}")
    if multiplier <= 0.0:
        raise ValueError(f"multiplier must be > 0; got {multiplier!r}")
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1; got {horizon!r}")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short'; got {direction!r}")
    offset = multiplier * sigma * math.sqrt(horizon) * entry
    stop = entry - offset if direction == "long" else entry + offset
    return StopLevel(
        entry=entry,
        stop=stop,
        direction=direction,
        method="volatility",
        distance_pct=abs(entry - stop) / entry,
    )


def check_stop_hit(
    prices: np.ndarray | pd.Series,
    stop: StopLevel,
) -> StopHitResult:
    """Check whether a stop level is hit on a price path.

    Long: hit when any price <= stop.stop.
    Short: hit when any price >= stop.stop.
    """
    arr = np.asarray(prices, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError("prices must be non-empty.")
    breached = arr <= stop.stop if stop.direction == "long" else arr >= stop.stop
    indices = np.flatnonzero(breached)
    if indices.size > 0:
        return StopHitResult(hit=True, hit_index=int(indices[0]), stop=stop)
    return StopHitResult(hit=False, hit_index=None, stop=stop)



# ---------------------------------------------------------------------------
# Section 2: Wilder ATR helper
# ---------------------------------------------------------------------------


def wilder_atr(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """Compute Wilder (1978) Average True Range.

    TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

    ATR seeded with mean(TR[1..period]) then Wilder smoothing (alpha=1/period):
        ATR[t] = ATR[t-1]*(1-1/period) + TR[t]*(1/period)

    Returns array length T; first period values are NaN.

    Parameters
    ----------
    high, low, close : array-like
        OHLC arrays length T.  close[0] is the previous close bar.
    period : int
        Smoothing period.  Must be >= 2.
    """
    h = np.asarray(high, dtype=float).ravel()
    lo = np.asarray(low, dtype=float).ravel()
    c = np.asarray(close, dtype=float).ravel()
    n = len(h)
    if not (len(lo) == len(c) == n):
        raise ValueError(
            f"high, low, close must have the same length; "
            f"got {n}, {len(lo)}, {len(c)}."
        )
    if period < 2:
        raise ValueError(f"period must be >= 2; got {period!r}")
    if n < period + 1:
        raise ValueError(
            f"Need at least period+1 = {period + 1} bars; got {n}."
        )
    tr = np.empty(n, dtype=float)
    tr[0] = float("nan")
    tr[1:] = np.maximum(
        h[1:] - lo[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])),
    )
    atr = np.full(n, float("nan"), dtype=float)
    atr[period] = float(np.mean(tr[1 : period + 1]))
    alpha = 1.0 / period
    for t in range(period + 1, n):
        atr[t] = atr[t - 1] * (1.0 - alpha) + tr[t] * alpha
    return atr



# ---------------------------------------------------------------------------
# Section 3: Trailing stops
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrailingStopResult:
    """Result of trailing_stop."""

    stop_path: np.ndarray = field(compare=False)
    hit: bool
    hit_index: int | None
    direction: Literal["long", "short"]
    method: Literal["pct", "atr"]
    initial_stop: float


def trailing_stop(
    prices: np.ndarray | pd.Series,
    *,
    direction: Literal["long", "short"] = "long",
    pct: float | None = None,
    atr_values: np.ndarray | pd.Series | None = None,
    atr_multiplier: float = 2.0,
) -> TrailingStopResult:
    """Compute a high-watermark trailing stop over a price series.

    Pct mode:
        hwm_t  = max(prices[0..t]);  stop_t = hwm_t * (1 - pct)  for long
        lwm_t  = min(prices[0..t]);  stop_t = lwm_t * (1 + pct)  for short

    ATR mode:
        stop_t = hwm_t - atr_multiplier * atr[t]  for long
        stop_t = lwm_t + atr_multiplier * atr[t]  for short

    The stop never moves against the position.  NaN ATR values are
    forward-filled from the last valid value.

    Parameters
    ----------
    prices : array-like
        1-D chronological price series.  Must be non-empty.
    direction : str
        "long" or "short".
    pct : float or None
        Trailing percentage.  Exactly one of pct/atr_values required.
    atr_values : array-like or None
        ATR series aligned with prices.
    atr_multiplier : float
        ATR multiple.  Must be > 0.
    """
    if (pct is None) == (atr_values is None):
        raise ValueError(
            "Provide exactly one of pct or atr_values, not both or neither."
        )
    arr = np.asarray(prices, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError("prices must be non-empty.")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short'; got {direction!r}")
    n = arr.size
    if pct is not None:
        if not (0.0 < pct < 1.0):
            raise ValueError(f"pct must be in (0, 1); got {pct!r}")
        method: Literal["pct", "atr"] = "pct"
        stop_path = _trailing_stop_pct(arr, pct=pct, direction=direction)
    else:
        atr_arr = np.asarray(atr_values, dtype=float).ravel()
        if atr_arr.size != n:
            raise ValueError(
                f"atr_values length {atr_arr.size} != prices length {n}."
            )
        if atr_multiplier <= 0.0:
            raise ValueError(f"atr_multiplier must be > 0; got {atr_multiplier!r}")
        method = "atr"
        stop_path = _trailing_stop_atr(
            arr, atr_values=atr_arr, multiplier=atr_multiplier, direction=direction
        )
    initial_stop = float(stop_path[0])
    breached = arr <= stop_path if direction == "long" else arr >= stop_path
    idx_arr = np.flatnonzero(breached)
    if idx_arr.size > 0:
        return TrailingStopResult(
            stop_path=stop_path,
            hit=True,
            hit_index=int(idx_arr[0]),
            direction=direction,
            method=method,
            initial_stop=initial_stop,
        )
    return TrailingStopResult(
        stop_path=stop_path,
        hit=False,
        hit_index=None,
        direction=direction,
        method=method,
        initial_stop=initial_stop,
    )


def _trailing_stop_pct(
    prices: np.ndarray,
    *,
    pct: float,
    direction: Literal["long", "short"],
) -> np.ndarray:
    n = prices.size
    stop_path = np.empty(n, dtype=float)
    if direction == "long":
        hwm = prices[0]
        stop_path[0] = hwm * (1.0 - pct)
        for t in range(1, n):
            if prices[t] > hwm:
                hwm = prices[t]
            new_stop = hwm * (1.0 - pct)
            stop_path[t] = max(stop_path[t - 1], new_stop)
    else:
        lwm = prices[0]
        stop_path[0] = lwm * (1.0 + pct)
        for t in range(1, n):
            if prices[t] < lwm:
                lwm = prices[t]
            new_stop = lwm * (1.0 + pct)
            stop_path[t] = min(stop_path[t - 1], new_stop)
    return stop_path


def _trailing_stop_atr(
    prices: np.ndarray,
    *,
    atr_values: np.ndarray,
    multiplier: float,
    direction: Literal["long", "short"],
) -> np.ndarray:
    n = prices.size
    stop_path = np.empty(n, dtype=float)
    atr_clean = np.empty(n, dtype=float)
    last_valid = 0.0
    for i in range(n):
        if np.isfinite(atr_values[i]):
            last_valid = float(atr_values[i])
        atr_clean[i] = last_valid
    if direction == "long":
        hwm = prices[0]
        stop_path[0] = hwm - multiplier * atr_clean[0]
        for t in range(1, n):
            if prices[t] > hwm:
                hwm = prices[t]
            new_stop = hwm - multiplier * atr_clean[t]
            stop_path[t] = max(stop_path[t - 1], new_stop)
    else:
        lwm = prices[0]
        stop_path[0] = lwm + multiplier * atr_clean[0]
        for t in range(1, n):
            if prices[t] < lwm:
                lwm = prices[t]
            new_stop = lwm + multiplier * atr_clean[t]
            stop_path[t] = min(stop_path[t - 1], new_stop)
    return stop_path



# ---------------------------------------------------------------------------
# Section 4: Component VaR (Euler decomposition)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComponentVaRResult:
    """Per-asset component VaR via Euler decomposition (Jorion 2006, ch. 7).

    All VaR values are positive loss fractions (consistent with
    core_trading.risk.var sign convention).

    Attributes
    ----------
    portfolio_var : float
        Total parametric portfolio VaR (positive loss fraction).
    marginal_var : np.ndarray
        Shape (N,).  mVaR_i = z_alpha * (Sigma @ w)[i] / sigma_p.
    component_var : np.ndarray
        Shape (N,).  CVaR_i = w[i] * mVaR_i.
        sum(component_var) == portfolio_var by Euler homogeneity.
    assets : list[str]
        Asset labels.
    confidence : float
        Confidence level used.
    """

    portfolio_var: float
    marginal_var: np.ndarray = field(compare=False)
    component_var: np.ndarray = field(compare=False)
    assets: list[str]
    confidence: float


def component_var(
    weights: np.ndarray,
    cov: np.ndarray,
    *,
    confidence: float = 0.95,
    assets: list[str] | None = None,
) -> ComponentVaRResult:
    """Compute marginal and component VaR via Euler decomposition.

    sigma_p = sqrt(w @ Sigma @ w)
    VaR_p   = z_alpha * sigma_p  where z_alpha = norm.ppf(confidence) > 0

    mVaR_i = z_alpha * (Sigma @ w)[i] / sigma_p  (Jorion 2006, eq. 7.11)
    CVaR_i = w[i] * mVaR_i                        (Jorion 2006, eq. 7.13)
    sum(CVaR) = VaR_p  by Euler homogeneity.

    Parameters
    ----------
    weights : array-like
        Portfolio weights, shape (N,).  Negatives (shorts) allowed.
    cov : array-like
        Covariance matrix, shape (N, N).  Must be PSD.
    confidence : float
        Confidence level in (0, 1).  Default 0.95.
    assets : list or None
        Asset labels.  None yields ["A0", "A1", ...].
    """
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1); got {confidence!r}")
    w = np.asarray(weights, dtype=float).ravel()
    c = np.asarray(cov, dtype=float)
    n = w.shape[0]
    if c.ndim != 2 or c.shape != (n, n):
        raise ValueError(f"cov must be shape ({n}, {n}); got {c.shape}.")
    port_variance = float(w @ c @ w)
    if port_variance < -1e-12:
        raise ValueError(
            f"Portfolio variance = {port_variance:.6g} < 0; "
            "cov must be positive semidefinite."
        )
    port_variance = max(port_variance, 0.0)
    sigma_p = math.sqrt(port_variance)
    z_alpha = float(_st.norm.ppf(confidence))
    if sigma_p == 0.0:
        mvars: np.ndarray = np.zeros(n, dtype=float)
        cvars: np.ndarray = np.zeros(n, dtype=float)
        port_var_scalar = 0.0
    else:
        cov_iw = c @ w
        mvars = z_alpha * cov_iw / sigma_p
        cvars = w * mvars
        port_var_scalar = z_alpha * sigma_p
    if assets is None:
        asset_labels = [f"A{i}" for i in range(n)]
    else:
        if len(assets) != n:
            raise ValueError(
                f"assets has {len(assets)} labels but weights has {n} elements."
            )
        asset_labels = list(assets)
    return ComponentVaRResult(
        portfolio_var=port_var_scalar,
        marginal_var=mvars,
        component_var=cvars,
        assets=asset_labels,
        confidence=confidence,
    )



# ---------------------------------------------------------------------------
# Section 5: Option Greeks (Black-Scholes-Merton)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GreeksResult:
    """Analytic BSM greeks for a single European option.

    References: Black-Scholes (1973), Merton (1973), Hull (2022) ch. 19.

    Attributes
    ----------
    delta : float
        dV/dS.  Call in (0, 1); put in (-1, 0).
    gamma : float
        d2V/dS2.  Always >= 0; identical for calls and puts.
    vega : float
        dV/d(sigma) per 1.0 sigma unit.  Identical for calls and puts.
    theta : float
        dV/dt per calendar day.  Typically negative for long options.
    rho : float
        dV/dr per 1.0 rate unit.
    option_price : float
        BSM option price.
    option_type : str
        "call" or "put".
    d1 : float
        BSM d1 parameter.
    d2 : float
        BSM d2 parameter.
    """

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    option_price: float
    option_type: Literal["call", "put"]
    d1: float
    d2: float


@dataclass(frozen=True, slots=True)
class PositionGreeksResult:
    """Greeks scaled by position size (quantity * multiplier).

    Attributes
    ----------
    per_contract : GreeksResult
        Single-contract greeks.
    position_delta : float
        quantity * multiplier * delta.
    position_gamma : float
        quantity * multiplier * gamma.
    position_vega : float
        quantity * multiplier * vega.
    position_theta : float
        quantity * multiplier * theta.
    position_rho : float
        quantity * multiplier * rho.
    quantity : float
        Signed contracts (positive = long, negative = short).
    multiplier : float
        Contract multiplier (default 100).
    """

    per_contract: GreeksResult
    position_delta: float
    position_gamma: float
    position_vega: float
    position_theta: float
    position_rho: float
    quantity: float
    multiplier: float


def bsm_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    option_type: Literal["call", "put"] = "call",
) -> GreeksResult:
    """Compute BSM analytic greeks for a European option.

    Merton (1973) extension for continuous dividend yield q.
    When q=0 reduces to Black-Scholes (1973).

    Formulas (Hull 2022, ch. 19 and 21):
        d1 = [ln(S/K) + (r-q+sigma^2/2)*T] / (sigma*sqrt(T))
        d2 = d1 - sigma*sqrt(T)
        call = S*exp(-qT)*N(d1) - K*exp(-rT)*N(d2)
        put  = K*exp(-rT)*N(-d2) - S*exp(-qT)*N(-d1)
        delta_call = exp(-qT)*N(d1)
        delta_put  = exp(-qT)*(N(d1)-1)
        gamma      = exp(-qT)*n(d1)/(S*sigma*sqrt(T))
        vega       = S*exp(-qT)*n(d1)*sqrt(T)
        theta_call = [-S*exp(-qT)*n(d1)*sigma/(2*sqrt(T))
                      - r*K*exp(-rT)*N(d2) + q*S*exp(-qT)*N(d1)] / 365
        theta_put  = [-S*exp(-qT)*n(d1)*sigma/(2*sqrt(T))
                      + r*K*exp(-rT)*N(-d2) - q*S*exp(-qT)*N(-d1)] / 365
        rho_call   = K*T*exp(-rT)*N(d2)
        rho_put    = -K*T*exp(-rT)*N(-d2)

    Theta is per calendar day (annual / 365).

    Parameters
    ----------
    S : float
        Spot price.  Must be > 0.
    K : float
        Strike price.  Must be > 0.
    T : float
        Time to expiry in years.  Must be > 0.
    r : float
        Risk-free rate (annualised fraction).
    sigma : float
        Volatility (annualised fraction).  Must be > 0.
    q : float
        Continuous dividend yield (annualised fraction).  Default 0.
    option_type : str
        "call" or "put".
    """
    if S <= 0.0:
        raise ValueError(f"S must be > 0; got {S!r}")
    if K <= 0.0:
        raise ValueError(f"K must be > 0; got {K!r}")
    if T <= 0.0:
        raise ValueError(f"T must be > 0; got {T!r}")
    if sigma <= 0.0:
        raise ValueError(f"sigma must be > 0; got {sigma!r}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put'; got {option_type!r}")

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    exp_qT = math.exp(-q * T)
    exp_rT = math.exp(-r * T)
    n_d1 = float(_st.norm.pdf(d1))
    N_d1 = float(_st.norm.cdf(d1))
    N_d2 = float(_st.norm.cdf(d2))
    N_neg_d1 = float(_st.norm.cdf(-d1))
    N_neg_d2 = float(_st.norm.cdf(-d2))

    if option_type == "call":
        price = S * exp_qT * N_d1 - K * exp_rT * N_d2
        delta = exp_qT * N_d1
    else:
        price = K * exp_rT * N_neg_d2 - S * exp_qT * N_neg_d1
        delta = exp_qT * (N_d1 - 1.0)

    gamma = exp_qT * n_d1 / (S * sigma * sqrt_T)
    vega = S * exp_qT * n_d1 * sqrt_T

    common_theta = -S * exp_qT * n_d1 * sigma / (2.0 * sqrt_T)
    if option_type == "call":
        theta_annual = (
            common_theta - r * K * exp_rT * N_d2 + q * S * exp_qT * N_d1
        )
        rho = K * T * exp_rT * N_d2
    else:
        theta_annual = (
            common_theta + r * K * exp_rT * N_neg_d2 - q * S * exp_qT * N_neg_d1
        )
        rho = -K * T * exp_rT * N_neg_d2

    return GreeksResult(
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta_annual / 365.0,
        rho=rho,
        option_price=price,
        option_type=option_type,
        d1=d1,
        d2=d2,
    )


def position_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    quantity: float,
    *,
    q: float = 0.0,
    option_type: Literal["call", "put"] = "call",
    multiplier: float = 100.0,
) -> PositionGreeksResult:
    """Compute position-level greeks scaled by quantity * multiplier.

    Parameters
    ----------
    S, K, T, r, sigma, q, option_type
        Passed directly to bsm_greeks.
    quantity : float
        Signed contracts.  Positive = long, negative = short.
    multiplier : float
        Contract multiplier.  Must be > 0.  Default 100.
    """
    if multiplier <= 0.0:
        raise ValueError(f"multiplier must be > 0; got {multiplier!r}")
    g = bsm_greeks(S=S, K=K, T=T, r=r, sigma=sigma, q=q, option_type=option_type)
    scale = quantity * multiplier
    return PositionGreeksResult(
        per_contract=g,
        position_delta=scale * g.delta,
        position_gamma=scale * g.gamma,
        position_vega=scale * g.vega,
        position_theta=scale * g.theta,
        position_rho=scale * g.rho,
        quantity=quantity,
        multiplier=multiplier,
    )



# ---------------------------------------------------------------------------
# Section 6: Daily risk snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionRiskSnapshot:
    """Per-position risk summary for the daily risk report.

    Attributes
    ----------
    asset : str
        Asset identifier (ticker, symbol, etc.).
    entry : float
        Entry price.
    direction : str
        "long" or "short".
    quantity : float
        Signed position size.
    stop_levels : list[StopLevel]
        Computed stop levels (empty if none requested).
    component_var : float or None
        Component VaR contribution (positive loss fraction), or None.
    marginal_var : float or None
        Marginal VaR, or None.
    greeks : PositionGreeksResult or None
        Option greeks for overlay reporting, or None.
    """

    asset: str
    entry: float
    direction: Literal["long", "short"]
    quantity: float
    stop_levels: list[StopLevel]
    component_var: float | None
    marginal_var: float | None
    greeks: PositionGreeksResult | None


def build_snapshot(
    asset: str,
    entry: float,
    direction: Literal["long", "short"],
    quantity: float,
    *,
    stop_levels: list[StopLevel] | None = None,
    component_var_result: ComponentVaRResult | None = None,
    asset_index: int | None = None,
    greeks: PositionGreeksResult | None = None,
) -> PositionRiskSnapshot:
    """Assemble a PositionRiskSnapshot for a single position.

    Parameters
    ----------
    asset : str
        Asset identifier.
    entry : float
        Entry price.  Must be > 0.
    direction : str
        "long" or "short".
    quantity : float
        Signed position size.
    stop_levels : list or None
        Pre-computed StopLevel objects.
    component_var_result : ComponentVaRResult or None
        Portfolio VaR decomposition.  If provided, asset_index is required.
    asset_index : int or None
        Index of this position in component_var_result arrays.
    greeks : PositionGreeksResult or None
        Option greeks from position_greeks.
    """
    if entry <= 0.0:
        raise ValueError(f"entry must be > 0; got {entry!r}")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short'; got {direction!r}")
    cv: float | None = None
    mv: float | None = None
    if component_var_result is not None:
        if asset_index is None:
            raise ValueError(
                "asset_index must be provided when component_var_result is given."
            )
        n = len(component_var_result.component_var)
        if not (0 <= asset_index < n):
            raise ValueError(
                f"asset_index {asset_index!r} out of range for result with {n} assets."
            )
        cv = float(component_var_result.component_var[asset_index])
        mv = float(component_var_result.marginal_var[asset_index])
    return PositionRiskSnapshot(
        asset=asset,
        entry=entry,
        direction=direction,
        quantity=quantity,
        stop_levels=list(stop_levels) if stop_levels else [],
        component_var=cv,
        marginal_var=mv,
        greeks=greeks,
    )
