"""Tests for core_trading.signals.alt_data.macro (Phase 5.F.5).

Covers:
* MacroConfig -- frozen/slotted DTO, __post_init__ validation.
* align_series -- outer join, ffill, ascending sort, error on single series.
* yield_curve_signal -- slope arithmetic, inversion flag fires at correct date
  and not before, curvature with y_mid, no-mid branch (curvature all-NaN).
* vix_term_structure -- contango (ratio < 1) -> +1 regime, backwardation -> -1,
  extreme ratio sanity clamping to NaN.
* credit_spread_signal -- level passthrough, change arithmetic, warmup NaN,
  widening -> positive change.
* currency_carry_signal -- differential sign, direction +1/-1/0 correctness.
* _zscore_series -- internal helper: warmup NaN, zero-sigma -> NaN.
* Public API / __all__ check.

All tests use synthetic data -- no external dependencies.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.alt_data.macro import (
    MacroConfig,
    _zscore_series,
    align_series,
    credit_spread_signal,
    currency_carry_signal,
    vix_term_structure,
    yield_curve_signal,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SEED = 20260601


def _dates(n: int, start: str = "2020-01-01", freq: str = "B") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq)


def _series(values: list[float] | np.ndarray, name: str = "s",
            dates: pd.DatetimeIndex | None = None) -> pd.Series:
    if dates is None:
        dates = _dates(len(values))
    return pd.Series(np.asarray(values, dtype=float), index=dates, name=name)


# ---------------------------------------------------------------------------
# MacroConfig tests
# ---------------------------------------------------------------------------


class TestMacroConfig:
    """MacroConfig: construction, defaults, validation, immutability."""

    def test_default_construction(self) -> None:
        cfg = MacroConfig()
        assert cfg.inversion_threshold == 0.0
        assert cfg.credit_spread_window == 21
        assert math.isclose(cfg.butterfly_short_tenor, 0.5)
        assert math.isclose(cfg.butterfly_long_tenor, 0.5)
        assert math.isclose(cfg.vix_min_ratio, 0.2)

    def test_custom_construction(self) -> None:
        cfg = MacroConfig(
            inversion_threshold=-0.10,
            credit_spread_window=5,
            butterfly_short_tenor=0.3,
            butterfly_long_tenor=0.7,
            vix_min_ratio=0.1,
        )
        assert cfg.inversion_threshold == -0.10
        assert cfg.credit_spread_window == 5

    def test_frozen(self) -> None:
        cfg = MacroConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.credit_spread_window = 10  # type: ignore[misc]

    def test_inversion_threshold_positive_raises(self) -> None:
        with pytest.raises(ValueError, match="inversion_threshold"):
            MacroConfig(inversion_threshold=0.01)

    def test_credit_spread_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="credit_spread_window"):
            MacroConfig(credit_spread_window=1)

    def test_credit_spread_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="credit_spread_window"):
            MacroConfig(credit_spread_window=0)

    def test_butterfly_weights_not_sum_to_one_raises(self) -> None:
        with pytest.raises(ValueError, match="butterfly"):
            MacroConfig(butterfly_short_tenor=0.4, butterfly_long_tenor=0.7)

    def test_butterfly_zero_weight_raises(self) -> None:
        with pytest.raises(ValueError, match="butterfly"):
            MacroConfig(butterfly_short_tenor=0.0, butterfly_long_tenor=1.0)

    def test_vix_min_ratio_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="vix_min_ratio"):
            MacroConfig(vix_min_ratio=0.0)

    def test_vix_min_ratio_one_raises(self) -> None:
        with pytest.raises(ValueError, match="vix_min_ratio"):
            MacroConfig(vix_min_ratio=1.0)

    def test_inversion_threshold_zero_allowed(self) -> None:
        cfg = MacroConfig(inversion_threshold=0.0)
        assert cfg.inversion_threshold == 0.0

    def test_inversion_threshold_negative_allowed(self) -> None:
        cfg = MacroConfig(inversion_threshold=-0.5)
        assert cfg.inversion_threshold == -0.5

    def test_credit_spread_window_two_allowed(self) -> None:
        cfg = MacroConfig(credit_spread_window=2)
        assert cfg.credit_spread_window == 2


# ---------------------------------------------------------------------------
# align_series tests
# ---------------------------------------------------------------------------


class TestAlignSeries:
    """align_series: outer join, ffill, error handling."""

    def test_basic_alignment_shape(self) -> None:
        s1 = _series([1.0, 2.0, 3.0], "a", _dates(3, "2020-01-01"))
        s2 = _series([4.0, 5.0, 6.0], "b", _dates(3, "2020-01-02"))
        df = align_series(s1, s2)
        # Union of [Jan 1, Jan 2, Jan 5] and [Jan 2, Jan 5, Jan 6] -- but
        # let us just check the shape is correct: 2 columns, index is union
        assert "a" in df.columns
        assert "b" in df.columns
        assert df.index.is_monotonic_increasing

    def test_ffill_propagates(self) -> None:
        dates_a = pd.DatetimeIndex(["2020-01-01", "2020-01-03"])
        dates_b = pd.DatetimeIndex(["2020-01-02", "2020-01-04"])
        s1 = pd.Series([10.0, 30.0], index=dates_a, name="x")
        s2 = pd.Series([20.0, 40.0], index=dates_b, name="y")
        df = align_series(s1, s2, fill_method="ffill")
        # After outer join and ffill: on 2020-01-03, x=30 (present), y should be 20 (ffilled)
        ts = pd.Timestamp("2020-01-03")
        assert df.loc[ts, "x"] == 30.0
        assert df.loc[ts, "y"] == 20.0

    def test_no_ffill(self) -> None:
        dates_a = pd.DatetimeIndex(["2020-01-01", "2020-01-03"])
        dates_b = pd.DatetimeIndex(["2020-01-02", "2020-01-04"])
        s1 = pd.Series([10.0, 30.0], index=dates_a, name="x")
        s2 = pd.Series([20.0, 40.0], index=dates_b, name="y")
        df = align_series(s1, s2, fill_method="none")
        # x on Jan 2 should be NaN (not present in s1)
        assert math.isnan(df.loc[pd.Timestamp("2020-01-02"), "x"])

    def test_single_series_raises(self) -> None:
        s1 = _series([1.0, 2.0], "a")
        with pytest.raises(ValueError, match="at least two"):
            align_series(s1)

    def test_non_datetime_index_raises(self) -> None:
        s1 = pd.Series([1.0, 2.0], index=[0, 1], name="a")
        s2 = _series([3.0, 4.0], "b")
        with pytest.raises(ValueError, match="DatetimeIndex"):
            align_series(s1, s2)

    def test_three_series(self) -> None:
        s1 = _series([1.0, 2.0], "a")
        s2 = _series([3.0, 4.0], "b")
        s3 = _series([5.0, 6.0], "c")
        df = align_series(s1, s2, s3)
        assert df.shape[1] == 3


# ---------------------------------------------------------------------------
# yield_curve_signal tests
# ---------------------------------------------------------------------------


class TestYieldCurveSignal:
    """yield_curve_signal: slope, inversion flag, curvature."""

    def _make_yield_curve(
        self,
        n: int = 100,
        inversion_start: int = 50,
    ) -> tuple[pd.Series, pd.Series]:
        """Build a yield curve that inverts from ``inversion_start`` onward.

        Before inversion: y_short = 2.0, y_long = 3.5 (positive slope).
        After inversion:  y_short = 4.5, y_long = 3.0 (negative slope).
        """
        dates = _dates(n)
        y_short_vals = np.full(n, 2.0)
        y_long_vals = np.full(n, 3.5)
        # Invert at known date index
        y_short_vals[inversion_start:] = 4.5
        y_long_vals[inversion_start:] = 3.0
        y_short = pd.Series(y_short_vals, index=dates, name="y2y")
        y_long = pd.Series(y_long_vals, index=dates, name="y10y")
        return y_short, y_long

    def test_slope_arithmetic(self) -> None:
        """slope = y_long - y_short."""
        y_short = _series([2.0, 2.5, 4.0])
        y_long = _series([3.5, 3.0, 3.0])
        result = yield_curve_signal(y_short, y_long)
        expected_slopes = [3.5 - 2.0, 3.0 - 2.5, 3.0 - 4.0]
        np.testing.assert_allclose(result["slope"].values, expected_slopes, atol=1e-12)

    def test_inversion_flag_fires_at_correct_date(self) -> None:
        """Inverted flag is True only from the inversion start, not before."""
        n = 100
        inv_start = 50
        y_short, y_long = self._make_yield_curve(n, inversion_start=inv_start)
        result = yield_curve_signal(y_short, y_long)

        # Before inversion: slope > 0 -> inverted = False
        pre_inversion = result["inverted"].iloc[:inv_start]
        assert not pre_inversion.any(), (
            f"Inversion flag fired before inversion: "
            f"{pre_inversion[pre_inversion].index.tolist()}"
        )

        # At and after inversion: slope < 0 -> inverted = True
        post_inversion = result["inverted"].iloc[inv_start:]
        assert post_inversion.all(), (
            f"Inversion flag missed post-inversion rows: "
            f"{post_inversion[~post_inversion].index.tolist()}"
        )

    def test_inversion_negative_threshold(self) -> None:
        """With inversion_threshold = -0.5, only deeply negative slopes invert."""
        y_short = _series([2.0, 2.1, 3.0])   # slopes: +1.5, +0.9, -0.5
        y_long = _series([3.5, 3.0, 2.5])
        cfg = MacroConfig(inversion_threshold=-0.5)
        result = yield_curve_signal(y_short, y_long, cfg)
        # slope at row 0: +1.5 -> not inverted
        assert not bool(result["inverted"].iloc[0])
        # slope at row 1: +0.9 -> not inverted (above threshold -0.5)
        assert not bool(result["inverted"].iloc[1])
        # slope at row 2: -0.5 -> inverted (<= -0.5)
        assert bool(result["inverted"].iloc[2])

    def test_curvature_with_mid(self) -> None:
        """Butterfly curvature = 0.5*y_short + 0.5*y_long - y_mid."""
        y_short = _series([2.0])
        y_long = _series([4.0])
        y_mid = _series([3.5])
        result = yield_curve_signal(y_short, y_long, y_mid=y_mid)
        # curvature = 0.5*2 + 0.5*4 - 3.5 = 1.0 + 2.0 - 3.5 = -0.5
        assert math.isclose(float(result["curvature"].iloc[0]), -0.5, abs_tol=1e-12)

    def test_curvature_without_mid_all_nan(self) -> None:
        """When y_mid is not provided, the curvature column is all NaN."""
        y_short = _series([2.0, 2.5])
        y_long = _series([3.5, 3.0])
        result = yield_curve_signal(y_short, y_long)
        assert result["curvature"].isna().all()

    def test_output_columns(self) -> None:
        """Output has exactly slope, curvature, inverted columns."""
        y_short = _series([2.0, 3.0])
        y_long = _series([3.5, 2.5])
        result = yield_curve_signal(y_short, y_long)
        assert set(result.columns) == {"slope", "curvature", "inverted"}

    def test_default_config(self) -> None:
        """Passing config=None uses MacroConfig() defaults."""
        y_short = _series([2.0])
        y_long = _series([1.5])   # slope = -0.5 -> inverted with threshold=0
        result = yield_curve_signal(y_short, y_long, None)
        assert bool(result["inverted"].iloc[0])

    def test_look_ahead_free_prefix_invariance(self) -> None:
        """slope on the full series and a prefix agree on overlapping rows."""
        n = 50
        y_short, y_long = self._make_yield_curve(n, inversion_start=25)
        cutoff = 30
        full = yield_curve_signal(y_short, y_long)
        prefix = yield_curve_signal(y_short.iloc[:cutoff], y_long.iloc[:cutoff])
        overlap = full.index[:cutoff]
        np.testing.assert_allclose(
            full.loc[overlap, "slope"].values,
            prefix["slope"].values,
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# vix_term_structure tests
# ---------------------------------------------------------------------------


class TestVixTermStructure:
    """vix_term_structure: contango/backwardation ratio and regime."""

    def test_contango_ratio_less_than_one(self) -> None:
        """front < back -> ratio < 1 -> regime = +1 (risk-on)."""
        vix_front = _series([15.0, 16.0])
        vix_back = _series([20.0, 22.0])
        result = vix_term_structure(vix_front, vix_back)
        assert (result["regime"] == 1.0).all()

    def test_backwardation_ratio_gt_one(self) -> None:
        """front > back -> ratio > 1 -> regime = -1 (risk-off)."""
        vix_front = _series([25.0, 30.0])
        vix_back = _series([18.0, 20.0])
        result = vix_term_structure(vix_front, vix_back)
        assert (result["regime"] == -1.0).all()

    def test_ratio_arithmetic(self) -> None:
        """ratio = vix_front / vix_back."""
        vix_front = _series([12.0])
        vix_back = _series([16.0])
        result = vix_term_structure(vix_front, vix_back)
        expected_ratio = 12.0 / 16.0
        assert math.isclose(float(result["ratio"].iloc[0]), expected_ratio, rel_tol=1e-10)

    def test_extreme_ratio_clamped_to_nan(self) -> None:
        """A very low front/back ratio is outside vix_min_ratio bounds -> NaN."""
        cfg = MacroConfig(vix_min_ratio=0.5)  # ratio must be in (0.5, 2.0)
        vix_front = _series([1.0])   # ratio = 0.1 < 0.5 -> clamped to NaN
        vix_back = _series([10.0])
        result = vix_term_structure(vix_front, vix_back, cfg)
        assert math.isnan(float(result["ratio"].iloc[0]))
        assert math.isnan(float(result["regime"].iloc[0]))

    def test_extreme_high_ratio_clamped(self) -> None:
        """A very high ratio (> 1/vix_min_ratio) is clamped to NaN."""
        cfg = MacroConfig(vix_min_ratio=0.5)  # upper bound is 2.0
        vix_front = _series([50.0])
        vix_back = _series([10.0])   # ratio = 5.0 > 2.0 -> NaN
        result = vix_term_structure(vix_front, vix_back, cfg)
        assert math.isnan(float(result["ratio"].iloc[0]))

    def test_output_columns(self) -> None:
        vix_front = _series([15.0])
        vix_back = _series([18.0])
        result = vix_term_structure(vix_front, vix_back)
        assert set(result.columns) == {"ratio", "regime"}

    def test_default_config(self) -> None:
        vix_front = _series([20.0])
        vix_back = _series([15.0])
        result = vix_term_structure(vix_front, vix_back, None)
        assert result["regime"].iloc[0] == -1.0

    def test_ratio_exactly_one_is_backwardation(self) -> None:
        """ratio == 1.0 -> regime = -1 (the boundary belongs to backwardation)."""
        vix_front = _series([15.0])
        vix_back = _series([15.0])
        result = vix_term_structure(vix_front, vix_back)
        assert result["regime"].iloc[0] == -1.0

    def test_non_datetime_raises(self) -> None:
        """Non-DatetimeIndex series raises ValueError via align_series."""
        bad = pd.Series([15.0], index=[0], name="vf")
        vix_back = _series([18.0])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            vix_term_structure(bad, vix_back)


# ---------------------------------------------------------------------------
# credit_spread_signal tests
# ---------------------------------------------------------------------------


class TestCreditSpreadSignal:
    """credit_spread_signal: level passthrough, rolling change, warmup NaN."""

    def test_level_passthrough(self) -> None:
        """level column equals the input spread exactly."""
        vals = [1.0, 1.5, 2.0, 1.8, 1.2]
        spread = _series(vals)
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=2))
        np.testing.assert_allclose(result["level"].values, vals, atol=1e-15)

    def test_warmup_nan(self) -> None:
        """First credit_spread_window rows of change are NaN."""
        window = 5
        n = 20
        spread = _series(list(range(n, 0, -1)))
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=window))
        assert result["change"].iloc[:window].isna().all()

    def test_change_arithmetic(self) -> None:
        """change[t] = spread[t] - spread[t-window]."""
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        spread = _series(vals)
        window = 2
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=window))
        # row 2: 3.0 - 1.0 = 2.0
        assert math.isclose(float(result["change"].iloc[2]), 2.0, abs_tol=1e-12)
        # row 3: 4.0 - 2.0 = 2.0
        assert math.isclose(float(result["change"].iloc[3]), 2.0, abs_tol=1e-12)

    def test_widening_spread_positive_change(self) -> None:
        """A monotonically widening spread produces positive changes."""
        vals = np.linspace(1.0, 5.0, 30)
        spread = _series(vals)
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=5))
        post_warmup = result["change"].iloc[5:]
        assert (post_warmup > 0).all(), "Expected all positive changes for widening spread"

    def test_narrowing_spread_negative_change(self) -> None:
        """A monotonically narrowing spread produces negative changes."""
        vals = np.linspace(5.0, 1.0, 30)
        spread = _series(vals)
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=5))
        post_warmup = result["change"].iloc[5:]
        assert (post_warmup < 0).all(), "Expected all negative changes for narrowing spread"

    def test_output_columns(self) -> None:
        spread = _series([1.0, 2.0, 3.0])
        result = credit_spread_signal(spread)
        assert set(result.columns) == {"level", "change"}

    def test_non_datetime_index_raises(self) -> None:
        bad = pd.Series([1.0, 2.0], index=[0, 1])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            credit_spread_signal(bad)

    def test_default_config(self) -> None:
        """Default config uses credit_spread_window=21."""
        n = 30
        spread = _series(list(range(n)))
        result = credit_spread_signal(spread, None)
        assert result["change"].iloc[:21].isna().all()
        assert math.isfinite(float(result["change"].iloc[21]))

    def test_index_preserved(self) -> None:
        """The output index matches the input spread index exactly."""
        dates = _dates(10)
        spread = pd.Series(np.random.default_rng(SEED).uniform(1, 5, 10), index=dates)
        result = credit_spread_signal(spread, MacroConfig(credit_spread_window=3))
        pd.testing.assert_index_equal(result.index, dates)


# ---------------------------------------------------------------------------
# currency_carry_signal tests
# ---------------------------------------------------------------------------


class TestCurrencyCarrySignal:
    """currency_carry_signal: differential, direction sign, alignment."""

    def test_carry_arithmetic(self) -> None:
        """carry = rate_domestic - rate_foreign."""
        dom = _series([5.0, 3.0, 1.0])
        fgn = _series([2.0, 3.0, 4.0])
        result = currency_carry_signal(dom, fgn)
        expected = [3.0, 0.0, -3.0]
        np.testing.assert_allclose(result["carry"].values, expected, atol=1e-12)

    def test_direction_positive(self) -> None:
        """Positive carry -> direction = +1."""
        dom = _series([5.0])
        fgn = _series([2.0])
        result = currency_carry_signal(dom, fgn)
        assert float(result["direction"].iloc[0]) == 1.0

    def test_direction_negative(self) -> None:
        """Negative carry -> direction = -1."""
        dom = _series([1.0])
        fgn = _series([4.0])
        result = currency_carry_signal(dom, fgn)
        assert float(result["direction"].iloc[0]) == -1.0

    def test_direction_zero(self) -> None:
        """Zero carry -> direction = 0.0."""
        dom = _series([3.0])
        fgn = _series([3.0])
        result = currency_carry_signal(dom, fgn)
        assert float(result["direction"].iloc[0]) == 0.0

    def test_output_columns(self) -> None:
        dom = _series([5.0, 3.0])
        fgn = _series([2.0, 4.0])
        result = currency_carry_signal(dom, fgn)
        assert set(result.columns) == {"carry", "direction"}

    def test_index_is_union_ascending(self) -> None:
        dates_dom = pd.DatetimeIndex(["2020-01-01", "2020-01-03"])
        dates_fgn = pd.DatetimeIndex(["2020-01-02", "2020-01-04"])
        dom = pd.Series([5.0, 4.0], index=dates_dom, name="dom")
        fgn = pd.Series([3.0, 2.0], index=dates_fgn, name="fgn")
        result = currency_carry_signal(dom, fgn)
        assert result.index.is_monotonic_increasing
        # Union of both: 4 dates total
        assert len(result) == 4

    def test_non_datetime_raises(self) -> None:
        bad = pd.Series([5.0], index=[0], name="dom")
        fgn = _series([3.0])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            currency_carry_signal(bad, fgn)

    def test_carry_look_ahead_free_prefix_invariance(self) -> None:
        """carry values are identical for the full series and a prefix."""
        n = 40
        dom = _series(np.linspace(3.0, 7.0, n))
        fgn = _series(np.linspace(1.0, 5.0, n))
        cutoff = 25
        full = currency_carry_signal(dom, fgn)
        prefix = currency_carry_signal(dom.iloc[:cutoff], fgn.iloc[:cutoff])
        overlap = full.index[:cutoff]
        np.testing.assert_allclose(
            full.loc[overlap, "carry"].values,
            prefix["carry"].values,
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# _zscore_series tests (internal helper)
# ---------------------------------------------------------------------------


class TestZscoreSeries:
    """_zscore_series: warmup NaN, zero-sigma -> NaN, arithmetic."""

    def test_warmup_nan(self) -> None:
        n = 20
        s = _series(list(range(n)))
        window = 5
        z = _zscore_series(s, window)
        assert z.iloc[: window - 1].isna().all()

    def test_finite_after_warmup(self) -> None:
        s = _series([float(i) for i in range(20)])
        z = _zscore_series(s, 5)
        assert math.isfinite(float(z.iloc[4]))

    def test_constant_series_nan(self) -> None:
        """A constant series has std=0 -> z-score is NaN."""
        s = _series([3.0] * 10)
        z = _zscore_series(s, 4)
        assert z.iloc[3:].isna().all()

    def test_bad_window_raises(self) -> None:
        s = _series([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="window"):
            _zscore_series(s, 1)

    def test_last_element_in_window(self) -> None:
        """The current bar t is included in the rolling window."""
        s = _series([0.0, 0.0, 0.0, 10.0])  # window=4 at t=3: mean=2.5, std=4.33
        z = _zscore_series(s, 4)
        z_val = float(z.iloc[3])
        assert math.isfinite(z_val)
        # z = (10 - 2.5) / std_population([0,0,0,10])
        arr = np.array([0.0, 0.0, 0.0, 10.0])
        expected_z = (10.0 - float(np.mean(arr))) / float(np.std(arr, ddof=0))
        assert math.isclose(z_val, expected_z, rel_tol=1e-10)

    def test_nan_in_window_fewer_than_2_valid(self) -> None:
        """Window with fewer than 2 finite values produces NaN (covers continue branch)."""
        # series: [NaN, NaN, NaN, 1.0, NaN] with window=4
        # At t=3: window = [NaN, NaN, NaN, 1.0] -> only 1 finite value -> NaN
        vals = [float("nan"), float("nan"), float("nan"), 1.0, float("nan")]
        s = _series(vals)
        z = _zscore_series(s, 4)
        # At index 3: only 1 valid value -> continue -> NaN
        assert math.isnan(float(z.iloc[3]))


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.alt_data.macro as mod
        expected = {
            "MacroConfig",
            "align_series",
            "yield_curve_signal",
            "vix_term_structure",
            "credit_spread_signal",
            "currency_carry_signal",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.alt_data.macro as mod
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(MacroConfig)

    def test_internal_zscore_not_in_all(self) -> None:
        import core_trading.signals.alt_data.macro as mod
        assert "_zscore_series" not in mod.__all__
