"""Tests for core_trading.strategies.ta_quant.primaries.

Coverage:
- Position values are strictly in {-1.0, 0.0, +1.0} for every primary.
- Warm-up period produces 0.0 (flat) before any indicator is valid.
- Truncation invariance: primary(data[:k]) == primary(data)[:k] on the
  non-NaN/flat region (the look-ahead-free contract).
- Hand-built tiny fixtures proving each rule fires where expected.
- No NaN in output frames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.ta_quant.primaries import (
    BollingerFadeConfig,
    DonchianBreakoutConfig,
    KeltnerSqueezeConfig,
    MACDTrendConfig,
    MACrossConfig,
    RSIDipConfig,
    bollinger_fade,
    donchian_breakout,
    keltner_squeeze,
    ma_cross,
    macd_trend,
    rsi_dip,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_SYMS = ["A", "B"]
_N = 300  # bars -- enough for all warm-up periods


def _make_index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _make_close(n: int = _N, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data: dict[str, np.ndarray] = {}
    for sym in _SYMS:
        price = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        price = np.clip(price, 1.0, None)
        data[sym] = price
    return pd.DataFrame(data, index=_make_index(n))


def _make_ohlcv(
    n: int = _N, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (close, high, low, volume) wide DataFrames."""
    close = _make_close(n, seed)
    rng = np.random.default_rng(seed + 1)
    high = close + rng.uniform(0.1, 1.0, close.shape)
    low = close - rng.uniform(0.1, 1.0, close.shape)
    high = pd.DataFrame(high, index=close.index, columns=close.columns)
    low = pd.DataFrame(low, index=close.index, columns=close.columns)
    volume = pd.DataFrame(
        np.ones(close.shape) * 1_000_000, index=close.index, columns=close.columns
    )
    return close, high, low, volume


def _assert_valid_positions(pos: pd.DataFrame) -> None:
    """Assert position frame contains only {-1, 0, +1} and no NaN."""
    assert not pos.isna().any().any(), "position frame contains NaN"
    arr = pos.to_numpy()
    valid_vals = {-1.0, 0.0, 1.0}
    unique_vals = set(np.unique(arr).tolist())
    unexpected = unique_vals - valid_vals
    assert not unexpected, f"unexpected position values: {unexpected}"


def _assert_truncation_invariance(pos_full: pd.DataFrame, pos_trunc: pd.DataFrame) -> None:
    """Assert truncated run agrees with full run on the overlapping region."""
    k = len(pos_trunc)
    overlap_full = pos_full.iloc[:k]
    # Both should agree on every bar where the truncated result is non-NaN.
    # (First bar may differ if it is 0.0 vs a state carried from warm-up,
    # but since warm-up is always 0.0 this should be exact.)
    np.testing.assert_array_equal(
        overlap_full.to_numpy(),
        pos_trunc.to_numpy(),
        err_msg="truncation invariance violated",
    )


# ---------------------------------------------------------------------------
# donchian_breakout
# ---------------------------------------------------------------------------


class TestDonchianBreakout:
    def test_position_values(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = DonchianBreakoutConfig(channel_window=20, allow_short=False)
        pos = donchian_breakout(close, high, low, cfg)
        _assert_valid_positions(pos)

    def test_no_short_when_long_only(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = DonchianBreakoutConfig(channel_window=20, allow_short=False)
        pos = donchian_breakout(close, high, low, cfg)
        assert (pos < 0).sum().sum() == 0, "long-only config should have no short positions"

    def test_warm_up_is_flat(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = DonchianBreakoutConfig(channel_window=20, allow_short=False)
        pos = donchian_breakout(close, high, low, cfg)
        # Before the channels are valid (first channel_window-1 bars) all
        # positions must be 0.
        warmup_end = cfg.channel_window - 1
        assert (pos.iloc[:warmup_end] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = DonchianBreakoutConfig(channel_window=20, allow_short=False)
        k = 150
        pos_full = donchian_breakout(close, high, low, cfg)
        pos_trunc = donchian_breakout(close.iloc[:k], high.iloc[:k], low.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_entry_fires_on_breakout(self) -> None:
        """Craft a price series that definitely crosses the 5-bar Donchian upper."""
        n = 20
        idx = _make_index(n)
        # Prices stay at 100 for the first 10 bars, then spike to 200.
        prices = np.array([100.0] * 10 + [200.0] * 10)
        close = pd.DataFrame({"X": prices}, index=idx)
        high = pd.DataFrame({"X": prices + 0.5}, index=idx)
        low = pd.DataFrame({"X": prices - 0.5}, index=idx)
        cfg = DonchianBreakoutConfig(channel_window=5, allow_short=False)
        pos = donchian_breakout(close, high, low, cfg)
        # After the spike the position should be +1
        assert (pos["X"].iloc[10:] == 1.0).any(), "breakout entry should fire"

    def test_short_fires_with_allow_short(self) -> None:
        """Craft a price series that drops below the Donchian lower."""
        n = 20
        idx = _make_index(n)
        prices = np.array([100.0] * 10 + [10.0] * 10)
        close = pd.DataFrame({"X": prices}, index=idx)
        high = pd.DataFrame({"X": prices + 0.5}, index=idx)
        low = pd.DataFrame({"X": prices - 0.5}, index=idx)
        cfg = DonchianBreakoutConfig(channel_window=5, allow_short=True)
        pos = donchian_breakout(close, high, low, cfg)
        assert (pos["X"].iloc[10:] == -1.0).any(), "short entry should fire"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            DonchianBreakoutConfig(channel_window=1)


# ---------------------------------------------------------------------------
# ma_cross
# ---------------------------------------------------------------------------


class TestMACross:
    def test_position_values(self) -> None:
        close = _make_close()
        cfg = MACrossConfig(fast_window=10, slow_window=50, long_only=False)
        pos = ma_cross(close, cfg)
        _assert_valid_positions(pos)

    def test_long_only_no_shorts(self) -> None:
        close = _make_close()
        cfg = MACrossConfig(fast_window=10, slow_window=50, long_only=True)
        pos = ma_cross(close, cfg)
        assert (pos < 0).sum().sum() == 0

    def test_warm_up_is_flat(self) -> None:
        close = _make_close()
        cfg = MACrossConfig(fast_window=10, slow_window=50, long_only=False)
        pos = ma_cross(close, cfg)
        # slow warm-up requires slow_window-1 bars
        assert (pos.iloc[: cfg.slow_window - 1] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        cfg = MACrossConfig(fast_window=10, slow_window=50, long_only=False)
        k = 150
        pos_full = ma_cross(close, cfg)
        pos_trunc = ma_cross(close.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_long_fires_when_fast_above_slow(self) -> None:
        """Craft a steadily rising series where fast EMA must exceed slow EMA."""
        n = 100
        idx = _make_index(n)
        # A constant upward trend so fast EMA will be above slow EMA.
        prices = np.linspace(100.0, 200.0, n)
        close = pd.DataFrame({"X": prices}, index=idx)
        cfg = MACrossConfig(fast_window=5, slow_window=20, long_only=False)
        pos = ma_cross(close, cfg)
        # After warm-up, the upward trend should give long positions.
        assert (pos["X"].iloc[30:] == 1.0).all(), "uptrend should produce long positions"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            MACrossConfig(fast_window=50, slow_window=20)


# ---------------------------------------------------------------------------
# rsi_dip
# ---------------------------------------------------------------------------


class TestRSIDip:
    def test_position_values(self) -> None:
        close = _make_close()
        cfg = RSIDipConfig(rsi_window=2, trend_window=50)
        pos = rsi_dip(close, cfg)
        _assert_valid_positions(pos)

    def test_long_only_no_shorts(self) -> None:
        close = _make_close()
        cfg = RSIDipConfig(rsi_window=2, trend_window=50, allow_short=False)
        pos = rsi_dip(close, cfg)
        assert (pos < 0).sum().sum() == 0

    def test_warm_up_is_flat(self) -> None:
        close = _make_close()
        cfg = RSIDipConfig(rsi_window=2, trend_window=100)
        pos = rsi_dip(close, cfg)
        # trend_window is the longer warm-up
        assert (pos.iloc[: cfg.trend_window - 1] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        cfg = RSIDipConfig(rsi_window=2, trend_window=50)
        k = 150
        pos_full = rsi_dip(close, cfg)
        pos_trunc = rsi_dip(close.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_entry_fires_on_oversold_with_uptrend(self) -> None:
        """Craft a series: long uptrend, then a sharp dip, so RSI(2) is low."""
        n = 80
        idx = _make_index(n)
        # Strong uptrend for 60 bars, then sharp 3-bar drop, then recovery.
        uptrend = np.linspace(100.0, 200.0, 60)
        dip = np.linspace(200.0, 100.0, 5)
        recovery = np.linspace(100.0, 200.0, 15)
        prices = np.concatenate([uptrend, dip, recovery])
        close = pd.DataFrame({"X": prices}, index=idx)
        cfg = RSIDipConfig(
            rsi_window=2,
            lower_thresh=20.0,
            upper_thresh=80.0,
            exit_thresh=65.0,
            trend_window=50,
            allow_short=False,
        )
        pos = rsi_dip(close, cfg)
        # During or just after the dip, a long entry should fire.
        assert (pos["X"].iloc[60:75] == 1.0).any(), "long entry should fire during dip above trend"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            RSIDipConfig(rsi_window=0)
        with pytest.raises(ValueError):
            RSIDipConfig(lower_thresh=50.0, upper_thresh=40.0)


# ---------------------------------------------------------------------------
# macd_trend
# ---------------------------------------------------------------------------


class TestMACDTrend:
    def test_position_values(self) -> None:
        close = _make_close()
        cfg = MACDTrendConfig(fast=12, slow=26, signal_period=9, allow_short=True)
        pos = macd_trend(close, cfg)
        _assert_valid_positions(pos)

    def test_no_short_when_disabled(self) -> None:
        close = _make_close()
        cfg = MACDTrendConfig(fast=12, slow=26, signal_period=9, allow_short=False)
        pos = macd_trend(close, cfg)
        assert (pos < 0).sum().sum() == 0

    def test_warm_up_is_flat(self) -> None:
        close = _make_close()
        cfg = MACDTrendConfig(fast=12, slow=26, signal_period=9)
        pos = macd_trend(close, cfg)
        # Need slow + signal - 2 bars before any output
        assert (pos.iloc[:34] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        cfg = MACDTrendConfig(fast=12, slow=26, signal_period=9)
        k = 150
        pos_full = macd_trend(close, cfg)
        pos_trunc = macd_trend(close.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_long_fires_on_rising_positive_histogram(self) -> None:
        """Monotone trend: MACD histogram should become positive and rising."""
        n = 100
        idx = _make_index(n)
        prices = np.linspace(100.0, 300.0, n)
        close = pd.DataFrame({"X": prices}, index=idx)
        cfg = MACDTrendConfig(fast=5, slow=20, signal_period=5, allow_short=True)
        pos = macd_trend(close, cfg)
        assert (pos["X"].iloc[50:] == 1.0).any(), "long should fire in strong uptrend"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            MACDTrendConfig(fast=26, slow=12)


# ---------------------------------------------------------------------------
# bollinger_fade
# ---------------------------------------------------------------------------


class TestBollingerFade:
    def test_position_values(self) -> None:
        close = _make_close()
        cfg = BollingerFadeConfig(window=20, num_std=2.0, min_bandwidth=0.005)
        pos = bollinger_fade(close, cfg)
        _assert_valid_positions(pos)

    def test_warm_up_is_flat(self) -> None:
        close = _make_close()
        cfg = BollingerFadeConfig(window=20)
        pos = bollinger_fade(close, cfg)
        assert (pos.iloc[: cfg.window - 1] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        cfg = BollingerFadeConfig(window=20, min_bandwidth=0.005)
        k = 150
        pos_full = bollinger_fade(close, cfg)
        pos_trunc = bollinger_fade(close.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_long_entry_on_lower_band_touch(self) -> None:
        """Craft a series where price dips to/below the lower band."""
        n = 60
        idx = _make_index(n)
        # Random walk seeded so it dips sharply around bar 40.
        rng = np.random.default_rng(123)
        prices = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
        # Force a known dip.
        prices[38:42] -= 10.0
        close = pd.DataFrame({"X": prices}, index=idx)
        cfg = BollingerFadeConfig(window=20, num_std=2.0, min_bandwidth=0.001)
        pos = bollinger_fade(close, cfg)
        assert (pos["X"].iloc[38:55] == 1.0).any(), "lower-band touch should trigger long fade"

    def test_no_entry_when_bandwidth_too_narrow(self) -> None:
        """With a very high min_bandwidth no entry should fire on a flat series."""
        n = 100
        idx = _make_index(n)
        # Nearly constant price -- very narrow bands.
        prices = 100.0 + np.random.default_rng(0).normal(0, 0.001, n)
        close = pd.DataFrame({"X": prices}, index=idx)
        cfg = BollingerFadeConfig(window=20, num_std=2.0, min_bandwidth=100.0)
        pos = bollinger_fade(close, cfg)
        # With bandwidth floor = 100 (100% of price), no entries should fire.
        assert (pos == 0.0).all().all(), "no entry should fire with very high min_bandwidth"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            BollingerFadeConfig(window=1)
        with pytest.raises(ValueError):
            BollingerFadeConfig(num_std=0.0)


# ---------------------------------------------------------------------------
# keltner_squeeze
# ---------------------------------------------------------------------------


class TestKeltnerSqueeze:
    def test_position_values(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = KeltnerSqueezeConfig()
        pos = keltner_squeeze(close, high, low, cfg)
        _assert_valid_positions(pos)

    def test_warm_up_is_flat(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = KeltnerSqueezeConfig(bb_window=20, kc_ema_period=20, kc_atr_period=10)
        pos = keltner_squeeze(close, high, low, cfg)
        # Before both band types are valid, must be flat.
        assert (pos.iloc[:19] == 0.0).all().all()

    def test_truncation_invariance(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = KeltnerSqueezeConfig()
        k = 150
        pos_full = keltner_squeeze(close, high, low, cfg)
        pos_trunc = keltner_squeeze(close.iloc[:k], high.iloc[:k], low.iloc[:k], cfg)
        _assert_truncation_invariance(pos_full, pos_trunc)

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            KeltnerSqueezeConfig(bb_window=1)
        with pytest.raises(ValueError):
            KeltnerSqueezeConfig(kc_multiplier=0.0)

    def test_no_short_when_disabled(self) -> None:
        close, high, low, _ = _make_ohlcv()
        cfg = KeltnerSqueezeConfig(allow_short=False)
        pos = keltner_squeeze(close, high, low, cfg)
        assert (pos < 0).sum().sum() == 0
