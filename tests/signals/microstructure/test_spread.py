"""Tests for core_trading.signals.microstructure.spread.

Covers:
* SpreadConfig -- frozen/slotted DTO, __post_init__ validation.
* roll_spread  -- parameter recovery from simulated bid-ask bounce; NaN when
                  autocovariance is non-negative; warmup NaN behaviour.
* corwin_schultz_spread -- parameter recovery from simulated bounce; zero floor
                           when alpha <= 0; first-bar NaN; NaN input propagation.
* Public API / __all__ completeness.

Synthetic data convention
--------------------------
The Roll model assumes the observed price is efficient midprice +/- half-spread
bouncing with each trade direction.  We simulate:

    efficient[t] = GBM random walk (sigma_eff small)
    observed[t]  = efficient[t] + q[t] * half_spread

where q[t] alternates between +1 and -1 (deterministic bounce) and
half_spread = s/2.  Under this model cov(dP_t, dP_{t-1}) = -s^2/4 so
Roll recovers s = 2*sqrt(s^2/4) = s exactly.

For Corwin-Schultz we construct OHLC bars consistent with a known spread s
and verify the estimator is in the right ballpark.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.microstructure.spread import (
    SpreadConfig,
    corwin_schultz_spread,
    roll_spread,
)

SEED = 20260604
N = 500  # enough bars for the rolling window to warm up


# ---------------------------------------------------------------------------
# Synthetic price factories
# ---------------------------------------------------------------------------


def _make_bounce_prices(
    n: int = N,
    half_spread: float = 0.05,
    sigma_eff: float = 0.001,
    seed: int = SEED,
) -> pd.Series:
    """Simulate observed close prices from a GBM midprice plus bid-ask bounce.

    The efficient price follows a log-random-walk with daily vol sigma_eff.
    Trade direction is i.i.d. uniform in {-1, +1} (the standard Roll model
    assumption).  Under i.i.d. direction:

        cov(dP_t, dP_{t-1}) = -(half_spread)^2

    so Roll's formula recovers spread = 2*half_spread exactly in expectation.
    observed_t = midprice_t + sign_t * half_spread.
    """
    rng = np.random.default_rng(seed)
    mid = np.ones(n)
    for i in range(1, n):
        mid[i] = mid[i - 1] * np.exp(rng.normal(0.0, sigma_eff))
    signs = rng.choice([-1.0, 1.0], size=n)
    observed = mid + signs * half_spread
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(observed, index=idx, name="close")


def _make_ohlc_bounce(
    n: int = N,
    half_spread: float = 0.05,
    sigma_eff: float = 0.001,
    seed: int = SEED,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Simulate OHLC bars consistent with a known spread and GBM midprice.

    High = midprice + half_spread + small intraday excursion
    Low  = midprice - half_spread - small intraday excursion
    Open = midprice (no gap)
    Close = midprice + i.i.d. random sign * half_spread (Roll bounce)
    """
    rng = np.random.default_rng(seed)
    mid = np.ones(n)
    for i in range(1, n):
        mid[i] = mid[i - 1] * np.exp(rng.normal(0.0, sigma_eff))

    excursion = np.abs(rng.normal(0.0, sigma_eff * 0.5, size=n))
    high = mid + half_spread + excursion
    low = mid - half_spread - excursion
    # Clamp low to be positive
    low = np.maximum(low, 1e-4)

    signs = rng.choice([-1.0, 1.0], size=n)
    close = mid + signs * half_spread
    open_ = mid.copy()

    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return (
        pd.Series(open_, index=idx, name="open"),
        pd.Series(high, index=idx, name="high"),
        pd.Series(low, index=idx, name="low"),
        pd.Series(close, index=idx, name="close"),
    )


# ---------------------------------------------------------------------------
# SpreadConfig tests
# ---------------------------------------------------------------------------


class TestSpreadConfig:
    """SpreadConfig: construction, validation, immutability."""

    def test_valid_defaults(self) -> None:
        cfg = SpreadConfig()
        assert cfg.window == 60
        assert cfg.min_periods is None
        assert cfg.effective_min_periods == 60

    def test_custom_construction(self) -> None:
        cfg = SpreadConfig(window=20, min_periods=10)
        assert cfg.window == 20
        assert cfg.effective_min_periods == 10

    def test_frozen(self) -> None:
        cfg = SpreadConfig(window=20)
        with pytest.raises((AttributeError, TypeError)):
            cfg.window = 5  # type: ignore[misc]

    def test_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 2"):
            SpreadConfig(window=1)

    def test_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 2"):
            SpreadConfig(window=0)

    def test_min_periods_gt_window_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods"):
            SpreadConfig(window=10, min_periods=20)

    def test_min_periods_one_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods must be >= 2"):
            SpreadConfig(window=10, min_periods=1)

    def test_window_two_allowed(self) -> None:
        cfg = SpreadConfig(window=2, min_periods=2)
        assert cfg.window == 2


# ---------------------------------------------------------------------------
# roll_spread tests
# ---------------------------------------------------------------------------


class TestRollSpread:
    """roll_spread: recovery, NaN conventions, validation."""

    def test_output_index_matches(self) -> None:
        close = _make_bounce_prices()
        result = roll_spread(close, window=100)
        assert list(result.index) == list(close.index)
        assert len(result) == len(close)

    def test_warmup_nan(self) -> None:
        """First window-1 bars must be NaN."""
        close = _make_bounce_prices()
        window = 100
        result = roll_spread(close, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_parameter_recovery(self) -> None:
        """Roll estimator should recover the known spread within 30%."""
        true_spread = 0.10  # $0.10
        half_spread = true_spread / 2.0
        close = _make_bounce_prices(n=2000, half_spread=half_spread, sigma_eff=0.0005)
        result = roll_spread(close, window=200, min_periods=100)
        # Use only fully-warmed-up values
        valid = result.dropna()
        assert len(valid) > 50, "Not enough valid estimates"
        median_est = float(valid.median())
        # Allow 30% relative tolerance -- Roll is a noisy estimator
        assert abs(median_est - true_spread) / true_spread < 0.30, (
            f"Roll recovered {median_est:.4f}, expected ~{true_spread:.4f}"
        )

    def test_non_negative_covariance_produces_nan(self) -> None:
        """A purely trending price series (positive autocov) -> all NaN after warmup."""
        # Strictly increasing prices: dP always positive -> cov(dP_t, dP_{t-1}) > 0
        n = 200
        prices = pd.Series(
            np.arange(1.0, n + 1.0),
            index=pd.date_range("2020-01-01", periods=n, freq="B"),
        )
        result = roll_spread(prices, window=20, min_periods=20)
        post_warmup = result.iloc[20:]
        assert post_warmup.isna().all(), (
            "Expected all NaN for perfectly trending prices; got some finite values"
        )

    def test_no_negative_output_values(self) -> None:
        """All non-NaN spread estimates should be >= 0."""
        close = _make_bounce_prices()
        result = roll_spread(close, window=60)
        valid = result.dropna()
        assert (valid >= 0.0).all(), "Negative spread estimate encountered"

    def test_nan_input_propagates(self) -> None:
        """NaN in close produces NaN outputs in the affected windows."""
        close = _make_bounce_prices(n=300)
        close_nan = close.copy()
        close_nan.iloc[150] = float("nan")
        result = roll_spread(close_nan, window=60)
        # At least some windows around bar 150 should be NaN
        assert result.iloc[150:210].isna().any()

    def test_window_lt2_raises(self) -> None:
        close = _make_bounce_prices(n=50)
        with pytest.raises(ValueError, match="window must be >= 2"):
            roll_spread(close, window=1)

    def test_min_periods_gt_window_raises(self) -> None:
        close = _make_bounce_prices(n=50)
        with pytest.raises(ValueError, match="min_periods"):
            roll_spread(close, window=10, min_periods=20)

    def test_series_name(self) -> None:
        close = _make_bounce_prices(n=100)
        result = roll_spread(close, window=20)
        assert result.name == "roll_spread"

    def test_more_liquid_has_smaller_spread(self) -> None:
        """A series with a smaller bounce should produce a smaller Roll estimate."""
        large_bounce = _make_bounce_prices(n=1000, half_spread=0.10, sigma_eff=0.0002)
        small_bounce = _make_bounce_prices(n=1000, half_spread=0.01, sigma_eff=0.0002, seed=SEED + 1)
        r_large = roll_spread(large_bounce, window=200).dropna().median()
        r_small = roll_spread(small_bounce, window=200).dropna().median()
        assert r_large > r_small, (
            f"Large bounce spread {r_large:.4f} should exceed small bounce {r_small:.4f}"
        )


# ---------------------------------------------------------------------------
# corwin_schultz_spread tests
# ---------------------------------------------------------------------------


class TestCorwinSchultzSpread:
    """corwin_schultz_spread: recovery, NaN conventions, validation."""

    def test_output_index_matches(self) -> None:
        _, high, low, _ = _make_ohlc_bounce()
        result = corwin_schultz_spread(high, low)
        assert list(result.index) == list(high.index)
        assert len(result) == len(high)

    def test_first_bar_is_nan(self) -> None:
        """The very first bar is always NaN (requires a previous bar)."""
        _, high, low, _ = _make_ohlc_bounce(n=50)
        result = corwin_schultz_spread(high, low)
        assert math.isnan(result.iloc[0])

    def test_non_negative_output(self) -> None:
        """All non-NaN estimates should be in [0, 1)."""
        _, high, low, _ = _make_ohlc_bounce()
        result = corwin_schultz_spread(high, low)
        valid = result.dropna()
        assert (valid >= 0.0).all()
        assert (valid < 1.0).all()

    def test_parameter_recovery_ballpark(self) -> None:
        """CS estimator should return positive spread for bouncing prices."""
        _, high, low, _ = _make_ohlc_bounce(n=2000, half_spread=0.10, sigma_eff=0.0005)
        result = corwin_schultz_spread(high, low)
        valid = result.dropna()
        # Mean estimate should be positive (we have a real spread)
        assert float(valid.mean()) > 0.0, "Expected positive CS spread for non-zero half-spread"

    def test_larger_spread_gives_larger_estimate(self) -> None:
        """Larger bounce half-spread -> larger CS estimate on average."""
        _, h_large, l_large, _ = _make_ohlc_bounce(n=1000, half_spread=0.20, sigma_eff=0.0003)
        _, h_small, l_small, _ = _make_ohlc_bounce(
            n=1000, half_spread=0.02, sigma_eff=0.0003, seed=SEED + 7
        )
        mean_large = float(corwin_schultz_spread(h_large, l_large).dropna().mean())
        mean_small = float(corwin_schultz_spread(h_small, l_small).dropna().mean())
        assert mean_large > mean_small, (
            f"Large spread {mean_large:.4f} should exceed small spread {mean_small:.4f}"
        )

    def test_zero_floor_when_alpha_nonpositive(self) -> None:
        """When alpha <= 0 (very narrow range), output is 0, not NaN."""
        # Construct bars where high == low (zero intraday range -> beta=gamma=0 -> alpha<0)
        n = 20
        prices = pd.Series(
            np.linspace(100.0, 101.0, n),
            index=pd.date_range("2020-01-01", periods=n, freq="B"),
        )
        # high == low == close means beta=0, gamma=0, alpha<0
        result = corwin_schultz_spread(prices, prices)
        # Every non-first bar should be 0 (zero floor, not NaN)
        post_first = result.iloc[1:]
        assert (post_first == 0.0).all(), (
            f"Expected all zeros for zero-range OHLC; got {post_first.values}"
        )

    def test_nan_high_propagates(self) -> None:
        """NaN in high -> NaN in result for that bar and the next."""
        _, high, low, _ = _make_ohlc_bounce(n=100)
        high_nan = high.copy()
        high_nan.iloc[50] = float("nan")
        result = corwin_schultz_spread(high_nan, low)
        # Bar 50 and bar 51 both reference bar 50 in their two-day window
        assert math.isnan(result.iloc[50])
        assert math.isnan(result.iloc[51])

    def test_mismatched_length_raises(self) -> None:
        _, high, low, _ = _make_ohlc_bounce(n=50)
        with pytest.raises(ValueError, match="same length"):
            corwin_schultz_spread(high, low.iloc[:-1])

    def test_mismatched_index_raises(self) -> None:
        _, high, low, _ = _make_ohlc_bounce(n=50)
        low_reindexed = low.copy()
        low_reindexed.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            corwin_schultz_spread(high, low_reindexed)

    def test_series_name(self) -> None:
        _, high, low, _ = _make_ohlc_bounce(n=50)
        result = corwin_schultz_spread(high, low)
        assert result.name == "cs_spread"

    def test_nonpositive_prices_produce_nan(self) -> None:
        """Bars with non-positive high or low -> NaN spread at that bar."""
        _, high, low, _ = _make_ohlc_bounce(n=50)
        high_bad = high.copy()
        high_bad.iloc[10] = 0.0
        result = corwin_schultz_spread(high_bad, low)
        # Bar 10 has invalid high -> NaN; bar 11 references bar 10 -> NaN too
        assert math.isnan(result.iloc[10])
        assert math.isnan(result.iloc[11])


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.microstructure.spread as mod

        expected = {"SpreadConfig", "roll_spread", "corwin_schultz_spread"}
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected(self) -> None:
        import core_trading.signals.microstructure.spread as mod

        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(SpreadConfig)
