"""Tests for core_trading.portfolio.risk_parity (Phase 6.4).

Covers:
* RiskParityConfig validation of every parameter bound.
* Closed forms from Maillard-Roncalli-Teiletche (2010): diagonal Sigma
  (w proportional to 1/sigma_i; with budgets, sqrt(b_i)/sigma_i), constant
  pairwise correlation (ERC equals inverse-volatility weighting), and the
  N = 2 universal solution w_1 = sigma_2 / (sigma_1 + sigma_2).
* The defining property on random PD matrices: equal (or budget-matching)
  fractional risk contributions to solver tolerance, strictly positive
  fully-invested weights.
* Volatility targeting: levered portfolio hits the target exactly;
  max_leverage clamps.
* Convergence diagnostics: diagonal start converges in one sweep;
  non-convergence raises RuntimeError.
* risk_contributions helper: known values, Euler decomposition sums to 1,
  zero-variance and misalignment errors.
* Input validation: sigma shape/labels/NaN/asymmetry/singularity, bad
  budgets.
* Phase 6 DOD: 20-asset solve in < 1 s; perturbation stability.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.risk_parity import (
    RiskParityConfig,
    RiskParityResult,
    risk_contributions,
    risk_parity_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assets(n: int) -> list[str]:
    return [f"A{i:02d}" for i in range(n)]


def _sigma_df(arr: np.ndarray) -> pd.DataFrame:
    names = _assets(arr.shape[0])
    return pd.DataFrame(np.asarray(arr, dtype=float), index=names, columns=names)


def _random_pd_sigma(rng: np.random.Generator, n: int) -> pd.DataFrame:
    q, _ = np.linalg.qr(rng.standard_normal((n, n)))
    eigenvalues = rng.uniform(0.5, 2.0, size=n)
    sigma = (q * eigenvalues) @ q.T
    return _sigma_df((sigma + sigma.T) / 2.0)


def _corr_sigma(vols: np.ndarray, rho: float) -> pd.DataFrame:
    n = vols.shape[0]
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    return _sigma_df(corr * np.outer(vols, vols))


# ---------------------------------------------------------------------------
# RiskParityConfig validation
# ---------------------------------------------------------------------------


class TestRiskParityConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = RiskParityConfig()
        assert cfg.target_vol is None
        assert cfg.max_leverage is None
        assert cfg.tol == 1e-10
        assert cfg.max_iter == 10_000

    @pytest.mark.parametrize("vol", [0.0, -0.1, float("nan")])
    def test_bad_target_vol(self, vol: float) -> None:
        with pytest.raises(ValueError, match="target_vol"):
            RiskParityConfig(target_vol=vol)

    @pytest.mark.parametrize("lev", [0.0, -1.0])
    def test_bad_max_leverage(self, lev: float) -> None:
        with pytest.raises(ValueError, match="max_leverage"):
            RiskParityConfig(max_leverage=lev)

    @pytest.mark.parametrize("tol", [0.0, -1e-8, float("nan")])
    def test_bad_tol(self, tol: float) -> None:
        with pytest.raises(ValueError, match="tol"):
            RiskParityConfig(tol=tol)

    def test_bad_max_iter(self) -> None:
        with pytest.raises(ValueError, match="max_iter"):
            RiskParityConfig(max_iter=0)


# ---------------------------------------------------------------------------
# Closed forms (Maillard-Roncalli-Teiletche 2010)
# ---------------------------------------------------------------------------


class TestClosedForms:
    def test_diagonal_sigma_inverse_vol(self) -> None:
        vols = np.array([0.10, 0.20, 0.40])
        sigma = _sigma_df(np.diag(vols**2))
        result = risk_parity_weights(sigma)
        expected = (1.0 / vols) / (1.0 / vols).sum()
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-10)
        # The diagonal closed form is also the iteration's start: one sweep.
        assert result.n_iterations == 1

    def test_diagonal_sigma_with_budgets(self) -> None:
        vols = np.array([0.10, 0.20, 0.40])
        budgets = np.array([0.5, 0.3, 0.2])
        sigma = _sigma_df(np.diag(vols**2))
        result = risk_parity_weights(
            sigma, budgets=pd.Series(budgets, index=_assets(3))
        )
        raw = np.sqrt(budgets) / vols
        np.testing.assert_allclose(
            result.weights.to_numpy(), raw / raw.sum(), atol=1e-10
        )

    @pytest.mark.parametrize("rho", [-0.2, 0.0, 0.5, 0.9])
    def test_constant_correlation_equals_inverse_vol(self, rho: float) -> None:
        vols = np.array([0.05, 0.10, 0.15, 0.30])
        sigma = _corr_sigma(vols, rho)
        result = risk_parity_weights(sigma)
        expected = (1.0 / vols) / (1.0 / vols).sum()
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-8)

    @pytest.mark.parametrize("rho", [-0.5, 0.0, 0.7])
    def test_two_assets_universal_solution(self, rho: float) -> None:
        vols = np.array([0.12, 0.36])
        sigma = _corr_sigma(vols, rho)
        result = risk_parity_weights(sigma)
        expected = np.array([vols[1], vols[0]]) / (vols[0] + vols[1])
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-9)


# ---------------------------------------------------------------------------
# Defining property on random matrices
# ---------------------------------------------------------------------------


class TestEqualRiskContribution:
    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_equal_contributions_random_pd(self, seed: int) -> None:
        rng = np.random.default_rng(seed)
        sigma = _random_pd_sigma(rng, 10)
        result = risk_parity_weights(sigma)
        rc = result.risk_contributions.to_numpy()
        np.testing.assert_allclose(rc, 0.1, atol=1e-9)
        w = result.weights.to_numpy()
        assert bool((w > 0.0).all())
        assert float(w.sum()) == pytest.approx(1.0, abs=1e-12)
        assert result.leverage == 1.0
        pd.testing.assert_series_equal(result.levered_weights, result.weights)

    def test_budgets_recovered_random_pd(self) -> None:
        rng = np.random.default_rng(5)
        sigma = _random_pd_sigma(rng, 8)
        budgets = pd.Series(
            rng.uniform(0.5, 2.0, size=8), index=_assets(8)
        )
        result = risk_parity_weights(sigma, budgets=budgets)
        normalised = budgets.to_numpy() / budgets.to_numpy().sum()
        np.testing.assert_allclose(
            result.risk_contributions.to_numpy(), normalised, atol=1e-9
        )

    def test_contributions_consistent_with_helper(self) -> None:
        rng = np.random.default_rng(6)
        sigma = _random_pd_sigma(rng, 6)
        result = risk_parity_weights(sigma)
        helper_rc = risk_contributions(result.weights, sigma)
        pd.testing.assert_series_equal(result.risk_contributions, helper_rc)


# ---------------------------------------------------------------------------
# Volatility targeting
# ---------------------------------------------------------------------------


class TestVolTargeting:
    def test_levered_portfolio_hits_target(self) -> None:
        rng = np.random.default_rng(7)
        sigma = _random_pd_sigma(rng, 5) * 1e-4
        target = 0.02
        result = risk_parity_weights(
            sigma, config=RiskParityConfig(target_vol=target)
        )
        assert result.leverage == pytest.approx(
            target / result.portfolio_vol, abs=1e-12
        )
        lw = result.levered_weights.to_numpy()
        s = sigma.to_numpy()
        levered_vol = float(np.sqrt(lw @ s @ lw))
        assert levered_vol == pytest.approx(target, abs=1e-10)

    def test_max_leverage_clamps(self) -> None:
        rng = np.random.default_rng(8)
        sigma = _random_pd_sigma(rng, 5) * 1e-4
        result = risk_parity_weights(
            sigma,
            config=RiskParityConfig(target_vol=10.0, max_leverage=3.0),
        )
        assert result.leverage == 3.0
        np.testing.assert_allclose(
            result.levered_weights.to_numpy(),
            3.0 * result.weights.to_numpy(),
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------


class TestConvergence:
    def test_non_convergence_raises(self) -> None:
        vols = np.array([0.05, 0.10, 0.15, 0.30, 0.20])
        sigma = _corr_sigma(vols, 0.8)
        with pytest.raises(RuntimeError, match="did not reach"):
            risk_parity_weights(
                sigma, config=RiskParityConfig(tol=1e-15, max_iter=1)
            )

    def test_correlated_matrix_converges_and_reports_sweeps(self) -> None:
        vols = np.array([0.05, 0.10, 0.15, 0.30, 0.20])
        sigma = _corr_sigma(vols, 0.8)
        result = risk_parity_weights(sigma)
        assert result.n_iterations >= 1
        np.testing.assert_allclose(
            result.risk_contributions.to_numpy(), 0.2, atol=1e-9
        )


# ---------------------------------------------------------------------------
# risk_contributions helper
# ---------------------------------------------------------------------------


class TestRiskContributionsHelper:
    def test_known_values_identity_sigma(self) -> None:
        sigma = _sigma_df(np.eye(2))
        weights = pd.Series([0.5, 0.5], index=_assets(2))
        rc = risk_contributions(weights, sigma)
        np.testing.assert_allclose(rc.to_numpy(), [0.5, 0.5], atol=1e-15)

    def test_sums_to_one_random(self) -> None:
        rng = np.random.default_rng(9)
        sigma = _random_pd_sigma(rng, 6)
        weights = pd.Series(rng.uniform(0.05, 0.3, size=6), index=_assets(6))
        rc = risk_contributions(weights, sigma)
        assert float(rc.sum()) == pytest.approx(1.0, abs=1e-12)

    def test_zero_variance_portfolio_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        weights = pd.Series([0.0, 0.0], index=_assets(2))
        with pytest.raises(ValueError, match="variance is zero"):
            risk_contributions(weights, sigma)

    def test_misaligned_weights_raise(self) -> None:
        sigma = _sigma_df(np.eye(2))
        weights = pd.Series([0.5, 0.5], index=["A01", "A00"])
        with pytest.raises(ValueError, match="weights index"):
            risk_contributions(weights, sigma)

    def test_nan_weights_raise(self) -> None:
        sigma = _sigma_df(np.eye(2))
        weights = pd.Series([0.5, np.nan], index=_assets(2))
        with pytest.raises(ValueError, match="weights contain"):
            risk_contributions(weights, sigma)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_sigma_not_square(self) -> None:
        bad = pd.DataFrame(np.zeros((2, 3)), index=["a", "b"], columns=["a", "b", "c"])
        with pytest.raises(ValueError, match="square"):
            risk_parity_weights(bad)

    def test_sigma_label_mismatch(self) -> None:
        bad = pd.DataFrame(np.eye(2), index=["a", "b"], columns=["b", "a"])
        with pytest.raises(ValueError, match="identical asset labels"):
            risk_parity_weights(bad)

    def test_sigma_single_asset(self) -> None:
        bad = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        with pytest.raises(ValueError, match="at least 2 assets"):
            risk_parity_weights(bad)

    def test_sigma_nan(self) -> None:
        arr = np.eye(2)
        arr[0, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            risk_parity_weights(_sigma_df(arr))

    def test_sigma_zero(self) -> None:
        with pytest.raises(ValueError, match="identically zero"):
            risk_parity_weights(_sigma_df(np.zeros((2, 2))))

    def test_sigma_asymmetric(self) -> None:
        arr = np.array([[1.0, 0.3], [0.0, 1.0]])
        with pytest.raises(ValueError, match="symmetric"):
            risk_parity_weights(_sigma_df(arr))

    def test_sigma_singular_raises(self) -> None:
        arr = np.array([[1.0, 1.0], [1.0, 1.0]])  # PSD but rank 1
        with pytest.raises(ValueError, match="positive definite"):
            risk_parity_weights(_sigma_df(arr))

    def test_budgets_misaligned(self) -> None:
        sigma = _sigma_df(np.eye(2))
        budgets = pd.Series([0.5, 0.5], index=["A01", "A00"])
        with pytest.raises(ValueError, match="budgets index"):
            risk_parity_weights(sigma, budgets=budgets)

    def test_budgets_nan(self) -> None:
        sigma = _sigma_df(np.eye(2))
        budgets = pd.Series([0.5, np.nan], index=_assets(2))
        with pytest.raises(ValueError, match="budgets contain"):
            risk_parity_weights(sigma, budgets=budgets)

    @pytest.mark.parametrize("bad", [0.0, -0.5])
    def test_budgets_nonpositive(self, bad: float) -> None:
        sigma = _sigma_df(np.eye(2))
        budgets = pd.Series([0.5, bad], index=_assets(2))
        with pytest.raises(ValueError, match="strictly positive"):
            risk_parity_weights(sigma, budgets=budgets)


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class TestRiskParityResult:
    def test_frozen(self) -> None:
        result = risk_parity_weights(_sigma_df(np.eye(2)))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.leverage = 2.0  # type: ignore[misc]

    def test_equality_ignores_series_fields(self) -> None:
        ones = pd.Series([0.5, 0.5], index=_assets(2))
        halves = pd.Series([0.9, 0.1], index=_assets(2))
        a = RiskParityResult(
            weights=ones,
            risk_contributions=ones,
            portfolio_vol=0.1,
            leverage=1.0,
            levered_weights=ones,
            n_iterations=3,
        )
        b = RiskParityResult(
            weights=halves,
            risk_contributions=halves,
            portfolio_vol=0.1,
            leverage=1.0,
            levered_weights=halves,
            n_iterations=3,
        )
        assert a == b


# ---------------------------------------------------------------------------
# Phase 6 DOD: performance and stability
# ---------------------------------------------------------------------------


class TestPhase6DOD:
    def test_twenty_assets_under_one_second(self) -> None:
        rng = np.random.default_rng(10)
        sigma = _random_pd_sigma(rng, 20)
        start = time.perf_counter()
        result = risk_parity_weights(sigma)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"20-asset risk parity took {elapsed:.3f}s"
        np.testing.assert_allclose(
            result.risk_contributions.to_numpy(), 1.0 / 20.0, atol=1e-9
        )

    def test_perturbation_stability(self) -> None:
        # ERC weights are a smooth function of Sigma: a 1% multiplicative
        # perturbation of the covariance entries must move the weights by
        # far less than the perturbation itself (no inversion instability).
        rng = np.random.default_rng(11)
        sigma = _random_pd_sigma(rng, 20)
        noise = 1.0 + 0.01 * rng.standard_normal(sigma.shape)
        perturbed_arr = sigma.to_numpy() * (noise + noise.T) / 2.0
        perturbed = pd.DataFrame(
            perturbed_arr, index=sigma.index, columns=sigma.columns
        )
        w_base = risk_parity_weights(sigma).weights.to_numpy()
        w_pert = risk_parity_weights(perturbed).weights.to_numpy()
        assert float(np.abs(w_base - w_pert).sum()) < 0.05
