"""Pure pandas/numpy implementations of common technical indicators.

This module provides a utility class for calculating technical indicators
without relying on TA-Lib, making it portable and testable.
"""

from typing import Tuple

import numpy as np
import pandas as pd


class TechnicalIndicators:
    """A utility class for calculating technical indicators using pure pandas/numpy."""

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI).

        Uses exponential moving average of gains/losses (Wilder's smoothing).

        Args:
            close: Series of closing prices.
            period: RSI lookback period (default 14).

        Returns:
            Series of RSI values (0-100).
        """
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        # Wilder's smoothing (EWM with com = period - 1)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        # Avoid division by zero
        rs = avg_gain / avg_loss.where(avg_loss != 0, 1e-10)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def bollinger_bands(
        close: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands.

        Args:
            close: Series of closing prices.
            period: Moving average period (default 20).
            std_dev: Number of standard deviations (default 2.0).

        Returns:
            Tuple of (upper_band, middle_band, lower_band).
        """
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

    @staticmethod
    def macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Moving Average Convergence Divergence (MACD).

        Args:
            close: Series of closing prices.
            fast: Fast EMA period (default 12).
            slow: Slow EMA period (default 26).
            signal: Signal line EMA period (default 9).

        Returns:
            Tuple of (macd_line, signal_line, histogram).
        """
        fast_ema = close.ewm(span=fast, adjust=False).mean()
        slow_ema = close.ewm(span=slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """Calculate Average True Range (ATR).

        Args:
            high: Series of high prices.
            low: Series of low prices.
            close: Series of closing prices.
            period: ATR lookback period (default 14).

        Returns:
            Series of ATR values.
        """
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_values = true_range.ewm(com=period - 1, min_periods=period).mean()
        return atr_values

    @staticmethod
    def stochastic(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        k_period: int = 14,
        d_period: int = 3,
    ) -> Tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator (%K and %D).

        Args:
            high: Series of high prices.
            low: Series of low prices.
            close: Series of closing prices.
            k_period: %K lookback period (default 14).
            d_period: %D smoothing period (default 3).

        Returns:
            Tuple of (%K, %D).
        """
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        denominator = highest_high - lowest_low
        # Avoid division by zero when highest == lowest
        k_percent = 100.0 * (close - lowest_low) / denominator.where(denominator != 0, 1e-10)
        d_percent = k_percent.rolling(window=d_period).mean()
        return k_percent, d_percent

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average.

        Args:
            series: Input data series.
            period: Window period.

        Returns:
            Series of SMA values.
        """
        return series.rolling(window=period).mean()

    @staticmethod
    def trend_strength(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """Calculate ADX-like trend strength using directional movement.

        This is a simplified ADX approximation using pure pandas.

        Args:
            high: Series of high prices.
            low: Series of low prices.
            close: Series of closing prices.
            period: Lookback period (default 14).

        Returns:
            Series of trend strength values (0-100 scale).
        """
        prev_high = high.shift(1)
        prev_low = low.shift(1)

        # True Range
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        # Smooth using EWM (Wilder's)
        atr_val = true_range.ewm(com=period - 1, min_periods=period).mean()
        smooth_plus_dm = plus_dm.ewm(com=period - 1, min_periods=period).mean()
        smooth_minus_dm = minus_dm.ewm(com=period - 1, min_periods=period).mean()

        # Directional Indicators
        plus_di = 100.0 * smooth_plus_dm / atr_val.where(atr_val != 0, 1e-10)
        minus_di = 100.0 * smooth_minus_dm / atr_val.where(atr_val != 0, 1e-10)

        # ADX
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).where(
            (plus_di + minus_di) != 0, 1e-10
        )
        adx = dx.ewm(com=period - 1, min_periods=period).mean()
        return adx

    @staticmethod
    def volume_sma(volume: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average of volume.

        Args:
            volume: Series of volume data.
            period: Window period.

        Returns:
            Series of volume SMA values.
        """
        return volume.rolling(window=period).mean()
