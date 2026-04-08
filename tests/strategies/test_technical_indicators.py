"""Tests for the pure-pandas TechnicalIndicators utility class."""

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.mean_reversion.technical_indicators import TechnicalIndicators


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_close(n: int = 100, base: float = 100.0, trend: str = "flat", seed: int = 42) -> pd.Series:
    """Generate a simple close-price series."""
    rng = np.random.default_rng(seed)
    if trend == "up":
        drift = 0.002
    elif trend == "down":
        drift = -0.002
    else:
        drift = 0.0
    returns = rng.normal(drift, 0.015, n)
    prices = base * np.cumprod(1 + returns)
    return pd.Series(prices)


def _make_ohlcv(n: int = 100, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV DataFrame for indicator tests."""
    rng = np.random.default_rng(seed)
    close = _make_close(n, base=base, seed=seed)
    spread = close * 0.01
    high = close + rng.uniform(0, 1, n) * spread
    low = close - rng.uniform(0, 1, n) * spread
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(500_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ========================= RSI =============================================

class TestRSI:
    def test_returns_series(self):
        close = _make_close(100)
        result = TechnicalIndicators.rsi(close, 14)
        assert isinstance(result, pd.Series)
        assert len(result) == len(close)

    def test_range_0_to_100(self):
        close = _make_close(200)
        rsi = TechnicalIndicators.rsi(close, 14).dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_insufficient_data(self):
        """RSI on very short series should produce NaN for initial values."""
        close = pd.Series([100.0, 101.0, 102.0])
        rsi = TechnicalIndicators.rsi(close, 14)
        # Values before min_periods will be NaN, which is expected
        assert len(rsi) == 3

    def test_custom_period(self):
        close = _make_close(100)
        rsi_7 = TechnicalIndicators.rsi(close, 7)
        rsi_21 = TechnicalIndicators.rsi(close, 21)
        # Different periods produce different values
        assert not rsi_7.dropna().equals(rsi_21.dropna())

    def test_monotonically_up_means_high_rsi(self):
        """Prices going straight up should have RSI near 100."""
        close = pd.Series(np.linspace(100, 120, 50))
        rsi = TechnicalIndicators.rsi(close, 14)
        assert rsi.iloc[-1] > 80


# ========================= Bollinger Bands ==================================

class TestBollingerBands:
    def test_returns_three_series(self):
        close = _make_close(100)
        upper, middle, lower = TechnicalIndicators.bollinger_bands(close, 20)
        assert isinstance(upper, pd.Series)
        assert isinstance(middle, pd.Series)
        assert isinstance(lower, pd.Series)

    def test_upper_above_lower(self):
        close = _make_close(100)
        upper, middle, lower = TechnicalIndicators.bollinger_bands(close, 20)
        valid = upper.dropna()
        assert (valid >= lower.dropna()).all()

    def test_middle_is_sma(self):
        close = _make_close(100)
        _, middle, _ = TechnicalIndicators.bollinger_bands(close, 20)
        expected_sma = close.rolling(20).mean()
        pd.testing.assert_series_equal(middle, expected_sma, check_names=False)

    def test_custom_std_dev(self):
        close = _make_close(100)
        upper_2, _, lower_2 = TechnicalIndicators.bollinger_bands(close, 20, std_dev=2.0)
        upper_1, _, lower_1 = TechnicalIndicators.bollinger_bands(close, 20, std_dev=1.0)
        # Wider bands with larger std_dev
        assert (upper_2.dropna() >= upper_1.dropna()).all()
        assert (lower_2.dropna() <= lower_1.dropna()).all()


# ========================= MACD ============================================

class TestMACD:
    def test_returns_three_series(self):
        close = _make_close(100)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(close)
        assert isinstance(macd_line, pd.Series)
        assert isinstance(signal_line, pd.Series)
        assert isinstance(histogram, pd.Series)

    def test_histogram_is_difference(self):
        close = _make_close(200)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(close)
        expected = (macd_line - signal_line).dropna()
        actual = histogram.dropna()
        np.testing.assert_allclose(actual.values, expected.values, atol=1e-10)

    def test_insufficient_data(self):
        close = pd.Series([100.0, 101.0])
        macd_line, _, _ = TechnicalIndicators.macd(close)
        # Early values will be NaN but series length matches input
        assert len(macd_line) == 2


# ========================= ATR =============================================

class TestATR:
    def test_returns_series(self):
        df = _make_ohlcv(100)
        atr = TechnicalIndicators.atr(df["high"], df["low"], df["close"], 14)
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(df)

    def test_non_negative(self):
        df = _make_ohlcv(100)
        atr = TechnicalIndicators.atr(df["high"], df["low"], df["close"], 14).dropna()
        assert (atr >= 0).all()

    def test_value_reasonable(self):
        """ATR should be a fraction of the price, not orders of magnitude off."""
        df = _make_ohlcv(100)
        atr = TechnicalIndicators.atr(df["high"], df["low"], df["close"], 14).dropna()
        avg_price = df["close"].mean()
        assert (atr < avg_price).all()


# ========================= Stochastic ======================================

class TestStochastic:
    def test_returns_two_series(self):
        df = _make_ohlcv(100)
        k, d = TechnicalIndicators.stochastic(df["high"], df["low"], df["close"])
        assert isinstance(k, pd.Series)
        assert isinstance(d, pd.Series)

    def test_k_range_0_to_100(self):
        df = _make_ohlcv(100)
        k, _ = TechnicalIndicators.stochastic(df["high"], df["low"], df["close"])
        valid_k = k.dropna()
        assert (valid_k >= 0).all()
        assert (valid_k <= 100).all()

    def test_custom_periods(self):
        df = _make_ohlcv(100)
        k, d = TechnicalIndicators.stochastic(df["high"], df["low"], df["close"], k_period=10, d_period=5)
        assert isinstance(k, pd.Series)


# ========================= SMA =============================================

class TestSMA:
    def test_returns_series(self):
        close = _make_close(50)
        sma = TechnicalIndicators.sma(close, 20)
        assert isinstance(sma, pd.Series)
        assert len(sma) == len(close)

    def test_correct_values(self):
        close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        sma = TechnicalIndicators.sma(close, 3)
        assert pd.isna(sma.iloc[0])
        assert pd.isna(sma.iloc[1])
        assert abs(sma.iloc[2] - 2.0) < 1e-10
        assert abs(sma.iloc[3] - 3.0) < 1e-10
        assert abs(sma.iloc[4] - 4.0) < 1e-10


# ========================= Trend Strength ==================================

class TestTrendStrength:
    def test_returns_series(self):
        df = _make_ohlcv(100)
        adx = TechnicalIndicators.trend_strength(df["high"], df["low"], df["close"], 14)
        assert isinstance(adx, pd.Series)
        assert len(adx) == len(df)

    def test_non_negative(self):
        df = _make_ohlcv(100)
        adx = TechnicalIndicators.trend_strength(df["high"], df["low"], df["close"], 14).dropna()
        assert (adx >= 0).all()


# ========================= Volume SMA ======================================

class TestVolumeSMA:
    def test_returns_series(self):
        vol = pd.Series([1e6, 2e6, 3e6, 4e6, 5e6], dtype=float)
        sma = TechnicalIndicators.volume_sma(vol, 3)
        assert isinstance(sma, pd.Series)
        assert abs(sma.iloc[4] - 4e6) < 1e-6


# ========================= Integration =====================================

class TestTechnicalIndicatorsIntegration:
    """Cross-cutting tests to ensure the class works as a whole."""

    def test_all_methods_static(self):
        """Every public method should be callable as a static method."""
        assert callable(TechnicalIndicators.rsi)
        assert callable(TechnicalIndicators.bollinger_bands)
        assert callable(TechnicalIndicators.macd)
        assert callable(TechnicalIndicators.atr)
        assert callable(TechnicalIndicators.stochastic)
        assert callable(TechnicalIndicators.sma)
        assert callable(TechnicalIndicators.trend_strength)
        assert callable(TechnicalIndicators.volume_sma)

    def test_with_fixture_data(self, bull_data_252):
        """All indicators should run without error on fixture data."""
        df = bull_data_252
        close = df["close"]
        TechnicalIndicators.rsi(close, 14)
        TechnicalIndicators.bollinger_bands(close, 20)
        TechnicalIndicators.macd(close)
        TechnicalIndicators.atr(df["high"], df["low"], close, 14)
        TechnicalIndicators.stochastic(df["high"], df["low"], close)
        TechnicalIndicators.sma(close, 20)
        TechnicalIndicators.trend_strength(df["high"], df["low"], close, 14)
        TechnicalIndicators.volume_sma(df["volume"], 20)
