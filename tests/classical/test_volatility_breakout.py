"""Tests for core_trading.strategies.classical.volatility_breakout.

Covers:
* BreakoutConfig validation (every guard).
* bollinger_bands / band_width known-value (hand-computed) checks, std and ATR.
* squeeze_mask / volume_surge_mask boolean semantics and warmup.
* breakout_signal state machine: entry only out of a confirmed squeeze, exit on
  middle-band touch, opposite-breakout reversal, output value set.
* CRITICAL: truncation-invariance (look-ahead-free) of breakout_signal.
* breakout_weights relabel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.classical.volatility_breakout import (
    BreakoutConfig,
    band_width,
    bollinger_bands,
    breakout_signal,
    breakout_weights,
    squeeze_mask,
    volume_surge_mask,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SEED = 20260605


def _ohlcv(
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    hl_pad: float = 0.0,
) -> pd.DataFrame:
    n = close.size
    if volume is None:
        volume = np.full(n, 1_000_000.0)
    high = close * (1.0 + hl_pad)
    low = close * (1.0 - hl_pad)
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _vol_regime_ohlcv(n: int = 1600, seed: int = _SEED) -> pd.DataFrame:
    """Squeeze (quiet) then directional volume-backed expansion, repeating.

    Engineered so the breakout rule -- enter out of a squeeze on a volume-backed
    band break, exit on the mid touch -- has a genuine edge.
    """
    rng = np.random.default_rng(seed)
    rets = np.zeros(n, dtype=float)
    vol = np.full(n, 1.0, dtype=float)
    t = 0
    squeeze_len, expand_len = 60, 40
    sign = 1.0
    while t < n:
        s_end = min(t + squeeze_len, n)
        rets[t:s_end] = rng.normal(0.0, 0.002, s_end - t)
        vol[t:s_end] = 1.0
        t = s_end
        if t >= n:
            break
        e_end = min(t + expand_len, n)
        rets[t:e_end] = sign * 0.012 + rng.normal(0.0, 0.004, e_end - t)
        vol[t:e_end] = 3.5
        sign = -sign
        t = e_end
    close = 100.0 * np.exp(np.cumsum(rets))
    volume = np.abs(1_000_000.0 * vol * (1.0 + rng.normal(0.0, 0.05, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.001, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.001, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestBreakoutConfig:
    def test_defaults_ok(self) -> None:
        cfg = BreakoutConfig()
        assert cfg.band_window == 20
        assert cfg.use_atr is False

    def test_band_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="band_window"):
            BreakoutConfig(band_window=1)

    def test_band_k_nonpositive(self) -> None:
        with pytest.raises(ValueError, match="band_k"):
            BreakoutConfig(band_k=0.0)

    def test_squeeze_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="squeeze_window"):
            BreakoutConfig(squeeze_window=1)

    def test_squeeze_q_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="squeeze_q"):
            BreakoutConfig(squeeze_q=1.5)
        with pytest.raises(ValueError, match="squeeze_q"):
            BreakoutConfig(squeeze_q=-0.1)

    def test_squeeze_q_boundaries_ok(self) -> None:
        assert BreakoutConfig(squeeze_q=0.0).squeeze_q == 0.0
        assert BreakoutConfig(squeeze_q=1.0).squeeze_q == 1.0

    def test_squeeze_lookback_too_small(self) -> None:
        with pytest.raises(ValueError, match="squeeze_lookback"):
            BreakoutConfig(squeeze_lookback=0)

    def test_vol_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            BreakoutConfig(vol_window=1)

    def test_vol_k_nonpositive(self) -> None:
        with pytest.raises(ValueError, match="vol_k"):
            BreakoutConfig(vol_k=-1.0)

    def test_frozen(self) -> None:
        cfg = BreakoutConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.band_window = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Bollinger bands / band width -- known values
# ---------------------------------------------------------------------------


class TestBollingerBands:
    def test_known_values_std(self) -> None:
        close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        df = _ohlcv(close)
        cfg = BreakoutConfig(band_window=3, band_k=2.0)
        bands = bollinger_bands(df, cfg)
        # Window [1,2,3]: mid=2, pstd=sqrt(2/3); upper=2+2*pstd
        pstd = float(np.std([1.0, 2.0, 3.0]))
        assert bands["mid"].iloc[2] == pytest.approx(2.0)
        assert bands["upper"].iloc[2] == pytest.approx(2.0 + 2.0 * pstd)
        assert bands["lower"].iloc[2] == pytest.approx(2.0 - 2.0 * pstd)

    def test_warmup_nan(self) -> None:
        close = np.arange(1.0, 11.0)
        df = _ohlcv(close)
        cfg = BreakoutConfig(band_window=5)
        bands = bollinger_bands(df, cfg)
        assert bands["mid"].iloc[:4].isna().all()
        assert bands["mid"].iloc[4:].notna().all()

    def test_band_width_known(self) -> None:
        close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        df = _ohlcv(close)
        cfg = BreakoutConfig(band_window=3, band_k=2.0)
        bands = bollinger_bands(df, cfg)
        w = band_width(bands)
        pstd = float(np.std([1.0, 2.0, 3.0]))
        # width = (upper - lower)/mid = (4*pstd)/2
        assert w.iloc[2] == pytest.approx((4.0 * pstd) / 2.0)

    def test_atr_bands_finite(self) -> None:
        rng = np.random.default_rng(1)
        close = 100.0 + np.cumsum(rng.normal(0, 1, 100))
        df = _ohlcv(close, hl_pad=0.01)
        cfg = BreakoutConfig(band_window=14, use_atr=True)
        bands = bollinger_bands(df, cfg)
        assert bands["upper"].dropna().size > 0
        # ATR bands must straddle the mid
        valid = bands.dropna()
        assert (valid["upper"] >= valid["mid"]).all()
        assert (valid["lower"] <= valid["mid"]).all()


# ---------------------------------------------------------------------------
# Squeeze and volume masks
# ---------------------------------------------------------------------------


class TestMasks:
    def test_squeeze_mask_picks_low_width(self) -> None:
        # width that is constant then dips: the dip should be flagged at low q
        width = pd.Series([0.1] * 30 + [0.01] * 5 + [0.1] * 30)
        cfg = BreakoutConfig(squeeze_window=20, squeeze_q=0.2)
        mask = squeeze_mask(width, cfg)
        # The low-width bars must be flagged
        assert mask.iloc[30:35].any()
        assert mask.dtype == bool

    def test_squeeze_warmup_false(self) -> None:
        width = pd.Series(np.linspace(0.05, 0.2, 60))
        cfg = BreakoutConfig(squeeze_window=20, squeeze_q=0.3)
        mask = squeeze_mask(width, cfg)
        assert not mask.iloc[:19].any()

    def test_volume_surge_mask(self) -> None:
        vol = pd.Series([100.0] * 25 + [1000.0])
        cfg = BreakoutConfig(vol_window=20, vol_k=2.0)
        mask = volume_surge_mask(vol, cfg)
        assert bool(mask.iloc[-1]) is True
        assert not mask.iloc[:19].any()

    def test_volume_surge_no_false_positive(self) -> None:
        vol = pd.Series(np.full(40, 100.0))
        cfg = BreakoutConfig(vol_window=20, vol_k=1.5)
        mask = volume_surge_mask(vol, cfg)
        assert not mask.any()


# ---------------------------------------------------------------------------
# breakout_signal state machine
# ---------------------------------------------------------------------------


class TestBreakoutSignal:
    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0], "volume": [1.0, 1.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            breakout_signal(df)

    def test_output_value_set(self) -> None:
        df = _vol_regime_ohlcv(n=800)
        sig = breakout_signal(df)
        assert set(np.unique(sig.to_numpy())).issubset({-1.0, 0.0, 1.0})
        assert sig.name == "position"

    def test_index_preserved(self) -> None:
        df = _vol_regime_ohlcv(n=400)
        idx = pd.date_range("2020-01-01", periods=len(df))
        df.index = idx
        sig = breakout_signal(df)
        pd.testing.assert_index_equal(sig.index, idx)

    def test_takes_positions(self) -> None:
        """On the engineered squeeze->expansion path the rule must actually trade."""
        df = _vol_regime_ohlcv(n=1200)
        sig = breakout_signal(df)
        assert (sig != 0.0).sum() > 0

    def test_exit_on_middle_band_touch(self) -> None:
        """A long opened on a breakout closes when price returns to the mid band."""
        # Construct: quiet ramp (squeeze), a volume-backed pop above the band,
        # then a slide back through the middle band.
        quiet = np.full(40, 100.0) + np.linspace(0, 0.2, 40)
        pop = np.array([104.0, 106.0, 108.0])  # clear upper-band break
        fade = np.linspace(107.0, 95.0, 10)  # slides back below mid
        close = np.concatenate([quiet, pop, fade])
        vol = np.concatenate(
            [np.full(40, 1_000_000.0), np.full(3, 5_000_000.0), np.full(10, 1_000_000.0)]
        )
        df = _ohlcv(close, volume=vol)
        cfg = BreakoutConfig(
            band_window=20, band_k=2.0, squeeze_window=20, squeeze_q=0.6,
            vol_window=20, vol_k=1.5,
        )
        sig = breakout_signal(df, cfg)
        # Goes long at the pop ...
        assert (sig.iloc[40:43] == 1.0).any()
        # ... and is flat again by the end of the fade (mid touch closed it).
        assert sig.iloc[-1] == 0.0

    def test_long_to_short_reversal(self) -> None:
        """A volume-backed opposite breakout flips a long straight to short."""
        quiet = np.full(40, 100.0) + np.linspace(0, 0.1, 40)
        pop = np.array([105.0, 107.0])  # up break -> long
        crash = np.array([108.0, 90.0, 85.0])  # strong down break -> short
        close = np.concatenate([quiet, pop, crash])
        vol = np.concatenate(
            [np.full(40, 1_000_000.0), np.full(2, 5_000_000.0), np.full(3, 6_000_000.0)]
        )
        df = _ohlcv(close, volume=vol, hl_pad=0.001)
        cfg = BreakoutConfig(
            band_window=20, band_k=2.0, squeeze_window=20, squeeze_q=0.7,
            squeeze_lookback=10, vol_window=20, vol_k=1.5,
        )
        sig = breakout_signal(df, cfg).to_numpy()
        assert 1.0 in sig[40:43]
        assert sig[-1] == -1.0

    def test_short_to_long_reversal(self) -> None:
        """Symmetric: a volume-backed up breakout flips a short straight to long."""
        quiet = np.full(40, 100.0) + np.linspace(0, 0.05, 40)  # near-flat squeeze
        drop = np.array([95.0, 90.0])  # sharp down break -> short
        rally = np.array([93.0, 108.0, 112.0])  # sharp up break -> long
        close = np.concatenate([quiet, drop, rally])
        vol = np.concatenate(
            [np.full(40, 1_000_000.0), np.full(2, 5_000_000.0), np.full(3, 6_000_000.0)]
        )
        df = _ohlcv(close, volume=vol, hl_pad=0.001)
        cfg = BreakoutConfig(
            band_window=20, band_k=2.0, squeeze_window=20, squeeze_q=0.7,
            squeeze_lookback=10, vol_window=20, vol_k=1.5,
        )
        sig = breakout_signal(df, cfg).to_numpy()
        assert -1.0 in sig[40:43]
        assert sig[-1] == 1.0

    def test_no_trade_without_volume(self) -> None:
        """Identical price path but flat volume -> no breakout is confirmed."""
        df = _vol_regime_ohlcv(n=1000)
        df_flat = df.copy()
        df_flat["volume"] = 1_000_000.0
        sig = breakout_signal(df_flat)
        assert (sig != 0.0).sum() == 0

    def test_all_nan_bands_flat(self) -> None:
        df = _ohlcv(np.arange(1.0, 6.0))  # only 5 bars, window 20 -> all NaN
        cfg = BreakoutConfig(band_window=20)
        sig = breakout_signal(df, cfg)
        assert (sig == 0.0).all()


# ---------------------------------------------------------------------------
# Look-ahead-free truncation invariance (CRITICAL)
# ---------------------------------------------------------------------------


class TestTruncationInvariance:
    def test_signal_unchanged_by_future_bars(self) -> None:
        df = _vol_regime_ohlcv(n=1000)
        k = 650
        full = breakout_signal(df).to_numpy()
        pref = breakout_signal(df.iloc[:k]).to_numpy()
        np.testing.assert_array_equal(full[:k], pref)

    def test_invariance_atr_variant(self) -> None:
        df = _vol_regime_ohlcv(n=800)
        cfg = BreakoutConfig(band_window=14, use_atr=True, squeeze_window=30)
        k = 500
        full = breakout_signal(df, cfg).to_numpy()
        pref = breakout_signal(df.iloc[:k], cfg).to_numpy()
        np.testing.assert_array_equal(full[:k], pref)


# ---------------------------------------------------------------------------
# breakout_weights
# ---------------------------------------------------------------------------


class TestBreakoutWeights:
    def test_relabel_of_signal(self) -> None:
        df = _vol_regime_ohlcv(n=400)
        sig = breakout_signal(df)
        w = breakout_weights(df)
        assert w.name == "weight"
        np.testing.assert_array_equal(sig.to_numpy(), w.to_numpy())
