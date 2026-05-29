"""Time-series storage for the data layer (Phase 1 storage).

Persists OHLCV bars (and tick/quote snapshots) to ClickHouse, the time-series
backend chosen in the architecture (ADR-003). This module is the canonical
storage layer for :mod:`core_trading.data`; it supersedes the older
``core_trading/data_feeds/timeseries_store.py`` (archived 2026-05-29), porting
its proven ClickHouse logic and adapting it to the :class:`~core_trading.data.bars.Bar`
model and the ``(symbol, timestamp)`` multi-indexed bar frame.

Design:

* **Graceful degradation.** If the ClickHouse client is unavailable (no server,
  or ``clickhouse`` libs not installed) the store operates in a no-op mode that
  logs and returns sensibly, so research code and tests run offline.
* **Bar-model native.** :meth:`store_bars` accepts the standard bar DataFrame
  produced by any :class:`~core_trading.data.bars.BarSource`; :meth:`load_bars`
  returns the same shape, so the store is a drop-in cache in front of any
  vendor adapter.
* **Idempotent schema.** Tables are created on first write
  (``CREATE TABLE IF NOT EXISTS``) using a ``ReplacingMergeTree`` keyed on
  ``(symbol, resolution, timestamp)`` so re-ingesting overlapping windows does
  not duplicate rows.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from core_trading.data.bars import Bar, BarRequest, BarResolution, BarSource, BarSourceCapabilities

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard exercised only without clickhouse libs
    from libs.database.clickhouse.client import (  # type: ignore
        ClickHouseClient,
        get_clickhouse_client,
    )

    _CLICKHOUSE_AVAILABLE = True
except ImportError:  # pragma: no cover
    ClickHouseClient = Any  # type: ignore
    get_clickhouse_client = None  # type: ignore
    _CLICKHOUSE_AVAILABLE = False


_BARS_DDL = """
CREATE TABLE IF NOT EXISTS market_data.bars (
    symbol String,
    resolution String,
    timestamp DateTime64(3, 'UTC'),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    adjusted_close Nullable(Float64),
    vwap Nullable(Float64),
    trade_count Nullable(Int64),
    source String,
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (symbol, resolution, timestamp)
"""

_BAR_COLUMNS = [
    "symbol",
    "resolution",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjusted_close",
    "vwap",
    "trade_count",
    "source",
]


class BarStore:
    """ClickHouse-backed store for OHLCV bars, native to the Bar model.

    Parameters
    ----------
    client:
        Optional ClickHouse client. If ``None`` the store lazily acquires the
        shared client via :func:`get_clickhouse_client` when available, else it
        runs in no-op mode.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._initialized = False

    @property
    def available(self) -> bool:
        """Whether a live ClickHouse client backs this store."""
        return self.client is not None

    @property
    def client(self) -> Any | None:
        if self._client is None and _CLICKHOUSE_AVAILABLE and get_clickhouse_client is not None:
            try:
                self._client = get_clickhouse_client()
            except Exception as exc:  # pragma: no cover - depends on live server
                logger.warning("clickhouse client unavailable: %s", exc)
                self._client = None
        return self._client

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        client = self.client
        if client is None:
            self._initialized = True
            return
        client.execute("CREATE DATABASE IF NOT EXISTS market_data")
        client.execute(_BARS_DDL)
        self._initialized = True

    def store_bars(self, df: pd.DataFrame, resolution: BarResolution) -> int:
        """Persist a standard bar frame. Returns the number of rows written.

        ``df`` is the ``(symbol, timestamp)`` multi-indexed frame produced by a
        :class:`BarSource`. In no-op mode (no client) this returns 0.
        """
        if df.empty:
            return 0
        BarSource.validate_dataframe(df)
        self._ensure_schema()
        client = self.client
        if client is None:
            logger.debug("BarStore no client; skipping store of %d rows", len(df))
            return 0

        rows: list[tuple[Any, ...]] = []
        for (symbol, timestamp), row in df.iterrows():
            ts = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp
            rows.append(
                (
                    str(symbol),
                    resolution.value,
                    ts,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]) if not pd.isna(row["volume"]) else 0.0,
                    None if pd.isna(row.get("adjusted_close")) else float(row["adjusted_close"]),
                    None if pd.isna(row.get("vwap")) else float(row["vwap"]),
                    None if pd.isna(row.get("trade_count")) else int(row["trade_count"]),
                    str(row.get("source", "")),
                )
            )
        client.insert_batch("market_data.bars", rows, _BAR_COLUMNS)
        logger.info("stored %d bars (%s)", len(rows), resolution.value)
        return len(rows)

    def load_bars(self, request: BarRequest) -> pd.DataFrame:
        """Load bars matching ``request`` as a standard bar frame.

        In no-op mode returns an empty (correctly-shaped) frame.
        """
        self._ensure_schema()
        client = self.client
        if client is None:
            return BarSource.bars_to_dataframe([])

        query = """
            SELECT symbol, timestamp, open, high, low, close, volume,
                   adjusted_close, vwap, trade_count, source
            FROM market_data.bars FINAL
            WHERE symbol IN %(symbols)s
              AND resolution = %(resolution)s
              AND timestamp >= %(start)s
              AND timestamp <= %(end)s
            ORDER BY symbol ASC, timestamp ASC
        """
        results = client.execute(
            query,
            {
                "symbols": list(request.symbols),
                "resolution": request.resolution.value,
                "start": request.start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "end": request.end.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        if not results:
            return BarSource.bars_to_dataframe([])

        records = []
        for r in results:
            ts = r[1]
            if isinstance(ts, datetime) and ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            records.append(
                {
                    "symbol": r[0],
                    "timestamp": ts,
                    "open": r[2],
                    "high": r[3],
                    "low": r[4],
                    "close": r[5],
                    "volume": r[6],
                    "adjusted_close": r[7],
                    "vwap": r[8],
                    "trade_count": r[9],
                    "source": r[10],
                }
            )
        return pd.DataFrame.from_records(records).set_index(["symbol", "timestamp"]).sort_index()


_bar_store: BarStore | None = None


def get_bar_store() -> BarStore:
    """Return the process-wide :class:`BarStore` singleton."""
    global _bar_store
    if _bar_store is None:
        _bar_store = BarStore()
    return _bar_store


class CachingBarSource(BarSource):
    """A :class:`BarSource` that reads from :class:`BarStore`, falling back to an
    upstream source on a miss and writing fetched bars back to the store.

    This is the standard research/production access pattern: repeated pulls of
    the same window during research hit ClickHouse instead of re-downloading,
    and live ingestion populates the store transparently.
    """

    def __init__(self, upstream: BarSource, store: BarStore | None = None) -> None:
        self._upstream = upstream
        self._store = store if store is not None else get_bar_store()

    @property
    def capabilities(self) -> BarSourceCapabilities:
        return self._upstream.capabilities

    async def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        cached = self._store.load_bars(request)
        if not cached.empty:
            cached_symbols = set(cached.index.get_level_values("symbol").unique())
            if cached_symbols >= set(request.symbols):
                return cached
        fresh = await self._upstream.fetch_bars(request)
        if not fresh.empty:
            self._store.store_bars(fresh, request.resolution)
        return fresh

    async def stream_bars(self, request: BarRequest) -> AsyncIterator[Bar]:
        df = await self.fetch_bars(request)
        for (symbol, timestamp), row in df.iterrows():
            yield Bar(
                symbol=str(symbol),
                timestamp=timestamp.to_pydatetime()
                if isinstance(timestamp, pd.Timestamp)
                else timestamp,
                resolution=request.resolution,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]) if not pd.isna(row["volume"]) else 0.0,
                source=str(row.get("source", "")),
                adjusted_close=None
                if pd.isna(row.get("adjusted_close"))
                else float(row["adjusted_close"]),
                vwap=None if pd.isna(row.get("vwap")) else float(row["vwap"]),
                trade_count=None if pd.isna(row.get("trade_count")) else int(row["trade_count"]),
            )
