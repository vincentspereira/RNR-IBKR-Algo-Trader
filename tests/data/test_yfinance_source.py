"""Tests for the yfinance bar source adapter.

These tests mock ``yfinance.download`` so they require no network and run
deterministically. End-to-end smoke-testing against the real Yahoo Finance API
is in ``tools/smoke_yfinance.py``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from core_trading.data.bars import BarRequest, BarResolution, BarSource
from core_trading.data.sources.yfinance_source import (
    YFinanceBarSource,
    fetch_bars_sync,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _make_multi_symbol_frame(symbols: list[str], n: int = 5) -> pd.DataFrame:
    """Build a frame in the same shape yfinance returns for multi-symbol downloads."""
    dates = pd.date_range("2026-05-01", periods=n, freq="D")
    rng = np.random.default_rng(seed=7)
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Adj Close", "Volume"], symbols],
        names=["Price", "Ticker"],
    )
    data = {}
    for col_name, ticker in columns:
        base = 100.0 + (10 if ticker == "MSFT" else 0)
        if col_name == "Volume":
            data[(col_name, ticker)] = rng.uniform(1_000_000, 5_000_000, n)
        elif col_name == "Adj Close":
            data[(col_name, ticker)] = base + rng.normal(0, 1, n).cumsum()
        else:
            data[(col_name, ticker)] = base + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame(data, index=dates, columns=columns)
    df["High"] = df[[("Open", t) for t in symbols]].values + 2.0
    df["Low"] = df[[("Open", t) for t in symbols]].values - 2.0
    return df


def _make_single_symbol_frame(symbol: str, n: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=n, freq="D")
    rng = np.random.default_rng(seed=11)
    closes = 100.0 + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame(
        {
            "Open": closes - 0.1,
            "High": closes + 1.0,
            "Low": closes - 1.0,
            "Close": closes,
            "Adj Close": closes,
            "Volume": rng.uniform(1_000_000, 5_000_000, n),
        },
        index=dates,
    )
    df.index.name = "Date"
    return df


class TestCapabilities:
    def test_capabilities_reports_no_api_key(self) -> None:
        cap = YFinanceBarSource().capabilities
        assert cap.name == "yfinance"
        assert cap.requires_api_key is False
        assert BarResolution.DAY_1 in cap.supports_resolutions

    def test_unsupported_resolution_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not support"):
            req = BarRequest(
                symbols=("AAPL",),
                resolution=BarResolution.TICK,
                start=_utc(2026, 1, 1),
                end=_utc(2026, 1, 5),
            )
            asyncio.run(YFinanceBarSource().fetch_bars(req))


class TestWindowValidation:
    def test_one_minute_window_too_long_rejected(self) -> None:
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.MINUTE_1,
            start=_utc(2026, 1, 1),
            end=_utc(2026, 4, 1),
        )
        with pytest.raises(ValueError, match="1-minute history"):
            asyncio.run(src.fetch_bars(req))

    def test_hourly_window_too_long_rejected(self) -> None:
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.HOUR_1,
            start=_utc(2020, 1, 1),
            end=_utc(2026, 1, 1),
        )
        with pytest.raises(ValueError, match=r"history to ~730"):
            asyncio.run(src.fetch_bars(req))


class TestFetchBars:
    @pytest.mark.asyncio
    async def test_multi_symbol_frame_shape(self) -> None:
        symbols = ["AAPL", "MSFT"]
        fake = _make_multi_symbol_frame(symbols, n=4)
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=tuple(symbols),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 5),
        )
        with patch("core_trading.data.sources.yfinance_source.yf.download", return_value=fake):
            df = await src.fetch_bars(req)
        assert df.index.names == ["symbol", "timestamp"]
        assert set(df.index.get_level_values("symbol").unique()) == {"AAPL", "MSFT"}
        assert (df["source"] == "yfinance").all()
        BarSource.validate_dataframe(df)

    @pytest.mark.asyncio
    async def test_single_symbol_frame_shape(self) -> None:
        fake = _make_single_symbol_frame("AAPL", n=5)
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 6),
        )
        with patch("core_trading.data.sources.yfinance_source.yf.download", return_value=fake):
            df = await src.fetch_bars(req)
        assert df.index.names == ["symbol", "timestamp"]
        assert set(df.index.get_level_values("symbol").unique()) == {"AAPL"}
        BarSource.validate_dataframe(df)

    @pytest.mark.asyncio
    async def test_empty_yfinance_response_returns_empty_frame(self) -> None:
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 6),
        )
        with patch(
            "core_trading.data.sources.yfinance_source.yf.download",
            return_value=pd.DataFrame(),
        ):
            df = await src.fetch_bars(req)
        assert df.empty
        assert set(["open", "high", "low", "close", "volume", "source"]).issubset(df.columns)


class TestDropInvalid:
    @staticmethod
    def _frame_with_bad_bar(n: int = 5) -> pd.DataFrame:
        fake = _make_single_symbol_frame("CFC", n=n)
        # Yahoo-style malformed bar: high < low on one row.
        fake.iloc[2, fake.columns.get_loc("High")] = 10.0
        fake.iloc[2, fake.columns.get_loc("Low")] = 20.0
        return fake

    @pytest.mark.asyncio
    async def test_strict_mode_rejects_malformed_bar(self) -> None:
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("CFC",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 6),
        )
        with patch(
            "core_trading.data.sources.yfinance_source.yf.download",
            return_value=self._frame_with_bad_bar(),
        ), pytest.raises(ValueError, match="high < low"):
            await src.fetch_bars(req)

    @pytest.mark.asyncio
    async def test_drop_invalid_drops_only_bad_rows(self) -> None:
        src = YFinanceBarSource(drop_invalid=True)
        req = BarRequest(
            symbols=("CFC",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 6),
        )
        with patch(
            "core_trading.data.sources.yfinance_source.yf.download",
            return_value=self._frame_with_bad_bar(),
        ), pytest.warns(UserWarning, match="malformed bar"):
            df = await src.fetch_bars(req)
        assert len(df) == 4  # 5 rows minus the malformed one
        BarSource.validate_dataframe(df)


class TestStreamBars:
    @pytest.mark.asyncio
    async def test_streams_individual_bars(self) -> None:
        fake = _make_single_symbol_frame("AAPL", n=3)
        src = YFinanceBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 4),
        )
        with patch("core_trading.data.sources.yfinance_source.yf.download", return_value=fake):
            bars = [b async for b in src.stream_bars(req)]
        assert len(bars) == 3
        assert all(b.source == "yfinance" for b in bars)
        assert all(b.symbol == "AAPL" for b in bars)
        assert all(b.timestamp.tzinfo is not None for b in bars)


class TestSyncWrapper:
    def test_sync_wrapper_uses_real_async(self) -> None:
        fake = _make_single_symbol_frame("AAPL", n=2)
        with patch("core_trading.data.sources.yfinance_source.yf.download", return_value=fake):
            df = fetch_bars_sync(
                symbols=("AAPL",),
                start=_utc(2026, 5, 1),
                end=_utc(2026, 5, 2),
                resolution=BarResolution.DAY_1,
            )
        assert not df.empty


class TestExpectedSeconds:
    def test_known_resolution(self) -> None:
        src = YFinanceBarSource()
        assert src.expected_seconds(BarResolution.DAY_1) == 86_400
        assert src.expected_seconds(BarResolution.MINUTE_1) == 60

    def test_unknown_resolution(self) -> None:
        src = YFinanceBarSource()
        assert src.expected_seconds(BarResolution.TICK) is None
