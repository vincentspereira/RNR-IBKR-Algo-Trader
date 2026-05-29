"""Tests for the IBKR bar source adapter (mocked IB client).

These mock the ``ib_insync`` client entirely so they run offline. Live
end-to-end validation is in ``tools/smoke_ibkr.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core_trading.data.bars import BarRequest, BarResolution, BarSource
from core_trading.data.sources import ibkr_source
from core_trading.data.sources.ibkr_source import IBKRBarSource, _ib_duration


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _fake_bar(d: datetime, close: float) -> SimpleNamespace:
    return SimpleNamespace(
        date=d,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1_000_000,
        average=close,
        barCount=500,
    )


class TestCapabilities:
    def test_capabilities(self) -> None:
        cap = IBKRBarSource().capabilities
        assert cap.name == "ibkr"
        assert cap.requires_api_key is False
        assert BarResolution.DAY_1 in cap.supports_resolutions

    def test_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IBKR_HOST", "192.168.1.5")
        monkeypatch.setenv("IBKR_PORT", "4002")
        src = IBKRBarSource()
        assert src._host == "192.168.1.5"
        assert src._port == 4002

    def test_explicit_args_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IBKR_HOST", "192.168.1.5")
        src = IBKRBarSource(host="10.0.0.1", port=7496)
        assert src._host == "10.0.0.1"
        assert src._port == 7496


class TestDurationHelper:
    def test_short_window_days(self) -> None:
        assert _ib_duration(_utc(2026, 1, 1), _utc(2026, 1, 31)) == "30 D"

    def test_long_window_years(self) -> None:
        out = _ib_duration(_utc(2020, 1, 1), _utc(2026, 1, 1))
        assert out.endswith(" Y")

    def test_minimum_one_day(self) -> None:
        assert _ib_duration(_utc(2026, 1, 1), _utc(2026, 1, 1)) == "1 D"


class TestResolutionMapping:
    def test_unsupported_resolution_rejected(self) -> None:
        src = IBKRBarSource()
        with pytest.raises(ValueError, match="does not support"):
            src._native_barsize(BarResolution.TICK)

    def test_known_resolution(self) -> None:
        src = IBKRBarSource()
        assert src._native_barsize(BarResolution.DAY_1) == "1 day"

    def test_expected_seconds(self) -> None:
        src = IBKRBarSource()
        assert src.expected_seconds(BarResolution.DAY_1) == 86_400
        assert src.expected_seconds(BarResolution.TICK) is None


class TestTimestampCoercion:
    def test_naive_datetime_gets_utc(self) -> None:
        out = IBKRBarSource._bar_timestamp(datetime(2026, 5, 1, 14, 30))
        assert out.tzinfo is not None

    def test_aware_datetime_converted_to_utc(self) -> None:
        out = IBKRBarSource._bar_timestamp(_utc(2026, 5, 1))
        assert out.tzinfo == timezone.utc

    def test_date_string_coerced(self) -> None:
        out = IBKRBarSource._bar_timestamp("2026-05-01")
        assert out.tzinfo is not None
        assert out.year == 2026


def _install_fake_ib(monkeypatch: pytest.MonkeyPatch, fake_ib: MagicMock) -> None:
    """Patch ib_insync's IB and Stock symbols used inside the adapter."""
    import sys
    fake_module = MagicMock()
    fake_module.IB = MagicMock(return_value=fake_ib)
    fake_module.Stock = MagicMock(side_effect=lambda *a, **k: SimpleNamespace(symbol=a[0]))
    fake_module.util = MagicMock()
    monkeypatch.setitem(sys.modules, "ib_insync", fake_module)


class TestFetchBars:
    @pytest.mark.asyncio
    async def test_fetch_returns_frame(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = False
        fake_ib.connectAsync = AsyncMock()
        fake_ib.qualifyContractsAsync = AsyncMock(
            return_value=[SimpleNamespace(conId=1, symbol="AAPL")]
        )
        bars = [
            _fake_bar(_utc(2026, 5, 1), 100.0),
            _fake_bar(_utc(2026, 5, 2), 101.0),
            _fake_bar(_utc(2026, 5, 3), 102.0),
        ]
        fake_ib.reqHistoricalDataAsync = AsyncMock(return_value=bars)
        _install_fake_ib(monkeypatch, fake_ib)

        src = IBKRBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 4, 30),
            end=_utc(2026, 5, 4),
        )
        df = await src.fetch_bars(req)
        assert df.index.names == ["symbol", "timestamp"]
        assert len(df) == 3
        assert (df["source"] == "ibkr").all()
        BarSource.validate_dataframe(df)

    @pytest.mark.asyncio
    async def test_out_of_window_bars_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = False
        fake_ib.connectAsync = AsyncMock()
        fake_ib.qualifyContractsAsync = AsyncMock(
            return_value=[SimpleNamespace(conId=1)]
        )
        bars = [
            _fake_bar(_utc(2026, 4, 1), 90.0),   # before window
            _fake_bar(_utc(2026, 5, 2), 101.0),  # in window
        ]
        fake_ib.reqHistoricalDataAsync = AsyncMock(return_value=bars)
        _install_fake_ib(monkeypatch, fake_ib)

        src = IBKRBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 4),
        )
        df = await src.fetch_bars(req)
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_unqualified_contract_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = False
        fake_ib.connectAsync = AsyncMock()
        fake_ib.qualifyContractsAsync = AsyncMock(return_value=[])
        _install_fake_ib(monkeypatch, fake_ib)

        src = IBKRBarSource()
        req = BarRequest(
            symbols=("BADSYM",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 5, 1),
            end=_utc(2026, 5, 4),
        )
        with pytest.raises(RuntimeError, match="could not qualify"):
            await src.fetch_bars(req)

    @pytest.mark.asyncio
    async def test_stream_bars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = False
        fake_ib.connectAsync = AsyncMock()
        fake_ib.qualifyContractsAsync = AsyncMock(
            return_value=[SimpleNamespace(conId=1)]
        )
        bars = [_fake_bar(_utc(2026, 5, 1), 100.0), _fake_bar(_utc(2026, 5, 2), 101.0)]
        fake_ib.reqHistoricalDataAsync = AsyncMock(return_value=bars)
        _install_fake_ib(monkeypatch, fake_ib)

        src = IBKRBarSource()
        req = BarRequest(
            symbols=("AAPL",),
            resolution=BarResolution.DAY_1,
            start=_utc(2026, 4, 30),
            end=_utc(2026, 5, 4),
        )
        streamed = [b async for b in src.stream_bars(req)]
        assert len(streamed) == 2
        assert all(b.source == "ibkr" for b in streamed)


class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect_skips_if_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = True
        fake_ib.connectAsync = AsyncMock()
        src = IBKRBarSource()
        src._ib = fake_ib
        await src.connect()
        fake_ib.connectAsync.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_when_connected(self) -> None:
        fake_ib = MagicMock()
        fake_ib.isConnected.return_value = True
        src = IBKRBarSource()
        src._ib = fake_ib
        await src.disconnect()
        fake_ib.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_noop_when_not_connected(self) -> None:
        src = IBKRBarSource()
        await src.disconnect()  # should not raise
