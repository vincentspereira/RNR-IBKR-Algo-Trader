"""Tests for core_trading.indicators.moving_averages.

Covers:
- Warm-up NaN count for each indicator.
- Truncation invariance (the definitive look-ahead check for this repo):
  f(x).iloc[:k] == f(x.iloc[:k]) on the overlapping non-NaN region.
- Cross-validation against hand-computed small fixtures for SMA, EMA, WMA.
- Input validation (ValueError on bad window / type).
- Specific properties (output dtype float64, same index as input).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.indicators.moving_averages import (
    dema,
    ema,
    hma,
    kama,
    mcginley_dynamic,
    sma,
    tema,
    vwma,
    wma,
    zlema,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_N = 60  # default series length for most tests


def _prices(n: int = _N, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100.0 + np.cumsum(rng.normal(0, 1, n)), dtype="float64")


def _volume(n: int = _N, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.integers(1_000, 1_000_000, n).astype(float))


def _check_truncation(fn, *args, window: int, k: int | None = None) -> None:
    """Assert truncation invariance.

    f(x).iloc[:k] == f(x.iloc[:k]) on the overlapping non-NaN region.
    """
    if k is None:
        k = len(args[0]) // 2

    full_result = fn(*args, window=window)
    trunc_args = tuple(a.iloc[:k] if isinstance(a, pd.Series) else a for a in args)
    trunc_result = fn(*trunc_args, window=window)

    full_slice = full_result.iloc[:k]
    valid = full_slice.notna() & trunc_result.notna()
    if valid.any():
        np.testing.assert_allclose(
            full_slice[valid].values,
            trunc_result[valid].values,
            rtol=1e-10,
            err_msg=f"{fn.__name__}: truncation invariance failed",
        )


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------


class TestSMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = sma(c, 10)
        assert result.iloc[:9].isna().all()
        assert result.iloc[9:].notna().all()

    def test_warmup_window_1(self) -> None:
        c = _prices()
        result = sma(c, 1)
        assert result.notna().all()

    def test_reference_values(self) -> None:
        # Hand-computed: SMA(3) of [1,2,3,4,5]
        c = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(c, 3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        np.testing.assert_allclose(result.iloc[2], 2.0)
        np.testing.assert_allclose(result.iloc[3], 3.0)
        np.testing.assert_allclose(result.iloc[4], 4.0)

    def test_reference_values_longer(self) -> None:
        # SMA(4) of [10, 20, 30, 40, 50, 60]
        c = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        result = sma(c, 4)
        np.testing.assert_allclose(result.iloc[3], 25.0)
        np.testing.assert_allclose(result.iloc[4], 35.0)
        np.testing.assert_allclose(result.iloc[5], 45.0)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(sma, c, window=10, k=30)

    def test_output_dtype(self) -> None:
        c = _prices()
        assert sma(c, 5).dtype == np.float64

    def test_output_index(self) -> None:
        c = _prices()
        assert sma(c, 5).index.equals(c.index)

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            sma(_prices(), 0)

    def test_invalid_type(self) -> None:
        with pytest.raises((ValueError, AttributeError)):
            sma([1.0, 2.0, 3.0], 2)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


class TestEMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = ema(c, 10)
        assert result.iloc[:9].isna().all()
        assert result.iloc[9:].notna().all()

    def test_seed_is_sma(self) -> None:
        c = _prices()
        result = ema(c, 5)
        # Value at index 4 (the seed) should equal SMA(5)
        expected_seed = float(c.iloc[:5].mean())
        np.testing.assert_allclose(result.iloc[4], expected_seed)

    def test_reference_values(self) -> None:
        # EMA(3) on [1, 2, 3, 4, 5]
        # alpha = 2/(3+1) = 0.5
        # seed = mean([1,2,3]) = 2.0
        # EMA[3] = 0.5*4 + 0.5*2.0 = 3.0
        # EMA[4] = 0.5*5 + 0.5*3.0 = 4.0
        c = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(c, 3)
        np.testing.assert_allclose(result.iloc[2], 2.0, rtol=1e-10)
        np.testing.assert_allclose(result.iloc[3], 3.0, rtol=1e-10)
        np.testing.assert_allclose(result.iloc[4], 4.0, rtol=1e-10)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(ema, c, window=10, k=35)

    def test_truncation_invariance_short(self) -> None:
        """SMA seed convention means invariance holds from the seed bar onwards."""
        c = _prices(n=50)
        window = 8
        _check_truncation(ema, c, window=window, k=25)

    def test_output_dtype(self) -> None:
        assert ema(_prices(), 5).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            ema(_prices(), 0)


# ---------------------------------------------------------------------------
# WMA
# ---------------------------------------------------------------------------


class TestWMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = wma(c, 10)
        assert result.iloc[:9].isna().all()
        assert result.iloc[9:].notna().all()

    def test_reference_values(self) -> None:
        # WMA(3) on [1, 2, 3, 4, 5]
        # weights = [1, 2, 3], weight_sum = 6
        # WMA[2] = (1*1 + 2*2 + 3*3)/6 = 14/6 = 7/3
        # WMA[3] = (1*2 + 2*3 + 3*4)/6 = 20/6 = 10/3
        c = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = wma(c, 3)
        np.testing.assert_allclose(result.iloc[2], 14.0 / 6.0, rtol=1e-10)
        np.testing.assert_allclose(result.iloc[3], 20.0 / 6.0, rtol=1e-10)
        np.testing.assert_allclose(result.iloc[4], 26.0 / 6.0, rtol=1e-10)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(wma, c, window=10, k=30)

    def test_output_dtype(self) -> None:
        assert wma(_prices(), 5).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            wma(_prices(), 0)


# ---------------------------------------------------------------------------
# DEMA
# ---------------------------------------------------------------------------


class TestDEMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = dema(c, 5)
        # 2*(5-1) = 8 NaN values
        assert result.iloc[:8].isna().all()
        assert result.notna().sum() > 0

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(dema, c, window=5, k=30)

    def test_output_dtype(self) -> None:
        assert dema(_prices(), 5).dtype == np.float64


# ---------------------------------------------------------------------------
# TEMA
# ---------------------------------------------------------------------------


class TestTEMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = tema(c, 5)
        # 3*(5-1) = 12 NaN values
        assert result.iloc[:12].isna().all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(tema, c, window=5, k=35)

    def test_output_dtype(self) -> None:
        assert tema(_prices(), 5).dtype == np.float64


# ---------------------------------------------------------------------------
# HMA
# ---------------------------------------------------------------------------


class TestHMA:
    def test_warmup_has_nans(self) -> None:
        c = _prices()
        result = hma(c, 16)
        # warm-up is approximately window + sqrt(window) - 2
        assert result.isna().sum() > 0
        assert result.notna().sum() > 0

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(hma, c, window=9, k=35)

    def test_output_dtype(self) -> None:
        assert hma(_prices(), 9).dtype == np.float64

    def test_period_2(self) -> None:
        """HMA with period=2 should produce values."""
        c = _prices(20)
        result = hma(c, 2)
        assert result.notna().sum() > 0


# ---------------------------------------------------------------------------
# KAMA
# ---------------------------------------------------------------------------


class TestKAMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = kama(c, window=10)
        # Seed at index 10, so indices 0..9 are NaN (10 NaN values)
        assert result.iloc[:10].isna().all()
        assert result.iloc[10:].notna().all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(kama, c, window=10, k=35)

    def test_stays_near_price_in_strong_trend(self) -> None:
        # In a strong monotone trend, ER ~= 1, SC ~= fastest, KAMA tracks price
        c = pd.Series(np.arange(1.0, 61.0))
        result = kama(c, window=10)
        # Last few values should be close to price
        assert abs(result.iloc[-1] - c.iloc[-1]) < 2.0

    def test_output_dtype(self) -> None:
        assert kama(_prices(), window=10).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            kama(_prices(), window=0)


# ---------------------------------------------------------------------------
# ZLEMA
# ---------------------------------------------------------------------------


class TestZLEMA:
    def test_warmup_has_nans(self) -> None:
        c = _prices()
        result = zlema(c, 10)
        assert result.isna().sum() > 0

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(zlema, c, window=10, k=30)

    def test_output_dtype(self) -> None:
        assert zlema(_prices(), 10).dtype == np.float64


# ---------------------------------------------------------------------------
# VWMA
# ---------------------------------------------------------------------------


class TestVWMA:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        v = _volume()
        result = vwma(c, v, 10)
        assert result.iloc[:9].isna().all()
        assert result.iloc[9:].notna().all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        v = _volume()
        _check_truncation(vwma, c, v, window=10, k=30)

    def test_reference_value(self) -> None:
        c = pd.Series([10.0, 20.0, 30.0])
        v = pd.Series([1.0, 2.0, 3.0])
        result = vwma(c, v, 3)
        # (10*1 + 20*2 + 30*3) / (1+2+3) = 140/6
        np.testing.assert_allclose(result.iloc[2], 140.0 / 6.0, rtol=1e-10)

    def test_output_dtype(self) -> None:
        assert vwma(_prices(), _volume(), 5).dtype == np.float64

    def test_mismatched_index_raises(self) -> None:
        c = _prices(30)
        v = _volume(25)  # different length -> different index
        with pytest.raises(ValueError):
            vwma(c, v, 5)


# ---------------------------------------------------------------------------
# McGinley Dynamic
# ---------------------------------------------------------------------------


class TestMcginleyDynamic:
    def test_no_nan_warm_up(self) -> None:
        c = _prices()
        result = mcginley_dynamic(c, 14)
        # Seeded at index 0; all values valid
        assert result.notna().all()

    def test_seed_is_first_price(self) -> None:
        c = _prices()
        result = mcginley_dynamic(c, 14)
        np.testing.assert_allclose(result.iloc[0], float(c.iloc[0]))

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation(mcginley_dynamic, c, window=14, k=30)

    def test_output_dtype(self) -> None:
        assert mcginley_dynamic(_prices(), 14).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            mcginley_dynamic(_prices(), 0)

    def test_tracks_price_direction(self) -> None:
        # Rising prices: MD should be below but trending up
        c = pd.Series(np.linspace(100.0, 200.0, 50))
        result = mcginley_dynamic(c, 10)
        assert result.iloc[-1] > result.iloc[0]
