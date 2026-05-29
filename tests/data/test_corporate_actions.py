"""Unit tests for core_trading.data.corporate_actions."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core_trading.data.corporate_actions import (
    CorporateAction,
    CorporateActionType,
    adjustment_factors,
    apply_adjustments,
    total_return_index,
)


def _closes(values: list[float], start: str = "2026-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx)


class TestCorporateAction:
    def test_split_construction(self) -> None:
        a = CorporateAction(
            symbol="AAPL",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 6, 1),
            ratio=2.0,
        )
        assert a.ratio == 2.0

    def test_negative_split_ratio_rejected(self) -> None:
        with pytest.raises(ValueError, match="split ratio"):
            CorporateAction(
                symbol="X",
                action_type=CorporateActionType.SPLIT,
                ex_date=date(2026, 6, 1),
                ratio=-1.0,
            )

    def test_negative_dividend_rejected(self) -> None:
        with pytest.raises(ValueError, match="cash_amount"):
            CorporateAction(
                symbol="X",
                action_type=CorporateActionType.DIVIDEND,
                ex_date=date(2026, 6, 1),
                cash_amount=-0.5,
            )


class TestAdjustmentFactors:
    def test_no_actions_all_ones(self) -> None:
        closes = _closes([100, 101, 102])
        factors = adjustment_factors(closes, [])
        assert (factors == 1.0).all()

    def test_empty_closes(self) -> None:
        closes = _closes([])
        factors = adjustment_factors(closes, [])
        assert len(factors) == 0

    def test_two_for_one_split_halves_prior_prices(self) -> None:
        # 5 days; split ex-date on day 3 (index 2). Prior bars get factor 0.5.
        closes = _closes([100, 100, 50, 50, 50])
        split = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 1, 3),
            ratio=2.0,
        )
        factors = adjustment_factors(closes, [split])
        assert factors.iloc[0] == pytest.approx(0.5)
        assert factors.iloc[1] == pytest.approx(0.5)
        assert factors.iloc[2] == pytest.approx(1.0)
        assert factors.iloc[-1] == pytest.approx(1.0)

    def test_split_makes_adjusted_series_continuous(self) -> None:
        closes = _closes([100, 100, 50, 50, 50])
        split = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 1, 3),
            ratio=2.0,
        )
        adjusted = closes * adjustment_factors(closes, [split])
        # After adjustment the pre-split 100s become 50s -> continuous at 50.
        assert adjusted.iloc[0] == pytest.approx(50.0)
        assert adjusted.iloc[2] == pytest.approx(50.0)

    def test_dividend_proportional_factor(self) -> None:
        closes = _closes([100, 100, 100, 100])
        div = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2026, 1, 3),
            cash_amount=2.0,
        )
        factors = adjustment_factors(closes, [div])
        # close before ex is 100; factor = 1 - 2/100 = 0.98 for bars before ex.
        assert factors.iloc[0] == pytest.approx(0.98)
        assert factors.iloc[1] == pytest.approx(0.98)
        assert factors.iloc[2] == pytest.approx(1.0)

    def test_action_before_all_bars_ignored(self) -> None:
        closes = _closes([100, 101, 102], start="2026-02-01")
        split = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 1, 1),
            ratio=2.0,
        )
        factors = adjustment_factors(closes, [split])
        assert (factors == 1.0).all()

    def test_multiple_actions_compound(self) -> None:
        closes = _closes([100, 100, 100, 100, 100])
        split = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 1, 3),
            ratio=2.0,
        )
        div = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2026, 1, 5),
            cash_amount=1.0,
        )
        factors = adjustment_factors(closes, [split, div])
        # Day 0: before both. split 0.5 * div (1 - 1/100=0.99) = 0.495
        assert factors.iloc[0] == pytest.approx(0.5 * 0.99)

    def test_non_datetime_index_rejected(self) -> None:
        bad = pd.Series([1.0, 2.0], index=["a", "b"])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            adjustment_factors(bad, [])

    def test_descending_index_rejected(self) -> None:
        idx = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")[::-1]
        bad = pd.Series([1.0, 2.0, 3.0], index=idx)
        with pytest.raises(ValueError, match="ascending"):
            adjustment_factors(bad, [])

    def test_dividend_exceeding_price_skipped(self) -> None:
        closes = _closes([1.0, 1.0, 1.0])
        div = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2026, 1, 3),
            cash_amount=5.0,
        )
        factors = adjustment_factors(closes, [div])
        # factor would be negative -> skipped, stays 1.0
        assert (factors == 1.0).all()

    def test_zero_close_before_dividend_skipped(self) -> None:
        closes = _closes([0.0, 0.0, 10.0])
        div = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2026, 1, 3),
            cash_amount=1.0,
        )
        factors = adjustment_factors(closes, [div])
        assert (factors == 1.0).all()


class TestApplyAdjustments:
    def test_empty_frame(self) -> None:
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        out = apply_adjustments(df, [])
        assert out.empty

    def test_missing_close_rejected(self) -> None:
        df = pd.DataFrame({"open": [1.0]}, index=pd.date_range("2026-01-01", periods=1, tz="UTC"))
        with pytest.raises(ValueError, match="'close' column"):
            apply_adjustments(df, [])

    def test_adjusts_ohlc(self) -> None:
        idx = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [100.0, 100.0, 50.0, 50.0],
                "high": [101.0, 101.0, 51.0, 51.0],
                "low": [99.0, 99.0, 49.0, 49.0],
                "close": [100.0, 100.0, 50.0, 50.0],
            },
            index=idx,
        )
        split = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2026, 1, 3),
            ratio=2.0,
        )
        out = apply_adjustments(df, [split])
        assert "adjusted_close" in out.columns
        assert "adj_open" in out.columns
        assert out["adjusted_close"].iloc[0] == pytest.approx(50.0)
        assert out["adj_open"].iloc[0] == pytest.approx(50.0)


class TestTotalReturnIndex:
    def test_base_100(self) -> None:
        closes = _closes([100, 110, 121])
        tri = total_return_index(closes, [])
        assert tri.iloc[0] == pytest.approx(100.0)
        assert tri.iloc[1] == pytest.approx(110.0)
        assert tri.iloc[2] == pytest.approx(121.0)

    def test_empty(self) -> None:
        closes = _closes([])
        tri = total_return_index(closes, [])
        assert len(tri) == 0

    def test_zero_base_rejected(self) -> None:
        closes = _closes([0.0, 10.0])
        with pytest.raises(ValueError, match="zero/NaN"):
            total_return_index(closes, [])
