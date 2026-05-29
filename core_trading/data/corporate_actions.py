"""Corporate actions: splits and dividends, with price adjustment.

Per master plan Phase 1.3: backtests should work in **unadjusted** price space
and apply corporate-action adjustments at the point of use. This module
provides:

* :class:`CorporateAction` -- one split or cash dividend event
* :class:`CorporateActionSource` -- adapter interface (yfinance, IBKR, EDGAR)
* :func:`adjustment_factors` -- compute the cumulative back-adjustment factor
  series used to convert unadjusted prices to a total-return-adjusted series
* :func:`apply_adjustments` -- apply those factors to an OHLCV frame

The adjustment convention follows the standard "CRSP-style" back-adjustment:
the most recent bar is unadjusted (factor 1.0) and earlier bars are scaled down
by the cumulative product of split ratios and dividend factors. This makes the
adjusted series continuous across corporate-action boundaries without altering
the latest price.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

import numpy as np
import pandas as pd


class CorporateActionType(str, Enum):
    """Kind of corporate action."""

    SPLIT = "split"
    DIVIDEND = "dividend"


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """A single corporate action event for one symbol.

    Attributes
    ----------
    symbol:
        Vendor-neutral symbol.
    action_type:
        Split or dividend.
    ex_date:
        Ex-date -- the first date on which the security trades without the
        entitlement. Price adjustments apply to bars strictly before this date.
    ratio:
        For a split: shares-after / shares-before (e.g. 2.0 for a 2:1 split,
        0.1 for a 1:10 reverse split). Ignored for dividends.
    cash_amount:
        For a dividend: cash per share in the quote currency. Ignored for splits.
    source:
        Vendor identifier.
    """

    symbol: str
    action_type: CorporateActionType
    ex_date: date
    ratio: float = 1.0
    cash_amount: float = 0.0
    source: str = ""

    def __post_init__(self) -> None:
        if self.action_type == CorporateActionType.SPLIT and self.ratio <= 0:
            raise ValueError(
                f"split ratio must be positive; got {self.ratio} for {self.symbol}"
            )
        if self.action_type == CorporateActionType.DIVIDEND and self.cash_amount < 0:
            raise ValueError(
                f"dividend cash_amount cannot be negative; got {self.cash_amount} "
                f"for {self.symbol}"
            )


class CorporateActionSource(abc.ABC):
    """Abstract base for corporate-action data adapters."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Adapter identifier."""

    @abc.abstractmethod
    async def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> Sequence[CorporateAction]:
        """Fetch corporate actions for ``symbols`` between ``start`` and ``end``."""


def adjustment_factors(
    closes: pd.Series,
    actions: Sequence[CorporateAction],
) -> pd.Series:
    """Compute the back-adjustment factor series for one symbol.

    Parameters
    ----------
    closes:
        Unadjusted close prices indexed by timezone-aware timestamp, ascending.
    actions:
        Corporate actions for the same symbol. Dividends use the close on the
        bar immediately before the ex-date to compute the proportional factor.

    Returns
    -------
    pd.Series
        A factor series aligned to ``closes``. Multiplying unadjusted prices by
        this series yields the back-adjusted (total-return) series, with the
        most recent bar unchanged (factor 1.0).

    Notes
    -----
    * Split factor for bars before an ex-date: ``1 / ratio`` (a 2:1 split halves
      historical prices so the series is continuous).
    * Dividend factor for bars before an ex-date:
      ``1 - cash_amount / close_before_ex`` (the standard proportional
      total-return adjustment).
    """
    if not isinstance(closes.index, pd.DatetimeIndex):
        raise ValueError("closes must be indexed by DatetimeIndex")
    if not closes.index.is_monotonic_increasing:
        raise ValueError("closes index must be ascending")

    factors = pd.Series(1.0, index=closes.index)
    if len(closes) == 0:
        return factors

    sorted_actions = sorted(actions, key=lambda a: a.ex_date)
    for action in sorted_actions:
        ex_ts = pd.Timestamp(action.ex_date)
        if closes.index.tz is not None:
            ex_ts = ex_ts.tz_localize(closes.index.tz)
        before_mask = closes.index < ex_ts
        if not before_mask.any():
            continue

        if action.action_type == CorporateActionType.SPLIT:
            per_event = 1.0 / action.ratio
        else:
            before_closes = closes[before_mask]
            close_before_ex = before_closes.iloc[-1]
            if close_before_ex <= 0:
                continue
            per_event = 1.0 - (action.cash_amount / close_before_ex)
            if per_event <= 0:
                continue

        factors[before_mask] *= per_event

    return factors


def apply_adjustments(
    df: pd.DataFrame,
    actions: Sequence[CorporateAction],
) -> pd.DataFrame:
    """Return a copy of ``df`` with an ``adjusted_close`` recomputed from actions.

    ``df`` is a single-symbol OHLCV frame indexed by timestamp (not the
    multi-index frame; slice with ``.xs(symbol, level="symbol")`` first). The
    OHLC columns are also back-adjusted in place into ``adj_open``, ``adj_high``,
    ``adj_low`` so downstream code can choose adjusted or raw consistently.
    """
    if df.empty:
        return df.copy()
    if "close" not in df.columns:
        raise ValueError("apply_adjustments requires a 'close' column")

    out = df.copy()
    factors = adjustment_factors(out["close"], actions)
    out["adjusted_close"] = out["close"] * factors
    for col, adj_col in (
        ("open", "adj_open"),
        ("high", "adj_high"),
        ("low", "adj_low"),
    ):
        if col in out.columns:
            out[adj_col] = out[col] * factors
    return out


def total_return_index(
    closes: pd.Series,
    actions: Sequence[CorporateAction],
) -> pd.Series:
    """Build a total-return index (base 100) from unadjusted closes + actions.

    Useful for performance attribution where dividends must be reinvested.
    """
    if len(closes) == 0:
        return closes.copy()
    factors = adjustment_factors(closes, actions)
    adjusted = closes * factors
    base = adjusted.iloc[0]
    if base == 0 or np.isnan(base):
        raise ValueError("first adjusted close is zero/NaN; cannot build index")
    return adjusted / base * 100.0
