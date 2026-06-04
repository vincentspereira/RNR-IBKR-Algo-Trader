"""Price-impact and illiquidity estimators from OHLCV data (Phase 5.E microstructure).

This module implements two classical market-impact / illiquidity measures that
can be estimated from daily OHLCV bars, without requiring signed trade data or
a real-time order book.

Module overview
---------------
1. ``KyleConfig``        -- frozen DTO capturing rolling-window parameters.
2. ``amihud_illiq``      -- Amihud (2002) illiquidity ratio.
3. ``kyle_lambda``       -- Kyle's lambda estimated via OLS of price changes on
                            signed (proxied) volume.

Signed-volume proxy
-------------------
True trade direction (whether a transaction is buyer- or seller-initiated) is
not available in OHLCV data.  A widely-used OHLCV proxy is the *tick rule*
(Lee & Ready 1991): the sign of the close-to-close return determines the
presumed direction of the marginal trade at each bar.

    signed_volume_t = sign(close_t - close_{t-1}) * volume_t

When close_t = close_{t-1} (a zero return), the sign is 0 and the bar
contributes no information; this is the standard convention.  The tick-rule
sign is a noisy proxy -- it conflates the direction of the *last* trade with
the direction of all trades in the bar -- so Kyle's lambda estimates from daily
OHLCV will be attenuated compared to tick-level estimates.  This is documented
in Goyenko, Holden & Trzcinka (2009) JFE.

Mathematical references
-----------------------
Amihud (2002) ILLIQ
    At day t, define the Amihud ratio:

        ILLIQ_t = |r_t| / (P_t * V_t)

    where r_t = (close_t - close_{t-1}) / close_{t-1} is the simple return,
    P_t is the closing price (dollars), and V_t is the share volume.  The
    product P_t * V_t is the dollar volume.  ILLIQ measures price impact per
    dollar traded.

    Units: (dimensionless return fraction) / (dollars).  The magnitude is
    typically very small for liquid stocks; multiply by 1e6 (the ``scale``
    parameter default) to express in (percent-return) / (million dollars),
    which is the convention in the empirical literature.

    The rolling mean is returned:

        ILLIQ_bar_t = (1/window) * sum_{i=t-window+1}^{t} ILLIQ_i

Kyle's lambda (OLS)
    Kyle (1985) models the price impact of a single large trader:

        delta_P_t = lambda * Q_t + epsilon_t

    where delta_P_t is the price change, Q_t is the net signed order flow
    (positive = buy pressure), and lambda is the price-impact coefficient.
    A larger lambda means worse liquidity (more price movement per unit of
    order flow).

    Because true order-flow Q_t is not available in OHLCV data, we substitute
    the tick-rule signed volume as described above.  The OLS estimator over a
    rolling window of length ``window`` regresses close-to-close price changes
    on signed volume, extracting the slope as the lambda estimate.

References
----------
Kyle, A.S. (1985). "Continuous Auctions and Insider Trading."
    Econometrica, 53(6), 1315-1335.

Amihud, Y. (2002). "Illiquidity and Stock Returns: Cross-Section and
    Time-Series Effects." Journal of Financial Markets, 5(1), 31-56.

Lee, C. & Ready, M. (1991). "Inferring Trade Direction from Intraday Data."
    Journal of Finance, 46(2), 733-746.

Goyenko, R.Y., Holden, C.W. & Trzcinka, C.A. (2009). "Do Liquidity Measures
    Measure Liquidity?" Journal of Financial Economics, 92(2), 153-181.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "KyleConfig",
    "amihud_illiq",
    "kyle_lambda",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KyleConfig:
    """Parameters for the rolling price-impact / illiquidity estimators.

    Attributes
    ----------
    window:
        Rolling window length in bars.  Must be >= 5 to allow a meaningful OLS
        regression (at least 5 (x, y) pairs after differencing).
    min_periods:
        Minimum number of non-NaN observations required in the window for an
        output to be produced.  Defaults to ``window``.  Must be >= 5.
    scale:
        Multiplicative scale applied to the Amihud ILLIQ before returning.
        Default 1e6, expressing illiquidity in units of
        (fractional return) / (million dollars of volume).
    """

    window: int = 60
    min_periods: int | None = None
    scale: float = 1e6

    def __post_init__(self) -> None:
        if self.window < 5:
            raise ValueError(f"window must be >= 5, got {self.window}")
        effective_min = self.min_periods if self.min_periods is not None else self.window
        if effective_min < 5:
            raise ValueError(f"min_periods must be >= 5, got {self.min_periods}")
        if effective_min > self.window:
            raise ValueError(
                f"min_periods ({self.min_periods}) must be <= window ({self.window})"
            )
        if self.scale <= 0.0:
            raise ValueError(f"scale must be > 0, got {self.scale}")

    @property
    def effective_min_periods(self) -> int:
        return self.min_periods if self.min_periods is not None else self.window


# ---------------------------------------------------------------------------
# Internal helper: OLS slope
# ---------------------------------------------------------------------------


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Return the OLS slope beta from a simple linear regression y ~ x.

    Uses the formula beta = cov(x, y) / var(x).  Returns NaN if var(x) == 0.
    Callers are responsible for ensuring len(x) >= 2.
    """
    xm = x - x.mean()
    var_x = float(np.dot(xm, xm))
    if var_x == 0.0:
        return float("nan")
    return float(np.dot(xm, y - y.mean()) / var_x)


# ---------------------------------------------------------------------------
# Amihud (2002) ILLIQ
# ---------------------------------------------------------------------------


def amihud_illiq(
    close: pd.Series,
    volume: pd.Series,
    *,
    window: int = 60,
    min_periods: int | None = None,
    scale: float = 1e6,
) -> pd.Series:
    """Compute the Amihud (2002) illiquidity ratio over a rolling window.

    At each bar t the per-bar ratio is:

        illiq_t = |return_t| / dollar_volume_t  *  scale

    where return_t = (close_t - close_{t-1}) / close_{t-1} (simple return)
    and dollar_volume_t = close_t * volume_t.

    The rolling mean of this ratio is returned as the liquidity proxy.  A
    higher value indicates lower liquidity (more price impact per dollar of
    trading activity).

    Bars where return is NaN (first bar), dollar_volume is zero, or any input
    is NaN produce NaN in the per-bar ratio, which then propagates into the
    rolling mean if enough NaN bars accumulate.

    Parameters
    ----------
    close:
        Series of closing prices (positive; NaN propagated).
    volume:
        Series of traded share volume (non-negative; NaN propagated).
    window:
        Rolling window length in bars.  Must be >= 5.
    min_periods:
        Minimum valid observations per window.  Defaults to ``window``.
    scale:
        Multiplier for unit conversion (default 1e6 = per-million-dollars).

    Returns
    -------
    pd.Series
        Rolling mean Amihud ILLIQ, indexed the same as ``close``.
        Units: (fractional return) / (scale dollars).

    Raises
    ------
    ValueError
        If inputs have different lengths / indices, or parameters are invalid.
    """
    if len(close) != len(volume):
        raise ValueError("close and volume must have the same length")
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")

    cfg = KyleConfig(window=window, min_periods=min_periods, scale=scale)
    mp = cfg.effective_min_periods

    c = close.astype(float).to_numpy()
    v = volume.astype(float).to_numpy()
    n = len(c)

    ret = np.full(n, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = (c[1:] - c[:-1]) / c[:-1]

    dollar_vol = c * v

    with np.errstate(divide="ignore", invalid="ignore"):
        per_bar = np.where(
            np.isfinite(ret) & np.isfinite(dollar_vol) & (dollar_vol > 0.0),
            np.abs(ret) / dollar_vol * scale,
            np.nan,
        )

    illiq = pd.Series(per_bar, index=close.index).rolling(
        window=window, min_periods=mp
    ).mean()
    illiq.name = "amihud_illiq"
    return illiq


# ---------------------------------------------------------------------------
# Kyle's lambda (OLS on proxied signed volume)
# ---------------------------------------------------------------------------


def kyle_lambda(
    close: pd.Series,
    volume: pd.Series,
    *,
    window: int = 60,
    min_periods: int | None = None,
) -> pd.Series:
    """Estimate Kyle's lambda via OLS over a rolling window.

    Uses the tick-rule signed volume as a proxy for net order flow (see module
    docstring for the rationale and limitations).  The model at each rolling
    window ending at bar t is:

        delta_P_i = lambda * signed_volume_i + epsilon_i

    where delta_P_i = close_i - close_{i-1} (price change in dollars)
    and signed_volume_i = sign(delta_P_i) * volume_i.

    The OLS slope (lambda) is estimated as:

        lambda = cov(signed_volume, delta_P) / var(signed_volume)

    A larger positive lambda indicates lower liquidity (each unit of net order
    flow moves the price more).  The estimate may be negative in windows
    dominated by mean-reversion or noisy proxy assignments.

    Parameters
    ----------
    close:
        Series of closing prices (positive; NaN propagated).
    volume:
        Series of traded share volume (non-negative; NaN propagated).
    window:
        Rolling window length in bars.  Must be >= 5.
    min_periods:
        Minimum valid observations per window.  Defaults to ``window``.

    Returns
    -------
    pd.Series
        Rolling Kyle lambda estimates indexed the same as ``close``.
        Units: dollars / share (price change per share of signed volume).
        NaN for the warm-up period and any window with insufficient data.

    Raises
    ------
    ValueError
        If inputs have different lengths / indices, or parameters are invalid.
    """
    if len(close) != len(volume):
        raise ValueError("close and volume must have the same length")
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")

    cfg = KyleConfig(window=window, min_periods=min_periods)
    mp = cfg.effective_min_periods

    c = close.astype(float).to_numpy()
    v = volume.astype(float).to_numpy()
    n = len(c)

    dp = np.full(n, np.nan, dtype=float)
    dp[1:] = c[1:] - c[:-1]

    # Tick-rule signed volume; zero return -> sign is 0
    signed_vol = np.sign(dp) * v

    lam = np.full(n, np.nan, dtype=float)

    for t in range(window - 1, n):
        start = t - window + 1
        sv = signed_vol[start : t + 1]
        dpt = dp[start : t + 1]
        valid = np.isfinite(sv) & np.isfinite(dpt)
        n_valid = int(valid.sum())
        if n_valid < mp:
            continue
        lam[t] = _ols_slope(sv[valid], dpt[valid])

    return pd.Series(lam, index=close.index, name="kyle_lambda")
