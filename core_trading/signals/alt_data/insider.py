"""SEC Form 4 insider-transaction signal (Phase 5.F.3).

Implements a cross-sectional insider-activity score derived from SEC Form 4
filings.  Form 4 is filed within two business days of a reportable transaction
(17 CFR 240.16a-3), so the signal is near-real-time when data are available.
The full EDGAR filing corpus is publicly accessible at no cost; only the XML
parser and ingest adapter are a Phase-1 follow-up.  This module defines the
consumed data shape that such an adapter will populate.

Consumed input shape -- InsiderTransaction
------------------------------------------
A *tidy* DataFrame (or a sequence of :class:`InsiderTransaction` records
converted via :func:`transactions_to_dataframe`) with at minimum the following
columns:

    symbol          str     Ticker / exchange symbol (e.g., "AAPL").
    insider_id      str     A stable opaque identifier for the filer (e.g.,
                            CIK number from EDGAR, or "Name/Title" composite).
    transaction_date datetime64[ns]
                            The date the transaction occurred (Form 4 Part I
                            header date), used as the look-ahead-free as-of cut.
    shares          float   Absolute number of shares transacted (> 0).
    transaction_code str    SEC transaction code.  This module distinguishes:
                                "P" -- open-market purchase (buy signal)
                                "S" -- open-market sale    (sell signal)
                            Other codes (e.g., "A" for award, "D" for
                            disposition to the issuer) are filtered out by
                            default because they carry different economic
                            interpretation (Cohen-Malloy-Pomorski 2012).
    price           float   Per-share transaction price as filed.
    shares_held_after float | NaN
                            Beneficial ownership after the transaction, used
                            to normalise trade size.  NaN when not reported.

The columns above are the minimum contract.  Extra columns in the DataFrame are
ignored.  A future EDGAR Form 4 ingest adapter will populate this schema by
parsing the XML ``<nonDerivativeTransaction>`` elements from EDGAR full-index
files.

Signal construction
-------------------
1. **Net insider sentiment** (Lakonishok-Lee 2001):
   For each (symbol, window) combination compute signed dollar flow:
       flow = sum(price * shares * direction)   where direction = +1 (P), -1 (S)
   Normalise by total dollar volume of all insider trades (buys + sells) for
   that symbol over the window so the score is bounded in [-1, +1]:
       sentiment = flow / total_dollar_volume
   When no P/S transactions exist the score is NaN (no signal).
   If ``shares_held_after`` is available and the normalisation choice is
   "holdings", the trade size is normalised by median ending holdings across
   all insiders for that symbol.

2. **Cluster-buy detection** (Lakonishok-Lee 2001):
   A cluster buy is defined as >= ``min_cluster_insiders`` *distinct* insiders
   buying symbol s within the window ending at each evaluation date.  The
   cluster flag is a boolean column ``cluster_buy`` in the score panel (True
   when the cluster criterion is met).  Cluster buys are the strongest signal
   in Lakonishok-Lee because they are unlikely to coincide by chance.

3. **Routine vs. opportunistic classifier** (Cohen-Malloy-Pomorski 2012):
   An insider is labelled *routine* if they have traded in the same calendar
   month in at least ``routine_years`` consecutive prior years within the
   historical data.  All other insiders are *opportunistic*.  Opportunistic
   trades receive a weight multiplier of ``opportunistic_weight`` (default 2.0)
   when aggregating net sentiment; routine trades receive weight 1.0.
   Cohen-Malloy-Pomorski (2012) show opportunistic insiders earn significantly
   higher abnormal returns than routine insiders.

4. **Cross-sectional score panel**:
   The function :func:`insider_score_panel` returns a
   (DatetimeIndex x symbols) DataFrame of z-scored net insider sentiment,
   evaluated at a user-supplied set of dates (``eval_dates``).  At each date t
   only transactions with ``transaction_date <= t`` within the rolling window
   are included (look-ahead-free).

5. **Long/short weights**:
   :func:`insider_portfolio` chains the score panel through
   :func:`~core_trading.signals.factors.momentum.cross_sectional_zscore` and
   :func:`~core_trading.signals.factors.momentum.long_short_weights` to produce
   dollar-neutral target weights.

Mathematical references
-----------------------
Lakonishok, J. & Lee, I. (2001). "Are Insider Trades Informative?"
    Review of Financial Studies, 14(1), 79-111.
    Defines the net purchase ratio (NPR), the basis for net sentiment here.

Cohen, L., Malloy, C. & Pomorski, L. (2012). "Decoding Inside Information."
    Journal of Finance, 67(3), 1009-1043.
    Introduces the routine vs. opportunistic insider classification.
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from core_trading.signals.factors.momentum import (
    cross_sectional_zscore,
    long_short_weights,
)

__all__ = [
    "InsiderConfig",
    "InsiderTransaction",
    "transactions_to_dataframe",
    "label_routine_insiders",
    "net_insider_sentiment",
    "cluster_buy_flags",
    "insider_score_panel",
    "insider_portfolio",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUY_CODE = "P"
_SELL_CODE = "S"
_OPEN_MARKET_CODES: frozenset[str] = frozenset({_BUY_CODE, _SELL_CODE})

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InsiderConfig:
    """Parameters for the insider-transaction signal.

    Attributes
    ----------
    window_days:
        Rolling look-back in calendar days for aggregating transactions.
        A transaction at date d enters the score at any evaluation date t
        where d <= t and t - d < window_days.  Must be >= 1.
        Typical value: 365 (12-month rolling window).
    min_cluster_insiders:
        Minimum number of *distinct* insiders that must have purchased within
        the window for the cluster-buy flag to fire.  Must be >= 2.
        Lakonishok-Lee (2001) use N=3 as a baseline.
    normalisation:
        How to normalise trade size when computing net sentiment.
        "dollar_flow" (default) -- normalise by total dollar volume of
            open-market trades (buys + sells) so the score is in [-1, +1].
        "holdings"    -- normalise by median reported ending holdings;
            falls back to "dollar_flow" for rows where holdings are missing.
    routine_years:
        An insider is labelled routine if they traded in the same calendar
        month in at least this many consecutive prior years.  Must be >= 1.
        Cohen-Malloy-Pomorski (2012) use 3 prior years.
    opportunistic_weight:
        Dollar-flow multiplier applied to trades by opportunistic insiders
        when computing net sentiment.  Must be > 0.  Default 2.0 replicates
        the relative weight used in Cohen-Malloy-Pomorski (2012).
    """

    window_days: int = 365
    min_cluster_insiders: int = 3
    normalisation: str = "dollar_flow"
    routine_years: int = 3
    opportunistic_weight: float = 2.0

    def __post_init__(self) -> None:
        if self.window_days < 1:
            raise ValueError(
                f"InsiderConfig.window_days must be >= 1, got {self.window_days}"
            )
        if self.min_cluster_insiders < 2:
            raise ValueError(
                f"InsiderConfig.min_cluster_insiders must be >= 2, "
                f"got {self.min_cluster_insiders}"
            )
        if self.normalisation not in {"dollar_flow", "holdings"}:
            raise ValueError(
                f"InsiderConfig.normalisation must be 'dollar_flow' or 'holdings', "
                f"got {self.normalisation!r}"
            )
        if self.routine_years < 1:
            raise ValueError(
                f"InsiderConfig.routine_years must be >= 1, got {self.routine_years}"
            )
        if self.opportunistic_weight <= 0.0:
            raise ValueError(
                f"InsiderConfig.opportunistic_weight must be > 0, "
                f"got {self.opportunistic_weight}"
            )


# ---------------------------------------------------------------------------
# Input shape -- InsiderTransaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InsiderTransaction:
    """One open-market transaction from a SEC Form 4 filing.

    This is the point-in-time unit of input.  The ``transaction_date`` is used
    as the as-of cut for look-ahead-free backtests: a transaction is visible
    at evaluation date t only if ``transaction_date <= t``.

    Attributes
    ----------
    symbol:
        Ticker / exchange symbol.
    insider_id:
        Stable opaque identifier for the filer (EDGAR CIK preferred).
    transaction_date:
        Date the transaction occurred (Form 4 Part I header date).
    shares:
        Absolute number of shares transacted.  Must be > 0.
    transaction_code:
        SEC transaction code.  Only "P" (open-market purchase) and "S"
        (open-market sale) carry the information signal studied in the
        literature; other codes are filtered out by :func:`transactions_to_dataframe`.
    price:
        Per-share transaction price as filed.  Must be >= 0.
    shares_held_after:
        Beneficial ownership after the transaction.  NaN when not reported.
    """

    symbol: str
    insider_id: str
    transaction_date: date
    shares: float
    transaction_code: str
    price: float
    shares_held_after: float = float("nan")

    def __post_init__(self) -> None:
        if self.shares <= 0.0:
            raise ValueError(
                f"InsiderTransaction.shares must be > 0, got {self.shares}"
            )
        if self.price < 0.0:
            raise ValueError(
                f"InsiderTransaction.price must be >= 0, got {self.price}"
            )


def transactions_to_dataframe(
    records: Sequence[InsiderTransaction],
) -> pd.DataFrame:
    """Convert a sequence of :class:`InsiderTransaction` records to a tidy DataFrame.

    Only open-market buy ("P") and sell ("S") transactions are retained.
    The resulting DataFrame has columns:
        symbol, insider_id, transaction_date (datetime64[ns]),
        shares, transaction_code, price, shares_held_after, dollar_volume.
    ``dollar_volume`` is ``price * shares`` (>= 0).

    Parameters
    ----------
    records:
        Iterable of :class:`InsiderTransaction` instances.

    Returns
    -------
    pd.DataFrame
        Tidy DataFrame; empty if ``records`` is empty or contains no P/S rows.
    """
    _cols = [
        "symbol",
        "insider_id",
        "transaction_date",
        "shares",
        "transaction_code",
        "price",
        "shares_held_after",
    ]
    if not records:
        df = pd.DataFrame(columns=_cols + ["dollar_volume"])
        df["transaction_date"] = pd.to_datetime(df["transaction_date"])
        return df

    rows = [
        {
            "symbol": r.symbol,
            "insider_id": r.insider_id,
            "transaction_date": r.transaction_date,
            "shares": r.shares,
            "transaction_code": r.transaction_code,
            "price": r.price,
            "shares_held_after": r.shares_held_after,
        }
        for r in records
        if r.transaction_code in _OPEN_MARKET_CODES
    ]

    if not rows:
        df = pd.DataFrame(columns=_cols + ["dollar_volume"])
        df["transaction_date"] = pd.to_datetime(df["transaction_date"])
        return df

    df = pd.DataFrame(rows)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["dollar_volume"] = df["price"] * df["shares"]
    return df


# ---------------------------------------------------------------------------
# Routine vs. opportunistic classifier
# ---------------------------------------------------------------------------


def label_routine_insiders(
    df: pd.DataFrame,
    *,
    routine_years: int = 3,
    as_of: pd.Timestamp | None = None,
) -> pd.Series:
    """Label each insider as routine (True) or opportunistic (False).

    An insider is *routine* (Cohen-Malloy-Pomorski 2012) if they have traded
    in the same calendar month in at least ``routine_years`` distinct prior
    calendar years relative to ``as_of``.  This captures insiders who execute
    predictable, calendar-driven transactions (e.g., 10b5-1 plans, recurring
    year-end sales), whose trades carry less information content than those of
    opportunistic insiders.

    Implementation: for each insider we extract all transaction months and
    years from the history up to (but not including) ``as_of``.  We then count
    how many calendar months appear in >= ``routine_years`` distinct years.
    An insider is routine if at least one such month exists.

    Parameters
    ----------
    df:
        Tidy transactions DataFrame as produced by :func:`transactions_to_dataframe`.
        Must contain columns ``insider_id`` and ``transaction_date``.
    routine_years:
        Minimum number of distinct calendar years a month must appear in for
        an insider to be classified as routine.  Must be >= 1.
    as_of:
        Cut-off timestamp.  Only transactions strictly before ``as_of`` are
        used when building the history (look-ahead-free).  If None, all rows
        are used.

    Returns
    -------
    pd.Series
        Index: unique ``insider_id`` values in ``df``.
        Values: bool -- True = routine, False = opportunistic.
    """
    if routine_years < 1:
        raise ValueError(f"routine_years must be >= 1, got {routine_years}")

    hist = df.copy()
    if as_of is not None:
        hist = hist[hist["transaction_date"] < as_of]

    if hist.empty:
        unique_ids = df["insider_id"].unique()
        return pd.Series(False, index=unique_ids, dtype=bool)

    # Extract month and year from each transaction
    hist = hist.copy()
    hist["_month"] = hist["transaction_date"].dt.month
    hist["_year"] = hist["transaction_date"].dt.year

    # For each insider: count distinct years per month
    month_year = (
        hist.groupby(["insider_id", "_month"])["_year"]
        .nunique()
    )

    # An insider is routine if any month appears in >= routine_years distinct years
    routine_mask = month_year >= routine_years
    routine_insiders: set[str] = set(
        month_year[routine_mask].index.get_level_values("insider_id").tolist()
    )

    unique_ids = df["insider_id"].unique()
    return pd.Series(
        [iid in routine_insiders for iid in unique_ids],
        index=unique_ids,
        dtype=bool,
    )


# ---------------------------------------------------------------------------
# Core aggregation helpers
# ---------------------------------------------------------------------------


def _signed_dollar_flow(
    df: pd.DataFrame,
    routine_labels: pd.Series,
    opportunistic_weight: float,
) -> pd.DataFrame:
    """Return a copy of df with a ``signed_dollar_flow`` column.

    Buys (code "P") are positive; sells (code "S") are negative.
    Opportunistic-insider trades are multiplied by ``opportunistic_weight``.
    """
    df = df.copy()
    direction = df["transaction_code"].map({_BUY_CODE: 1.0, _SELL_CODE: -1.0})
    weight = df["insider_id"].map(
        lambda iid: 1.0 if routine_labels.get(iid, False) else opportunistic_weight
    )
    df["signed_dollar_flow"] = df["dollar_volume"] * direction * weight
    df["weighted_dollar_volume"] = df["dollar_volume"] * weight
    return df


def net_insider_sentiment(
    df: pd.DataFrame,
    eval_date: pd.Timestamp,
    *,
    config: InsiderConfig,
    routine_labels: pd.Series | None = None,
) -> pd.Series:
    """Compute net insider sentiment per symbol at a single evaluation date.

    For each symbol, the net purchase ratio (Lakonishok-Lee 2001) is:
        sentiment = signed_weighted_flow / total_weighted_dollar_volume
    where signed_weighted_flow = sum of (direction * dollar_volume * weight)
    and total_weighted_dollar_volume = sum of (dollar_volume * weight).
    The score is in [-1, +1].

    Only transactions with ``transaction_date <= eval_date`` and
    ``eval_date - transaction_date < window_days`` are included (look-ahead-free).

    Parameters
    ----------
    df:
        Tidy transactions DataFrame from :func:`transactions_to_dataframe`.
    eval_date:
        The evaluation timestamp (the "as of" date).
    config:
        :class:`InsiderConfig` controlling window, normalisation, and weights.
    routine_labels:
        Optional pre-computed routine/opportunistic labels from
        :func:`label_routine_insiders`.  If None, all insiders are treated
        as opportunistic (weight = ``config.opportunistic_weight``).

    Returns
    -------
    pd.Series
        Index: symbol strings present in ``df``.
        Values: float in [-1, +1] or NaN when no P/S trades exist.
    """
    if df.empty:
        return pd.Series(dtype=float)

    cutoff_low = eval_date - pd.Timedelta(days=config.window_days - 1)
    window_df = df[
        (df["transaction_date"] <= eval_date)
        & (df["transaction_date"] >= cutoff_low)
    ].copy()

    if window_df.empty:
        symbols = df["symbol"].unique()
        return pd.Series(np.nan, index=symbols)

    if routine_labels is None:
        dummy_routine = pd.Series(False, index=df["insider_id"].unique(), dtype=bool)
        labels = dummy_routine
    else:
        labels = routine_labels

    window_df = _signed_dollar_flow(window_df, labels, config.opportunistic_weight)

    grp = window_df.groupby("symbol")
    signed_flow = grp["signed_dollar_flow"].sum()
    total_vol = grp["weighted_dollar_volume"].sum()

    if config.normalisation == "holdings":
        holdings = window_df.dropna(subset=["shares_held_after"])
        if not holdings.empty:
            med_holdings = holdings.groupby("symbol")["shares_held_after"].median()
            med_price = window_df.groupby("symbol")["price"].median()
            holdings_dollar = med_holdings * med_price
            denom = holdings_dollar.reindex(signed_flow.index)
            missing_mask = denom.isna() | (denom == 0.0)
            denom_safe = denom.where(~missing_mask, other=total_vol)
            denom_safe = denom_safe.where(denom_safe != 0.0, other=np.nan)
            raw_sentiment = signed_flow / denom_safe
        else:
            denom_safe = total_vol.where(total_vol != 0.0, other=np.nan)
            raw_sentiment = signed_flow / denom_safe
    else:
        denom_safe = total_vol.where(total_vol != 0.0, other=np.nan)
        raw_sentiment = signed_flow / denom_safe

    # Clip to [-1, +1] as a robustness guard (holdings normalisation can exceed)
    return raw_sentiment.clip(-1.0, 1.0)


def cluster_buy_flags(
    df: pd.DataFrame,
    eval_date: pd.Timestamp,
    *,
    config: InsiderConfig,
) -> pd.Series:
    """Return a boolean Series indicating cluster-buy symbols at ``eval_date``.

    A cluster buy fires for symbol s when >= ``config.min_cluster_insiders``
    *distinct* insiders purchased (code "P") within the rolling window ending
    at ``eval_date`` (look-ahead-free).

    Parameters
    ----------
    df:
        Tidy transactions DataFrame from :func:`transactions_to_dataframe`.
    eval_date:
        Evaluation timestamp.
    config:
        :class:`InsiderConfig`.

    Returns
    -------
    pd.Series
        Index: all symbols in ``df``.  Values: bool (True = cluster buy).
    """
    symbols = df["symbol"].unique()
    if df.empty:
        return pd.Series(False, index=symbols, dtype=bool)

    cutoff_low = eval_date - pd.Timedelta(days=config.window_days - 1)
    buys = df[
        (df["transaction_code"] == _BUY_CODE)
        & (df["transaction_date"] <= eval_date)
        & (df["transaction_date"] >= cutoff_low)
    ]

    if buys.empty:
        return pd.Series(False, index=symbols, dtype=bool)

    distinct_buyers = buys.groupby("symbol")["insider_id"].nunique()
    return (distinct_buyers >= config.min_cluster_insiders).reindex(symbols, fill_value=False)


# ---------------------------------------------------------------------------
# Cross-sectional score panel
# ---------------------------------------------------------------------------


def insider_score_panel(
    df: pd.DataFrame,
    eval_dates: pd.DatetimeIndex,
    *,
    config: InsiderConfig,
) -> pd.DataFrame:
    """Build a (DatetimeIndex x symbols) net insider sentiment panel.

    At each evaluation date t:
    1. Compute routine/opportunistic labels using only history strictly
       before t (look-ahead-free).
    2. Compute net insider sentiment per symbol over the rolling window.
    3. Record cluster-buy flags per symbol.

    The returned panel contains two DataFrames bundled as a dict is NOT
    ergonomic; instead the function returns the primary sentiment scores
    panel (DatetimeIndex x symbols, float in [-1, +1] or NaN).  The
    cluster-buy flags are returned via a companion call to
    :func:`cluster_buy_panel`.

    Parameters
    ----------
    df:
        Tidy transactions DataFrame from :func:`transactions_to_dataframe`.
    eval_dates:
        Sorted DatetimeIndex of evaluation timestamps.
    config:
        :class:`InsiderConfig`.

    Returns
    -------
    pd.DataFrame
        Shape (len(eval_dates), n_symbols).
        Index: ``eval_dates``.
        Columns: sorted unique symbol strings from ``df``.
        Values: net insider sentiment in [-1, +1] or NaN.
    """
    if df.empty or len(eval_dates) == 0:
        return pd.DataFrame(index=eval_dates, dtype=float)

    symbols_sorted: list[str] = sorted(df["symbol"].unique().tolist())
    result = np.full((len(eval_dates), len(symbols_sorted)), np.nan, dtype=float)

    for i, eval_ts in enumerate(eval_dates):
        routine_labels = label_routine_insiders(
            df,
            routine_years=config.routine_years,
            as_of=eval_ts,
        )
        sentiment = net_insider_sentiment(
            df,
            eval_ts,
            config=config,
            routine_labels=routine_labels,
        )
        for j, sym in enumerate(symbols_sorted):
            if sym in sentiment.index:
                result[i, j] = float(sentiment[sym])

    return pd.DataFrame(result, index=eval_dates, columns=symbols_sorted)


def cluster_buy_panel(
    df: pd.DataFrame,
    eval_dates: pd.DatetimeIndex,
    *,
    config: InsiderConfig,
) -> pd.DataFrame:
    """Build a (DatetimeIndex x symbols) boolean cluster-buy panel.

    Parameters
    ----------
    df:
        Tidy transactions DataFrame from :func:`transactions_to_dataframe`.
    eval_dates:
        Sorted DatetimeIndex of evaluation timestamps.
    config:
        :class:`InsiderConfig`.

    Returns
    -------
    pd.DataFrame
        Shape (len(eval_dates), n_symbols).
        Index: ``eval_dates``.
        Columns: sorted unique symbol strings.
        Values: bool -- True when the cluster-buy criterion fires.
    """
    if df.empty or len(eval_dates) == 0:
        return pd.DataFrame(index=eval_dates, dtype=bool)

    symbols_sorted: list[str] = sorted(df["symbol"].unique().tolist())
    result = np.zeros((len(eval_dates), len(symbols_sorted)), dtype=bool)

    for i, eval_ts in enumerate(eval_dates):
        flags = cluster_buy_flags(df, eval_ts, config=config)
        for j, sym in enumerate(symbols_sorted):
            if sym in flags.index:
                result[i, j] = bool(flags[sym])

    return pd.DataFrame(result, index=eval_dates, columns=symbols_sorted)


# ---------------------------------------------------------------------------
# Convenience pipeline
# ---------------------------------------------------------------------------


def insider_portfolio(
    df: pd.DataFrame,
    eval_dates: pd.DatetimeIndex,
    *,
    config: InsiderConfig,
    quantile: float = 0.2,
) -> pd.DataFrame:
    """End-to-end pipeline: transactions -> dollar-neutral long/short weights.

    Chains:
      1. :func:`insider_score_panel` -> raw sentiment panel.
      2. :func:`~core_trading.signals.factors.momentum.cross_sectional_zscore`
         -> z-scored panel.
      3. :func:`~core_trading.signals.factors.momentum.long_short_weights`
         -> dollar-neutral weights.

    Parameters
    ----------
    df:
        Tidy transactions DataFrame from :func:`transactions_to_dataframe`.
    eval_dates:
        Sorted DatetimeIndex of evaluation timestamps.
    config:
        :class:`InsiderConfig`.
    quantile:
        Fraction of the cross-section per leg (passed to
        :func:`~core_trading.signals.factors.momentum.long_short_weights`).

    Returns
    -------
    pd.DataFrame
        Target weights panel (DatetimeIndex x symbols).
        Row sums are 0 for rows with enough valid scores.
    """
    scores = insider_score_panel(df, eval_dates, config=config)

    if scores.empty:
        return scores

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        z = cross_sectional_zscore(scores)

    return long_short_weights(z, quantile=quantile)
