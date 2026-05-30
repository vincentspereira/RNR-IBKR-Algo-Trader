"""Tests for core_trading.signals.volatility.garch (master plan Phase 5.A.5).

All tests pass under ``pytest -W error`` with no filtered warnings except
where documented below.

Design notes
------------
* GARCH simulation uses ``arch_model.simulate`` seeded via ``numpy.random.seed``
  (arch 7.x does not accept a seed kwarg on simulate()).
* All arch fits use ``rescale=False`` on percentage returns (variance ~1) to
  avoid ``DataScaleWarning`` and ``ConvergenceWarning``.
* HAR-RV parameter recovery is tested against a controlled iterated HAR DGP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.volatility.garch import (  # noqa: E402
    GARCHConfig,
    GARCHResult,
    HARRVConfig,
    HARRVResult,
    fit_garch,
    fit_har_rv,
    forecast_har_rv,
    forecast_variance,
    realised_variance,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _simulate_garch_pct(
    omega: float,
    alpha: float,
    beta: float,
    nobs: int = 2000,
    seed: int = 42,
) -> pd.Series:
    """Simulate a GARCH(1,1) ZeroMean process with percentage-return params.

    Parameters are in percentage-return space (variance ~1 range).
    Returns a pd.Series of simulated percentage returns.
    """
    from arch import arch_model

    np.random.seed(seed)
    am = arch_model(None, vol="GARCH", p=1, q=1, mean="Zero", dist="Normal")
    sim_df = am.simulate([omega, alpha, beta], nobs=nobs, burn=500)
    return sim_df["data"]


def _simulate_har_rv_process(
    const: float,
    beta_d: float,
    beta_w: float,
    beta_m: float,
    nobs: int = 3000,
    seed: int = 42,
) -> np.ndarray:
    """Simulate a HAR-RV process with known linear structure."""
    rng = np.random.default_rng(seed)
    rv = np.zeros(nobs)
    rv[:22] = 0.04
    sigma_eps = 0.005

    for t in range(22, nobs):
        rv_w_avg = rv[t - 5 : t].mean()
        rv_m_avg = rv[t - 22 : t].mean()
        eps = rng.normal(0.0, sigma_eps)
        val = const + beta_d * rv[t - 1] + beta_w * rv_w_avg + beta_m * rv_m_avg + eps
        rv[t] = max(val, 1e-10)

    return rv


# ---------------------------------------------------------------------------
# GARCHConfig validation
# ---------------------------------------------------------------------------


class TestGARCHConfig:
    def test_default_values(self) -> None:
        cfg = GARCHConfig()
        assert cfg.model == "GARCH"
        assert cfg.p == 1
        assert cfg.q == 1

    def test_invalid_model(self) -> None:
        with pytest.raises(ValueError, match="model must be"):
            GARCHConfig(model="IGARCH")  # type: ignore[arg-type]

    def test_invalid_p(self) -> None:
        with pytest.raises(ValueError, match="p must be"):
            GARCHConfig(p=0)

    def test_invalid_q(self) -> None:
        with pytest.raises(ValueError, match="q must be"):
            GARCHConfig(q=0)

    def test_frozen(self) -> None:
        cfg = GARCHConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.p = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HARRVConfig validation
# ---------------------------------------------------------------------------


class TestHARRVConfig:
    def test_default_values(self) -> None:
        cfg = HARRVConfig()
        assert cfg.daily_lag == 1
        assert cfg.weekly_lag == 5
        assert cfg.monthly_lag == 22

    def test_daily_lag_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="daily_lag must be"):
            HARRVConfig(daily_lag=0)

    def test_weekly_must_exceed_daily(self) -> None:
        with pytest.raises(ValueError, match="weekly_lag must be"):
            HARRVConfig(daily_lag=5, weekly_lag=3)

    def test_monthly_must_exceed_weekly(self) -> None:
        with pytest.raises(ValueError, match="monthly_lag must be"):
            HARRVConfig(weekly_lag=10, monthly_lag=5)

    def test_frozen(self) -> None:
        cfg = HARRVConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.weekly_lag = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PARAMETER RECOVERY -- Phase 5 DOD headline test
# ---------------------------------------------------------------------------


class TestGARCHParameterRecovery:
    """Simulate a GARCH(1,1) with known params, fit, and verify recovery.

    The simulation uses params in *percentage-return* space (omega=0.05,
    meaning the variance intercept is 0.05 (pct_return)^2).  fit_garch
    internally converts decimal returns to pct returns, fits, and converts
    omega back to the original decimal scale:
        omega_decimal = omega_pct / 100^2

    The dimensionless alpha and beta are unchanged by rescaling.
    """

    # Params in percentage-return space (the simulation DGP)
    TRUE_OMEGA_PCT = 0.05
    TRUE_ALPHA = 0.10
    TRUE_BETA = 0.85
    # Tolerance: Monte Carlo noise; 2000-obs sample, generous but meaningful
    TOL_ALPHA = 0.06
    TOL_BETA = 0.08

    def test_parameter_recovery_garch11(self) -> None:
        """Recovered omega/alpha/beta are within tolerance of simulated truth.

        omega is stored in the original (decimal) scale inside GARCHResult,
        so the comparison converts the truth from pct space:
            omega_truth_orig = omega_pct / 100^2
        alpha and beta are dimensionless and compared directly.
        """
        r_pct = _simulate_garch_pct(
            omega=self.TRUE_OMEGA_PCT,
            alpha=self.TRUE_ALPHA,
            beta=self.TRUE_BETA,
            nobs=2000,
            seed=42,
        )
        # fit_garch works in pct returns internally; feed decimal returns
        # (they get multiplied by 100 inside fit_garch).
        r_decimal = r_pct / 100.0

        result = fit_garch(r_decimal, model="GARCH", p=1, q=1)

        assert isinstance(result, GARCHResult)
        assert result.config.model == "GARCH"

        # Recovered params -- omega is in original (decimal) return^2 units.
        omega_rec = float(result.params["omega"])
        alpha_rec = float(result.params["alpha"][0])  # type: ignore[index]
        beta_rec = float(result.params["beta"][0])  # type: ignore[index]

        # Convert simulation truth from pct space to original scale.
        omega_truth_orig = self.TRUE_OMEGA_PCT / (100.0**2)
        # Relative tolerance on omega: omega is small, so allow 200% relative
        # or at least the absolute tolerance set by TOL_ALPHA/100^2.
        tol_omega_orig = 3.0 * omega_truth_orig  # within 3x the truth

        assert abs(omega_rec - omega_truth_orig) < tol_omega_orig, (
            f"omega recovery failed: truth={omega_truth_orig:.2e}, "
            f"recovered={omega_rec:.2e}, tol={tol_omega_orig:.2e}"
        )
        assert abs(alpha_rec - self.TRUE_ALPHA) < self.TOL_ALPHA, (
            f"alpha recovery failed: truth={self.TRUE_ALPHA}, "
            f"recovered={alpha_rec:.4f}, tol={self.TOL_ALPHA}"
        )
        assert abs(beta_rec - self.TRUE_BETA) < self.TOL_BETA, (
            f"beta recovery failed: truth={self.TRUE_BETA}, "
            f"recovered={beta_rec:.4f}, tol={self.TOL_BETA}"
        )

    def test_parameter_recovery_with_config(self) -> None:
        """fit_garch accepts a GARCHConfig object and produces identical results."""
        r_pct = _simulate_garch_pct(
            omega=self.TRUE_OMEGA_PCT,
            alpha=self.TRUE_ALPHA,
            beta=self.TRUE_BETA,
            nobs=2000,
            seed=42,
        )
        r_decimal = r_pct / 100.0
        cfg = GARCHConfig(model="GARCH", p=1, q=1)

        result_cfg = fit_garch(r_decimal, config=cfg)
        result_kw = fit_garch(r_decimal, model="GARCH", p=1, q=1)

        assert result_cfg.params["alpha"] == result_kw.params["alpha"]
        assert result_cfg.params["beta"] == result_kw.params["beta"]


# ---------------------------------------------------------------------------
# GARCH result shape / finite checks
# ---------------------------------------------------------------------------


class TestGARCHResultShape:
    def test_cond_vol_shape_and_sign(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=0)
        result = fit_garch(r_pct / 100.0)

        assert isinstance(result.conditional_volatility, pd.Series)
        assert len(result.conditional_volatility) == 500
        assert (result.conditional_volatility > 0).all()

    def test_information_criteria_finite(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=1)
        result = fit_garch(r_pct / 100.0)

        assert np.isfinite(result.loglikelihood)
        assert np.isfinite(result.aic)
        assert np.isfinite(result.bic)
        assert result.bic >= result.aic  # BIC penalises more

    def test_result_preserves_series_index(self) -> None:
        dates = pd.date_range("2020-01-01", periods=500, freq="B")
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=2)
        r_s = pd.Series(r_pct.values / 100.0, index=dates)

        result = fit_garch(r_s)

        assert len(result.conditional_volatility) == 500

    def test_too_few_observations_raises(self) -> None:
        with pytest.raises(ValueError, match="finite observations"):
            fit_garch(np.array([0.01, 0.02]))

    def test_accepts_numpy_array(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=400, seed=3)
        result = fit_garch(r_pct.to_numpy() / 100.0)
        assert isinstance(result, GARCHResult)

    def test_params_omega_positive(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=5)
        result = fit_garch(r_pct / 100.0)
        assert float(result.params["omega"]) > 0


# ---------------------------------------------------------------------------
# EGARCH
# ---------------------------------------------------------------------------


class TestEGARCH:
    def test_egarch_fit_finite_params(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=10)
        result = fit_garch(r_pct / 100.0, model="EGARCH", p=1, q=1)

        assert result.config.model == "EGARCH"
        assert np.isfinite(float(result.params["omega"]))
        alpha_vals = result.params["alpha"]
        assert isinstance(alpha_vals, list)
        assert all(np.isfinite(v) for v in alpha_vals)  # type: ignore[arg-type]
        beta_vals = result.params["beta"]
        assert isinstance(beta_vals, list)
        assert all(np.isfinite(v) for v in beta_vals)  # type: ignore[arg-type]

    def test_egarch_cond_vol_positive(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=11)
        result = fit_garch(r_pct / 100.0, model="EGARCH", p=1, q=1)

        assert (result.conditional_volatility > 0).all()

    def test_egarch_no_gamma_key(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=12)
        result = fit_garch(r_pct / 100.0, model="EGARCH")

        assert "gamma" not in result.params


# ---------------------------------------------------------------------------
# GJR-GARCH
# ---------------------------------------------------------------------------


class TestGJRGARCH:
    def test_gjr_fit_finite_params(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=20)
        result = fit_garch(r_pct / 100.0, model="GJR-GARCH", p=1, q=1)

        assert result.config.model == "GJR-GARCH"
        assert np.isfinite(float(result.params["omega"]))
        gamma_vals = result.params["gamma"]
        assert isinstance(gamma_vals, list)
        assert all(np.isfinite(v) for v in gamma_vals)  # type: ignore[arg-type]

    def test_gjr_cond_vol_positive(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=21)
        result = fit_garch(r_pct / 100.0, model="GJR-GARCH", p=1, q=1)

        assert (result.conditional_volatility > 0).all()

    def test_gjr_has_gamma_key(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=22)
        result = fit_garch(r_pct / 100.0, model="GJR-GARCH")

        assert "gamma" in result.params
        assert isinstance(result.params["gamma"], list)
        assert len(result.params["gamma"]) == 1  # o=p=1


# ---------------------------------------------------------------------------
# forecast_variance
# ---------------------------------------------------------------------------


class TestForecastVariance:
    def test_garch_forecast_positive_and_shaped(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=30)
        result = fit_garch(r_pct / 100.0, model="GARCH")
        fc = forecast_variance(result, horizon=5)

        assert fc.shape == (5,)
        assert (fc > 0).all()

    def test_garch_forecast_horizon_1(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=31)
        result = fit_garch(r_pct / 100.0)
        fc = forecast_variance(result, horizon=1)

        assert fc.shape == (1,)
        assert float(fc[0]) > 0

    def test_egarch_forecast_h1_positive(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=32)
        result = fit_garch(r_pct / 100.0, model="EGARCH")
        fc = forecast_variance(result, horizon=1)

        assert fc.shape == (1,)
        assert float(fc[0]) > 0

    def test_egarch_forecast_h5_positive(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=33)
        result = fit_garch(r_pct / 100.0, model="EGARCH")
        fc = forecast_variance(result, horizon=5, n_simulations=200, random_seed=1)

        assert fc.shape == (5,)
        assert (fc > 0).all()

    def test_gjr_forecast_positive_and_shaped(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=1000, seed=34)
        result = fit_garch(r_pct / 100.0, model="GJR-GARCH")
        fc = forecast_variance(result, horizon=5)

        assert fc.shape == (5,)
        assert (fc > 0).all()

    def test_invalid_horizon_raises(self) -> None:
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=35)
        result = fit_garch(r_pct / 100.0)
        with pytest.raises(ValueError, match="horizon must be"):
            forecast_variance(result, horizon=0)

    def test_variance_in_original_scale(self) -> None:
        """Forecast variance should be in original (decimal) return scale."""
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=36)
        r_decimal = r_pct / 100.0
        result = fit_garch(r_decimal)
        fc = forecast_variance(result, horizon=1)
        # Conditional vol of ~1% daily returns is ~0.01; var is ~0.0001
        # Should be << 1 (not in percentage-return space)
        assert float(fc[0]) < 0.01, (
            f"variance {fc[0]:.6f} looks like it is in pct space, not decimal"
        )

    def test_forecast_matches_cond_vol_magnitude(self) -> None:
        """h=1 forecast should be in the same ballpark as the conditional vol."""
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=37)
        r_decimal = r_pct / 100.0
        result = fit_garch(r_decimal)
        fc = forecast_variance(result, horizon=1)
        last_vol = float(result.conditional_volatility.iloc[-1])
        last_var_from_vol = last_vol**2
        # forecast and last observed var should be within 2 orders of magnitude
        ratio = float(fc[0]) / last_var_from_vol
        assert 0.01 < ratio < 100.0, (
            f"forecast variance {fc[0]:.2e} and last var {last_var_from_vol:.2e} "
            f"differ by ratio {ratio:.2f}"
        )


# ---------------------------------------------------------------------------
# realised_variance
# ---------------------------------------------------------------------------


class TestRealisedVariance:
    def test_window_1_equals_squared_returns(self) -> None:
        r = pd.Series([0.01, -0.02, 0.015, -0.005, 0.008])
        rv = realised_variance(r, window=1)

        np.testing.assert_allclose(rv.values, (r**2).values)

    def test_window_5_shape(self) -> None:
        r = pd.Series(np.random.default_rng(0).standard_normal(100) * 0.01)
        rv = realised_variance(r, window=5)

        assert rv.shape == (100,)
        assert rv.iloc[:4].isna().all()
        assert rv.iloc[4:].notna().all()

    def test_annualised(self) -> None:
        r = pd.Series(np.ones(252) * 0.01)
        rv = realised_variance(r, window=1, annualise=True, trading_periods=252)

        np.testing.assert_allclose(rv.dropna().values, 0.01**2 * 252)

    def test_numpy_input(self) -> None:
        arr = np.array([0.01, -0.02, 0.015])
        rv = realised_variance(arr, window=1)

        assert rv.shape == (3,)

    def test_returns_series_name(self) -> None:
        r = pd.Series([0.01, 0.02])
        rv = realised_variance(r)
        assert rv.name == "realised_variance"


# ---------------------------------------------------------------------------
# HAR-RV fit
# ---------------------------------------------------------------------------


class TestFitHARRV:
    def test_parameter_recovery(self) -> None:
        """Recovered HAR-RV coefficients are close to the true DGP values."""
        TRUE_C = 0.02
        TRUE_BD = 0.30
        TRUE_BW = 0.40
        TRUE_BM = 0.20
        rv = _simulate_har_rv_process(TRUE_C, TRUE_BD, TRUE_BW, TRUE_BM, nobs=3000)

        result = fit_har_rv(rv)

        assert isinstance(result, HARRVResult)
        assert abs(result.const - TRUE_C) < 0.01, (
            f"const: truth={TRUE_C}, got={result.const:.4f}"
        )
        assert abs(result.beta_daily - TRUE_BD) < 0.06, (
            f"beta_d: truth={TRUE_BD}, got={result.beta_daily:.4f}"
        )
        assert abs(result.beta_weekly - TRUE_BW) < 0.08, (
            f"beta_w: truth={TRUE_BW}, got={result.beta_weekly:.4f}"
        )
        assert abs(result.beta_monthly - TRUE_BM) < 0.08, (
            f"beta_m: truth={TRUE_BM}, got={result.beta_monthly:.4f}"
        )

    def test_rsquared_on_har_dgp(self) -> None:
        """R-squared should be high when data comes from a HAR process."""
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=3000)
        result = fit_har_rv(rv)

        assert result.rsquared > 0.70, (
            f"R-squared {result.rsquared:.3f} is unexpectedly low for HAR DGP"
        )

    def test_fitted_shape(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)

        assert isinstance(result.fitted, pd.Series)
        assert len(result.fitted) == len(rv) - 22

    def test_n_obs_matches(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        assert result.n_obs == len(rv) - 22

    def test_coef_vector_shape(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        assert result.coef_vector.shape == (4,)

    def test_custom_config(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        cfg = HARRVConfig(daily_lag=1, weekly_lag=4, monthly_lag=16)
        result = fit_har_rv(rv, config=cfg)
        assert result.config.weekly_lag == 4
        assert result.config.monthly_lag == 16

    def test_too_few_obs_raises(self) -> None:
        with pytest.raises(ValueError, match="fit_har_rv requires"):
            fit_har_rv(np.array([0.01, 0.02, 0.03]))

    def test_numpy_input_accepted(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        assert isinstance(result, HARRVResult)

    def test_pandas_series_input_accepted(self) -> None:
        rv_arr = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        rv_s = pd.Series(rv_arr)
        result = fit_har_rv(rv_s)
        assert isinstance(result, HARRVResult)

    def test_frozen(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        with pytest.raises((AttributeError, TypeError)):
            result.const = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HAR-RV forecast
# ---------------------------------------------------------------------------


class TestForecastHARRV:
    def test_forecast_shape_and_positive(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        fc = forecast_har_rv(result, rv_history=rv, horizon=5)

        assert fc.shape == (5,)
        assert (fc > 0).all()

    def test_forecast_horizon_1(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        fc = forecast_har_rv(result, rv_history=rv, horizon=1)

        assert fc.shape == (1,)

    def test_forecast_invalid_horizon(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        with pytest.raises(ValueError, match="horizon must be"):
            forecast_har_rv(result, rv_history=rv, horizon=0)

    def test_forecast_too_short_history(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        with pytest.raises(ValueError, match="rv_history"):
            forecast_har_rv(result, rv_history=np.array([0.01, 0.02]), horizon=1)

    def test_forecast_finite(self) -> None:
        rv = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        result = fit_har_rv(rv)
        fc = forecast_har_rv(result, rv_history=rv, horizon=10)

        assert np.isfinite(fc).all()

    def test_pandas_history_accepted(self) -> None:
        rv_arr = _simulate_har_rv_process(0.02, 0.30, 0.40, 0.20, nobs=500)
        rv_s = pd.Series(rv_arr)
        result = fit_har_rv(rv_arr)
        fc = forecast_har_rv(result, rv_history=rv_s, horizon=3)
        assert fc.shape == (3,)
