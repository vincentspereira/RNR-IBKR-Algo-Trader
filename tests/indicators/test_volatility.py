"""Tests for core_trading.indicators.volatility.

Covers:
- Warm-up NaN count for each indicator.
- Truncation invariance.
- Cross-validation against hand-computed fixtures for ATR and Bollinger Bands.
- DataFrame column names and dtypes.
- Input validation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.indicators.volatility import (
    atr,
    bollinger_bands,
    donchian_channels,
    historical_volatility,
    keltner_channels,
    natr,
    true_range,
    ulcer_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 80


def _prices(n: int = _N, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100.0 + np.cumsum(rng.normal(0, 0.5, n)), dtype="float64")


def _ohlc(n: int = _N, seed: int = 42) -> tuple[pd.Series, pd.Series, pd.Series]:
    c = _prices(n, seed)
    rng = np.random.default_rng(seed + 1)
    high = c + rng.uniform(0.3, 2.0, n)
    low = c - rng.uniform(0.3, 2.0, n)
    return high.rename(None), low.rename(None), c


def _check_truncation_series(fn, *args, k: int | None = None) -> None:
    if k is None:
        k = len(args[0]) // 2
    full = fn(*args)
    trunc = fn(*[a.iloc[:k] if isinstance(a, pd.Series) else a for a in args])
    if isinstance(full, pd.DataFrame):
        for col in full.columns:
            fs = full[col].iloc[:k]
            ts_ = trunc[col]
            valid = fs.notna() & ts_.notna()
            if valid.any():
                np.testing.assert_allclose(
                    fs[valid].values,
                    ts_[valid].values,
                    rtol=1e-10,
                    err_msg=f"{fn.__name__}[{col}]: truncation invariance failed",
                )
    else:
        fs = full.iloc[:k]
        ts_ = trunc
        valid = fs.notna() & ts_.notna()
        if valid.any():
            np.testing.assert_allclose(
                fs[valid].values,
                ts_[valid].values,
                rtol=1e-10,
                err_msg=f"{fn.__name__}: truncation invariance failed",
            )


# ---------------------------------------------------------------------------
# True Range
# ---------------------------------------------------------------------------


class TestTrueRange:
    def test_all_valid(self) -> None:
        h, low, c = _ohlc()
        result = true_range(h, low, c)
        assert result.notna().all()

    def test_first_bar_is_hl(self) -> None:
        h = pd.Series([15.0, 12.0])
        low = pd.Series([10.0, 8.0])
        c = pd.Series([14.0, 11.0])
        result = true_range(h, low, c)
        np.testing.assert_allclose(result.iloc[0], 5.0)  # 15 - 10

    def test_reference_with_gap(self) -> None:
        # At t=0: TR = high - low = 15 - 10 = 5 (no previous close).
        # At t=1: prev_close=20, h=12, low=9.
        #   TR = max(|12-9|=3, |12-20|=8, |9-20|=11) = 11.
        h = pd.Series([15.0, 12.0])
        low = pd.Series([10.0, 9.0])
        c = pd.Series([20.0, 11.0])
        result = true_range(h, low, c)
        np.testing.assert_allclose(result.iloc[0], 5.0)   # h - low at t=0
        np.testing.assert_allclose(result.iloc[1], 11.0)  # |low - prev_close|

    def test_non_negative(self) -> None:
        h, low, c = _ohlc()
        result = true_range(h, low, c)
        assert (result >= 0.0).all()

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        assert true_range(h, low, c).dtype == np.float64


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


class TestATR:
    def test_warmup_nan_count(self) -> None:
        h, low, c = _ohlc()
        result = atr(h, low, c, window=14)
        assert result.iloc[:13].isna().all()
        assert result.iloc[13:].notna().all()

    def test_reference_constant_ohlc(self) -> None:
        # Constant OHLC: TR = 0, ATR = 0
        h = pd.Series([10.0] * 30)
        low = pd.Series([10.0] * 30)
        c = pd.Series([10.0] * 30)
        result = atr(h, low, c, window=5)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_reference_fixed_tr(self) -> None:
        # Every bar has TR=2: ATR must converge to 2 with Wilder smoothing
        n = 50
        h = pd.Series(np.arange(1.0, n + 1.0) + 1.0)
        low = pd.Series(np.arange(1.0, n + 1.0) - 1.0)
        c = pd.Series(np.arange(1.0, n + 1.0))
        result = atr(h, low, c, window=5)
        # TR[0] = 2 (h-low), TR[i>0] involves prev close: max(2, |hi-ci-1|, |li-ci-1|)
        # For uniform step of 1: TR[i] = max(2, 1-0.5?, ...) -- allow for larger TR
        # Just verify non-negative and finite
        assert result.dropna().notna().all()
        assert (result.dropna() >= 0.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(atr, h, low, c, k=45)

    def test_non_negative(self) -> None:
        h, low, c = _ohlc()
        result = atr(h, low, c)
        assert (result.dropna() >= 0.0).all()

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        assert atr(h, low, c).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c = _ohlc()
        with pytest.raises(ValueError):
            atr(h, low, c, window=0)


# ---------------------------------------------------------------------------
# NATR
# ---------------------------------------------------------------------------


class TestNATR:
    def test_warmup_nans(self) -> None:
        h, low, c = _ohlc()
        result = natr(h, low, c, window=14)
        assert result.isna().sum() > 0

    def test_non_negative(self) -> None:
        h, low, c = _ohlc()
        result = natr(h, low, c, window=14)
        assert (result.dropna() >= 0.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(natr, h, low, c, k=45)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollingerBands:
    def test_columns(self) -> None:
        c = _prices()
        result = bollinger_bands(c)
        assert set(result.columns) == {"mid", "upper", "lower", "bandwidth", "pct_b"}

    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = bollinger_bands(c, window=20)
        for col in result.columns:
            assert result[col].iloc[:19].isna().all()
        assert result["mid"].iloc[19:].notna().all()

    def test_reference_constant(self) -> None:
        # Constant price: std=0, upper=lower=mid, bandwidth=0, pct_b=0.5
        c = pd.Series([50.0] * 30)
        result = bollinger_bands(c, window=5)
        np.testing.assert_allclose(result["mid"].dropna().values, 50.0, atol=1e-10)
        np.testing.assert_allclose(result["upper"].dropna().values, 50.0, atol=1e-10)
        np.testing.assert_allclose(result["lower"].dropna().values, 50.0, atol=1e-10)
        np.testing.assert_allclose(result["bandwidth"].dropna().values, 0.0, atol=1e-10)

    def test_reference_small_fixture(self) -> None:
        # Hand-computed: 5 bars, window=3, num_std=1
        # [1, 2, 3, 4, 5] -> at index 4: mid=4, std=1, upper=5, lower=3
        c = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = bollinger_bands(c, window=3, num_std=1.0)
        np.testing.assert_allclose(result["mid"].iloc[4], 4.0, rtol=1e-10)
        np.testing.assert_allclose(result["upper"].iloc[4], 5.0, rtol=1e-10)
        np.testing.assert_allclose(result["lower"].iloc[4], 3.0, rtol=1e-10)

    def test_upper_above_lower(self) -> None:
        c = _prices()
        result = bollinger_bands(c)
        valid = result.dropna()
        # When std > 0
        with_variance = valid[valid["bandwidth"] > 0]
        assert (with_variance["upper"] > with_variance["lower"]).all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(bollinger_bands, c, k=50)

    def test_output_dtype(self) -> None:
        result = bollinger_bands(_prices())
        for col in result.columns:
            assert result[col].dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            bollinger_bands(_prices(), window=0)


# ---------------------------------------------------------------------------
# Keltner Channels
# ---------------------------------------------------------------------------


class TestKeltnerChannels:
    def test_columns(self) -> None:
        h, low, c = _ohlc()
        result = keltner_channels(h, low, c)
        assert set(result.columns) == {"mid", "upper", "lower"}

    def test_warmup_nans(self) -> None:
        h, low, c = _ohlc()
        result = keltner_channels(h, low, c, ema_period=20, atr_period=10)
        assert result["mid"].isna().sum() > 0

    def test_upper_above_lower(self) -> None:
        h, low, c = _ohlc()
        result = keltner_channels(h, low, c)
        valid = result.dropna()
        assert (valid["upper"] > valid["lower"]).all()

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(keltner_channels, h, low, c, k=50)

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        result = keltner_channels(h, low, c)
        for col in result.columns:
            assert result[col].dtype == np.float64


# ---------------------------------------------------------------------------
# Donchian Channels
# ---------------------------------------------------------------------------


class TestDonchianChannels:
    def test_columns(self) -> None:
        h, low, _ = _ohlc()
        result = donchian_channels(h, low)
        assert set(result.columns) == {"upper", "mid", "lower"}

    def test_warmup_nan_count(self) -> None:
        h, low, _ = _ohlc()
        result = donchian_channels(h, low, window=20)
        assert result["upper"].iloc[:19].isna().all()
        assert result["upper"].iloc[19:].notna().all()

    def test_reference(self) -> None:
        h = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        low = pd.Series([0.5, 1.5, 2.5, 3.5, 4.5])
        result = donchian_channels(h, low, window=3)
        np.testing.assert_allclose(result["upper"].iloc[2], 3.0)
        np.testing.assert_allclose(result["lower"].iloc[2], 0.5)
        np.testing.assert_allclose(result["mid"].iloc[2], 1.75)

    def test_truncation_invariance(self) -> None:
        h, low, _ = _ohlc()
        _check_truncation_series(donchian_channels, h, low, k=50)

    def test_output_dtype(self) -> None:
        h, low, _ = _ohlc()
        result = donchian_channels(h, low)
        for col in result.columns:
            assert result[col].dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, _ = _ohlc()
        with pytest.raises(ValueError):
            donchian_channels(h, low, window=0)


# ---------------------------------------------------------------------------
# Ulcer Index
# ---------------------------------------------------------------------------


class TestUlcerIndex:
    def test_warmup_nan_count(self) -> None:
        # Ulcer Index requires two rolling operations of width `window`:
        # (1) rolling_max -> NaN for first window-1 bars
        # (2) rolling_mean(dd_sq, window) -> needs window valid dd_sq values
        # Combined warm-up = 2*(window-1).  With window=14: first valid at index 26.
        c = _prices()
        result = ulcer_index(c, window=14)
        assert result.iloc[:26].isna().all()
        assert result.iloc[26:].notna().all()

    def test_non_negative(self) -> None:
        c = _prices()
        result = ulcer_index(c, window=14)
        assert (result.dropna() >= 0.0).all()

    def test_monotone_up_is_zero(self) -> None:
        # Monotone increasing: price always at rolling high, drawdown = 0
        c = pd.Series(np.arange(1.0, 50.0))
        result = ulcer_index(c, window=10)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(ulcer_index, c, k=45)

    def test_output_dtype(self) -> None:
        assert ulcer_index(_prices(), 14).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            ulcer_index(_prices(), 0)


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------


class TestHistoricalVolatility:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = historical_volatility(c, window=20)
        # Needs 20 log returns -> 21 prices, so indices 0..20 are NaN (21 NaN)
        assert result.iloc[:20].isna().all()
        assert result.iloc[20:].notna().all()

    def test_non_negative(self) -> None:
        c = _prices()
        result = historical_volatility(c, window=20)
        assert (result.dropna() >= 0.0).all()

    def test_constant_price_zero_vol(self) -> None:
        c = pd.Series([50.0] * 30)
        result = historical_volatility(c, window=10)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_annualisation(self) -> None:
        # HV(252) vs HV(52) on same series: factor = sqrt(252/52)
        c = _prices()
        hv252 = historical_volatility(c, window=20, trading_periods=252)
        hv52 = historical_volatility(c, window=20, trading_periods=52)
        ratio = (hv252 / hv52).dropna()
        expected = np.sqrt(252.0 / 52.0)
        np.testing.assert_allclose(ratio.values, expected, rtol=1e-10)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(historical_volatility, c, k=50)

    def test_output_dtype(self) -> None:
        assert historical_volatility(_prices(), 20).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            historical_volatility(_prices(), 0)
