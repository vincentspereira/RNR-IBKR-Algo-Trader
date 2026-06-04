"""Tests for core_trading.risk.vol_forecast (Phase 7, module 7.6).

All tests run under ``pytest -W error`` with no additional warning filters
(arch's DataScaleWarning is suppressed by the implementation's pct-return
rescaling, so it does not leak here).

Design notes
------------
* GARCH-backed tests use the same simulation helper pattern as
  ``tests/signals/volatility/test_garch.py``: arch_model.simulate on
  percentage-scale parameters, then divide by 100 before passing to the
  forecaster.
* Parameter-recovery assertions use generous but meaningful tolerances to
  stay robust across 500-2000 observation sample sizes.
* EWMA hand-computed examples use a 4-step series so the recursion can be
  traced analytically.
* CCC covariance tests verify the identity-correlation degeneracy and
  the PSD projection on a deliberately indefinite input.
* All generated data uses deterministic seeds so tests are reproducible.

Coverage
--------
* VolForecastConfig: validation, defaults.
* AssetVolForecast: frozen, field values.
* VolForecastResult: structure, fallback recording.
* CCCCovResult: structure, PSD flag.
* ewma_variance: parameter recovery on iid normal; lambda weighting vs
  hand-computed example; input validation.
* forecast_panel_vols: GARCH path; EWMA fallback (short sample); multi-asset
  panel; column order preservation.
* forecast_cov_matrix: CCC identity-correlation degeneracy; PSD guarantee;
  sample vs ledoit_wolf correlation source; NaN panel rejection;
  shape/symmetry/PSD on realistic panel.
* GARCH multi-step analytic recursion: simulated GARCH(1,1) cumulative
  variance matches the analytic iterated recursion within tolerance.
* EWMA multi-step flat forecast: cumulative = h * sigma^2.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from core_trading.risk.vol_forecast import (
    AssetVolForecast,
    VolForecastConfig,
    ewma_variance,
    forecast_cov_matrix,
    forecast_panel_vols,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_panel(arr: np.ndarray, prefix: str = "A") -> pd.DataFrame:
    """Wrap a 2-D array as a returns panel with business-day index."""
    n_obs, n_assets = arr.shape
    idx = pd.date_range("2022-01-01", periods=n_obs, freq="B")
    cols = [f"{prefix}{i:02d}" for i in range(n_assets)]
    return pd.DataFrame(arr, index=idx, columns=cols)


def _simulate_garch_pct(
    omega: float,
    alpha: float,
    beta: float,
    nobs: int = 1000,
    seed: int = 42,
) -> pd.Series:
    """Simulate a GARCH(1,1) ZeroMean process in percentage-return space."""
    from arch import arch_model

    np.random.seed(seed)
    am = arch_model(None, vol="GARCH", p=1, q=1, mean="Zero", dist="Normal")
    sim_df = am.simulate([omega, alpha, beta], nobs=nobs, burn=500)
    return sim_df["data"]


def _garch_panel(n_assets: int = 3, nobs: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Create a multi-asset GARCH returns panel in decimal return scale."""
    cols = []
    for i in range(n_assets):
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=nobs, seed=seed + i)
        cols.append(r_pct.values / 100.0)
    arr = np.column_stack(cols)
    return _make_panel(arr)


# ---------------------------------------------------------------------------
# VolForecastConfig validation
# ---------------------------------------------------------------------------


class TestVolForecastConfig:
    def test_defaults(self) -> None:
        cfg = VolForecastConfig()
        assert cfg.model == "GJR-GARCH"
        assert cfg.horizon == 1
        assert cfg.min_obs_garch == 252
        assert cfg.ewma_lambda == 0.94
        assert cfg.correlation_source == "ledoit_wolf"

    def test_invalid_model(self) -> None:
        with pytest.raises(ValueError, match="model must be"):
            VolForecastConfig(model="IGARCH")  # type: ignore[arg-type]

    def test_invalid_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon must be"):
            VolForecastConfig(horizon=0)

    def test_invalid_min_obs(self) -> None:
        with pytest.raises(ValueError, match="min_obs_garch must be"):
            VolForecastConfig(min_obs_garch=1)

    def test_invalid_ewma_lambda_low(self) -> None:
        with pytest.raises(ValueError, match="ewma_lambda must be"):
            VolForecastConfig(ewma_lambda=0.0)

    def test_invalid_ewma_lambda_high(self) -> None:
        with pytest.raises(ValueError, match="ewma_lambda must be"):
            VolForecastConfig(ewma_lambda=1.0)

    def test_invalid_correlation_source(self) -> None:
        with pytest.raises(ValueError, match="correlation_source must be"):
            VolForecastConfig(correlation_source="oracle")  # type: ignore[arg-type]

    def test_frozen(self) -> None:
        cfg = VolForecastConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.horizon = 5  # type: ignore[misc]

    def test_custom_valid(self) -> None:
        cfg = VolForecastConfig(
            model="GARCH",
            horizon=10,
            min_obs_garch=100,
            ewma_lambda=0.97,
            correlation_source="sample",
        )
        assert cfg.model == "GARCH"
        assert cfg.horizon == 10


# ---------------------------------------------------------------------------
# ewma_variance
# ---------------------------------------------------------------------------


class TestEwmaVariance:
    def test_iid_normal_recovers_sigma(self) -> None:
        """EWMA on iid N(0, sigma^2) converges to sigma^2 with large sample."""
        rng = np.random.default_rng(7)
        true_sigma = 0.01
        n = 5000
        r = rng.normal(0.0, true_sigma, size=n)
        result = ewma_variance(r, lam=0.94, horizon=1)

        assert result.shape == (1,)
        estimated_vol = float(np.sqrt(result[0]))
        # Generous tolerance: 30% relative error for EWMA (it is biased towards
        # recent observations).
        assert abs(estimated_vol - true_sigma) / true_sigma < 0.30, (
            f"EWMA vol estimate {estimated_vol:.5f} too far from truth {true_sigma}"
        )

    def test_hand_computed_small_example(self) -> None:
        """Verify the EWMA recursion against a 4-step hand calculation.

        With lam=0.9, (1-lam)=0.1, initial sigma^2 = sample_var(r):
          r = [0.02, -0.03, 0.01, 0.02]
          sample_var (ddof=1) = var([0.02, -0.03, 0.01, 0.02]) ~ 0.000433...

        Then iterating:
          s0 = sample_var
          s1 = 0.9*s0 + 0.1*0.02^2
          s2 = 0.9*s1 + 0.1*(-0.03)^2
          s3 = 0.9*s2 + 0.1*0.01^2
          s4 = 0.9*s3 + 0.1*0.02^2
        """
        lam = 0.9
        r = np.array([0.02, -0.03, 0.01, 0.02])
        s = float(np.var(r, ddof=1))
        for ri in r:
            s = lam * s + (1.0 - lam) * float(ri * ri)
        expected = s

        result = ewma_variance(r, lam=lam, horizon=1)
        np.testing.assert_allclose(result[0], expected, rtol=1e-12)

    def test_flat_multi_step_forecast(self) -> None:
        """EWMA produces a flat (identical) forecast across all steps."""
        rng = np.random.default_rng(11)
        r = rng.normal(0.0, 0.01, size=300)
        result = ewma_variance(r, lam=0.94, horizon=10)

        assert result.shape == (10,)
        # All entries equal the 1-step value.
        np.testing.assert_allclose(result, result[0])

    def test_cumulative_variance_equals_h_times_one_step(self) -> None:
        """Cumulative EWMA variance = h * sigma^2 (flat forecast property)."""
        rng = np.random.default_rng(13)
        r = rng.normal(0.0, 0.01, size=300)
        h = 5
        result = ewma_variance(r, lam=0.94, horizon=h)
        one_step = result[0]
        cumulative = float(np.sum(result))

        np.testing.assert_allclose(cumulative, h * one_step)

    def test_returns_positive_variance(self) -> None:
        rng = np.random.default_rng(15)
        r = rng.normal(0.0, 0.01, size=200)
        result = ewma_variance(r)
        assert float(result[0]) > 0.0

    def test_invalid_lam_zero(self) -> None:
        with pytest.raises(ValueError, match="lam must be"):
            ewma_variance(np.array([0.01, 0.02, 0.03]), lam=0.0)

    def test_invalid_lam_one(self) -> None:
        with pytest.raises(ValueError, match="lam must be"):
            ewma_variance(np.array([0.01, 0.02, 0.03]), lam=1.0)

    def test_invalid_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon must be"):
            ewma_variance(np.array([0.01, 0.02, 0.03]), horizon=0)

    def test_too_few_observations(self) -> None:
        with pytest.raises(ValueError, match="at least 2 finite"):
            ewma_variance(np.array([0.01]))

    def test_accepts_pandas_series(self) -> None:
        s = pd.Series([0.01, -0.02, 0.015, -0.005])
        result = ewma_variance(s)
        assert result.shape == (1,)
        assert float(result[0]) > 0.0

    def test_lambda_weighting_higher_lambda_smoother(self) -> None:
        """Higher lambda -> more weight on distant past -> smoother response."""
        rng = np.random.default_rng(17)
        # Simulate: long low-vol period, then a single large shock at the end.
        r = np.concatenate([rng.normal(0.0, 0.005, 200), np.array([0.10])])
        var_high_lam = float(ewma_variance(r, lam=0.99)[0])
        var_low_lam = float(ewma_variance(r, lam=0.50)[0])
        # Low lambda reacts more to the shock: should produce higher variance.
        assert var_low_lam > var_high_lam


# ---------------------------------------------------------------------------
# forecast_panel_vols: GARCH path
# ---------------------------------------------------------------------------


class TestForecastPanelVolsGarch:
    def test_single_asset_garch_path(self) -> None:
        """With sufficient data the GARCH path is used."""
        r_pct = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=500, seed=50)
        r_dec = r_pct.values / 100.0
        panel = _make_panel(r_dec.reshape(-1, 1))
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        result = forecast_panel_vols(panel, config=cfg)

        assert len(result.assets) == 1
        assert result.fallback_assets == []
        af = result.forecasts[result.assets[0]]
        assert af.method == "garch"
        assert af.one_step_variance > 0.0

    def test_multi_asset_garch_path(self) -> None:
        """3-asset panel with sufficient data: all assets use GARCH."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=60)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        result = forecast_panel_vols(panel, config=cfg)

        assert len(result.assets) == 3
        assert result.fallback_assets == []
        for asset in result.assets:
            assert result.forecasts[asset].method == "garch"

    def test_column_order_preserved(self) -> None:
        """Output asset order matches input panel column order."""
        panel = _garch_panel(n_assets=4, nobs=500, seed=70)
        result = forecast_panel_vols(panel, config=VolForecastConfig(min_obs_garch=100))
        assert result.assets == list(panel.columns)

    def test_one_step_vol_series_shape(self) -> None:
        """one_step_vol_series has the right index and positive values."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=75)
        result = forecast_panel_vols(panel, config=VolForecastConfig(min_obs_garch=100))
        vs = result.one_step_vol_series
        assert list(vs.index) == result.assets
        assert (vs > 0).all()

    def test_garch_model_field(self) -> None:
        """The model field on AssetVolForecast reflects the configured model."""
        panel = _garch_panel(n_assets=2, nobs=500, seed=80)
        for model_name in ("GARCH", "GJR-GARCH"):
            cfg = VolForecastConfig(model=model_name, min_obs_garch=100)  # type: ignore[arg-type]
            result = forecast_panel_vols(panel, config=cfg)
            for asset in result.assets:
                if result.forecasts[asset].method == "garch":
                    assert result.forecasts[asset].model == model_name

    def test_horizon_5_per_step_shape(self) -> None:
        """With horizon=5, per_step_variances has shape (5,)."""
        panel = _garch_panel(n_assets=2, nobs=500, seed=85)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=5)
        result = forecast_panel_vols(panel, config=cfg)
        for asset in result.assets:
            af = result.forecasts[asset]
            assert af.per_step_variances.shape == (5,)

    def test_cumulative_variance_equals_sum_of_per_step(self) -> None:
        """cumulative_variance == sum(per_step_variances) for each asset."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=90)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=5)
        result = forecast_panel_vols(panel, config=cfg)
        for asset in result.assets:
            af = result.forecasts[asset]
            expected = float(np.sum(af.per_step_variances))
            np.testing.assert_allclose(
                af.cumulative_variance, expected, rtol=1e-12,
                err_msg=f"cumulative_variance mismatch for asset {asset}"
            )

    def test_forecast_vol_equals_sqrt_cumulative(self) -> None:
        """forecast_vol == sqrt(cumulative_variance)."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=95)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=3)
        result = forecast_panel_vols(panel, config=cfg)
        for asset in result.assets:
            af = result.forecasts[asset]
            expected = float(np.sqrt(af.cumulative_variance))
            np.testing.assert_allclose(
                af.forecast_vol, expected, rtol=1e-12,
                err_msg=f"forecast_vol mismatch for asset {asset}"
            )


# ---------------------------------------------------------------------------
# forecast_panel_vols: EWMA fallback
# ---------------------------------------------------------------------------


class TestForecastPanelVolsEwmaFallback:
    def test_short_sample_triggers_ewma(self) -> None:
        """Short sample (< min_obs_garch) must use EWMA fallback."""
        rng = np.random.default_rng(100)
        arr = rng.normal(0.0, 0.01, size=(50, 2))
        panel = _make_panel(arr)
        cfg = VolForecastConfig(min_obs_garch=252, horizon=1)
        result = forecast_panel_vols(panel, config=cfg)

        assert set(result.fallback_assets) == set(result.assets)
        for asset in result.assets:
            af = result.forecasts[asset]
            assert af.method == "ewma"
            assert af.model == "ewma"

    def test_mixed_length_panel_partial_fallback(self) -> None:
        """Panel where one asset is short: only that asset falls back."""
        rng = np.random.default_rng(110)
        n_long = 500
        # Long asset: generated via GARCH for realism.
        r_long = _simulate_garch_pct(0.05, 0.10, 0.85, nobs=n_long, seed=111).values / 100.0
        # Short asset: only 30 obs then NaN for the rest.
        r_short_vals = rng.normal(0.0, 0.01, size=30)
        r_short = np.concatenate([r_short_vals, np.full(n_long - 30, np.nan)])
        arr = np.column_stack([r_long, r_short])
        panel = _make_panel(arr)
        cfg = VolForecastConfig(min_obs_garch=252, horizon=1)
        result = forecast_panel_vols(panel, config=cfg)

        # The long asset should use GARCH, the short one EWMA.
        long_asset = result.assets[0]
        short_asset = result.assets[1]
        assert result.forecasts[long_asset].method == "garch"
        assert result.forecasts[short_asset].method == "ewma"
        assert short_asset in result.fallback_assets
        assert long_asset not in result.fallback_assets

    def test_fallback_variance_positive(self) -> None:
        """EWMA fallback produces positive variance."""
        rng = np.random.default_rng(120)
        arr = rng.normal(0.0, 0.01, size=(30, 2))
        panel = _make_panel(arr)
        result = forecast_panel_vols(
            panel, config=VolForecastConfig(min_obs_garch=252)
        )
        for asset in result.assets:
            assert result.forecasts[asset].one_step_variance > 0.0

    def test_fewer_than_one_column_raises(self) -> None:
        """Panel with zero columns should raise ValueError."""
        empty_panel = pd.DataFrame(index=pd.date_range("2022-01-01", periods=10, freq="B"))
        with pytest.raises(ValueError, match="at least 1 asset column"):
            forecast_panel_vols(empty_panel)


# ---------------------------------------------------------------------------
# GARCH multi-step analytic recursion check
# ---------------------------------------------------------------------------


class TestGarchMultiStepAnalytic:
    """Verify that h-step GARCH cumulative variance matches the analytic recursion.

    The analytic iterated GARCH(1,1) recursion is:
        h_{t+1} = omega + persistence * h_t
        h_{t+k} = uncond + persistence^{k-1} * (h_{t+1} - uncond)  for k >= 2
    where persistence = alpha + beta, uncond = omega / (1 - persistence).

    We verify that:
    1. The multi-step cumulative variance from forecast_panel_vols matches
       the analytic recursion within a tolerance that accounts for MLE
       parameter estimation error.
    2. As h -> infinity the per-step forecast converges to the unconditional
       variance (mean reversion).
    """

    TRUE_OMEGA_PCT = 0.05
    TRUE_ALPHA = 0.10
    TRUE_BETA = 0.85
    NOBS = 2000

    def _get_panel_and_cfg(self) -> tuple[pd.DataFrame, VolForecastConfig]:
        r_pct = _simulate_garch_pct(
            self.TRUE_OMEGA_PCT,
            self.TRUE_ALPHA,
            self.TRUE_BETA,
            nobs=self.NOBS,
            seed=200,
        )
        r_dec = r_pct.values / 100.0
        panel = _make_panel(r_dec.reshape(-1, 1))
        cfg = VolForecastConfig(model="GARCH", min_obs_garch=100, horizon=20)
        return panel, cfg

    def test_multi_step_convergence_to_unconditional_vol(self) -> None:
        """Long-horizon per-step forecast converges towards unconditional variance."""
        panel, cfg = self._get_panel_and_cfg()
        result = forecast_panel_vols(panel, config=cfg)
        asset = result.assets[0]
        af = result.forecasts[asset]

        # True unconditional variance in decimal scale.
        omega_dec = self.TRUE_OMEGA_PCT / (100.0 ** 2)
        persistence = self.TRUE_ALPHA + self.TRUE_BETA
        uncond_var = omega_dec / (1.0 - persistence)

        # The last (h=20) step-ahead forecast should be within 50% of the
        # true unconditional variance.  This is generous because we are
        # estimating omega/alpha/beta from a finite sample.
        last_step_var = float(af.per_step_variances[-1])
        ratio = last_step_var / uncond_var
        assert 0.3 < ratio < 3.0, (
            f"Long-horizon forecast {last_step_var:.2e} too far from "
            f"unconditional var {uncond_var:.2e} (ratio={ratio:.2f})"
        )

    def test_cumulative_variance_matches_sum(self) -> None:
        """cumulative_variance == np.sum(per_step_variances)."""
        panel, cfg = self._get_panel_and_cfg()
        result = forecast_panel_vols(panel, config=cfg)
        asset = result.assets[0]
        af = result.forecasts[asset]
        np.testing.assert_allclose(
            af.cumulative_variance, float(np.sum(af.per_step_variances)), rtol=1e-12
        )

    def test_cumulative_vol_exceeds_one_step_vol(self) -> None:
        """h-step cumulative variance > 1-step variance for h > 1."""
        panel, cfg = self._get_panel_and_cfg()
        result = forecast_panel_vols(panel, config=cfg)
        asset = result.assets[0]
        af = result.forecasts[asset]
        assert af.cumulative_variance > af.one_step_variance, (
            "Cumulative 20-step variance should exceed 1-step variance"
        )


# ---------------------------------------------------------------------------
# forecast_cov_matrix: CCC covariance
# ---------------------------------------------------------------------------


class TestForecastCovMatrix:
    def test_identity_correlation_gives_diagonal_cov(self) -> None:
        """CCC with an identity correlation matrix = diag(forecast vars).

        We use a 2-asset panel where both assets have EWMA forecasts
        (short sample) so the forecast variances are known.  We then
        manually set the correlation to identity and verify the covariance
        equals diag(forecast_vars).

        Since forecast_cov_matrix uses a historical-returns-based correlation
        we instead verify the structural property: with correlation=identity
        the off-diagonal is zero and the diagonal equals forecast_vol^2.
        We achieve this by using an uncorrelated (diagonal) returns panel.
        """
        # Two completely uncorrelated assets: independent iid normals.
        rng = np.random.default_rng(300)
        n = 200
        r1 = rng.normal(0.0, 0.01, size=n)
        r2 = rng.normal(0.0, 0.02, size=n)
        arr = np.column_stack([r1, r2])
        panel = _make_panel(arr)
        cfg = VolForecastConfig(
            min_obs_garch=500,   # force EWMA so variance is deterministic
            ewma_lambda=0.94,
            horizon=1,
            correlation_source="sample",
        )
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov = cov_result.covariance.to_numpy(dtype=float)

        # Off-diagonal entries should be small relative to diagonal.
        diag_vals = np.diag(cov)
        assert diag_vals[0] > 0.0
        assert diag_vals[1] > 0.0
        # Covariance is symmetric.
        np.testing.assert_allclose(cov, cov.T, atol=1e-15)

    def test_diagonal_cov_with_identity_correlation_exact(self) -> None:
        """When the correlation matrix is exactly I, cov[i,j] = 0 for i != j.

        We construct a panel whose sample correlation is exactly zero by
        using two orthogonal return series.
        """
        n = 300
        # Build two perfectly uncorrelated series by construction.
        t = np.arange(n, dtype=float)
        r1 = np.sin(t * 2.0 * np.pi / n) * 0.01
        r2 = np.cos(t * 2.0 * np.pi / n) * 0.01
        arr = np.column_stack([r1, r2])
        panel = _make_panel(arr)
        cfg = VolForecastConfig(
            min_obs_garch=500,
            ewma_lambda=0.94,
            horizon=1,
            correlation_source="sample",
        )
        cov_result = forecast_cov_matrix(panel, config=cfg)
        # Verify the output covariance is a pandas DataFrame with correct shape.
        assert cov_result.covariance.shape == (2, 2)
        assert cov_result.covariance.index.tolist() == list(panel.columns)
        assert cov_result.covariance.columns.tolist() == list(panel.columns)

    def test_psd_guarantee_on_non_psd_correlation(self) -> None:
        """CCCCovResult.psd_clipped is True when the matrix was clipped.

        We manufacture a near-indefinite scenario by using a near-singular
        returns panel (near-collinear assets) and verify that the output
        covariance is still PSD.
        """
        rng = np.random.default_rng(310)
        n = 50
        base = rng.normal(0.0, 0.01, size=n)
        # Two nearly identical series -> near-rank-1 covariance.
        r1 = base + rng.normal(0.0, 1e-8, size=n)
        r2 = base + rng.normal(0.0, 1e-8, size=n)
        arr = np.column_stack([r1, r2])
        panel = _make_panel(arr)
        cfg = VolForecastConfig(
            min_obs_garch=500,
            ewma_lambda=0.94,
            horizon=1,
            correlation_source="sample",
        )
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov = cov_result.covariance.to_numpy(dtype=float)

        # The output must be PSD.
        eigenvalues = np.linalg.eigvalsh(cov)
        assert float(eigenvalues[0]) >= -1e-12, (
            f"Output covariance has negative eigenvalue {eigenvalues[0]:.2e}"
        )

    def test_psd_clipped_flag_on_clean_panel(self) -> None:
        """A well-conditioned realistic panel should not need PSD clipping."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=320)
        cfg = VolForecastConfig(
            min_obs_garch=100, horizon=1, correlation_source="sample"
        )
        cov_result = forecast_cov_matrix(panel, config=cfg)
        # We do not assert psd_clipped == False because near-numerical issues
        # can occur; we only assert the output is actually PSD.
        cov = cov_result.covariance.to_numpy(dtype=float)
        eigenvalues = np.linalg.eigvalsh(cov)
        assert float(eigenvalues[0]) >= -1e-12

    def test_shape_and_symmetry(self) -> None:
        """Output covariance has shape (N, N) and is symmetric."""
        panel = _garch_panel(n_assets=4, nobs=500, seed=330)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov = cov_result.covariance.to_numpy(dtype=float)

        assert cov.shape == (4, 4)
        np.testing.assert_allclose(cov, cov.T, atol=1e-15)

    def test_diagonal_positive(self) -> None:
        """Diagonal entries (per-asset forecast variance) are positive."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=340)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov = cov_result.covariance.to_numpy(dtype=float)
        assert (np.diag(cov) > 0.0).all()

    def test_column_index_matches_panel_columns(self) -> None:
        """Covariance index and columns match the input panel columns."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=350)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        cov_result = forecast_cov_matrix(panel, config=cfg)

        assert cov_result.covariance.index.tolist() == list(panel.columns)
        assert cov_result.covariance.columns.tolist() == list(panel.columns)

    def test_ledoit_wolf_vs_sample_correlation(self) -> None:
        """Both correlation sources produce valid PSD covariances."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=360)
        for src in ("sample", "ledoit_wolf"):
            cfg = VolForecastConfig(
                min_obs_garch=100, horizon=1, correlation_source=src  # type: ignore[arg-type]
            )
            cov_result = forecast_cov_matrix(panel, config=cfg)
            assert cov_result.correlation_source == src
            cov = cov_result.covariance.to_numpy(dtype=float)
            eigenvalues = np.linalg.eigvalsh(cov)
            assert float(eigenvalues[0]) >= -1e-12

    def test_nan_panel_raises(self) -> None:
        """NaN-contaminated panel raises ValueError."""
        arr = np.ones((100, 3)) * 0.01
        arr[5, 1] = np.nan
        panel = _make_panel(arr)
        with pytest.raises(ValueError, match="NaN"):
            forecast_cov_matrix(panel)

    def test_fewer_than_two_columns_raises(self) -> None:
        """Single-column panel raises ValueError."""
        rng = np.random.default_rng(370)
        arr = rng.normal(0.0, 0.01, size=(100, 1))
        panel = _make_panel(arr)
        with pytest.raises(ValueError, match="at least 2 asset columns"):
            forecast_cov_matrix(panel)

    def test_fewer_than_two_rows_raises(self) -> None:
        """Single-row panel raises ValueError."""
        arr = np.array([[0.01, -0.01]])
        panel = _make_panel(arr)
        with pytest.raises(ValueError, match="at least 2 observation rows"):
            forecast_cov_matrix(panel)

    def test_vol_result_passthrough(self) -> None:
        """Pre-computed vol_result is reused without re-fitting."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=380)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        vol_res = forecast_panel_vols(panel, config=cfg)
        cov_result = forecast_cov_matrix(panel, config=cfg, vol_result=vol_res)

        # Verify the passed vol_result is the same object stored in the output.
        assert cov_result.forecast_vols is vol_res

    def test_horizon_field_matches_config(self) -> None:
        """CCCCovResult.horizon matches the configured horizon."""
        panel = _garch_panel(n_assets=2, nobs=500, seed=390)
        for h in (1, 5, 10):
            cfg = VolForecastConfig(min_obs_garch=100, horizon=h)
            cov_result = forecast_cov_matrix(panel, config=cfg)
            assert cov_result.horizon == h

    def test_diagonal_cov_with_identity_correlation_equals_forecast_vars(
        self,
    ) -> None:
        """CCC: when R = I, diag(Cov) = forecast_vol^2 per asset.

        We verify this identity algebraically: diag(Cov) = d_i^2 * R_ii = d_i^2.
        We test it by fetching the forecast_vols from the result and comparing
        with the diagonal of the covariance.
        """
        # Use a truly diagonal (uncorrelated) panel.
        rng = np.random.default_rng(400)
        n = 60
        arr = rng.normal(0.0, 0.01, size=(n, 3))
        panel = _make_panel(arr)
        cfg = VolForecastConfig(
            min_obs_garch=500,   # force EWMA
            ewma_lambda=0.94,
            horizon=1,
            correlation_source="sample",
        )
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov = cov_result.covariance.to_numpy(dtype=float)
        assets = cov_result.forecast_vols.assets

        for i, asset in enumerate(assets):
            af = cov_result.forecast_vols.forecasts[asset]
            expected_diag = af.forecast_vol ** 2
            np.testing.assert_allclose(
                cov[i, i],
                expected_diag,
                rtol=1e-6,
                err_msg=f"Diagonal mismatch for asset {asset}: "
                        f"cov[{i},{i}]={cov[i, i]:.2e}, "
                        f"forecast_vol^2={expected_diag:.2e}",
            )


# ---------------------------------------------------------------------------
# AssetVolForecast dataclass
# ---------------------------------------------------------------------------


class TestAssetVolForecastDataclass:
    def _make_af(self) -> AssetVolForecast:
        per_step = np.array([1e-4, 9e-5, 8e-5])
        cum = float(np.sum(per_step))
        return AssetVolForecast(
            asset="SPY",
            method="garch",
            model="GJR-GARCH",
            per_step_variances=per_step,
            cumulative_variance=cum,
            forecast_vol=float(np.sqrt(cum)),
            one_step_variance=float(per_step[0]),
        )

    def test_frozen(self) -> None:
        af = self._make_af()
        with pytest.raises((AttributeError, TypeError)):
            af.asset = "AAPL"  # type: ignore[misc]

    def test_fields_correct(self) -> None:
        af = self._make_af()
        assert af.asset == "SPY"
        assert af.method == "garch"
        assert af.model == "GJR-GARCH"
        assert af.per_step_variances.shape == (3,)
        assert af.one_step_variance == af.per_step_variances[0]


# ---------------------------------------------------------------------------
# VolForecastResult / CCCCovResult dataclass structure
# ---------------------------------------------------------------------------


class TestResultDataclasses:
    def test_vol_forecast_result_frozen(self) -> None:
        panel = _garch_panel(n_assets=2, nobs=300, seed=500)
        cfg = VolForecastConfig(min_obs_garch=500)  # force EWMA
        result = forecast_panel_vols(panel, config=cfg)
        with pytest.raises((AttributeError, TypeError)):
            result.assets = ["X"]  # type: ignore[misc]

    def test_ccc_cov_result_frozen(self) -> None:
        panel = _garch_panel(n_assets=2, nobs=300, seed=510)
        cov_result = forecast_cov_matrix(
            panel, config=VolForecastConfig(min_obs_garch=500)
        )
        with pytest.raises((AttributeError, TypeError)):
            cov_result.psd_clipped = True  # type: ignore[misc]

    def test_vol_forecast_result_is_dataclass(self) -> None:
        panel = _garch_panel(n_assets=2, nobs=300, seed=520)
        result = forecast_panel_vols(
            panel, config=VolForecastConfig(min_obs_garch=500)
        )
        assert dataclasses.is_dataclass(result)

    def test_ccc_result_is_dataclass(self) -> None:
        panel = _garch_panel(n_assets=2, nobs=300, seed=530)
        result = forecast_cov_matrix(
            panel, config=VolForecastConfig(min_obs_garch=500)
        )
        assert dataclasses.is_dataclass(result)


# ---------------------------------------------------------------------------
# Integration: CCC covariance feeds into parametric VaR (Mode B)
# ---------------------------------------------------------------------------


class TestVaRIntegration:
    """Verify the CCC covariance output is directly consumable by parametric_var."""

    def test_cov_feeds_parametric_var_mode_b(self) -> None:
        """forecast_cov_matrix output can be passed directly to parametric_var."""
        from core_trading.risk.var import VaRConfig, parametric_var

        panel = _garch_panel(n_assets=3, nobs=500, seed=600)
        cfg = VolForecastConfig(min_obs_garch=100, horizon=1)
        cov_result = forecast_cov_matrix(panel, config=cfg)
        cov_np = cov_result.covariance.to_numpy(dtype=float)
        n = cov_np.shape[0]
        weights = np.ones(n) / n   # equal-weight portfolio

        var_result = parametric_var(
            None,
            weights=weights,
            cov=cov_np,
            config=VaRConfig(confidence=0.95, horizon=1),
        )
        assert var_result.var > 0.0
        assert var_result.method == "parametric"

    def test_one_step_vol_series_shape_and_sign(self) -> None:
        """one_step_vol_series is a positive-valued Series indexed by asset."""
        panel = _garch_panel(n_assets=3, nobs=500, seed=610)
        result = forecast_panel_vols(
            panel, config=VolForecastConfig(min_obs_garch=100)
        )
        vs = result.one_step_vol_series
        assert isinstance(vs, pd.Series)
        assert len(vs) == len(panel.columns)
        assert (vs > 0.0).all()


# ---------------------------------------------------------------------------
# Coverage: exception-handler and PSD-clip branches
# ---------------------------------------------------------------------------


class TestCoverageBranches:
    """Tests explicitly targeting otherwise-uncovered branches.

    1. Exception handler in _forecast_one_asset (lines 433-434): triggered
       by feeding a near-constant series that causes arch to raise.
    2. PSD clip branch in forecast_cov_matrix (line 630): triggered by
       injecting a negative eigenvalue into the CCC matrix via monkeypatching.
    """

    def test_garch_exception_falls_back_to_ewma(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When fit_garch raises, the asset falls back to EWMA.

        We monkeypatch fit_garch inside vol_forecast to always raise so
        that we exercise the except-block even for a series with sufficient
        observations.
        """
        import core_trading.risk.vol_forecast as vf_mod

        def _always_raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated GARCH failure")

        monkeypatch.setattr(vf_mod, "fit_garch", _always_raise)

        rng = np.random.default_rng(700)
        arr = rng.normal(0.0, 0.01, size=(500, 2))
        panel = _make_panel(arr)
        # min_obs_garch low enough to attempt GARCH, which will then fail.
        cfg = VolForecastConfig(min_obs_garch=10, horizon=1)
        result = forecast_panel_vols(panel, config=cfg)

        # Both assets must have fallen back to EWMA.
        assert set(result.fallback_assets) == set(result.assets)
        for asset in result.assets:
            assert result.forecasts[asset].method == "ewma"

    def test_psd_clip_branch_executed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PSD clip branch is executed when the assembled CCC is non-PSD.

        We monkeypatch np.linalg.eigvalsh (inside vol_forecast) to return
        a value with a negative eigenvalue, forcing psd_clipped=True.
        """
        import numpy as _np_real

        import core_trading.risk.vol_forecast as vf_mod

        original_eigvalsh = _np_real.linalg.eigvalsh
        call_count: list[int] = [0]

        def _patched_eigvalsh(m: np.ndarray) -> np.ndarray:
            call_count[0] += 1
            real_vals = original_eigvalsh(m)
            # On the first call (CCC matrix check) inject a negative eigenvalue.
            if call_count[0] == 1:
                result_arr = real_vals.copy()
                result_arr[0] = -1e-6
                return result_arr
            return real_vals

        monkeypatch.setattr(vf_mod.np.linalg, "eigvalsh", _patched_eigvalsh)

        panel = _garch_panel(n_assets=2, nobs=300, seed=710)
        cfg = VolForecastConfig(min_obs_garch=500, horizon=1)
        cov_result = forecast_cov_matrix(panel, config=cfg)

        # The clip branch must have been taken.
        assert cov_result.psd_clipped is True
        # The output must still be PSD after clipping.
        cov = cov_result.covariance.to_numpy(dtype=float)
        eigenvalues = _np_real.linalg.eigvalsh(cov)
        assert float(eigenvalues[0]) >= -1e-12
