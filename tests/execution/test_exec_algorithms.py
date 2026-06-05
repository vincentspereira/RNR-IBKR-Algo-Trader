"""Tests for core_trading.execution.exec_algorithms (Phase 9.1).

Coverage targets
----------------
* validate_schedule -- pass, ndim, non-finite, negative, sum mismatch.
* ACParams -- validation errors on every field.
* ac_trajectory:
  - hand-derived exact pin (N=2, cosh(kappa*tau)=1.5 -> x1=X/3, E=1/9, V=200/9).
  - lambda->0 reduces to the exact linear TWAP trajectory.
  - holdings endpoints, monotone decreasing, trades non-negative, sum invariant.
  - eta_tilde <= 0 guard; total_shares / n_intervals validation.
* efficient_frontier -- E weakly increasing, V weakly decreasing in lambda.
* pov_schedule -- rate*volume, cumulative cap, cleanup vs truncation, errors.
* arrival_price_schedule -- AC variant, exponential-decay variant, front-loading,
  TWAP limit of decay, xor-arg and validation errors.
* adaptive_liquidity_schedule -- liquidity proportionality, completion guarantee,
  min_clip, max_participation ceiling, errors.
* iceberg_clip_sizes -- exact division, remainder, single-clip, errors.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from core_trading.execution.exec_algorithms import (
    ACParams,
    ACSchedule,
    ac_trajectory,
    adaptive_liquidity_schedule,
    arrival_price_schedule,
    efficient_frontier,
    iceberg_clip_sizes,
    pov_schedule,
    validate_schedule,
)

# ---------------------------------------------------------------------------
# validate_schedule
# ---------------------------------------------------------------------------


def test_validate_schedule_pass() -> None:
    validate_schedule(np.array([1.0, 2.0, 3.0]), 6.0)


def test_validate_schedule_rejects_2d() -> None:
    with pytest.raises(ValueError, match="1-D"):
        validate_schedule(np.ones((2, 2)), 4.0)


def test_validate_schedule_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        validate_schedule(np.array([1.0, np.inf]), 1.0)


def test_validate_schedule_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        validate_schedule(np.array([2.0, -1.0]), 1.0)


def test_validate_schedule_rejects_sum_mismatch() -> None:
    with pytest.raises(ValueError, match="sums to"):
        validate_schedule(np.array([1.0, 1.0]), 5.0)


def test_validate_schedule_tiny_negative_within_atol() -> None:
    # A clip just below zero by less than atol is tolerated.
    validate_schedule(np.array([2.0, -1e-9, 4.0 + 1e-9]), 6.0)


# ---------------------------------------------------------------------------
# ACParams validation
# ---------------------------------------------------------------------------


def test_acparams_valid() -> None:
    p = ACParams(horizon=1.0, sigma=0.3, eta=2e-6)
    assert p.gamma == 0.0
    assert p.lam == 0.0


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"horizon": 0.0, "sigma": 0.3, "eta": 1e-6}, "horizon"),
        ({"horizon": 1.0, "sigma": 0.0, "eta": 1e-6}, "sigma"),
        ({"horizon": 1.0, "sigma": 0.3, "eta": 0.0}, "eta"),
        ({"horizon": 1.0, "sigma": 0.3, "eta": 1e-6, "gamma": -1.0}, "gamma"),
        ({"horizon": 1.0, "sigma": 0.3, "eta": 1e-6, "lam": -1.0}, "lam"),
        ({"horizon": 1.0, "sigma": 0.3, "eta": 1e-6, "epsilon": -1.0}, "epsilon"),
    ],
)
def test_acparams_invalid(kwargs: dict[str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ACParams(**kwargs)


# ---------------------------------------------------------------------------
# ac_trajectory -- exact hand-derived pin
# ---------------------------------------------------------------------------


def test_ac_trajectory_exact_pin() -> None:
    """N=2 case with cosh(kappa*tau)=1.5 has an exact closed form.

    Parameters: X=100, T=1, N=2 (tau=0.5), sigma=0.2, eta=1e-5, gamma=0.
    kappa_tilde^2 = lam*sigma^2/eta = 1e-3*0.04/1e-5 = 4.0, so
    cosh(kappa*tau) = 1 + 0.5*4.0*0.25 = 1.5 exactly.
    Then x1 = X*sinh(kappa*tau)/sinh(2*kappa*tau) = X/(2*cosh(kappa*tau)) = X/3.
    Trades n = [200/3, 100/3].
    E = (eta/tau)*sum(n^2) = (1e-5/0.5)*(50000/9) = 1/9.
    V = sigma^2*tau*(x1^2 + 0) = 0.04*0.5*(100/3)^2 = 200/9.
    """
    params = ACParams(horizon=1.0, sigma=0.2, eta=1e-5, gamma=0.0, lam=1e-3)
    sched = ac_trajectory(100.0, 2, params=params)

    assert isinstance(sched, ACSchedule)
    # cosh(kappa*tau) == 1.5  ->  verify kappa.
    tau = 0.5
    assert math.isclose(math.cosh(sched.kappa * tau), 1.5, rel_tol=1e-12)
    # x1 = 100/3.
    assert math.isclose(sched.holdings[1], 100.0 / 3.0, rel_tol=1e-12)
    np.testing.assert_allclose(
        sched.trades, [200.0 / 3.0, 100.0 / 3.0], rtol=1e-12
    )
    assert math.isclose(sched.expected_cost, 1.0 / 9.0, rel_tol=1e-12)
    assert math.isclose(sched.cost_variance, 200.0 / 9.0, rel_tol=1e-12)


def test_ac_trajectory_lambda_zero_is_twap() -> None:
    """lambda = 0 gives the exact linear (TWAP) trajectory."""
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, lam=0.0)
    sched = ac_trajectory(1000.0, 5, params=params)
    assert sched.kappa == 0.0
    np.testing.assert_allclose(
        sched.holdings, [1000.0, 800.0, 600.0, 400.0, 200.0, 0.0], rtol=0.0,
        atol=1e-9,
    )
    np.testing.assert_allclose(sched.trades, [200.0] * 5, atol=1e-9)


def test_ac_trajectory_tiny_lambda_matches_twap_limit() -> None:
    """A numerically negligible lambda hits the linear branch, not sinh blow-up."""
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, lam=1e-18)
    sched = ac_trajectory(1000.0, 5, params=params)
    np.testing.assert_allclose(sched.trades, [200.0] * 5, atol=1e-6)
    # Sum invariant holds despite the tiny lambda.
    assert math.isclose(float(sched.trades.sum()), 1000.0, abs_tol=1e-6)


def test_ac_trajectory_known_full_case() -> None:
    """Pin the documented worked example (N=5) to guard regressions."""
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, gamma=0.0, lam=2e-6)
    sched = ac_trajectory(1000.0, 5, params=params)
    assert math.isclose(sched.kappa, 0.29995501821524456, rel_tol=1e-9)
    assert math.isclose(sched.expected_cost, 2.0003360703661994, rel_tol=1e-9)
    assert math.isclose(sched.cost_variance, 21262.418261136023, rel_tol=1e-9)


def test_ac_trajectory_structure() -> None:
    params = ACParams(horizon=2.0, sigma=0.25, eta=5e-6, gamma=1e-7, lam=1e-5)
    sched = ac_trajectory(5000.0, 10, params=params)
    # Endpoints exact.
    assert sched.holdings[0] == 5000.0
    assert sched.holdings[-1] == 0.0
    # Holdings strictly decreasing.
    assert np.all(np.diff(sched.holdings) < 0)
    # Trades non-negative and front-loaded (first > last, since lam > 0).
    assert np.all(sched.trades >= 0)
    assert sched.trades[0] > sched.trades[-1]
    # Sum invariant.
    assert math.isclose(float(sched.trades.sum()), 5000.0, abs_tol=1e-6)
    assert len(sched.trades) == 10
    assert len(sched.holdings) == 11


def test_ac_trajectory_eta_tilde_guard() -> None:
    # Large gamma drives eta_tilde = eta - 0.5*gamma*tau negative.
    params = ACParams(horizon=1.0, sigma=0.3, eta=1e-6, gamma=1.0, lam=1e-6)
    with pytest.raises(ValueError, match="eta_tilde"):
        ac_trajectory(1000.0, 2, params=params)


def test_ac_trajectory_bad_total() -> None:
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6)
    with pytest.raises(ValueError, match="total_shares"):
        ac_trajectory(0.0, 5, params=params)


def test_ac_trajectory_bad_intervals() -> None:
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6)
    with pytest.raises(ValueError, match="n_intervals"):
        ac_trajectory(100.0, 0, params=params)


# ---------------------------------------------------------------------------
# efficient_frontier
# ---------------------------------------------------------------------------


def test_efficient_frontier_monotonicity() -> None:
    base = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, gamma=0.0, lam=0.0)
    lambdas = [1e-9, 1e-7, 1e-6, 1e-5, 1e-4]
    points = efficient_frontier(lambdas, 1000.0, 5, base_params=base)
    # lambdas preserved in input order.
    assert [p[0] for p in points] == lambdas
    costs = [p[1] for p in points]
    variances = [p[2] for p in points]
    # E weakly increasing, V weakly decreasing in lambda.
    assert all(costs[i] <= costs[i + 1] + 1e-12 for i in range(len(costs) - 1))
    assert all(
        variances[i] >= variances[i + 1] - 1e-6 for i in range(len(variances) - 1)
    )
    # Strict at the high-lambda end (front-loading really does shed variance).
    assert costs[-1] > costs[0]
    assert variances[-1] < variances[0]


def test_efficient_frontier_accepts_ndarray() -> None:
    base = ACParams(horizon=1.0, sigma=0.3, eta=2e-6)
    points = efficient_frontier(np.array([0.0, 1e-5]), 500.0, 4, base_params=base)
    assert len(points) == 2
    assert points[0][0] == 0.0


# ---------------------------------------------------------------------------
# pov_schedule
# ---------------------------------------------------------------------------


def test_pov_schedule_basic_proportionality() -> None:
    vols = [1000.0, 2000.0, 1000.0, 2000.0]
    # 10% of 6000 total volume = 600 placed naturally; total exactly 600.
    clip = pov_schedule(600.0, vols, 0.1)
    np.testing.assert_allclose(clip, [100.0, 200.0, 100.0, 200.0])
    assert math.isclose(float(clip.sum()), 600.0)


def test_pov_schedule_cumulative_cap_and_cleanup() -> None:
    vols = [1000.0, 1000.0, 1000.0, 1000.0]
    # 50% participation wants 500/interval = 2000 total but only 600 needed.
    clip = pov_schedule(600.0, vols, 0.5, cleanup=True)
    # First interval places 500, second is capped to 100, rest zero.
    np.testing.assert_allclose(clip, [500.0, 100.0, 0.0, 0.0])
    assert math.isclose(float(clip.sum()), 600.0)


def test_pov_schedule_cleanup_adds_remainder_to_last() -> None:
    vols = [100.0, 100.0]
    # 10% wants 10+10=20 but total is 100 -> remainder 80 to last interval.
    clip = pov_schedule(100.0, vols, 0.1, cleanup=True)
    np.testing.assert_allclose(clip, [10.0, 90.0])


def test_pov_schedule_truncation_underfills() -> None:
    vols = [100.0, 100.0]
    clip = pov_schedule(100.0, vols, 0.1, cleanup=False)
    np.testing.assert_allclose(clip, [10.0, 10.0])
    assert math.isclose(float(clip.sum()), 20.0)


@pytest.mark.parametrize(
    "total, vols, rate, match",
    [
        (0.0, [1.0], 0.1, "total_shares"),
        (100.0, [1.0], 0.0, "participation_rate"),
        (100.0, [1.0], 1.5, "participation_rate"),
        (100.0, [], 0.1, "non-empty"),
        (100.0, [[1.0, 2.0]], 0.1, "non-empty"),
        (100.0, [-1.0], 0.1, "non-negative"),
    ],
)
def test_pov_schedule_errors(
    total: float, vols: object, rate: float, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        pov_schedule(total, vols, rate)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# arrival_price_schedule
# ---------------------------------------------------------------------------


def test_arrival_price_ac_variant() -> None:
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, lam=5e-5)
    clip = arrival_price_schedule(1000.0, 5, params=params)
    expected = ac_trajectory(1000.0, 5, params=params).trades
    np.testing.assert_allclose(clip, expected)
    # Front-loaded: first clip largest.
    assert clip[0] == clip.max()


def test_arrival_price_decay_variant_front_loaded() -> None:
    clip = arrival_price_schedule(1000.0, 5, front_load_factor=0.5)
    assert math.isclose(float(clip.sum()), 1000.0, abs_tol=1e-6)
    # Strictly decreasing geometric profile.
    assert np.all(np.diff(clip) < 0)
    # Exact geometric ratio between consecutive clips: exp(-0.5).
    ratio = clip[1] / clip[0]
    assert math.isclose(ratio, math.exp(-0.5), rel_tol=1e-12)


def test_arrival_price_decay_small_factor_near_twap() -> None:
    clip = arrival_price_schedule(1000.0, 4, front_load_factor=1e-9)
    np.testing.assert_allclose(clip, [250.0] * 4, atol=1e-3)


def test_arrival_price_requires_exactly_one_arg() -> None:
    params = ACParams(horizon=1.0, sigma=0.3, eta=2e-6, lam=1e-5)
    with pytest.raises(ValueError, match="exactly one"):
        arrival_price_schedule(100.0, 5)
    with pytest.raises(ValueError, match="exactly one"):
        arrival_price_schedule(100.0, 5, params=params, front_load_factor=0.5)


def test_arrival_price_validation() -> None:
    with pytest.raises(ValueError, match="total_shares"):
        arrival_price_schedule(0.0, 5, front_load_factor=0.5)
    with pytest.raises(ValueError, match="n_intervals"):
        arrival_price_schedule(100.0, 0, front_load_factor=0.5)
    with pytest.raises(ValueError, match="front_load_factor"):
        arrival_price_schedule(100.0, 5, front_load_factor=-1.0)


# ---------------------------------------------------------------------------
# adaptive_liquidity_schedule
# ---------------------------------------------------------------------------


def test_adaptive_liquidity_completes_and_sums() -> None:
    vols = [1000.0, 500.0, 2000.0, 100.0, 800.0]
    clip = adaptive_liquidity_schedule(
        1000.0, vols, min_clip=10.0, max_participation=0.3, urgency=1.0
    )
    assert math.isclose(float(clip.sum()), 1000.0, abs_tol=1e-6)
    assert len(clip) == 5
    assert np.all(clip >= 0)


def test_adaptive_liquidity_seeks_high_volume() -> None:
    # Plenty of capacity; trade more where volume is higher.
    vols = [1000.0, 4000.0]
    clip = adaptive_liquidity_schedule(
        1000.0, vols, min_clip=0.0, max_participation=0.5, urgency=1.0
    )
    # Interval 0 capacity 500, catch-up 500 -> takes 500. Interval 1 takes 500.
    assert math.isclose(float(clip.sum()), 1000.0, abs_tol=1e-6)
    assert clip[0] <= 500.0 + 1e-9


def test_adaptive_liquidity_catch_up_binds_at_end() -> None:
    # Quiet final interval still completes via catch-up term.
    vols = [10000.0, 1.0]
    clip = adaptive_liquidity_schedule(
        1000.0, vols, min_clip=0.0, max_participation=0.01, urgency=1.0
    )
    # Interval 0: cap=100, catch-up=500 -> 500. Interval 1 must clear 500.
    assert math.isclose(float(clip.sum()), 1000.0, abs_tol=1e-6)
    assert clip[1] > 0.0


def test_adaptive_liquidity_respects_min_clip() -> None:
    vols = [1.0, 1.0, 1.0, 100000.0]
    clip = adaptive_liquidity_schedule(
        1000.0, vols, min_clip=50.0, max_participation=0.001, urgency=0.001
    )
    # Early intervals have near-zero capacity but min_clip lifts them to 50.
    assert clip[0] >= 50.0 - 1e-9
    assert math.isclose(float(clip.sum()), 1000.0, abs_tol=1e-6)


def test_adaptive_liquidity_early_finish_breaks_loop() -> None:
    # Huge first-interval capacity finishes the order; later intervals stay 0.
    vols = [1_000_000.0, 1_000_000.0]
    clip = adaptive_liquidity_schedule(
        100.0, vols, min_clip=0.0, max_participation=1.0, urgency=1.0
    )
    assert math.isclose(float(clip.sum()), 100.0, abs_tol=1e-6)
    assert clip[1] == 0.0


def test_adaptive_liquidity_final_remainder_below_min_clip() -> None:
    """When the leftover is smaller than min_clip, trade just the remainder."""
    # i0: cap=0.001, catch_up=27.5 -> qty 27.5 < min_clip 50 -> min(50, 55)=50.
    # i1: remaining=5 < min_clip 50 -> min(50, 5)=5 (not lifted to 50).
    clip = adaptive_liquidity_schedule(
        55.0, [1.0, 1.0], min_clip=50.0, max_participation=0.001, urgency=0.001
    )
    np.testing.assert_allclose(clip, [50.0, 5.0])
    assert math.isclose(float(clip.sum()), 55.0, abs_tol=1e-6)


def test_adaptive_liquidity_zero_volume_interval() -> None:
    # A zero-volume interval relies purely on the catch-up term.
    vols = [0.0, 0.0]
    clip = adaptive_liquidity_schedule(
        100.0, vols, min_clip=0.0, max_participation=0.5, urgency=1.0
    )
    assert math.isclose(float(clip.sum()), 100.0, abs_tol=1e-6)


@pytest.mark.parametrize(
    "total, vols, kwargs, match",
    [
        (0.0, [1.0], {"min_clip": 0.0, "max_participation": 0.5}, "total_shares"),
        (100.0, [1.0], {"min_clip": -1.0, "max_participation": 0.5}, "min_clip"),
        (100.0, [1.0], {"min_clip": 0.0, "max_participation": 0.0}, "max_participation"),
        (100.0, [1.0], {"min_clip": 0.0, "max_participation": 1.5}, "max_participation"),
        (100.0, [1.0], {"min_clip": 0.0, "max_participation": 0.5, "urgency": 0.0}, "urgency"),
        (100.0, [], {"min_clip": 0.0, "max_participation": 0.5}, "non-empty"),
        (100.0, [-1.0], {"min_clip": 0.0, "max_participation": 0.5}, "non-negative"),
    ],
)
def test_adaptive_liquidity_errors(
    total: float, vols: object, kwargs: dict[str, float], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        adaptive_liquidity_schedule(total, vols, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# iceberg_clip_sizes
# ---------------------------------------------------------------------------


def test_iceberg_exact_division() -> None:
    clips = iceberg_clip_sizes(1000.0, 250.0)
    assert clips == [250.0, 250.0, 250.0, 250.0]


def test_iceberg_with_remainder() -> None:
    clips = iceberg_clip_sizes(1000.0, 300.0)
    assert clips == [300.0, 300.0, 300.0, 100.0]
    assert math.isclose(sum(clips), 1000.0)


def test_iceberg_single_clip_when_display_exceeds_total() -> None:
    assert iceberg_clip_sizes(100.0, 500.0) == [100.0]
    assert iceberg_clip_sizes(100.0, 100.0) == [100.0]


@pytest.mark.parametrize(
    "total, display, match",
    [
        (0.0, 100.0, "total"),
        (1000.0, 0.0, "display_size"),
    ],
)
def test_iceberg_errors(total: float, display: float, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        iceberg_clip_sizes(total, display)
