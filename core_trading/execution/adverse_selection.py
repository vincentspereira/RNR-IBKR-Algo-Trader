"""Adverse-selection monitoring -- VPIN, toxicity, markout drift (Phase 9.5).

This module monitors *execution-time adverse selection*: the risk that the
counterparties filling our orders are, on average, better informed than we are,
so that our fills systematically precede an adverse price move.  It exposes
three complementary diagnostics and a stateful auto-pause monitor:

1. **VPIN** (Volume-Synchronized Probability of Informed Trading).  A flow
   toxicity gauge in ``[0, 1]`` computed via **Bulk Volume Classification**
   (BVC), which requires only OHLCV-style bar data -- price changes and bar
   volumes -- and *not* trade-by-trade tick data.

2. **Pre-trade toxicity check**: a simple verdict on whether current VPIN is
   elevated relative to either an absolute threshold or a trailing percentile
   of its own history.

3. **Markout drift detection**: a one-sided test on a series of post-trade
   markouts (positive = adverse) detecting a persistent adverse-execution
   regime.

4. :class:`ExecutionToxicityMonitor`: a replayable, deterministic state machine
   that pauses execution when VPIN turns toxic OR markout drift fires, and
   re-arms conservatively only after a configurable run of clean readings.

Relationship to Phase 5 microstructure signals
-----------------------------------------------
VPIN was explicitly **deferred** from the Phase 5 microstructure signal set
(see :mod:`core_trading.signals.microstructure` -- its header lists VPIN as
"requires tick data").  That deferral assumed the canonical VPIN construction
of Easley, Lopez de Prado and O'Hara (2012), which classifies *individual
trades* as buyer- or seller-initiated.  This module closes that gap using the
authors' own **Bulk Volume Classification** approximation, which classifies
the *aggregate* volume of a bar using the standardized price change, and is
therefore computable from OHLCV bars alone.  No tick feed is required.

Bulk Volume Classification (BVC)
--------------------------------
For each bar ``t`` with signed price change ``dP_t = P_t - P_{t-1}`` and total
volume ``V_t``, the buyer-initiated fraction is::

    buy_frac_t = Z(dP_t / sigma_dP)

where ``Z`` is the standard normal CDF and ``sigma_dP`` is the (rolling)
standard deviation of price changes.  Buyer- and seller-initiated volumes are::

    buy_vol_t  = V_t * buy_frac_t
    sell_vol_t = V_t * (1 - buy_frac_t)

Large positive ``dP`` -> ``buy_frac -> 1`` (mostly buyer-initiated); large
negative ``dP`` -> ``buy_frac -> 0`` (mostly seller-initiated); ``dP = 0`` ->
``buy_frac = 0.5`` (balanced).  When ``sigma_dP`` is zero (degenerate, e.g. a
constant up-tick window) we fall back to the sign of ``dP`` (1.0 for up, 0.0
for down, 0.5 for flat), which is the limiting value of the CDF.

Volume bucketing
----------------
Classified flow is re-bucketed into **equal-volume buckets** of size ``V``
(``bucket_size``).  Because a single bar's volume rarely lands exactly on a
bucket boundary, each bar is split across bucket boundaries **pro-rata**: a bar
contributing ``v`` units of volume that straddles a boundary donates a fraction
of its buy/sell volume to each side in proportion to the volume on each side of
the boundary.  This preserves total buy and total sell volume exactly.  Each
completed bucket therefore has total volume exactly ``V`` and is stamped with
the index/timestamp of the bar in which it *completed*.

VPIN
----
VPIN is the rolling mean, over the most recent ``n_buckets`` completed buckets,
of the per-bucket order-flow imbalance::

    VPIN = mean_{i in window} |buy_i - sell_i| / V

Each term lies in ``[0, 1]`` (since ``|buy_i - sell_i| <= buy_i + sell_i = V``),
so VPIN lies in ``[0, 1]``.  All-buy (or all-sell) buckets give VPIN ~= 1;
perfectly balanced buckets give VPIN ~= 0.

References
----------
Easley, D., Lopez de Prado, M.M. & O'Hara, M. (2012). "Flow Toxicity and
    Liquidity in a High-Frequency World." Review of Financial Studies,
    25(5), 1457-1493.

Easley, D., Lopez de Prado, M. & O'Hara, M. (2012). "The Volume Clock:
    Insights into the High-Frequency Paradigm." Journal of Portfolio
    Management, 39(1), 19-29.

Page, E.S. (1954). "Continuous Inspection Schemes." Biometrika, 41(1/2),
    100-115.  (CUSUM.)
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy.special import ndtr as _ndtr  # vectorised normal CDF, no Python loop
from scipy.stats import t as student_t

__all__ = [
    "AdverseSelectionConfig",
    "DEFAULT_CONFIG",
    "MonitorState",
    "TriggerType",
    "ToxicityVerdict",
    "DriftVerdict",
    "ToxicityEvent",
    "ExecutionToxicityMonitor",
    "bulk_volume_classify",
    "volume_buckets",
    "vpin",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdverseSelectionConfig:
    """Immutable configuration for adverse-selection monitoring.

    VPIN / BVC parameters
    ---------------------
    sigma_window:
        Rolling window (in bars) used to estimate ``sigma_dP``, the standard
        deviation of price changes, for Bulk Volume Classification.  Must be
        ``>= 2`` (a sample standard deviation needs at least two points).
    bucket_size:
        Equal-volume bucket size ``V``.  Must be ``> 0``.
    n_buckets:
        Number of completed buckets in the trailing VPIN window.  Must be
        ``>= 1``.

    Toxicity-check parameters
    -------------------------
    toxicity_mode:
        ``"absolute"`` -- VPIN is toxic when it exceeds
        :attr:`toxicity_threshold`.
        ``"percentile"`` -- VPIN is toxic when it exceeds the
        :attr:`toxicity_percentile`-th percentile of its own trailing history.
    toxicity_threshold:
        Absolute VPIN threshold in ``(0, 1]`` used when
        ``toxicity_mode == "absolute"`` (default ``0.7``).
    toxicity_percentile:
        Percentile in ``(0, 100)`` used when
        ``toxicity_mode == "percentile"`` (default ``95.0``).

    Markout-drift parameters
    ------------------------
    markout_window:
        Trailing window (number of markout observations) over which the
        adverse-drift t-statistic is computed.  Must be ``>= 2``.
    drift_t_threshold:
        One-sided t-statistic threshold above which the mean markout is judged
        significantly adverse (default ``2.0``, ~ p < 0.025 for large samples).

    Monitor parameters
    ------------------
    cooldown_buckets:
        Number of consecutive *clean* readings (neither VPIN-toxic nor
        drift-firing) required while PAUSED before the monitor re-arms to
        ACTIVE.  Conservative: a single dirty reading resets the counter.
        Must be ``>= 1``.
    """

    # VPIN / BVC
    sigma_window: int = 50
    bucket_size: float = 1.0
    n_buckets: int = 50

    # toxicity check
    toxicity_mode: str = "absolute"
    toxicity_threshold: float = 0.7
    toxicity_percentile: float = 95.0

    # markout drift
    markout_window: int = 20
    drift_t_threshold: float = 2.0

    # monitor
    cooldown_buckets: int = 5

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.sigma_window < 2:
            raise ValueError(
                f"sigma_window must be >= 2, got {self.sigma_window!r}"
            )
        if self.bucket_size <= 0.0:
            raise ValueError(
                f"bucket_size must be > 0, got {self.bucket_size!r}"
            )
        if self.n_buckets < 1:
            raise ValueError(f"n_buckets must be >= 1, got {self.n_buckets!r}")
        if self.toxicity_mode not in ("absolute", "percentile"):
            raise ValueError(
                "toxicity_mode must be 'absolute' or 'percentile', got"
                f" {self.toxicity_mode!r}"
            )
        if not (0.0 < self.toxicity_threshold <= 1.0):
            raise ValueError(
                f"toxicity_threshold must be in (0, 1], got"
                f" {self.toxicity_threshold!r}"
            )
        if not (0.0 < self.toxicity_percentile < 100.0):
            raise ValueError(
                f"toxicity_percentile must be in (0, 100), got"
                f" {self.toxicity_percentile!r}"
            )
        if self.markout_window < 2:
            raise ValueError(
                f"markout_window must be >= 2, got {self.markout_window!r}"
            )
        if self.drift_t_threshold <= 0.0:
            raise ValueError(
                f"drift_t_threshold must be > 0, got {self.drift_t_threshold!r}"
            )
        if self.cooldown_buckets < 1:
            raise ValueError(
                f"cooldown_buckets must be >= 1, got {self.cooldown_buckets!r}"
            )


DEFAULT_CONFIG: AdverseSelectionConfig = AdverseSelectionConfig()


# ---------------------------------------------------------------------------
# Enumerations and verdict / event records
# ---------------------------------------------------------------------------


class MonitorState(enum.Enum):
    """State of :class:`ExecutionToxicityMonitor`.

    ACTIVE
        Execution permitted; no toxicity trigger is currently latched.
    PAUSED
        Execution should halt; a VPIN or markout-drift trigger is latched and
        the conservative cooldown has not yet elapsed.
    """

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class TriggerType(enum.Enum):
    """Which diagnostic caused (or cleared) a monitor transition."""

    VPIN = "VPIN"
    MARKOUT_DRIFT = "MARKOUT_DRIFT"
    COOLDOWN = "COOLDOWN"


@dataclass(frozen=True, slots=True)
class ToxicityVerdict:
    """Result of :func:`toxicity_check`.

    Attributes
    ----------
    toxic:
        ``True`` when the latest VPIN reading exceeds the active threshold.
    latest_vpin:
        Most recent VPIN value evaluated.
    threshold:
        The numeric VPIN level used as the toxicity cutoff.  In
        ``"absolute"`` mode this is the configured absolute threshold; in
        ``"percentile"`` mode it is the computed trailing-percentile VPIN.
    percentile:
        The percentile rank (in ``[0, 100]``) of ``latest_vpin`` within the
        trailing VPIN history (inclusive).  Useful for diagnostics in both
        modes.
    mode:
        The toxicity mode used (``"absolute"`` or ``"percentile"``).
    """

    toxic: bool
    latest_vpin: float
    threshold: float
    percentile: float
    mode: str


@dataclass(frozen=True, slots=True)
class DriftVerdict:
    """Result of :func:`markout_drift`.

    Attributes
    ----------
    drifting:
        ``True`` when the trailing mean markout is significantly adverse
        (one-sided t-statistic exceeds the configured threshold).
    mean_markout:
        Trailing-window mean markout (positive = adverse).
    t_stat:
        One-sided t-statistic for ``H0: mean <= 0`` vs ``H1: mean > 0``.
        ``+inf`` when the window has zero dispersion but a positive mean;
        ``0.0`` when the mean is non-positive with zero dispersion.
    p_value:
        One-sided p-value associated with ``t_stat`` (small => adverse).
    threshold:
        The t-statistic threshold used.
    n_obs:
        Number of observations in the trailing window.
    """

    drifting: bool
    mean_markout: float
    t_stat: float
    p_value: float
    threshold: float
    n_obs: int


@dataclass(frozen=True, slots=True)
class ToxicityEvent:
    """Immutable record of a single monitor state transition.

    Mirrors the lightweight audit-event pattern of
    :class:`core_trading.risk.circuit_breakers.BreakerEvent`: every transition
    appends one of these to :attr:`ExecutionToxicityMonitor.events`, forming an
    authoritative, machine-readable audit log.

    Attributes
    ----------
    index:
        Caller-supplied label/timestamp of the reading that caused the
        transition (whatever was passed to :meth:`ExecutionToxicityMonitor.update`).
    trigger:
        Which diagnostic drove the transition.
    from_state:
        State before the transition.
    to_state:
        State after the transition.
    observed:
        The observed metric value that drove the transition (latest VPIN for a
        VPIN trigger, mean markout for a drift trigger, clean-count for a
        cooldown re-arm).
    limit:
        The limit/threshold against which ``observed`` was compared.
    reason:
        Human-readable ASCII description of the transition.
    """

    index: object
    trigger: TriggerType
    from_state: MonitorState
    to_state: MonitorState
    observed: float
    limit: float
    reason: str


# ---------------------------------------------------------------------------
# Bulk Volume Classification
# ---------------------------------------------------------------------------


def bulk_volume_classify(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    sigma_window: int,
) -> tuple[pd.Series, pd.Series]:
    """Classify each bar's volume into buyer- and seller-initiated parts.

    Implements Bulk Volume Classification (Easley, Lopez de Prado & O'Hara,
    2012): the buyer-initiated fraction of bar ``t`` is the standard-normal CDF
    of the standardized price change ``dP_t / sigma_dP``, where ``sigma_dP`` is
    the rolling standard deviation of price changes estimated over the trailing
    ``sigma_window`` bars.

    Parameters
    ----------
    prices:
        Bar prices (typically closes), indexed by bar.
    volumes:
        Bar volumes, aligned to ``prices`` (same index, same length, all
        ``>= 0``).
    sigma_window:
        Rolling window for the price-change standard deviation (``>= 2``).

    Returns
    -------
    (buy_vol, sell_vol):
        Two :class:`pandas.Series` aligned to ``prices``.  The first bar has no
        defined price change and is classified as balanced
        (``buy = sell = volume / 2``).  Bars whose rolling ``sigma_dP`` is not
        yet defined (insufficient history) or is exactly zero fall back to the
        sign of the price change (full buy / full sell / balanced).  In all
        cases ``buy_vol + sell_vol == volumes`` exactly.

    Notes
    -----
    The fallback for ``sigma_dP == 0`` uses the limiting value of the CDF:
    ``Z(+inf) = 1`` for an up-tick, ``Z(-inf) = 0`` for a down-tick, and
    ``Z(0) = 0.5`` for a flat bar.
    """
    if sigma_window < 2:
        raise ValueError(f"sigma_window must be >= 2, got {sigma_window!r}")
    if len(prices) != len(volumes):
        raise ValueError(
            f"prices and volumes length mismatch: {len(prices)} vs {len(volumes)}"
        )
    if not prices.index.equals(volumes.index):
        raise ValueError("prices and volumes must share the same index")

    price_vals = prices.to_numpy(dtype=float)
    vol_vals = volumes.to_numpy(dtype=float)
    if np.any(vol_vals < 0.0):
        raise ValueError("volumes must be non-negative")

    dP = np.diff(price_vals, prepend=np.nan)  # dP[0] = NaN (no prior bar)

    # Rolling sample standard deviation of price changes (min 2 obs).
    dP_series = pd.Series(dP, index=prices.index)
    sigma = dP_series.rolling(window=sigma_window, min_periods=2).std(ddof=1)
    sigma_vals = sigma.to_numpy(dtype=float)

    # -- Vectorised BVC classification (no Python loop) ---------------------
    #
    # Three mutually exclusive masks select which formula applies per bar:
    #   (a) dP is NaN (first bar, no prior price)      -> buy_frac = 0.5
    #   (b) sigma is NaN or zero (fallback to sign)    -> {0.0, 0.5, 1.0}
    #   (c) normal case                                 -> ndtr(dP / sigma)
    #
    # scipy.special.ndtr is the vectorised normal CDF; it handles the full
    # array in a single C call and is ~100x faster than calling norm.cdf in
    # a Python loop.  The result is numerically identical to norm.cdf because
    # scipy.stats.norm.cdf delegates to ndtr internally.

    nan_dp = np.isnan(dP)                               # mask (a)
    bad_sigma = np.isnan(sigma_vals) | (sigma_vals == 0.0)  # mask (b)
    normal_case = ~nan_dp & ~bad_sigma                  # mask (c)

    # Compute CDF only where sigma is valid (avoids 0-division warning).
    z = np.where(normal_case, dP / np.where(normal_case, sigma_vals, 1.0), 0.0)
    cdf_vals = _ndtr(z)  # vectorised; safe for any finite input

    # Sign-based fallback for mask (b): up -> 1.0, down -> 0.0, flat -> 0.5
    fallback = np.where(dP > 0.0, 1.0, np.where(dP < 0.0, 0.0, 0.5))

    buy_frac = np.where(nan_dp, 0.5, np.where(bad_sigma, fallback, cdf_vals))

    buy_vol = vol_vals * buy_frac
    sell_vol = vol_vals - buy_vol
    return (
        pd.Series(buy_vol, index=prices.index, name="buy_vol"),
        pd.Series(sell_vol, index=prices.index, name="sell_vol"),
    )


# ---------------------------------------------------------------------------
# Volume bucketing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Bucket:
    """A single completed equal-volume bucket."""

    buy: float
    sell: float
    index: object  # label of the bar in which the bucket completed


def volume_buckets(
    buy_vol: pd.Series,
    sell_vol: pd.Series,
    *,
    bucket_size: float,
) -> pd.DataFrame:
    """Re-bucket classified flow into equal-volume buckets.

    Bars are consumed in order; their (buy, sell) volumes accumulate into the
    current bucket until the bucket's total volume reaches ``bucket_size``.  A
    bar that would overflow the boundary is **split pro-rata**: the portion of
    its volume needed to fill the current bucket donates buy/sell flow in
    proportion to that portion, and the remainder carries into the next
    bucket(s).  A single very large bar may therefore complete several buckets.
    Total buy and total sell volume are preserved exactly.

    Parameters
    ----------
    buy_vol, sell_vol:
        Per-bar buyer- and seller-initiated volumes (e.g. from
        :func:`bulk_volume_classify`), sharing the same index.
    bucket_size:
        Target volume ``V`` per bucket (``> 0``).

    Returns
    -------
    DataFrame
        One row per *completed* bucket with columns ``buy``, ``sell`` and
        ``imbalance`` (``|buy - sell| / bucket_size``), indexed by the label of
        the bar in which the bucket completed.  Any trailing partial bucket
        (volume ``< bucket_size``) is discarded.
    """
    if bucket_size <= 0.0:
        raise ValueError(f"bucket_size must be > 0, got {bucket_size!r}")
    if not buy_vol.index.equals(sell_vol.index):
        raise ValueError("buy_vol and sell_vol must share the same index")

    buy_arr = buy_vol.to_numpy(dtype=float)
    sell_arr = sell_vol.to_numpy(dtype=float)

    # -- Vectorised equal-volume bucketing (zero Python loops) ----------------
    #
    # Key insight: treat cumulative buy volume as a *piecewise-linear* function
    # of cumulative total volume.  Within each bar i, both buy and sell volume
    # are proportional to total volume (the bar's buy_frac is constant), so the
    # cumulative buy function is indeed piecewise-linear.  The buy contribution
    # to any volume interval [lo, hi] is then:
    #
    #   buy(lo, hi) = cum_buy_interp(hi) - cum_buy_interp(lo)
    #
    # where cum_buy_interp(q) interpolates the cumulative-buy curve at position q
    # in total-volume space.  np.searchsorted locates the containing bar in O(log n)
    # and the interpolation is a single multiply-add per query point.  Applying
    # this to ALL bucket boundaries simultaneously (no Python loop) reduces
    # volume_buckets from O(n_bars) Python iterations to two vectorised
    # searchsorted + arithmetic passes over the boundary arrays.
    #
    # Completing bar for each bucket: the bar in which cumvol first reaches the
    # bucket's upper boundary (adjusted inward by _BUCKET_EPS so that bars
    # landing within epsilon of the boundary are treated as completing it,
    # matching the original while-loop condition).
    #
    # Numerical fidelity: results match the original Python loop to within
    # ~1e-9 (a few ULPs in double precision).  The only semantic difference is
    # that out_sell = bucket_size - out_buy instead of an independent tracking
    # variable; this is mathematically identical but may differ by <= 1 ULP.
    # For zero-volume bars (buy_frac undefined), we fall back to 0.5 as in
    # bulk_volume_classify; a zero-volume bar contributes no volume regardless.

    vol_arr = buy_arr + sell_arr               # total volume per bar
    cumvol = np.cumsum(vol_arr)                # cumulative volume at end of each bar
    total_vol = float(cumvol[-1]) if len(cumvol) > 0 else 0.0

    n_buckets_possible = int((total_vol + _BUCKET_EPS) / bucket_size)
    if n_buckets_possible == 0:
        return pd.DataFrame(
            {"buy": [], "sell": [], "imbalance": []},
            index=pd.Index([], name=buy_vol.index.name),
        )

    # Bucket upper/lower boundaries in cumulative-volume space.
    upper_bound = np.arange(1, n_buckets_possible + 1, dtype=float) * bucket_size
    lower_bound = upper_bound - bucket_size  # = k * bucket_size

    # Cumulative buy prefix sums for piecewise-linear interpolation.
    cum_buy = np.cumsum(buy_arr)

    # Prefix sums for both buy and sell (used in the interpolation below).
    cum_sell = np.cumsum(sell_arr)

    # Per-bar fractions (safe for zero-volume bars: 0/0 -> 0.5).
    buy_frac_arr = np.where(vol_arr > 0.0, buy_arr / vol_arr, 0.5)
    sell_frac_arr = np.where(vol_arr > 0.0, sell_arr / vol_arr, 0.5)

    def _interp(q_arr: np.ndarray, cum_side: np.ndarray, frac_arr: np.ndarray) -> np.ndarray:
        """Interpolate a cumulative buy-or-sell curve at total-volume positions.

        For position q in bar i (cumvol[i-1] < q <= cumvol[i]), the
        cumulative value is:
            cum_side[i-1] + frac_arr[i] * (q - cumvol[i-1])
        """
        bars = np.searchsorted(cumvol, q_arr, side="left")
        bars = np.clip(bars, 0, len(cumvol) - 1)
        cumvol_before = np.where(bars > 0, cumvol[bars - 1], 0.0)
        cum_before = np.where(bars > 0, cum_side[bars - 1], 0.0)
        leftover: np.ndarray = np.clip(q_arr - cumvol_before, 0.0, vol_arr[bars])
        result: np.ndarray = cum_before + frac_arr[bars] * leftover
        return result

    # Buy and sell volumes per bucket via piecewise-linear interpolation.
    # Computing both independently (rather than sell = bucket_size - buy)
    # preserves the exact zero when a bar has zero sell volume, matching
    # the original loop's independent tracking of cur_buy and cur_sell.
    out_buy = _interp(upper_bound, cum_buy, buy_frac_arr) - _interp(lower_bound, cum_buy, buy_frac_arr)
    out_sell = _interp(upper_bound, cum_sell, sell_frac_arr) - _interp(lower_bound, cum_sell, sell_frac_arr)

    # Completing bar label = bar whose cumvol first reaches the upper boundary.
    completing_bar = np.searchsorted(cumvol, upper_bound - _BUCKET_EPS, side="left")
    completing_bar = np.clip(completing_bar, 0, len(cumvol) - 1)
    # Index.take is the vectorised gather -- a per-bucket Python loop here
    # dominates the whole computation once buckets number in the hundreds of
    # thousands (small bucket_size relative to total volume).
    completing_labels = buy_vol.index.take(completing_bar)

    imbalance = np.abs(out_buy - out_sell) / bucket_size
    return pd.DataFrame(
        {"buy": out_buy, "sell": out_sell, "imbalance": imbalance},
        index=completing_labels,
    )


_BUCKET_EPS = 1e-9


# ---------------------------------------------------------------------------
# VPIN
# ---------------------------------------------------------------------------


def vpin(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    config: AdverseSelectionConfig = DEFAULT_CONFIG,
) -> pd.Series:
    """Compute the VPIN series from OHLCV-style bars.

    Pipeline: :func:`bulk_volume_classify` (BVC) ->
    :func:`volume_buckets` (equal-volume re-bucketing) -> rolling mean of
    per-bucket order-flow imbalance over the trailing ``config.n_buckets``
    buckets.

    Parameters
    ----------
    prices:
        Bar prices (typically closes).
    volumes:
        Bar volumes aligned to ``prices``.
    config:
        :class:`AdverseSelectionConfig` providing ``sigma_window``,
        ``bucket_size`` and ``n_buckets``.

    Returns
    -------
    Series
        VPIN values in ``[0, 1]``, indexed by the bar in which each contributing
        bucket completed.  The series begins once at least ``config.n_buckets``
        buckets have completed (earlier buckets yield ``NaN`` under the rolling
        ``min_periods`` rule).  Empty if fewer than one bucket completes.
    """
    buy_vol, sell_vol = bulk_volume_classify(
        prices, volumes, sigma_window=config.sigma_window
    )
    buckets = volume_buckets(buy_vol, sell_vol, bucket_size=config.bucket_size)
    if buckets.empty:
        return pd.Series([], dtype=float, name="vpin")
    out = (
        buckets["imbalance"]
        .rolling(window=config.n_buckets, min_periods=config.n_buckets)
        .mean()
    )
    out.name = "vpin"
    return out


# ---------------------------------------------------------------------------
# Pre-trade toxicity check
# ---------------------------------------------------------------------------


def toxicity_check(
    vpin_series: pd.Series,
    *,
    config: AdverseSelectionConfig = DEFAULT_CONFIG,
) -> ToxicityVerdict:
    """Judge whether current flow toxicity (VPIN) is elevated.

    Two modes (selected by ``config.toxicity_mode``):

    ``"absolute"``
        Toxic when the latest VPIN exceeds ``config.toxicity_threshold``
        (default ``0.7``).  Simple and stable, but does not adapt to an
        instrument whose VPIN baseline is structurally high or low.

    ``"percentile"``
        Toxic when the latest VPIN exceeds the
        ``config.toxicity_percentile``-th percentile (default 95th) of the
        *trailing* VPIN history (all prior non-NaN values, inclusive of the
        latest).  Self-calibrating to each instrument's own distribution.

    Parameters
    ----------
    vpin_series:
        VPIN values (e.g. from :func:`vpin`).  NaNs are dropped before
        evaluation; the last remaining value is the "latest" reading.
    config:
        Configuration controlling mode and thresholds.

    Returns
    -------
    ToxicityVerdict

    Raises
    ------
    ValueError
        If ``vpin_series`` has no non-NaN values.
    """
    clean = vpin_series.dropna()
    if len(clean) == 0:
        raise ValueError("vpin_series has no non-NaN values to evaluate")

    vals = clean.to_numpy(dtype=float)
    latest = float(vals[-1])

    # Percentile rank of the latest value within the trailing history
    # (inclusive), in [0, 100].
    rank = float(np.mean(vals <= latest) * 100.0)

    if config.toxicity_mode == "absolute":
        threshold = config.toxicity_threshold
        toxic = latest > threshold
    else:  # "percentile"
        threshold = float(np.percentile(vals, config.toxicity_percentile))
        toxic = latest > threshold

    return ToxicityVerdict(
        toxic=toxic,
        latest_vpin=latest,
        threshold=threshold,
        percentile=rank,
        mode=config.toxicity_mode,
    )


# ---------------------------------------------------------------------------
# Markout drift detection
# ---------------------------------------------------------------------------


def markout_drift(
    markouts: pd.Series,
    *,
    config: AdverseSelectionConfig = DEFAULT_CONFIG,
) -> DriftVerdict:
    """Detect a persistent adverse-markout regime via a one-sided t-test.

    A *markout* is the signed post-trade price move measured at a fixed horizon
    after a fill, expressed so that **positive = adverse** (matching the
    convention used by the TCA module: a fill followed by an adverse move costs
    us).  Persistent positive markouts indicate we are being adversely selected.

    The test takes the trailing ``config.markout_window`` markouts and computes
    the one-sided one-sample t-statistic for ``H0: mean <= 0`` against
    ``H1: mean > 0``::

        t = mean / (s / sqrt(n))

    where ``s`` is the sample standard deviation (``ddof=1``).  The regime is
    flagged as drifting when ``t > config.drift_t_threshold``.

    Degenerate dispersion (``s == 0``) is handled explicitly: a strictly
    positive constant mean yields ``t = +inf`` (drifting); a non-positive
    constant mean yields ``t = 0`` (not drifting).

    Parameters
    ----------
    markouts:
        Series of markouts (positive = adverse).  NaNs are dropped.  Only the
        trailing ``config.markout_window`` observations are used.
    config:
        Configuration providing ``markout_window`` and ``drift_t_threshold``.

    Returns
    -------
    DriftVerdict

    Raises
    ------
    ValueError
        If fewer than two non-NaN markouts are available.
    """
    clean = markouts.dropna()
    if len(clean) < 2:
        raise ValueError(
            f"markout_drift needs >= 2 non-NaN observations, got {len(clean)}"
        )

    window = clean.iloc[-config.markout_window :]
    vals = window.to_numpy(dtype=float)
    n = int(vals.size)
    mean = float(vals.mean())
    sd = float(vals.std(ddof=1))

    if sd == 0.0:
        if mean > 0.0:
            t_stat = math.inf
            p_value = 0.0
        else:
            t_stat = 0.0
            p_value = 1.0
    else:
        t_stat = mean / (sd / math.sqrt(n))
        # One-sided p-value: P(T > t_stat) under t with n-1 dof.
        p_value = float(student_t.sf(t_stat, df=n - 1))

    drifting = t_stat > config.drift_t_threshold
    return DriftVerdict(
        drifting=drifting,
        mean_markout=mean,
        t_stat=t_stat,
        p_value=p_value,
        threshold=config.drift_t_threshold,
        n_obs=n,
    )


# ---------------------------------------------------------------------------
# Auto-pause monitor
# ---------------------------------------------------------------------------


@dataclass
class ExecutionToxicityMonitor:
    """Stateful, replayable auto-pause monitor for execution toxicity.

    The monitor is fed one reading at a time via :meth:`update`.  Each reading
    supplies the trailing VPIN history and (optionally) the trailing markout
    history available *at that point in time*.  The monitor:

    * PAUSES (ACTIVE -> PAUSED) the first time VPIN is toxic OR markout drift
      fires.  The latching trigger and observed/limit values are recorded.
    * While PAUSED, counts *consecutive clean* readings (neither VPIN-toxic nor
      drift-firing).  A single dirty reading resets that counter to zero --
      this is the conservative re-arm philosophy of
      :mod:`core_trading.risk.circuit_breakers`.
    * RE-ARMS (PAUSED -> ACTIVE) once ``config.cooldown_buckets`` consecutive
      clean readings have accumulated.

    Determinism / replayability: the monitor reads no wall clock and holds no
    hidden randomness.  Replaying the same sequence of :meth:`update` calls
    always produces the same :attr:`state` trajectory and :attr:`events` log.

    Attributes
    ----------
    config:
        Immutable configuration.
    state:
        Current :class:`MonitorState` (starts ACTIVE).
    events:
        Append-only audit log of :class:`ToxicityEvent` transitions.
    clean_streak:
        Number of consecutive clean readings observed while PAUSED.
    last_reason:
        Machine-readable reason string for the most recent transition (empty
        until the first transition).
    """

    config: AdverseSelectionConfig = DEFAULT_CONFIG
    state: MonitorState = MonitorState.ACTIVE
    events: list[ToxicityEvent] = field(default_factory=list)
    clean_streak: int = 0
    last_reason: str = ""

    @property
    def status(self) -> MonitorState:
        """Alias for :attr:`state` (machine-readable monitor status)."""
        return self.state

    @property
    def paused(self) -> bool:
        """``True`` when execution is currently paused."""
        return self.state is MonitorState.PAUSED

    def update(
        self,
        index: object,
        *,
        vpin_series: pd.Series | None = None,
        markouts: pd.Series | None = None,
    ) -> MonitorState:
        """Feed one reading and return the resulting :class:`MonitorState`.

        Parameters
        ----------
        index:
            Caller-supplied label/timestamp for this reading; stored verbatim
            on any emitted :class:`ToxicityEvent`.
        vpin_series:
            Trailing VPIN history available at this point.  When ``None`` or
            empty/all-NaN, the VPIN trigger is skipped for this reading.
        markouts:
            Trailing markout history (positive = adverse) available at this
            point.  When ``None`` or with fewer than two non-NaN values, the
            drift trigger is skipped for this reading.

        Returns
        -------
        MonitorState
            The monitor's state *after* processing this reading.
        """
        tox = self._eval_toxicity(vpin_series)
        drift = self._eval_drift(markouts)

        vpin_toxic = tox is not None and tox.toxic
        drift_firing = drift is not None and drift.drifting
        dirty = vpin_toxic or drift_firing

        if self.state is MonitorState.ACTIVE:
            if dirty:
                if vpin_toxic and tox is not None:
                    trigger = TriggerType.VPIN
                    observed = tox.latest_vpin
                    limit = tox.threshold
                    reason = (
                        f"VPIN {observed:.4f} > threshold {limit:.4f}"
                        f" ({tox.mode} mode)"
                    )
                else:
                    assert drift is not None
                    trigger = TriggerType.MARKOUT_DRIFT
                    observed = drift.mean_markout
                    limit = drift.threshold
                    reason = (
                        f"markout drift t={drift.t_stat:.4f} >"
                        f" threshold {limit:.4f}"
                        f" (mean markout {observed:.6f})"
                    )
                self._transition(
                    index,
                    trigger,
                    MonitorState.PAUSED,
                    observed,
                    limit,
                    reason,
                )
                self.clean_streak = 0
            return self.state

        # state is PAUSED
        if dirty:
            self.clean_streak = 0
            return self.state

        self.clean_streak += 1
        if self.clean_streak >= self.config.cooldown_buckets:
            reason = (
                f"cooldown satisfied: {self.clean_streak} clean readings"
                f" >= {self.config.cooldown_buckets}"
            )
            self._transition(
                index,
                TriggerType.COOLDOWN,
                MonitorState.ACTIVE,
                float(self.clean_streak),
                float(self.config.cooldown_buckets),
                reason,
            )
            self.clean_streak = 0
        return self.state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _eval_toxicity(
        self, vpin_series: pd.Series | None
    ) -> ToxicityVerdict | None:
        if vpin_series is None:
            return None
        if vpin_series.dropna().empty:
            return None
        return toxicity_check(vpin_series, config=self.config)

    def _eval_drift(self, markouts: pd.Series | None) -> DriftVerdict | None:
        if markouts is None:
            return None
        if markouts.dropna().shape[0] < 2:
            return None
        return markout_drift(markouts, config=self.config)

    def _transition(
        self,
        index: object,
        trigger: TriggerType,
        to_state: MonitorState,
        observed: float,
        limit: float,
        reason: str,
    ) -> None:
        event = ToxicityEvent(
            index=index,
            trigger=trigger,
            from_state=self.state,
            to_state=to_state,
            observed=observed,
            limit=limit,
            reason=reason,
        )
        self.state = to_state
        self.last_reason = reason
        self.events.append(event)
