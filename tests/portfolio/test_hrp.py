"""Tests for core_trading.portfolio.hrp (Phase 6.3).

Covers:
* De Prado's worked example, recovered end to end: the exact 10-asset
  dataset from AFML Snippet 16.4 (regenerated with his seeds: numpy
  RandomState(12345) + stdlib random.Random(12345)) run through faithful
  test-local transcriptions of Snippets 16.1-16.3 (quasi-diagonalisation
  and recursive bisection) must match the module's output to 1e-12, and
  the module's sort order must equal the snippet recursion's leaf order.
* The diagonal closed form: for a diagonal covariance with a power-of-two
  asset count HRP reproduces the global inverse-variance portfolio
  exactly; for N = 2 the IVP closed form holds for any covariance.
* The no-inversion selling point: a singular PSD covariance (T < N sample
  matrix; a perfectly-correlated duplicate pair) is accepted and yields
  valid weights.
* Structural properties on random matrices: strictly positive weights
  summing to 1, sort_order a permutation, linkage shape (N-1, 4).
* Symmetric two-block matrices give the symmetric (equal-weight) answer.
* correlation_distance: known values, float-residue clipping, validation.
* Config / input validation and the frozen result DTO.
* Phase 6 DOD: 20-asset solve in < 1 s; perturbation stability.
"""

from __future__ import annotations

import dataclasses
import random as stdlib_random
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.hrp import (
    HRPConfig,
    HRPResult,
    correlation_distance,
    hrp_weights,
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


def _two_block_sigma(n: int, rho_within: float, vol: float = 0.1) -> pd.DataFrame:
    """Two equal blocks with high internal correlation, zero across."""
    half = n // 2
    corr = np.eye(n)
    corr[:half, :half] = rho_within
    corr[half:, half:] = rho_within
    np.fill_diagonal(corr, 1.0)
    return _sigma_df(corr * vol * vol)


# ---------------------------------------------------------------------------
# Test-local transcriptions of de Prado's snippets (AFML 16.1-16.4)
# ---------------------------------------------------------------------------


def _snippet_quasi_diag(link: np.ndarray) -> list[int]:
    """Snippet 16.2 logic: expand the linkage tree into leaf order."""
    link_int = link.astype(int)
    n_items = int(link_int[-1, 3])
    sort_ix: list[int] = [int(link_int[-1, 0]), int(link_int[-1, 1])]
    while max(sort_ix) >= n_items:
        expanded: list[int] = []
        for item in sort_ix:
            if item >= n_items:
                j = item - n_items
                expanded.append(int(link_int[j, 0]))
                expanded.append(int(link_int[j, 1]))
            else:
                expanded.append(item)
        sort_ix = expanded
    return sort_ix


def _snippet_ivp(cov: np.ndarray) -> np.ndarray:
    inv = 1.0 / np.diag(cov)
    out: np.ndarray = inv / inv.sum()
    return out


def _snippet_cluster_var(cov: np.ndarray, items: list[int]) -> float:
    sub = cov[np.ix_(items, items)]
    w = _snippet_ivp(sub)
    return float(w @ sub @ w)


def _snippet_rec_bipart(cov: np.ndarray, sort_ix: list[int]) -> np.ndarray:
    """Snippet 16.3 logic: recursive bisection over the sorted list."""
    weights = np.ones(cov.shape[0])
    clusters = [list(sort_ix)]
    while clusters:
        clusters = [
            part
            for cluster in clusters
            for part in (cluster[: len(cluster) // 2], cluster[len(cluster) // 2 :])
            if len(cluster) > 1
        ]
        for k in range(0, len(clusters), 2):
            left, right = clusters[k], clusters[k + 1]
            v_left = _snippet_cluster_var(cov, left)
            v_right = _snippet_cluster_var(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
    return weights


def _de_prado_panel() -> pd.DataFrame:
    """Snippet 16.4 generateData with the original seeds (10 assets)."""
    n_obs, size0, size1, sigma1 = 10_000, 5, 5, 0.25
    np_rng = np.random.RandomState(12345)  # legacy generator on purpose: de Prado's seed
    py_rng = stdlib_random.Random(12345)
    x = np_rng.normal(0.0, 1.0, size=(n_obs, size0))
    cols = [py_rng.randint(0, size0 - 1) for _ in range(size1)]
    y = x[:, cols] + np_rng.normal(0.0, sigma1, size=(n_obs, size1))
    data = np.append(x, y, axis=1)
    return pd.DataFrame(data, columns=_assets(size0 + size1))


# ---------------------------------------------------------------------------
# De Prado worked example
# ---------------------------------------------------------------------------


class TestDePradoWorkedExample:
    def test_module_matches_snippet_pipeline_exactly(self) -> None:
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import squareform

        panel = _de_prado_panel()
        cov = panel.cov()
        corr = panel.corr()

        # Reference pipeline: Snippets 16.1-16.4 verbatim logic.
        dist = np.sqrt((1.0 - corr.to_numpy()) / 2.0)
        np.fill_diagonal(dist, 0.0)
        link = linkage(squareform(dist, checks=False), method="single")
        ref_order = _snippet_quasi_diag(link)
        ref_weights = _snippet_rec_bipart(cov.to_numpy(), ref_order)

        result = hrp_weights(cov)
        np.testing.assert_allclose(
            result.weights.to_numpy(), ref_weights, atol=1e-12
        )
        assert result.sort_order == tuple(panel.columns[i] for i in ref_order)
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)
        assert bool((result.weights.to_numpy() > 0.0).all())

    def test_correlated_duplicates_get_down_weighted(self) -> None:
        # The economic point of the worked example: the five duplicated
        # (highly correlated) series must collectively receive less weight
        # per asset than the five independent originals.
        panel = _de_prado_panel()
        result = hrp_weights(panel.cov())
        weights = result.weights.to_numpy()
        originals = weights[:5]
        duplicates = weights[5:]
        assert float(duplicates.mean()) < float(originals.mean())


# ---------------------------------------------------------------------------
# Closed forms
# ---------------------------------------------------------------------------


class TestClosedForms:
    def test_diagonal_power_of_two_equals_ivp(self) -> None:
        variances = np.array([1.0, 2.0, 3.0, 4.0])
        sigma = _sigma_df(np.diag(variances))
        result = hrp_weights(sigma)
        ivp = (1.0 / variances) / (1.0 / variances).sum()
        np.testing.assert_allclose(result.weights.to_numpy(), ivp, atol=1e-12)

    def test_two_assets_ivp_closed_form(self) -> None:
        sigma = _sigma_df(np.array([[0.04, 0.012], [0.012, 0.09]]))
        result = hrp_weights(sigma)
        expected = np.array([0.09, 0.04]) / 0.13
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-12)

    def test_symmetric_two_blocks_equal_weights(self) -> None:
        sigma = _two_block_sigma(4, rho_within=0.8)
        result = hrp_weights(sigma)
        np.testing.assert_allclose(result.weights.to_numpy(), 0.25, atol=1e-10)


# ---------------------------------------------------------------------------
# No-inversion selling point
# ---------------------------------------------------------------------------


class TestSingularInputs:
    def test_rank_deficient_sample_covariance_accepted(self) -> None:
        # T = 10 observations of N = 20 assets: rank <= 9, hopelessly
        # singular for Markowitz, fine for HRP.
        rng = np.random.default_rng(0)
        panel = pd.DataFrame(
            rng.standard_normal((10, 20)) * 0.01, columns=_assets(20)
        )
        cov = panel.cov()
        assert float(np.linalg.eigvalsh(cov.to_numpy())[0]) < 1e-12  # singular
        result = hrp_weights(cov)
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)
        assert bool((result.weights.to_numpy() > 0.0).all())

    def test_perfectly_correlated_pair_accepted(self) -> None:
        sigma = _sigma_df(
            np.array(
                [
                    [1.0, 1.0, 0.0],
                    [1.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ]
            )
        )
        result = hrp_weights(sigma)
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)
        assert bool((result.weights.to_numpy() > 0.0).all())


# ---------------------------------------------------------------------------
# Structural properties
# ---------------------------------------------------------------------------


class TestStructuralProperties:
    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_valid_portfolio_random_pd(self, seed: int) -> None:
        rng = np.random.default_rng(seed)
        sigma = _random_pd_sigma(rng, 10)
        result = hrp_weights(sigma)
        w = result.weights.to_numpy()
        assert float(w.sum()) == pytest.approx(1.0, abs=1e-12)
        assert bool((w > 0.0).all())
        assert sorted(result.sort_order) == sorted(sigma.index)
        assert result.linkage.shape == (9, 4)
        assert list(result.weights.index) == list(sigma.index)

    @pytest.mark.parametrize("method", ["single", "complete", "average", "ward"])
    def test_linkage_methods_all_give_valid_portfolios(self, method: str) -> None:
        rng = np.random.default_rng(5)
        sigma = _random_pd_sigma(rng, 8)
        result = hrp_weights(sigma, HRPConfig(linkage_method=method))
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)
        assert bool((result.weights.to_numpy() > 0.0).all())

    def test_invalid_linkage_method_raises(self) -> None:
        with pytest.raises(ValueError, match="linkage_method"):
            HRPConfig(linkage_method="centroid")


# ---------------------------------------------------------------------------
# correlation_distance
# ---------------------------------------------------------------------------


class TestCorrelationDistance:
    def test_known_values(self) -> None:
        corr = np.array([[1.0, 0.0], [0.0, 1.0]])
        dist = correlation_distance(corr)
        np.testing.assert_allclose(dist, [[0.0, np.sqrt(0.5)], [np.sqrt(0.5), 0.0]])

    def test_extremes(self) -> None:
        corr = np.array([[1.0, -1.0], [-1.0, 1.0]])
        dist = correlation_distance(corr)
        assert dist[0, 1] == pytest.approx(1.0)
        assert dist[0, 0] == 0.0

    def test_float_residue_clipped_not_nan(self) -> None:
        corr = np.array([[1.0, 1.0 + 1e-12], [1.0 + 1e-12, 1.0]])
        dist = correlation_distance(corr)
        assert np.isfinite(dist).all()
        assert dist[0, 1] == 0.0

    def test_material_violation_raises(self) -> None:
        corr = np.array([[1.0, 1.5], [1.5, 1.0]])
        with pytest.raises(ValueError, match="not a correlation matrix"):
            correlation_distance(corr)

    def test_non_square_raises(self) -> None:
        with pytest.raises(ValueError, match="square"):
            correlation_distance(np.zeros((2, 3)))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_sigma_not_square(self) -> None:
        bad = pd.DataFrame(np.zeros((2, 3)), index=["a", "b"], columns=["a", "b", "c"])
        with pytest.raises(ValueError, match="square"):
            hrp_weights(bad)

    def test_sigma_label_mismatch(self) -> None:
        bad = pd.DataFrame(np.eye(2), index=["a", "b"], columns=["b", "a"])
        with pytest.raises(ValueError, match="identical asset labels"):
            hrp_weights(bad)

    def test_sigma_single_asset(self) -> None:
        bad = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        with pytest.raises(ValueError, match="at least 2 assets"):
            hrp_weights(bad)

    def test_sigma_nan(self) -> None:
        arr = np.eye(2)
        arr[0, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            hrp_weights(_sigma_df(arr))

    def test_sigma_zero(self) -> None:
        with pytest.raises(ValueError, match="identically zero"):
            hrp_weights(_sigma_df(np.zeros((2, 2))))

    def test_sigma_asymmetric(self) -> None:
        arr = np.array([[1.0, 0.3], [0.0, 1.0]])
        with pytest.raises(ValueError, match="symmetric"):
            hrp_weights(_sigma_df(arr))

    def test_sigma_nonpositive_variance(self) -> None:
        arr = np.array([[1.0, 0.0], [0.0, 0.0]])
        with pytest.raises(ValueError, match="A01"):
            hrp_weights(_sigma_df(arr))


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class TestHRPResult:
    def test_frozen(self) -> None:
        result = hrp_weights(_sigma_df(np.eye(2)))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.sort_order = ("x",)  # type: ignore[misc]

    def test_equality_compares_sort_order_not_arrays(self) -> None:
        a = HRPResult(
            weights=pd.Series([0.5, 0.5]),
            sort_order=("A", "B"),
            linkage=np.zeros((1, 4)),
        )
        b = HRPResult(
            weights=pd.Series([0.9, 0.1]),
            sort_order=("A", "B"),
            linkage=np.ones((1, 4)),
        )
        c = HRPResult(
            weights=pd.Series([0.5, 0.5]),
            sort_order=("B", "A"),
            linkage=np.zeros((1, 4)),
        )
        assert a == b
        assert a != c


# ---------------------------------------------------------------------------
# Phase 6 DOD: performance and stability
# ---------------------------------------------------------------------------


class TestPhase6DOD:
    def test_twenty_assets_under_one_second(self) -> None:
        rng = np.random.default_rng(6)
        sigma = _random_pd_sigma(rng, 20)
        start = time.perf_counter()
        result = hrp_weights(sigma)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"20-asset HRP took {elapsed:.3f}s"
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)

    def test_perturbation_stability_variance_bumps(self) -> None:
        # Perturbing only the VARIANCES (1% diagonal rescaling) leaves the
        # correlation matrix -- and therefore the tree and leaf order --
        # exactly unchanged, isolating HRP's continuous arithmetic: the
        # recursive-bisection alphas must respond smoothly.
        rng = np.random.default_rng(7)
        sigma = _random_pd_sigma(rng, 20)
        scale = np.sqrt(rng.uniform(0.99, 1.01, size=20))
        perturbed_arr = sigma.to_numpy() * np.outer(scale, scale)
        perturbed = pd.DataFrame(
            perturbed_arr, index=sigma.index, columns=sigma.columns
        )
        base = hrp_weights(sigma)
        pert = hrp_weights(perturbed)
        assert pert.sort_order == base.sort_order  # tree unchanged
        l1_change = float(
            np.abs(base.weights.to_numpy() - pert.weights.to_numpy()).sum()
        )
        assert l1_change < 0.05

    def test_inversion_instability_check_near_twin_universe(self) -> None:
        # The master plan's "matrix-inversion-instability check", on de
        # Prado's own motivating case: a universe of near-duplicate asset
        # pairs.  Closed-form minimum variance (Sigma^{-1} 1, the textbook
        # inversion) takes huge offsetting positions within each twin pair
        # and reshuffles violently under a 1% data bump; HRP clusters the
        # twins and barely moves (orders of magnitude more stable).
        rng = np.random.default_rng(9)
        n_obs, n_pairs = 50, 10
        common = rng.standard_normal((n_obs, n_pairs)) * 0.01
        data = np.empty((n_obs, 2 * n_pairs))
        for p in range(n_pairs):
            data[:, 2 * p] = common[:, p] + rng.standard_normal(n_obs) * 0.0005
            data[:, 2 * p + 1] = common[:, p] + rng.standard_normal(n_obs) * 0.0005
        base_panel = pd.DataFrame(data, columns=_assets(2 * n_pairs))
        bumped_panel = base_panel + rng.standard_normal(data.shape) * 1e-4
        cov_base = base_panel.cov()
        cov_bumped = bumped_panel.cov()

        ones = np.ones(2 * n_pairs)

        def closed_form_minvar(cov: pd.DataFrame) -> np.ndarray:
            x = np.linalg.solve(cov.to_numpy(), ones)
            out: np.ndarray = x / x.sum()
            return out

        inversion_change = float(
            np.abs(
                closed_form_minvar(cov_base) - closed_form_minvar(cov_bumped)
            ).sum()
        )
        hrp_change = float(
            np.abs(
                hrp_weights(cov_base).weights.to_numpy()
                - hrp_weights(cov_bumped).weights.to_numpy()
            ).sum()
        )
        assert hrp_change < inversion_change / 100.0
        assert hrp_change < 0.05

    def test_perturbation_stability_block_allocation_under_ties(self) -> None:
        # With tied within-block distances individual weights CAN reshuffle
        # (split-by-position bisection), but the aggregate allocation to
        # each block must stay put.
        rng = np.random.default_rng(8)
        sigma = _two_block_sigma(20, rho_within=0.7)
        noise = 1.0 + 0.01 * rng.standard_normal(sigma.shape)
        perturbed_arr = sigma.to_numpy() * (noise + noise.T) / 2.0
        perturbed = pd.DataFrame(
            perturbed_arr, index=sigma.index, columns=sigma.columns
        )
        w_base = hrp_weights(sigma).weights
        w_pert = hrp_weights(perturbed).weights
        block1 = [f"A{i:02d}" for i in range(10)]
        base_block1 = float(w_base[block1].sum())
        pert_block1 = float(w_pert[block1].sum())
        assert base_block1 == pytest.approx(0.5, abs=1e-9)
        assert abs(base_block1 - pert_block1) < 0.02
