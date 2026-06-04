"""Macro indicator signal transforms (Phase 5.F.5).

This module derives look-ahead-free trading signals from macro time series
(interest rates, credit spreads, volatility term structures, and FX rate
differentials).  All transforms operate on :class:`MacroSeries` values or
aligned ``pd.Series`` / ``pd.DataFrame`` objects with a ``DatetimeIndex``.

Consumed input shapes
---------------------
All public functions accept **pre-aligned** ``pd.Series`` objects whose index
is a ``DatetimeIndex`` in ascending order.  Callers are responsible for
sourcing and aligning the series (e.g., from FRED via a
:class:`~core_trading.data.macro.MacroSource` adapter) before passing them
in.  A convenience helper :func:`align_series` left-joins two or more series
onto a common index using the union of their timestamps.

Signal catalogue
----------------
1. ``yield_curve_signal``     -- slope, curvature, and inversion flag from the
                                  U.S. Treasury yield curve.
2. ``vix_term_structure``     -- front/back VIX ratio (contango = risk-on,
                                  backwardation = risk-off).
3. ``credit_spread_signal``   -- level and rolling change of a credit spread
                                  (e.g., BAA-AAA or HY-IG).
4. ``currency_carry_signal``  -- pairwise interest-rate differential as a
                                  carry-trade direction proxy.

Mathematical references
-----------------------
Yield-curve slope and recession leading indicator:
  Estrella, A. & Mishkin, F.S. (1998). "Predicting U.S. Recessions: Financial
  Variables as Leading Indicators." Review of Economics and Statistics, 80(1),
  45-61.

VIX term-structure contango/backwardation regime:
  Whaley, R.E. (2009). "Understanding the VIX." Journal of Portfolio Management,
  35(3), 98-105.  Term-structure ratio referenced in: Connors, L. et al. (2012).
  "Short Term Trading Strategies That Work."

Credit-spread level as business-cycle signal:
  Gilchrist, S. & Zakrajsek, E. (2012). "Credit Spreads and Business Cycle
  Fluctuations." American Economic Review, 102(4), 1692-1720.

Currency carry trade rate-differential approach:
  Lustig, H., Roussanov, N. & Verdelhan, A. (2011). "Common Risk Factors in
  Currency Markets." Review of Financial Studies, 24(11), 3731-3777.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "MacroConfig",
    "align_series",
    "yield_curve_signal",
    "vix_term_structure",
    "credit_spread_signal",
    "currency_carry_signal",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MacroConfig:
    """Parameters for the macro indicator signal transforms.

    Attributes
    ----------
    inversion_threshold:
        Spread value (percentage points) at or below which the yield curve is
        considered inverted (Estrella-Mishkin 1998 use 0 bps; some practitioners
        use a small positive buffer, e.g. -10 bps expressed as -0.10).
        Must be <= 0.  Default 0.0.
    credit_spread_window:
        Rolling window (in rows) over which the change in credit spread is
        computed.  Must be >= 2.  Default 21 (approx. one month of daily data).
    butterfly_short_tenor:
        Weight applied to the short-end yield in the butterfly curvature
        calculation.  Curvature = butterfly_short_tenor * y_short
        + butterfly_long_tenor * y_long - y_mid.  Both wing weights must be
        positive and sum to 1.  Default 0.5.
    butterfly_long_tenor:
        Weight applied to the long-end yield in the butterfly curvature.
        Default 0.5.
    vix_min_ratio:
        Minimum valid front/back VIX ratio.  Ratios outside
        (vix_min_ratio, 1/vix_min_ratio) are treated as data errors and
        replaced with NaN.  Must be in (0, 1).  Default 0.2.
    """

    inversion_threshold: float = 0.0
    credit_spread_window: int = 21
    butterfly_short_tenor: float = 0.5
    butterfly_long_tenor: float = 0.5
    vix_min_ratio: float = 0.2

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.inversion_threshold > 0.0:
            raise ValueError(
                f"inversion_threshold must be <= 0.0, got {self.inversion_threshold}"
            )
        if self.credit_spread_window < 2:
            raise ValueError(
                f"credit_spread_window must be >= 2, got {self.credit_spread_window}"
            )
        if self.butterfly_short_tenor <= 0.0 or self.butterfly_long_tenor <= 0.0:
            raise ValueError(
                "butterfly_short_tenor and butterfly_long_tenor must both be > 0"
            )
        # Allow a small floating-point epsilon around 1.0
        wing_sum = self.butterfly_short_tenor + self.butterfly_long_tenor
        if abs(wing_sum - 1.0) > 1e-9:
            raise ValueError(
                f"butterfly_short_tenor + butterfly_long_tenor must equal 1.0, "
                f"got {wing_sum}"
            )
        if not (0.0 < self.vix_min_ratio < 1.0):
            raise ValueError(
                f"vix_min_ratio must be in (0, 1), got {self.vix_min_ratio}"
            )


# ---------------------------------------------------------------------------
# Alignment helper
# ---------------------------------------------------------------------------


def align_series(*series: pd.Series, fill_method: str = "ffill") -> pd.DataFrame:
    """Align two or more macro series onto their union index.

    Macro series are sparse and heterogeneous in frequency (daily yields, weekly
    M2, monthly CPI).  This helper performs an outer join so no observation date
    is discarded, then optionally forward-fills missing values.

    Parameters
    ----------
    *series:
        Two or more ``pd.Series`` with ``DatetimeIndex``.  Series names are
        used as column names in the returned ``DataFrame``; callers should set
        ``series.name`` before calling.
    fill_method:
        ``"ffill"`` (default) to forward-fill after alignment, or ``"none"``
        to leave gaps as NaN.

    Returns
    -------
    pd.DataFrame
        Aligned DataFrame: DatetimeIndex rows, one column per input series.
        Sorted in ascending date order.

    Raises
    ------
    ValueError
        If fewer than two series are provided, or if any series does not have
        a ``DatetimeIndex``.
    """
    if len(series) < 2:
        raise ValueError("align_series requires at least two series")
    for i, s in enumerate(series):
        if not isinstance(s.index, pd.DatetimeIndex):
            raise ValueError(
                f"Series at position {i} must have a DatetimeIndex"
            )

    df = pd.concat(list(series), axis=1, join="outer").sort_index()
    if fill_method == "ffill":
        df = df.ffill()
    return df


# ---------------------------------------------------------------------------
# Signal 1: Yield-curve slope, curvature, and inversion flag
# ---------------------------------------------------------------------------


def yield_curve_signal(
    y_short: pd.Series,
    y_long: pd.Series,
    config: MacroConfig | None = None,
    *,
    y_mid: pd.Series | None = None,
) -> pd.DataFrame:
    """Derive slope, curvature, and inversion flag from the yield curve.

    The slope is the canonical Estrella-Mishkin (1998) recession leading
    indicator.  A negative slope (inverted curve: short rate > long rate)
    precedes U.S. recessions with a well-documented lead of 4-6 quarters.

    **Slope** (10y minus 2y, or any long-minus-short spread):

        slope_t = y_long_t - y_short_t

    **Inversion flag** (boolean):

        inverted_t = slope_t <= config.inversion_threshold

    **Butterfly curvature** (requires ``y_mid``):

        curvature_t = w_s * y_short_t + w_l * y_long_t - y_mid_t

    where w_s = config.butterfly_short_tenor and w_l = config.butterfly_long_tenor
    (default 0.5 each, mimicking the standard 2s/5s/10s butterfly).
    A positive curvature indicates a humped curve; negative = flat/inverted belly.

    All computations use only data available at each timestamp t (look-ahead-free).

    Parameters
    ----------
    y_short:
        Short-end yield series (e.g., 2-year Treasury CMT).  Percentage points.
        ``DatetimeIndex``, ascending.
    y_long:
        Long-end yield series (e.g., 10-year Treasury CMT).  Percentage points.
        Same or compatible index.
    config:
        ``MacroConfig`` instance.  Defaults to ``MacroConfig()`` (0 bps threshold).
    y_mid:
        Optional mid-tenor yield (e.g., 5-year CMT) for the butterfly curvature
        column.  If ``None``, the curvature column is all NaN.

    Returns
    -------
    pd.DataFrame
        Index: union of ``y_short`` and ``y_long`` (and ``y_mid``) timestamps,
        forward-filled, sorted ascending.  Columns:

        - ``slope``:     float, percentage points (y_long - y_short).
        - ``curvature``: float, butterfly curvature (NaN if y_mid not provided).
        - ``inverted``:  bool (True when slope <= inversion_threshold).

    Raises
    ------
    ValueError
        If any series does not have a DatetimeIndex.
    """
    if config is None:
        config = MacroConfig()

    # Build aligned frame
    s_s = y_short.rename("y_short")
    s_l = y_long.rename("y_long")
    if y_mid is not None:
        aligned = align_series(s_s, s_l, y_mid.rename("y_mid"))
    else:
        aligned = align_series(s_s, s_l)

    slope = aligned["y_long"] - aligned["y_short"]
    inverted = slope <= config.inversion_threshold

    if "y_mid" in aligned.columns:
        curvature = (
            config.butterfly_short_tenor * aligned["y_short"]
            + config.butterfly_long_tenor * aligned["y_long"]
            - aligned["y_mid"]
        )
    else:
        curvature = pd.Series(np.nan, index=aligned.index, dtype=float)

    return pd.DataFrame(
        {
            "slope": slope,
            "curvature": curvature,
            "inverted": inverted,
        },
        index=aligned.index,
    )


# ---------------------------------------------------------------------------
# Signal 2: VIX term-structure ratio
# ---------------------------------------------------------------------------


def vix_term_structure(
    vix_front: pd.Series,
    vix_back: pd.Series,
    config: MacroConfig | None = None,
) -> pd.DataFrame:
    """Compute the VIX term-structure ratio as a risk-on / risk-off signal.

    The ratio of near-term VIX to far-term VIX (or VIX3M) characterises the
    shape of the implied-volatility term structure:

        ratio_t = vix_front_t / vix_back_t

    A ratio > 1 (backwardation) implies near-term risk demand exceeds far-term:
    associated with risk-off episodes (e.g., market stress, sharp sell-offs).
    A ratio < 1 (contango) is the normal state and is associated with calmer,
    risk-on environments.

    Signal column ``regime`` is +1 (contango / risk-on) when ratio < 1 and
    -1 (backwardation / risk-off) when ratio >= 1.

    Whaley (2009) documents the VIX level as a fear gauge; extending to the
    term structure (front/back ratio) amplifies the signal-to-noise of single-
    point VIX (see also Connors et al. 2012 for practitioner use).

    Parameters
    ----------
    vix_front:
        Near-term VIX series (e.g., CBOE VIX spot, 1-month implied vol).
        ``DatetimeIndex``, ascending.  Values must be positive.
    vix_back:
        Far-term VIX series (e.g., CBOE VIX3M, 3-month implied vol).
        ``DatetimeIndex``, ascending.  Values must be positive.
    config:
        ``MacroConfig`` instance.  ``config.vix_min_ratio`` is used to sanity-
        check extreme ratio values.  Defaults to ``MacroConfig()``.

    Returns
    -------
    pd.DataFrame
        Index: union of front/back timestamps, forward-filled, ascending.
        Columns:

        - ``ratio``:  float, vix_front / vix_back.  NaN for invalid rows.
        - ``regime``: float, +1 (contango) or -1 (backwardation).  NaN when
                      ratio is NaN.

    Raises
    ------
    ValueError
        If either series does not have a DatetimeIndex.
    """
    if config is None:
        config = MacroConfig()

    aligned = align_series(
        vix_front.rename("vix_front"),
        vix_back.rename("vix_back"),
    )

    front = aligned["vix_front"].to_numpy(dtype=float)
    back = aligned["vix_back"].to_numpy(dtype=float)

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio_arr = np.where(
            np.isfinite(front) & (front > 0.0)
            & np.isfinite(back) & (back > 0.0),
            front / back,
            np.nan,
        )

    # Sanity-check: extreme ratios suggest data errors
    lo = config.vix_min_ratio
    hi = 1.0 / lo
    ratio_arr = np.where(
        np.isfinite(ratio_arr) & (ratio_arr > lo) & (ratio_arr < hi),
        ratio_arr,
        np.nan,
    )

    # Regime: +1 if ratio < 1 (contango/risk-on), -1 if ratio >= 1 (backwardation)
    regime_arr = np.where(
        np.isfinite(ratio_arr),
        np.where(ratio_arr < 1.0, 1.0, -1.0),
        np.nan,
    )

    return pd.DataFrame(
        {"ratio": ratio_arr, "regime": regime_arr},
        index=aligned.index,
    )


# ---------------------------------------------------------------------------
# Signal 3: Credit-spread level and change
# ---------------------------------------------------------------------------


def credit_spread_signal(
    spread: pd.Series,
    config: MacroConfig | None = None,
) -> pd.DataFrame:
    """Derive level and rolling change signals from a credit-spread series.

    Credit spreads (e.g., Moody's BAA-AAA corporate bond spread, or a high-yield
    minus investment-grade spread) compress during expansions and widen sharply
    during downturns and financial stress (Gilchrist-Zakrajsek 2012).  Both the
    level and the rate-of-change carry predictive information:

        level_t  = spread_t                         (raw credit risk premium)
        change_t = spread_t - spread_{t - window}   (momentum of risk aversion)

    A widening spread (positive change) is a risk-off / tightening signal;
    a narrowing spread (negative change) is risk-on.

    The computation is look-ahead-free: at row t only values at or before t are
    used.

    Parameters
    ----------
    spread:
        Credit spread series (percentage points or basis points -- consistent
        units throughout).  ``DatetimeIndex``, ascending.
    config:
        ``MacroConfig`` instance.  ``config.credit_spread_window`` controls the
        rolling window for the change computation.  Defaults to ``MacroConfig()``.

    Returns
    -------
    pd.DataFrame
        Index matches the input ``spread`` index.  Columns:

        - ``level``:  float, the raw spread value.
        - ``change``: float, spread_t - spread_{t-window}.  NaN for rows
                      within the first ``window`` observations.

    Raises
    ------
    ValueError
        If ``spread`` does not have a DatetimeIndex.
    """
    if config is None:
        config = MacroConfig()

    if not isinstance(spread.index, pd.DatetimeIndex):
        raise ValueError("spread must have a DatetimeIndex")

    arr = spread.to_numpy(dtype=float)
    n = len(arr)
    window = config.credit_spread_window

    change_arr = np.full(n, np.nan, dtype=float)
    for t in range(window, n):
        if np.isfinite(arr[t]) and np.isfinite(arr[t - window]):
            change_arr[t] = arr[t] - arr[t - window]

    return pd.DataFrame(
        {"level": arr, "change": change_arr},
        index=spread.index,
    )


# ---------------------------------------------------------------------------
# Signal 4: Currency carry signal (interest-rate differential)
# ---------------------------------------------------------------------------


def currency_carry_signal(
    rate_domestic: pd.Series,
    rate_foreign: pd.Series,
) -> pd.DataFrame:
    """Compute a pairwise carry signal from the interest-rate differential.

    The uncovered interest-rate parity (UIP) framework implies that a currency
    with a higher short rate should depreciate to equalise returns.  In
    practice, high-rate currencies tend to *appreciate* in the short run
    (the "carry trade premium" -- Lustig-Roussanov-Verdelhan 2011), so the
    rate differential is used as a directional carry-trade signal:

        carry_t = rate_domestic_t - rate_foreign_t

    A positive carry_t implies the domestic currency offers a higher yield;
    a carry trader borrows the foreign currency and invests domestically.
    The ``direction`` column encodes +1 (long domestic / short foreign) when
    carry > 0 and -1 (long foreign / short domestic) when carry < 0.

    The computation is look-ahead-free: at row t only rates available at t
    are used.

    Parameters
    ----------
    rate_domestic:
        Domestic short-term interest rate series (same units as
        ``rate_foreign``, e.g., 3-month overnight rate in % p.a.).
        ``DatetimeIndex``, ascending.
    rate_foreign:
        Foreign short-term interest rate series.  ``DatetimeIndex``,
        ascending.

    Returns
    -------
    pd.DataFrame
        Index: union of both rate series timestamps, forward-filled, ascending.
        Columns:

        - ``carry``:     float, rate_domestic - rate_foreign.  NaN for
                         missing observations.
        - ``direction``: float, +1 or -1.  0.0 when carry is exactly 0;
                         NaN when carry is NaN.

    Raises
    ------
    ValueError
        If either series does not have a DatetimeIndex.
    """
    aligned = align_series(
        rate_domestic.rename("domestic"),
        rate_foreign.rename("foreign"),
    )

    carry_arr = (aligned["domestic"] - aligned["foreign"]).to_numpy(dtype=float)

    direction_arr = np.where(
        np.isfinite(carry_arr),
        np.sign(carry_arr),   # +1, 0, or -1
        np.nan,
    )

    return pd.DataFrame(
        {"carry": carry_arr, "direction": direction_arr},
        index=aligned.index,
    )


# ---------------------------------------------------------------------------
# Internal helper (used in tests via the public cross_sectional_zscore import
# from momentum -- not re-exported here because macro.py operates on single
# series, not multi-asset panels)
# ---------------------------------------------------------------------------


def _zscore_series(s: pd.Series, window: int) -> pd.Series:
    """Rolling z-score of a univariate series (internal use).

    At each row t:
        z_t = (s_t - rolling_mean_{t}) / rolling_std_{t}

    where the rolling window includes only observations up to and including t
    (look-ahead-free).  Rows with insufficient history produce NaN.

    Parameters
    ----------
    s:
        Input series with DatetimeIndex.
    window:
        Rolling window length >= 2.

    Returns
    -------
    pd.Series
        Z-scored series with the same index as ``s``.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    arr = s.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)

    for t in range(window - 1, n):
        window_data = arr[t - window + 1 : t + 1]
        valid = window_data[np.isfinite(window_data)]
        if len(valid) < 2:
            continue
        mu = float(np.mean(valid))
        sigma = float(np.std(valid, ddof=0))
        if sigma == 0.0 or not np.isfinite(sigma):
            continue
        if np.isfinite(arr[t]):
            out[t] = (arr[t] - mu) / sigma

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.Series(out, index=s.index, name=s.name)
