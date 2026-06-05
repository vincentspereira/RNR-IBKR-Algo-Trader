"""Tests for core_trading.indicators.momentum.

Covers:
- Warm-up NaN count for each indicator.
- Truncation invariance.
- Cross-validation against hand-computed fixtures for RSI and MACD.
- Output DataFrame column names and dtypes.
- Input validation (ValueError on bad params).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.indicators.momentum import (
    cci,
    macd,
    roc,
    rsi,
    stochastic,
    stochrsi,
    tsi,
    ultimate_oscillator,
    williams_r,
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
    high = c + rng.uniform(0.1, 2.0, n)
    low = c - rng.uniform(0.1, 2.0, n)
    return high.rename(None), low.rename(None), c


def _volume(n: int = _N, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.integers(100_000, 5_000_000, n).astype(float))


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
# RSI
# ---------------------------------------------------------------------------


class TestRSI:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = rsi(c, 14)
        # Wilder RSI: NaN at indices 0..13 (need period+1 bars for first value)
        assert result.iloc[:14].isna().all()
        assert result.iloc[14:].notna().all()

    def test_reference_all_gains(self) -> None:
        # Monotone increasing: RS = inf, RSI = 100
        c = pd.Series(np.arange(1.0, 20.0))
        result = rsi(c, 5)
        # From index 5 onwards all gains, no losses -> RSI = 100
        assert (result.iloc[5:] == 100.0).all()

    def test_reference_all_losses(self) -> None:
        # Monotone decreasing: RS = 0, RSI = 0
        c = pd.Series(np.arange(20.0, 0.0, -1.0))
        result = rsi(c, 5)
        # avg_loss > 0, avg_gain = 0 -> RSI = 0
        assert (result.iloc[5:] == 0.0).all()

    def test_reference_alternating(self) -> None:
        # Fixed +1 / -1 pattern: avg_gain == avg_loss -> RSI = 50
        data = [100.0]
        for i in range(40):
            data.append(data[-1] + (1.0 if i % 2 == 0 else -1.0))
        c = pd.Series(data)
        result = rsi(c, 14)
        # After warmup, RSI should be close to 50 for balanced gains/losses
        np.testing.assert_allclose(result.iloc[20:].mean(), 50.0, atol=5.0)

    def test_range_0_100(self) -> None:
        c = _prices()
        result = rsi(c, 14)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(rsi, c, k=40)

    def test_output_dtype(self) -> None:
        assert rsi(_prices(), 14).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            rsi(_prices(), 0)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMACD:
    def test_columns(self) -> None:
        c = _prices()
        result = macd(c)
        assert set(result.columns) == {"macd", "signal", "histogram"}

    def test_warmup_nans(self) -> None:
        c = _prices(100)
        result = macd(c, fast=12, slow=26, signal_period=9)
        # slow EMA needs window-1 = 25 bars warm-up; signal adds signal_period-1 = 8 more
        # At minimum indices 0..24 of macd should be NaN
        assert result["macd"].iloc[:25].isna().all()

    def test_histogram_is_macd_minus_signal(self) -> None:
        c = _prices()
        result = macd(c)
        valid = result.dropna()
        np.testing.assert_allclose(
            valid["histogram"].values,
            (valid["macd"] - valid["signal"]).values,
            rtol=1e-10,
        )

    def test_reference_constant_price(self) -> None:
        # Constant price: all EMAs converge to price, MACD = signal = histogram = 0
        c = pd.Series([50.0] * 60)
        result = macd(c)
        valid = result.dropna()
        np.testing.assert_allclose(valid["macd"].values, 0.0, atol=1e-8)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(macd, c, k=50)

    def test_output_dtype(self) -> None:
        result = macd(_prices())
        for col in result.columns:
            assert result[col].dtype == np.float64

    def test_invalid_slow(self) -> None:
        with pytest.raises(ValueError):
            macd(_prices(), slow=0)


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


class TestStochastic:
    def test_columns(self) -> None:
        h, low, c = _ohlc()
        result = stochastic(h, low, c)
        assert set(result.columns) == {"pct_k", "pct_d"}

    def test_warmup_nans(self) -> None:
        h, low, c = _ohlc()
        result = stochastic(h, low, c, k_period=14, d_period=3, smooth_k=3)
        # k_period + smooth_k - 2 bars of NaN for pct_k
        # pct_d needs d_period more
        assert result["pct_d"].isna().sum() > 0

    def test_range_0_100(self) -> None:
        h, low, c = _ohlc()
        result = stochastic(h, low, c)
        for col in result.columns:
            v = result[col].dropna()
            assert (v >= 0.0).all() and (v <= 100.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(stochastic, h, low, c, k=50)

    def test_invalid_k_period(self) -> None:
        h, low, c = _ohlc()
        with pytest.raises(ValueError):
            stochastic(h, low, c, k_period=0)

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        result = stochastic(h, low, c)
        for col in result.columns:
            assert result[col].dtype == np.float64


# ---------------------------------------------------------------------------
# StochRSI
# ---------------------------------------------------------------------------


class TestStochRSI:
    def test_columns(self) -> None:
        c = _prices()
        result = stochrsi(c)
        assert set(result.columns) == {"pct_k", "pct_d"}

    def test_warmup_nans(self) -> None:
        c = _prices()
        result = stochrsi(c)
        assert result["pct_k"].isna().sum() > 0

    def test_range_0_100(self) -> None:
        c = _prices()
        result = stochrsi(c)
        for col in result.columns:
            v = result[col].dropna()
            assert (v >= 0.0).all() and (v <= 100.0).all()

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(stochrsi, c, k=50)

    def test_invalid_rsi_period(self) -> None:
        with pytest.raises(ValueError):
            stochrsi(_prices(), rsi_period=0)


# ---------------------------------------------------------------------------
# CCI
# ---------------------------------------------------------------------------


class TestCCI:
    def test_warmup_nan_count(self) -> None:
        h, low, c = _ohlc()
        result = cci(h, low, c, window=20)
        # MAD is rolling_mean(|tp - sma|, window) applied after sma is valid,
        # so warm-up is 2*(window-1) = 38 bars.
        assert result.iloc[:38].isna().all()
        assert result.iloc[38:].notna().all()

    def test_reference_constant_ohlc(self) -> None:
        # Constant prices: TP constant, MAD=0, CCI=0
        h = pd.Series([10.0] * 30)
        low = pd.Series([10.0] * 30)
        c = pd.Series([10.0] * 30)
        result = cci(h, low, c, window=5)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(cci, h, low, c, k=50)

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        assert cci(h, low, c).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c = _ohlc()
        with pytest.raises(ValueError):
            cci(h, low, c, window=0)


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


class TestWilliamsR:
    def test_warmup_nan_count(self) -> None:
        h, low, c = _ohlc()
        result = williams_r(h, low, c, window=14)
        assert result.iloc[:13].isna().all()
        assert result.iloc[13:].notna().all()

    def test_range_minus100_to_0(self) -> None:
        h, low, c = _ohlc()
        result = williams_r(h, low, c, window=14)
        valid = result.dropna()
        assert (valid >= -100.0).all() and (valid <= 0.0).all()

    def test_reference_close_at_high(self) -> None:
        # close == high: %R = 0 (or -0)
        h = pd.Series([10.0] * 20)
        low = pd.Series([5.0] * 20)
        c = h.copy()  # close == high
        result = williams_r(h, low, c, window=5)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_reference_close_at_low(self) -> None:
        # close == low: %R = -100
        h = pd.Series([10.0] * 20)
        low = pd.Series([5.0] * 20)
        c = low.copy()
        result = williams_r(h, low, c, window=5)
        np.testing.assert_allclose(result.dropna().values, -100.0, atol=1e-10)

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(williams_r, h, low, c, k=45)

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        assert williams_r(h, low, c).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c = _ohlc()
        with pytest.raises(ValueError):
            williams_r(h, low, c, window=0)


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------


class TestROC:
    def test_warmup_nan_count(self) -> None:
        c = _prices()
        result = roc(c, 12)
        assert result.iloc[:12].isna().all()
        assert result.iloc[12:].notna().all()

    def test_reference_constant(self) -> None:
        # Constant price: ROC = 0
        c = pd.Series([50.0] * 30)
        result = roc(c, 5)
        np.testing.assert_allclose(result.dropna().values, 0.0, atol=1e-10)

    def test_reference_doubling(self) -> None:
        # Price doubles over 5 periods -> ROC = 100%
        data = [100.0, 100.0, 100.0, 100.0, 100.0, 200.0]
        c = pd.Series(data)
        result = roc(c, 5)
        np.testing.assert_allclose(result.iloc[5], 100.0, rtol=1e-10)

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(roc, c, k=40)

    def test_output_dtype(self) -> None:
        assert roc(_prices(), 12).dtype == np.float64

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            roc(_prices(), 0)


# ---------------------------------------------------------------------------
# TSI
# ---------------------------------------------------------------------------


class TestTSI:
    def test_columns(self) -> None:
        c = _prices()
        result = tsi(c)
        assert set(result.columns) == {"tsi", "signal"}

    def test_warmup_nans(self) -> None:
        c = _prices()
        result = tsi(c)
        assert result["tsi"].isna().sum() > 0

    def test_truncation_invariance(self) -> None:
        c = _prices()
        _check_truncation_series(tsi, c, k=50)

    def test_output_dtype(self) -> None:
        result = tsi(_prices())
        for col in result.columns:
            assert result[col].dtype == np.float64

    def test_invalid_long_period(self) -> None:
        with pytest.raises(ValueError):
            tsi(_prices(), long_period=0)


# ---------------------------------------------------------------------------
# Ultimate Oscillator
# ---------------------------------------------------------------------------


class TestUltimateOscillator:
    def test_warmup_nan_count(self) -> None:
        # bp and tr use pd.concat().min/max(axis=1) which skips NaN, so both
        # series are fully valid from bar 0.  The rolling sum of width period3
        # is therefore first valid at index period3-1 = 27.
        h, low, c = _ohlc()
        result = ultimate_oscillator(h, low, c, period1=7, period2=14, period3=28)
        assert result.iloc[:27].isna().all()
        assert result.iloc[27:].notna().all()

    def test_range_0_100(self) -> None:
        h, low, c = _ohlc()
        result = ultimate_oscillator(h, low, c)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c = _ohlc()
        _check_truncation_series(ultimate_oscillator, h, low, c, k=55)

    def test_output_dtype(self) -> None:
        h, low, c = _ohlc()
        assert ultimate_oscillator(h, low, c).dtype == np.float64

    def test_invalid_period(self) -> None:
        h, low, c = _ohlc()
        with pytest.raises(ValueError):
            ultimate_oscillator(h, low, c, period1=0)
