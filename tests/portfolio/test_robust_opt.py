"""Tests for core_trading.portfolio.robust_opt (Phase 6.5).

Covers:
* empirical_cvar: hand-computed discrete RU values including the
  fractional-boundary case and the thin-tail (worst-loss) branch, plus
  validation.
* cvar_weights: GLOBAL optimality against a dense 2-asset grid search of
  the empirical CVaR; fat-tail avoidance; the min-return trade-off; the
  constraint paths (gross cap, max weight, long-short); infeasibility;
  the validation battery for scenarios and config.
* worst_case_cvar_weights: minimax property against each single-block
  optimum; single-block degeneracy to plain CVaR; block diagnostics.
* michaud_weights: seed determinism; convex-constraint preservation
  (budget, long-only, sector cap, max weight) of the AVERAGED weights;
  convergence to the base MVO solution as the estimation window grows;
  dispersion shrinking with the window; the no-covariance-resampling
  branch; parameter validation.
* robust_mean_variance_weights: exact kappa = 0 degeneracy to Markowitz;
  monotone de-risking in kappa; the kappa -> infinity minimum-variance
  limit; nominal-return accounting; constraint paths and validation.
* Phase 6 DOD: every optimiser solves a 20-asset universe in < 1 s.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.mvo import (
    MVOConfig,
    mean_variance_weights,
    min_variance_weights,
)
from core_trading.portfolio.robust_opt import (
    CVaRConfig,
    CVaRResult,
    cvar_weights,
    empirical_cvar,
    michaud_weights,
    robust_mean_variance_weights,
    worst_case_cvar_weights,
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


def _random_pd_sigma(rng: np.random.Generator, n: int, scale: float = 1.0) -> pd.DataFrame:
    q, _ = np.linalg.qr(rng.standard_normal((n, n)))
    eigenvalues = rng.uniform(0.5, 2.0, size=n)
    sigma = ((q * eigenvalues) @ q.T) * scale
    return _sigma_df((sigma + sigma.T) / 2.0)


def _scenario_df(arr: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(np.asarray(arr, dtype=float), columns=_assets(arr.shape[1]))


# ---------------------------------------------------------------------------
# empirical_cvar
# ---------------------------------------------------------------------------


class TestEmpiricalCVaR:
    _RETURNS = np.array([-0.10, -0.05, 0.00, 0.05, 0.10])

    def test_whole_scenario_tail(self) -> None:
        # alpha = 0.8 on 5 scenarios: the tail is exactly the worst loss.
        assert empirical_cvar(self._RETURNS, 0.8) == pytest.approx(0.10, abs=1e-15)

    def test_fractional_boundary(self) -> None:
        # alpha = 0.5: tail mass 2.5 scenarios = losses {0.10, 0.05} fully
        # plus half of the 0.00 loss -> (0.10 + 0.05 + 0.5 * 0) / 2.5.
        assert empirical_cvar(self._RETURNS, 0.5) == pytest.approx(0.06, abs=1e-15)

    def test_thin_tail_branch_returns_worst_loss(self) -> None:
        # alpha = 0.95 on 5 scenarios: ceil(4.75) = 5 = n -> worst loss.
        assert empirical_cvar(self._RETURNS, 0.95) == pytest.approx(0.10, abs=1e-15)

    def test_accepts_series(self) -> None:
        series = pd.Series(self._RETURNS)
        assert empirical_cvar(series, 0.8) == pytest.approx(0.10, abs=1e-15)

    @pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
    def test_bad_alpha(self, alpha: float) -> None:
        with pytest.raises(ValueError, match="alpha"):
            empirical_cvar(self._RETURNS, alpha)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            empirical_cvar(np.array([]), 0.9)

    def test_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            empirical_cvar(np.array([0.1, np.nan]), 0.9)


# ---------------------------------------------------------------------------
# cvar_weights
# ---------------------------------------------------------------------------


class TestCVaRWeights:
    def _two_asset_scenarios(self, seed: int = 0) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        n = 200
        a = rng.normal(0.001, 0.01, size=n)
        b = rng.normal(0.002, 0.01, size=n)
        b[rng.integers(0, n, size=8)] -= 0.20  # fat left tail for B
        return _scenario_df(np.column_stack([a, b]))

    def test_global_optimality_against_grid_search(self) -> None:
        scenarios = self._two_asset_scenarios()
        cfg = CVaRConfig(alpha=0.9)
        result = cvar_weights(scenarios, cfg)
        arr = scenarios.to_numpy()
        grid = np.linspace(0.0, 1.0, 1001)
        grid_best = min(
            empirical_cvar(arr @ np.array([g, 1.0 - g]), 0.9) for g in grid
        )
        assert result.cvar == pytest.approx(grid_best, abs=1e-3)
        assert result.cvar <= grid_best + 1e-3

    def test_avoids_fat_tail_asset(self) -> None:
        scenarios = self._two_asset_scenarios()
        result = cvar_weights(scenarios, CVaRConfig(alpha=0.95))
        assert result.weights["A00"] > 0.8
        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.alpha == 0.95
        assert len(result.block_cvars) == 1
        assert result.cvar == pytest.approx(result.block_cvars[0], abs=1e-15)

    def test_min_return_constraint_trades_cvar(self) -> None:
        scenarios = self._two_asset_scenarios()
        arr = scenarios.to_numpy()
        means = arr.mean(axis=0)
        unconstrained = cvar_weights(scenarios, CVaRConfig(alpha=0.9))
        target = float(means @ np.array([0.2, 0.8]))  # needs heavy B
        constrained = cvar_weights(
            scenarios, CVaRConfig(alpha=0.9, min_expected_return=target)
        )
        assert constrained.expected_return >= target - 1e-9
        assert constrained.cvar >= unconstrained.cvar - 1e-12

    def test_budget_and_long_only_hold(self) -> None:
        scenarios = self._two_asset_scenarios(1)
        result = cvar_weights(scenarios)
        w = result.weights.to_numpy()
        assert float(w.sum()) == pytest.approx(1.0, abs=1e-7)
        assert bool((w >= 0.0).all())

    def test_long_short_with_gross_cap(self) -> None:
        scenarios = self._two_asset_scenarios(2)
        cfg = CVaRConfig(alpha=0.9, long_only=False, gross_cap=1.5)
        result = cvar_weights(scenarios, cfg)
        assert float(np.abs(result.weights.to_numpy()).sum()) <= 1.5 + 1e-6

    def test_max_weight_cap_holds(self) -> None:
        rng = np.random.default_rng(3)
        scenarios = _scenario_df(rng.normal(0.001, 0.01, size=(150, 4)))
        result = cvar_weights(scenarios, CVaRConfig(max_weight=0.4))
        assert bool((result.weights.to_numpy() <= 0.4 + 1e-7).all())

    def test_infeasible_min_return_raises(self) -> None:
        scenarios = self._two_asset_scenarios(4)
        means = scenarios.to_numpy().mean(axis=0)
        impossible = float(means.max()) + 1.0
        with pytest.raises(ValueError, match="status"):
            cvar_weights(
                scenarios, CVaRConfig(min_expected_return=impossible)
            )


class TestCVaRValidation:
    def test_empty_block_sequence_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one block"):
            worst_case_cvar_weights([])

    def test_mismatched_block_columns_raise(self) -> None:
        rng = np.random.default_rng(5)
        a = _scenario_df(rng.normal(size=(50, 3)))
        b = a.copy()
        b.columns = ["X", "Y", "Z"]
        with pytest.raises(ValueError, match="columns"):
            worst_case_cvar_weights([a, b])

    def test_single_asset_raises(self) -> None:
        scenarios = pd.DataFrame({"A00": [0.1, -0.1, 0.05]})
        with pytest.raises(ValueError, match="at least 2 asset"):
            cvar_weights(scenarios)

    def test_single_scenario_raises(self) -> None:
        scenarios = _scenario_df(np.array([[0.1, -0.1]]))
        with pytest.raises(ValueError, match="at least 2 scenario"):
            cvar_weights(scenarios)

    def test_nan_scenarios_raise(self) -> None:
        arr = np.zeros((10, 2))
        arr[3, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            cvar_weights(_scenario_df(arr))

    @pytest.mark.parametrize("alpha", [0.0, 1.0, -0.5])
    def test_config_bad_alpha(self, alpha: float) -> None:
        with pytest.raises(ValueError, match="alpha"):
            CVaRConfig(alpha=alpha)

    def test_config_bad_budget(self) -> None:
        with pytest.raises(ValueError, match="budget"):
            CVaRConfig(budget=float("nan"))

    @pytest.mark.parametrize("gross", [0.0, -1.0])
    def test_config_bad_gross_cap(self, gross: float) -> None:
        with pytest.raises(ValueError, match="gross_cap"):
            CVaRConfig(gross_cap=gross)

    def test_config_gross_cap_below_budget(self) -> None:
        with pytest.raises(ValueError, match="gross_cap"):
            CVaRConfig(budget=1.0, gross_cap=0.6)

    def test_config_bad_max_weight(self) -> None:
        with pytest.raises(ValueError, match="max_weight"):
            CVaRConfig(max_weight=0.0)

    def test_config_bad_min_return(self) -> None:
        with pytest.raises(ValueError, match="min_expected_return"):
            CVaRConfig(min_expected_return=float("inf"))


# ---------------------------------------------------------------------------
# worst_case_cvar_weights
# ---------------------------------------------------------------------------


class TestWorstCaseCVaR:
    def _two_blocks(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        rng = np.random.default_rng(6)
        n = 150
        # Calm regime: A slightly better.  Crisis regime: A crashes.
        calm = np.column_stack(
            [rng.normal(0.002, 0.008, n), rng.normal(0.001, 0.008, n)]
        )
        crisis = np.column_stack(
            [rng.normal(-0.004, 0.03, n), rng.normal(0.000, 0.012, n)]
        )
        return _scenario_df(calm), _scenario_df(crisis)

    def test_minimax_beats_single_block_solutions(self) -> None:
        calm, crisis = self._two_blocks()
        cfg = CVaRConfig(alpha=0.9)
        wc = worst_case_cvar_weights([calm, crisis], cfg)

        def worst_of(weights: pd.Series) -> float:
            w = weights.to_numpy()
            return max(
                empirical_cvar(calm.to_numpy() @ w, 0.9),
                empirical_cvar(crisis.to_numpy() @ w, 0.9),
            )

        w_calm_only = cvar_weights(calm, cfg).weights
        w_crisis_only = cvar_weights(crisis, cfg).weights
        assert wc.cvar <= worst_of(w_calm_only) + 1e-6
        assert wc.cvar <= worst_of(w_crisis_only) + 1e-6
        assert wc.cvar == pytest.approx(worst_of(wc.weights), abs=1e-12)
        assert len(wc.block_cvars) == 2

    def test_single_block_degenerates_to_plain_cvar(self) -> None:
        calm, _ = self._two_blocks()
        cfg = CVaRConfig(alpha=0.9)
        plain = cvar_weights(calm, cfg)
        wc = worst_case_cvar_weights([calm], cfg)
        np.testing.assert_allclose(
            wc.weights.to_numpy(), plain.weights.to_numpy(), atol=1e-9
        )

    def test_expected_return_is_worst_block_mean(self) -> None:
        calm, crisis = self._two_blocks()
        wc = worst_case_cvar_weights([calm, crisis], CVaRConfig(alpha=0.9))
        w = wc.weights.to_numpy()
        means = [
            float(calm.to_numpy().mean(axis=0) @ w),
            float(crisis.to_numpy().mean(axis=0) @ w),
        ]
        assert wc.expected_return == pytest.approx(min(means), abs=1e-12)


# ---------------------------------------------------------------------------
# michaud_weights
# ---------------------------------------------------------------------------


class TestMichaud:
    def _inputs(self) -> tuple[pd.Series, pd.DataFrame]:
        rng = np.random.default_rng(7)
        sigma = _random_pd_sigma(rng, 5, scale=1e-2)
        mu = _mu_series(rng.uniform(0.0, 0.01, size=5))
        return mu, sigma

    def test_seed_determinism(self) -> None:
        mu, sigma = self._inputs()
        a = michaud_weights(mu, sigma, n_resamples=10, estimation_window=30, seed=1)
        b = michaud_weights(mu, sigma, n_resamples=10, estimation_window=30, seed=1)
        c = michaud_weights(mu, sigma, n_resamples=10, estimation_window=30, seed=2)
        np.testing.assert_array_equal(a.weights.to_numpy(), b.weights.to_numpy())
        assert not np.allclose(a.weights.to_numpy(), c.weights.to_numpy())

    def test_constraints_preserved_by_averaging(self) -> None:
        mu, sigma = self._inputs()
        sectors = {a: ("tech" if i < 3 else "fin") for i, a in enumerate(_assets(5))}
        result = michaud_weights(
            mu,
            sigma,
            MVOConfig(risk_aversion=4.0, max_weight=0.5),
            n_resamples=25,
            estimation_window=20,
            seed=3,
            sectors=sectors,
            sector_caps={"tech": 0.5},
        )
        w = result.weights
        assert float(w.sum()) == pytest.approx(1.0, abs=1e-7)
        assert bool((w.to_numpy() >= -1e-9).all())
        assert bool((w.to_numpy() <= 0.5 + 1e-7).all())
        assert float(w.iloc[:3].sum()) <= 0.5 + 1e-7
        assert result.n_resamples == 25
        assert result.estimation_window == 20

    def test_converges_to_base_solution_with_long_window(self) -> None:
        mu, sigma = self._inputs()
        cfg = MVOConfig(risk_aversion=4.0)
        base = mean_variance_weights(mu, sigma, cfg)
        resampled = michaud_weights(
            mu, sigma, cfg, n_resamples=20, estimation_window=5000, seed=4
        )
        l1_gap = float(
            np.abs(resampled.weights.to_numpy() - base.weights.to_numpy()).sum()
        )
        assert l1_gap < 0.05

    def test_dispersion_shrinks_with_window(self) -> None:
        mu, sigma = self._inputs()
        noisy = michaud_weights(
            mu, sigma, n_resamples=20, estimation_window=20, seed=5
        )
        precise = michaud_weights(
            mu, sigma, n_resamples=20, estimation_window=2000, seed=5
        )
        assert float(precise.weight_dispersion.mean()) < float(
            noisy.weight_dispersion.mean()
        )

    def test_mean_only_resampling_branch(self) -> None:
        mu, sigma = self._inputs()
        result = michaud_weights(
            mu,
            sigma,
            n_resamples=10,
            estimation_window=30,
            resample_covariance=False,
            seed=6,
        )
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-7)

    def test_bad_n_resamples_raises(self) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="n_resamples"):
            michaud_weights(mu, sigma, n_resamples=0)

    def test_bad_estimation_window_raises(self) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="estimation_window"):
            michaud_weights(mu, sigma, estimation_window=1)


# ---------------------------------------------------------------------------
# robust_mean_variance_weights
# ---------------------------------------------------------------------------


class TestRobustMeanVariance:
    def _inputs(self) -> tuple[pd.Series, pd.DataFrame]:
        rng = np.random.default_rng(8)
        sigma = _random_pd_sigma(rng, 5, scale=1e-2)
        mu = _mu_series(rng.uniform(-0.005, 0.015, size=5))
        return mu, sigma

    def test_kappa_zero_is_exactly_markowitz(self) -> None:
        mu, sigma = self._inputs()
        cfg = MVOConfig(risk_aversion=3.0)
        plain = mean_variance_weights(mu, sigma, cfg)
        robust = robust_mean_variance_weights(mu, sigma, cfg, kappa=0.0, n_obs=50)
        np.testing.assert_array_equal(
            robust.weights.to_numpy(), plain.weights.to_numpy()
        )

    def test_expected_return_monotone_in_kappa(self) -> None:
        mu, sigma = self._inputs()
        cfg = MVOConfig(risk_aversion=3.0)
        returns = [
            robust_mean_variance_weights(
                mu, sigma, cfg, kappa=k, n_obs=50
            ).expected_return
            for k in [0.0, 0.5, 2.0, 10.0]
        ]
        assert all(r is not None for r in returns)
        for early, late in zip(returns, returns[1:], strict=False):
            assert late <= early + 1e-9  # type: ignore[operator]
        assert returns[-1] < returns[0]  # type: ignore[operator]

    def test_large_kappa_reaches_minimum_variance(self) -> None:
        mu, sigma = self._inputs()
        cfg = MVOConfig(risk_aversion=3.0)
        robust = robust_mean_variance_weights(
            mu,
            sigma,
            cfg,
            kappa=1e4,
            mean_uncertainty=sigma,  # ambiguity term = kappa * portfolio vol
        )
        minvar = min_variance_weights(sigma, cfg)
        np.testing.assert_allclose(
            robust.weights.to_numpy(), minvar.weights.to_numpy(), atol=1e-3
        )

    def test_volatility_and_nominal_return_accounting(self) -> None:
        mu, sigma = self._inputs()
        result = robust_mean_variance_weights(
            mu, sigma, MVOConfig(risk_aversion=3.0), kappa=1.0, n_obs=50
        )
        w = result.weights.to_numpy()
        assert result.volatility == pytest.approx(
            float(np.sqrt(w @ sigma.to_numpy() @ w)), abs=1e-10
        )
        assert result.expected_return == pytest.approx(
            float(mu.to_numpy() @ w), abs=1e-12
        )
        assert result.status in ("optimal", "optimal_inaccurate")

    def test_constraint_paths(self) -> None:
        mu, sigma = self._inputs()
        sectors = {a: ("tech" if i < 3 else "fin") for i, a in enumerate(_assets(5))}
        prev = pd.Series(np.full(5, 0.2), index=_assets(5))
        cfg = MVOConfig(
            risk_aversion=3.0,
            gross_cap=1.0,
            max_weight=0.6,
            turnover_cap=0.5,
        )
        result = robust_mean_variance_weights(
            mu,
            sigma,
            cfg,
            kappa=1.0,
            n_obs=50,
            prev_weights=prev,
            sectors=sectors,
            sector_caps={"tech": 0.7},
        )
        w = result.weights
        assert float(np.abs(w.to_numpy()).sum()) <= 1.0 + 1e-6
        assert bool((w.to_numpy() <= 0.6 + 1e-7).all())
        assert float(w.iloc[:3].sum()) <= 0.7 + 1e-6
        assert float(np.abs(w.to_numpy() - prev.to_numpy()).sum()) <= 0.5 + 1e-6

    def test_turnover_cap_without_prev_raises(self) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="prev_weights"):
            robust_mean_variance_weights(
                mu, sigma, MVOConfig(turnover_cap=0.1), kappa=1.0, n_obs=50
            )

    def test_infeasible_problem_raises_with_status(self) -> None:
        # Five assets capped at 0.1 each cannot sum to a budget of 1.
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="status"):
            robust_mean_variance_weights(
                mu, sigma, MVOConfig(max_weight=0.1), kappa=1.0, n_obs=50
            )

    @pytest.mark.parametrize("kappa", [-1.0, float("nan")])
    def test_bad_kappa_raises(self, kappa: float) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="kappa"):
            robust_mean_variance_weights(mu, sigma, kappa=kappa, n_obs=50)

    def test_target_return_mode_rejected(self) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="target_return"):
            robust_mean_variance_weights(
                mu, sigma, MVOConfig(target_return=0.01), kappa=1.0, n_obs=50
            )

    def test_missing_n_obs_raises(self) -> None:
        mu, sigma = self._inputs()
        with pytest.raises(ValueError, match="n_obs"):
            robust_mean_variance_weights(mu, sigma, kappa=1.0)

    def test_mean_uncertainty_label_mismatch_raises(self) -> None:
        mu, sigma = self._inputs()
        bad = pd.DataFrame(
            np.eye(5), index=list("abcde"), columns=list("abcde")
        )
        with pytest.raises(ValueError, match="mean_uncertainty"):
            robust_mean_variance_weights(
                mu, sigma, kappa=1.0, mean_uncertainty=bad
            )

    def test_mean_uncertainty_nan_raises(self) -> None:
        mu, sigma = self._inputs()
        bad = sigma.copy()
        bad.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="mean_uncertainty"):
            robust_mean_variance_weights(
                mu, sigma, kappa=1.0, mean_uncertainty=bad
            )


# ---------------------------------------------------------------------------
# Result DTO and Phase 6 DOD
# ---------------------------------------------------------------------------


class TestResultAndDOD:
    def test_cvar_result_frozen_and_equality(self) -> None:
        result = CVaRResult(
            weights=pd.Series([0.5, 0.5]),
            cvar=0.05,
            block_cvars=(0.05,),
            expected_return=0.001,
            alpha=0.95,
            status="optimal",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.cvar = 0.1  # type: ignore[misc]
        same_meta = CVaRResult(
            weights=pd.Series([0.9, 0.1]),
            cvar=0.05,
            block_cvars=(0.05,),
            expected_return=0.001,
            alpha=0.95,
            status="optimal",
        )
        assert result == same_meta

    def test_michaud_result_frozen(self) -> None:
        rng = np.random.default_rng(9)
        sigma = _random_pd_sigma(rng, 3, scale=1e-2)
        mu = _mu_series([0.001, 0.002, 0.003])
        result = michaud_weights(mu, sigma, n_resamples=3, estimation_window=20)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.n_resamples = 5  # type: ignore[misc]

    def test_twenty_assets_under_one_second_each(self) -> None:
        rng = np.random.default_rng(10)
        sigma = _random_pd_sigma(rng, 20, scale=1e-4)
        mu = _mu_series(rng.uniform(0.0, 0.002, size=20))
        scenarios = _scenario_df(rng.normal(0.0005, 0.01, size=(500, 20)))

        start = time.perf_counter()
        cvar_weights(scenarios, CVaRConfig(alpha=0.95))
        cvar_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        robust_mean_variance_weights(
            mu, sigma, MVOConfig(risk_aversion=3.0), kappa=1.0, n_obs=60
        )
        robust_elapsed = time.perf_counter() - start

        # Resampling is embarrassingly parallel; 50 draws is the
        # single-threaded budget that fits the < 1 s DOD gate.
        start = time.perf_counter()
        michaud_weights(
            mu,
            sigma,
            MVOConfig(risk_aversion=3.0),
            n_resamples=50,
            estimation_window=60,
            seed=11,
        )
        michaud_elapsed = time.perf_counter() - start

        assert cvar_elapsed < 1.0, f"CVaR took {cvar_elapsed:.3f}s"
        assert robust_elapsed < 1.0, f"robust MV took {robust_elapsed:.3f}s"
        assert michaud_elapsed < 1.0, f"Michaud(50) took {michaud_elapsed:.3f}s"
