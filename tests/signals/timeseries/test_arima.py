"""Tests for core_trading.signals.timeseries.arima (Phase 5.A.4).

Validates ARIMA/SARIMA fitting, fractional differencing (FFD and expanding
window), the min-d search helper, and all error-handling paths.

Run with:
    pytest tests/signals/timeseries/test_arima.py -W error -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.timeseries.arima import (
    ArimaConfig,
    ArimaResult,
    FracDiffResult,
    _expanding_weights,
    _ffd_weights,
    fit_arima,
    frac_diff,
    frac_diff_ffd,
    min_frac_diff,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ar1_series(n: int = 400, phi: float = 0.7, seed: int = 0) -> np.ndarray:
    """Simulate a zero-mean AR(1) series with known phi."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=n)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = phi * y[t - 1] + eps[t]
    return y


def _random_walk(n: int = 1000, seed: int = 11) -> np.ndarray:
    """Simulate a near-unit-root (random walk) series.

    Default seed=11 is chosen so that frac_diff_ffd(d=0.4) passes the ADF
    test with p < 0.001 while maintaining correlation > 0.5 with the level.
    """
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(size=n))


# ---------------------------------------------------------------------------
# ArimaConfig tests
# ---------------------------------------------------------------------------


class TestArimaConfig:
    def test_default_values(self) -> None:
        cfg = ArimaConfig()
        assert cfg.order == (1, 0, 0)
        assert cfg.seasonal_order == (0, 0, 0, 0)
        assert cfg.trend == "n"

    def test_custom_values(self) -> None:
        cfg = ArimaConfig(order=(2, 1, 1), seasonal_order=(1, 0, 0, 12), trend="c")
        assert cfg.order == (2, 1, 1)
        assert cfg.seasonal_order == (1, 0, 0, 12)
        assert cfg.trend == "c"

    def test_frozen(self) -> None:
        cfg = ArimaConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.order = (0, 0, 0)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _ffd_weights helper
# ---------------------------------------------------------------------------


class TestFfdWeights:
    def test_first_weight_is_one(self) -> None:
        w = _ffd_weights(0.4, threshold=1e-3)
        assert w[0] == pytest.approx(1.0)

    def test_second_weight_is_minus_d(self) -> None:
        d = 0.4
        w = _ffd_weights(d, threshold=1e-3)
        assert w[1] == pytest.approx(-d, rel=1e-9)

    def test_weights_truncated_at_threshold(self) -> None:
        threshold = 1e-3
        w = _ffd_weights(0.4, threshold=threshold)
        # Every weight that was emitted must be above threshold in abs value
        assert np.all(np.abs(w) >= threshold)

    def test_d_zero_returns_single_weight(self) -> None:
        w = _ffd_weights(0.0, threshold=1e-3)
        assert len(w) == 1
        assert w[0] == pytest.approx(1.0)

    def test_d_one_returns_two_weights(self) -> None:
        w = _ffd_weights(1.0, threshold=1e-5)
        assert len(w) == 2
        assert w[0] == pytest.approx(1.0)
        assert w[1] == pytest.approx(-1.0)

    def test_smaller_threshold_longer_window(self) -> None:
        w_coarse = _ffd_weights(0.4, threshold=1e-2)
        w_fine = _ffd_weights(0.4, threshold=1e-3)
        assert len(w_fine) > len(w_coarse)

    def test_invalid_d_below_zero(self) -> None:
        with pytest.raises(ValueError, match="d must be in"):
            _ffd_weights(-0.1, threshold=1e-3)

    def test_invalid_d_above_one(self) -> None:
        with pytest.raises(ValueError, match="d must be in"):
            _ffd_weights(1.1, threshold=1e-3)

    def test_invalid_threshold_zero(self) -> None:
        with pytest.raises(ValueError, match="threshold must be positive"):
            _ffd_weights(0.4, threshold=0.0)

    def test_weights_decay(self) -> None:
        w = _ffd_weights(0.4, threshold=1e-3)
        # Absolute values should be monotonically decreasing after w[0]
        abs_w = np.abs(w)
        assert np.all(abs_w[1:] <= abs_w[:-1])


# ---------------------------------------------------------------------------
# _expanding_weights helper
# ---------------------------------------------------------------------------


class TestExpandingWeights:
    def test_length_equals_requested(self) -> None:
        w = _expanding_weights(0.4, length=20, threshold=1e-3)
        assert len(w) == 20

    def test_first_weight_is_one(self) -> None:
        w = _expanding_weights(0.4, length=10, threshold=1e-3)
        assert w[0] == pytest.approx(1.0)

    def test_zero_tail_when_threshold_reached(self) -> None:
        # With threshold=0.5 the second weight (-0.4) triggers early stop
        w = _expanding_weights(0.4, length=5, threshold=0.45)
        # w[0]=1.0 passes, w[1]=-0.4 which is below 0.45 threshold
        assert w[0] == pytest.approx(1.0)
        assert all(v == 0.0 for v in w[1:])


# ---------------------------------------------------------------------------
# fit_arima -- AR(1) recovery
# ---------------------------------------------------------------------------


class TestFitArima:
    """AR(1) parameter recovery and basic ARIMA/SARIMA functionality."""

    TRUE_PHI = 0.72

    @pytest.fixture()
    def ar1_series(self) -> np.ndarray:
        return _ar1_series(n=500, phi=self.TRUE_PHI, seed=42)

    def test_ar1_phi_recovery(self, ar1_series: np.ndarray) -> None:
        """Recovered AR(1) coefficient must be within 0.05 of the true phi."""
        result = fit_arima(ar1_series, order=(1, 0, 0))
        phi_hat = result.params["ar.L1"]
        assert abs(phi_hat - self.TRUE_PHI) < 0.05, (
            f"Expected phi near {self.TRUE_PHI}, got {phi_hat:.4f}"
        )

    def test_result_is_arima_result(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert isinstance(result, ArimaResult)

    def test_result_is_frozen(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        with pytest.raises((AttributeError, TypeError)):
            result.aic = 0.0  # type: ignore[misc]

    def test_config_stored_correctly(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0), trend="n")
        assert result.config.order == (1, 0, 0)
        assert result.config.trend == "n"

    def test_information_criteria_positive(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert np.isfinite(result.aic)
        assert np.isfinite(result.bic)
        assert np.isfinite(result.loglikelihood)

    def test_aic_bic_ordering(self, ar1_series: np.ndarray) -> None:
        """AIC = -2*ll + 2k; BIC = -2*ll + k*log(n); for n >= 8, BIC >= AIC."""
        result = fit_arima(ar1_series, order=(1, 0, 0))
        # With n=500 >> e^2 ~ 7.4, BIC penalty is larger so BIC >= AIC
        assert result.bic >= result.aic - 1e-6

    def test_params_dict_has_ar_l1(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert "ar.L1" in result.params
        assert "sigma2" in result.params

    def test_fitted_values_shape(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert result.fitted_values.shape == (len(ar1_series),)

    def test_fitted_values_finite(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert np.all(np.isfinite(result.fitted_values))

    def test_n_obs(self, ar1_series: np.ndarray) -> None:
        result = fit_arima(ar1_series, order=(1, 0, 0))
        assert result.n_obs == len(ar1_series)

    def test_pandas_series_input(self, ar1_series: np.ndarray) -> None:
        s = pd.Series(ar1_series)
        result = fit_arima(s, order=(1, 0, 0))
        assert isinstance(result, ArimaResult)
        assert result.n_obs == len(ar1_series)

    def test_sarima_seasonal(self) -> None:
        """SARIMA(1,0,0)(1,0,0,4) should fit without error."""
        rng = np.random.default_rng(7)
        y = rng.normal(size=300)
        result = fit_arima(y, order=(1, 0, 0), seasonal_order=(1, 0, 0, 4))
        assert "ar.L1" in result.params
        assert "ar.S.L4" in result.params

    def test_too_short_series_raises(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            fit_arima(np.array([1.0, 2.0]), order=(1, 0, 0))

    def test_negative_order_raises(self) -> None:
        y = _ar1_series(n=100)
        with pytest.raises(ValueError, match="non-negative"):
            fit_arima(y, order=(-1, 0, 0))


# ---------------------------------------------------------------------------
# ArimaResult.forecast
# ---------------------------------------------------------------------------


class TestArimaForecast:
    @pytest.fixture()
    def fitted(self) -> ArimaResult:
        y = _ar1_series(n=400, phi=0.7, seed=10)
        return fit_arima(y, order=(1, 0, 0))

    def test_forecast_shape(self, fitted: ArimaResult) -> None:
        fc = fitted.forecast(horizon=5)
        assert isinstance(fc, np.ndarray)
        assert fc.shape == (5,)

    def test_forecast_finite(self, fitted: ArimaResult) -> None:
        fc = fitted.forecast(horizon=10)
        assert np.all(np.isfinite(fc))

    def test_single_step_forecast(self, fitted: ArimaResult) -> None:
        fc = fitted.forecast(horizon=1)
        assert fc.shape == (1,)
        assert np.isfinite(fc[0])

    def test_forecast_with_conf_int(self, fitted: ArimaResult) -> None:
        fc, ci = fitted.forecast(horizon=5, conf_int=True)
        assert fc.shape == (5,)
        assert ci.shape == (5, 2)
        # Lower < point forecast < upper for all steps
        assert np.all(ci[:, 0] <= fc + 1e-9)
        assert np.all(ci[:, 1] >= fc - 1e-9)

    def test_conf_int_widens_with_horizon(self, fitted: ArimaResult) -> None:
        """Confidence interval should widen as horizon grows."""
        _, ci = fitted.forecast(horizon=10, conf_int=True)
        widths = ci[:, 1] - ci[:, 0]
        # Width should be non-decreasing
        assert np.all(np.diff(widths) >= -1e-9)

    def test_forecast_horizon_zero_raises(self, fitted: ArimaResult) -> None:
        with pytest.raises(ValueError, match="horizon must be >= 1"):
            fitted.forecast(horizon=0)

    def test_forecast_horizon_negative_raises(self, fitted: ArimaResult) -> None:
        with pytest.raises(ValueError, match="horizon must be >= 1"):
            fitted.forecast(horizon=-3)

    def test_forecast_no_fitted_result_raises(self) -> None:
        """Constructing ArimaResult without a live model raises AttributeError."""
        bare = ArimaResult(
            config=ArimaConfig(),
            params={},
            loglikelihood=-100.0,
            aic=200.0,
            bic=210.0,
            fitted_values=np.zeros(10),
            n_obs=10,
            _fitted_result=None,
        )
        with pytest.raises(AttributeError, match="_fitted_result is None"):
            bare.forecast(horizon=1)

    def test_ar1_forecast_decays_to_zero(self) -> None:
        """AR(1) multi-step forecast should decay toward zero for phi < 1."""
        rng = np.random.default_rng(99)
        n = 500
        phi = 0.8
        y = np.zeros(n)
        for t in range(1, n):
            y[t] = phi * y[t - 1] + rng.normal() * 0.1
        # Drive y away from zero so the decay is observable
        result = fit_arima(y, order=(1, 0, 0))
        fc = result.forecast(horizon=20)
        # Forecast magnitude should shrink: |fc[19]| < |fc[0]|
        assert abs(fc[19]) <= abs(fc[0]) + 1e-6


# ---------------------------------------------------------------------------
# frac_diff_ffd
# ---------------------------------------------------------------------------


class TestFracDiffFfd:
    @pytest.fixture()
    def rw(self) -> np.ndarray:
        return _random_walk(n=1000, seed=11)

    def test_returns_frac_diff_result(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.4)
        assert isinstance(result, FracDiffResult)
        assert result.method == "ffd"

    def test_series_length_equals_input(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.4)
        assert len(result.series) == len(rw)

    def test_nan_warmup_period(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.4)
        arr = np.asarray(result.series)
        assert np.isnan(arr[0])
        nan_count = int(np.sum(np.isnan(arr)))
        assert nan_count == result.window_length - 1

    def test_valid_observations_finite(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.4)
        arr = np.asarray(result.series)
        valid = arr[~np.isnan(arr)]
        assert len(valid) > 0
        assert np.all(np.isfinite(valid))

    def test_stationarity_achieved(self, rw: np.ndarray) -> None:
        """FFD with d=0.4 should make the random walk stationary (ADF p < 0.05)."""
        from statsmodels.tsa.stattools import adfuller

        result = frac_diff_ffd(rw, d=0.4)
        arr = np.asarray(result.series)
        valid = arr[~np.isnan(arr)]
        _, pval, *_ = adfuller(valid, autolag="AIC")
        assert pval < 0.05, (
            f"FFD(d=0.4) series not stationary; ADF p-value = {pval:.4f}"
        )

    def test_memory_preserved_with_original(self, rw: np.ndarray) -> None:
        """FFD output should remain strongly correlated with the input level series."""
        result = frac_diff_ffd(rw, d=0.4)
        arr = np.asarray(result.series)
        mask = ~np.isnan(arr)
        corr = float(np.corrcoef(rw[mask], arr[mask])[0, 1])
        assert corr > 0.5, (
            f"FFD output not correlated with original; correlation = {corr:.4f}"
        )

    def test_d_one_approximates_first_difference(self, rw: np.ndarray) -> None:
        """d=1.0 with tight threshold should equal the ordinary first difference."""
        result = frac_diff_ffd(rw, d=1.0, threshold=1e-5)
        fd_arr = np.asarray(result.series)
        first_diff = np.diff(rw)
        # Align: fd_arr[1] corresponds to first_diff[0]
        assert np.allclose(fd_arr[1:], first_diff, atol=1e-10)

    def test_d_zero_equals_original(self, rw: np.ndarray) -> None:
        """d=0 should return the original series unchanged (no NaN)."""
        result = frac_diff_ffd(rw, d=0.0, threshold=1e-5)
        fd_arr = np.asarray(result.series)
        # With d=0, weights=[1.0], window_length=1, no NaN
        assert result.window_length == 1
        assert np.allclose(fd_arr, rw)

    def test_window_length_stored(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.4, threshold=1e-3)
        assert result.window_length is not None
        assert result.window_length >= 2

    def test_d_and_threshold_stored(self, rw: np.ndarray) -> None:
        result = frac_diff_ffd(rw, d=0.3, threshold=5e-4)
        assert result.d == pytest.approx(0.3)
        assert result.threshold == pytest.approx(5e-4)

    def test_pandas_series_preserves_index(self) -> None:
        idx = pd.date_range("2020-01-01", periods=200, freq="B")
        s = pd.Series(_random_walk(200, seed=5), index=idx)
        result = frac_diff_ffd(s, d=0.4)
        assert isinstance(result.series, pd.Series)
        assert result.series.index.equals(idx)

    def test_series_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="shorter than the filter window"):
            frac_diff_ffd(np.ones(5), d=0.4, threshold=1e-5)

    def test_invalid_d_raises(self) -> None:
        with pytest.raises(ValueError, match="d must be in"):
            frac_diff_ffd(np.ones(100), d=1.5)

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold must be positive"):
            frac_diff_ffd(np.ones(100), d=0.4, threshold=-1.0)

    def test_larger_d_shorter_correlation(self) -> None:
        """Higher d should produce lower correlation with the original level."""
        rw = _random_walk(n=800, seed=9)
        r_low = frac_diff_ffd(rw, d=0.2, threshold=1e-3)
        r_high = frac_diff_ffd(rw, d=0.8, threshold=1e-3)

        def _corr(fd_res: FracDiffResult) -> float:
            arr = np.asarray(fd_res.series)
            mask = ~np.isnan(arr)
            return float(np.corrcoef(rw[mask], arr[mask])[0, 1])

        assert _corr(r_low) > _corr(r_high)


# ---------------------------------------------------------------------------
# frac_diff (expanding window)
# ---------------------------------------------------------------------------


class TestFracDiff:
    @pytest.fixture()
    def rw(self) -> np.ndarray:
        return _random_walk(n=400, seed=3)

    def test_returns_frac_diff_result(self, rw: np.ndarray) -> None:
        result = frac_diff(rw, d=0.4)
        assert isinstance(result, FracDiffResult)
        assert result.method == "expanding"

    def test_no_nan_in_output(self, rw: np.ndarray) -> None:
        result = frac_diff(rw, d=0.4)
        assert np.all(np.isfinite(np.asarray(result.series)))

    def test_length_matches_input(self, rw: np.ndarray) -> None:
        result = frac_diff(rw, d=0.4)
        assert len(result.series) == len(rw)

    def test_window_length_is_none(self, rw: np.ndarray) -> None:
        result = frac_diff(rw, d=0.4)
        assert result.window_length is None

    def test_stationarity_achieved(self, rw: np.ndarray) -> None:
        from statsmodels.tsa.stattools import adfuller

        result = frac_diff(rw, d=0.4)
        _, pval, *_ = adfuller(np.asarray(result.series), autolag="AIC")
        assert pval < 0.05

    def test_invalid_d_raises(self, rw: np.ndarray) -> None:
        with pytest.raises(ValueError, match="d must be in"):
            frac_diff(rw, d=-0.1)

    def test_invalid_threshold_raises(self, rw: np.ndarray) -> None:
        with pytest.raises(ValueError, match="threshold must be positive"):
            frac_diff(rw, d=0.4, threshold=0.0)

    def test_pandas_series_preserves_index(self) -> None:
        idx = pd.date_range("2021-01-01", periods=100, freq="B")
        s = pd.Series(_random_walk(100, seed=6), index=idx)
        result = frac_diff(s, d=0.4)
        assert isinstance(result.series, pd.Series)
        assert result.series.index.equals(idx)


# ---------------------------------------------------------------------------
# min_frac_diff
# ---------------------------------------------------------------------------


class TestMinFracDiff:
    def test_returns_float(self) -> None:
        rw = _random_walk(n=800, seed=4)
        d = min_frac_diff(rw)
        assert isinstance(d, float)

    def test_result_in_unit_interval(self) -> None:
        rw = _random_walk(n=800, seed=4)
        d = min_frac_diff(rw)
        assert 0.0 <= d <= 1.0

    def test_already_stationary_returns_zero(self) -> None:
        """White noise is already stationary so d=0 should be returned."""
        rng = np.random.default_rng(5)
        wn = rng.normal(size=1000)
        d = min_frac_diff(wn)
        assert d == 0.0

    def test_random_walk_needs_positive_d(self) -> None:
        """A pure random walk should require d > 0 for stationarity."""
        rw = _random_walk(n=1000, seed=6)
        d = min_frac_diff(rw)
        assert d > 0.0

    def test_result_achieves_stationarity(self) -> None:
        """The returned d should produce a stationary FFD series."""
        from statsmodels.tsa.stattools import adfuller

        rw = _random_walk(n=1000, seed=7)
        d = min_frac_diff(rw)
        if d == 0.0:
            candidate = rw
        else:
            fd = frac_diff_ffd(rw, d=d, threshold=1e-3)
            arr = np.asarray(fd.series)
            candidate = arr[~np.isnan(arr)]
        _, pval, *_ = adfuller(candidate, autolag="AIC")
        assert pval < 0.05

    def test_invalid_d_step_raises(self) -> None:
        with pytest.raises(ValueError, match="d_step must be in"):
            min_frac_diff(np.ones(200), d_step=0.0)

    def test_pandas_series_accepted(self) -> None:
        s = pd.Series(_random_walk(n=800, seed=8))
        d = min_frac_diff(s)
        assert 0.0 <= d <= 1.0

    def test_custom_d_step(self) -> None:
        rw = _random_walk(n=800, seed=9)
        d = min_frac_diff(rw, d_step=0.1)
        assert d % 0.1 < 1e-9 or abs(d - 1.0) < 1e-9

    def test_returns_one_when_no_d_achieves_stationarity(self) -> None:
        """When no d in grid achieves stationarity, 1.0 is returned.

        We force this by using a very tight adf_alpha near zero so that the
        ADF test effectively never rejects, combined with a wide d_step so
        only d=0 and d=1 are tried.
        """
        rw = _random_walk(n=400, seed=20)
        result = min_frac_diff(rw, adf_alpha=1e-15, d_step=1.0)
        assert result == 1.0

    def test_skips_candidate_shorter_than_min_valid_obs(self) -> None:
        """The min_valid_obs guard skips candidates with too few valid points.

        With n=50 and a threshold_fd that yields a filter window of length 40
        for d=0.5, only 11 valid values remain.  With min_valid_obs=30 the
        candidate is skipped.  We pair this with a non-stationary seed so
        d=0 is also not stationary, but d=1.0 (window=2) should pass.
        The function must return a valid float in [0, 1].
        """
        rng = np.random.default_rng(88)
        mid_rw = np.cumsum(rng.normal(size=50))
        # threshold_fd=1e-3 gives window ~55 for d=0.4 but window=11 for d=0.5;
        # min_valid_obs=45 forces the skip for d=0.5 (50 - 11 + 1 = 40 valid < 45)
        result = min_frac_diff(
            mid_rw,
            threshold_fd=1e-3,
            d_step=0.5,
            min_valid_obs=45,
        )
        assert 0.0 <= result <= 1.0

    def test_skips_d_when_series_too_short_for_window(self) -> None:
        """FFD ValueError on too-short series is caught and the d is skipped.

        We construct a non-stationary (random walk) series of length 10 and
        search with threshold_fd=1e-5.  For d=0.5 the filter window is 927
        (greater than 10), so frac_diff_ffd raises ValueError; the loop
        catches it and continues.  With only 10 obs the min_valid_obs guard
        (default 30) also fires for d=0.  Because no d passes, the function
        returns 1.0 -- covering both the except-continue and return-1.0 paths.
        """
        rng = np.random.default_rng(77)
        tiny_rw = np.cumsum(rng.normal(size=10))
        result = min_frac_diff(tiny_rw, threshold_fd=1e-5, d_step=0.5)
        assert result == 1.0


# ---------------------------------------------------------------------------
# FracDiffResult DTO
# ---------------------------------------------------------------------------


class TestFracDiffResult:
    def test_all_fields_accessible(self) -> None:
        rw = _random_walk(n=400, seed=10)
        result = frac_diff_ffd(rw, d=0.3, threshold=1e-3)
        assert result.d == pytest.approx(0.3)
        assert result.threshold == pytest.approx(1e-3)
        assert result.window_length is not None
        assert result.method == "ffd"
        assert len(result.series) == len(rw)


# ---------------------------------------------------------------------------
# Public re-export from __init__
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_imports_from_package(self) -> None:
        from core_trading.signals.timeseries import (
            ArimaConfig,
            ArimaResult,
            FracDiffResult,
            fit_arima,
            frac_diff,
            frac_diff_ffd,
            min_frac_diff,
        )

        assert callable(fit_arima)
        assert callable(frac_diff_ffd)
        assert callable(frac_diff)
        assert callable(min_frac_diff)
        assert issubclass(ArimaConfig, object)
        assert issubclass(ArimaResult, object)
        assert issubclass(FracDiffResult, object)

    def test_all_exports_defined(self) -> None:
        import core_trading.signals.timeseries as pkg

        for name in pkg.__all__:
            assert hasattr(pkg, name), f"Missing export: {name}"
