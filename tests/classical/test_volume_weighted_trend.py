"""Tests for core_trading.strategies.classical.volume_weighted_trend.

Covers:
* VWTrendConfig validation (every guard).
* vw_ema: CONSTANT-VOLUME identity against pandas ewm (exact), seed, volume tilt.
* vw_macd: line == fast - slow, signal line == ewm of line.
* wilder_adx: known-value (monotonic trend -> ADX 100), warmup index, chop -> low.
* vw_trend_signal: value set, no-trade ADX band, direction logic.
* CRITICAL: truncation-invariance of vw_trend_signal.
* vw_trend_weights relabel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.classical.volume_weighted_trend import (
    VWTrendConfig,
    vw_ema,
    vw_macd,
    vw_trend_signal,
    vw_trend_weights,
    wilder_adx,
)

_SEED = 20260605


def _ohlcv(
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    hl_pad: float = 0.002,
) -> pd.DataFrame:
    n = close.size
    if volume is None:
        volume = np.full(n, 1_000_000.0)
    high = close * (1.0 + hl_pad)
    low = close * (1.0 - hl_pad)
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _trend_ohlcv(n: int = 1600, seed: int = _SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    seg = 200
    drift = 0.006
    rets = np.empty(n, dtype=float)
    t = 0
    while t < n:
        end = min(t + seg, n)
        sign = 1.0 if (t // seg) % 2 == 0 else -1.0
        rets[t:end] = sign * drift + rng.normal(0.0, 0.008, end - t)
        t = end
    close = 100.0 * np.exp(np.cumsum(rets))
    volume = np.abs(1_000_000.0 * (1.0 + rng.normal(0.0, 0.2, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.002, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.002, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestVWTrendConfig:
    def test_defaults_ok(self) -> None:
        cfg = VWTrendConfig()
        assert cfg.fast_window == 12
        assert cfg.slow_window == 26

    def test_fast_ge_slow(self) -> None:
        with pytest.raises(ValueError, match="strictly less"):
            VWTrendConfig(fast_window=26, slow_window=26)

    def test_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            VWTrendConfig(fast_window=1)

    def test_signal_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="signal_window"):
            VWTrendConfig(signal_window=1)

    def test_adx_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="adx_window"):
            VWTrendConfig(adx_window=1)

    def test_adx_thresholds_ordering(self) -> None:
        with pytest.raises(ValueError, match="adx_medium <= adx_strong"):
            VWTrendConfig(adx_strong=20.0, adx_medium=25.0)
        with pytest.raises(ValueError, match="adx_medium <= adx_strong"):
            VWTrendConfig(adx_medium=0.0)

    def test_vol_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            VWTrendConfig(vol_window=1)

    def test_weight_clip_invalid(self) -> None:
        with pytest.raises(ValueError, match="weight_clip"):
            VWTrendConfig(weight_clip=(1.5, 3.0))
        with pytest.raises(ValueError, match="weight_clip"):
            VWTrendConfig(weight_clip=(0.0, 3.0))
        with pytest.raises(ValueError, match="weight_clip"):
            VWTrendConfig(weight_clip=(0.5, 0.9))


# ---------------------------------------------------------------------------
# vw_ema
# ---------------------------------------------------------------------------


class TestVWEma:
    def test_constant_volume_equals_plain_ema(self) -> None:
        """The pinning identity: constant volume -> VW-EMA == standard EMA."""
        rng = np.random.default_rng(0)
        price = pd.Series(100.0 + np.cumsum(rng.normal(0, 1, 300)))
        volume = pd.Series(np.full(300, 1234.0))
        vw = vw_ema(price, volume, period=12, vol_window=20)
        plain = price.ewm(span=12, adjust=False).mean()
        np.testing.assert_allclose(vw.to_numpy(), plain.to_numpy(), rtol=0, atol=1e-12)

    def test_seed_equals_first_price(self) -> None:
        price = pd.Series([10.0, 11.0, 12.0])
        volume = pd.Series([1.0, 1.0, 1.0])
        vw = vw_ema(price, volume, period=2, vol_window=2)
        assert vw.iloc[0] == pytest.approx(10.0)

    def test_high_volume_bar_pulls_harder(self) -> None:
        """A high-volume up-bar moves the VW-EMA more than constant volume would."""
        price = pd.Series([10.0, 10.0, 20.0])
        vol_const = pd.Series([1.0, 1.0, 1.0])
        vol_spike = pd.Series([1.0, 1.0, 10.0])
        vw_const = vw_ema(price, vol_const, period=5, vol_window=2)
        vw_spike = vw_ema(price, vol_spike, period=5, vol_window=2)
        assert vw_spike.iloc[-1] > vw_const.iloc[-1]

    def test_period_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="period must be at least 1"):
            vw_ema(pd.Series([1.0]), pd.Series([1.0]), period=0, vol_window=2)

    def test_empty_series(self) -> None:
        out = vw_ema(pd.Series([], dtype=float), pd.Series([], dtype=float),
                     period=5, vol_window=2)
        assert out.empty

    def test_clip_caps_weight(self) -> None:
        # An enormous volume spike must not blow up the recursion past the price.
        price = pd.Series([10.0, 10.0, 20.0])
        vol = pd.Series([1.0, 1.0, 1e9])
        vw = vw_ema(price, vol, period=5, vol_window=2, weight_clip=(0.2, 3.0))
        # alpha=2/6=0.333, clipped weight 3 -> a=1.0 capped... but a stays < 1 here.
        assert vw.iloc[-1] <= 20.0


# ---------------------------------------------------------------------------
# vw_macd
# ---------------------------------------------------------------------------


class TestVWMacd:
    def test_macd_is_fast_minus_slow(self) -> None:
        df = _trend_ohlcv(n=400)
        cfg = VWTrendConfig()
        m = vw_macd(df["close"], df["volume"], cfg)
        np.testing.assert_allclose(
            m["macd"].to_numpy(),
            (m["vw_ema_fast"] - m["vw_ema_slow"]).to_numpy(),
            atol=1e-12,
        )

    def test_signal_is_ewm_of_macd(self) -> None:
        df = _trend_ohlcv(n=400)
        cfg = VWTrendConfig()
        m = vw_macd(df["close"], df["volume"], cfg)
        expected = m["macd"].ewm(span=cfg.signal_window, adjust=False).mean()
        np.testing.assert_allclose(
            m["macd_signal"].to_numpy(), expected.to_numpy(), atol=1e-12
        )


# ---------------------------------------------------------------------------
# wilder_adx
# ---------------------------------------------------------------------------


class TestWilderAdx:
    def test_monotonic_uptrend_adx_100(self) -> None:
        n = 60
        close = np.arange(1.0, n + 1)
        adx = wilder_adx(
            pd.Series(close + 0.5), pd.Series(close - 0.5), pd.Series(close), window=14
        )
        assert adx.iloc[-1] == pytest.approx(100.0)

    def test_monotonic_downtrend_adx_100(self) -> None:
        n = 60
        close = np.arange(n, 0, -1, dtype=float)
        adx = wilder_adx(
            pd.Series(close + 0.5), pd.Series(close - 0.5), pd.Series(close), window=14
        )
        assert adx.iloc[-1] == pytest.approx(100.0)

    def test_first_finite_index(self) -> None:
        """ADX needs a double warmup: first finite value at index 2*window - 1."""
        n = 60
        close = np.arange(1.0, n + 1)
        adx = wilder_adx(
            pd.Series(close + 0.5), pd.Series(close - 0.5), pd.Series(close), window=14
        )
        finite = np.isfinite(adx.to_numpy())
        assert int(np.argmax(finite)) == 2 * 14 - 1

    def test_chop_low_adx(self) -> None:
        rng = np.random.default_rng(1)
        c = 20.0 + rng.normal(0, 0.3, 80)
        adx = wilder_adx(pd.Series(c + 0.5), pd.Series(c - 0.5), pd.Series(c), window=14)
        assert adx.iloc[-1] < 25.0

    def test_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be at least 2"):
            wilder_adx(pd.Series([1.0]), pd.Series([1.0]), pd.Series([1.0]), window=1)

    def test_range_bounded(self) -> None:
        df = _trend_ohlcv(n=600)
        adx = wilder_adx(df["high"], df["low"], df["close"], window=14)
        valid = adx.dropna().to_numpy()
        assert np.all(valid >= 0.0) and np.all(valid <= 100.0 + 1e-9)


# ---------------------------------------------------------------------------
# vw_trend_signal
# ---------------------------------------------------------------------------


class TestVWTrendSignal:
    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0], "volume": [1.0, 1.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            vw_trend_signal(df)

    def test_output_value_set(self) -> None:
        df = _trend_ohlcv(n=800)
        sig = vw_trend_signal(df)
        assert set(np.unique(sig.to_numpy())).issubset({-1.0, 0.0, 1.0})
        assert sig.name == "position"

    def test_takes_positions_on_trend(self) -> None:
        df = _trend_ohlcv(n=1200)
        sig = vw_trend_signal(df)
        assert (sig != 0.0).sum() > 0

    def test_no_trade_band_flattens(self) -> None:
        """A very high adx_medium gate suppresses all trading (chop everywhere)."""
        df = _trend_ohlcv(n=800)
        cfg = VWTrendConfig(adx_strong=99.5, adx_medium=99.0)
        sig = vw_trend_signal(df, cfg)
        # Almost nothing should clear a 99 ADX gate.
        assert (sig != 0.0).sum() == 0

    def test_index_preserved(self) -> None:
        df = _trend_ohlcv(n=400)
        idx = pd.date_range("2020-01-01", periods=len(df))
        df.index = idx
        sig = vw_trend_signal(df)
        pd.testing.assert_index_equal(sig.index, idx)

    def test_short_series_all_flat(self) -> None:
        df = _ohlcv(np.arange(1.0, 11.0))  # too short for ADX warmup
        sig = vw_trend_signal(df)
        assert (sig == 0.0).all()


# ---------------------------------------------------------------------------
# Truncation invariance (CRITICAL)
# ---------------------------------------------------------------------------


class TestTruncationInvariance:
    def test_signal_unchanged_by_future_bars(self) -> None:
        df = _trend_ohlcv(n=1000)
        k = 650
        full = vw_trend_signal(df).to_numpy()
        pref = vw_trend_signal(df.iloc[:k]).to_numpy()
        np.testing.assert_array_equal(full[:k], pref)


# ---------------------------------------------------------------------------
# vw_trend_weights
# ---------------------------------------------------------------------------


class TestVWTrendWeights:
    def test_relabel_of_signal(self) -> None:
        df = _trend_ohlcv(n=400)
        sig = vw_trend_signal(df)
        w = vw_trend_weights(df)
        assert w.name == "weight"
        np.testing.assert_array_equal(sig.to_numpy(), w.to_numpy())
