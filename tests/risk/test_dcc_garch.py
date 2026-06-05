"""Tests for core_trading.risk.dcc_garch (DCC-GARCH, Engle 2002).

All tests run under ``pytest -W error`` with no extra warning filters: the
module catches ``arch``'s ConvergenceWarning internally (surfacing it via the
per-asset ``garch_converged`` flags) and ``fit_garch``'s pct-return rescaling
neutralises the DataScaleWarning, so nothing leaks here.

Design / runtime notes
----------------------
* The two simulated panels (2-asset and 4-asset DCC processes with known
  ``a = 0.05``, ``b = 0.90``) and the constant-correlation (CCC-reduction)
  panel are fitted once each at module scope via fixtures, because the stage-1
  ``arch`` GARCH fits dominate runtime.  Every assertion-level test reuses a
  cached :class:`DCCResult`.
* Sample length is held at ``T = 1500`` so the whole file fits comfortably
  under the ~30s budget while still recovering ``(a, b)`` to a meaningful
  tolerance.
* All randomness uses ``numpy.random.default_rng`` with fixed seeds so the
  panels (and therefore the fits) are reproducible.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from core_trading.risk import dcc_garch as _dcc_mod
from core_trading.risk.dcc_garch import (
    DCCConfig,
    DCCResult,
    dcc_correlation_series,
    dcc_forecast_correlation,
    dcc_forward_covariance,
    fit_dcc,
)

# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

_OMEGA = 1e-5
_ALPHA = 0.05
_BETA = 0.90


def _simulate_dcc_panel(
    n_assets: int,
    a: float,
    b: float,
    *,
    t_obs: int,
    seed: int,
    base_corr: float = 0.3,
    burn: int = 500,
) -> pd.DataFrame:
    """Simulate an N-asset scalar-DCC(1,1) process with GARCH(1,1) margins.

    Each asset has the same GARCH(1,1) variance recursion (omega, alpha, beta)
    and the cross-asset standardized residuals follow the DCC recursion driving
    ``Q_t`` around a constant target ``Q_bar`` with all off-diagonals equal to
    ``base_corr``.

    Parameters
    ----------
    n_assets:
        Number of assets N.
    a, b:
        True DCC coefficients used to generate the data.
    t_obs:
        Number of retained observation rows (after burn-in).
    seed:
        Seed for ``numpy.random.default_rng``.
    base_corr:
        Constant off-diagonal of the target correlation ``Q_bar``.
    burn:
        Burn-in rows discarded before retaining ``t_obs`` rows.

    Returns
    -------
    pandas.DataFrame
        ``t_obs x n_assets`` decimal-return panel with columns ``A0..A{N-1}``.
    """
    rng = np.random.default_rng(seed)
    n = n_assets
    q_bar = np.full((n, n), base_corr)
    np.fill_diagonal(q_bar, 1.0)
    q_mat = q_bar.copy()
    eps_prev = np.zeros(n)
    h = np.full(n, _OMEGA / (1.0 - _ALPHA - _BETA))
    r_prev = np.zeros(n)

    rows: list[np.ndarray] = []
    for t in range(t_obs + burn):
        q_mat = (1.0 - a - b) * q_bar + a * np.outer(eps_prev, eps_prev) + b * q_mat
        d = 1.0 / np.sqrt(np.diag(q_mat))
        r_corr = q_mat * np.outer(d, d)
        np.fill_diagonal(r_corr, 1.0)
        chol = np.linalg.cholesky(r_corr)
        z = chol @ rng.standard_normal(n)
        h = _OMEGA + _ALPHA * r_prev**2 + _BETA * h
        r = np.sqrt(h) * z
        if t >= burn:
            rows.append(r)
        eps_prev = z
        r_prev = r

    arr = np.array(rows, dtype=float)
    cols = [f"A{i}" for i in range(n)]
    return pd.DataFrame(arr, columns=cols)


def _simulate_ccc_panel(
    *, t_obs: int, seed: int, burn: int = 500
) -> pd.DataFrame:
    """Simulate a 3-asset *constant*-correlation process (a = b = 0 in DCC).

    GARCH(1,1) margins but a fixed correlation matrix, so the fitted DCC ``a``
    should be near zero and the ``R_t`` path nearly constant.
    """
    rng = np.random.default_rng(seed)
    r_corr = np.array(
        [[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]], dtype=float
    )
    chol = np.linalg.cholesky(r_corr)
    n = 3
    h = np.full(n, _OMEGA / (1.0 - _ALPHA - _BETA))
    r_prev = np.zeros(n)
    rows: list[np.ndarray] = []
    for t in range(t_obs + burn):
        z = chol @ rng.standard_normal(n)
        h = _OMEGA + _ALPHA * r_prev**2 + _BETA * h
        r = np.sqrt(h) * z
        if t >= burn:
            rows.append(r)
        r_prev = r
    arr = np.array(rows, dtype=float)
    return pd.DataFrame(arr, columns=["X", "Y", "Z"])


# ---------------------------------------------------------------------------
# Module-scope fixtures (fit the expensive panels once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def panel2() -> pd.DataFrame:
    """2-asset DCC panel with true a=0.05, b=0.90."""
    return _simulate_dcc_panel(2, 0.05, 0.90, t_obs=1500, seed=7)


@pytest.fixture(scope="module")
def panel4() -> pd.DataFrame:
    """4-asset DCC panel with true a=0.05, b=0.90."""
    return _simulate_dcc_panel(4, 0.05, 0.90, t_obs=1500, seed=13)


@pytest.fixture(scope="module")
def ccc_panel() -> pd.DataFrame:
    """3-asset constant-correlation panel (DCC reduces to CCC)."""
    return _simulate_ccc_panel(t_obs=1500, seed=11)


@pytest.fixture(scope="module")
def result2(panel2: pd.DataFrame) -> DCCResult:
    """Fitted DCC on the 2-asset panel."""
    return fit_dcc(panel2, config=DCCConfig(min_observations=250))


@pytest.fixture(scope="module")
def result4(panel4: pd.DataFrame) -> DCCResult:
    """Fitted DCC on the 4-asset panel."""
    return fit_dcc(panel4, config=DCCConfig(min_observations=250))


@pytest.fixture(scope="module")
def result_ccc(ccc_panel: pd.DataFrame) -> DCCResult:
    """Fitted DCC on the constant-correlation panel."""
    return fit_dcc(ccc_panel, config=DCCConfig(min_observations=250))


# ---------------------------------------------------------------------------
# DCCConfig validation
# ---------------------------------------------------------------------------


class TestDCCConfig:
    """Validation and defaults of :class:`DCCConfig`."""

    def test_defaults(self) -> None:
        cfg = DCCConfig()
        assert cfg.univariate_model == "GARCH"
        assert cfg.horizon == 1
        assert cfg.min_observations == 250
        assert cfg.a0 == 0.02
        assert cfg.b0 == 0.97
        assert cfg.optimizer == "SLSQP"

    def test_frozen(self) -> None:
        cfg = DCCConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.horizon = 5  # type: ignore[misc]

    def test_bad_model(self) -> None:
        with pytest.raises(ValueError, match="univariate_model"):
            DCCConfig(univariate_model="FOO")

    def test_bad_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            DCCConfig(horizon=0)

    def test_bad_min_observations(self) -> None:
        with pytest.raises(ValueError, match="min_observations"):
            DCCConfig(min_observations=1)

    def test_negative_a0(self) -> None:
        with pytest.raises(ValueError, match="a0"):
            DCCConfig(a0=-0.1)

    def test_negative_b0(self) -> None:
        with pytest.raises(ValueError, match="b0"):
            DCCConfig(b0=-0.1)

    def test_a0_b0_sum_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="a0 \\+ b0"):
            DCCConfig(a0=0.6, b0=0.6)

    def test_bad_stationarity_eps(self) -> None:
        with pytest.raises(ValueError, match="stationarity_eps"):
            DCCConfig(stationarity_eps=0.0)

    def test_bad_optimizer(self) -> None:
        with pytest.raises(ValueError, match="optimizer"):
            DCCConfig(optimizer="newton")

    def test_bad_max_iter(self) -> None:
        with pytest.raises(ValueError, match="max_iter"):
            DCCConfig(max_iter=0)


# ---------------------------------------------------------------------------
# Parameter recovery
# ---------------------------------------------------------------------------


class TestParameterRecovery:
    """Stage-2 (a, b) recovery on simulated DCC processes."""

    def test_recovery_2asset(self, result2: DCCResult) -> None:
        assert result2.converged is True
        assert result2.a == pytest.approx(0.05, abs=0.04)
        assert result2.b == pytest.approx(0.90, abs=0.06)
        assert result2.a >= 0.0
        assert result2.b >= 0.0
        assert result2.a + result2.b < 1.0

    def test_recovery_4asset(self, result4: DCCResult) -> None:
        assert result4.converged is True
        assert result4.a == pytest.approx(0.05, abs=0.04)
        assert result4.b == pytest.approx(0.90, abs=0.06)
        assert result4.a + result4.b < 1.0

    def test_result_shapes_2asset(self, result2: DCCResult) -> None:
        assert result2.n_assets == 2
        assert result2.n_obs == 1500
        assert result2.sigmas.shape == (1500, 2)
        assert result2.std_resid.shape == (1500, 2)
        assert result2.correlations.shape == (1500, 2, 2)
        assert result2.q_path.shape == (1500, 2, 2)
        assert result2.q_bar.shape == (2, 2)

    def test_garch_metadata(self, result4: DCCResult) -> None:
        assert set(result4.garch_params) == {"A0", "A1", "A2", "A3"}
        assert set(result4.garch_converged) == {"A0", "A1", "A2", "A3"}
        for params in result4.garch_params.values():
            assert "omega" in params
            assert "alpha" in params
            assert "beta" in params

    def test_loglikelihood_finite(self, result2: DCCResult) -> None:
        assert np.isfinite(result2.loglikelihood)

    def test_gjr_margins(self, panel2: pd.DataFrame) -> None:
        # An asymmetric univariate model still yields a valid DCC fit.
        res = fit_dcc(
            panel2,
            config=DCCConfig(univariate_model="GJR-GARCH", min_observations=250),
        )
        assert res.converged is True
        assert res.a + res.b < 1.0
        for params in res.garch_params.values():
            assert "gamma" in params


# ---------------------------------------------------------------------------
# CCC reduction
# ---------------------------------------------------------------------------


class TestCCCReduction:
    """When the data have constant correlation, DCC should collapse to CCC."""

    def test_a_near_zero(self, result_ccc: DCCResult) -> None:
        assert result_ccc.a == pytest.approx(0.0, abs=0.02)

    def test_rt_path_nearly_constant(self, result_ccc: DCCResult) -> None:
        # Off-diagonal [0,1] correlation should barely move across the path.
        path01 = result_ccc.correlations[:, 0, 1]
        assert float(np.std(path01)) < 0.02

    def test_forecast_matches_qbar_corr(self, result_ccc: DCCResult) -> None:
        fc = dcc_forecast_correlation(result_ccc, horizon=10)
        q_bar = result_ccc.q_bar
        d = 1.0 / np.sqrt(np.diag(q_bar))
        r_qbar = q_bar * np.outer(d, d)
        np.fill_diagonal(r_qbar, 1.0)
        assert np.allclose(fc, r_qbar, atol=0.05)


# ---------------------------------------------------------------------------
# Validity of the R_t path
# ---------------------------------------------------------------------------


class TestCorrelationPathValidity:
    """Every R_t in the path must be a valid correlation matrix."""

    @pytest.mark.parametrize("which", ["result2", "result4", "result_ccc"])
    def test_path_is_valid(self, which: str, request: pytest.FixtureRequest) -> None:
        result: DCCResult = request.getfixturevalue(which)
        path = result.correlations
        n = result.n_assets
        diag_idx = np.arange(n)
        # Unit diagonal.
        assert np.allclose(path[:, diag_idx, diag_idx], 1.0)
        # Symmetric.
        assert np.allclose(path, path.transpose(0, 2, 1))
        # Off-diagonals in [-1, 1].
        assert path.min() >= -1.0 - 1e-9
        assert path.max() <= 1.0 + 1e-9
        # PSD at every step (check a sample of indices to keep runtime down).
        sample = np.linspace(0, path.shape[0] - 1, 50, dtype=int)
        for t in sample:
            eig = np.linalg.eigvalsh(path[t])
            assert eig.min() >= -1e-8

    def test_correlation_at_accessor(self, result2: DCCResult) -> None:
        mat = result2.correlation_at(-1)
        assert mat.shape == (2, 2)
        assert np.allclose(np.diag(mat), 1.0)
        # Returned matrix is a copy (mutating it must not change the result).
        mat[0, 1] = 99.0
        assert result2.correlations[-1, 0, 1] != 99.0


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------


class TestForecastCorrelation:
    """h-step correlation forecast properties."""

    def test_horizon_one_matches_recursion(self, result2: DCCResult) -> None:
        fc = dcc_forecast_correlation(result2, horizon=1)
        assert fc.shape == (2, 2)
        assert np.allclose(np.diag(fc), 1.0)
        assert np.allclose(fc, fc.T)

    def test_uses_config_horizon_by_default(self, panel2: pd.DataFrame) -> None:
        res = fit_dcc(panel2, config=DCCConfig(horizon=3, min_observations=250))
        default_fc = dcc_forecast_correlation(res)
        explicit_fc = dcc_forecast_correlation(res, horizon=3)
        assert np.allclose(default_fc, explicit_fc)

    def test_mean_reversion(self, result2: DCCResult) -> None:
        # As horizon grows, the forecast approaches the Q_bar-implied corr.
        q_bar = result2.q_bar
        d = 1.0 / np.sqrt(np.diag(q_bar))
        r_long = q_bar * np.outer(d, d)
        np.fill_diagonal(r_long, 1.0)
        near = dcc_forecast_correlation(result2, horizon=1)
        far = dcc_forecast_correlation(result2, horizon=500)
        dist_near = abs(near[0, 1] - r_long[0, 1])
        dist_far = abs(far[0, 1] - r_long[0, 1])
        assert dist_far <= dist_near + 1e-9
        assert np.allclose(far, r_long, atol=1e-6)

    def test_bad_horizon(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="horizon"):
            dcc_forecast_correlation(result2, horizon=0)


class TestForwardCovariance:
    """Forward covariance PSD guarantee and vol combination."""

    def test_diagonal_matches_vol_squared(self, result4: DCCResult) -> None:
        vols = np.array([0.01, 0.02, 0.015, 0.03])
        cov = dcc_forward_covariance(result4, vols, horizon=1)
        assert cov.shape == (4, 4)
        assert np.allclose(np.diag(cov), vols**2, rtol=1e-6)

    def test_psd(self, result4: DCCResult) -> None:
        rng = np.random.default_rng(99)
        for _ in range(10):
            vols = rng.uniform(0.005, 0.05, size=4)
            cov = dcc_forward_covariance(result4, vols, horizon=3)
            eig = np.linalg.eigvalsh(cov)
            assert eig.min() >= -1e-10

    def test_symmetric(self, result2: DCCResult) -> None:
        cov = dcc_forward_covariance(result2, np.array([0.01, 0.02]))
        assert np.allclose(cov, cov.T)

    def test_series_input_reindexed(self, result2: DCCResult) -> None:
        # Series given out of asset order is reindexed by result.assets.
        vols = pd.Series({"A1": 0.02, "A0": 0.01})
        cov = dcc_forward_covariance(result2, vols, horizon=1)
        assert cov[0, 0] == pytest.approx(0.01**2, rel=1e-6)
        assert cov[1, 1] == pytest.approx(0.02**2, rel=1e-6)

    def test_series_missing_asset(self, result2: DCCResult) -> None:
        vols = pd.Series({"A0": 0.01})
        with pytest.raises(ValueError, match="missing asset"):
            dcc_forward_covariance(result2, vols)

    def test_wrong_length_array(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="does not match"):
            dcc_forward_covariance(result2, np.array([0.01, 0.02, 0.03]))

    def test_non_finite_vols(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            dcc_forward_covariance(result2, np.array([0.01, np.nan]))

    def test_negative_vols(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="negative"):
            dcc_forward_covariance(result2, np.array([0.01, -0.02]))

    def test_psd_clip_branch(self) -> None:
        # Force a non-PSD assembly by monkeying a correlation outside [-1, 1].
        # We build the covariance manually with an invalid correlation to make
        # sure the nearest_psd clip path runs and yields a PSD result.
        # (Direct construction so we exercise the clip without an artificial
        # DCCResult.)
        from core_trading.portfolio.covariance import nearest_psd

        bad_corr = np.array([[1.0, 1.5], [1.5, 1.0]])
        vols = np.array([0.01, 0.02])
        cov = np.outer(vols, vols) * bad_corr
        eig = np.linalg.eigvalsh(cov)
        assert eig.min() < 0.0
        fixed = nearest_psd(cov, epsilon=0.0)
        assert np.linalg.eigvalsh(fixed).min() >= -1e-12


class TestCorrelationSeries:
    """Pairwise time-varying correlation extraction."""

    def test_series_length_and_name(self, result4: DCCResult) -> None:
        s = dcc_correlation_series(result4, ("A0", "A2"))
        assert isinstance(s, pd.Series)
        assert len(s) == result4.n_obs
        assert s.name == "corr_A0_A2"

    def test_series_matches_path(self, result2: DCCResult) -> None:
        s = dcc_correlation_series(result2, ("A0", "A1"))
        assert np.allclose(s.to_numpy(), result2.correlations[:, 0, 1])

    def test_symmetry_of_pair(self, result2: DCCResult) -> None:
        s_ij = dcc_correlation_series(result2, ("A0", "A1"))
        s_ji = dcc_correlation_series(result2, ("A1", "A0"))
        assert np.allclose(s_ij.to_numpy(), s_ji.to_numpy())

    def test_identical_assets(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="distinct"):
            dcc_correlation_series(result2, ("A0", "A0"))

    def test_unknown_first_asset(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="unknown asset"):
            dcc_correlation_series(result2, ("ZZ", "A1"))

    def test_unknown_second_asset(self, result2: DCCResult) -> None:
        with pytest.raises(ValueError, match="unknown asset"):
            dcc_correlation_series(result2, ("A0", "ZZ"))


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------


class TestValidation:
    """Panel validation in :func:`fit_dcc`."""

    def test_too_few_columns(self) -> None:
        df = pd.DataFrame({"A0": np.random.default_rng(0).standard_normal(300)})
        with pytest.raises(ValueError, match="at least 2 asset columns"):
            fit_dcc(df)

    def test_too_few_rows(self) -> None:
        rng = np.random.default_rng(1)
        df = pd.DataFrame(rng.standard_normal((100, 2)), columns=["A0", "A1"])
        with pytest.raises(ValueError, match="min_observations"):
            fit_dcc(df, config=DCCConfig(min_observations=250))

    def test_nan_rejected(self) -> None:
        rng = np.random.default_rng(2)
        arr = rng.standard_normal((300, 2))
        arr[5, 1] = np.nan
        df = pd.DataFrame(arr, columns=["A0", "A1"])
        with pytest.raises(ValueError, match="NaN"):
            fit_dcc(df, config=DCCConfig(min_observations=250))

    def test_constant_column_rejected(self) -> None:
        rng = np.random.default_rng(3)
        arr = rng.standard_normal((300, 2)) * 0.01
        arr[:, 1] = 0.0
        df = pd.DataFrame(arr, columns=["A0", "A1"])
        with pytest.raises(ValueError, match="constant"):
            fit_dcc(df, config=DCCConfig(min_observations=250))


# ---------------------------------------------------------------------------
# L-BFGS-B optimiser path + determinism
# ---------------------------------------------------------------------------


class TestOptimizerAndDeterminism:
    """Alternate optimiser branch and reproducibility."""

    def test_lbfgsb_path(self, panel2: pd.DataFrame) -> None:
        res = fit_dcc(
            panel2,
            config=DCCConfig(optimizer="L-BFGS-B", min_observations=250),
        )
        assert res.a >= 0.0
        assert res.b >= 0.0
        assert res.a + res.b < 1.0

    def test_determinism(self, panel2: pd.DataFrame) -> None:
        cfg = DCCConfig(min_observations=250)
        r1 = fit_dcc(panel2, config=cfg)
        r2 = fit_dcc(panel2, config=cfg)
        assert r1.a == r2.a
        assert r1.b == r2.b
        assert r1.loglikelihood == r2.loglikelihood
        assert np.array_equal(r1.correlations, r2.correlations)


# ---------------------------------------------------------------------------
# Internal defensive branches (negloglik guards, clip path, convergence flag)
# ---------------------------------------------------------------------------


class TestInternalGuards:
    """Directly exercise the defensive guards that valid simulated data skips."""

    def _eps_qbar(self) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(5)
        eps = rng.standard_normal((40, 2))
        q_bar = np.cov(eps, rowvar=False, ddof=1)
        q_bar = (q_bar + q_bar.T) / 2.0
        return eps, q_bar

    def test_negloglik_infeasible_params_penalty(self) -> None:
        # a + b above the stationarity bound returns the large penalty.
        eps, q_bar = self._eps_qbar()
        val = _dcc_mod._dcc_negloglik(
            np.array([0.6, 0.6]), eps, q_bar, 1e-4
        )
        assert val == pytest.approx(1e12)

    def test_negloglik_negative_param_penalty(self) -> None:
        eps, q_bar = self._eps_qbar()
        val = _dcc_mod._dcc_negloglik(
            np.array([-0.1, 0.5]), eps, q_bar, 1e-4
        )
        assert val == pytest.approx(1e12)

    def test_negloglik_singular_correlation_penalty(self) -> None:
        # A rank-deficient Q_bar makes R_t singular -> slogdet/solve guard.
        eps = np.tile(np.array([1.0, 1.0]), (30, 1))
        # eps with perfectly collinear columns -> Q_bar singular correlation.
        q_bar = np.array([[1.0, 1.0], [1.0, 1.0]])
        val = _dcc_mod._dcc_negloglik(
            np.array([0.05, 0.9]), eps, q_bar, 1e-4
        )
        assert val == pytest.approx(1e12)

    def test_negloglik_linalg_error_penalty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # slogdet is fine but solve raises LinAlgError -> defensive penalty.
        # (Belt-and-braces: a PD R_t never makes solve raise in practice, so
        # we force it to exercise the guard.)
        eps, q_bar = self._eps_qbar()

        def _raise(*_a: object, **_k: object) -> np.ndarray:
            raise np.linalg.LinAlgError("forced")

        monkeypatch.setattr(np.linalg, "solve", _raise)
        val = _dcc_mod._dcc_negloglik(
            np.array([0.05, 0.9]), eps, q_bar, 1e-4
        )
        assert val == pytest.approx(1e12)

    def test_forward_covariance_clip_path(
        self, result2: DCCResult, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force an invalid (out-of-range) correlation so the assembled
        # covariance is indefinite and the nearest_psd clip branch runs.
        bad = np.array([[1.0, 1.5], [1.5, 1.0]])
        monkeypatch.setattr(
            _dcc_mod, "dcc_forecast_correlation", lambda *_a, **_k: bad
        )
        cov = dcc_forward_covariance(result2, np.array([0.01, 0.02]), horizon=1)
        assert np.linalg.eigvalsh(cov).min() >= -1e-12

    def test_convergence_flag_false_on_arch_warning(
        self, panel2: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate an arch ConvergenceWarning during stage 1 and assert the
        # per-asset flag and the overall flag both record non-convergence.
        from arch.utility.exceptions import ConvergenceWarning

        real_fit = _dcc_mod.fit_garch
        state = {"first": True}

        def _warning_fit(
            returns_col: np.ndarray, *, config: object
        ) -> object:
            res = real_fit(returns_col, config=config)  # type: ignore[arg-type]
            if state["first"]:
                state["first"] = False
                import warnings as _w

                _w.warn("forced", ConvergenceWarning, stacklevel=2)
            return res

        monkeypatch.setattr(_dcc_mod, "fit_garch", _warning_fit)
        res = fit_dcc(panel2, config=DCCConfig(min_observations=250))
        assert res.garch_converged["A0"] is False
        assert res.converged is False
