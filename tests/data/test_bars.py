"""Unit tests for core_trading.data.bars."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core_trading.data.bars import (
    Bar,
    BarRequest,
    BarResolution,
    BarSource,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestBar:
    def test_minimal_bar_constructs(self) -> None:
        b = Bar(
            symbol="AAPL",
            timestamp=_utc(2026, 5, 28),
            resolution=BarResolution.DAY_1,
            open=200.0,
            high=205.0,
            low=199.0,
            close=204.0,
            volume=1_000_000.0,
            source="yfinance",
        )
        assert b.symbol == "AAPL"
        assert b.adjusted_close is None
        assert b.vwap is None

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            Bar(
                symbol="AAPL",
                timestamp=datetime(2026, 5, 28),
                resolution=BarResolution.DAY_1,
                open=1, high=1, low=1, close=1, volume=0, source="x",
            )

    def test_high_below_low_rejected(self) -> None:
        with pytest.raises(ValueError, match="high.*low"):
            Bar(
                symbol="X",
                timestamp=_utc(2026, 5, 28),
                resolution=BarResolution.DAY_1,
                open=10, high=5, low=8, close=9, volume=100, source="x",
            )

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            Bar(
                symbol="X",
                timestamp=_utc(2026, 5, 28),
                resolution=BarResolution.DAY_1,
                open=10, high=11, low=9, close=10, volume=-1, source="x",
            )


class TestBarRequest:
    def test_minimal_request(self) -> None:
        r = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 1, 1),
            end=_utc(2026, 1, 31),
        )
        assert r.symbols == ("AAPL",)

    def test_empty_symbols_rejected(self) -> None:
        with pytest.raises(ValueError, match="symbols"):
            BarRequest(
                symbols=(),
                resolution=BarResolution.DAY_1,
                start=_utc(2026, 1, 1),
                end=_utc(2026, 1, 31),
            )

    def test_start_after_end_rejected(self) -> None:
        with pytest.raises(ValueError, match="strictly before"):
            BarRequest(
                symbols=("AAPL",),
                resolution=BarResolution.DAY_1,
                start=_utc(2026, 2, 1),
                end=_utc(2026, 1, 1),
            )

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            BarRequest(
                symbols=("AAPL",),
                resolution=BarResolution.DAY_1,
                start=datetime(2026, 1, 1),
                end=datetime(2026, 1, 31),
            )


class TestBarSourceHelpers:
    def test_bars_to_dataframe_empty(self) -> None:
        df = BarSource.bars_to_dataframe([])
        assert df.empty
        assert set(["open", "high", "low", "close", "volume", "source"]).issubset(df.columns)

    def test_bars_to_dataframe_roundtrip(self) -> None:
        bars = [
            Bar(
                symbol="AAPL",
                timestamp=_utc(2026, 5, 28) + timedelta(days=i),
                resolution=BarResolution.DAY_1,
                open=200 + i, high=201 + i, low=199 + i, close=200.5 + i,
                volume=1_000_000.0, source="test",
            )
            for i in range(3)
        ]
        df = BarSource.bars_to_dataframe(bars)
        assert len(df) == 3
        assert df.index.names == ["symbol", "timestamp"]
        BarSource.validate_dataframe(df)

    def test_validate_dataframe_rejects_missing_columns(self) -> None:
        df = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
            index=pd.MultiIndex.from_tuples(
                [("AAPL", pd.Timestamp("2026-05-28", tz="UTC"))],
                names=["symbol", "timestamp"],
            ),
        )
        with pytest.raises(ValueError, match="missing required columns"):
            BarSource.validate_dataframe(df)
