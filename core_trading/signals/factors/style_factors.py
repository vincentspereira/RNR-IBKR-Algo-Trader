"""Asness-style Quality, Value, and Low-Volatility style premia (Phase 5.C.5).

This module implements three academically-grounded style premia as
cross-sectional factor signals operating on a multi-asset price panel and
an optional tidy fundamentals frame.  Each premia generates a z-scored
characteristics panel and a dollar-neutral long/short weight panel.

Cross-sectional panel convention
---------------------------------
A *price panel* is a ``pandas.DataFrame`` with an ascending
``DatetimeIndex`` (rows) and one column per asset symbol (values are
strictly positive prices; NaN permitted for missing data).

A *fundamentals panel* is the tidy frame produced by
``FundamentalSource.records_to_dataframe``, with columns::

    symbol, statement, metric, value, period_end,
    filing_date, fiscal_period, revision_id, source

Point-in-time rule: a fundamental record for asset *i* enters the
cross-section at date *t* only if ``filing_date <= t``.  At each *t* the
most-recently-filed value (latest ``filing_date <= t``) is used.  This
avoids look-ahead bias: a quarterly 10-Q filed on 2020-05-15 is not
visible to the model on 2020-05-14.

Required fundamental metrics (as strings in the ``metric`` column)
-------------------------------------------------------------------
For the VALUE and QUALITY premia the following metrics must be present:

    net_income          -- INCOME statement; annual or TTM earnings.
    book_equity         -- BALANCE_SHEET; shareholders equity / book value.
    total_assets        -- BALANCE_SHEET; total assets.
    total_debt          -- BALANCE_SHEET; interest-bearing debt.
    operating_cashflow  -- CASH_FLOW; operating cash flow.
    revenue             -- INCOME statement; total revenue.
    gross_profit        -- INCOME statement; revenue - cost of goods sold.

Shares are not required; price-based ratios use the *price level* directly
as a per-share proxy (see VALUE score documentation below).

The LOW-VOL premia requires NO fundamentals; it works from the price
panel alone.  This makes it the first style leg that can fire in a
production system even before fundamental data is wired.

Module overview
---------------
1. ``StyleFactorConfig``   -- frozen DTO with validation.
2. ``pit_characteristic``  -- point-in-time as-of panel builder.
3. ``value_scores``        -- book/earnings/cashflow-to-price composite.
4. ``quality_scores``      -- QMJ-style profitability/leverage/stability.
5. ``lowvol_scores``       -- negative trailing realised volatility.
6. ``style_factor_weights``-- convenience: scores -> long/short weights.
7. ``style_factor_panels`` -- full pipeline: prices + fundamentals -> all.

Shared helpers imported from sibling module
-------------------------------------------
``cross_sectional_zscore`` and ``long_short_weights`` are imported from
``core_trading.signals.factors.momentum`` (already unit-tested there) to
avoid duplication.

Mathematical references
-----------------------
VALUE (book-to-price composite):
  * Fama, E.F. & French, K.R. (1992). "The Cross-Section of Expected Stock
    Returns." Journal of Finance, 47(2), 427-465.
  * Asness, C., Moskowitz, T. & Pedersen, L.H. (2013). "Value and Momentum
    Everywhere." Journal of Finance, 68(3), 929-985.

QUALITY (QMJ -- Quality Minus Junk):
  * Asness, C., Frazzini, A. & Pedersen, L.H. (2019). "Quality Minus Junk."
    Review of Accounting Studies, 24(1), 34-112.
  The quality score is a composite of profitability (ROE, gross profitability),
  leverage (negative debt-to-assets), and earnings stability (negative variance
  of trailing net income).

LOW-VOLATILITY (Betting Against Beta):
  * Frazzini, A. & Pedersen, L.H. (2014). "Betting Against Beta."
    Journal of Financial Economics, 111(1), 1-45.
  * Baker, M., Bradley, B. & Wurgler, J. (2011). "Benchmarks as Limits to
    Arbitrage: Understanding the Low-Volatility Anomaly." Financial Analysts
    Journal, 67(1), 40-54.
  Low-vol score = negative of trailing realised return volatility so that
  low-volatility assets receive high scores.
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.signals.factors.momentum import (
    cross_sectional_zscore,
    long_short_weights,
)

__all__ = [
    "StyleFactorConfig",
    "pit_characteristic",
    "value_scores",
    "quality_scores",
    "lowvol_scores",
    "style_factor_weights",
    "style_factor_panels",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StyleFactorConfig:
    """Parameters controlling the three style premia.

    Attributes
    ----------
    vol_window:
        Rolling window length (bars) for trailing realised volatility used in
        the LOW-VOL score and the risk-normalisation inside QUALITY stability.
        Must be >= 2.  Typical value: 63 (approx. 3 months daily).
    winsor_clip:
        Cross-sectional winsorisation bound applied to each raw characteristic
        *before* z-scoring.  Values outside ``[-winsor_clip, +winsor_clip]``
        standard-deviations from the cross-sectional mean are clipped.
        Must be > 0.  Typical value: 3.0 (clip at +/-3 sigma).
    value_legs:
        Ordered sequence of value sub-signal names to composite.  Each name
        must be one of ``{'book_to_price', 'earnings_to_price',
        'cashflow_to_price'}``.  At least one required.
    quality_legs:
        Ordered sequence of quality sub-signal names.  Each must be one of
        ``{'roe', 'gross_profitability', 'low_leverage', 'earnings_stability'}``.
        At least one required.
    earnings_history_window:
        Number of trailing filing observations used to estimate earnings
        stability (variance of net_income).  Must be >= 2.
    quantile:
        Fraction of the cross-section assigned to each long/short leg when
        converting scores to portfolio weights (passed to ``long_short_weights``).
        Must be in (0, 1).
    """

    vol_window: int = 63
    winsor_clip: float = 3.0
    value_legs: Sequence[str] = field(
        default_factory=lambda: ["book_to_price", "earnings_to_price", "cashflow_to_price"]
    )
    quality_legs: Sequence[str] = field(
        default_factory=lambda: ["roe", "gross_profitability", "low_leverage", "earnings_stability"]
    )
    earnings_history_window: int = 4
    quantile: float = 0.2

    _VALID_VALUE_LEGS: frozenset[str] = field(
        init=False,
        repr=False,
        compare=False,
        default=frozenset({"book_to_price", "earnings_to_price", "cashflow_to_price"}),
    )
    _VALID_QUALITY_LEGS: frozenset[str] = field(
        init=False,
        repr=False,
        compare=False,
        default=frozenset({"roe", "gross_profitability", "low_leverage", "earnings_stability"}),
    )

    def __post_init__(self) -> None:
        """Validate all parameter constraints."""
        if self.vol_window < 2:
            raise ValueError(
                f"vol_window must be >= 2, got {self.vol_window}"
            )
        if self.winsor_clip <= 0.0:
            raise ValueError(
                f"winsor_clip must be > 0, got {self.winsor_clip}"
            )
        if not self.value_legs:
            raise ValueError("value_legs must contain at least one sub-signal name")
        unknown_value = set(self.value_legs) - self._VALID_VALUE_LEGS
        if unknown_value:
            raise ValueError(
                f"Unknown value_legs: {sorted(unknown_value)}. "
                f"Valid: {sorted(self._VALID_VALUE_LEGS)}"
            )
        if not self.quality_legs:
            raise ValueError("quality_legs must contain at least one sub-signal name")
        unknown_quality = set(self.quality_legs) - self._VALID_QUALITY_LEGS
        if unknown_quality:
            raise ValueError(
                f"Unknown quality_legs: {sorted(unknown_quality)}. "
                f"Valid: {sorted(self._VALID_QUALITY_LEGS)}"
            )
        if self.earnings_history_window < 2:
            raise ValueError(
                f"earnings_history_window must be >= 2, got {self.earnings_history_window}"
            )
        if not (0.0 < self.quantile < 1.0):
            raise ValueError(
                f"quantile must be in (0, 1), got {self.quantile}"
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _winsorise_rows(arr: np.ndarray, clip_sigma: float) -> np.ndarray:
    """Clip each row of ``arr`` to ``clip_sigma`` cross-sectional std deviations.

    Parameters
    ----------
    arr:
        2-D array of shape (T, N).  May contain NaN.
    clip_sigma:
        Number of cross-sectional standard deviations beyond which values are
        clipped.  The bound is applied symmetrically around the row mean.

    Returns
    -------
    numpy.ndarray
        Winsorised copy of ``arr``, same shape.
    """
    out = arr.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        row_mean = np.nanmean(out, axis=1, keepdims=True)
        row_std = np.nanstd(out, axis=1, keepdims=True, ddof=0)
    lo = row_mean - clip_sigma * row_std
    hi = row_mean + clip_sigma * row_std
    # Only clip where bounds are finite
    valid_bounds = np.isfinite(lo) & np.isfinite(hi)
    lo_safe = np.where(valid_bounds, lo, -np.inf)
    hi_safe = np.where(valid_bounds, hi, np.inf)
    return np.clip(out, lo_safe, hi_safe)


def _composite_zscore(
    panels: list[pd.DataFrame],
    winsor_clip: float,
) -> pd.DataFrame:
    """Average multiple z-scored panels into a single composite z-score.

    For each sub-signal panel, this function:
      1. Applies cross-sectional winsorisation (``winsor_clip`` sigma clip).
      2. Applies ``cross_sectional_zscore`` to standardise across assets.
      3. Averages the z-scores across sub-signals equally.
      4. Applies a final ``cross_sectional_zscore`` to the composite.

    A cell is NaN in the output if it is NaN in *all* sub-signal panels for
    that (t, asset) position.

    Parameters
    ----------
    panels:
        List of DataFrames with identical index and columns.
    winsor_clip:
        Number of cross-sectional standard deviations for clipping.

    Returns
    -------
    pd.DataFrame
        Composite z-score panel; same index and columns as the first input.
    """
    zscored: list[np.ndarray] = []
    idx = panels[0].index
    cols = panels[0].columns
    for panel in panels:
        arr = panel.to_numpy(dtype=float)
        arr = _winsorise_rows(arr, winsor_clip)
        z_df = cross_sectional_zscore(
            pd.DataFrame(arr, index=idx, columns=cols)
        )
        zscored.append(z_df.to_numpy(dtype=float))

    stacked = np.stack(zscored, axis=0)  # (n_legs, T, N)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        composite = np.nanmean(stacked, axis=0)  # (T, N); ignores NaN legs

    all_nan_mask = np.all(~np.isfinite(stacked), axis=0)
    composite[all_nan_mask] = np.nan

    composite_df = pd.DataFrame(composite, index=idx, columns=cols)
    return cross_sectional_zscore(composite_df)


# ---------------------------------------------------------------------------
# Point-in-time characteristic builder
# ---------------------------------------------------------------------------


def pit_characteristic(
    dates: pd.DatetimeIndex,
    fundamentals: pd.DataFrame,
    metric: str,
    symbols: list[str],
) -> pd.DataFrame:
    """Build a point-in-time characteristic panel for one fundamental metric.

    For each (date t, symbol i), selects the most-recently-filed value of
    ``metric`` such that ``filing_date <= t``.  If no such record exists the
    cell is NaN.

    This is the only function that touches ``filing_date`` logic; all
    higher-level functions call this.  The forward-fill is *per-symbol*:
    once a value is filed it persists until a newer filing supersedes it.

    Parameters
    ----------
    dates:
        The index of the target price panel (DatetimeIndex, ascending).
    fundamentals:
        Tidy fundamentals frame from ``FundamentalSource.records_to_dataframe``.
        Required columns: ``symbol``, ``metric``, ``value``, ``filing_date``.
    metric:
        The ``metric`` string to extract (e.g. ``'net_income'``).
    symbols:
        Ordered list of asset symbol strings (columns of the output panel).

    Returns
    -------
    pd.DataFrame
        Panel of shape ``(len(dates), len(symbols))`` with ``dates`` as index
        and ``symbols`` as columns.  Values are floats; missing cells are NaN.
    """
    out = pd.DataFrame(np.nan, index=dates, columns=symbols)

    if fundamentals.empty:
        return out

    sub = fundamentals[fundamentals["metric"] == metric].copy()
    if sub.empty:
        return out

    sub["filing_date"] = pd.to_datetime(sub["filing_date"])

    for sym in symbols:
        sym_data = sub[sub["symbol"] == sym]
        if sym_data.empty:
            continue
        sym_data = sym_data.sort_values("filing_date")

        # For each date in the panel, find the most-recently-filed record
        # with filing_date <= date.  Use searchsorted for vectorised lookup.
        filing_dates = sym_data["filing_date"].values.astype("datetime64[ns]")
        values = sym_data["value"].values.astype(float)
        date_arr = dates.values.astype("datetime64[ns]")

        # searchsorted returns insertion point; index - 1 is the last element <= date.
        idx = np.searchsorted(filing_dates, date_arr, side="right") - 1
        valid = idx >= 0
        out.loc[dates[valid], sym] = values[idx[valid]]

    return out


# ---------------------------------------------------------------------------
# Value scores
# ---------------------------------------------------------------------------


def value_scores(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    config: StyleFactorConfig,
) -> pd.DataFrame:
    """Compute the VALUE composite z-score panel.

    The value score is the cross-sectional composite of three
    price-relative fundamental ratios, following Asness-Moskowitz-Pedersen
    (2013) and Fama-French (1992):

    1. Book-to-price (B/P):
         book_equity / price
       where ``price`` is the closing price from the price panel (used as a
       per-share proxy; assumes a consistent share-count normalisation within
       each cross-section).  High B/P = cheap (value stock).

    2. Earnings-to-price (E/P):
         net_income / price
       Negative earnings are allowed and are not zeroed out; winsorisation
       handles extreme negative values before z-scoring.

    3. Cashflow-to-price (CF/P):
         operating_cashflow / price

    Point-in-time rule: each fundamental is the most-recently-filed value
    with ``filing_date <= t`` (see ``pit_characteristic``).

    Required metrics in ``fundamentals``:
        ``book_equity``, ``net_income``, ``operating_cashflow``.

    Only the sub-signals listed in ``config.value_legs`` are included.

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex rows x symbol columns (strictly positive).
    fundamentals:
        Tidy fundamentals frame.  If empty, all output cells are NaN.
    config:
        ``StyleFactorConfig`` controlling winsorisation and sub-signal selection.

    Returns
    -------
    pd.DataFrame
        Composite value z-score panel; same index and columns as ``prices``.
    """
    dates = prices.index
    symbols = list(prices.columns)
    price_arr = prices.to_numpy(dtype=float)

    leg_panels: list[pd.DataFrame] = []
    leg_names = list(config.value_legs)

    if "book_to_price" in leg_names:
        bv = pit_characteristic(dates, fundamentals, "book_equity", symbols)
        with np.errstate(divide="ignore", invalid="ignore"):
            bp = np.where(
                np.isfinite(price_arr) & (price_arr > 0.0),
                bv.to_numpy(dtype=float) / price_arr,
                np.nan,
            )
        leg_panels.append(pd.DataFrame(bp, index=dates, columns=symbols))

    if "earnings_to_price" in leg_names:
        ni = pit_characteristic(dates, fundamentals, "net_income", symbols)
        with np.errstate(divide="ignore", invalid="ignore"):
            ep = np.where(
                np.isfinite(price_arr) & (price_arr > 0.0),
                ni.to_numpy(dtype=float) / price_arr,
                np.nan,
            )
        leg_panels.append(pd.DataFrame(ep, index=dates, columns=symbols))

    if "cashflow_to_price" in leg_names:
        cf = pit_characteristic(dates, fundamentals, "operating_cashflow", symbols)
        with np.errstate(divide="ignore", invalid="ignore"):
            cfp = np.where(
                np.isfinite(price_arr) & (price_arr > 0.0),
                cf.to_numpy(dtype=float) / price_arr,
                np.nan,
            )
        leg_panels.append(pd.DataFrame(cfp, index=dates, columns=symbols))

    # leg_panels is always non-empty here: StyleFactorConfig.__post_init__
    # enforces that value_legs contains at least one valid sub-signal name,
    # and each branch above is triggered by exactly one of those valid names.
    return _composite_zscore(leg_panels, config.winsor_clip)


# ---------------------------------------------------------------------------
# Quality scores
# ---------------------------------------------------------------------------


def quality_scores(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    config: StyleFactorConfig,
) -> pd.DataFrame:
    """Compute the QUALITY composite z-score panel (QMJ recipe).

    Implements the Quality Minus Junk composite from Asness, Frazzini and
    Pedersen (2019, Rev. Accounting Studies).  The composite is the equal-
    weighted average z-score of up to four sub-signals:

    1. ROE (Return on Equity):
         net_income / book_equity
       Higher ROE = more profitable.

    2. Gross Profitability:
         gross_profit / total_assets
       Novy-Marx (2013) gross profitability scaled by assets; higher = better.

    3. Low Leverage (negated debt-to-assets):
         -(total_debt / total_assets)
       Negated so that low-leverage firms get high scores.

    4. Earnings Stability (negated trailing earnings variance):
         -(variance of net_income over the last config.earnings_history_window
           filed observations)
       Negated so that stable earners get high scores; variance is computed on
       the sequence of point-in-time ``net_income`` values available at t.

    Only the sub-signals listed in ``config.quality_legs`` are included.

    Required metrics in ``fundamentals``:
        ``net_income``, ``book_equity``, ``gross_profit``,
        ``total_assets``, ``total_debt``.

    Parameters
    ----------
    prices:
        Price panel.  Used only for its index (dates) and columns (symbols).
        Prices themselves are not used by quality sub-signals.
    fundamentals:
        Tidy fundamentals frame.
    config:
        ``StyleFactorConfig``.

    Returns
    -------
    pd.DataFrame
        Composite quality z-score panel; same index and columns as ``prices``.
    """
    dates = prices.index
    symbols = list(prices.columns)
    leg_names = list(config.quality_legs)
    leg_panels: list[pd.DataFrame] = []

    if "roe" in leg_names:
        ni = pit_characteristic(dates, fundamentals, "net_income", symbols)
        be = pit_characteristic(dates, fundamentals, "book_equity", symbols)
        ni_arr = ni.to_numpy(dtype=float)
        be_arr = be.to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            roe = np.where(
                np.isfinite(be_arr) & (be_arr != 0.0),
                ni_arr / be_arr,
                np.nan,
            )
        leg_panels.append(pd.DataFrame(roe, index=dates, columns=symbols))

    if "gross_profitability" in leg_names:
        gp = pit_characteristic(dates, fundamentals, "gross_profit", symbols)
        ta = pit_characteristic(dates, fundamentals, "total_assets", symbols)
        gp_arr = gp.to_numpy(dtype=float)
        ta_arr = ta.to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            gpa = np.where(
                np.isfinite(ta_arr) & (ta_arr != 0.0),
                gp_arr / ta_arr,
                np.nan,
            )
        leg_panels.append(pd.DataFrame(gpa, index=dates, columns=symbols))

    if "low_leverage" in leg_names:
        td = pit_characteristic(dates, fundamentals, "total_debt", symbols)
        ta = pit_characteristic(dates, fundamentals, "total_assets", symbols)
        td_arr = td.to_numpy(dtype=float)
        ta_arr = ta.to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            lev = np.where(
                np.isfinite(ta_arr) & (ta_arr != 0.0),
                -(td_arr / ta_arr),
                np.nan,
            )
        leg_panels.append(pd.DataFrame(lev, index=dates, columns=symbols))

    if "earnings_stability" in leg_names:
        ni = pit_characteristic(dates, fundamentals, "net_income", symbols)
        ni_arr = ni.to_numpy(dtype=float)
        T, N = ni_arr.shape
        window = int(config.earnings_history_window)
        stability = np.full((T, N), np.nan, dtype=float)
        for t in range(window - 1, T):
            block = ni_arr[max(0, t - window + 1): t + 1, :]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                var = np.nanvar(block, axis=0, ddof=0)
            n_obs = np.sum(np.isfinite(block), axis=0)
            stability[t] = np.where(n_obs >= 2, -var, np.nan)
        leg_panels.append(pd.DataFrame(stability, index=dates, columns=symbols))

    # leg_panels is always non-empty here: StyleFactorConfig.__post_init__
    # enforces that quality_legs contains at least one valid sub-signal name.
    return _composite_zscore(leg_panels, config.winsor_clip)


# ---------------------------------------------------------------------------
# Low-volatility scores
# ---------------------------------------------------------------------------


def lowvol_scores(
    prices: pd.DataFrame,
    config: StyleFactorConfig,
) -> pd.DataFrame:
    """Compute the LOW-VOLATILITY z-score panel from price data alone.

    This signal requires NO fundamental data; it is the style leg that can
    fire immediately in a production system even before fundamental data is
    wired.

    The low-vol score at bar t for asset i is the negative of the trailing
    realised volatility of simple daily returns over the past
    ``config.vol_window`` bars:

        lowvol_{i,t} = -sigma_{i,t}

    where sigma_{i,t} = std(r_{i, t-vol_window+1 : t}, ddof=1).

    Return at bar t is r_{t} = price_{t} / price_{t-1} - 1.  The vol window
    ends at bar t-1 (the last *complete* return available at the close of bar t),
    which is look-ahead-free: volatility is estimated only from returns
    strictly prior to the current bar.

    After negation, low-volatility assets receive high scores and appear in
    the long leg of the resulting portfolio, consistent with the BAB anomaly
    (Frazzini & Pedersen, 2014) and the low-volatility anomaly (Baker,
    Bradley & Wurgler, 2011).

    The raw negative-vol panel is then cross-sectionally z-scored via
    ``cross_sectional_zscore`` from the momentum module.

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex rows x symbol columns (strictly positive).
        NaN prices produce NaN returns which propagate NaN vol estimates.
    config:
        ``StyleFactorConfig``; only ``vol_window`` is used by this function.

    Returns
    -------
    pd.DataFrame
        Cross-sectional z-score of negative realised volatility; same index
        and columns as ``prices``.  Rows 0 .. vol_window are NaN (warm-up).
    """
    price_arr = prices.to_numpy(dtype=float)
    T, N = price_arr.shape

    # Simple daily returns: ret[t] = price[t] / price[t-1] - 1.
    ret = np.empty((T, N), dtype=float)
    ret[0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = price_arr[1:] / price_arr[:-1] - 1.0

    window = int(config.vol_window)
    neg_vol = np.full((T, N), np.nan, dtype=float)

    # At bar t, estimate vol from returns in [t - window, t - 1].
    # This is look-ahead-free: we use only returns strictly before bar t.
    for t in range(window + 1, T):
        block = ret[t - window: t]  # shape (window, N)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sigma = np.nanstd(block, axis=0, ddof=1)
        n_obs = np.sum(np.isfinite(block), axis=0)
        neg_vol[t] = np.where(n_obs >= 2, -sigma, np.nan)

    raw = pd.DataFrame(neg_vol, index=prices.index, columns=prices.columns)
    return cross_sectional_zscore(raw)


# ---------------------------------------------------------------------------
# Portfolio weight convenience wrapper
# ---------------------------------------------------------------------------


def style_factor_weights(
    scores: pd.DataFrame,
    config: StyleFactorConfig,
) -> pd.DataFrame:
    """Convert a style scores panel to dollar-neutral long/short weights.

    Thin wrapper around ``long_short_weights`` from the momentum module,
    using ``config.quantile`` as the leg fraction.

    Parameters
    ----------
    scores:
        Cross-sectional z-score panel (output of ``value_scores``,
        ``quality_scores``, or ``lowvol_scores``).
    config:
        ``StyleFactorConfig``; ``quantile`` field is used.

    Returns
    -------
    pd.DataFrame
        Dollar-neutral long/short weights; same index and columns as ``scores``.
    """
    return long_short_weights(scores, quantile=config.quantile)


# ---------------------------------------------------------------------------
# Full pipeline convenience function
# ---------------------------------------------------------------------------


def style_factor_panels(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    config: StyleFactorConfig,
) -> dict[str, pd.DataFrame]:
    """Full pipeline: prices + fundamentals -> scores and weights for all styles.

    Chains the three style premia into a single call and returns a named
    dictionary for easy downstream consumption.

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex rows x symbol columns.
    fundamentals:
        Tidy fundamentals frame (may be empty; in that case VALUE and QUALITY
        panels will be all-NaN, but LOW-VOL will still be computed).
    config:
        ``StyleFactorConfig`` controlling all computation parameters.

    Returns
    -------
    dict[str, pd.DataFrame]
        Keys and contents:

        ``'value_scores'``    -- VALUE composite z-score panel.
        ``'value_weights'``   -- VALUE dollar-neutral long/short weights.
        ``'quality_scores'``  -- QUALITY composite z-score panel.
        ``'quality_weights'`` -- QUALITY dollar-neutral long/short weights.
        ``'lowvol_scores'``   -- LOW-VOL z-score panel.
        ``'lowvol_weights'``  -- LOW-VOL dollar-neutral long/short weights.
    """
    v_scores = value_scores(prices, fundamentals, config)
    q_scores = quality_scores(prices, fundamentals, config)
    lv_scores = lowvol_scores(prices, config)

    return {
        "value_scores": v_scores,
        "value_weights": style_factor_weights(v_scores, config),
        "quality_scores": q_scores,
        "quality_weights": style_factor_weights(q_scores, config),
        "lowvol_scores": lv_scores,
        "lowvol_weights": style_factor_weights(lv_scores, config),
    }
