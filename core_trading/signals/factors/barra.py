"""Barra MSCI USE-style cross-sectional risk factor model (Phase 5.C.2).

This module implements a cross-sectional factor model in the spirit of the
Barra MSCI United States Equity (USE) model.  At each period t, the cross-
section of asset returns is regressed on a matrix of lagged factor EXPOSURES
to produce FACTOR RETURNS and IDIOSYNCRATIC RESIDUALS.  The residuals are the
tradeable idiosyncratic alpha after the systematic risk has been stripped out.

Mathematical framework
----------------------
The cross-sectional WLS model at period t:

    r_i,t  =  sum_k  X_i,k,t-1 * f_k,t  +  u_i,t

where:
  - r_i,t   : return of asset i at period t.
  - X_i,k,t-1 : exposure of asset i to factor k as of the prior period (t-1).
  - f_k,t   : estimated factor return (unknown; estimated by WLS).
  - u_i,t   : idiosyncratic residual return.

Solved period-by-period via WLS (weights = sqrt(market cap)) using
``numpy.linalg.lstsq``.  This is equivalent to the standard GLS formula when
the idiosyncratic variances are homogeneous within the weighting scheme.

Factor structure
----------------
Two factor groups are combined column-wise into the exposure matrix X:

1. Style factors (7 columns) -- cross-sectionally z-scored at t-1:
     * SIZE      : log(market_cap)
     * VALUE     : book_value_per_share / price  (B/P ratio)
     * MOMENTUM  : 12-1 trailing return  (lookback=252, skip=21 bars)
     * VOLATILITY: trailing realized volatility of returns (annualized)
     * LIQUIDITY : log(1 + dollar_volume / price)  [Amihud turnover proxy]
     * LEVERAGE  : total_debt / total_assets
     * GROWTH    : year-over-year growth of total_assets

2. Industry factors -- identification via market factor + drop-one dummies.

Industry dummy identification (collinearity handling)
-----------------------------------------------------
A full set of 0/1 industry dummies is rank-deficient when combined with a
market factor (intercept-equivalent) because the dummy columns sum to a
constant.  Standard identification choices:

  Option A  (Barra-style): Include a market factor (column of 1s) plus ONE
            dummy per industry EXCEPT a chosen base industry (drop-one).
            Result: f_market captures the average return; f_ind_k captures
            the incremental return of industry k vs the base.

  Option B: No market factor, include ALL industry dummies.  The model is
            identified but factor returns are industry-average returns.

This module uses **Option A** (default): a market factor column is prepended,
and the industry with the highest frequency of appearances across the panel is
designated as the base and dropped.  The base industry name is stored in
``BarraResult.base_industry`` for transparency.

Required fundamental metrics (columns in the tidy fundamentals DataFrame)
--------------------------------------------------------------------------
The following metric names are looked up in the ``fundamentals`` panel passed
to :func:`build_style_exposures`.  The caller must ensure these metric names
exist in the ``metric`` column of the tidy frame:

  * ``book_value_per_share``   -- balance sheet; annual or most-recent quarter.
  * ``total_assets``           -- balance sheet; for Leverage and Growth.
  * ``total_debt``             -- balance sheet; total interest-bearing debt.

Market-cap inputs must be provided as the ``market_cap`` panel (prices x
shares_outstanding, computed externally).

Module overview
---------------
1. ``BarraConfig``            -- frozen DTO for model parameters + validation.
2. ``BarraResult``            -- frozen DTO holding fitted outputs.
3. ``build_style_exposures``  -- style factor exposure matrix (T x N panel).
4. ``build_industry_exposures`` -- 0/1 industry dummies with drop-one rule.
5. ``fit_barra``              -- main entry: fits the full model panel.
6. ``idiosyncratic_returns``  -- convenience extractor from BarraResult.

References
----------
* Grinold, R.C. & Kahn, R.N. (1999). "Active Portfolio Management." 2nd ed.
  McGraw-Hill.  -- Barra USE model specification.
* Barra (2004). "United States Equity Model Version 3 (USE3)."  MSCI Barra.
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning."
  Wiley.  -- feature importance + factor attribution (Chapters 6-8).
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from core_trading.signals.factors.momentum import cross_sectional_zscore

__all__ = [
    "BarraConfig",
    "BarraResult",
    "build_style_exposures",
    "build_industry_exposures",
    "fit_barra",
    "idiosyncratic_returns",
]

# ---------------------------------------------------------------------------
# Reference-data protocol (structural subtyping for ReferenceData)
# ---------------------------------------------------------------------------


class _ReferenceDataProtocol(Protocol):
    """Structural interface required by this module from the reference store.

    Any object that implements ``industry_of(symbol, as_of)`` satisfies this
    protocol.  ``core_trading.data.reference.ReferenceData`` is the canonical
    implementation.
    """

    def industry_of(self, symbol: str, as_of: date | None = None) -> str | None:
        """Return the industry string for ``symbol`` as of ``as_of``."""
        ...


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQRT_252: float = float(np.sqrt(252.0))  # annualisation factor for daily vol

# Default style factor names in exposure-matrix column order.
_STYLE_FACTOR_NAMES: tuple[str, ...] = (
    "SIZE",
    "VALUE",
    "MOMENTUM",
    "VOLATILITY",
    "LIQUIDITY",
    "LEVERAGE",
    "GROWTH",
)

# Fundamental metric names required from the tidy DataFrame.
# These must appear in the ``metric`` column of the fundamentals frame.
_METRIC_BOOK_VALUE_PER_SHARE: str = "book_value_per_share"
_METRIC_TOTAL_ASSETS: str = "total_assets"
_METRIC_TOTAL_DEBT: str = "total_debt"

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarraConfig:
    """Parameters for the Barra-style cross-sectional factor model.

    Attributes
    ----------
    momentum_lookback:
        Formation window in bars for the momentum style factor.
        Must be strictly greater than ``momentum_skip``.
        Default 252 (~12 months of daily bars).
    momentum_skip:
        Recency skip in bars for momentum (removes short-term reversal).
        Must be >= 0.  Default 21 (~1 month of daily bars).
    vol_window:
        Rolling window in bars for trailing realized volatility.
        Must be >= 2.  Default 60 (~3 months of daily bars).
    liquidity_window:
        Rolling window in bars for the dollar-volume liquidity proxy.
        Must be >= 1.  Default 21 (~1 month of daily bars).
    style_factors:
        Tuple of style factor names to include.  Must be a non-empty
        subset of the seven canonical names.
    weight_scheme:
        How to weight observations in the cross-sectional WLS regression.
        ``"sqrt_mcap"`` uses sqrt(market_cap) weights (default).
        ``"equal"`` uses unit weights (equivalent to OLS).
    include_market_factor:
        If ``True`` (default), prepend a market factor (column of 1s) and
        drop one base industry dummy.  If ``False``, include all industry
        dummies and omit the market factor (Option B identification).
    """

    momentum_lookback: int = 252
    momentum_skip: int = 21
    vol_window: int = 60
    liquidity_window: int = 21
    style_factors: tuple[str, ...] = _STYLE_FACTOR_NAMES
    weight_scheme: str = "sqrt_mcap"
    include_market_factor: bool = True

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.momentum_skip < 0:
            raise ValueError(
                f"BarraConfig.momentum_skip must be >= 0, got {self.momentum_skip}"
            )
        if self.momentum_lookback <= self.momentum_skip:
            raise ValueError(
                f"BarraConfig.momentum_lookback ({self.momentum_lookback}) must be "
                f"strictly greater than momentum_skip ({self.momentum_skip})"
            )
        if self.vol_window < 2:
            raise ValueError(
                f"BarraConfig.vol_window must be >= 2, got {self.vol_window}"
            )
        if self.liquidity_window < 1:
            raise ValueError(
                f"BarraConfig.liquidity_window must be >= 1, got {self.liquidity_window}"
            )
        if not self.style_factors:
            raise ValueError("BarraConfig.style_factors must not be empty")
        invalid = set(self.style_factors) - set(_STYLE_FACTOR_NAMES)
        if invalid:
            raise ValueError(
                f"BarraConfig.style_factors contains unknown names: {sorted(invalid)}. "
                f"Valid names are: {sorted(_STYLE_FACTOR_NAMES)}"
            )
        if self.weight_scheme not in ("sqrt_mcap", "equal"):
            raise ValueError(
                f"BarraConfig.weight_scheme must be 'sqrt_mcap' or 'equal', "
                f"got '{self.weight_scheme}'"
            )


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarraResult:
    """Output of a fitted Barra cross-sectional model.

    Attributes
    ----------
    factor_returns:
        DataFrame of shape (T, K) where T is the number of fitted periods
        and K is the total number of factors (style + industry factors).
        Columns are factor names; index matches the input returns index.
        The first column is ``MARKET`` when ``include_market_factor=True``.
        Rows before the warm-up period (insufficient history) are NaN.
    residual_returns:
        DataFrame of shape (T, N) where N is the number of assets.
        Contains u_i,t -- the idiosyncratic returns after factor attribution.
        Rows before the warm-up period are NaN.
    exposures:
        Dictionary mapping period date/timestamp to the (N, K) exposure
        array used for that period's regression.  Only periods with a valid
        regression are included.
    factor_names:
        Ordered tuple of factor column names (style factors then industry
        factors in sorted order).
    asset_names:
        Ordered tuple of asset column names.
    base_industry:
        The industry name that was dropped as the collinearity base.
        ``None`` when ``include_market_factor=False`` (all dummies included).
    config:
        The ``BarraConfig`` used to produce this result.
    """

    factor_returns: pd.DataFrame = field(compare=False)
    residual_returns: pd.DataFrame = field(compare=False)
    exposures: dict[object, np.ndarray] = field(compare=False)
    factor_names: tuple[str, ...]
    asset_names: tuple[str, ...]
    base_industry: str | None
    config: BarraConfig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pit_latest_fundamental(
    fundamentals: pd.DataFrame,
    symbol: str,
    metric: str,
    as_of: date,
) -> float | None:
    """Return the most-recently-filed value of ``metric`` for ``symbol`` as of ``as_of``.

    Point-in-time rule: only records with ``filing_date <= as_of`` are
    considered.  Among those, the record with the most recent ``filing_date``
    is returned.  If multiple records share the latest filing date, the one
    with the highest ``revision_id`` wins.

    Returns ``None`` if no qualifying record exists.

    Parameters
    ----------
    fundamentals:
        Tidy fundamentals DataFrame with columns:
        symbol, statement, metric, value, period_end, filing_date,
        fiscal_period, revision_id, source.
    symbol:
        Asset identifier.
    metric:
        Fundamental metric name.
    as_of:
        Point-in-time cutoff date (inclusive).

    Returns
    -------
    float or None
    """
    mask = (
        (fundamentals["symbol"] == symbol)
        & (fundamentals["metric"] == metric)
        & (fundamentals["filing_date"] <= as_of)
    )
    sub = fundamentals.loc[mask]
    if sub.empty:
        return None
    # Sort by filing_date desc, then revision_id desc; take the first row.
    sub_sorted = sub.sort_values(
        ["filing_date", "revision_id"], ascending=[False, False]
    )
    return float(sub_sorted.iloc[0]["value"])


def _rolling_vol(
    prices: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """Compute trailing annualized realized volatility at each bar.

    At bar t the volatility is estimated from returns over
    [t - window, t - 1] (look-ahead-free).  Returns are simple daily
    returns.  The result is annualized by multiplying by sqrt(252).

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex x assets.
    window:
        Number of bars for the rolling window (>= 2).

    Returns
    -------
    pd.DataFrame
        Annualized vol panel; same shape as ``prices``.
    """
    price_arr = prices.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret_arr = np.empty_like(price_arr)
        ret_arr[0] = np.nan
        ret_arr[1:] = price_arr[1:] / price_arr[:-1] - 1.0

    ret_df = pd.DataFrame(ret_arr, index=prices.index, columns=prices.columns)
    # Shift by 1 so the window at t covers [t-window, t-1].
    shifted = ret_df.shift(1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return shifted.rolling(window=window, min_periods=window).std() * _SQRT_252


def _rolling_liquidity(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """Compute the rolling-average log-dollar-volume as a liquidity proxy.

    Liquidity exposure = log(1 + mean(price * volume, window)),
    computed at t-1 (shifted by 1).

    Parameters
    ----------
    prices:
        Price panel.
    volumes:
        Volume panel aligned to ``prices`` (same index, same columns).
    window:
        Rolling window in bars.

    Returns
    -------
    pd.DataFrame
        Liquidity exposure panel; same shape as ``prices``.
    """
    price_arr = prices.to_numpy(dtype=float)
    vol_arr = volumes.to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        dollar_vol = price_arr * vol_arr
    dv_df = pd.DataFrame(
        dollar_vol, index=prices.index, columns=prices.columns
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        roll_dv = dv_df.rolling(window=window, min_periods=window).mean()
    roll_dv_shifted = roll_dv.shift(1)
    with np.errstate(invalid="ignore"):
        liq = np.log1p(
            np.where(
                np.isfinite(roll_dv_shifted.to_numpy()),
                roll_dv_shifted.to_numpy(),
                np.nan,
            )
        )
    return pd.DataFrame(liq, index=prices.index, columns=prices.columns)


# ---------------------------------------------------------------------------
# Public API: exposure construction
# ---------------------------------------------------------------------------


def build_style_exposures(
    prices: pd.DataFrame,
    market_cap: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame,
    config: BarraConfig,
) -> dict[str, pd.DataFrame]:
    """Construct cross-sectionally z-scored style factor exposures.

    Each style factor exposure is computed in levels (pre-z-score) from the
    price panel, market-cap panel, volume panel, and fundamentals tidy frame,
    then standardised row-wise (across assets) via :func:`cross_sectional_zscore`
    imported from ``momentum.py``.

    The exposure at period t is look-ahead-free: it uses only information
    available at t-1 (prices up to t-1, fundamentals with filing_date <= t-1).

    Fundamental-based exposures (VALUE, LEVERAGE, GROWTH) are computed per-
    period from the point-in-time fundamentals and are intentionally constant
    between filing dates -- this is the correct PIT behaviour.

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex x asset columns, positive floats.
    market_cap:
        Market-cap panel: same shape as ``prices``.  Values are
        price * shares_outstanding (or price if shares not available).
    volumes:
        Volume panel: same shape as ``prices``.  Share counts traded per bar.
    fundamentals:
        Tidy fundamentals DataFrame produced by
        ``FundamentalSource.records_to_dataframe``.  Columns:
        symbol, statement, metric, value, period_end, filing_date,
        fiscal_period, revision_id, source.
        Required metric names: ``book_value_per_share``, ``total_assets``,
        ``total_debt``.  Missing metrics produce NaN exposures for the
        affected assets on each period.
    config:
        ``BarraConfig`` instance governing window lengths and which style
        factors to include.

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping from style factor name (e.g. ``"SIZE"``) to a z-scored
        exposure DataFrame of the same shape as ``prices``.
        Only factors listed in ``config.style_factors`` are included.

    Raises
    ------
    ValueError
        If ``prices``, ``market_cap``, and ``volumes`` do not share the same
        shape or if they contain no rows.
    """
    if prices.shape != market_cap.shape or prices.shape != volumes.shape:
        raise ValueError(
            "prices, market_cap, and volumes must have the same shape; "
            f"got prices={prices.shape}, market_cap={market_cap.shape}, "
            f"volumes={volumes.shape}"
        )
    if prices.empty:
        raise ValueError("prices panel is empty")

    symbols: list[str] = [str(c) for c in prices.columns]
    index = prices.index
    T = len(index)

    requested = set(config.style_factors)
    exposures: dict[str, pd.DataFrame] = {}

    # --- SIZE: log market cap at t-1 ---
    if "SIZE" in requested:
        mc_arr = market_cap.to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            log_mc = np.where(mc_arr > 0.0, np.log(mc_arr), np.nan)
        log_mc_df = pd.DataFrame(
            np.full_like(log_mc, np.nan), index=index, columns=prices.columns
        )
        log_mc_df.iloc[1:] = log_mc[:-1]  # shift by 1
        exposures["SIZE"] = cross_sectional_zscore(log_mc_df)

    # --- MOMENTUM: 12-1 trailing return, standardised ---
    if "MOMENTUM" in requested:
        from core_trading.signals.factors.momentum import momentum_scores

        raw_mom = momentum_scores(
            prices,
            lookback=config.momentum_lookback,
            skip=config.momentum_skip,
        )
        # The score at t already uses prices up to t-skip (look-ahead-free).
        # Shift by 1 to ensure t-1 exposure.
        raw_mom_shifted = raw_mom.shift(1)
        exposures["MOMENTUM"] = cross_sectional_zscore(raw_mom_shifted)

    # --- VOLATILITY: trailing annualized realized vol at t-1 ---
    if "VOLATILITY" in requested:
        vol_df = _rolling_vol(prices, config.vol_window)
        vol_shifted = vol_df.shift(1)
        # Invert so higher vol = lower (safer) exposure; z-score after invert.
        # We keep the raw vol (not inverted) -- the sign convention is that
        # high-volatility stocks have high VOLATILITY exposure.
        exposures["VOLATILITY"] = cross_sectional_zscore(vol_shifted)

    # --- LIQUIDITY: log-dollar-volume rolling average ---
    if "LIQUIDITY" in requested:
        liq_df = _rolling_liquidity(prices, volumes, config.liquidity_window)
        # _rolling_liquidity already shifts by 1 internally.
        exposures["LIQUIDITY"] = cross_sectional_zscore(liq_df)

    # --- VALUE, LEVERAGE, GROWTH: fundamental-based, built period by period ---
    need_fundamentals = requested & {"VALUE", "LEVERAGE", "GROWTH"}
    if need_fundamentals and not fundamentals.empty:
        # Convert filing_date to date objects for PIT comparisons.
        fund_df = fundamentals.copy()
        if not pd.api.types.is_object_dtype(fund_df["filing_date"]):
            fund_df["filing_date"] = pd.to_datetime(
                fund_df["filing_date"]
            ).dt.date
        else:
            fund_df["filing_date"] = fund_df["filing_date"].apply(
                lambda x: x if isinstance(x, date) else pd.Timestamp(x).date()
            )

        val_rows: list[list[float]] = []
        lev_rows: list[list[float]] = []
        grw_rows: list[list[float]] = []

        price_arr = prices.to_numpy(dtype=float)

        for t_idx in range(T):
            ts = index[t_idx]
            # Use t-1's date as the PIT cutoff.
            if t_idx == 0:
                pit_date = pd.Timestamp(ts).date()
            else:
                pit_date = pd.Timestamp(index[t_idx - 1]).date()

            val_row: list[float] = []
            lev_row: list[float] = []
            grw_row: list[float] = []

            for sym_idx, sym in enumerate(symbols):
                price_now = float(price_arr[t_idx, sym_idx])

                # VALUE: book-to-price
                if "VALUE" in need_fundamentals:
                    bvps = _pit_latest_fundamental(
                        fund_df, sym, _METRIC_BOOK_VALUE_PER_SHARE, pit_date
                    )
                    if bvps is not None and price_now > 0.0 and np.isfinite(price_now):
                        val_row.append(bvps / price_now)
                    else:
                        val_row.append(float("nan"))

                # LEVERAGE: total_debt / total_assets
                if "LEVERAGE" in need_fundamentals:
                    td = _pit_latest_fundamental(
                        fund_df, sym, _METRIC_TOTAL_DEBT, pit_date
                    )
                    ta = _pit_latest_fundamental(
                        fund_df, sym, _METRIC_TOTAL_ASSETS, pit_date
                    )
                    if td is not None and ta is not None and ta > 0.0:
                        lev_row.append(td / ta)
                    else:
                        lev_row.append(float("nan"))

                # GROWTH: YoY change in total_assets (requires two readings)
                if "GROWTH" in need_fundamentals:
                    ta_now = _pit_latest_fundamental(
                        fund_df, sym, _METRIC_TOTAL_ASSETS, pit_date
                    )
                    grw_row.append(
                        float("nan") if ta_now is None else float(ta_now)
                    )

            if "VALUE" in need_fundamentals:
                val_rows.append(val_row)
            if "LEVERAGE" in need_fundamentals:
                lev_rows.append(lev_row)
            if "GROWTH" in need_fundamentals:
                grw_rows.append(grw_row)

        if "VALUE" in need_fundamentals:
            val_df = pd.DataFrame(val_rows, index=index, columns=prices.columns)
            exposures["VALUE"] = cross_sectional_zscore(val_df)

        if "LEVERAGE" in need_fundamentals:
            lev_df = pd.DataFrame(lev_rows, index=index, columns=prices.columns)
            exposures["LEVERAGE"] = cross_sectional_zscore(lev_df)

        if "GROWTH" in need_fundamentals:
            grw_arr = np.array(grw_rows, dtype=float)
            # YoY growth requires two PIT readings one year apart.
            # Approximate by comparing current filing to one 252 bars ago.
            grw_shifted = pd.DataFrame(
                grw_arr, index=index, columns=prices.columns
            ).shift(252)
            ta_now_df = pd.DataFrame(
                grw_arr, index=index, columns=prices.columns
            )
            with np.errstate(divide="ignore", invalid="ignore"):
                growth_raw = np.where(
                    (grw_shifted.to_numpy() > 0.0)
                    & np.isfinite(grw_shifted.to_numpy()),
                    ta_now_df.to_numpy() / grw_shifted.to_numpy() - 1.0,
                    np.nan,
                )
            grw_df = pd.DataFrame(growth_raw, index=index, columns=prices.columns)
            exposures["GROWTH"] = cross_sectional_zscore(grw_df)

    elif need_fundamentals and fundamentals.empty:
        # No fundamental data: return NaN panels for fundamental-based factors.
        nan_df = pd.DataFrame(
            np.full(prices.shape, np.nan), index=index, columns=prices.columns
        )
        for fname in need_fundamentals:
            exposures[fname] = nan_df.copy()

    # Return only factors that were requested and built.
    return {k: v for k, v in exposures.items() if k in requested}


def build_industry_exposures(
    symbols: Sequence[str],
    as_of: date,
    reference: _ReferenceDataProtocol,
    include_market_factor: bool = True,
) -> tuple[pd.DataFrame, list[str], str | None]:
    """Build 0/1 industry dummy exposures with the drop-one identification.

    Calls ``reference.industry_of(symbol, as_of)`` for each symbol to obtain
    the as-of-correct industry assignment.  Symbols with no industry assignment
    receive no dummy column contribution (all zeros).

    Identification choice (Option A)
    ---------------------------------
    When ``include_market_factor=True``, the market factor column (all-1s) is
    prepended and the most-frequent industry is designated as the base and
    dropped.  This ensures the design matrix is full-rank: the market factor
    captures the cross-sectional average return; each industry dummy captures
    the incremental return vs the base industry.

    When ``include_market_factor=False`` (Option B), all industry dummies are
    included with no market factor.  The regression is identified because the
    dummies sum to a vector of 0s and 1s (not a constant 1 vector) whenever at
    least one symbol has no industry assignment (all-zero row).  In practice,
    callers using Option B must ensure the design matrix is full-rank.

    Parameters
    ----------
    symbols:
        Ordered sequence of asset identifiers matching the returns panel.
    as_of:
        Point-in-time date for the industry lookup.
    reference:
        A ``ReferenceData`` instance (or any object with an
        ``industry_of(symbol, as_of)`` method).
    include_market_factor:
        See module docstring identification discussion.

    Returns
    -------
    (dummy_df, factor_names, base_industry)
        dummy_df    : DataFrame of shape (N, K_ind) with index=symbols.
        factor_names: list of column names; starts with ``"MARKET"`` when
                      ``include_market_factor=True``.
        base_industry: the dropped industry name, or ``None``.
    """
    n = len(symbols)
    industries: list[str | None] = []
    for sym in symbols:
        ind = reference.industry_of(sym, as_of)
        industries.append(ind)

    unique_industries = sorted(
        set(ind for ind in industries if ind is not None)
    )

    if not unique_industries:
        # No industry data at all: return empty dummy block.
        empty_df = pd.DataFrame(index=symbols, dtype=float)
        return empty_df, [], None

    # Count frequencies to find base.
    from collections import Counter

    freq = Counter(ind for ind in industries if ind is not None)
    base_industry: str | None = None

    if include_market_factor:
        base_industry = freq.most_common(1)[0][0]
        industry_columns = [
            ind for ind in unique_industries if ind != base_industry
        ]
    else:
        industry_columns = unique_industries

    # Build dummy matrix.
    dummy_arr = np.zeros((n, len(industry_columns)), dtype=float)
    for row_idx, ind in enumerate(industries):
        if ind is None:
            continue
        if ind in industry_columns:
            col_idx = industry_columns.index(ind)
            dummy_arr[row_idx, col_idx] = 1.0

    factor_names: list[str] = []
    cols: list[np.ndarray] = []

    if include_market_factor:
        market_col = np.ones((n, 1), dtype=float)
        cols.append(market_col)
        factor_names.append("MARKET")

    if industry_columns:
        cols.append(dummy_arr)
        factor_names.extend([f"IND_{ind}" for ind in industry_columns])

    # cols is guaranteed non-empty: either include_market_factor=True appended a
    # market column, or industry_columns is non-empty (Option B always has at least
    # one industry because unique_industries is non-empty after the early-return guard).
    full_arr = np.hstack(cols)

    dummy_df = pd.DataFrame(full_arr, index=list(symbols), columns=factor_names)
    return dummy_df, factor_names, base_industry


# ---------------------------------------------------------------------------
# Main model fitting entry point
# ---------------------------------------------------------------------------


def fit_barra(
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    market_cap: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame,
    reference: _ReferenceDataProtocol,
    config: BarraConfig | None = None,
) -> BarraResult:
    """Fit the Barra-style cross-sectional factor model over a full panel.

    At each period t the following steps are performed:

    1. Assemble the exposure matrix X_t from lagged style exposures and
       as-of-correct industry dummies (T-1 exposures used for regression at T).
    2. Solve the WLS regression: r_t = X_t @ f_t + u_t.
    3. Store factor returns f_t and residual returns u_t.

    Periods without a valid cross-section (fewer than K+1 assets with
    complete exposures and returns) are skipped and produce NaN rows.

    Parameters
    ----------
    returns:
        Returns panel: DatetimeIndex x asset columns, simple or log returns.
        NaN values are permitted; assets with NaN return at period t are
        excluded from that period's regression.
    prices:
        Price panel: same shape and alignment as ``returns``.
    market_cap:
        Market-cap panel: same shape as ``returns``.
    volumes:
        Volume panel: same shape as ``returns``.
    fundamentals:
        Tidy fundamentals DataFrame (see :func:`build_style_exposures`).
    reference:
        ``ReferenceData`` instance for industry lookups.
    config:
        ``BarraConfig``; defaults to ``BarraConfig()`` if ``None``.

    Returns
    -------
    BarraResult
        Fitted model outputs including factor_returns, residual_returns,
        exposures dict, factor_names, asset_names, base_industry, and config.

    Raises
    ------
    ValueError
        If ``returns``, ``prices``, ``market_cap``, ``volumes`` do not have
        the same shape, or if the panel has fewer than 2 assets.
    """
    if config is None:
        config = BarraConfig()

    if (
        returns.shape != prices.shape
        or returns.shape != market_cap.shape
        or returns.shape != volumes.shape
    ):
        raise ValueError(
            "returns, prices, market_cap, volumes must all have the same shape"
        )
    if returns.shape[1] < 2:
        raise ValueError(
            f"Panel must have at least 2 assets; got {returns.shape[1]}"
        )

    symbols: tuple[str, ...] = tuple(str(c) for c in returns.columns)
    index = returns.index
    T, N = returns.shape

    # Build style exposures (full-panel, look-ahead-free).
    style_exp_dict = build_style_exposures(
        prices, market_cap, volumes, fundamentals, config
    )

    # Collect style factor arrays in canonical order.
    style_names_ordered = [
        f for f in config.style_factors if f in style_exp_dict
    ]
    style_arrs: dict[str, np.ndarray] = {
        name: style_exp_dict[name].to_numpy(dtype=float)
        for name in style_names_ordered
    }

    # Pre-compute industry exposures for each unique (as-of date, industry set).
    # We recompute per period because industry assignments can change.
    # For efficiency, cache by date (most periods share the same date's lookup).
    _ind_cache: dict[date, tuple[pd.DataFrame, list[str], str | None]] = {}

    def _get_industry_exp(
        pit: date,
    ) -> tuple[pd.DataFrame, list[str], str | None]:
        if pit not in _ind_cache:
            _ind_cache[pit] = build_industry_exposures(
                symbols, pit, reference, config.include_market_factor
            )
        return _ind_cache[pit]

    # Determine full factor name list from first valid period.
    # We do a dry run on the first timestamp to determine industry factor names.
    _first_pit = pd.Timestamp(index[0]).date() if T > 0 else date.today()
    _, ind_factor_names_first, base_ind_first = _get_industry_exp(_first_pit)

    all_factor_names: tuple[str, ...] = tuple(
        list(style_names_ordered) + ind_factor_names_first
    )
    K = len(all_factor_names)

    # Output arrays.
    f_returns_arr = np.full((T, K), np.nan, dtype=float)
    u_returns_arr = np.full((T, N), np.nan, dtype=float)
    exposures_out: dict[object, np.ndarray] = {}

    ret_arr = returns.to_numpy(dtype=float)

    for t in range(T):
        ts = index[t]
        pit = pd.Timestamp(ts).date()

        # --- Assemble exposure matrix for period t ---
        # Style: use t-idx row directly (already shifted/lagged in build_style_exposures).
        # Track which canonical factor indices are ACTIVE at this period.
        # A style column is inactive if it is entirely NaN at period t
        # (e.g., during warm-up or when no cross-sectional variation exists).
        style_cols: list[np.ndarray] = []     # (N, 1) arrays for active style factors
        active_style_indices: list[int] = []  # indices into all_factor_names

        for s_local_idx, sname in enumerate(style_names_ordered):
            col_t = style_arrs[sname][t, :]  # (N,)
            # If the entire column is NaN, skip this style factor this period.
            if not np.any(np.isfinite(col_t)):
                continue
            style_cols.append(col_t.reshape(-1, 1))
            active_style_indices.append(s_local_idx)

        ind_df, ind_fnames, base_ind_t = _get_industry_exp(pit)

        # If industry factor names differ from the canonical (e.g. new industry
        # appeared), skip this period to avoid shape mismatch.
        if ind_fnames != ind_factor_names_first:
            continue

        ind_block = ind_df.to_numpy(dtype=float)  # (N, K_ind)

        # Active factor indices in all_factor_names for industry columns.
        n_style_total = len(style_names_ordered)
        active_ind_indices = list(
            range(n_style_total, n_style_total + len(ind_factor_names_first))
        )

        if style_cols:
            style_block = np.hstack(style_cols)  # (N, K_style_active)
            X_full = np.hstack([style_block, ind_block])  # (N, K_active)
        else:
            X_full = ind_block  # (N, K_ind)

        active_indices = active_style_indices + active_ind_indices
        K_active = len(active_indices)

        # Returns vector at t.
        r_t = ret_arr[t, :]  # (N,)

        # Mask: keep assets with finite return AND finite exposures in all active columns.
        valid_mask = np.isfinite(r_t) & np.all(np.isfinite(X_full), axis=1)
        n_valid = int(valid_mask.sum())

        # Need at least K_active + 1 observations for an identified regression.
        if n_valid <= K_active or K_active == 0:
            continue

        X_t = X_full[valid_mask, :]  # (n_valid, K_active)
        r_t_valid = r_t[valid_mask]  # (n_valid,)

        # Weights: sqrt(market_cap) at t-1, or equal.
        if config.weight_scheme == "sqrt_mcap":
            mc_arr_t = market_cap.to_numpy(dtype=float)
            mc_t = mc_arr_t[0, :] if t == 0 else mc_arr_t[t - 1, :]
            raw_w = np.where(
                np.isfinite(mc_t) & (mc_t > 0.0), np.sqrt(mc_t), 1.0
            )
            w_valid = raw_w[valid_mask]
        else:
            w_valid = np.ones(n_valid, dtype=float)

        # Normalise weights to sum to n_valid (keeps the scale comparable to OLS).
        # w_valid is always positive (sqrt_mcap falls back to 1.0; equal=all-ones),
        # so w_sum > 0 is guaranteed.
        w_sum = float(w_valid.sum())
        w_valid = w_valid * float(n_valid) / w_sum

        # WLS via sqrt-weighting: scale rows by sqrt(w_i) then solve OLS.
        sqrt_w = np.sqrt(w_valid)  # (n_valid,)
        Xw = X_t * sqrt_w[:, np.newaxis]  # (n_valid, K_active)
        rw = r_t_valid * sqrt_w  # (n_valid,)

        # Solve: Xw @ f = rw  (OLS on weighted data)
        f_t_active: np.ndarray
        f_t_active, *_ = np.linalg.lstsq(Xw, rw, rcond=None)  # (K_active,)

        # Residuals (unweighted) for all valid assets.
        u_t_valid = r_t_valid - X_t @ f_t_active  # (n_valid,)

        # Store only the active factor positions; inactive ones stay NaN.
        for out_k, f_val in zip(active_indices, f_t_active.tolist(), strict=False):
            f_returns_arr[t, out_k] = f_val
        u_returns_arr[t, valid_mask] = u_t_valid
        exposures_out[ts] = X_t

    f_df = pd.DataFrame(f_returns_arr, index=index, columns=list(all_factor_names))
    u_df = pd.DataFrame(u_returns_arr, index=index, columns=list(symbols))

    return BarraResult(
        factor_returns=f_df,
        residual_returns=u_df,
        exposures=exposures_out,
        factor_names=all_factor_names,
        asset_names=symbols,
        base_industry=base_ind_first,
        config=config,
    )


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------


def idiosyncratic_returns(result: BarraResult) -> pd.DataFrame:
    """Extract idiosyncratic (residual) returns from a fitted BarraResult.

    This is a thin accessor provided for API symmetry with :func:`fit_barra`.
    Equivalent to ``result.residual_returns``.

    Parameters
    ----------
    result:
        A fitted :class:`BarraResult` from :func:`fit_barra`.

    Returns
    -------
    pd.DataFrame
        Idiosyncratic return panel: periods x assets.
    """
    return result.residual_returns
