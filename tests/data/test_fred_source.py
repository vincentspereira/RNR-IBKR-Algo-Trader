"""Tests for the FRED macro source adapter (mocked)."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core_trading.data.macro import MacroFrequency
from core_trading.data.sources.fred_source import (
    COMMON_SERIES,
    FredMacroSource,
    fred_series_id,
)


@pytest.fixture
def fake_fred() -> MagicMock:
    """Mock of the ``fredapi.Fred`` instance."""
    fake = MagicMock()
    return fake


@pytest.fixture
def fred_source(monkeypatch: pytest.MonkeyPatch, fake_fred: MagicMock) -> FredMacroSource:
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    with patch("core_trading.data.sources.fred_source.Fred", return_value=fake_fred):
        src = FredMacroSource()
    src._fred = fake_fred
    return src


class TestConstruction:
    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FRED API key required"):
            FredMacroSource()

    def test_api_key_argument_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with patch("core_trading.data.sources.fred_source.Fred") as MockFred:
            FredMacroSource(api_key="explicit")
            MockFred.assert_called_once_with(api_key="explicit")

    def test_name(self, fred_source: FredMacroSource) -> None:
        assert fred_source.name == "fred"


class TestFetchSeries:
    @pytest.mark.asyncio
    async def test_returns_macroseries(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        fake_fred.get_series.return_value = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
        fake_fred.get_series_info.return_value = pd.Series(
            {
                "title": "Test Macro Series",
                "frequency_short": "D",
                "units_short": "%",
            }
        )
        s = await fred_source.fetch_series("DGS10")
        assert s.series_id == "DGS10"
        assert s.title == "Test Macro Series"
        assert s.frequency == MacroFrequency.DAILY
        assert s.units == "%"
        assert s.source == "fred"
        assert len(s.values) == 5

    @pytest.mark.asyncio
    async def test_monthly_frequency_recognised(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        idx = pd.date_range("2026-01-01", periods=4, freq="MS")
        fake_fred.get_series.return_value = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)
        fake_fred.get_series_info.return_value = pd.Series(
            {"title": "CPI", "frequency_short": "M", "units_short": "Index"}
        )
        s = await fred_source.fetch_series("CPIAUCSL")
        assert s.frequency == MacroFrequency.MONTHLY

    @pytest.mark.asyncio
    async def test_unknown_frequency_defaults_to_daily(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="D")
        fake_fred.get_series.return_value = pd.Series([1.0, 2.0], index=idx)
        fake_fred.get_series_info.return_value = pd.Series(
            {"title": "X", "frequency_short": "?", "units_short": "x"}
        )
        s = await fred_source.fetch_series("X")
        assert s.frequency == MacroFrequency.DAILY

    @pytest.mark.asyncio
    async def test_non_datetime_index_coerced(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        raw_idx = ["2026-01-01", "2026-01-02", "2026-01-03"]
        fake_fred.get_series.return_value = pd.Series([10.0, 11.0, 12.0], index=raw_idx)
        fake_fred.get_series_info.return_value = pd.Series(
            {"title": "Y", "frequency_short": "D", "units_short": ""}
        )
        s = await fred_source.fetch_series("Y")
        assert isinstance(s.values.index, pd.DatetimeIndex)

    @pytest.mark.asyncio
    async def test_start_end_dates_forwarded(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="D")
        fake_fred.get_series.return_value = pd.Series([1.0, 2.0], index=idx)
        fake_fred.get_series_info.return_value = pd.Series(
            {"title": "X", "frequency_short": "D", "units_short": ""}
        )
        await fred_source.fetch_series(
            "X", start=date(2026, 1, 1), end=date(2026, 1, 2)
        )
        kwargs = fake_fred.get_series.call_args.kwargs
        assert kwargs["observation_start"] == date(2026, 1, 1)
        assert kwargs["observation_end"] == date(2026, 1, 2)


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_dataframe(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        fake_fred.search.return_value = pd.DataFrame(
            {
                "id": ["X1", "X2"],
                "title": ["First", "Second"],
                "frequency_short": ["D", "M"],
                "units_short": ["%", "Index"],
            }
        )
        df = await fred_source.search("cpi", limit=2)
        assert list(df.columns) == ["series_id", "title", "frequency", "units"]
        assert len(df) == 2

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_frame(
        self, fred_source: FredMacroSource, fake_fred: MagicMock
    ) -> None:
        fake_fred.search.return_value = None
        df = await fred_source.search("nonexistent")
        assert df.empty
        assert list(df.columns) == ["series_id", "title", "frequency", "units"]


class TestSeriesIdAlias:
    def test_known_alias(self) -> None:
        assert fred_series_id("VIX") == "VIXCLS"
        assert fred_series_id("10Y_YIELD") == "DGS10"

    def test_unknown_alias_pass_through(self) -> None:
        assert fred_series_id("CUSTOM_ID") == "CUSTOM_ID"

    def test_alias_dict_has_expected_keys(self) -> None:
        for key in ["VIX", "10Y_YIELD", "FED_FUNDS", "UNEMPLOYMENT"]:
            assert key in COMMON_SERIES
