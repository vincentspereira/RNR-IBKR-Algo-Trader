"""Unit tests for core_trading.data.quality."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.data.quality import (
    QualityIssue,
    QualityReport,
    cross_source_compare,
    validate_bar_frame,
)


def _frame(symbol: str, n: int = 30, *, source: str = "test") -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [[symbol], pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")],
        names=["symbol", "timestamp"],
    )
    rng = np.random.default_rng(seed=42)
    closes = 100.0 + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame(
        {
            "open": closes - 0.1,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": rng.uniform(1_000_000, 5_000_000, n),
            "adjusted_close": closes,
            "vwap": None,
            "trade_count": None,
            "source": source,
        },
        index=idx,
    )
    return df


class TestQualityIssue:
    def test_unknown_severity_rejected(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            QualityIssue(severity="critical", category="x", symbol=None, detail="x")


class TestValidateBarFrame:
    def test_clean_frame_passes(self) -> None:
        df = _frame("AAPL")
        report = validate_bar_frame(df, source="test")
        assert not report.has_errors
        assert report.n_rows == 30
        assert report.n_symbols == 1

    def test_empty_frame_yields_warn(self) -> None:
        df = _frame("AAPL").iloc[0:0]
        report = validate_bar_frame(df, source="test")
        assert any(i.category == "empty" for i in report.issues)

    def test_missing_columns_yields_error(self) -> None:
        df = _frame("AAPL").drop(columns=["high"])
        report = validate_bar_frame(df, source="test")
        assert report.has_errors
        assert any(i.category == "schema" for i in report.issues)

    def test_negative_volume_flagged(self) -> None:
        df = _frame("AAPL")
        df = df.copy()
        df.iloc[0, df.columns.get_loc("volume")] = -1.0
        report = validate_bar_frame(df, source="test")
        assert report.has_errors
        assert any(i.category == "negative_volume" for i in report.issues)

    def test_high_below_low_flagged(self) -> None:
        df = _frame("AAPL").copy()
        df.iloc[5, df.columns.get_loc("high")] = df.iloc[5, df.columns.get_loc("low")] - 1.0
        report = validate_bar_frame(df, source="test")
        assert report.has_errors
        assert any(i.category == "high_lt_low" for i in report.issues)

    def test_all_zero_close_flagged(self) -> None:
        df = _frame("AAPL").copy()
        df["close"] = 0.0
        df["high"] = 0.0
        df["low"] = 0.0
        df["open"] = 0.0
        report = validate_bar_frame(df, source="test")
        assert report.has_errors
        assert any(i.category == "all_zero_close" for i in report.issues)


class TestCrossSourceCompare:
    def test_identical_sources_no_issue(self) -> None:
        a = _frame("AAPL", source="srcA")
        b = a.copy()
        b["source"] = "srcB"
        report = cross_source_compare(a, b, tolerance_bps=5.0)
        assert not report.has_warnings

    def test_diverged_sources_flagged(self) -> None:
        a = _frame("AAPL", source="srcA")
        b = a.copy()
        b["close"] = b["close"] * 1.01
        b["source"] = "srcB"
        report = cross_source_compare(a, b, tolerance_bps=5.0)
        assert report.has_warnings

    def test_no_overlap_flagged(self) -> None:
        a = _frame("AAPL", source="srcA")
        b_idx = pd.MultiIndex.from_product(
            [["AAPL"], pd.date_range("2030-01-01", periods=5, freq="D", tz="UTC")],
            names=["symbol", "timestamp"],
        )
        b = pd.DataFrame(
            {"close": [100.0, 101.0, 102.0, 103.0, 104.0], "source": "srcB"},
            index=b_idx,
        )
        report = cross_source_compare(a, b, tolerance_bps=5.0)
        assert any(i.category == "no_overlap" for i in report.issues)


class TestQualityReportFormatting:
    def test_summary_string(self) -> None:
        report = QualityReport(source="x", n_rows=10, n_symbols=2)
        report.issues.append(QualityIssue("warn", "x", None, "d"))
        report.issues.append(QualityIssue("error", "y", None, "d"))
        report.issues.append(QualityIssue("info", "z", None, "d"))
        s = report.summary()
        assert "1 errors" in s
        assert "1 warnings" in s
        assert "1 info" in s


class TestValidateBarFrameExtra:
    def test_all_nan_close_flagged(self) -> None:
        df = _frame("AAPL").copy()
        df["close"] = float("nan")
        report = validate_bar_frame(df, source="test")
        assert any(i.category == "all_nan_close" for i in report.issues)

    def test_price_spike_flagged(self) -> None:
        df = _frame("AAPL", n=60).copy()
        df.iloc[30, df.columns.get_loc("close")] = df.iloc[30, df.columns.get_loc("close")] * 100
        report = validate_bar_frame(df, source="test", spike_z_threshold=3.0)
        assert any(i.category == "price_spike" for i in report.issues)

    def test_time_gap_flagged_when_resolution_given(self) -> None:
        idx = pd.MultiIndex.from_arrays(
            [
                ["AAPL"] * 5,
                pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-02",
                        "2026-01-03",
                        "2026-02-15",
                        "2026-02-16",
                    ],
                    utc=True,
                ),
            ],
            names=["symbol", "timestamp"],
        )
        df = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [101.0] * 5,
                "low": [99.0] * 5,
                "close": [100.5] * 5,
                "volume": [1_000_000.0] * 5,
                "source": "test",
            },
            index=idx,
        )
        report = validate_bar_frame(df, source="test", expected_resolution_seconds=86_400)
        assert any(i.category == "time_gap" for i in report.issues)

    def test_duplicate_rows_flagged(self) -> None:
        idx = pd.MultiIndex.from_arrays(
            [
                ["AAPL", "AAPL", "AAPL"],
                pd.to_datetime(
                    ["2026-01-01", "2026-01-01", "2026-01-02"], utc=True
                ),
            ],
            names=["symbol", "timestamp"],
        )
        df = pd.DataFrame(
            {
                "open": [100.0, 100.0, 101.0],
                "high": [101.0, 101.0, 102.0],
                "low": [99.0, 99.0, 100.0],
                "close": [100.5, 100.5, 101.5],
                "volume": [1.0, 1.0, 1.0],
                "source": "test",
            },
            index=idx,
        )
        report = validate_bar_frame(df, source="test")
        assert any(i.category == "duplicate_rows" for i in report.issues)
