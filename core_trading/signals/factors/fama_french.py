"""Fama-French multi-factor model (Phase 5.C.1).

This module is the canonical implementation of the Fama-French factor
construction for the RNR-IBKR-Algo-Trader quant library.  It derives the classic
1993 three-factor model (MKT, SMB, HML) extended to the 2015 five-factor model
(adding RMW and CMA) plus the UMD momentum factor, yielding a six-factor set.

Cross-sectional panel conventions
----------------------------------
A *price panel* is a ``pandas.DataFrame`` whose:
  - Index  : ascending ``DatetimeIndex`` (daily bars).
  - Columns: one column per asset symbol (strings); values are prices (floats,
    strictly positive).  NaN is permitted for unlisted / missing data.

A *fundamentals panel* is the tidy ``pandas.DataFrame`` produced by
``FundamentalSource.records_to_dataframe(records)`` with columns:
  ``symbol``, ``statement``, ``metric``, ``value``,
  ``period_end`` (date), ``filing_date`` (date),
  ``fiscal_period``, ``revision_id``, ``source``.

Point-in-time (PIT) correctness
---------------------------------
A fundamental value is admitted to the cross-section at date ``t`` ONLY when
``filing_date <= t``.  Using ``period_end`` instead of ``filing_date`` would
introduce look-ahead bias (the period-end date precedes the public disclosure
date by weeks to months).  All characteristic construction in this module
enforces the PIT cut via ``filing_date``.

Module overview
---------------
1. ``FamaFrenchConfig``        -- frozen DTO for rebalance / breakpoint / momentum
                                  parameters, with ``__post_init__`` validation.
2. ``pit_latest_value``        -- point-in-time latest filed value per
                                  (symbol, metric) as of a given date.
3. ``build_characteristic_panel`` -- wide (DatetimeIndex x symbols) characteristic
                                     panel with PIT forward-fill, for one metric.
4. ``compute_market_equity``   -- size = price * shares_outstanding.
5. ``compute_book_to_market``  -- book-to-market = book_equity / market_equity.
6. ``compute_rmw``             -- operating profitability (RMW).
7. ``compute_cma``             -- investment factor (CMA = asset growth).
8. ``form_ff_portfolios``      -- 2x3 independent-sort portfolios for one
                                  characteristic (the Fama-French breakpoint rule).
9. ``factor_returns_from_portfolios`` -- long-minus-short factor return series
                                        from a 2x3 portfolio set.
10. ``compute_umd``            -- UMD (up-minus-down) momentum factor return
                                  (12-1 month, price-only).
11. ``compute_fama_french_factors`` -- main entry point; returns a DataFrame of
                                      daily factor returns: SMB, HML, RMW, CMA,
                                      UMD (columns).

Metric name conventions
-----------------------
The fundamentals panel must contain records with the following ``metric``
string values for the factor construction to proceed:

  ``shares_outstanding`` -- number of shares (balance-sheet or share-count item)
  ``book_equity``        -- book value of equity (total equity attributable to
                            common shareholders)
  ``operating_profit``   -- operating income / EBIT used as the RMW numerator
  ``total_assets``       -- total assets used for the CMA (asset-growth) denominator

These names are conventions of this module; callers / adapters must normalise
their raw metric names to these keys before passing the fundamentals panel.

Mathematical references
-----------------------
Fama-French three-factor model (size and value):

    R_{i,t} - Rf_t = alpha_i + b_i * MKT_t + s_i * SMB_t + h_i * HML_t + e_{i,t}

where MKT = market excess return, SMB = small-minus-big (size), HML =
high-minus-low book-to-market (value).  Portfolios are formed each June using
NYSE breakpoints; here we use the full universe with periodic rebalancing.

Fama-French five-factor model (adds profitability and investment):

    Additional factors: RMW = robust-minus-weak (profitability),
                        CMA = conservative-minus-aggressive (investment).

Portfolio formation (2 x 3 independent sort):
  - Size split: median of market equity -> Small (below median) / Big (above).
  - Characteristic split: 30th / 70th percentile -> Low / Neutral / High.
  - Six value-weighted portfolios: S/L, S/N, S/H, B/L, B/N, B/H.
  - Factor return = (S/H + B/H) / 2 - (S/L + B/L) / 2  (for value-type factors)
  - SMB = (S/L + S/N + S/H) / 3 - (B/L + B/N + B/H) / 3

Momentum (UMD):
  Price-only, 12-1 month formation (252 bar lookback, 21 bar skip).
  Breakpoints: 30th / 70th percentile of cross-sectional momentum scores.
  Value-weighted within each leg.

References:
  * Fama, E.F. & French, K.R. (1993). "Common Risk Factors in the Returns on
    Stocks and Bonds."
    Journal of Financial Economics, 33(1), 3-56.

  * Fama, E.F. & French, K.R. (2015). "A Five-Factor Asset Pricing Model."
    Journal of Financial Economics, 116(1), 1-22.

  * Carhart, M.M. (1997). "On Persistence in Mutual Fund Performance."
    Journal of Finance, 52(1), 57-82.
    (UMD momentum factor.)
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from core_trading.signals.factors.momentum import (
    cross_sectional_zscore,
    long_short_weights,
    momentum_scores,
)

__all__ = [
    "FamaFrenchConfig",
    "pit_latest_value",
    "build_characteristic_panel",
    "compute_market_equity",
    "compute_book_to_market",
    "compute_rmw",
    "compute_cma",
    "form_ff_portfolios",
    "factor_returns_from_portfolios",
    "compute_umd",
    "compute_fama_french_factors",
]


# ---------------------------------------------------------------------------
# Metric name constants (public so tests and callers can reference them)
# ---------------------------------------------------------------------------

METRIC_SHARES_OUTSTANDING: str = "shares_outstanding"
METRIC_BOOK_EQUITY: str = "book_equity"
METRIC_OPERATING_PROFIT: str = "operating_profit"
METRIC_TOTAL_ASSETS: str = "total_assets"


# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamaFrenchConfig:
    """Parameters controlling Fama-French factor construction.

    Attributes
    ----------
    rebalance_freq:
        Rebalance frequency as a pandas offset alias.  The cross-section is
        re-sorted and portfolios reformed at the first date of each period.
        Common values: ``'ME'`` (month-end, default), ``'QE'`` (quarter-end),
        ``'YE'`` (year-end).  Must be a non-empty string.
    size_breakpoint_q:
        Quantile used for the size (market equity) split.  Fama-French use the
        median (0.50).  Must be strictly in (0, 1).
    char_breakpoint_lo:
        Lower quantile for the characteristic (book-to-market / profitability /
        investment) 30/70 split.  Default 0.30.  Must be strictly in (0, 1)
        and strictly less than ``char_breakpoint_hi``.
    char_breakpoint_hi:
        Upper quantile for the characteristic split.  Default 0.70.  Must be
        strictly in (0, 1) and strictly greater than ``char_breakpoint_lo``.
    momentum_lookback:
        Formation window in bars for the UMD momentum signal.  Default 252
        (approx. 12 months daily).  Must be strictly greater than
        ``momentum_skip``.
    momentum_skip:
        Recency skip in bars for UMD.  Default 21 (approx. 1 month).
        Must be >= 0.
    min_assets:
        Minimum number of assets required to form portfolios at a rebalance
        date.  If fewer assets are available (after NaN filtering), the
        rebalance date is skipped (factor return is NaN).  Default 10.
        Must be >= 4.
    """

    rebalance_freq: str = "ME"
    size_breakpoint_q: float = 0.50
    char_breakpoint_lo: float = 0.30
    char_breakpoint_hi: float = 0.70
    momentum_lookback: int = 252
    momentum_skip: int = 21
    min_assets: int = 10

    def __post_init__(self) -> None:
        """Validate all parameter constraints."""
        if not self.rebalance_freq:
            raise ValueError("rebalance_freq must be a non-empty string")
        if not (0.0 < self.size_breakpoint_q < 1.0):
            raise ValueError(
                f"size_breakpoint_q must be in (0, 1), got {self.size_breakpoint_q}"
            )
        if not (0.0 < self.char_breakpoint_lo < 1.0):
            raise ValueError(
                f"char_breakpoint_lo must be in (0, 1), got {self.char_breakpoint_lo}"
            )
        if not (0.0 < self.char_breakpoint_hi < 1.0):
            raise ValueError(
                f"char_breakpoint_hi must be in (0, 1), got {self.char_breakpoint_hi}"
            )
        if self.char_breakpoint_lo >= self.char_breakpoint_hi:
            raise ValueError(
                f"char_breakpoint_lo ({self.char_breakpoint_lo}) must be strictly "
                f"less than char_breakpoint_hi ({self.char_breakpoint_hi})"
            )
        if self.momentum_skip < 0:
            raise ValueError(
                f"momentum_skip must be >= 0, got {self.momentum_skip}"
            )
        if self.momentum_lookback <= self.momentum_skip:
            raise ValueError(
                f"momentum_lookback ({self.momentum_lookback}) must be strictly "
                f"greater than momentum_skip ({self.momentum_skip})"
            )
        if self.min_assets < 4:
            raise ValueError(
                f"min_assets must be >= 4, got {self.min_assets}"
            )


# ---------------------------------------------------------------------------
# Point-in-time helpers
# ---------------------------------------------------------------------------


def pit_latest_value(
    fundamentals: pd.DataFrame,
    as_of: date,
    metric: str,
) -> pd.Series:
    """Return the latest filed value per symbol for a metric as of a date.

    For each symbol, selects the record with the greatest ``filing_date``
    satisfying ``filing_date <= as_of``.  If multiple records share the same
    maximum ``filing_date``, the one with the largest ``revision_id`` is kept
    (most recent revision for that filing).

    Point-in-time correctness: this function enforces the PIT cut on
    ``filing_date``, NOT ``period_end``.  Using ``period_end`` as the cut
    would admit future data and introduce look-ahead bias.

    Parameters
    ----------
    fundamentals:
        Tidy fundamentals panel from
        ``FundamentalSource.records_to_dataframe()``.  Must contain columns:
        ``symbol``, ``metric``, ``value``, ``filing_date``, ``revision_id``.
    as_of:
        The date up to which filings are admitted (inclusive).  Records with
        ``filing_date > as_of`` are excluded.
    metric:
        The metric string to filter on (e.g. ``'book_equity'``).

    Returns
    -------
    pd.Series
        Index: symbol strings.  Values: latest filed ``value`` for that
        symbol / metric combination as of ``as_of``.  Symbols with no
        qualifying record are absent from the index (not NaN-filled).
    """
    if fundamentals.empty:
        return pd.Series(dtype=float)

    sub = fundamentals[
        (fundamentals["metric"] == metric)
        & (fundamentals["filing_date"] <= as_of)
    ].copy()

    if sub.empty:
        return pd.Series(dtype=float)

    sub = sub.sort_values(["symbol", "filing_date", "revision_id"])
    latest = sub.groupby("symbol").last()["value"]
    latest.name = metric
    return latest.astype(float)


def build_characteristic_panel(
    fundamentals: pd.DataFrame,
    dates: pd.DatetimeIndex,
    metric: str,
) -> pd.DataFrame:
    """Build a point-in-time wide characteristic panel for one metric.

    For each date in ``dates``, calls :func:`pit_latest_value` to obtain the
    latest filed value per symbol as of that date, then assembles a wide
    ``DataFrame`` (dates x symbols).  The value for symbol ``s`` at date ``t``
    equals the value filed on the most recent ``filing_date <= t``.

    This implements forward-filling in filing-date time, not calendar time:
    a value filed on day ``f`` is carried forward (visible) from day ``f``
    onward until a newer filing supersedes it.  No explicit ``ffill()`` call
    is needed -- the PIT query at each date naturally picks the latest
    available value.

    Parameters
    ----------
    fundamentals:
        Tidy fundamentals panel (see module docstring for column schema).
    dates:
        Ascending ``DatetimeIndex`` of dates at which the characteristic is
        evaluated.
    metric:
        The metric string to extract (e.g. ``'book_equity'``).

    Returns
    -------
    pd.DataFrame
        Wide characteristic panel.
        Index: ``dates``.
        Columns: union of all symbols that appear in ``fundamentals`` for this
        metric.
        Values: latest PIT value, or NaN if no qualifying record exists at
        that date for that symbol.
    """
    if fundamentals.empty or dates.empty:
        return pd.DataFrame(index=dates)

    rows: list[pd.Series] = []
    date_list = [d.date() for d in dates]

    for d in date_list:
        rows.append(pit_latest_value(fundamentals, d, metric))

    return pd.DataFrame(rows, index=dates)


# ---------------------------------------------------------------------------
# Characteristic computations
# ---------------------------------------------------------------------------


def compute_market_equity(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    """Compute market equity (size) as price times shares outstanding.

    Market equity at date t for symbol s:

        ME_{s,t} = price_{s,t} * shares_outstanding_{s,t}

    where ``shares_outstanding_{s,t}`` is the latest filed value as of t
    (PIT-correct, using ``filing_date``).

    Parameters
    ----------
    prices:
        Price panel (DatetimeIndex rows x symbol columns, strictly positive).
    fundamentals:
        Tidy fundamentals panel with metric ``'shares_outstanding'``.

    Returns
    -------
    pd.DataFrame
        Market equity panel, same shape as ``prices``.  NaN where price or
        shares are missing.
    """
    shares_panel = build_characteristic_panel(
        fundamentals, prices.index, METRIC_SHARES_OUTSTANDING
    )
    shares_aligned = shares_panel.reindex(
        index=prices.index, columns=prices.columns
    )
    return prices * shares_aligned


def compute_book_to_market(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    """Compute book-to-market ratio (B/M) for the HML factor.

    Book-to-market at date t for symbol s:

        BM_{s,t} = book_equity_{s,t} / market_equity_{s,t}

    where market_equity is price times shares_outstanding and book_equity is
    the latest PIT-correct filed value.

    High B/M (value) stocks are expected to earn a premium over low B/M
    (growth) stocks (Fama and French, 1993).

    Parameters
    ----------
    prices:
        Price panel.
    fundamentals:
        Tidy fundamentals panel with metrics ``'book_equity'`` and
        ``'shares_outstanding'``.

    Returns
    -------
    pd.DataFrame
        Book-to-market panel, same shape as ``prices``.
    """
    me = compute_market_equity(prices, fundamentals)
    be_panel = build_characteristic_panel(
        fundamentals, prices.index, METRIC_BOOK_EQUITY
    )
    be_aligned = be_panel.reindex(index=prices.index, columns=prices.columns)
    with np.errstate(divide="ignore", invalid="ignore"):
        return be_aligned / me


def compute_rmw(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    """Compute operating profitability (RMW characteristic) for the RMW factor.

    Operating profitability at date t for symbol s is defined as:

        OP_{s,t} = operating_profit_{s,t} / book_equity_{s,t}

    Fama and French (2015) use the ratio of annual revenues minus cost of
    goods sold, minus selling, general and administrative expenses, minus
    interest expense, scaled by book equity.  This module uses
    ``operating_profit / book_equity`` as a parsimonious approximation
    consistent with the spirit of the definition.

    Robust (high profitability) stocks are expected to earn higher returns
    than Weak (low profitability) stocks.

    Parameters
    ----------
    prices:
        Price panel (used only for its index and columns to align output).
    fundamentals:
        Tidy fundamentals panel with metrics ``'operating_profit'`` and
        ``'book_equity'``.

    Returns
    -------
    pd.DataFrame
        Operating profitability panel, same index and columns as ``prices``.
    """
    op_panel = build_characteristic_panel(
        fundamentals, prices.index, METRIC_OPERATING_PROFIT
    )
    be_panel = build_characteristic_panel(
        fundamentals, prices.index, METRIC_BOOK_EQUITY
    )
    op_aligned = op_panel.reindex(index=prices.index, columns=prices.columns)
    be_aligned = be_panel.reindex(index=prices.index, columns=prices.columns)
    with np.errstate(divide="ignore", invalid="ignore"):
        return op_aligned / be_aligned


def compute_cma(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    lag_days: int = 365,
) -> pd.DataFrame:
    """Compute investment characteristic (CMA = asset growth) for the CMA factor.

    Asset growth at date t for symbol s is:

        AG_{s,t} = total_assets_PIT(t) / total_assets_PIT(t - lag_days) - 1

    where both the current and lagged total_assets are resolved via
    point-in-time queries: ``total_assets_PIT(d)`` is the latest filed
    total_assets value with ``filing_date <= d``.  This design ensures that
    both numerator and denominator use only information available on or before
    each respective date, eliminating look-ahead bias.

    With the default ``lag_days=365``, the ratio captures annual total-assets
    growth consistent with the Fama-French (2015) investment factor definition.

    Conservative (low investment) stocks are expected to earn higher returns
    than Aggressive (high investment) stocks (Fama and French, 2015).

    Parameters
    ----------
    prices:
        Price panel.
    fundamentals:
        Tidy fundamentals panel with metric ``'total_assets'``.
    lag_days:
        Calendar-day lookback for the denominator PIT query.  Default 365
        (one year).  Must be >= 1.

    Returns
    -------
    pd.DataFrame
        Asset-growth panel, same index and columns as ``prices``.
    """
    if lag_days < 1:
        raise ValueError(
            f"lag_days must be >= 1, got {lag_days}"
        )
    ta_now = build_characteristic_panel(
        fundamentals, prices.index, METRIC_TOTAL_ASSETS
    )
    ta_now_aligned = ta_now.reindex(index=prices.index, columns=prices.columns)

    lag_td = pd.Timedelta(days=lag_days)
    lagged_dates = pd.DatetimeIndex([ts - lag_td for ts in prices.index])
    ta_lagged_panel = build_characteristic_panel(
        fundamentals, lagged_dates, METRIC_TOTAL_ASSETS
    )
    ta_lagged_panel.index = prices.index
    ta_lagged_aligned = ta_lagged_panel.reindex(
        index=prices.index, columns=prices.columns
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        return ta_now_aligned / ta_lagged_aligned - 1.0


# ---------------------------------------------------------------------------
# Portfolio construction helpers
# ---------------------------------------------------------------------------


def form_ff_portfolios(
    me: pd.Series,
    char: pd.Series,
    config: FamaFrenchConfig,
) -> dict[str, list[str]]:
    """Form the 2x3 Fama-French independent-sort portfolios for one date.

    The construction follows Fama and French (1993):
      1. Compute the size (median) breakpoint on ``me``.
      2. Compute the characteristic 30th / 70th percentile breakpoints on
         ``char`` (using the full cross-section, independent of size).
      3. Assign each asset to one of six cells: {S, B} x {L, N, H}.

    Breakpoints are computed independently (the size split and the
    characteristic split do not condition on each other), which is the
    defining feature of the Fama-French double-sort.

    Parameters
    ----------
    me:
        Market equity ``pd.Series`` (index = symbol, values = market cap).
        NaN symbols are excluded from portfolio formation.
    char:
        Characteristic ``pd.Series`` (index = symbol, same or overlapping
        symbols as ``me``).  NaN symbols are excluded.
    config:
        ``FamaFrenchConfig`` DTO providing breakpoint quantiles.

    Returns
    -------
    dict[str, list[str]]
        Keys are cell labels: ``'SL'``, ``'SN'``, ``'SH'``,
        ``'BL'``, ``'BN'``, ``'BH'``.
        Values are lists of symbol strings in each cell.
    """
    valid_syms = me.dropna().index.intersection(char.dropna().index)
    me_valid = me.loc[valid_syms]
    char_valid = char.loc[valid_syms]

    if len(valid_syms) < config.min_assets:
        return {k: [] for k in ("SL", "SN", "SH", "BL", "BN", "BH")}

    me_arr = me_valid.values.astype(float)
    char_arr = char_valid.values.astype(float)
    syms = list(valid_syms)

    size_med = float(np.nanmedian(me_arr))
    char_lo = float(np.nanpercentile(char_arr, config.char_breakpoint_lo * 100.0))
    char_hi = float(np.nanpercentile(char_arr, config.char_breakpoint_hi * 100.0))

    portfolios: dict[str, list[str]] = {
        "SL": [], "SN": [], "SH": [],
        "BL": [], "BN": [], "BH": [],
    }

    for i, sym in enumerate(syms):
        m = me_arr[i]
        c = char_arr[i]
        if not (np.isfinite(m) and np.isfinite(c)):
            continue
        size_label = "S" if m < size_med else "B"
        if c <= char_lo:
            char_label = "L"
        elif c >= char_hi:
            char_label = "H"
        else:
            char_label = "N"
        portfolios[size_label + char_label].append(sym)

    return portfolios


def factor_returns_from_portfolios(
    portfolios: dict[str, list[str]],
    me: pd.Series,
    returns: pd.Series,
) -> dict[str, float]:
    """Compute SMB and the long-short characteristic factor return for one period.

    Value-weighted return for a portfolio of symbols at a given period:

        R_{portfolio} = sum_i (w_i * r_i)  where  w_i = ME_i / sum_j ME_j

    Factor returns:

        factor = (R_{SH} + R_{BH}) / 2 - (R_{SL} + R_{BL}) / 2
        SMB    = (R_{SL} + R_{SN} + R_{SH}) / 3
               - (R_{BL} + R_{BN} + R_{BH}) / 3

    where H = high characteristic, L = low characteristic, S = small, B = big.

    Parameters
    ----------
    portfolios:
        Output of :func:`form_ff_portfolios` (symbol lists per cell).
    me:
        Market equity ``pd.Series`` used as value-weighting denominator.
        Must cover the symbols in ``portfolios``.
    returns:
        Scalar return ``pd.Series`` over the period (index = symbol).

    Returns
    -------
    dict[str, float]
        Keys: ``'factor'`` (long-short H-minus-L return), ``'smb'``
        (small-minus-big return).  Values are NaN when any required leg
        is empty.
    """
    def _vw_return(syms: list[str]) -> float:
        if not syms:
            return float("nan")
        r = returns.reindex(syms).dropna()
        m = me.reindex(r.index).dropna()
        common = r.index.intersection(m.index)
        r = r.loc[common]
        m = m.loc[common]
        if m.sum() <= 0.0 or len(r) == 0:
            return float("nan")
        w = m / m.sum()
        return float((w * r).sum())

    r_sl = _vw_return(portfolios["SL"])
    r_sn = _vw_return(portfolios["SN"])
    r_sh = _vw_return(portfolios["SH"])
    r_bl = _vw_return(portfolios["BL"])
    r_bn = _vw_return(portfolios["BN"])
    r_bh = _vw_return(portfolios["BH"])

    # The characteristic factor (H-minus-L) only requires the four extreme legs.
    # The neutral leg (SN, BN) may be empty when all cross-section members fall
    # outside the 30th-70th band, which is valid and should not produce NaN.
    if any(np.isnan(v) for v in (r_sl, r_sh, r_bl, r_bh)):
        factor_ret = float("nan")
    else:
        factor_ret = (r_sh + r_bh) / 2.0 - (r_sl + r_bl) / 2.0

    # SMB requires all six legs (the Fama-French 2015 construction).
    if any(np.isnan(v) for v in (r_sl, r_sn, r_sh, r_bl, r_bn, r_bh)):
        smb_ret = float("nan")
    else:
        smb_ret = (r_sl + r_sn + r_sh) / 3.0 - (r_bl + r_bn + r_bh) / 3.0

    return {"factor": factor_ret, "smb": smb_ret}


# ---------------------------------------------------------------------------
# UMD (momentum) factor
# ---------------------------------------------------------------------------


def compute_umd(
    prices: pd.DataFrame,
    config: FamaFrenchConfig,
    me: pd.DataFrame | None = None,
) -> pd.Series:
    """Compute the UMD (up-minus-down) momentum factor return series.

    UMD is the value-weighted return spread between high-momentum (Up) and
    low-momentum (Down) stocks, formed using 12-1 month price-only momentum.

    Construction (Carhart, 1997; Fama and French use a similar but
    equal-weighted variant):
      1. Compute cross-sectional momentum scores: 12-month return skipping
         the most recent 1 month (``lookback=252``, ``skip=21``).
      2. At each rebalance date, assign the top 30% to Up, bottom 30% to Down.
      3. Value-weight within each leg (or equal-weight when ``me`` is not
         provided).
      4. UMD_t = R_{Up,t} - R_{Down,t} for each period following a rebalance.

    When ``me`` is ``None``, equal-weighted long-short weights are used (via
    :func:`~core_trading.signals.factors.momentum.long_short_weights`), and the
    UMD return is the equal-weighted spread.

    Parameters
    ----------
    prices:
        Price panel (DatetimeIndex rows x symbol columns).
    config:
        ``FamaFrenchConfig`` providing ``momentum_lookback``,
        ``momentum_skip``, and ``rebalance_freq``.
    me:
        Optional market equity panel (same shape as ``prices``) for
        value-weighting.  When supplied, each period's UMD return is
        computed as a value-weighted long-short spread.

    Returns
    -------
    pd.Series
        Daily UMD factor returns, indexed by the price panel's DatetimeIndex.
        NaN during warmup or when the cross-section is too sparse.
    """
    scores = momentum_scores(
        prices,
        lookback=config.momentum_lookback,
        skip=config.momentum_skip,
    )

    if me is None:
        z = cross_sectional_zscore(scores)
        w = long_short_weights(z, quantile=config.char_breakpoint_lo)
        price_arr = prices.to_numpy(dtype=float)
        rets_arr = np.empty_like(price_arr)
        rets_arr[0] = np.nan
        rets_arr[1:] = price_arr[1:] / price_arr[:-1] - 1.0
        rets_df = pd.DataFrame(rets_arr, index=prices.index, columns=prices.columns)

        w_arr = w.to_numpy(dtype=float)
        r_arr = rets_df.to_numpy(dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            umd_arr = np.nansum(w_arr * r_arr, axis=1)

        umd_arr = np.where(
            np.all(w_arr == 0, axis=1) | np.all(~np.isfinite(r_arr), axis=1),
            np.nan,
            umd_arr,
        )
        return pd.Series(umd_arr, index=prices.index, name="UMD")

    rebal_dates = _rebalance_dates(prices.index, config.rebalance_freq)
    price_arr = prices.to_numpy(dtype=float)
    rets_arr = np.empty_like(price_arr)
    rets_arr[0] = np.nan
    rets_arr[1:] = price_arr[1:] / price_arr[:-1] - 1.0
    rets_df = pd.DataFrame(rets_arr, index=prices.index, columns=prices.columns)
    scores_arr = scores.to_numpy(dtype=float)

    umd_vals = np.full(len(prices), np.nan, dtype=float)
    current_weights: np.ndarray | None = None
    last_rebal_idx: int = -1

    rebal_set = set(rebal_dates)

    for t, dt in enumerate(prices.index):
        if dt in rebal_set and t > 0:
            score_row = scores_arr[t]
            me_row = me.iloc[t].values.astype(float)
            valid = np.isfinite(score_row) & np.isfinite(me_row) & (me_row > 0)
            if valid.sum() >= config.min_assets:
                n = int(valid.sum())
                n_leg = max(1, int(np.floor(n * config.char_breakpoint_lo)))
                valid_idx = np.where(valid)[0]
                sorted_by_score = valid_idx[np.argsort(score_row[valid_idx])]
                down_idx = sorted_by_score[:n_leg]
                up_idx = sorted_by_score[-n_leg:]

                w_new = np.zeros(prices.shape[1], dtype=float)
                me_up = me_row[up_idx]
                me_dn = me_row[down_idx]
                me_up_sum = me_up.sum()
                me_dn_sum = me_dn.sum()
                # Both sums are strictly positive because up_idx and down_idx
                # are drawn exclusively from indices where me_row > 0 (the
                # valid mask above).  The check is kept for defensive clarity
                # but the else branch is structurally unreachable.
                if me_up_sum > 0 and me_dn_sum > 0:
                    for idx in up_idx:
                        w_new[idx] = me_row[idx] / me_up_sum
                    for idx in down_idx:
                        w_new[idx] = -me_row[idx] / me_dn_sum
                    current_weights = w_new
                    last_rebal_idx = t

        if current_weights is not None and t > last_rebal_idx:
            r_row = rets_arr[t]
            valid_r = np.isfinite(r_row)
            if valid_r.any():
                umd_vals[t] = float(
                    np.nansum(current_weights * np.where(valid_r, r_row, 0.0))
                )

    return pd.Series(umd_vals, index=prices.index, name="UMD")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    """Return the subset of ``index`` that falls on a rebalance boundary.

    Uses ``pandas.DatetimeIndex.to_period`` to assign each date to a period
    and picks the first date in each period as the rebalance date.

    Parameters
    ----------
    index:
        Ascending ``DatetimeIndex`` of trading dates.
    freq:
        Pandas offset alias (e.g. ``'ME'``, ``'QE'``, ``'YE'``).

    Returns
    -------
    pd.DatetimeIndex
        Subset of ``index`` at rebalance points.
    """
    if index.empty:
        return pd.DatetimeIndex([])

    _PERIOD_ALIAS: dict[str, str] = {
        "ME": "M", "MS": "M",
        "QE": "Q", "QS": "Q",
        "YE": "A", "YS": "A", "AS": "A",
        "BME": "M", "BMS": "M",
    }
    period_freq = _PERIOD_ALIAS.get(freq, freq)

    try:
        periods = index.to_period(period_freq)
    except Exception:
        periods = index.to_period("M")

    seen: set[object] = set()
    rebal: list[pd.Timestamp] = []
    for ts, per in zip(index, periods, strict=False):
        if per not in seen:
            seen.add(per)
            rebal.append(ts)

    return pd.DatetimeIndex(rebal)


def _compute_one_characteristic_factor(
    prices: pd.DataFrame,
    me_panel: pd.DataFrame,
    char_panel: pd.DataFrame,
    config: FamaFrenchConfig,
    factor_name: str,
) -> tuple[pd.Series, pd.Series]:
    """Compute factor return and SMB contribution for one characteristic.

    At each rebalance date, forms 2x3 portfolios using :func:`form_ff_portfolios`,
    carries those portfolio assignments forward until the next rebalance, and
    accumulates the value-weighted return spread for the factor and SMB.

    Parameters
    ----------
    prices:
        Price panel.
    me_panel:
        Market equity panel (same shape as ``prices``).
    char_panel:
        Characteristic panel (same shape as ``prices``).
    config:
        ``FamaFrenchConfig``.
    factor_name:
        Label for the factor series (e.g. ``'HML'``).

    Returns
    -------
    tuple[pd.Series, pd.Series]
        ``(factor_series, smb_contribution_series)`` both indexed like ``prices``.
    """
    rebal_dates = _rebalance_dates(prices.index, config.rebalance_freq)
    rebal_set = set(rebal_dates)

    price_arr = prices.to_numpy(dtype=float)
    rets_arr = np.empty_like(price_arr)
    rets_arr[0] = np.nan
    rets_arr[1:] = price_arr[1:] / price_arr[:-1] - 1.0
    rets_df = pd.DataFrame(rets_arr, index=prices.index, columns=prices.columns)

    factor_vals = np.full(len(prices), np.nan, dtype=float)
    smb_vals = np.full(len(prices), np.nan, dtype=float)

    current_portfolios: dict[str, list[str]] | None = None
    last_rebal_idx: int = -1

    for t, dt in enumerate(prices.index):
        if dt in rebal_set and t > 0:
            me_row = me_panel.iloc[t]
            char_row = char_panel.iloc[t]
            current_portfolios = form_ff_portfolios(me_row, char_row, config)
            last_rebal_idx = t

        if current_portfolios is not None and t > last_rebal_idx:
            me_row = me_panel.iloc[t]
            ret_row = rets_df.iloc[t]
            result = factor_returns_from_portfolios(
                current_portfolios, me_row, ret_row
            )
            factor_vals[t] = result["factor"]
            smb_vals[t] = result["smb"]

    return (
        pd.Series(factor_vals, index=prices.index, name=factor_name),
        pd.Series(smb_vals, index=prices.index, name=f"SMB_{factor_name}"),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_fama_french_factors(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    config: FamaFrenchConfig | None = None,
) -> pd.DataFrame:
    """Compute the six Fama-French factor return series from price and fundamental data.

    This is the primary entry point for the module.  It orchestrates the full
    pipeline:

      1. Compute market equity (size) from prices and ``shares_outstanding``.
      2. Compute book-to-market, RMW, and CMA characteristics (all PIT-correct).
      3. At each rebalance date, form the 2x3 portfolios for each characteristic.
      4. Between rebalances, accumulate daily value-weighted factor returns.
      5. Average the three SMB contributions (from HML, RMW, CMA sorts) to produce
         the final SMB series (following Fama and French, 2015).
      6. Compute UMD (momentum) independently as a value-weighted long-short spread.

    The look-ahead-free guarantee:
      - Portfolio formation at rebalance date ``t`` uses only fundamentals filed
        on or before ``t`` (PIT via ``filing_date``).
      - The factor return *earned* over bar ``t`` uses the portfolio formed at the
        most recent prior rebalance date ``< t`` (not ``<= t``), so the formation
        cross-section does not overlap with the return period.

    Parameters
    ----------
    prices:
        Price panel: ascending ``DatetimeIndex`` rows x symbol-string columns.
        Values are strictly positive prices.  NaN is permitted for missing data.
    fundamentals:
        Tidy fundamentals panel from ``FundamentalSource.records_to_dataframe()``.
        Required metrics: ``'shares_outstanding'``, ``'book_equity'``,
        ``'operating_profit'``, ``'total_assets'``.
    config:
        Optional ``FamaFrenchConfig`` DTO.  If ``None``, defaults are used
        (monthly rebalance, 50/30/70 breakpoints, 252/21 momentum windows).

    Returns
    -------
    pd.DataFrame
        Daily factor return series.
        Index: same as ``prices.index``.
        Columns: ``['SMB', 'HML', 'RMW', 'CMA', 'UMD']``.
        Values are NaN during warmup or when the cross-section is too sparse.

    References
    ----------
    Fama, E.F. & French, K.R. (1993). "Common Risk Factors in the Returns on
    Stocks and Bonds." Journal of Financial Economics, 33(1), 3-56.

    Fama, E.F. & French, K.R. (2015). "A Five-Factor Asset Pricing Model."
    Journal of Financial Economics, 116(1), 1-22.
    """
    if config is None:
        config = FamaFrenchConfig()

    me_panel = compute_market_equity(prices, fundamentals)
    bm_panel = compute_book_to_market(prices, fundamentals)
    rmw_panel = compute_rmw(prices, fundamentals)
    cma_panel = compute_cma(prices, fundamentals)

    hml_series, smb_hml = _compute_one_characteristic_factor(
        prices, me_panel, bm_panel, config, "HML"
    )
    rmw_series, smb_rmw = _compute_one_characteristic_factor(
        prices, me_panel, rmw_panel, config, "RMW"
    )
    # Negate the CMA characteristic so that the "High" portfolio contains stocks
    # with LOW asset growth (conservative) and the "Low" portfolio contains stocks
    # with HIGH asset growth (aggressive).  After negation the long-minus-short
    # factor becomes conservative-minus-aggressive, matching the Fama-French (2015)
    # convention where CMA > 0 when conservative stocks earn a premium.
    cma_series, smb_cma = _compute_one_characteristic_factor(
        prices, me_panel, -cma_panel, config, "CMA"
    )

    smb_stack = np.column_stack([
        smb_hml.values.astype(float),
        smb_rmw.values.astype(float),
        smb_cma.values.astype(float),
    ])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        smb_final: np.ndarray = np.where(
            np.all(np.isfinite(smb_stack), axis=1),
            smb_stack.mean(axis=1),
            np.nan,
        )

    smb_series = pd.Series(smb_final, index=prices.index, name="SMB")

    umd_series = compute_umd(prices, config, me=me_panel)

    return pd.DataFrame(
        {
            "SMB": smb_series,
            "HML": hml_series,
            "RMW": rmw_series,
            "CMA": cma_series,
            "UMD": umd_series,
        },
        index=prices.index,
    )
