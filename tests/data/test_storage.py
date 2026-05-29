"""Tests for core_trading.data.storage (BarStore + CachingBarSource).

A fake ClickHouse client records inserts and replays them on query, so the
full store/load round-trip is exercised offline. No-client (degraded) mode is
also covered.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from core_trading.data import storage as storage_mod
from core_trading.data.bars import Bar, BarRequest, BarResolution, BarSource
from core_trading.data.storage import BarStore, CachingBarSource, get_bar_store


@pytest.fixture
def force_no_clickhouse(monkeypatch):
    """Deterministically put the storage module in no-client mode.

    Without this, collection order can make ``_CLICKHOUSE_AVAILABLE`` True
    (another test module sets DB-password env vars at import), causing
    ``BarStore(client=None)`` to acquire a real client and attempt a live
    connection. Patching guarantees hermetic no-op behaviour.
    """
    monkeypatch.setattr(storage_mod, "_CLICKHOUSE_AVAILABLE", False)
    monkeypatch.setattr(storage_mod, "get_clickhouse_client", None)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _frame(symbols: list[str], n: int = 3) -> pd.DataFrame:
    bars = []
    for sym in symbols:
        for i in range(n):
            bars.append(
                Bar(
                    symbol=sym,
                    timestamp=_utc(2026, 5, 1) + pd.Timedelta(days=i).to_pytimedelta(),
                    resolution=BarResolution.DAY_1,
                    open=100 + i,
                    high=101 + i,
                    low=99 + i,
                    close=100.5 + i,
                    volume=1_000_000.0,
                    source="test",
                    adjusted_close=100.5 + i,
                )
            )
    return BarSource.bars_to_dataframe(bars)


class FakeClickHouse:
    """Minimal ClickHouse stand-in: stores inserted rows, replays on SELECT."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []
        self.columns: list[str] = []
        self.executed: list[str] = []

    def execute(self, query: str, params: dict | None = None):
        self.executed.append(query.strip().split()[0].upper())
        if query.strip().upper().startswith("SELECT"):
            symbols = set(params["symbols"])
            resolution = params["resolution"]
            out = []
            for r in self.rows:
                # row layout matches _BAR_COLUMNS order
                (sym, res, ts, o, h, low, c, v, adj, vwap, tc, src) = r
                if sym in symbols and res == resolution:
                    out.append((sym, ts, o, h, low, c, v, adj, vwap, tc, src))
            return out
        return []

    def insert_batch(self, table: str, data: list[tuple], columns: list[str]) -> None:
        self.rows.extend(data)
        self.columns = columns


class TestBarStoreDegraded:
    def test_no_client_store_returns_zero(self, force_no_clickhouse) -> None:
        store = BarStore(client=None)
        df = _frame(["AAPL"])
        assert store.store_bars(df, BarResolution.DAY_1) == 0

    def test_no_client_load_returns_empty(self, force_no_clickhouse) -> None:
        store = BarStore(client=None)
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        out = store.load_bars(req)
        assert out.empty

    def test_empty_frame_store_is_noop(self) -> None:
        store = BarStore(client=FakeClickHouse())
        assert store.store_bars(BarSource.bars_to_dataframe([]), BarResolution.DAY_1) == 0


class TestBarStoreRoundTrip:
    def test_store_then_load(self) -> None:
        fake = FakeClickHouse()
        store = BarStore(client=fake)
        df = _frame(["AAPL", "MSFT"], n=3)
        written = store.store_bars(df, BarResolution.DAY_1)
        assert written == 6
        assert "CREATE" in fake.executed[0]

        req = BarRequest(
            symbols=("AAPL", "MSFT"),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        loaded = store.load_bars(req)
        assert len(loaded) == 6
        assert set(loaded.index.get_level_values("symbol").unique()) == {"AAPL", "MSFT"}
        BarSource.validate_dataframe(loaded)

    def test_resolution_filter_on_load(self) -> None:
        fake = FakeClickHouse()
        store = BarStore(client=fake)
        store.store_bars(_frame(["AAPL"]), BarResolution.DAY_1)
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.HOUR_1,  # different resolution -> no match
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        assert store.load_bars(req).empty

    def test_available_property_with_client(self) -> None:
        assert BarStore(client=FakeClickHouse()).available is True

    def test_available_property_no_client(self, force_no_clickhouse) -> None:
        assert BarStore(client=None).available is False


class TestSingleton:
    def test_singleton_returns_same(self) -> None:
        a = get_bar_store()
        b = get_bar_store()
        assert a is b


class TestCachingBarSource:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_upstream(self) -> None:
        fake = FakeClickHouse()
        store = BarStore(client=fake)
        store.store_bars(_frame(["AAPL"]), BarResolution.DAY_1)

        class BoomSource(BarSource):
            @property
            def capabilities(self):
                raise AssertionError("capabilities should not be needed")

            async def fetch_bars(self, request):
                raise AssertionError("upstream must not be called on cache hit")

            async def stream_bars(self, request):
                yield  # pragma: no cover

        caching = CachingBarSource(BoomSource(), store=store)
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        out = await caching.fetch_bars(req)
        assert len(out) == 3

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_and_stores(self) -> None:
        fake = FakeClickHouse()
        store = BarStore(client=fake)
        fetched = _frame(["TSLA"])

        class StubSource(BarSource):
            calls = 0

            @property
            def capabilities(self):
                return None

            async def fetch_bars(self, request):
                StubSource.calls += 1
                return fetched

            async def stream_bars(self, request):
                yield  # pragma: no cover

        caching = CachingBarSource(StubSource(), store=store)
        req = BarRequest(
            symbols=("TSLA",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        out = await caching.fetch_bars(req)
        assert len(out) == 3
        # Stored back to ClickHouse
        assert len(fake.rows) == 3

    @pytest.mark.asyncio
    async def test_capabilities_delegates(self) -> None:
        class CapSource(BarSource):
            @property
            def capabilities(self):
                return "CAP"

            async def fetch_bars(self, request):
                return BarSource.bars_to_dataframe([])

            async def stream_bars(self, request):
                yield  # pragma: no cover

        caching = CachingBarSource(CapSource(), store=BarStore(client=FakeClickHouse()))
        assert caching.capabilities == "CAP"

    @pytest.mark.asyncio
    async def test_stream_after_fetch(self) -> None:
        fake = FakeClickHouse()
        store = BarStore(client=fake)
        store.store_bars(_frame(["AAPL"]), BarResolution.DAY_1)

        class StubSource(BarSource):
            @property
            def capabilities(self):
                return None

            async def fetch_bars(self, request):
                return BarSource.bars_to_dataframe([])

            async def stream_bars(self, request):
                yield  # pragma: no cover

        caching = CachingBarSource(StubSource(), store=store)
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 10),
        )
        streamed = [b async for b in caching.stream_bars(req)]
        assert len(streamed) == 3
        assert all(b.source == "test" for b in streamed)
