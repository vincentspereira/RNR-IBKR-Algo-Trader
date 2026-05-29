"""OHLCV bar data abstraction.

Defines the vendor-agnostic ``Bar`` value object, the ``BarRequest`` query
descriptor, the ``BarResolution`` enumeration, and the abstract
:class:`BarSource` interface that every vendor adapter implements.

Design notes (per master plan Phase 1.2):

* Bars carry **both** adjusted and unadjusted prices when available. Backtests
  default to working in unadjusted space and apply corporate-action adjustments
  at trade time -- using only adjusted prices leaks information.
* Volume is float (not int) because some venues report fractional shares and
  some aggregated bars are pro-rated.
* All timestamps are timezone-aware UTC. Vendor-specific local-time handling
  happens inside the adapter; the abstraction layer is UTC.
* Sources are async because the dominant cost is network I/O; sync wrappers
  can compose async via ``asyncio.run`` when needed.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator, Sequence

import pandas as pd


class BarResolution(str, Enum):
    """Supported bar resolutions.

    Values are the canonical string used across the codebase. Vendor adapters
    translate to their native representations (yfinance "1d", IBKR "1 day",
    etc.) inside the adapter.
    """

    TICK = "tick"
    SECOND_1 = "1s"
    SECOND_5 = "5s"
    SECOND_30 = "30s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1mo"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar for a single symbol at a single timestamp.

    Attributes
    ----------
    symbol:
        Vendor-neutral symbol identifier (e.g. "AAPL", "RELIANCE.NS").
    timestamp:
        Bar end time (close), UTC, timezone-aware.
    resolution:
        Bar duration.
    open, high, low, close:
        Prices in the instrument's quote currency. **Unadjusted** -- raw
        market prices before split/dividend adjustment.
    volume:
        Reported volume; float to accommodate fractional shares.
    adjusted_close:
        Split- and dividend-adjusted close, when the vendor provides it. ``None``
        means the vendor did not report adjustment.
    vwap:
        Volume-weighted average price for the bar, when reported.
    trade_count:
        Number of trades aggregated into the bar, when reported.
    source:
        Identifier of the vendor that produced this bar
        (e.g. ``"yfinance"``, ``"ibkr"``).
    """

    symbol: str
    timestamp: datetime
    resolution: BarResolution
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    adjusted_close: float | None = None
    vwap: float | None = None
    trade_count: int | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError(
                f"Bar.timestamp must be timezone-aware (UTC); got naive datetime for {self.symbol}"
            )
        if self.high < self.low:
            raise ValueError(
                f"Bar.high ({self.high}) < Bar.low ({self.low}) for {self.symbol} @ {self.timestamp}"
            )
        if self.volume < 0:
            raise ValueError(
                f"Bar.volume cannot be negative; got {self.volume} for {self.symbol} @ {self.timestamp}"
            )


@dataclass(frozen=True, slots=True)
class BarRequest:
    """Query descriptor for fetching bars from a :class:`BarSource`."""

    symbols: tuple[str, ...]
    resolution: BarResolution
    start: datetime
    end: datetime
    include_extended_hours: bool = False

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("BarRequest.symbols cannot be empty")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("BarRequest start/end must be timezone-aware UTC")
        if self.start >= self.end:
            raise ValueError(
                f"BarRequest.start ({self.start}) must be strictly before BarRequest.end ({self.end})"
            )


@dataclass(frozen=True, slots=True)
class BarSourceCapabilities:
    """What a given vendor adapter can do.

    Used by callers (and the registry) to pick the right adapter for a request
    without trial-and-error.
    """

    name: str
    supports_resolutions: frozenset[BarResolution]
    supports_extended_hours: bool
    supports_adjusted: bool
    supports_unadjusted: bool
    max_history_days: int | None
    rate_limit_per_minute: int | None
    requires_api_key: bool


class BarSource(abc.ABC):
    """Abstract base for OHLCV bar data adapters.

    Concrete subclasses live in :mod:`core_trading.data.sources` (one per
    vendor). Adapters must:

    * Honour ``request.resolution`` and translate to vendor-native format inside
      the adapter.
    * Yield bars in increasing timestamp order per symbol.
    * Tag each ``Bar.source`` with the adapter name for downstream attribution
      and cross-source validation.
    * Raise :class:`ValueError` for malformed requests and
      :class:`RuntimeError` for vendor failures.
    """

    @property
    @abc.abstractmethod
    def capabilities(self) -> BarSourceCapabilities:
        """Static description of what this source can do."""

    @abc.abstractmethod
    async def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        """Fetch bars for ``request`` and return a tidy DataFrame.

        The returned frame has a multi-index ``(symbol, timestamp)`` and
        columns: ``open, high, low, close, volume, adjusted_close, vwap,
        trade_count, source``. Missing optional columns are filled with
        ``NaN`` / ``None``.
        """

    @abc.abstractmethod
    async def stream_bars(self, request: BarRequest) -> AsyncIterator[Bar]:
        """Stream bars one at a time.

        For batch/historical fetch this can simply iterate the DataFrame
        produced by :meth:`fetch_bars`. For live feeds it should yield bars as
        the venue produces them.
        """

    @staticmethod
    def bars_to_dataframe(bars: Sequence[Bar]) -> pd.DataFrame:
        """Utility: convert a sequence of :class:`Bar` to the standard frame.

        Adapters that fetch bars one at a time and want to return a frame from
        :meth:`fetch_bars` can use this rather than reinventing the column
        layout.
        """
        if not bars:
            return pd.DataFrame(
                columns=[
                    "open", "high", "low", "close", "volume",
                    "adjusted_close", "vwap", "trade_count", "source",
                ]
            )
        records = [
            {
                "symbol": b.symbol,
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "adjusted_close": b.adjusted_close,
                "vwap": b.vwap,
                "trade_count": b.trade_count,
                "source": b.source,
            }
            for b in bars
        ]
        df = pd.DataFrame.from_records(records)
        df = df.set_index(["symbol", "timestamp"]).sort_index()
        return df

    @staticmethod
    def validate_dataframe(df: pd.DataFrame) -> None:
        """Sanity-check a bar frame for the invariants every adapter must hold."""
        required = {"open", "high", "low", "close", "volume", "source"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Bar frame missing required columns: {sorted(missing)}")
        if not isinstance(df.index, pd.MultiIndex) or df.index.names != ["symbol", "timestamp"]:
            raise ValueError(
                "Bar frame must be MultiIndexed on (symbol, timestamp); "
                f"got index names {df.index.names}"
            )
        if (df["high"] < df["low"]).any():
            bad = df[df["high"] < df["low"]].head(3)
            raise ValueError(f"Bar frame has high < low rows:\n{bad}")
        if (df["volume"] < 0).any():
            raise ValueError("Bar frame has negative volume rows")


def utc_now() -> datetime:
    """Return the current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)
