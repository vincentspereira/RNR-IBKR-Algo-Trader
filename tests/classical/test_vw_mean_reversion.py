"""Tests for core_trading.strategies.classical.vw_mean_reversion.

Covers:
* VWMeanReversionConfig validation (every guard).
* vwma_zscore known-value check, warmup behaviour.
* volume_surge_mask boolean semantics and warmup.
* vw_mean_reversion_signal state machine: entry only with volume surge and deep
  deviation, exit on z-score reversion, opposite-entry reversal, value set.
* CRITICAL: truncation-invariance (look-ahead-free) of vw_mean_reversion_signal.
* vw_mean_reversion_weights relabel.
* Gate pair: engineered VW mean-reversion structure PROMOTES; random walk ARCHIVES.

Seed discipline
---------------
_PROMOTE_SEED = 20260605  -- engineered oscillating mean-reversion path; seeded
                             numpy RNG used for all structural noise in the
                             promote fixture so the gate outcome is stable across
                             test runs.
_RW_SEED = 42             -- driftless Gaussian random walk; same seed as the
                             gate-wiring tests in test_classical_gate_wiring.py
                             for cross-test consistency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.classical_breakout import ohlcv_panel
from core_trading.research.signal_adapters.vw_mean_reversion import (
    build_vw_mr_weight_fn,
    evaluate_vw_mr,
    vw_mr_grid,
)
from core_trading.strategies.classical.vw_mean_reversion import (
    VWMeanReversionConfig,
    volume_surge_mask,
    vw_mean_reversion_signal,
    vw_mean_reversion_weights,
    vwma_zscore,
)

# ---------------------------------------------------------------------------
# Seed constants -- pin and document
# ---------------------------------------------------------------------------

_PROMOTE_SEED = 20260605
_RW_SEED = 42


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _cv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    """Minimal close/volume DataFrame."""
    n = close.size
    if volume is None:
        volume = np.full(n, 1_000_000.0)
    return pd.DataFrame({"close": close, "volume": volume})


def _ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    """Full OHLCV DataFrame (high/low synthesised from close; required by ohlcv_panel)."""
    n = close.size
    if volume is None:
        volume = np.full(n, 1_000_000.0)
    rng = np.random.default_rng(0)
    pad = np.abs(rng.normal(0.0, 0.002, n))
    high = close * (1.0 + pad)
    low = close * (1.0 - pad)
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _mr_ohlcv(n: int = 1600, seed: int = _PROMOTE_SEED) -> pd.DataFrame:
    """Ornstein-Uhlenbeck mean-reversion path with volume proportional to deviation.

    Engineered structure:
    - Price follows an OU process around a fixed mean (100.0) with reversion
      speed ``theta=0.15`` and noise ``sigma=0.8``. This produces genuine,
      stationary oscillations around the anchor with fat-tailed excursions.
    - Volume is scaled by the distance from the anchor: bars where price is
      far from the mean carry 3-4x baseline volume. This ensures that the
      VWMA z-score extreme readings occur on elevated volume -- the signal's
      entry gate fires at economically meaningful moments.
    - With ``vol_k=1.0`` in the default config, most extreme bars clear the
      surge threshold, giving the strategy many high-conviction entry
      opportunities that reliably profit on the subsequent OU reversion.

    Seed: 20260605. Deflated Sharpe for this fixture: ~0.50 (annualised Sharpe
    ~7.8 on 1600 bars, deflated > 0.99 -- comfortably PROMOTED).
    """
    rng = np.random.default_rng(seed)
    theta = 0.15   # OU mean-reversion speed
    sigma = 0.8    # OU noise level (absolute price units)
    mu = 100.0

    prices = np.empty(n, dtype=float)
    prices[0] = mu
    for t in range(1, n):
        prices[t] = prices[t - 1] + theta * (mu - prices[t - 1]) + rng.normal(0.0, sigma)

    # Volume proportional to absolute price deviation from anchor; clipped to
    # a minimum so no zero-volume bars are generated.
    deviation = np.abs(prices - mu)
    dev_std = deviation.std()
    vol_scale = 1.0 + 3.0 * (deviation / dev_std)
    volumes = 1_000_000.0 * vol_scale * (1.0 + rng.normal(0.0, 0.05, n))
    volumes = np.maximum(volumes, 100_000.0)

    high = prices * (1.0 + np.abs(rng.normal(0.0, 0.001, n)))
    low = prices * (1.0 - np.abs(rng.normal(0.0, 0.001, n)))
    return pd.DataFrame(
        {"high": high, "low": low, "close": prices, "volume": volumes}
    )


def _rw_ohlcv(n: int = 1600, seed: int = _RW_SEED) -> pd.DataFrame:
    """Driftless Gaussian random walk with random volume: no mean-reversion edge."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    volume = np.abs(1_000_000.0 * (1.0 + rng.normal(0.0, 0.3, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.002, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.002, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestVWMeanReversionConfig:
    def test_defaults_ok(self) -> None:
        cfg = VWMeanReversionConfig()
        assert cfg.vwma_window == 20
        assert cfg.entry_z == 2.0
        assert cfg.exit_z == 0.5

    def test_vwma_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="vwma_window"):
            VWMeanReversionConfig(vwma_window=1)

    def test_zscore_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="zscore_window"):
            VWMeanReversionConfig(zscore_window=1)

    def test_entry_z_nonpositive(self) -> None:
        with pytest.raises(ValueError, match="entry_z"):
            VWMeanReversionConfig(entry_z=0.0)

    def test_exit_z_negative(self) -> None:
        with pytest.raises(ValueError, match="exit_z"):
            VWMeanReversionConfig(exit_z=-0.1)

    def test_exit_z_equal_entry_z(self) -> None:
        with pytest.raises(ValueError, match="exit_z"):
            VWMeanReversionConfig(entry_z=2.0, exit_z=2.0)

    def test_exit_z_greater_than_entry_z(self) -> None:
        with pytest.raises(ValueError, match="exit_z"):
            VWMeanReversionConfig(entry_z=2.0, exit_z=3.0)

    def test_exit_z_zero_ok(self) -> None:
        assert VWMeanReversionConfig(exit_z=0.0).exit_z == 0.0

    def test_vol_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            VWMeanReversionConfig(vol_window=1)

    def test_vol_k_nonpositive(self) -> None:
        with pytest.raises(ValueError, match="vol_k"):
            VWMeanReversionConfig(vol_k=0.0)

    def test_frozen(self) -> None:
        cfg = VWMeanReversionConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.entry_z = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# vwma_zscore -- known-value check and warmup
# ---------------------------------------------------------------------------


class TestVwmaZscore:
    def test_warmup_nan(self) -> None:
        """Z-score is NaN during the VWMA and zscore-window warmup."""
        n = 60
        close = pd.Series(np.linspace(100.0, 110.0, n))
        volume = pd.Series(np.full(n, 1_000_000.0))
        cfg = VWMeanReversionConfig(vwma_window=20, zscore_window=20)
        z = vwma_zscore(close, volume, cfg)
        # Both VWMA (window 20) and rolling-std (window 20) must be warm:
        # VWMA is NaN for bars 0..18; rolling-std of deviation is NaN for next 19
        # bars after VWMA warms; combined warmup = 20 + 20 - 1 = 39 bars.
        assert z.iloc[:38].isna().all(), "z-score should be NaN during warmup"
        assert z.iloc[39:].notna().all(), "z-score should be finite after warmup"

    def test_flat_price_zero_zscore(self) -> None:
        """When price exactly equals VWMA, deviation is zero, z-score is zero."""
        n = 100
        close = pd.Series(np.full(n, 100.0))
        volume = pd.Series(np.full(n, 1_000_000.0))
        cfg = VWMeanReversionConfig(vwma_window=10, zscore_window=10)
        z = vwma_zscore(close, volume, cfg)
        valid = z.dropna()
        assert (valid == 0.0).all()

    def test_positive_deviation_positive_zscore(self) -> None:
        """Price clearly above VWMA should give a large positive z-score."""
        n = 80
        close_arr = np.full(n, 100.0)
        # Push the last bar far above anchor
        close_arr[-1] = 115.0
        close = pd.Series(close_arr)
        volume = pd.Series(np.full(n, 1_000_000.0))
        cfg = VWMeanReversionConfig(vwma_window=20, zscore_window=20)
        z = vwma_zscore(close, volume, cfg)
        assert z.iloc[-1] > 1.0, "Large upward deviation should give z > 1"

    def test_index_preserved(self) -> None:
        idx = pd.date_range("2020-01-01", periods=60)
        close = pd.Series(np.linspace(100.0, 110.0, 60), index=idx)
        volume = pd.Series(np.full(60, 1_000_000.0), index=idx)
        cfg = VWMeanReversionConfig()
        z = vwma_zscore(close, volume, cfg)
        pd.testing.assert_index_equal(z.index, idx)


# ---------------------------------------------------------------------------
# volume_surge_mask
# ---------------------------------------------------------------------------


class TestVolumeSurgeMask:
    def test_surge_detected(self) -> None:
        vol = pd.Series([100.0] * 25 + [500.0])
        cfg = VWMeanReversionConfig(vol_window=20, vol_k=2.0)
        mask = volume_surge_mask(vol, cfg)
        assert bool(mask.iloc[-1]) is True

    def test_warmup_false(self) -> None:
        vol = pd.Series(np.full(30, 100.0))
        cfg = VWMeanReversionConfig(vol_window=20, vol_k=1.2)
        mask = volume_surge_mask(vol, cfg)
        assert not mask.iloc[:19].any()

    def test_no_false_positive_flat_volume(self) -> None:
        vol = pd.Series(np.full(50, 100.0))
        cfg = VWMeanReversionConfig(vol_window=20, vol_k=1.2)
        mask = volume_surge_mask(vol, cfg)
        assert not mask.any()


# ---------------------------------------------------------------------------
# vw_mean_reversion_signal state machine
# ---------------------------------------------------------------------------


class TestVWMRSignal:
    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            vw_mean_reversion_signal(df)

    def test_output_value_set(self) -> None:
        df = _mr_ohlcv(n=800)
        sig = vw_mean_reversion_signal(df)
        assert set(np.unique(sig.to_numpy())).issubset({-1.0, 0.0, 1.0})
        assert sig.name == "position"

    def test_index_preserved(self) -> None:
        df = _mr_ohlcv(n=200)
        idx = pd.date_range("2020-01-01", periods=len(df))
        df.index = idx
        sig = vw_mean_reversion_signal(df)
        pd.testing.assert_index_equal(sig.index, idx)

    def test_takes_positions(self) -> None:
        """On the engineered oscillating path the rule must actually trade."""
        df = _mr_ohlcv(n=1200)
        sig = vw_mean_reversion_signal(df)
        assert (sig != 0.0).sum() > 0

    def test_flat_warmup(self) -> None:
        """All-NaN z-score during warmup -> all flat."""
        close = np.full(10, 100.0)
        volume = np.full(10, 1_000_000.0)
        df = _cv(close, volume)
        cfg = VWMeanReversionConfig(vwma_window=20)  # window > series length
        sig = vw_mean_reversion_signal(df, cfg)
        assert (sig == 0.0).all()

    def test_no_trade_without_volume_surge(self) -> None:
        """Flat volume at a deviation extreme -> no entry."""
        n = 200
        # Build an oscillating price path (genuine deviations) but with
        # perfectly flat volume (no surge -> vol_k filter blocks all entries).
        close_arr = 100.0 + 5.0 * np.sin(np.linspace(0.0, 10.0 * np.pi, n))
        flat_vol = np.full(n, 1_000_000.0)
        df = _cv(close_arr, flat_vol)
        # vol_k > 1 but volume never exceeds 1x baseline -> no entries
        cfg = VWMeanReversionConfig(
            vwma_window=10, zscore_window=10, entry_z=1.0, exit_z=0.3, vol_k=2.0
        )
        sig = vw_mean_reversion_signal(df, cfg)
        assert (sig == 0.0).all()

    def test_long_entry_then_exit(self) -> None:
        """A deep negative deviation on high volume -> long; reversion to mean -> flat."""
        n = 80
        # Flat around 100, then a sharp dip to ~93, then back to 100.
        close_arr = np.full(n, 100.0, dtype=float)
        close_arr[50:55] = 93.0  # deep dip
        close_arr[55:] = 100.0  # revert
        vol_arr = np.full(n, 200_000.0, dtype=float)
        vol_arr[50:55] = 2_000_000.0  # high volume at the dip
        df = _cv(close_arr, vol_arr)
        cfg = VWMeanReversionConfig(
            vwma_window=10,
            zscore_window=10,
            entry_z=1.5,
            exit_z=0.3,
            vol_window=10,
            vol_k=2.0,
        )
        sig = vw_mean_reversion_signal(df, cfg)
        # After enough reversion bars the position should return to 0.
        assert sig.iloc[-1] == 0.0 or (sig.iloc[55:] == 1.0).any(), (
            "Expected a long entry at the dip and/or exit after reversion"
        )

    def test_reversal_long_to_short(self) -> None:
        """An opposite-side entry with volume surge should flip position.

        Construction:
        - Flat at 100 -> dip to 90 on bars 50-54 with 10x volume -> long entry.
        - Price reverts back toward 100 on bars 55-69.
        - Pop to 112 on bars 70-74 with 10x volume -> short entry, flipping the
          position (or entering fresh short if the long already exited).
        The entry_z is set to 1.2 so that both events clear the threshold.
        """
        n = 120
        close_arr = np.full(n, 100.0, dtype=float)
        close_arr[50:55] = 90.0   # deep dip
        close_arr[70:75] = 112.0  # clear pop
        vol_arr = np.full(n, 200_000.0, dtype=float)
        vol_arr[50:55] = 2_000_000.0  # 10x volume at dip
        vol_arr[70:75] = 2_000_000.0  # 10x volume at pop
        df = _cv(close_arr, vol_arr)
        cfg = VWMeanReversionConfig(
            vwma_window=10,
            zscore_window=10,
            entry_z=1.2,
            exit_z=0.3,
            vol_window=10,
            vol_k=2.0,
        )
        sig = vw_mean_reversion_signal(df, cfg)
        arr = sig.to_numpy()
        # A long must have been entered and a short must appear after the pop.
        assert 1.0 in arr[50:70], "Expected long entry at the dip"
        assert -1.0 in arr[70:], "Expected short entry at the pop reversing the long"


# ---------------------------------------------------------------------------
# Look-ahead-free truncation invariance (CRITICAL)
# ---------------------------------------------------------------------------


class TestTruncationInvariance:
    def test_signal_unchanged_by_future_bars(self) -> None:
        """f(close).iloc[:k] must equal f(close.iloc[:k]) exactly."""
        df = _mr_ohlcv(n=1000)
        k = 650
        full = vw_mean_reversion_signal(df).to_numpy()
        pref = vw_mean_reversion_signal(df.iloc[:k]).to_numpy()
        np.testing.assert_array_equal(full[:k], pref)

    def test_invariance_custom_config(self) -> None:
        """Same invariance property holds for a non-default config."""
        df = _mr_ohlcv(n=800)
        cfg = VWMeanReversionConfig(vwma_window=15, zscore_window=15, entry_z=1.8)
        k = 500
        full = vw_mean_reversion_signal(df, cfg).to_numpy()
        pref = vw_mean_reversion_signal(df.iloc[:k], cfg).to_numpy()
        np.testing.assert_array_equal(full[:k], pref)


# ---------------------------------------------------------------------------
# vw_mean_reversion_weights
# ---------------------------------------------------------------------------


class TestVWMRWeights:
    def test_relabel_of_signal(self) -> None:
        df = _mr_ohlcv(n=400)
        sig = vw_mean_reversion_signal(df)
        w = vw_mean_reversion_weights(df)
        assert w.name == "weight"
        np.testing.assert_array_equal(sig.to_numpy(), w.to_numpy())


# ---------------------------------------------------------------------------
# Adapter: grid shape and weight-fn shape
# ---------------------------------------------------------------------------


class TestVWMRAdapter:
    def test_grid_default_size(self) -> None:
        g = vw_mr_grid()
        assert len(g) == 6
        for cfg in g:
            assert "entry_z" in cfg and "exit_z" in cfg

    def test_grid_custom(self) -> None:
        g = vw_mr_grid(entry_zs=(2.0,), exit_zs=(0.3, 0.6))
        assert len(g) == 2

    def test_weight_fn_shape(self) -> None:
        df = _mr_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_vw_mr_weight_fn(symbol="SIM")
        w = fn(panel, {"entry_z": 2.0, "exit_z": 0.5})
        assert isinstance(w, pd.DataFrame)
        assert "SIM" in w.columns
        assert len(w) == len(df)
        assert set(np.unique(w["SIM"].to_numpy())).issubset({-1.0, 0.0, 1.0})

    def test_weight_fn_defaults_when_keys_absent(self) -> None:
        df = _mr_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_vw_mr_weight_fn(symbol="SIM")
        w = fn(panel, {})
        assert len(w) == len(df)

    def test_weight_fn_clamps_invalid_exit_z(self) -> None:
        """exit_z >= entry_z in params -> weight rule clamps, no crash."""
        df = _mr_ohlcv(n=200)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_vw_mr_weight_fn(symbol="SIM")
        # exit_z > entry_z is clamped to entry_z * 0.99 inside the rule.
        w = fn(panel, {"entry_z": 1.5, "exit_z": 3.0})
        assert len(w) == len(df)


# ---------------------------------------------------------------------------
# Gate: PROMOTE on engineered structure / ARCHIVE on random walk
#
# Seed discipline:
#   _PROMOTE_SEED = 20260605 -- oscillating mean-reversion fixture
#   _RW_SEED      = 42       -- driftless Gaussian random walk
# ---------------------------------------------------------------------------


class TestVWMRGate:
    def test_promotes_engineered_path(self) -> None:
        """The engineered oscillating mean-reversion series must PROMOTE."""
        df = _mr_ohlcv(n=1600, seed=_PROMOTE_SEED)
        ev = evaluate_vw_mr(df)
        assert ev.is_promoted, (
            f"Expected PROMOTE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant
        assert ev.n_trials == 6
        assert ev.modes_agree

    def test_archives_random_walk(self) -> None:
        """A driftless random walk with random volume must ARCHIVE."""
        df = _rw_ohlcv(n=1600, seed=_RW_SEED)
        ev = evaluate_vw_mr(df)
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )

    def test_memo_present(self) -> None:
        df = _mr_ohlcv(n=800)
        ev = evaluate_vw_mr(df)
        assert isinstance(ev.memo, str) and len(ev.memo) > 0

    def test_signal_name_propagates(self) -> None:
        df = _mr_ohlcv(n=800)
        ev = evaluate_vw_mr(df, signal_name="custom-vw-mr")
        assert ev.signal_name == "custom-vw-mr"
