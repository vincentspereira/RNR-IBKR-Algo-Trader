"""Yahoo Finance OHLCV adapter via ``yfinance``.

Notes per :doc:`docs/FREE_DATA_VENDORS.md`:

* **No API key required.** This is the primary fallback / cross-validation
  source while paid vendors are out of scope.
* **Not point-in-time correct** for fundamentals. We expose only bars here.
* **Limits:** ~60 days for 1m bars, ~730 days for hourly. Daily is full
  history (decades).
* **Adjustments:** ``yfinance`` returns the unadjusted OHLCV in the standard
  columns and the split/dividend-adjusted close in the ``Adj Close`` column
  when ``auto_adjust=False`` (the default we use). We preserve both.

The adapter is async-friendly but yfinance itself is synchronous; we run the
blocking call in a thread to avoid stalling the event loop.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import AsyncIterator

import pandas as pd
import yfinance as yf

from core_trading.data.bars import (
    Bar,
    BarRequest,
    BarResolution,
    BarSource,
    BarSourceCapabilities,
)


_RES_TO_YF: dict[BarResolution, str] = {
    BarResolution.MINUTE_1: "1m",
    BarResolution.MINUTE_5: "5m",
    BarResolution.MINUTE_15: "15m",
    BarResolution.MINUTE_30: "30m",
    BarResolution.HOUR_1: "60m",
    BarResolution.DAY_1: "1d",
    BarResolution.WEEK_1: "1wk",
    BarResolution.MONTH_1: "1mo",
}

_RES_TO_SECONDS: dict[BarResolution, int] = {
    BarResolution.MINUTE_1: 60,
    BarResolution.MINUTE_5: 300,
    BarResolution.MINUTE_15: 900,
    BarResolution.MINUTE_30: 1800,
    BarResolution.HOUR_1: 3600,
    BarResolution.DAY_1: 86_400,
    BarResolution.WEEK_1: 604_800,
    BarResolution.MONTH_1: 2_592_000,
}


class YFinanceBarSource(BarSource):
    """OHLCV via Yahoo Finance.

    Parameters
    ----------
    threads:
        Whether to enable yfinance's internal threading. The default ``False``
        keeps behaviour predictable inside the async wrapper.
    progress:
        yfinance default is to print progress bars; we silence that.
    """

    _NAME = "yfinance"

    def __init__(self, threads: bool = False, progress: bool = False) -> None:
        self._threads = threads
        self._progress = progress

    @property
    def capabilities(self) -> BarSourceCapabilities:
        return BarSourceCapabilities(
            name=self._NAME,
            supports_resolutions=frozenset(_RES_TO_YF.keys()),
            supports_extended_hours=True,
            supports_adjusted=True,
            supports_unadjusted=True,
            max_history_days=None,
            rate_limit_per_minute=None,
            requires_api_key=False,
        )

    def _native_interval(self, resolution: BarResolution) -> str:
        if resolution not in _RES_TO_YF:
            raise ValueError(
                f"yfinance does not support resolution {resolution!r}. "
                f"Supported: {sorted(r.value for r in _RES_TO_YF)}"
            )
        return _RES_TO_YF[resolution]

    def _validate_history_window(self, request: BarRequest) -> None:
        span_days = (request.end - request.start).days
        if request.resolution == BarResolution.MINUTE_1 and span_days > 60:
            raise ValueError(
                "yfinance limits 1-minute history to ~60 days; "
                "split the request or use a coarser resolution."
            )
        if request.resolution in {
            BarResolution.MINUTE_5,
            BarResolution.MINUTE_15,
            BarResolution.MINUTE_30,
            BarResolution.HOUR_1,
        } and span_days > 730:
            raise ValueError(
                f"yfinance limits {request.resolution.value} history to ~730 days; "
                "split the request or use 1d."
            )

    def _to_frame(
        self,
        raw: pd.DataFrame,
        symbols: tuple[str, ...],
        resolution: BarResolution,
    ) -> pd.DataFrame:
        if raw is None or raw.empty:
            return BarSource.bars_to_dataframe([])

        if isinstance(raw.columns, pd.MultiIndex):
            stacked = raw.stack(level=1, future_stack=True)
            stacked.index.set_names(["timestamp", "symbol"], inplace=True)
            stacked = stacked.reorder_levels(["symbol", "timestamp"]).sort_index()
        else:
            stacked = raw.copy()
            stacked["symbol"] = symbols[0]
            stacked.index.name = "timestamp"
            stacked = stacked.set_index("symbol", append=True).reorder_levels(
                ["symbol", "timestamp"]
            )

        rename = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adjusted_close",
            "Volume": "volume",
        }
        stacked = stacked.rename(columns=rename)

        if "adjusted_close" not in stacked.columns:
            stacked["adjusted_close"] = stacked["close"]

        stacked["vwap"] = None
        stacked["trade_count"] = None
        stacked["source"] = self._NAME

        for col in ["open", "high", "low", "close", "volume", "adjusted_close"]:
            stacked[col] = pd.to_numeric(stacked[col], errors="coerce")

        stacked = stacked.dropna(subset=["open", "high", "low", "close"])

        idx = stacked.index
        if isinstance(idx, pd.MultiIndex):
            ts_level = idx.get_level_values("timestamp")
            sym_level = idx.get_level_values("symbol")
            if getattr(ts_level, "tz", None) is None:
                ts_level = ts_level.tz_localize("UTC")
            else:
                ts_level = ts_level.tz_convert("UTC")
            stacked.index = pd.MultiIndex.from_arrays(
                [sym_level, ts_level], names=["symbol", "timestamp"]
            )

        cols = [
            "open", "high", "low", "close", "volume",
            "adjusted_close", "vwap", "trade_count", "source",
        ]
        stacked = stacked[cols].sort_index()
        return stacked

    async def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        self._validate_history_window(request)
        interval = self._native_interval(request.resolution)

        def _download() -> pd.DataFrame:
            return yf.download(
                tickers=list(request.symbols),
                start=request.start,
                end=request.end,
                interval=interval,
                auto_adjust=False,
                actions=False,
                prepost=request.include_extended_hours,
                progress=self._progress,
                threads=self._threads,
                group_by="column",
            )

        raw = await asyncio.to_thread(_download)
        df = self._to_frame(raw, request.symbols, request.resolution)
        if not df.empty:
            BarSource.validate_dataframe(df)
        return df

    async def stream_bars(self, request: BarRequest) -> AsyncIterator[Bar]:
        df = await self.fetch_bars(request)
        for (symbol, timestamp), row in df.iterrows():
            yield Bar(
                symbol=str(symbol),
                timestamp=timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp,
                resolution=request.resolution,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]) if not pd.isna(row["volume"]) else 0.0,
                source=self._NAME,
                adjusted_close=(
                    float(row["adjusted_close"]) if not pd.isna(row["adjusted_close"]) else None
                ),
                vwap=None,
                trade_count=None,
            )

    def expected_seconds(self, resolution: BarResolution) -> int | None:
        return _RES_TO_SECONDS.get(resolution)


def fetch_bars_sync(
    symbols: tuple[str, ...] | list[str],
    start,
    end,
    resolution: BarResolution = BarResolution.DAY_1,
) -> pd.DataFrame:
    """Synchronous convenience wrapper for research notebooks.

    Equivalent to ``asyncio.run(YFinanceBarSource().fetch_bars(...))`` with
    sensible defaults. Use the async :class:`YFinanceBarSource` API directly
    from production code.
    """
    from datetime import datetime, timezone

    def _to_utc(d):
        if isinstance(d, datetime):
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    request = BarRequest(
        symbols=tuple(symbols),
        resolution=resolution,
        start=_to_utc(start),
        end=_to_utc(end) + timedelta(seconds=1),
    )
    return asyncio.run(YFinanceBarSource().fetch_bars(request))
