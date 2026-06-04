"""Tests for core_trading.portfolio.black_litterman (Phase 6.2).

Covers:
* The algebraic-identity cross-check: the module's stable k x k form must
  equal a test-local transcription of the textbook information form
  mu = [(tau S)^-1 + P' O^-1 P]^-1 [(tau S)^-1 pi + P' O^-1 Q] for both
  the posterior mean and the posterior covariance of the mean.
* Reverse optimisation round trip: pi = delta Sigma w_mkt fed back into
  the Batch 2 Markowitz solver returns the market weights.
* Confidence limits and monotonicity (the Omega dial of the master plan):
  near-zero Omega imposes the view (P mu == Q); near-zero confidence
  leaves the prior untouched; the posterior moves monotonically towards
  the view as confidence rises.
* A fully hand-computed 2-asset absolute-view example.
* The no-views degeneracy: mu == pi, Sigma_BL == (1 + tau) Sigma.
* Default Omega == diag(P tau Sigma P') / confidences.
* Posterior covariance structure: symmetric, Sigma_BL - Sigma PSD, and
  tau Sigma - M PSD (views can only reduce the mean uncertainty).
* The singular view-system error path and the full validation battery.
* Frozen result DTO; Phase 6 DOD performance (20 assets < 1 s).
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.black_litterman import (
    BlackLittermanResult,
    black_litterman,
    implied_equilibrium_returns,
)
from core_trading.portfolio.mvo import MVOConfig, mean_variance_weights

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assets(n: int) -> list[str]:
    return [f"A{i:02d}" for i in range(n)]


def _sigma_df(arr: np.ndarray) -> pd.DataFrame:
    names = _assets(arr.shape[0])
    return pd.DataFrame(np.asarray(arr, dtype=float), index=names, columns=names)


def _random_pd_sigma(rng: np.random.Generator, n: int, scale: float = 1e-2) -> pd.DataFrame:
    q, _ = np.linalg.qr(rng.standard_normal((n, n)))
    eigenvalues = rng.uniform(0.5, 2.0, size=n)
    sigma = ((q * eigenvalues) @ q.T) * scale
    return _sigma_df((sigma + sigma.T) / 2.0)


def _market_weights(n: int) -> pd.Series:
    raw = np.arange(1, n + 1, dtype=float)
    return pd.Series(raw / raw.sum(), index=_assets(n))


def _views_df(rows: np.ndarray, n_assets: int) -> pd.DataFrame:
    rows = np.atleast_2d(np.asarray(rows, dtype=float))
    labels = [f"view{i}" for i in range(rows.shape[0])]
    return pd.DataFrame(rows, index=labels, columns=_assets(n_assets))


def _information_form_reference(
    sigma: np.ndarray,
    pi: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    omega: np.ndarray,
    tau: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Textbook information (precision-mixing) form with explicit inverses."""
    tau_sigma_inv = np.linalg.inv(tau * sigma)
    omega_inv = np.linalg.inv(omega)
    a = tau_sigma_inv + p.T @ omega_inv @ p
    m = np.linalg.inv(a)
    mu = m @ (tau_sigma_inv @ pi + p.T @ omega_inv @ q)
    return mu, m


# ---------------------------------------------------------------------------
# Equilibrium returns
# ---------------------------------------------------------------------------


class TestImpliedEquilibrium:
    def test_formula(self) -> None:
        rng = np.random.default_rng(0)
        sigma = _random_pd_sigma(rng, 4)
        w = _market_weights(4)
        pi = implied_equilibrium_returns(sigma, w, risk_aversion=3.0)
        np.testing.assert_allclose(
            pi.to_numpy(), 3.0 * sigma.to_numpy() @ w.to_numpy(), atol=1e-15
        )
        assert list(pi.index) == list(sigma.index)

    def test_reverse_optimisation_round_trip(self) -> None:
        # Feeding pi back into the Batch 2 Markowitz solver at the same
        # risk aversion must return the market portfolio: the prior is
        # DEFINED as the return vector that makes w_mkt optimal.
        rng = np.random.default_rng(1)
        sigma = _random_pd_sigma(rng, 5)
        w_mkt = _market_weights(5)
        delta = 2.5
        pi = implied_equilibrium_returns(sigma, w_mkt, risk_aversion=delta)
        result = mean_variance_weights(
            pi, sigma, MVOConfig(risk_aversion=delta, long_only=False)
        )
        np.testing.assert_allclose(
            result.weights.to_numpy(), w_mkt.to_numpy(), atol=1e-6
        )

    @pytest.mark.parametrize("delta", [0.0, -1.0, float("nan")])
    def test_bad_risk_aversion(self, delta: float) -> None:
        sigma = _sigma_df(np.eye(2))
        w = _market_weights(2)
        with pytest.raises(ValueError, match="risk_aversion"):
            implied_equilibrium_returns(sigma, w, risk_aversion=delta)

    def test_misaligned_weights(self) -> None:
        sigma = _sigma_df(np.eye(2))
        w = pd.Series([0.5, 0.5], index=["A01", "A00"])
        with pytest.raises(ValueError, match="market_weights"):
            implied_equilibrium_returns(sigma, w)


# ---------------------------------------------------------------------------
# Posterior: algebraic cross-check and hand example
# ---------------------------------------------------------------------------


class TestPosterior:
    @pytest.mark.parametrize("seed,n,k", [(2, 5, 2), (3, 8, 3)])
    def test_matches_information_form(self, seed: int, n: int, k: int) -> None:
        rng = np.random.default_rng(seed)
        sigma = _random_pd_sigma(rng, n)
        w_mkt = _market_weights(n)
        p = rng.standard_normal((k, n))
        q = rng.standard_normal(k) * 0.01
        omega_diag = rng.uniform(0.5, 2.0, size=k) * 1e-4
        omega = pd.DataFrame(
            np.diag(omega_diag),
            index=[f"view{i}" for i in range(k)],
            columns=[f"view{i}" for i in range(k)],
        )
        tau = 0.05

        result = black_litterman(
            sigma,
            market_weights=w_mkt,
            risk_aversion=2.5,
            views=_views_df(p, n),
            view_returns=pd.Series(q, index=omega.index),
            omega=omega,
            tau=tau,
        )

        pi = implied_equilibrium_returns(sigma, w_mkt, risk_aversion=2.5)
        ref_mu, ref_m = _information_form_reference(
            sigma.to_numpy(), pi.to_numpy(), p, q, np.diag(omega_diag), tau
        )
        np.testing.assert_allclose(
            result.posterior_means.to_numpy(), ref_mu, atol=1e-10
        )
        np.testing.assert_allclose(
            result.posterior_covariance.to_numpy(),
            sigma.to_numpy() + ref_m,
            atol=1e-10,
        )
        np.testing.assert_allclose(
            result.equilibrium_returns.to_numpy(), pi.to_numpy(), atol=1e-15
        )
        assert result.tau == tau

    def test_two_asset_hand_example(self) -> None:
        # Diagonal sigma, one absolute view on asset 0: the posterior is
        # the scalar precision-weighted blend; asset 1 is untouched.
        var0, var1 = 0.04, 0.09
        sigma = _sigma_df(np.diag([var0, var1]))
        pi = pd.Series([0.05, 0.07], index=_assets(2))
        tau, q0, omega0 = 0.05, 0.10, 0.002
        result = black_litterman(
            sigma,
            prior_means=pi,
            views=_views_df(np.array([[1.0, 0.0]]), 2),
            view_returns=pd.Series([q0], index=["view0"]),
            omega=pd.DataFrame([[omega0]], index=["view0"], columns=["view0"]),
            tau=tau,
        )
        ts0 = tau * var0
        expected0 = 0.05 + ts0 * (q0 - 0.05) / (ts0 + omega0)
        assert result.posterior_means["A00"] == pytest.approx(expected0, abs=1e-12)
        assert result.posterior_means["A01"] == pytest.approx(0.07, abs=1e-12)
        # Posterior covariance: asset 0's mean uncertainty shrinks, asset
        # 1 keeps the full tau * var1; off-diagonal stays zero.
        expected_m00 = ts0 - ts0 * ts0 / (ts0 + omega0)
        cov = result.posterior_covariance
        assert cov.loc["A00", "A00"] == pytest.approx(var0 + expected_m00, abs=1e-12)
        assert cov.loc["A01", "A01"] == pytest.approx(var1 + tau * var1, abs=1e-12)
        assert cov.loc["A00", "A01"] == pytest.approx(0.0, abs=1e-15)

    def test_no_views_degenerates_to_prior(self) -> None:
        rng = np.random.default_rng(4)
        sigma = _random_pd_sigma(rng, 4)
        w_mkt = _market_weights(4)
        tau = 0.07
        result = black_litterman(sigma, market_weights=w_mkt, tau=tau)
        pi = implied_equilibrium_returns(sigma, w_mkt)
        np.testing.assert_allclose(
            result.posterior_means.to_numpy(), pi.to_numpy(), atol=1e-15
        )
        np.testing.assert_allclose(
            result.posterior_covariance.to_numpy(),
            (1.0 + tau) * sigma.to_numpy(),
            atol=1e-15,
        )
        assert result.omega is None


# ---------------------------------------------------------------------------
# Omega and confidence behaviour
# ---------------------------------------------------------------------------


class TestOmegaConfidence:
    def _setup(self) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        rng = np.random.default_rng(5)
        sigma = _random_pd_sigma(rng, 4)
        pi = pd.Series([0.02, 0.03, 0.04, 0.05], index=_assets(4))
        views = _views_df(np.array([[1.0, -1.0, 0.0, 0.0]]), 4)
        q = pd.Series([0.05], index=["view0"])
        return sigma, pi, views, q

    def test_default_omega_is_proportional(self) -> None:
        sigma, pi, views, q = self._setup()
        tau = 0.05
        result = black_litterman(
            sigma, prior_means=pi, views=views, view_returns=q, tau=tau
        )
        p = views.to_numpy()
        expected = p @ (tau * sigma.to_numpy()) @ p.T
        assert result.omega is not None
        np.testing.assert_allclose(
            result.omega.to_numpy(), np.diag(np.diag(expected)), atol=1e-15
        )

    def test_confidence_scales_default_omega(self) -> None:
        sigma, pi, views, q = self._setup()
        confident = black_litterman(
            sigma,
            prior_means=pi,
            views=views,
            view_returns=q,
            view_confidences=pd.Series([2.0], index=["view0"]),
        )
        baseline = black_litterman(
            sigma, prior_means=pi, views=views, view_returns=q
        )
        assert confident.omega is not None and baseline.omega is not None
        np.testing.assert_allclose(
            confident.omega.to_numpy(), baseline.omega.to_numpy() / 2.0, atol=1e-18
        )

    def test_full_confidence_imposes_view(self) -> None:
        sigma, pi, views, q = self._setup()
        result = black_litterman(
            sigma,
            prior_means=pi,
            views=views,
            view_returns=q,
            view_confidences=pd.Series([1e12], index=["view0"]),
        )
        achieved = float((views.to_numpy() @ result.posterior_means.to_numpy())[0])
        assert achieved == pytest.approx(float(q.iloc[0]), abs=1e-6)

    def test_zero_confidence_keeps_prior(self) -> None:
        sigma, pi, views, q = self._setup()
        result = black_litterman(
            sigma,
            prior_means=pi,
            views=views,
            view_returns=q,
            view_confidences=pd.Series([1e-12], index=["view0"]),
        )
        np.testing.assert_allclose(
            result.posterior_means.to_numpy(), pi.to_numpy(), atol=1e-9
        )

    def test_posterior_moves_monotonically_with_confidence(self) -> None:
        sigma, pi, views, q = self._setup()
        gaps = []
        for conf in [0.5, 1.0, 2.0, 10.0]:
            result = black_litterman(
                sigma,
                prior_means=pi,
                views=views,
                view_returns=q,
                view_confidences=pd.Series([conf], index=["view0"]),
            )
            achieved = float(
                (views.to_numpy() @ result.posterior_means.to_numpy())[0]
            )
            gaps.append(abs(achieved - float(q.iloc[0])))
        assert gaps == sorted(gaps, reverse=True)
        assert gaps[-1] < gaps[0]

    def test_posterior_covariance_structure(self) -> None:
        sigma, pi, views, q = self._setup()
        tau = 0.05
        result = black_litterman(
            sigma, prior_means=pi, views=views, view_returns=q, tau=tau
        )
        s = sigma.to_numpy()
        sigma_bl = result.posterior_covariance.to_numpy()
        np.testing.assert_allclose(sigma_bl, sigma_bl.T, atol=1e-14)
        m = sigma_bl - s
        # Views only ever REDUCE mean uncertainty: 0 <= M <= tau Sigma.
        assert float(np.linalg.eigvalsh(m)[0]) >= -1e-12
        assert float(np.linalg.eigvalsh(tau * s - m)[0]) >= -1e-12


# ---------------------------------------------------------------------------
# Validation battery
# ---------------------------------------------------------------------------


class TestValidation:
    def _base(self) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        sigma = _sigma_df(np.diag([0.04, 0.09]))
        pi = pd.Series([0.05, 0.07], index=_assets(2))
        views = _views_df(np.array([[1.0, 0.0]]), 2)
        q = pd.Series([0.1], index=["view0"])
        return sigma, pi, views, q

    @pytest.mark.parametrize("tau", [0.0, -0.05, float("nan")])
    def test_bad_tau(self, tau: float) -> None:
        sigma, pi, _, _ = self._base()
        with pytest.raises(ValueError, match="tau"):
            black_litterman(sigma, prior_means=pi, tau=tau)

    def test_both_priors_raise(self) -> None:
        sigma, pi, _, _ = self._base()
        with pytest.raises(ValueError, match="exactly one"):
            black_litterman(sigma, market_weights=_market_weights(2), prior_means=pi)

    def test_neither_prior_raises(self) -> None:
        sigma, _, _, _ = self._base()
        with pytest.raises(ValueError, match="exactly one"):
            black_litterman(sigma)

    def test_views_without_returns_raises(self) -> None:
        sigma, pi, views, _ = self._base()
        with pytest.raises(ValueError, match="together"):
            black_litterman(sigma, prior_means=pi, views=views)

    def test_returns_without_views_raises(self) -> None:
        sigma, pi, _, q = self._base()
        with pytest.raises(ValueError, match="together"):
            black_litterman(sigma, prior_means=pi, view_returns=q)

    def test_empty_views_raises(self) -> None:
        sigma, pi, _, _ = self._base()
        empty = pd.DataFrame(np.zeros((0, 2)), columns=_assets(2))
        with pytest.raises(ValueError, match="at least one row"):
            black_litterman(
                sigma,
                prior_means=pi,
                views=empty,
                view_returns=pd.Series(dtype=float),
            )

    def test_views_column_mismatch_raises(self) -> None:
        sigma, pi, _, q = self._base()
        bad = pd.DataFrame([[1.0, 0.0]], index=["view0"], columns=["A01", "A00"])
        with pytest.raises(ValueError, match="views columns"):
            black_litterman(sigma, prior_means=pi, views=bad, view_returns=q)

    def test_view_returns_index_mismatch_raises(self) -> None:
        sigma, pi, views, _ = self._base()
        bad_q = pd.Series([0.1], index=["other"])
        with pytest.raises(ValueError, match="view_returns index"):
            black_litterman(sigma, prior_means=pi, views=views, view_returns=bad_q)

    def test_nan_in_views_raises(self) -> None:
        sigma, pi, _, q = self._base()
        bad = _views_df(np.array([[np.nan, 0.0]]), 2)
        with pytest.raises(ValueError, match="views contain"):
            black_litterman(sigma, prior_means=pi, views=bad, view_returns=q)

    def test_nan_in_view_returns_raises(self) -> None:
        sigma, pi, views, _ = self._base()
        bad_q = pd.Series([np.nan], index=["view0"])
        with pytest.raises(ValueError, match="view_returns contain"):
            black_litterman(sigma, prior_means=pi, views=views, view_returns=bad_q)

    def test_zero_view_row_raises(self) -> None:
        sigma, pi, _, q = self._base()
        bad = _views_df(np.array([[0.0, 0.0]]), 2)
        with pytest.raises(ValueError, match="non-zero"):
            black_litterman(sigma, prior_means=pi, views=bad, view_returns=q)

    def test_omega_and_confidences_together_raise(self) -> None:
        sigma, pi, views, q = self._base()
        omega = pd.DataFrame([[1e-4]], index=["view0"], columns=["view0"])
        with pytest.raises(ValueError, match="not both"):
            black_litterman(
                sigma,
                prior_means=pi,
                views=views,
                view_returns=q,
                omega=omega,
                view_confidences=pd.Series([1.0], index=["view0"]),
            )

    def test_omega_label_mismatch_raises(self) -> None:
        sigma, pi, views, q = self._base()
        omega = pd.DataFrame([[1e-4]], index=["other"], columns=["other"])
        with pytest.raises(ValueError, match="omega index"):
            black_litterman(
                sigma, prior_means=pi, views=views, view_returns=q, omega=omega
            )

    def test_omega_nan_raises(self) -> None:
        sigma, pi, views, q = self._base()
        omega = pd.DataFrame([[np.nan]], index=["view0"], columns=["view0"])
        with pytest.raises(ValueError, match="omega contains"):
            black_litterman(
                sigma, prior_means=pi, views=views, view_returns=q, omega=omega
            )

    def test_omega_asymmetric_raises(self) -> None:
        sigma, pi, _, _ = self._base()
        views = _views_df(np.array([[1.0, 0.0], [0.0, 1.0]]), 2)
        q = pd.Series([0.1, 0.1], index=["view0", "view1"])
        omega = pd.DataFrame(
            [[1e-4, 1e-5], [0.0, 1e-4]],
            index=["view0", "view1"],
            columns=["view0", "view1"],
        )
        with pytest.raises(ValueError, match="omega must be symmetric"):
            black_litterman(
                sigma, prior_means=pi, views=views, view_returns=q, omega=omega
            )

    def test_omega_nonpositive_diagonal_raises(self) -> None:
        sigma, pi, views, q = self._base()
        omega = pd.DataFrame([[0.0]], index=["view0"], columns=["view0"])
        with pytest.raises(ValueError, match="strictly positive"):
            black_litterman(
                sigma, prior_means=pi, views=views, view_returns=q, omega=omega
            )

    def test_confidences_index_mismatch_raises(self) -> None:
        sigma, pi, views, q = self._base()
        with pytest.raises(ValueError, match="view_confidences index"):
            black_litterman(
                sigma,
                prior_means=pi,
                views=views,
                view_returns=q,
                view_confidences=pd.Series([1.0], index=["other"]),
            )

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
    def test_confidences_nonpositive_raise(self, bad: float) -> None:
        sigma, pi, views, q = self._base()
        with pytest.raises(ValueError, match="view_confidences"):
            black_litterman(
                sigma,
                prior_means=pi,
                views=views,
                view_returns=q,
                view_confidences=pd.Series([bad], index=["view0"]),
            )

    def test_prior_means_misaligned_raises(self) -> None:
        sigma, _, _, _ = self._base()
        bad_pi = pd.Series([0.05, 0.07], index=["A01", "A00"])
        with pytest.raises(ValueError, match="prior_means"):
            black_litterman(sigma, prior_means=bad_pi)

    def test_sigma_indefinite_raises(self) -> None:
        arr = np.array([[1.0, 2.0], [2.0, 1.0]])
        pi = pd.Series([0.05, 0.07], index=_assets(2))
        with pytest.raises(ValueError, match="indefinite"):
            black_litterman(_sigma_df(arr), prior_means=pi)

    def test_sigma_not_square_raises(self) -> None:
        bad = pd.DataFrame(np.zeros((2, 3)), index=["a", "b"], columns=["a", "b", "c"])
        with pytest.raises(ValueError, match="square"):
            implied_equilibrium_returns(bad, pd.Series([0.5, 0.5], index=["a", "b"]))

    def test_sigma_label_mismatch_raises(self) -> None:
        bad = pd.DataFrame(np.eye(2), index=["a", "b"], columns=["b", "a"])
        with pytest.raises(ValueError, match="identical asset labels"):
            implied_equilibrium_returns(bad, pd.Series([0.5, 0.5], index=["a", "b"]))

    def test_sigma_single_asset_raises(self) -> None:
        bad = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        with pytest.raises(ValueError, match="at least 2 assets"):
            implied_equilibrium_returns(bad, pd.Series([1.0], index=["a"]))

    def test_sigma_nan_raises(self) -> None:
        arr = np.eye(2)
        arr[0, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            implied_equilibrium_returns(_sigma_df(arr), _market_weights(2))

    def test_sigma_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="identically zero"):
            implied_equilibrium_returns(_sigma_df(np.zeros((2, 2))), _market_weights(2))

    def test_sigma_asymmetric_raises(self) -> None:
        arr = np.array([[1.0, 0.3], [0.0, 1.0]])
        with pytest.raises(ValueError, match="symmetric"):
            implied_equilibrium_returns(_sigma_df(arr), _market_weights(2))

    def test_market_weights_nan_raises(self) -> None:
        sigma = _sigma_df(np.eye(2))
        w = pd.Series([0.5, np.nan], index=_assets(2))
        with pytest.raises(ValueError, match="market_weights contains"):
            implied_equilibrium_returns(sigma, w)

    def test_singular_view_system_raises(self) -> None:
        # Two identical views whose Omega is the all-equal matrix make
        # (P tau Sigma P' + Omega) exactly rank 1.
        sigma, pi, _, _ = self._base()
        views = _views_df(np.array([[1.0, 0.0], [1.0, 0.0]]), 2)
        q = pd.Series([0.1, 0.1], index=["view0", "view1"])
        e = 1e-4
        omega = pd.DataFrame(
            [[e, e], [e, e]], index=["view0", "view1"], columns=["view0", "view1"]
        )
        with pytest.raises(ValueError, match="singular"):
            black_litterman(
                sigma, prior_means=pi, views=views, view_returns=q, omega=omega
            )


# ---------------------------------------------------------------------------
# Result DTO and Phase 6 DOD
# ---------------------------------------------------------------------------


class TestResultAndDOD:
    def test_frozen(self) -> None:
        sigma = _sigma_df(np.diag([0.04, 0.09]))
        pi = pd.Series([0.05, 0.07], index=_assets(2))
        result = black_litterman(sigma, prior_means=pi)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.tau = 0.1  # type: ignore[misc]

    def test_equality_ignores_frames(self) -> None:
        s1 = pd.Series([0.1, 0.2])
        s2 = pd.Series([0.3, 0.4])
        f1 = pd.DataFrame(np.eye(2))
        a = BlackLittermanResult(
            posterior_means=s1,
            posterior_covariance=f1,
            equilibrium_returns=s1,
            omega=None,
            tau=0.05,
        )
        b = BlackLittermanResult(
            posterior_means=s2,
            posterior_covariance=f1 * 2.0,
            equilibrium_returns=s2,
            omega=None,
            tau=0.05,
        )
        assert a == b

    def test_twenty_assets_under_one_second(self) -> None:
        rng = np.random.default_rng(6)
        sigma = _random_pd_sigma(rng, 20)
        w_mkt = _market_weights(20)
        views = _views_df(rng.standard_normal((5, 20)), 20)
        q = pd.Series(rng.standard_normal(5) * 0.01, index=views.index)
        start = time.perf_counter()
        result = black_litterman(
            sigma, market_weights=w_mkt, views=views, view_returns=q
        )
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"20-asset Black-Litterman took {elapsed:.3f}s"
        assert np.isfinite(result.posterior_means.to_numpy()).all()
