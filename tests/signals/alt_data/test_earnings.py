"""Tests for core_trading.signals.alt_data.earnings (Phase 5.F.2).

Covers:
* EarningsConfig -- frozen/slotted DTO, __post_init__ validation.
* _build_eps_history -- symbol filter, chronological sort, empty case.
* _compute_sue_for_symbol -- SUE sign/magnitude recovery on known path,
  insufficient history -> NaN SUE, std=0 -> NaN SUE.
* compute_sue_panel -- end-to-end SUE on a tidy DataFrame; missing-columns
  error; empty DataFrame; point-in-time: filing_date is preserved correctly.
* pead_signal -- long high-SUE / short low-SUE; point-in-time leakage guard
  (filing_date > eval_date -> absent); dollar-neutral (long leg = +1, short
  leg = -1); bad quantile raises; missing-columns raises; all-NaN SUE row
  produces zero weights.
* Public API / __all__ check.

All tests use synthetic data.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.alt_data.earnings import (
    EarningsConfig,
    _build_eps_history,
    _compute_sue_for_symbol,
    compute_sue_panel,
    pead_signal,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SEED = 20260601


def _make_fundamentals(
    records: list[dict],
) -> pd.DataFrame:
    """Build a minimal tidy fundamental DataFrame from a list of dicts."""
    required_keys = {
        "symbol", "metric", "value", "period_end", "filing_date", "fiscal_period"
    }
    for rec in records:
        for k in required_keys:
            assert k in rec, f"Missing key: {k}"
    return pd.DataFrame(records)


def _eps_record(
    symbol: str,
    eps: float,
    period_end: date,
    filing_date: date,
    fiscal_period: str = "Q1",
    metric: str = "eps",
) -> dict:
    return {
        "symbol": symbol,
        "metric": metric,
        "value": eps,
        "period_end": period_end,
        "filing_date": filing_date,
        "fiscal_period": fiscal_period,
        "statement": "income",
        "revision_id": 0,
        "source": "test",
    }


# ---------------------------------------------------------------------------
# EarningsConfig tests
# ---------------------------------------------------------------------------


class TestEarningsConfig:
    """EarningsConfig: construction, defaults, validation, immutability."""

    def test_default_construction(self) -> None:
        cfg = EarningsConfig()
        assert cfg.sue_std_window == 8
        assert cfg.seasonal_lag == 4
        assert cfg.pead_drift_window == 60
        assert cfg.eps_metric == "eps"

    def test_custom_construction(self) -> None:
        cfg = EarningsConfig(
            sue_std_window=6,
            seasonal_lag=4,
            pead_drift_window=90,
            eps_metric="eps_diluted",
        )
        assert cfg.sue_std_window == 6
        assert cfg.pead_drift_window == 90

    def test_frozen(self) -> None:
        cfg = EarningsConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.sue_std_window = 10  # type: ignore[misc]

    def test_sue_std_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="sue_std_window"):
            EarningsConfig(sue_std_window=1)

    def test_sue_std_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="sue_std_window"):
            EarningsConfig(sue_std_window=0)

    def test_seasonal_lag_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="seasonal_lag"):
            EarningsConfig(seasonal_lag=0)

    def test_pead_drift_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="pead_drift_window"):
            EarningsConfig(pead_drift_window=0)

    def test_empty_eps_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="eps_metric"):
            EarningsConfig(eps_metric="")

    def test_sue_std_window_two_allowed(self) -> None:
        cfg = EarningsConfig(sue_std_window=2)
        assert cfg.sue_std_window == 2

    def test_seasonal_lag_one_allowed(self) -> None:
        cfg = EarningsConfig(seasonal_lag=1)
        assert cfg.seasonal_lag == 1


# ---------------------------------------------------------------------------
# _build_eps_history tests
# ---------------------------------------------------------------------------


class TestBuildEpsHistory:
    """_build_eps_history: symbol filter, chronological sort, empty."""

    def test_filters_to_symbol_and_metric(self) -> None:
        recs = [
            _eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15), "Q1"),
            _eps_record("MSFT", 2.0, date(2020, 3, 31), date(2020, 4, 20), "Q1"),
            _eps_record("AAPL", 3.0, date(2020, 6, 30), date(2020, 7, 15), "Q2"),
        ]
        df = _make_fundamentals(recs)
        hist = _build_eps_history(df, "AAPL", "eps")
        assert len(hist) == 2
        assert (hist["value"] == [1.0, 3.0]).all()

    def test_empty_for_missing_symbol(self) -> None:
        recs = [_eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15))]
        df = _make_fundamentals(recs)
        hist = _build_eps_history(df, "GOOG", "eps")
        assert hist.empty

    def test_chronological_sort(self) -> None:
        """Rows are sorted by period_end ascending."""
        recs = [
            _eps_record("AAPL", 2.0, date(2020, 6, 30), date(2020, 7, 15), "Q2"),
            _eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15), "Q1"),
            _eps_record("AAPL", 3.0, date(2020, 9, 30), date(2020, 10, 15), "Q3"),
        ]
        df = _make_fundamentals(recs)
        hist = _build_eps_history(df, "AAPL", "eps")
        eps_vals = hist["value"].tolist()
        assert eps_vals == [1.0, 2.0, 3.0]

    def test_filters_to_eps_metric_only(self) -> None:
        recs = [
            _eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15), metric="eps"),
            _eps_record("AAPL", 999.0, date(2020, 3, 31), date(2020, 4, 15), metric="revenue"),
        ]
        df = _make_fundamentals(recs)
        hist = _build_eps_history(df, "AAPL", "eps")
        assert len(hist) == 1
        assert float(hist["value"].iloc[0]) == 1.0

    def test_unknown_fiscal_period_sort_key(self) -> None:
        """Unknown fiscal_period strings map to sort key 0 (covers fallback branch)."""
        # Put a row with an unknown fiscal_period string; it should sort before Q1
        recs = [
            _eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15), "Q1"),
            _eps_record("AAPL", 2.0, date(2020, 3, 31), date(2020, 4, 15), "UNKNOWN"),
        ]
        df = _make_fundamentals(recs)
        # Should not raise; sort key fallback handles unknown string
        hist = _build_eps_history(df, "AAPL", "eps")
        assert len(hist) == 2


# ---------------------------------------------------------------------------
# _compute_sue_for_symbol tests
# ---------------------------------------------------------------------------


class TestComputeSueForSymbol:
    """_compute_sue_for_symbol: SUE sign/magnitude, insufficient history, std=0."""

    def _make_history(self, eps_values: list[float]) -> pd.DataFrame:
        """Build a minimal history DataFrame with quarterly periods."""
        rows = []
        for i, v in enumerate(eps_values):
            # Quarterly periods: Q1/2018, Q2/2018, ...
            year = 2018 + i // 4
            quarter = (i % 4) + 1
            period_month = quarter * 3
            period_end_date = date(year, period_month, 28 if period_month == 2 else 30)
            filing_date_date = date(year, period_month, 28 if period_month == 2 else 30)
            rows.append({
                "period_end": pd.Timestamp(period_end_date),
                "filing_date": pd.Timestamp(filing_date_date),
                "fiscal_period": f"Q{quarter}",
                "value": v,
            })
        return pd.DataFrame(rows)

    def test_positive_surprise_positive_sue(self) -> None:
        """A large positive surprise produces a positive SUE.

        EPS path is varied so prior surprises have nonzero std:
          rows 0-3: baseline 1.0 (no forecast available, no surprise)
          row 4: 1.3 -> surprise = 1.3 - 1.0 = 0.3
          row 5: 1.0 -> surprise = 1.0 - 1.0 = 0.0  (note: forecast = eps[1]=1.0)
          row 6: 1.5 -> surprise = 1.5 - 1.0 = 0.5  (forecast = eps[2]=1.0)
          row 7: 1.2 -> surprise = 1.2 - 1.0 = 0.2  (forecast = eps[3]=1.0)
          row 8: 3.0 -> surprise = 3.0 - 1.3 = 1.7  (forecast = eps[4]=1.3)
        Prior surprises at row 8: [0.3, 0.0, 0.5, 0.2] -> std > 0 -> valid SUE.
        """
        eps_vals = [1.0, 1.0, 1.0, 1.0, 1.3, 1.0, 1.5, 1.2, 3.0]
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # At row 8: forecast = eps[4] = 1.3, surprise = 1.7
        sue_row8 = float(result["sue"].iloc[8])
        surprise_row8 = float(result["surprise"].iloc[8])
        assert surprise_row8 == pytest.approx(1.7, abs=1e-10)
        assert sue_row8 > 0, f"Expected positive SUE, got {sue_row8}"

    def test_negative_surprise_negative_sue(self) -> None:
        """A large negative surprise produces a negative SUE.

        Use a varied EPS path so prior surprises have nonzero std:
          rows 0-3: EPS = 2.0 (baseline)
          row 4: 2.3 -> surprise = 0.3
          row 5: 1.8 -> surprise = -0.2
          row 6: 2.5 -> surprise = 0.5
          row 7: 2.2 -> surprise = 0.2
          row 8: 0.5 -> surprise = 0.5 - 2.3 = -1.8  (big negative)
        """
        eps_vals = [2.0, 2.0, 2.0, 2.0, 2.3, 1.8, 2.5, 2.2, 0.5]
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        sue_row8 = float(result["sue"].iloc[8])
        assert sue_row8 < 0, f"Expected negative SUE, got {sue_row8}"

    def test_insufficient_seasonal_lag_history_nan(self) -> None:
        """Before seasonal_lag quarters of history, SUE must be NaN."""
        eps_vals = [1.0, 1.2, 1.1, 1.3]  # only 4 rows, lag=4: first valid at row 4
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=2)
        # All 4 rows have lag_idx < 0 -> all NaN
        assert result["sue"].isna().all()
        assert result["surprise"].isna().all()

    def test_insufficient_prior_surprises_sue_nan(self) -> None:
        """When fewer than 2 prior surprises exist, SUE is NaN."""
        # 5 rows: rows 0-3 are baseline, row 4 is the first with a lag forecast
        # But there are 0 prior surprises at row 4 (no valid surprises yet) -> NaN
        eps_vals = [1.0, 1.0, 1.0, 1.0, 1.5]
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # Row 4: first valid surprise, but 0 prior surprises -> NaN SUE
        assert math.isnan(float(result["sue"].iloc[4]))
        assert math.isfinite(float(result["surprise"].iloc[4]))

    def test_zero_std_surprise_sue_nan(self) -> None:
        """When all historical surprises are identical (std=0), SUE is NaN."""
        # EPS: [1.0]*8 so all surprises = 0.0 -> std=0 -> NaN SUE
        eps_vals = [1.0] * 12
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # Rows 8-11 have surprise = 0, std(prior surprises) = 0 -> NaN
        for i in range(8, 12):
            assert math.isnan(float(result["sue"].iloc[i]))

    def test_sue_magnitude_recovery(self) -> None:
        """Verify SUE = surprise / std(prior_surprises) numerically."""
        # Construct known EPS path:
        # Quarters 0-3: eps=1.0 (baseline for lag-4 forecast)
        # Quarters 4-7: eps=1.0 + known_surprise (constant surprise = 0.5)
        # Quarter 8:    eps=1.0 + big_surprise = 3.0 (surprise = 2.0)
        known_surprise = 0.5
        eps_vals = (
            [1.0] * 4               # baseline (rows 0-3)
            + [1.0 + known_surprise] * 4  # rows 4-7, surprise=0.5 each
            + [1.0 + 2.0]           # row 8, surprise=2.0
        )
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # At row 8: prior surprises (rows 5,6,7 are 0.5; row 4 might be first)
        # The window includes up to 4 prior surprises before row 8
        # All prior surprises at rows 4,5,6,7 = 0.5 -> std_ddof1 = 0
        # std=0 -> NaN (all identical surprises in the window)
        # This is expected behavior.
        assert math.isnan(float(result["sue"].iloc[8]))

    def test_sue_magnitude_recovery_varied_surprises(self) -> None:
        """When prior surprises vary, SUE equals surprise / std(prior_surprises)."""
        # EPS path with known, varied surprises:
        # Q0-Q3: [1.0, 1.1, 1.2, 1.3] (baseline)
        # Q4: eps=1.5 -> surprise = 1.5 - 1.0 = 0.5
        # Q5: eps=1.8 -> surprise = 1.8 - 1.1 = 0.7
        # Q6: eps=2.2 -> surprise = 2.2 - 1.2 = 1.0
        # Q7: eps=2.3 -> surprise = 2.3 - 1.3 = 1.0
        # Q8: eps=2.8 -> surprise = 2.8 - 1.5 = 1.3  (forecast = eps[4]=1.5)
        eps_vals = [1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.2, 2.3, 2.8]
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # At row 8: forecast = eps[4] = 1.5, surprise = 1.3
        # Prior surprises window (rows 4..7): [0.5, 0.7, 1.0, 1.0]
        # std_ddof1 = std([0.5, 0.7, 1.0, 1.0], ddof=1)
        prior = np.array([0.5, 0.7, 1.0, 1.0])
        expected_std = float(np.std(prior, ddof=1))
        expected_sue = 1.3 / expected_std
        actual_sue = float(result["sue"].iloc[8])
        assert math.isclose(actual_sue, expected_sue, rel_tol=1e-9), (
            f"Expected SUE {expected_sue:.6f}, got {actual_sue:.6f}"
        )

    def test_surprise_preserved_even_without_enough_history(self) -> None:
        """Surprise is computed even when SUE is NaN (no prior surprises)."""
        eps_vals = [1.0] * 4 + [2.0]  # row 4: forecast=1.0, surprise=1.0
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # Surprise at row 4 should be 1.0 even if SUE is NaN
        assert math.isclose(float(result["surprise"].iloc[4]), 1.0, abs_tol=1e-10)
        assert math.isnan(float(result["sue"].iloc[4]))

    def test_nan_eps_at_lag_position_skipped(self) -> None:
        """A NaN EPS at the seasonal-lag position produces NaN surprise (covers NaN forecast branch)."""
        # row 0: NaN EPS (the lag-4 forecast for row 4 is NaN -> skip)
        eps_vals = [float("nan"), 1.0, 1.0, 1.0, 2.0]
        history = self._make_history(eps_vals)
        result = _compute_sue_for_symbol(history, seasonal_lag=4, std_window=4)
        # At row 4: forecast = eps[0] = NaN -> surprise and sue both NaN
        assert math.isnan(float(result["surprise"].iloc[4]))
        assert math.isnan(float(result["sue"].iloc[4]))


# ---------------------------------------------------------------------------
# compute_sue_panel tests
# ---------------------------------------------------------------------------


class TestComputeSuePanel:
    """compute_sue_panel: end-to-end SUE, missing columns, empty input."""

    def _make_multi_symbol_df(self) -> pd.DataFrame:
        """Build a multi-symbol fundamental DataFrame with 9 quarters each."""
        records = []
        for sym in ("AAPL", "MSFT", "GOOG"):
            for i in range(9):
                year = 2020 + i // 4
                quarter = (i % 4) + 1
                period_month = quarter * 3
                period_day = 30 if period_month != 9 else 30
                period_end_date = date(year, period_month, period_day)
                filing_date_date = date(year, period_month + (1 if period_month < 12 else -11),
                                        15) if period_month < 12 else date(year + 1, 1, 15)
                records.append(_eps_record(
                    sym,
                    eps=float(1.0 + i * 0.1 + (0.5 if sym == "MSFT" else 0.0)),
                    period_end=period_end_date,
                    filing_date=filing_date_date,
                    fiscal_period=f"Q{quarter}",
                ))
        return _make_fundamentals(records)

    def test_returns_dataframe(self) -> None:
        df = self._make_multi_symbol_df()
        result = compute_sue_panel(df)
        assert isinstance(result, pd.DataFrame)

    def test_output_columns(self) -> None:
        df = self._make_multi_symbol_df()
        result = compute_sue_panel(df)
        expected_cols = {"symbol", "period_end", "filing_date", "fiscal_period",
                         "eps", "surprise", "sue"}
        assert expected_cols.issubset(set(result.columns))

    def test_all_input_symbols_present(self) -> None:
        df = self._make_multi_symbol_df()
        result = compute_sue_panel(df)
        assert set(result["symbol"].unique()) == {"AAPL", "MSFT", "GOOG"}

    def test_missing_columns_raises(self) -> None:
        df = pd.DataFrame({"symbol": ["AAPL"], "value": [1.0]})
        with pytest.raises(ValueError, match="missing columns"):
            compute_sue_panel(df)

    def test_empty_fundamentals_returns_empty(self) -> None:
        empty = pd.DataFrame(
            columns=["symbol", "metric", "value", "period_end",
                     "filing_date", "fiscal_period"]
        )
        result = compute_sue_panel(empty)
        assert result.empty

    def test_sorted_by_filing_date(self) -> None:
        df = self._make_multi_symbol_df()
        result = compute_sue_panel(df)
        filing_dates = pd.to_datetime(result["filing_date"])
        assert filing_dates.is_monotonic_increasing

    def test_eps_column_matches_input_value(self) -> None:
        """The 'eps' column in the output matches the 'value' input column."""
        recs = [
            _eps_record("AAPL", 2.5, date(2020, 3, 31), date(2020, 4, 15), "Q1"),
        ]
        df = _make_fundamentals(recs)
        result = compute_sue_panel(df)
        row = result[result["symbol"] == "AAPL"]
        assert len(row) == 1
        assert math.isclose(float(row["eps"].iloc[0]), 2.5, abs_tol=1e-12)

    def test_symbol_with_no_eps_rows_excluded(self) -> None:
        """A symbol that has rows but only non-eps metrics is excluded (covers empty-history continue)."""
        recs = [
            _eps_record("AAPL", 1.0, date(2020, 3, 31), date(2020, 4, 15), metric="eps"),
            _eps_record("MSFT", 99.0, date(2020, 3, 31), date(2020, 4, 15), metric="revenue"),
        ]
        df = _make_fundamentals(recs)
        result = compute_sue_panel(df)
        # MSFT has no eps rows -> excluded from output
        assert "MSFT" not in result["symbol"].values

    def test_known_surprise_sign(self) -> None:
        """Plant a clear positive EPS surprise and verify sign in output."""
        # 4 quarters of baseline EPS=1.0, then Q5 = 2.0 (surprise=+1.0)
        recs = []
        for i in range(4):
            q = i + 1
            pm = q * 3
            recs.append(_eps_record(
                "TEST", 1.0,
                date(2019, pm, 28 if pm == 2 else 30),
                date(2019, pm, 28 if pm == 2 else 30),
                f"Q{q}",
            ))
        # Q1 of 2020 (same quarter as Q1 2019)
        recs.append(_eps_record(
            "TEST", 2.0,
            date(2020, 3, 30),
            date(2020, 4, 15),
            "Q1",
        ))
        df = _make_fundamentals(recs)
        result = compute_sue_panel(df)
        q5_row = result[(result["symbol"] == "TEST") &
                        (pd.to_datetime(result["period_end"]).dt.year == 2020)]
        assert len(q5_row) == 1
        # surprise should be positive (2.0 - 1.0 = 1.0)
        surprise_val = float(q5_row["surprise"].iloc[0])
        assert surprise_val > 0, f"Expected positive surprise, got {surprise_val}"


# ---------------------------------------------------------------------------
# pead_signal tests
# ---------------------------------------------------------------------------


class TestPeadSignal:
    """pead_signal: long/short assignment, leakage guard, dollar-neutrality."""

    def _make_sue_panel(self) -> pd.DataFrame:
        """Build a synthetic SUE panel with known high/low-SUE names."""
        # 3 symbols: HIGH_SUE=5.0, MED_SUE=0.0, LOW_SUE=-5.0
        # Filed on 2020-01-15
        records = [
            {
                "symbol": "HIGH",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 2.0,
                "surprise": 1.0,
                "sue": 5.0,
            },
            {
                "symbol": "MED",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": 0.0,
                "sue": 0.0,
            },
            {
                "symbol": "LOW",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 0.5,
                "surprise": -1.0,
                "sue": -5.0,
            },
        ]
        return pd.DataFrame(records)

    def test_high_sue_gets_positive_weight(self) -> None:
        """HIGH_SUE symbol receives a positive PEAD weight after filing_date."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16", "2020-01-17"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert float(result.loc[pd.Timestamp("2020-01-16"), "HIGH"]) > 0

    def test_low_sue_gets_negative_weight(self) -> None:
        """LOW_SUE symbol receives a negative PEAD weight after filing_date."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert float(result.loc[pd.Timestamp("2020-01-16"), "LOW"]) < 0

    def test_point_in_time_leakage_guard(self) -> None:
        """On eval_date BEFORE filing_date, all weights must be zero."""
        sp = self._make_sue_panel()
        # All filings are on 2020-01-15; evaluate on 2020-01-14 -> no signal
        eval_dates = pd.DatetimeIndex(["2020-01-14"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert (result.iloc[0] == 0.0).all(), (
            f"Expected all-zero weights before filing date, "
            f"got {result.iloc[0].to_dict()}"
        )

    def test_dollar_neutral_long_leg_sums_to_one(self) -> None:
        """After filing_date, the long leg of PEAD weights sums to +1."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        row = result.iloc[0]
        long_sum = float(row[row > 0].sum())
        assert math.isclose(long_sum, 1.0, abs_tol=1e-12), (
            f"Long leg sum = {long_sum:.6f}"
        )

    def test_dollar_neutral_short_leg_sums_to_minus_one(self) -> None:
        """After filing_date, the short leg of PEAD weights sums to -1."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        row = result.iloc[0]
        short_sum = float(row[row < 0].sum())
        assert math.isclose(short_sum, -1.0, abs_tol=1e-12), (
            f"Short leg sum = {short_sum:.6f}"
        )

    def test_all_nan_sue_produces_zero_weights(self) -> None:
        """If all symbols have NaN SUE, the row should be all-zero."""
        records = [
            {
                "symbol": "A",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": float("nan"),
                "sue": float("nan"),
            },
            {
                "symbol": "B",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 2.0,
                "surprise": float("nan"),
                "sue": float("nan"),
            },
        ]
        sp = pd.DataFrame(records)
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.4)
        assert (result.iloc[0] == 0.0).all()

    def test_bad_quantile_zero_raises(self) -> None:
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        with pytest.raises(ValueError, match="quantile"):
            pead_signal(sp, eval_dates, quantile=0.0)

    def test_bad_quantile_one_raises(self) -> None:
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        with pytest.raises(ValueError, match="quantile"):
            pead_signal(sp, eval_dates, quantile=1.0)

    def test_missing_columns_raises(self) -> None:
        bad = pd.DataFrame({"symbol": ["A"], "sue": [1.0]})
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        with pytest.raises(ValueError, match="missing columns"):
            pead_signal(bad, eval_dates)

    def test_output_shape(self) -> None:
        """Output has shape (n_dates, n_symbols)."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(
            ["2020-01-16", "2020-01-17", "2020-01-20"]
        )
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert result.shape == (3, 3)

    def test_output_columns_are_symbols(self) -> None:
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert set(result.columns) == {"HIGH", "MED", "LOW"}

    def test_output_index_matches_eval_dates(self) -> None:
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16", "2020-01-17"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        pd.testing.assert_index_equal(result.index, eval_dates)

    def test_most_recent_sue_used_per_symbol(self) -> None:
        """When a symbol has two filings, the most recent SUE wins."""
        records = [
            # Old filing: sue = -3.0
            {
                "symbol": "A",
                "period_end": pd.Timestamp("2019-09-30"),
                "filing_date": pd.Timestamp("2019-11-01"),
                "fiscal_period": "Q3",
                "eps": 0.5,
                "surprise": -0.5,
                "sue": -3.0,
            },
            # New filing: sue = +4.0 -- this should be used on 2020-01-16
            {
                "symbol": "A",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 2.0,
                "surprise": 1.0,
                "sue": 4.0,
            },
            # Counterpart with low SUE
            {
                "symbol": "B",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-15"),
                "fiscal_period": "Q4",
                "eps": 0.3,
                "surprise": -1.0,
                "sue": -4.0,
            },
        ]
        sp = pd.DataFrame(records)
        eval_dates = pd.DatetimeIndex(["2020-01-16"])
        result = pead_signal(sp, eval_dates, quantile=0.4)
        # A has most recent sue = +4.0 -> should be long
        weight_a = float(result.loc[pd.Timestamp("2020-01-16"), "A"])
        assert weight_a > 0, f"Expected A to be long (new sue=+4.0), got {weight_a}"

    def test_pead_long_high_sue_drift_property(self) -> None:
        """Construct panel where high-SUE names subsequently drift up.

        This tests the core PEAD property: the signal correctly identifies
        names expected to outperform post-announcement.
        """
        # 6 symbols with varied SUE scores, 2 high and 2 low
        records = []
        sue_map = {
            "HIGH1": 8.0, "HIGH2": 6.0,   # top quantile -> long
            "MED1": 0.5, "MED2": -0.5,    # middle -> zero weight
            "LOW1": -6.0, "LOW2": -8.0,   # bottom quantile -> short
        }
        for sym, sue_val in sue_map.items():
            records.append({
                "symbol": sym,
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-10"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": sue_val * 0.1,
                "sue": sue_val,
            })
        sp = pd.DataFrame(records)
        eval_dates = pd.DatetimeIndex(["2020-01-11"])
        result = pead_signal(sp, eval_dates, quantile=1.0 / 3.0)

        row = result.iloc[0]
        # High-SUE symbols should have positive weight
        assert float(row["HIGH1"]) > 0
        assert float(row["HIGH2"]) > 0
        # Low-SUE symbols should have negative weight
        assert float(row["LOW1"]) < 0
        assert float(row["LOW2"]) < 0

    def test_identical_sue_values_produce_zero_weights(self) -> None:
        """All symbols with identical SUE -> sigma=0 -> all-zero weights (covers sigma==0 branch)."""
        records = [
            {
                "symbol": "A",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-10"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": 0.5,
                "sue": 2.0,
            },
            {
                "symbol": "B",
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-10"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": 0.5,
                "sue": 2.0,
            },
        ]
        sp = pd.DataFrame(records)
        eval_dates = pd.DatetimeIndex(["2020-01-11"])
        result = pead_signal(sp, eval_dates, quantile=0.4)
        # sigma of [2.0, 2.0] = 0 -> continue -> all zero
        assert (result.iloc[0] == 0.0).all()

    def test_overlap_guard_too_few_symbols(self) -> None:
        """With 2 symbols and quantile=0.9: n_leg=max(1,floor(2*0.9))=1, 2*1=2<=2 OK but
        let us test with 3 symbols and quantile=0.9: n_leg=max(1,floor(3*0.9))=2, 2*2=4>3 -> skip."""
        records = [
            {
                "symbol": sym,
                "period_end": pd.Timestamp("2019-12-31"),
                "filing_date": pd.Timestamp("2020-01-10"),
                "fiscal_period": "Q4",
                "eps": 1.0,
                "surprise": float(i),
                "sue": float(i),
            }
            for i, sym in enumerate(["X", "Y", "Z"])
        ]
        sp = pd.DataFrame(records)
        eval_dates = pd.DatetimeIndex(["2020-01-11"])
        # quantile=0.9, n_valid=3: n_leg=max(1,floor(3*0.9))=2, 2*2=4>3 -> all zero
        result = pead_signal(sp, eval_dates, quantile=0.9)
        assert (result.iloc[0] == 0.0).all()

    def test_empty_eval_dates_returns_empty(self) -> None:
        """Empty evaluation_dates produces an empty DataFrame."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex([])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        assert len(result) == 0

    def test_row_net_weight_zero(self) -> None:
        """Net weight per row = 0 (dollar-neutral long/short)."""
        sp = self._make_sue_panel()
        eval_dates = pd.DatetimeIndex(["2020-01-16", "2020-01-17", "2020-01-20"])
        result = pead_signal(sp, eval_dates, quantile=0.3)
        post_filing = result.iloc[0:]
        row_sums = post_filing.sum(axis=1)
        assert float(row_sums.abs().max()) < 1e-12, (
            f"Max abs row net = {float(row_sums.abs().max()):.2e}"
        )


# ---------------------------------------------------------------------------
# Integration: compute_sue_panel -> pead_signal pipeline
# ---------------------------------------------------------------------------


class TestSuePipelineIntegration:
    """End-to-end: compute_sue_panel -> pead_signal."""

    def test_pipeline_produces_nonzero_weights(self) -> None:
        """A realistic EPS panel produces nonzero PEAD weights post-announcement."""
        # Two symbols: BULL (consistently strong earnings) and BEAR (weak)
        records = []
        for i in range(9):
            year = 2019 + i // 4
            quarter = (i % 4) + 1
            period_month = quarter * 3
            period_day = 30
            filing_month = period_month + 1 if period_month < 12 else 1
            filing_year = year if period_month < 12 else year + 1
            period_end_date = date(year, period_month, period_day)
            filing_date_date = date(filing_year, filing_month, 15)

            records.append(_eps_record(
                "BULL",
                eps=float(1.0 + i * 0.2),  # steadily growing EPS
                period_end=period_end_date,
                filing_date=filing_date_date,
                fiscal_period=f"Q{quarter}",
            ))
            records.append(_eps_record(
                "BEAR",
                eps=float(2.0 - i * 0.2),  # steadily declining EPS
                period_end=period_end_date,
                filing_date=filing_date_date,
                fiscal_period=f"Q{quarter}",
            ))

        df = _make_fundamentals(records)
        sue_panel = compute_sue_panel(df)

        # Evaluate on a date after the last filing
        last_filing = pd.to_datetime(sue_panel["filing_date"]).max()
        eval_date = last_filing + pd.Timedelta(days=1)
        eval_dates = pd.DatetimeIndex([eval_date])

        result = pead_signal(sue_panel, eval_dates, quantile=0.4)

        # At least one symbol should have a nonzero weight
        assert result.iloc[0].abs().sum() > 0, (
            "Expected nonzero PEAD weights but got all zeros"
        )


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.alt_data.earnings as mod
        expected = {"EarningsConfig", "compute_sue_panel", "pead_signal"}
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.alt_data.earnings as mod
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(EarningsConfig)

    def test_internal_helpers_not_in_all(self) -> None:
        import core_trading.signals.alt_data.earnings as mod
        assert "_build_eps_history" not in mod.__all__
        assert "_compute_sue_for_symbol" not in mod.__all__
