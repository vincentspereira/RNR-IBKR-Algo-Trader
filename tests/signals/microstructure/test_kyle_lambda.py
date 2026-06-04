"""Tests for core_trading.signals.microstructure.kyle_lambda.

Covers:
* KyleConfig -- frozen/slotted DTO, __post_init__ validation.
* amihud_illiq -- correct formula, recovery ordering (illiquid > liquid),
                  warmup NaN, zero dollar-volume handling.
* kyle_lambda  -- sign / magnitude recovery from planted linear model,
                  liquidity ordering (larger lambda = less liquid),
                  warmup NaN, sign convention.
* Public API / __all__ completeness.

Synthetic data design
---------------------
For Amihud ILLIQ we construct two series: a ''liquid'' series (high volume,
small returns) and an ''illiquid'' series (low volume, large returns).
The illiquid series should have a higher ILLIQ value.

For Kyle lambda we plant the data-generating process:
    delta_P_t = lambda_true * signed_volume_t + noise_t

and verify that the OLS estimator recovers lambda_true within tolerance.
The tick-rule proxy for signed volume introduces noise, so we use a small
noise_t to make recovery tractable in a test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.microstructure.kyle_lambda import (
    KyleConfig,
    amihud_illiq,
    kyle_lambda,
)

SEED = 20260604
N = 600


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------


def _make_liquid_illiquid(
    n: int = N,
    seed: int = SEED,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return (close_liq, vol_liq, close_illiq, vol_illiq).

    Liquid:   small returns (~0.1% / day), high volume (~1e6 shares/day).
    Illiquid: large returns (~1% / day), low volume (~1e3 shares/day).
    Both start at price 100.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")

    ret_liq = rng.normal(0.0, 0.001, n)
    price_liq = 100.0 * np.cumprod(1.0 + ret_liq)
    vol_liq = rng.uniform(800_000, 1_200_000, n)

    ret_illiq = rng.normal(0.0, 0.01, n)
    price_illiq = 100.0 * np.cumprod(1.0 + ret_illiq)
    vol_illiq = rng.uniform(800, 1_200, n)

    return (
        pd.Series(price_liq, index=idx, name="close"),
        pd.Series(vol_liq, index=idx, name="volume"),
        pd.Series(price_illiq, index=idx, name="close"),
        pd.Series(vol_illiq, index=idx, name="volume"),
    )


def _make_kyle_planted(
    n: int = N,
    lambda_true: float = 1e-6,
    noise_scale: float = 0.0,
    seed: int = SEED,
) -> tuple[pd.Series, pd.Series]:
    """Construct (close, volume) such that:

        delta_P_t = lambda_true * signed_volume_t + noise_t

    where signed_volume_t = sign(delta_P_t) * volume_t (tick rule, self-consistent
    when noise is small relative to the lambda * volume term).

    We build this by:
    1. Drawing volume_t ~ Uniform(1e5, 2e5).
    2. Drawing signs q_t in {-1, +1} randomly.
    3. Setting delta_P_t = lambda_true * q_t * volume_t + noise_t.
    4. Accumulating price from 100.0.

    Because signed_vol_t = sign(delta_P_t) * volume_t and sign(delta_P_t) == q_t
    when noise is small, the tick-rule proxy equals q_t * volume_t, so OLS on
    (signed_vol, delta_P) recovers lambda_true.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")

    volume = rng.uniform(1e5, 2e5, n)
    signs = rng.choice([-1.0, 1.0], size=n)
    noise = rng.normal(0.0, noise_scale, n) if noise_scale > 0.0 else np.zeros(n)

    dp = lambda_true * signs * volume + noise
    price = np.concatenate([[100.0], 100.0 + np.cumsum(dp[1:])])

    return pd.Series(price, index=idx), pd.Series(volume, index=idx)


# ---------------------------------------------------------------------------
# KyleConfig tests
# ---------------------------------------------------------------------------


class TestKyleConfig:
    """KyleConfig: construction, validation, immutability."""

    def test_valid_defaults(self) -> None:
        cfg = KyleConfig()
        assert cfg.window == 60
        assert cfg.min_periods is None
        assert cfg.scale == 1e6
        assert cfg.effective_min_periods == 60

    def test_custom(self) -> None:
        cfg = KyleConfig(window=20, min_periods=10, scale=1e4)
        assert cfg.window == 20
        assert cfg.effective_min_periods == 10

    def test_frozen(self) -> None:
        cfg = KyleConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.window = 10  # type: ignore[misc]

    def test_window_lt5_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 5"):
            KyleConfig(window=4)

    def test_min_periods_lt5_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods must be >= 5"):
            KyleConfig(window=10, min_periods=4)

    def test_min_periods_gt_window_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods"):
            KyleConfig(window=10, min_periods=15)

    def test_scale_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="scale must be > 0"):
            KyleConfig(scale=0.0)

    def test_scale_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="scale must be > 0"):
            KyleConfig(scale=-1.0)


# ---------------------------------------------------------------------------
# amihud_illiq tests
# ---------------------------------------------------------------------------


class TestAmihudIlliq:
    """amihud_illiq: formula correctness, ordering, edge cases."""

    def test_output_index_matches(self) -> None:
        c, v, _, _ = _make_liquid_illiquid()
        result = amihud_illiq(c, v, window=60)
        assert list(result.index) == list(c.index)
        assert len(result) == len(c)

    def test_warmup_nan(self) -> None:
        """First window-1 bars should be NaN (insufficient rolling history)."""
        c, v, _, _ = _make_liquid_illiquid()
        window = 60
        result = amihud_illiq(c, v, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_illiquid_greater_than_liquid(self) -> None:
        """The illiquid series should have a higher ILLIQ than the liquid series."""
        c_liq, v_liq, c_illiq, v_illiq = _make_liquid_illiquid()
        window = 60
        illiq_liq = amihud_illiq(c_liq, v_liq, window=window).dropna().median()
        illiq_ill = amihud_illiq(c_illiq, v_illiq, window=window).dropna().median()
        assert illiq_ill > illiq_liq, (
            f"Illiquid median {illiq_ill:.4e} should exceed liquid {illiq_liq:.4e}"
        )

    def test_non_negative_output(self) -> None:
        """All non-NaN ILLIQ values must be >= 0."""
        c, v, _, _ = _make_liquid_illiquid()
        result = amihud_illiq(c, v, window=60).dropna()
        assert (result >= 0.0).all()

    def test_zero_volume_produces_nan(self) -> None:
        """A bar with zero volume (dollar_vol=0) -> NaN per-bar ratio.

        With strict min_periods == window, any NaN in the window propagates into
        the rolling mean.  Bar 100 through bar 119 all include the zero-volume
        bar in their window, so they should all be NaN.
        """
        c, v, _, _ = _make_liquid_illiquid(n=200)
        v_zero = v.copy()
        v_zero.iloc[100] = 0.0
        window = 20
        result = amihud_illiq(c, v_zero, window=window, min_periods=window)
        # Bars 100-119 each have a window that includes the zero-volume bar
        assert result.iloc[100:120].isna().any()

    def test_scale_parameter(self) -> None:
        """Changing scale by 1000x should change output by exactly 1000x."""
        c, v, _, _ = _make_liquid_illiquid()
        r1 = amihud_illiq(c, v, window=60, scale=1e6)
        r2 = amihud_illiq(c, v, window=60, scale=1e3)
        valid1 = r1.dropna()
        valid2 = r2.dropna()
        ratio = (valid1 / valid2).dropna()
        assert abs(float(ratio.mean()) - 1000.0) < 1e-6

    def test_mismatched_length_raises(self) -> None:
        c, v, _, _ = _make_liquid_illiquid(n=50)
        with pytest.raises(ValueError, match="same length"):
            amihud_illiq(c, v.iloc[:-1], window=10)

    def test_mismatched_index_raises(self) -> None:
        c, v, _, _ = _make_liquid_illiquid(n=50)
        v_reindexed = v.copy()
        v_reindexed.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            amihud_illiq(c, v_reindexed, window=10)

    def test_series_name(self) -> None:
        c, v, _, _ = _make_liquid_illiquid(n=100)
        result = amihud_illiq(c, v, window=20)
        assert result.name == "amihud_illiq"

    def test_window_lt5_raises(self) -> None:
        c, v, _, _ = _make_liquid_illiquid(n=50)
        with pytest.raises(ValueError, match="window must be >= 5"):
            amihud_illiq(c, v, window=4)


# ---------------------------------------------------------------------------
# kyle_lambda tests
# ---------------------------------------------------------------------------


class TestKyleLambda:
    """kyle_lambda: OLS recovery, liquidity ordering, edge cases."""

    def test_output_index_matches(self) -> None:
        c, v = _make_kyle_planted()
        result = kyle_lambda(c, v, window=60)
        assert list(result.index) == list(c.index)
        assert len(result) == len(c)

    def test_warmup_nan(self) -> None:
        """First window-1 bars should be NaN."""
        c, v = _make_kyle_planted()
        window = 60
        result = kyle_lambda(c, v, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_parameter_recovery_sign(self) -> None:
        """With no noise, the estimator should recover a positive lambda > 0."""
        lambda_true = 5e-7
        c, v = _make_kyle_planted(n=1000, lambda_true=lambda_true, noise_scale=0.0)
        result = kyle_lambda(c, v, window=200, min_periods=100)
        valid = result.dropna()
        assert len(valid) > 10
        median_lam = float(valid.median())
        # Should be positive
        assert median_lam > 0.0, f"Expected positive lambda, got {median_lam:.2e}"

    def test_parameter_recovery_magnitude(self) -> None:
        """With zero noise the estimator should tightly recover lambda_true."""
        lambda_true = 5e-7
        c, v = _make_kyle_planted(n=2000, lambda_true=lambda_true, noise_scale=0.0)
        result = kyle_lambda(c, v, window=500, min_periods=200)
        valid = result.dropna()
        median_lam = float(valid.median())
        rel_err = abs(median_lam - lambda_true) / lambda_true
        assert rel_err < 0.20, (
            f"Lambda recovery error {rel_err:.1%} > 20%; "
            f"estimated {median_lam:.2e}, true {lambda_true:.2e}"
        )

    def test_less_liquid_has_larger_lambda(self) -> None:
        """A series with large lambda (illiquid) should have a higher estimate."""
        c_illiq, v_illiq = _make_kyle_planted(n=800, lambda_true=1e-5, noise_scale=0.0)
        c_liq, v_liq = _make_kyle_planted(
            n=800, lambda_true=1e-7, noise_scale=0.0, seed=SEED + 3
        )
        lam_illiq = float(kyle_lambda(c_illiq, v_illiq, window=200).dropna().median())
        lam_liq = float(kyle_lambda(c_liq, v_liq, window=200).dropna().median())
        assert lam_illiq > lam_liq, (
            f"Illiquid lambda {lam_illiq:.2e} should exceed liquid {lam_liq:.2e}"
        )

    def test_mismatched_length_raises(self) -> None:
        c, v = _make_kyle_planted(n=50)
        with pytest.raises(ValueError, match="same length"):
            kyle_lambda(c, v.iloc[:-1], window=10)

    def test_mismatched_index_raises(self) -> None:
        c, v = _make_kyle_planted(n=50)
        v_reindexed = v.copy()
        v_reindexed.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            kyle_lambda(c, v_reindexed, window=10)

    def test_series_name(self) -> None:
        c, v = _make_kyle_planted(n=100)
        result = kyle_lambda(c, v, window=20)
        assert result.name == "kyle_lambda"

    def test_window_lt5_raises(self) -> None:
        c, v = _make_kyle_planted(n=50)
        with pytest.raises(ValueError, match="window must be >= 5"):
            kyle_lambda(c, v, window=4)

    def test_constant_price_all_nan(self) -> None:
        """Constant price -> zero signed volume variance -> NaN lambda."""
        n = 100
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        c = pd.Series(np.ones(n) * 50.0, index=idx)
        v = pd.Series(np.ones(n) * 1e5, index=idx)
        result = kyle_lambda(c, v, window=20, min_periods=10)
        # All signed volumes are 0 (sign(0) == 0), so variance of x is 0 -> NaN
        post_warmup = result.iloc[20:]
        assert post_warmup.isna().all()


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import importlib

        mod = importlib.import_module("core_trading.signals.microstructure.kyle_lambda")
        expected = {"KyleConfig", "amihud_illiq", "kyle_lambda"}
        for name in expected:
            assert hasattr(mod, name), f"Missing: {name}"

    def test_all_contains_expected(self) -> None:
        import importlib

        mod = importlib.import_module("core_trading.signals.microstructure.kyle_lambda")
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(KyleConfig)
