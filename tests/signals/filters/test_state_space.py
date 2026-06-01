"""Tests for core_trading.signals.filters.state_space (Phase 5.A.3).

Covers:
* StateSpaceResult -- frozen dataclass contract; forecast shape.
* fit_local_level -- AIC/loglik finite; params populated.
* fit_local_linear_trend -- slope recovery on simulated drift series.
* fit_basic_structural -- seasonal decomposition on trend+sine series.
* fit_unobserved_components -- flexible interface; level+cycle.
* forecast() -- shape (steps,); continuity near last level; no NaN.
* ValueError guards -- too-short series; bad seasonal_periods; bad steps.
* TestPublicAPI -- package re-exports.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.filters.state_space import (
    StateSpaceResult,
    fit_basic_structural,
    fit_local_level,
    fit_local_linear_trend,
    fit_unobserved_components,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEED = 20240602
N_TREND = 300    # length for trend-recovery tests
N_SEAS = 200     # length for seasonal tests (>= 2 * seasonal_periods)


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _trend_series(
    n: int = N_TREND,
    slope: float = 0.05,
    noise_std: float = 0.5,
    seed: int = SEED,
) -> pd.Series:
    """Simulate a series with a constant drift slope + Gaussian noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    y = slope * t + rng.normal(0.0, noise_std, size=n)
    return pd.Series(y)


def _seasonal_trend_series(
    n: int = N_SEAS,
    seasonal_periods: int = 12,
    slope: float = 0.02,
    seasonal_amp: float = 2.0,
    noise_std: float = 0.1,
    seed: int = SEED,
) -> tuple[pd.Series, np.ndarray, np.ndarray]:
    """Simulate trend + clean seasonal + noise.

    Returns (series, true_trend, true_seasonal).
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    trend = slope * t
    seasonal = seasonal_amp * np.sin(2.0 * np.pi * t / seasonal_periods)
    y = trend + seasonal + rng.normal(0.0, noise_std, size=n)
    return pd.Series(y), trend, seasonal


# ---------------------------------------------------------------------------
# StateSpaceResult contract
# ---------------------------------------------------------------------------


class TestStateSpaceResult:
    """StateSpaceResult frozen dataclass and forecast method."""

    def test_is_frozen(self) -> None:
        r = StateSpaceResult(level=np.zeros(10))
        with pytest.raises((AttributeError, TypeError)):
            r.loglikelihood = 0.0  # type: ignore[misc]

    def test_default_empty_components(self) -> None:
        r = StateSpaceResult(level=np.ones(5))
        assert r.trend.size == 0
        assert r.seasonal.size == 0
        assert r.cycle.size == 0

    def test_forecast_raises_on_none_result(self) -> None:
        r = StateSpaceResult(level=np.ones(5), _fitted_result=None)
        with pytest.raises(AttributeError, match="_fitted_result"):
            r.forecast(5)

    def test_forecast_raises_bad_steps(self) -> None:
        """steps < 1 raises ValueError."""
        # Use a real fitted result to get past the None check
        y = _trend_series(n=50)
        res = fit_local_level(y)
        with pytest.raises(ValueError, match="steps"):
            res.forecast(0)


# ---------------------------------------------------------------------------
# fit_local_level
# ---------------------------------------------------------------------------


class TestFitLocalLevel:
    """fit_local_level basic contract tests."""

    def test_returns_state_space_result(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert isinstance(res, StateSpaceResult)

    def test_level_shape(self) -> None:
        n = 80
        y = _trend_series(n=n)
        res = fit_local_level(y)
        assert res.level.shape == (n,)

    def test_level_finite(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert np.all(np.isfinite(res.level))

    def test_loglikelihood_finite(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert np.isfinite(res.loglikelihood)

    def test_aic_finite(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert np.isfinite(res.aic)

    def test_params_populated(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert len(res.params) > 0
        for v in res.params.values():
            assert isinstance(v, float)

    def test_trend_and_seasonal_empty(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        assert res.trend.size == 0
        assert res.seasonal.size == 0

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            fit_local_level(pd.Series([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# fit_local_linear_trend
# ---------------------------------------------------------------------------


class TestFitLocalLinearTrend:
    """fit_local_linear_trend recovers a constant slope on simulated data."""

    def test_returns_state_space_result(self) -> None:
        y = _trend_series(n=150)
        res = fit_local_linear_trend(y)
        assert isinstance(res, StateSpaceResult)

    def test_level_and_trend_populated(self) -> None:
        n = N_TREND
        y = _trend_series(n=n)
        res = fit_local_linear_trend(y)
        assert res.level.shape == (n,)
        assert res.trend.shape == (n,)

    def test_level_tracks_trend(self) -> None:
        """The smoothed level should track the true linear trend closely."""
        slope = 0.05
        n = N_TREND
        y = _trend_series(n=n, slope=slope, noise_std=0.5)
        res = fit_local_linear_trend(y)
        true_trend = slope * np.arange(n, dtype=float)
        # Level should be close to true trend over the middle of the series
        mid = slice(n // 4, 3 * n // 4)
        corr = float(np.corrcoef(res.level[mid], true_trend[mid])[0, 1])
        assert corr > 0.98, f"level-trend correlation={corr:.3f}"

    def test_slope_recovery_trend_component(self) -> None:
        """The mean trend (slope) component should be close to the true slope.

        The local-linear-trend state[1] is the slope nu_t.  For a nearly
        constant-slope process the mean of nu_t should be near the true slope.
        """
        slope = 0.05
        y = _trend_series(n=N_TREND, slope=slope, noise_std=0.3)
        res = fit_local_linear_trend(y)
        # Use middle third to avoid boundary effects
        n = len(res.trend)
        mid = slice(n // 3, 2 * n // 3)
        mean_slope = float(np.mean(res.trend[mid]))
        assert abs(mean_slope - slope) < 0.02, (
            f"mean_slope={mean_slope:.4f}, true={slope}"
        )

    def test_loglikelihood_finite(self) -> None:
        y = _trend_series(n=150)
        res = fit_local_linear_trend(y)
        assert np.isfinite(res.loglikelihood)

    def test_params_populated(self) -> None:
        y = _trend_series(n=150)
        res = fit_local_linear_trend(y)
        assert len(res.params) > 0

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            fit_local_linear_trend(pd.Series(np.arange(5.0)))


# ---------------------------------------------------------------------------
# fit_basic_structural
# ---------------------------------------------------------------------------


class TestFitBasicStructural:
    """fit_basic_structural decomposes trend + seasonal correctly."""

    def test_returns_state_space_result(self) -> None:
        y, _, _ = _seasonal_trend_series(n=N_SEAS, seasonal_periods=12)
        res = fit_basic_structural(y, seasonal_periods=12)
        assert isinstance(res, StateSpaceResult)

    def test_components_populated(self) -> None:
        y, _, _ = _seasonal_trend_series(n=N_SEAS, seasonal_periods=12)
        res = fit_basic_structural(y, seasonal_periods=12)
        assert res.level.shape == (N_SEAS,)
        assert res.trend.shape == (N_SEAS,)
        assert res.seasonal.shape == (N_SEAS,)

    def test_seasonal_correlates_with_injected(self) -> None:
        """Recovered seasonal component should correlate > 0.8 with the injected sine."""
        y, _, true_seasonal = _seasonal_trend_series(
            n=N_SEAS, seasonal_periods=12, seasonal_amp=2.0, noise_std=0.1
        )
        res = fit_basic_structural(y, seasonal_periods=12)
        # Use middle portion to avoid edge effects
        mid = slice(N_SEAS // 4, 3 * N_SEAS // 4)
        corr = float(np.corrcoef(res.seasonal[mid], true_seasonal[mid])[0, 1])
        assert corr > 0.8, f"seasonal correlation={corr:.3f}"

    def test_level_tracks_trend(self) -> None:
        """The smoothed level should correlate with the true linear trend."""
        slope = 0.02
        y, true_trend, _ = _seasonal_trend_series(
            n=N_SEAS, seasonal_periods=12, slope=slope, seasonal_amp=2.0, noise_std=0.1
        )
        res = fit_basic_structural(y, seasonal_periods=12)
        mid = slice(N_SEAS // 4, 3 * N_SEAS // 4)
        corr = float(np.corrcoef(res.level[mid], true_trend[mid])[0, 1])
        assert corr > 0.9, f"level-trend correlation={corr:.3f}"

    def test_loglikelihood_finite(self) -> None:
        y, _, _ = _seasonal_trend_series(n=N_SEAS, seasonal_periods=12)
        res = fit_basic_structural(y, seasonal_periods=12)
        assert np.isfinite(res.loglikelihood)

    def test_raises_bad_seasonal_periods(self) -> None:
        y, _, _ = _seasonal_trend_series(n=100, seasonal_periods=12)
        with pytest.raises(ValueError, match="seasonal_periods"):
            fit_basic_structural(y, seasonal_periods=1)

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            fit_basic_structural(pd.Series(np.arange(10.0)), seasonal_periods=12)


# ---------------------------------------------------------------------------
# fit_unobserved_components (general interface)
# ---------------------------------------------------------------------------


class TestFitUnobservedComponents:
    """fit_unobserved_components flexible interface."""

    def test_level_only(self) -> None:
        y = _trend_series(n=100)
        res = fit_unobserved_components(y, level=True)
        assert isinstance(res, StateSpaceResult)
        assert res.level.shape == (100,)
        assert res.trend.size == 0

    def test_level_and_trend(self) -> None:
        y = _trend_series(n=150)
        res = fit_unobserved_components(y, level=True, trend=True)
        assert res.level.shape == (150,)
        assert res.trend.shape == (150,)

    def test_level_trend_seasonal(self) -> None:
        y, _, _ = _seasonal_trend_series(n=N_SEAS, seasonal_periods=12)
        res = fit_unobserved_components(y, level=True, trend=True, seasonal=12)
        assert res.level.shape == (N_SEAS,)
        assert res.trend.shape == (N_SEAS,)
        assert res.seasonal.shape == (N_SEAS,)

    def test_string_model_spec(self) -> None:
        """Passing a string model spec should work."""
        y = _trend_series(n=150)
        res = fit_unobserved_components(y, level="local linear trend")
        assert isinstance(res, StateSpaceResult)
        assert res.level.shape == (150,)

    def test_raises_bad_seasonal(self) -> None:
        y = _trend_series(n=100)
        with pytest.raises(ValueError, match="seasonal"):
            fit_unobserved_components(y, seasonal=1)

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            fit_unobserved_components(pd.Series([1.0, 2.0]), level=True)


# ---------------------------------------------------------------------------
# forecast method
# ---------------------------------------------------------------------------


class TestForecast:
    """StateSpaceResult.forecast shape, finiteness, and continuity."""

    def test_forecast_shape(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        fc = res.forecast(10)
        assert fc.shape == (10,)

    def test_forecast_finite(self) -> None:
        y = _trend_series(n=100)
        res = fit_local_level(y)
        fc = res.forecast(5)
        assert np.all(np.isfinite(fc))

    def test_forecast_continuity_local_level(self) -> None:
        """Forecast step 1 should be close to the last smoothed level."""
        y = _trend_series(n=150, slope=0.0, noise_std=0.5)
        res = fit_local_level(y)
        fc = res.forecast(3)
        last_level = float(res.level[-1])
        # First forecast should be within 3 obs_std of last level
        assert abs(float(fc[0]) - last_level) < 3.0, (
            f"fc[0]={fc[0]:.3f} vs last_level={last_level:.3f}"
        )

    def test_forecast_llt_shape(self) -> None:
        y = _trend_series(n=150)
        res = fit_local_linear_trend(y)
        fc = res.forecast(20)
        assert fc.shape == (20,)

    def test_forecast_bsm_shape(self) -> None:
        y, _, _ = _seasonal_trend_series(n=N_SEAS, seasonal_periods=12)
        res = fit_basic_structural(y, seasonal_periods=12)
        fc = res.forecast(12)
        assert fc.shape == (12,)

    def test_forecast_step_1_matches_statsmodels(self) -> None:
        """Verify forecast delegates correctly to the stored statsmodels result."""
        y = _trend_series(n=100)
        res = fit_local_level(y)
        fc = res.forecast(1)
        # Internal check: calling the raw statsmodels forecast should agree
        raw_fc = np.asarray(res._fitted_result.forecast(1), dtype=float)
        np.testing.assert_allclose(fc, raw_fc, atol=1e-10)


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify that the filters package re-exports the expected names."""

    def test_imports_from_package(self) -> None:
        from core_trading.signals.filters import (  # noqa: F401
            StateSpaceResult,
            fit_basic_structural,
            fit_local_level,
            fit_local_linear_trend,
            fit_unobserved_components,
        )

    def test_all_contents_state_space(self) -> None:
        import core_trading.signals.filters as pkg

        for name in (
            "StateSpaceResult",
            "fit_local_level",
            "fit_local_linear_trend",
            "fit_basic_structural",
            "fit_unobserved_components",
        ):
            assert hasattr(pkg, name), f"missing from package: {name}"
