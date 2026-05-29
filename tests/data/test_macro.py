"""Unit tests for core_trading.data.macro."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core_trading.data.macro import MacroFrequency, MacroSeries


def _series(n: int = 30) -> pd.Series:
    return pd.Series(
        range(n),
        index=pd.date_range("2026-01-01", periods=n, freq="D"),
    )


class TestMacroSeries:
    def test_basic_construction(self) -> None:
        s = MacroSeries(
            series_id="X",
            title="Test",
            frequency=MacroFrequency.DAILY,
            units="%",
            source="test",
            values=_series(5),
        )
        assert s.series_id == "X"
        assert len(s.values) == 5

    def test_non_series_values_rejected(self) -> None:
        with pytest.raises(TypeError, match="pandas Series"):
            MacroSeries(
                series_id="X",
                title="x",
                frequency=MacroFrequency.DAILY,
                units="",
                source="t",
                values=[1, 2, 3],
            )

    def test_non_datetime_index_rejected(self) -> None:
        bad = pd.Series([1, 2], index=["a", "b"])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            MacroSeries(
                series_id="X",
                title="x",
                frequency=MacroFrequency.DAILY,
                units="",
                source="t",
                values=bad,
            )

    def test_as_of_filter(self) -> None:
        s = MacroSeries(
            series_id="X",
            title="x",
            frequency=MacroFrequency.DAILY,
            units="",
            source="t",
            values=_series(10),
        )
        cutoff = s.values.index[4].date()
        sliced = s.as_of(cutoff)
        assert len(sliced) == 5
        assert sliced.index[-1].date() == cutoff
