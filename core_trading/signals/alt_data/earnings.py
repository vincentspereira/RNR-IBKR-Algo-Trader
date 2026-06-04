"""Earnings surprise and post-earnings-announcement drift signal (Phase 5.F.2).

This module implements the Standardised Unexpected Earnings (SUE) score and
the Post-Earnings-Announcement Drift (PEAD) cross-sectional signal from the
academic literature.  Both signals are constructed point-in-time: an EPS
observation enters the model only once its ``filing_date`` has been reached,
preventing look-ahead bias.

Consumed input shape
--------------------
The module consumes EPS records sourced from the fundamental data layer
(:class:`~core_trading.data.fundamentals.FundamentalRecord` /
:func:`~core_trading.data.fundamentals.FundamentalSource.records_to_dataframe`).
The minimum required tidy DataFrame columns are:

    symbol         str       Ticker / exchange symbol.
    metric         str       Must equal ``"eps"`` (or the caller-supplied value).
    value          float     Reported EPS for the period (e.g., USD per share).
    period_end     date      Fiscal-period end date (quarter or annual).
    filing_date    date      Public disclosure date; used as the as-of cut for
                             point-in-time correctness (Foster-Olsen-Shevlin 1984,
                             Bernard-Thomas 1989).
    fiscal_period  str       E.g., ``"Q1"``, ``"Q2"``, ``"Q3"``, ``"Q4"`` or
                             ``"FY"``.  Used to identify same-quarter prior-year
                             observations for the seasonal random-walk forecast.

Point-in-time rule: a row enters the model as of its ``filing_date``, NOT
its ``period_end``.  A quarterly earnings announcement might have
``period_end = 2024-09-30`` but ``filing_date = 2024-11-12``; the model sees
it only from 2024-11-12 onward.

Signal construction
-------------------
1. **Seasonal random-walk EPS forecast** (Foster-Olsen-Shevlin 1984):

       E[EPS_{t}] = EPS_{t-4}   (prior-year same quarter)

   where indices count quarters.  This naive benchmark is a strong forecast
   for earnings because of seasonality in firm cash flows.

2. **Standardised Unexpected Earnings** (SUE; Foster-Olsen-Shevlin 1984):

       surprise_t = EPS_{t} - E[EPS_{t}]
       SUE_t = surprise_t / sigma(surprise_{t-std_window : t-1})

   where sigma is the sample standard deviation of historical surprises over
   a trailing ``std_window``-quarter window.  When fewer than 2 historical
   surprises are available, the raw surprise (un-normalised) is used as a
   fallback with a clear NaN designation.

3. **PEAD cross-sectional score** (Bernard-Thomas 1989/1990):

   A PEAD score is assigned to each (evaluation_date, symbol) pair by:
   a. Restricting to SUE values whose ``filing_date`` <= ``evaluation_date``
      (point-in-time).
   b. Using only the most recent SUE per symbol (the last announced quarter).
   c. Cross-sectionally ranking and z-scoring across all symbols that have a
      valid SUE on that evaluation date.

   The score is +1 for the highest-SUE names (expected to drift up) and -1
   for the lowest-SUE names.  Weights follow the same
   :func:`~core_trading.signals.factors.momentum.cross_sectional_zscore`
   convention used elsewhere in the signal library.

Mathematical references
-----------------------
  Foster, G., Olsen, C. & Shevlin, T. (1984). "Earnings Releases, Anomalies,
  and the Behavior of Security Returns." Accounting Review, 59(4), 574-603.

  Bernard, V.L. & Thomas, J.K. (1989). "Post-Earnings-Announcement Drift:
  Delayed Price Response or Risk Premium?" Journal of Accounting Research,
  27(Supplement), 1-36.

  Bernard, V.L. & Thomas, J.K. (1990). "Evidence That Stock Prices Do Not
  Fully Reflect the Implications of Current Earnings for Future Earnings."
  Journal of Accounting and Economics, 13(4), 305-340.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "EarningsConfig",
    "compute_sue_panel",
    "pead_signal",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EarningsConfig:
    """Parameters for the SUE and PEAD signal pipeline.

    Attributes
    ----------
    sue_std_window:
        Number of historical quarterly surprises used to estimate the
        standard deviation for SUE normalisation.  Must be >= 2 (fewer
        than 2 observations would produce an undefined standard deviation).
        Default 8 (2 years of quarterly history).
    seasonal_lag:
        Number of quarters to look back for the seasonal random-walk
        forecast (E[EPS_t] = EPS_{t-seasonal_lag}).  Must be >= 1.
        Default 4 (same quarter prior year).
    pead_drift_window:
        Documented post-announcement drift window in calendar days.  This
        attribute is metadata only -- it does not affect the signal values
        produced by this module but should be passed downstream to the
        backtest holding-period logic.  Must be >= 1.  Default 60.
    eps_metric:
        Name of the EPS metric key inside the fundamental tidy DataFrame's
        ``metric`` column.  Default ``"eps"``.
    """

    sue_std_window: int = 8
    seasonal_lag: int = 4
    pead_drift_window: int = 60
    eps_metric: str = "eps"

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.sue_std_window < 2:
            raise ValueError(
                f"sue_std_window must be >= 2, got {self.sue_std_window}"
            )
        if self.seasonal_lag < 1:
            raise ValueError(
                f"seasonal_lag must be >= 1, got {self.seasonal_lag}"
            )
        if self.pead_drift_window < 1:
            raise ValueError(
                f"pead_drift_window must be >= 1, got {self.pead_drift_window}"
            )
        if not self.eps_metric:
            raise ValueError("eps_metric cannot be empty")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _quarter_sort_key(fiscal_period: str) -> int:
    """Map a fiscal_period string to an integer for chronological ordering.

    Annual records ("FY", "annual", "Y") are mapped to Q4 (4) so they sort
    after Q3 within the same calendar year.  Unknown strings map to 0.

    Parameters
    ----------
    fiscal_period:
        E.g., ``"Q1"``, ``"Q2"``, ``"Q3"``, ``"Q4"``, ``"FY"``.

    Returns
    -------
    int
        0 (unknown), 1, 2, 3, or 4.
    """
    fp = fiscal_period.upper().strip()
    mapping: dict[str, int] = {
        "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4,
        "FY": 4, "ANNUAL": 4, "FY2024": 4,
        "Y": 4,
    }
    # Handle patterns like "FY2024" or "Q12024"
    for prefix, val in (("Q1", 1), ("Q2", 2), ("Q3", 3), ("Q4", 4), ("FY", 4)):
        if fp.startswith(prefix):
            return val
    return mapping.get(fp, 0)


def _build_eps_history(
    eps_df: pd.DataFrame,
    symbol: str,
    eps_metric: str,
) -> pd.DataFrame:
    """Extract and sort the EPS history for one symbol.

    Returns a DataFrame with columns ``period_end``, ``filing_date``,
    ``fiscal_period``, ``value`` (EPS), sorted chronologically by
    (``period_end``, fiscal_period sort key).

    Parameters
    ----------
    eps_df:
        Full tidy fundamental DataFrame (all symbols, all metrics).
    symbol:
        The ticker to extract.
    eps_metric:
        The value of the ``metric`` column to select.

    Returns
    -------
    pd.DataFrame
        Symbol-specific EPS rows, sorted chronologically.  May be empty.
    """
    mask = (eps_df["symbol"] == symbol) & (eps_df["metric"] == eps_metric)
    sub = eps_df.loc[mask, ["period_end", "filing_date", "fiscal_period", "value"]].copy()
    if sub.empty:
        return sub

    # Convert to datetime for sorting
    sub["period_end"] = pd.to_datetime(sub["period_end"])
    sub["filing_date"] = pd.to_datetime(sub["filing_date"])

    # Sort by (period_end, fiscal_period quarter index) ascending
    sub["_fp_order"] = sub["fiscal_period"].map(_quarter_sort_key)
    return (
        sub.sort_values(["period_end", "_fp_order"])
        .drop(columns=["_fp_order"])
        .reset_index(drop=True)
    )


def _compute_sue_for_symbol(
    history: pd.DataFrame,
    seasonal_lag: int,
    std_window: int,
) -> pd.DataFrame:
    """Compute SUE for each reported EPS in the chronological history.

    For row i:
      - Seasonal forecast: EPS at row i - seasonal_lag (same quarter, prior year).
      - Surprise: eps[i] - forecast.
      - SUE: surprise / std(surprises[i-std_window : i-1]).  If fewer than 2
        prior surprises are available, SUE is raw surprise / NaN -> NaN but
        the raw surprise is retained in the ``surprise`` column.

    Parameters
    ----------
    history:
        Output of :func:`_build_eps_history` for one symbol.  Must have
        columns ``period_end``, ``filing_date``, ``value``.  Chronologically
        sorted.
    seasonal_lag:
        Quarters to lag for the naive seasonal forecast.
    std_window:
        Number of trailing historical surprises used to estimate std.

    Returns
    -------
    pd.DataFrame
        Same rows as ``history`` with additional columns:

        - ``surprise``: float, EPS - seasonal_forecast.  NaN if forecast
                        unavailable.
        - ``sue``:      float, surprise / surprise_std.  NaN if surprise
                        is NaN or if fewer than 2 prior surprises exist.
    """
    n = len(history)
    eps_values = history["value"].to_numpy(dtype=float)
    surprises = np.full(n, np.nan, dtype=float)
    sues = np.full(n, np.nan, dtype=float)

    for i in range(n):
        lag_idx = i - seasonal_lag
        if lag_idx < 0:
            continue  # Not enough history for the seasonal forecast
        forecast = eps_values[lag_idx]
        if not np.isfinite(forecast):
            continue
        surprise_i = eps_values[i] - forecast
        surprises[i] = surprise_i

        # Compute std over trailing surprises (excluding current row i)
        start_idx = max(0, i - std_window)
        prior_surprises = surprises[start_idx:i]
        valid_prior = prior_surprises[np.isfinite(prior_surprises)]
        if len(valid_prior) >= 2:
            sigma = float(np.std(valid_prior, ddof=1))
            if sigma > 0.0:
                sues[i] = surprise_i / sigma
            # sigma == 0 -> NaN (all identical surprises, uninformative)
        # else: fewer than 2 prior surprises -> SUE is NaN (raw surprise preserved)

    out = history.copy()
    out["surprise"] = surprises
    out["sue"] = sues
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_sue_panel(
    fundamentals: pd.DataFrame,
    config: EarningsConfig | None = None,
) -> pd.DataFrame:
    """Compute SUE (Standardised Unexpected Earnings) for all symbols.

    Processes the tidy fundamental DataFrame to produce a long-format
    SUE panel.  Each row represents one quarterly EPS announcement with its
    associated SUE and filing date.  The SUE panel is the primary input to
    :func:`pead_signal`.

    Point-in-time guarantee: the ``filing_date`` column of each row is the
    as-of date from which that SUE is permissible in a backtest.  Callers
    must NOT use a row at any date earlier than its ``filing_date``.

    SUE construction follows Foster-Olsen-Shevlin (1984):
      - Expected EPS = EPS_{t - seasonal_lag} (seasonal random-walk).
      - Surprise = actual EPS - expected EPS.
      - SUE = surprise / rolling_std(historical surprises).

    Parameters
    ----------
    fundamentals:
        Tidy fundamental DataFrame produced by
        :func:`~core_trading.data.fundamentals.FundamentalSource.records_to_dataframe`
        (or equivalent).  Must contain at minimum the columns:
        ``symbol``, ``metric``, ``value``, ``period_end``, ``filing_date``,
        ``fiscal_period``.  Rows where ``metric != config.eps_metric``
        are ignored.
    config:
        ``EarningsConfig`` instance.  Defaults to ``EarningsConfig()``.

    Returns
    -------
    pd.DataFrame
        Long-format SUE panel with columns:

        - ``symbol``      : str
        - ``period_end``  : datetime64[ns]
        - ``filing_date`` : datetime64[ns]
        - ``fiscal_period``: str
        - ``eps``         : float, reported EPS.
        - ``surprise``    : float, EPS - seasonal_forecast.  NaN if forecast
                            unavailable (insufficient history).
        - ``sue``         : float, surprise / sigma.  NaN if fewer than 2
                            prior surprises or sigma == 0.

        Sorted by (``filing_date``, ``symbol``).  Empty if no EPS rows exist.

    Raises
    ------
    ValueError
        If required columns are missing from ``fundamentals``.
    """
    if config is None:
        config = EarningsConfig()

    required_cols = {"symbol", "metric", "value", "period_end", "filing_date", "fiscal_period"}
    missing = required_cols - set(fundamentals.columns)
    if missing:
        raise ValueError(f"fundamentals DataFrame missing columns: {missing}")

    symbols = fundamentals["symbol"].unique()
    parts: list[pd.DataFrame] = []

    for sym in symbols:
        history = _build_eps_history(fundamentals, sym, config.eps_metric)
        if history.empty:
            continue
        sue_history = _compute_sue_for_symbol(
            history,
            seasonal_lag=config.seasonal_lag,
            std_window=config.sue_std_window,
        )
        sue_history.insert(0, "symbol", sym)
        sue_history = sue_history.rename(columns={"value": "eps"})
        parts.append(sue_history)

    if not parts:
        return pd.DataFrame(
            columns=["symbol", "period_end", "filing_date", "fiscal_period",
                     "eps", "surprise", "sue"]
        )

    return (
        pd.concat(parts, ignore_index=True)
        .sort_values(["filing_date", "symbol"])
        .reset_index(drop=True)
    )


def pead_signal(
    sue_panel: pd.DataFrame,
    evaluation_dates: pd.DatetimeIndex,
    config: EarningsConfig | None = None,
    *,
    quantile: float = 0.2,
) -> pd.DataFrame:
    """Build the PEAD cross-sectional long/short signal from the SUE panel.

    For each evaluation date t in ``evaluation_dates``:
    1. Filter the SUE panel to rows with ``filing_date`` <= t (point-in-time).
    2. Select the most recent SUE per symbol (by ``filing_date``, then
       ``period_end`` as a tiebreaker).
    3. Cross-sectionally z-score the SUE values across all symbols that have
       a valid (non-NaN) SUE.
    4. Assign PEAD weights: long the top ``quantile`` fraction (high SUE),
       short the bottom ``quantile`` fraction (low SUE), equal-weighted within
       each leg so the long leg sums to +1 and the short leg sums to -1
       (dollar-neutral).  All other symbols receive weight 0.

    The PEAD effect (Bernard-Thomas 1989/1990) documents that high-SUE stocks
    continue to outperform low-SUE stocks over a 60-day post-announcement
    window.  The drift window is stored in ``config.pead_drift_window`` for
    use by downstream holding-period logic.

    Parameters
    ----------
    sue_panel:
        Output of :func:`compute_sue_panel`.  Must contain at minimum:
        ``symbol``, ``filing_date``, ``period_end``, ``sue``.
    evaluation_dates:
        Sorted, ascending ``DatetimeIndex`` of dates on which to evaluate
        the signal (e.g., daily business dates for a backtest).
    config:
        ``EarningsConfig`` instance.  Defaults to ``EarningsConfig()``.
    quantile:
        Fraction of the cross-section per leg.  Must be in (0, 1).
        Default 0.2 (top/bottom quintile).

    Returns
    -------
    pd.DataFrame
        Shape: (len(evaluation_dates), n_symbols) where ``n_symbols`` is the
        union of all symbols appearing in ``sue_panel``.

        - Index : ``evaluation_dates``.
        - Columns: symbol strings.
        - Values: float, PEAD weight in {-w, 0, +w} or 0 (NaN-safe; missing
          data yields 0, not NaN).

        A value of 0.0 means the symbol either has no valid SUE at t or falls
        in the middle of the cross-section.

    Raises
    ------
    ValueError
        If ``quantile`` is not in (0, 1), or if required columns are absent
        from ``sue_panel``.
    """
    if not (0.0 < quantile < 1.0):
        raise ValueError(f"quantile must be in (0, 1), got {quantile}")

    if config is None:
        config = EarningsConfig()

    required_cols = {"symbol", "filing_date", "period_end", "sue"}
    missing = required_cols - set(sue_panel.columns)
    if missing:
        raise ValueError(f"sue_panel missing columns: {missing}")

    # Ensure datetime types
    sp = sue_panel.copy()
    sp["filing_date"] = pd.to_datetime(sp["filing_date"])
    sp["period_end"] = pd.to_datetime(sp["period_end"])

    all_symbols = sorted(sp["symbol"].unique().tolist())
    n_dates = len(evaluation_dates)
    n_syms = len(all_symbols)
    sym_index = {s: i for i, s in enumerate(all_symbols)}

    weights_arr = np.zeros((n_dates, n_syms), dtype=float)

    for row_idx, eval_date in enumerate(evaluation_dates):
        # Point-in-time: only rows filed on or before eval_date
        eligible = sp[sp["filing_date"] <= eval_date]
        if eligible.empty:
            continue

        # Most recent SUE per symbol: sort by (filing_date, period_end) descending,
        # then take the first (most recent) row per symbol
        eligible_sorted = eligible.sort_values(
            ["filing_date", "period_end"], ascending=[False, False]
        )
        latest = eligible_sorted.drop_duplicates(subset=["symbol"], keep="first")

        # Keep only rows with a valid (finite) SUE
        valid = latest[np.isfinite(latest["sue"].to_numpy(dtype=float))]
        if valid.empty:
            continue

        sue_vals = valid["sue"].to_numpy(dtype=float)
        syms = valid["symbol"].tolist()
        n_valid = len(sue_vals)

        # Cross-sectional z-score
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mu = float(np.nanmean(sue_vals))
            sigma = float(np.nanstd(sue_vals, ddof=0))

        if sigma == 0.0 or not np.isfinite(sigma):
            continue  # All identical SUE -- no signal

        z_vals = (sue_vals - mu) / sigma

        # Long top quantile, short bottom quantile (equal-weighted per leg)
        n_leg = max(1, int(np.floor(n_valid * quantile)))
        if 2 * n_leg > n_valid:
            continue  # Legs would overlap

        order = np.argsort(z_vals)
        short_positions = order[:n_leg]   # lowest SUE
        long_positions = order[-n_leg:]   # highest SUE

        long_w = 1.0 / float(n_leg)
        short_w = -1.0 / float(n_leg)

        for pos in long_positions:
            col_idx = sym_index[syms[pos]]
            weights_arr[row_idx, col_idx] = long_w

        for pos in short_positions:
            col_idx = sym_index[syms[pos]]
            weights_arr[row_idx, col_idx] = short_w

    return pd.DataFrame(weights_arr, index=evaluation_dates, columns=all_symbols)
