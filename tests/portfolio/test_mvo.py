"""Tests for core_trading.portfolio.mvo (Phase 6.1).

Covers:
* MVOConfig validation of every parameter bound.
* Closed-form agreement (KKT solutions computed independently with numpy):
  utility mode vs the budget-constrained Markowitz solution, min-variance
  vs Sigma^{-1} 1 / (1' Sigma^{-1} 1), target-return mode vs the Merton
  frontier formulas (binding) and the min-variance degeneracy (slack).
* Every constraint: long-only corner solutions, gross-leverage cap,
  per-asset cap, sector caps (incl. validation), turnover cap (incl. the
  cap = 0 pin and the missing-prev_weights error).
* Infeasibility raising with solver status (never silent garbage).
* Input validation: sigma shape/labels/NaN/asymmetry/indefiniteness,
  misaligned mu / prev_weights.
* bayes_stein_means: exact agreement with an explicit-inverse reference,
  Stein dominance over the sample mean on synthetic truth, the
  zero-dispersion degeneracy, T >= N + 3 and singularity guards.
* Phase 6 DOD sensitivity: with Ledoit-Wolf covariance a small mu
  perturbation moves the weights a little; with the raw sample covariance
  it moves them a lot (the matrix-inversion-instability check).
* Phase 6 DOD performance: 20-asset solves complete in < 1 s.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.covariance import (
    ledoit_wolf_covariance,
    sample_covariance,
)
from core_trading.portfolio.mvo import (
    MVOConfig,
    MVOResult,
    bayes_stein_means,
    mean_variance_weights,
    min_variance_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assets(n: int) -> list[str]:
    return [f"A{i:02d}" for i in range(n)]


def _sigma_df(arr: np.ndarray) -> pd.DataFrame:
    names = _assets(arr.shape[0])
    return pd.DataFrame(np.asarray(arr, dtype=float), index=names, columns=names)


def _mu_series(values: list[float] | np.ndarray) -> pd.Series:
    arr = np.asarray(values, dtype=float)
    return pd.Series(arr, index=_assets(arr.shape[0]))


def _random_pd_sigma(rng: np.random.Generator, n: int) -> pd.DataFrame:
    q, _ = np.linalg.qr(rng.standard_normal((n, n)))
    eigenvalues = rng.uniform(0.5, 2.0, size=n)
    sigma = (q * eigenvalues) @ q.T
    return _sigma_df((sigma + sigma.T) / 2.0)


def _utility_closed_form(
    mu: pd.Series, sigma: pd.DataFrame, gamma: float, budget: float
) -> np.ndarray:
    """Budget-only Markowitz KKT solution: w = Sigma^{-1}(mu - lam 1)/gamma."""
    s = sigma.to_numpy()
    m = mu.to_numpy()
    ones = np.ones(s.shape[0])
    a = float(ones @ np.linalg.solve(s, ones))
    b = float(ones @ np.linalg.solve(s, m))
    lam = (b - gamma * budget) / a
    out: np.ndarray = np.linalg.solve(s, m - lam * ones) / gamma
    return out


def _min_variance_closed_form(sigma: pd.DataFrame, budget: float) -> np.ndarray:
    s = sigma.to_numpy()
    ones = np.ones(s.shape[0])
    w = np.linalg.solve(s, ones)
    out: np.ndarray = budget * w / float(ones @ w)
    return out


def _target_return_closed_form(
    mu: pd.Series, sigma: pd.DataFrame, target: float
) -> np.ndarray:
    """Merton frontier solution for budget = 1 with the return constraint binding."""
    s = sigma.to_numpy()
    m = mu.to_numpy()
    ones = np.ones(s.shape[0])
    inv_ones = np.linalg.solve(s, ones)
    inv_mu = np.linalg.solve(s, m)
    a = float(ones @ inv_ones)
    b = float(ones @ inv_mu)
    c = float(m @ inv_mu)
    d = a * c - b * b
    lam = (c - b * target) / d
    gam = (a * target - b) / d
    out: np.ndarray = lam * inv_ones + gam * inv_mu
    return out


def _panel(arr: np.ndarray) -> pd.DataFrame:
    n_obs, n_assets = arr.shape
    index = pd.date_range("2024-01-01", periods=n_obs, freq="B")
    return pd.DataFrame(arr, index=index, columns=_assets(n_assets))


def _mvn_panel(
    rng: np.random.Generator, sigma: np.ndarray, n_obs: int, mean: np.ndarray | None = None
) -> pd.DataFrame:
    chol = np.linalg.cholesky(sigma)
    z = rng.standard_normal((n_obs, sigma.shape[0]))
    data = z @ chol.T
    if mean is not None:
        data = data + mean
    return _panel(data)


# ---------------------------------------------------------------------------
# MVOConfig validation
# ---------------------------------------------------------------------------


class TestMVOConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = MVOConfig()
        assert cfg.risk_aversion == 1.0
        assert cfg.long_only is True
        assert cfg.budget == 1.0
        assert cfg.gross_cap is None

    @pytest.mark.parametrize("gamma", [0.0, -1.0, float("nan"), float("inf")])
    def test_bad_risk_aversion(self, gamma: float) -> None:
        with pytest.raises(ValueError, match="risk_aversion"):
            MVOConfig(risk_aversion=gamma)

    def test_bad_target_return(self) -> None:
        with pytest.raises(ValueError, match="target_return"):
            MVOConfig(target_return=float("inf"))

    def test_bad_budget(self) -> None:
        with pytest.raises(ValueError, match="budget"):
            MVOConfig(budget=float("nan"))

    @pytest.mark.parametrize("gross", [0.0, -2.0, float("nan")])
    def test_bad_gross_cap(self, gross: float) -> None:
        with pytest.raises(ValueError, match="gross_cap"):
            MVOConfig(gross_cap=gross)

    def test_gross_cap_below_budget_infeasible_by_construction(self) -> None:
        with pytest.raises(ValueError, match="gross_cap"):
            MVOConfig(budget=1.0, gross_cap=0.5)

    @pytest.mark.parametrize("cap", [0.0, -0.1])
    def test_bad_max_weight(self, cap: float) -> None:
        with pytest.raises(ValueError, match="max_weight"):
            MVOConfig(max_weight=cap)

    def test_bad_turnover_cap(self) -> None:
        with pytest.raises(ValueError, match="turnover_cap"):
            MVOConfig(turnover_cap=-0.1)


# ---------------------------------------------------------------------------
# Closed-form agreement
# ---------------------------------------------------------------------------


class TestClosedFormAgreement:
    @pytest.mark.parametrize("seed", [0, 1])
    @pytest.mark.parametrize("gamma", [1.0, 5.0])
    def test_utility_mode_matches_kkt_solution(self, seed: int, gamma: float) -> None:
        rng = np.random.default_rng(seed)
        sigma = _random_pd_sigma(rng, 4)
        mu = _mu_series(rng.uniform(-0.05, 0.10, size=4))
        cfg = MVOConfig(risk_aversion=gamma, long_only=False)
        result = mean_variance_weights(mu, sigma, cfg)
        expected = _utility_closed_form(mu, sigma, gamma, budget=1.0)
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-6)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.expected_return == pytest.approx(
            float(mu.to_numpy() @ expected), abs=1e-6
        )
        s = sigma.to_numpy()
        assert result.volatility == pytest.approx(
            float(np.sqrt(expected @ s @ expected)), abs=1e-6
        )

    def test_min_variance_matches_closed_form(self) -> None:
        sigma = _sigma_df(np.diag([1.0, 2.0, 4.0]))
        result = min_variance_weights(sigma)
        expected = _min_variance_closed_form(sigma, budget=1.0)
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-8)
        assert result.expected_return is None

    def test_min_variance_correlated_long_short(self) -> None:
        rng = np.random.default_rng(2)
        sigma = _random_pd_sigma(rng, 5)
        result = min_variance_weights(sigma, MVOConfig(long_only=False))
        expected = _min_variance_closed_form(sigma, budget=1.0)
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-6)

    def test_target_return_mode_binding_matches_merton(self) -> None:
        rng = np.random.default_rng(3)
        sigma = _random_pd_sigma(rng, 4)
        mu = _mu_series([0.02, 0.05, 0.08, 0.11])
        # Pick a target above the min-variance portfolio's return so the
        # constraint binds.
        minvar_ret = float(
            mu.to_numpy() @ _min_variance_closed_form(sigma, budget=1.0)
        )
        target = minvar_ret + 0.02
        cfg = MVOConfig(target_return=target, long_only=False)
        result = mean_variance_weights(mu, sigma, cfg)
        expected = _target_return_closed_form(mu, sigma, target)
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-6)
        assert result.expected_return == pytest.approx(target, abs=1e-6)

    def test_target_return_mode_slack_degenerates_to_min_variance(self) -> None:
        rng = np.random.default_rng(4)
        sigma = _random_pd_sigma(rng, 4)
        mu = _mu_series([0.02, 0.05, 0.08, 0.11])
        minvar_ret = float(
            mu.to_numpy() @ _min_variance_closed_form(sigma, budget=1.0)
        )
        cfg = MVOConfig(target_return=minvar_ret - 0.05, long_only=False)
        result = mean_variance_weights(mu, sigma, cfg)
        np.testing.assert_allclose(
            result.weights.to_numpy(),
            _min_variance_closed_form(sigma, budget=1.0),
            atol=1e-6,
        )

    def test_custom_budget(self) -> None:
        sigma = _sigma_df(np.diag([1.0, 2.0]))
        result = min_variance_weights(sigma, MVOConfig(budget=0.5))
        np.testing.assert_allclose(
            result.weights.to_numpy(),
            _min_variance_closed_form(sigma, budget=0.5),
            atol=1e-8,
        )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_long_only_corner_solution(self) -> None:
        # Unconstrained optimum is [1.1, -0.1]; long-only clips to [1, 0].
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.6, -0.6])
        result = mean_variance_weights(mu, sigma, MVOConfig(risk_aversion=1.0))
        np.testing.assert_allclose(result.weights.to_numpy(), [1.0, 0.0], atol=1e-7)
        # Snapping makes the bound asset exactly zero.
        assert result.weights.iloc[1] == 0.0

    def test_long_only_weights_nonnegative_random(self) -> None:
        rng = np.random.default_rng(5)
        sigma = _random_pd_sigma(rng, 6)
        mu = _mu_series(rng.uniform(-0.1, 0.1, size=6))
        result = mean_variance_weights(mu, sigma, MVOConfig(risk_aversion=2.0))
        assert bool((result.weights.to_numpy() >= -1e-9).all())
        assert result.weights.sum() == pytest.approx(1.0, abs=1e-7)

    def test_gross_cap_binds_dollar_neutral(self) -> None:
        # Dollar-neutral book wants [3, -3]; the gross cap pins it to [1, -1].
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([3.0, -3.0])
        cfg = MVOConfig(long_only=False, budget=0.0, gross_cap=2.0)
        result = mean_variance_weights(mu, sigma, cfg)
        np.testing.assert_allclose(result.weights.to_numpy(), [1.0, -1.0], atol=1e-6)
        assert float(np.abs(result.weights.to_numpy()).sum()) == pytest.approx(
            2.0, abs=1e-6
        )

    def test_max_weight_cap(self) -> None:
        # Capping the favourite at 0.5 spreads the remainder equally.
        sigma = _sigma_df(np.eye(3))
        mu = _mu_series([1.0, 0.0, 0.0])
        cfg = MVOConfig(risk_aversion=1.0, max_weight=0.5)
        result = mean_variance_weights(mu, sigma, cfg)
        np.testing.assert_allclose(
            result.weights.to_numpy(), [0.5, 0.25, 0.25], atol=1e-6
        )

    def test_sector_cap_binds(self) -> None:
        sigma = _sigma_df(np.eye(4))
        mu = _mu_series([1.0, 1.0, 0.0, 0.0])
        sectors = {"A00": "tech", "A01": "tech", "A02": "fin", "A03": "fin"}
        result = mean_variance_weights(
            mu,
            sigma,
            MVOConfig(risk_aversion=1.0),
            sectors=sectors,
            sector_caps={"tech": 0.3},
        )
        w = result.weights
        assert w["A00"] + w["A01"] == pytest.approx(0.3, abs=1e-6)
        np.testing.assert_allclose(
            w.to_numpy(), [0.15, 0.15, 0.35, 0.35], atol=1e-6
        )

    def test_sector_caps_without_sectors_mapping_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.1, 0.1])
        with pytest.raises(ValueError, match="sectors mapping is None"):
            mean_variance_weights(mu, sigma, sector_caps={"tech": 0.5})

    def test_sector_cap_unknown_sector_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.1, 0.1])
        sectors = {"A00": "tech", "A01": "tech"}
        with pytest.raises(ValueError, match="no asset in the"):
            mean_variance_weights(
                mu, sigma, sectors=sectors, sector_caps={"fin": 0.5}
            )

    def test_sector_cap_nonpositive_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.1, 0.1])
        sectors = {"A00": "tech", "A01": "tech"}
        with pytest.raises(ValueError, match="sector cap"):
            mean_variance_weights(
                mu, sigma, sectors=sectors, sector_caps={"tech": 0.0}
            )

    def test_turnover_cap_limits_rebalance(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([1.0, 0.0])
        prev = pd.Series([0.5, 0.5], index=_assets(2))
        cfg = MVOConfig(risk_aversion=1.0, turnover_cap=0.2)
        result = mean_variance_weights(mu, sigma, cfg, prev_weights=prev)
        np.testing.assert_allclose(result.weights.to_numpy(), [0.6, 0.4], atol=1e-6)
        turnover = float(np.abs(result.weights.to_numpy() - prev.to_numpy()).sum())
        assert turnover <= 0.2 + 1e-7

    def test_turnover_cap_zero_pins_to_previous(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([1.0, 0.0])
        prev = pd.Series([0.5, 0.5], index=_assets(2))
        cfg = MVOConfig(risk_aversion=1.0, turnover_cap=0.0)
        result = mean_variance_weights(mu, sigma, cfg, prev_weights=prev)
        np.testing.assert_allclose(result.weights.to_numpy(), [0.5, 0.5], atol=1e-7)

    def test_turnover_cap_without_prev_weights_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.1, 0.1])
        with pytest.raises(ValueError, match="prev_weights"):
            mean_variance_weights(mu, sigma, MVOConfig(turnover_cap=0.1))

    def test_infeasible_problem_raises_with_status(self) -> None:
        # Five assets capped at 0.1 each cannot sum to a budget of 1.
        sigma = _sigma_df(np.eye(5))
        mu = _mu_series([0.1] * 5)
        cfg = MVOConfig(max_weight=0.1)
        with pytest.raises(ValueError, match="infeasible"):
            mean_variance_weights(mu, sigma, cfg)

    def test_solver_override(self) -> None:
        sigma = _sigma_df(np.diag([1.0, 2.0, 4.0]))
        result = min_variance_weights(sigma, MVOConfig(solver="OSQP"))
        np.testing.assert_allclose(
            result.weights.to_numpy(),
            _min_variance_closed_form(sigma, budget=1.0),
            atol=1e-5,
        )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_sigma_not_square(self) -> None:
        bad = pd.DataFrame(np.zeros((2, 3)), index=["a", "b"], columns=["a", "b", "c"])
        with pytest.raises(ValueError, match="square"):
            min_variance_weights(bad)

    def test_sigma_label_mismatch(self) -> None:
        bad = pd.DataFrame(np.eye(2), index=["a", "b"], columns=["b", "a"])
        with pytest.raises(ValueError, match="identical asset labels"):
            min_variance_weights(bad)

    def test_sigma_single_asset(self) -> None:
        bad = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        with pytest.raises(ValueError, match="at least 2 assets"):
            min_variance_weights(bad)

    def test_sigma_nan(self) -> None:
        arr = np.eye(2)
        arr[0, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            min_variance_weights(_sigma_df(arr))

    def test_sigma_zero(self) -> None:
        with pytest.raises(ValueError, match="identically zero"):
            min_variance_weights(_sigma_df(np.zeros((2, 2))))

    def test_sigma_asymmetric(self) -> None:
        arr = np.array([[1.0, 0.3], [0.0, 1.0]])
        with pytest.raises(ValueError, match="symmetric"):
            min_variance_weights(_sigma_df(arr))

    def test_sigma_indefinite(self) -> None:
        arr = np.array([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues 3 and -1
        with pytest.raises(ValueError, match="indefinite"):
            min_variance_weights(_sigma_df(arr))

    def test_mu_misaligned(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = pd.Series([0.1, 0.2], index=["A01", "A00"])  # wrong order
        with pytest.raises(ValueError, match="mu index"):
            mean_variance_weights(mu, sigma)

    def test_mu_nan(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = pd.Series([0.1, np.nan], index=_assets(2))
        with pytest.raises(ValueError, match="mu contains"):
            mean_variance_weights(mu, sigma)

    def test_prev_weights_misaligned(self) -> None:
        sigma = _sigma_df(np.eye(2))
        mu = _mu_series([0.1, 0.1])
        prev = pd.Series([0.5, 0.5], index=["A01", "A00"])
        with pytest.raises(ValueError, match="prev_weights index"):
            mean_variance_weights(
                mu, sigma, MVOConfig(turnover_cap=1.0), prev_weights=prev
            )

    def test_min_variance_prev_weights_misaligned(self) -> None:
        sigma = _sigma_df(np.eye(2))
        prev = pd.Series([0.5, 0.5], index=["A01", "A00"])
        with pytest.raises(ValueError, match="prev_weights index"):
            min_variance_weights(
                sigma, MVOConfig(turnover_cap=1.0), prev_weights=prev
            )

    def test_min_variance_sector_caps(self) -> None:
        sigma = _sigma_df(np.diag([1.0, 1.0, 4.0, 4.0]))
        sectors = {"A00": "tech", "A01": "tech", "A02": "fin", "A03": "fin"}
        result = min_variance_weights(
            sigma, sectors=sectors, sector_caps={"tech": 0.4}
        )
        w = result.weights
        assert w["A00"] + w["A01"] == pytest.approx(0.4, abs=1e-6)


# ---------------------------------------------------------------------------
# Bayes-Stein expected returns
# ---------------------------------------------------------------------------


def _bayes_stein_reference(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Explicit-inverse transcription of Jorion (1986)."""
    n_obs, n_assets = arr.shape
    mu_hat = arr.mean(axis=0)
    x = arr - mu_hat
    s = (x.T @ x) / float(n_obs - 1)
    sigma_adj = s * (float(n_obs - 1) / float(n_obs - n_assets - 2))
    p = np.linalg.inv(sigma_adj)
    ones = np.ones(n_assets)
    mu_g = float(ones @ p @ mu_hat) / float(ones @ p @ ones)
    d = mu_hat - mu_g
    lam = float(n_assets + 2) / float(d @ p @ d)
    v = float(np.clip(lam / (lam + n_obs), 0.0, 1.0))
    return (1.0 - v) * mu_hat + v * mu_g, v, mu_g


class TestBayesStein:
    @pytest.mark.parametrize("seed,n_obs,n_assets", [(0, 60, 5), (1, 40, 8)])
    def test_matches_reference(self, seed: int, n_obs: int, n_assets: int) -> None:
        rng = np.random.default_rng(seed)
        panel = _panel(rng.standard_normal((n_obs, n_assets)) * 0.01 + 0.001)
        result = bayes_stein_means(panel)
        ref_means, ref_v, ref_g = _bayes_stein_reference(panel.to_numpy())
        np.testing.assert_allclose(result.means.to_numpy(), ref_means, atol=1e-12)
        assert result.intensity == pytest.approx(ref_v, abs=1e-12)
        assert result.grand_mean == pytest.approx(ref_g, abs=1e-12)
        assert result.method == "bayes_stein"
        assert 0.0 <= result.intensity <= 1.0
        assert list(result.means.index) == list(panel.columns)

    def test_stein_dominance_over_sample_mean(self) -> None:
        # True means are all equal: the grand mean is the truth, so
        # shrinking towards it must beat the raw sample means.
        n_assets, n_obs = 10, 30
        true_mu = np.full(n_assets, 0.002)
        bs_errors = []
        sample_errors = []
        for seed in range(10):
            rng = np.random.default_rng(400 + seed)
            sigma = np.diag(rng.uniform(0.0001, 0.0004, size=n_assets))
            panel = _mvn_panel(rng, sigma, n_obs, mean=true_mu)
            arr = panel.to_numpy()
            bs = bayes_stein_means(panel).means.to_numpy()
            bs_errors.append(float(((bs - true_mu) ** 2).sum()))
            sample_errors.append(float(((arr.mean(axis=0) - true_mu) ** 2).sum()))
        assert float(np.mean(bs_errors)) < float(np.mean(sample_errors))

    def test_identical_sample_means_full_shrink(self) -> None:
        # Paired +x/-x rows give every column a sample mean of EXACTLY 0.0
        # (float negation is exact), driving the dispersion term to exact
        # zero -- the full-shrink degeneracy: intensity 1, means == grand
        # mean.  Columns are distinct permutations so the covariance stays
        # non-singular.
        col0 = [0.01, -0.01, 0.02, -0.02, 0.03, -0.03, 0.04, -0.04]
        col1 = [0.02, -0.02, 0.01, -0.01, 0.04, -0.04, 0.03, -0.03]
        col2 = [0.03, -0.03, 0.04, -0.04, 0.01, -0.01, 0.02, -0.02]
        panel = _panel(np.column_stack([col0, col1, col2]))
        result = bayes_stein_means(panel)
        assert result.intensity == 1.0
        assert result.grand_mean == pytest.approx(0.0, abs=1e-15)
        np.testing.assert_allclose(result.means.to_numpy(), 0.0, atol=1e-15)

    def test_nan_raises(self) -> None:
        rng = np.random.default_rng(7)
        panel = _panel(rng.standard_normal((20, 3)))
        panel.iloc[3, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            bayes_stein_means(panel)

    def test_single_asset_raises(self) -> None:
        rng = np.random.default_rng(8)
        panel = _panel(rng.standard_normal((20, 3))).iloc[:, :1]
        with pytest.raises(ValueError, match="at least 2 asset"):
            bayes_stein_means(panel)

    def test_too_few_observations_raises(self) -> None:
        rng = np.random.default_rng(9)
        panel = _panel(rng.standard_normal((7, 5)))  # needs T >= 8
        with pytest.raises(ValueError, match="N \\+ 3"):
            bayes_stein_means(panel)

    def test_singular_covariance_raises(self) -> None:
        rng = np.random.default_rng(10)
        col = rng.standard_normal(20)
        panel = _panel(np.column_stack([col, col]))  # perfectly collinear
        with pytest.raises(ValueError, match="singular"):
            bayes_stein_means(panel)


# ---------------------------------------------------------------------------
# Phase 6 DOD: sensitivity (instability repair) and performance
# ---------------------------------------------------------------------------


class TestPhase6DOD:
    def test_shrinkage_stabilises_weight_sensitivity(self) -> None:
        # T = 24 observations of N = 20 assets: the sample covariance is
        # barely invertible.  Perturb mu by a basis-point-scale bump and
        # compare the L1 weight change under the sample covariance vs the
        # Ledoit-Wolf covariance.  Shrinkage must damp the instability by
        # a wide margin (master plan: "perturbation -> small weight change").
        rng = np.random.default_rng(42)
        q, _ = np.linalg.qr(rng.standard_normal((20, 20)))
        eigenvalues = rng.uniform(0.5, 2.0, size=20)
        true_sigma = ((q * eigenvalues) @ q.T) * 1e-4
        true_sigma = (true_sigma + true_sigma.T) / 2.0
        panel = _mvn_panel(rng, true_sigma, 24)

        mu = bayes_stein_means(panel).means
        bump = pd.Series(0.0, index=mu.index)
        bump.iloc[0] = 1e-4
        cfg = MVOConfig(risk_aversion=5.0, long_only=False)

        sigma_sample = sample_covariance(panel).covariance
        sigma_lw = ledoit_wolf_covariance(panel).covariance

        w_sample = mean_variance_weights(mu, sigma_sample, cfg).weights
        w_sample_bumped = mean_variance_weights(mu + bump, sigma_sample, cfg).weights
        w_lw = mean_variance_weights(mu, sigma_lw, cfg).weights
        w_lw_bumped = mean_variance_weights(mu + bump, sigma_lw, cfg).weights

        change_sample = float(np.abs(w_sample - w_sample_bumped).sum())
        change_lw = float(np.abs(w_lw - w_lw_bumped).sum())

        assert change_lw < change_sample / 2.0
        assert change_lw < 1.0

    def test_twenty_asset_solves_under_one_second(self) -> None:
        rng = np.random.default_rng(43)
        sigma = _random_pd_sigma(rng, 20)
        mu = _mu_series(rng.uniform(-0.05, 0.10, size=20))
        sectors = {a: ("tech" if i < 10 else "fin") for i, a in enumerate(_assets(20))}
        start = time.perf_counter()
        mean_variance_weights(
            mu,
            sigma,
            MVOConfig(risk_aversion=2.0, max_weight=0.2),
            sectors=sectors,
            sector_caps={"tech": 0.6, "fin": 0.6},
        )
        min_variance_weights(sigma)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"20-asset MVO solves took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class TestMVOResult:
    def test_frozen(self) -> None:
        import dataclasses

        result = min_variance_weights(_sigma_df(np.eye(2)))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "other"  # type: ignore[misc]

    def test_equality_ignores_weights(self) -> None:
        a = MVOResult(
            weights=pd.Series([1.0, 0.0]),
            expected_return=None,
            volatility=0.1,
            objective_value=0.01,
            status="optimal",
        )
        b = MVOResult(
            weights=pd.Series([0.0, 1.0]),
            expected_return=None,
            volatility=0.1,
            objective_value=0.01,
            status="optimal",
        )
        assert a == b
