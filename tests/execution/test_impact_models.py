"""Tests for core_trading.execution.impact_models (master plan Phase 9.3).

Coverage targets
----------------
* Dataclass validation (ACParams, OWParams, IStarParams, CalibrationResult).
* Almgren-Chriss square-root model -- hand-computed temporary / permanent /
  slice / schedule costs, beta != 0.5 case, half-permanent toggle, empty
  schedule, negative-input guards.
* Obizhaeva-Wang transient impact -- single trade, two-trade decay,
  full-resilience / no-resilience limits, scalar vs sequence dt, dt length
  variants, volume-weighted schedule cost, empty / zero-volume schedules.
* Kissell-Glantz I-Star -- hand-computed I*, temporary/permanent split,
  b1 endpoints, zero-order / zero-sigma short circuits, negative guards.
* calibrate_impact -- missing columns, empty frame, insufficient observations,
  degenerate regressor, synthetic-data parameter recovery (true vs recovered),
  determinism, side-sign handling, well_determined=False on negative slope.
* expected_cost_bps round-trip.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.execution.impact_models import (
    ACParams,
    CalibrationResult,
    IStarParams,
    OWParams,
    ac_permanent_impact,
    ac_schedule_cost,
    ac_slice_cost,
    ac_temporary_impact,
    calibrate_impact,
    expected_cost_bps,
    istar_impact,
    kissell_glantz_cost,
    ow_impact_path,
    ow_schedule_cost,
)

_TOL = 1e-12


# ---------------------------------------------------------------------------
# Dataclass validation
# ---------------------------------------------------------------------------


def test_acparams_defaults_valid() -> None:
    params = ACParams()
    assert params.beta == 0.5
    assert params.eta >= 0.0


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"eta": -1.0}, "eta"),
        ({"gamma": -0.1}, "gamma"),
        ({"beta": 0.0}, "beta"),
        ({"sigma": -0.01}, "sigma"),
    ],
)
def test_acparams_validation(kwargs: dict[str, float], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        ACParams(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"kappa": -1.0}, "kappa"),
        ({"rho": 0.0}, "rho"),
    ],
)
def test_owparams_validation(kwargs: dict[str, float], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        OWParams(**kwargs)


def test_owparams_defaults_valid() -> None:
    params = OWParams()
    assert params.rho > 0.0


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"a1": -1.0}, "a1"),
        ({"a2": 0.0}, "a2"),
        ({"a3": -0.5}, "a3"),
        ({"a4": 0.0}, "a4"),
        ({"b1": 1.5}, "b1"),
        ({"b1": -0.1}, "b1"),
    ],
)
def test_istarparams_validation(kwargs: dict[str, float], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        IStarParams(**kwargs)


def test_istarparams_defaults_valid() -> None:
    params = IStarParams()
    assert 0.0 <= params.b1 <= 1.0


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"eta": -1.0, "beta": 0.5, "r_squared": 0.5, "n_obs": 10}, "eta"),
        ({"eta": 0.1, "beta": 0.0, "r_squared": 0.5, "n_obs": 10}, "beta"),
        ({"eta": 0.1, "beta": 0.5, "r_squared": 1.5, "n_obs": 10}, "r_squared"),
        ({"eta": 0.1, "beta": 0.5, "r_squared": 0.5, "n_obs": -1}, "n_obs"),
    ],
)
def test_calibrationresult_validation(
    kwargs: dict[str, float], needle: str
) -> None:
    with pytest.raises(ValueError, match=needle):
        CalibrationResult(well_determined=True, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Almgren-Chriss
# ---------------------------------------------------------------------------


def test_ac_temporary_square_root_known_value() -> None:
    params = ACParams(eta=0.2, gamma=0.0, beta=0.5, sigma=0.03)
    # h = eta * sigma * sqrt(0.25) = 0.2 * 0.03 * 0.5 = 0.003
    assert ac_temporary_impact(0.25, params) == pytest.approx(0.003, abs=_TOL)


def test_ac_temporary_custom_beta() -> None:
    params = ACParams(eta=0.5, gamma=0.0, beta=1.0, sigma=0.04)
    # beta=1 -> linear: 0.5 * 0.04 * 0.1 = 0.002
    assert ac_temporary_impact(0.1, params) == pytest.approx(0.002, abs=_TOL)


def test_ac_temporary_zero_participation() -> None:
    assert ac_temporary_impact(0.0, ACParams()) == 0.0


def test_ac_temporary_negative_raises() -> None:
    with pytest.raises(ValueError, match="participation"):
        ac_temporary_impact(-0.1, ACParams())


def test_ac_permanent_known_value() -> None:
    params = ACParams(eta=0.0, gamma=0.4, beta=0.5, sigma=0.05)
    # g = gamma * sigma * (Q/V) = 0.4 * 0.05 * 0.2 = 0.004
    assert ac_permanent_impact(0.2, params) == pytest.approx(0.004, abs=_TOL)


def test_ac_permanent_negative_raises() -> None:
    with pytest.raises(ValueError, match="order_fraction"):
        ac_permanent_impact(-0.1, ACParams())


def test_ac_slice_cost_sum() -> None:
    params = ACParams(eta=0.2, gamma=0.4, beta=0.5, sigma=0.03)
    temp = ac_temporary_impact(0.25, params)
    perm = ac_permanent_impact(0.1, params)
    assert ac_slice_cost(0.25, 0.1, params) == pytest.approx(
        temp + perm, abs=_TOL
    )


def test_ac_schedule_empty() -> None:
    assert ac_schedule_cost([], ACParams()) == 0.0


def test_ac_schedule_negative_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ac_schedule_cost([0.1, -0.2], ACParams())


def test_ac_schedule_known_value_half_permanent() -> None:
    params = ACParams(eta=0.1, gamma=0.2, beta=0.5, sigma=0.02)
    parts = [0.1, 0.1]  # equal slices, total fraction 0.2
    # temp per slice = 0.1 * 0.02 * sqrt(0.1) = 0.002 * 0.316227766 = 6.32455e-4
    temp_slice = 0.1 * 0.02 * math.sqrt(0.1)
    # weights 0.5 / 0.5 -> weighted temp = temp_slice
    temp_cost = temp_slice
    # permanent on total 0.2: 0.2 * 0.02 * 0.2 = 8e-4, halved -> 4e-4
    perm_cost = 0.5 * (0.2 * 0.02 * 0.2)
    assert ac_schedule_cost(parts, params) == pytest.approx(
        temp_cost + perm_cost, abs=_TOL
    )


def test_ac_schedule_full_permanent_toggle() -> None:
    params = ACParams(eta=0.1, gamma=0.2, beta=0.5, sigma=0.02)
    parts = [0.1, 0.1]
    half = ac_schedule_cost(parts, params, permanent_on_half=True)
    full = ac_schedule_cost(parts, params, permanent_on_half=False)
    perm_full = ac_permanent_impact(0.2, params)
    assert full - half == pytest.approx(0.5 * perm_full, abs=_TOL)


def test_ac_schedule_zero_total_fraction() -> None:
    # All-zero participations: total fraction 0, no temp, no perm.
    assert ac_schedule_cost([0.0, 0.0], ACParams()) == 0.0


# ---------------------------------------------------------------------------
# Obizhaeva-Wang
# ---------------------------------------------------------------------------


def test_ow_single_trade_path() -> None:
    params = OWParams(kappa=0.5, rho=1.0)
    path = ow_impact_path([0.2], 0.0, params)
    assert path.shape == (1,)
    assert path[0] == pytest.approx(0.5 * 0.2, abs=_TOL)


def test_ow_empty_path() -> None:
    path = ow_impact_path([], 1.0, OWParams())
    assert path.shape == (0,)


def test_ow_two_trade_decay_known_value() -> None:
    params = OWParams(kappa=1.0, rho=2.0)
    # D0 = 1.0 * 0.1 = 0.1
    # D1 = D0 * exp(-2 * 0.5) + 1.0 * 0.1 = 0.1 * exp(-1) + 0.1
    path = ow_impact_path([0.1, 0.1], 0.5, params)
    expected_d1 = 0.1 * math.exp(-1.0) + 0.1
    assert path[0] == pytest.approx(0.1, abs=_TOL)
    assert path[1] == pytest.approx(expected_d1, abs=_TOL)


def test_ow_no_resilience_high_rho_decays_fully() -> None:
    # Very large rho with a positive gap -> prior displacement nearly gone.
    params = OWParams(kappa=1.0, rho=1000.0)
    path = ow_impact_path([0.1, 0.1], 1.0, params)
    assert path[1] == pytest.approx(0.1, abs=1e-9)


def test_ow_zero_gap_accumulates() -> None:
    # dt = 0 -> no decay, displacement accumulates fully.
    params = OWParams(kappa=1.0, rho=5.0)
    path = ow_impact_path([0.1, 0.1, 0.1], 0.0, params)
    assert path[2] == pytest.approx(0.3, abs=_TOL)


def test_ow_dt_sequence_length_n() -> None:
    params = OWParams(kappa=1.0, rho=1.0)
    # Length-n dt: only first n-1 gaps used.
    path_seq = ow_impact_path([0.1, 0.1], [0.5, 99.0], params)
    path_scalar = ow_impact_path([0.1, 0.1], 0.5, params)
    assert np.allclose(path_seq, path_scalar, atol=_TOL)


def test_ow_dt_sequence_length_nm1() -> None:
    params = OWParams(kappa=1.0, rho=1.0)
    path = ow_impact_path([0.1, 0.1, 0.1], [0.5, 0.5], params)
    assert path.shape == (3,)


def test_ow_dt_bad_length_raises() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        ow_impact_path([0.1, 0.1, 0.1], [0.5], OWParams())


def test_ow_negative_participation_raises() -> None:
    with pytest.raises(ValueError, match="participations"):
        ow_impact_path([0.1, -0.1], 0.5, OWParams())


def test_ow_negative_gap_raises() -> None:
    with pytest.raises(ValueError, match="gaps"):
        ow_impact_path([0.1, 0.1], [-0.5], OWParams())


def test_ow_schedule_cost_weighted_average() -> None:
    params = OWParams(kappa=1.0, rho=2.0)
    parts = [0.1, 0.1]
    path = ow_impact_path(parts, 0.5, params)
    expected = (0.1 * path[0] + 0.1 * path[1]) / 0.2
    assert ow_schedule_cost(parts, 0.5, params) == pytest.approx(
        expected, abs=_TOL
    )


def test_ow_schedule_cost_zero_volume() -> None:
    assert ow_schedule_cost([0.0, 0.0], 0.5, OWParams()) == 0.0


def test_ow_schedule_cost_empty() -> None:
    assert ow_schedule_cost([], 0.5, OWParams()) == 0.0


def test_ow_scalar_dt_numpy_zero_dim() -> None:
    params = OWParams(kappa=1.0, rho=1.0)
    path = ow_impact_path([0.1, 0.1], np.array(0.0), params)
    assert path[1] == pytest.approx(0.2, abs=_TOL)


# ---------------------------------------------------------------------------
# Kissell-Glantz I-Star
# ---------------------------------------------------------------------------


def test_istar_known_value() -> None:
    params = IStarParams(a1=1000.0, a2=0.5, a3=1.0, a4=0.5, b1=0.9)
    # I* = 1000 * sqrt(0.04) * 0.02 = 1000 * 0.2 * 0.02 = 4.0 (bps)
    assert istar_impact(0.04, 0.02, params) == pytest.approx(4.0, abs=1e-9)


def test_istar_zero_order_fraction() -> None:
    assert istar_impact(0.0, 0.02, IStarParams()) == 0.0


def test_istar_zero_sigma() -> None:
    assert istar_impact(0.04, 0.0, IStarParams()) == 0.0


def test_istar_negative_order_raises() -> None:
    with pytest.raises(ValueError, match="order_fraction"):
        istar_impact(-0.1, 0.02, IStarParams())


def test_istar_negative_sigma_raises() -> None:
    with pytest.raises(ValueError, match="sigma"):
        istar_impact(0.04, -0.02, IStarParams())


def test_kissell_glantz_cost_known_value() -> None:
    params = IStarParams(a1=1000.0, a2=0.5, a3=1.0, a4=0.5, b1=0.9)
    # I* = 4.0 bps. POV=0.25, a4=0.5 -> POV^0.5 = 0.5
    # MI = 0.9 * 4 * 0.5 + 0.1 * 4 = 1.8 + 0.4 = 2.2 bps = 2.2e-4 fraction
    cost = kissell_glantz_cost(0.04, 0.02, 0.25, params)
    assert cost == pytest.approx(2.2e-4, abs=1e-12)


def test_kissell_glantz_b1_zero_is_pure_permanent() -> None:
    params = IStarParams(a1=1000.0, a2=0.5, a3=1.0, a4=0.5, b1=0.0)
    # Pure permanent: MI = I* = 4 bps regardless of POV.
    cost = kissell_glantz_cost(0.04, 0.02, 0.9, params)
    assert cost == pytest.approx(4.0e-4, abs=1e-12)


def test_kissell_glantz_b1_one_is_pure_temporary() -> None:
    params = IStarParams(a1=1000.0, a2=0.5, a3=1.0, a4=0.5, b1=1.0)
    # Pure temporary: MI = I* * POV^0.5 = 4 * sqrt(0.25) = 2 bps.
    cost = kissell_glantz_cost(0.04, 0.02, 0.25, params)
    assert cost == pytest.approx(2.0e-4, abs=1e-12)


def test_kissell_glantz_negative_pov_raises() -> None:
    with pytest.raises(ValueError, match="pov"):
        kissell_glantz_cost(0.04, 0.02, -0.1, IStarParams())


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def _make_fills(
    participation: np.ndarray,
    sigma: np.ndarray,
    slippage: np.ndarray,
    *,
    side: str = "buy",
) -> pd.DataFrame:
    """Build a fills DataFrame from a target slippage fraction (all buys)."""
    arrival = np.full(participation.shape[0], 100.0)
    # buy: slippage = (avg_fill - arrival) / arrival -> avg_fill = arrival*(1+s)
    avg_fill = arrival * (1.0 + slippage)
    return pd.DataFrame(
        {
            "symbol": ["AAA"] * participation.shape[0],
            "side": [side] * participation.shape[0],
            "quantity": np.full(participation.shape[0], 1000.0),
            "adv": np.full(participation.shape[0], 1_000_000.0),
            "sigma": sigma,
            "participation": participation,
            "arrival_price": arrival,
            "avg_fill_price": avg_fill,
        }
    )


def test_calibrate_missing_columns_raises() -> None:
    df = pd.DataFrame({"symbol": ["AAA"]})
    with pytest.raises(ValueError, match="missing required columns"):
        calibrate_impact(df)


def test_calibrate_empty_frame() -> None:
    cols = [
        "symbol",
        "side",
        "quantity",
        "adv",
        "sigma",
        "participation",
        "arrival_price",
        "avg_fill_price",
    ]
    df = pd.DataFrame({c: [] for c in cols})
    result = calibrate_impact(df)
    assert result.n_obs == 0
    assert result.well_determined is False
    assert result.eta == pytest.approx(0.1)
    assert result.beta == pytest.approx(0.5)


def test_calibrate_insufficient_obs() -> None:
    part = np.array([0.01, 0.05])
    sigma = np.array([0.02, 0.02])
    slip = np.array([0.001, 0.002])
    df = _make_fills(part, sigma, slip)
    result = calibrate_impact(df, min_obs=5)
    assert result.well_determined is False
    assert result.n_obs == 2


def test_calibrate_degenerate_regressor() -> None:
    # All participations identical -> no variation -> not well determined.
    part = np.full(10, 0.05)
    sigma = np.full(10, 0.02)
    slip = np.full(10, 0.0015)
    df = _make_fills(part, sigma, slip)
    result = calibrate_impact(df)
    assert result.well_determined is False
    assert result.n_obs == 10


def test_calibrate_parameter_recovery() -> None:
    # Generate fills from a KNOWN square-root law with seeded multiplicative
    # log-noise, then assert the calibration recovers (eta, beta).
    rng = np.random.default_rng(20260605)
    n = 4000
    true_eta = 0.18
    true_beta = 0.55
    participation = rng.uniform(0.005, 0.25, size=n)
    sigma = rng.uniform(0.01, 0.05, size=n)
    # slippage = eta * sigma * participation^beta * exp(noise)
    noise = rng.normal(0.0, 0.05, size=n)
    slippage = (
        true_eta
        * sigma
        * np.power(participation, true_beta)
        * np.exp(noise)
    )
    df = _make_fills(participation, sigma, slippage)
    result = calibrate_impact(df)

    assert result.well_determined is True
    assert result.n_obs == n
    assert result.eta == pytest.approx(true_eta, rel=0.05)
    assert result.beta == pytest.approx(true_beta, abs=0.02)
    assert result.r_squared > 0.95


def test_calibrate_deterministic() -> None:
    rng = np.random.default_rng(7)
    n = 200
    part = rng.uniform(0.01, 0.2, size=n)
    sigma = np.full(n, 0.02)
    slip = 0.1 * sigma * np.sqrt(part) * np.exp(rng.normal(0, 0.03, n))
    df = _make_fills(part, sigma, slip)
    r1 = calibrate_impact(df)
    r2 = calibrate_impact(df)
    assert r1 == r2


def test_calibrate_sell_side_sign() -> None:
    # For sells, an adverse fill is BELOW arrival; side sign flips it positive.
    rng = np.random.default_rng(99)
    n = 500
    part = rng.uniform(0.01, 0.2, size=n)
    sigma = np.full(n, 0.02)
    slip = 0.12 * sigma * np.power(part, 0.5) * np.exp(rng.normal(0, 0.04, n))
    arrival = np.full(n, 100.0)
    # sell adverse: avg_fill below arrival by the slippage fraction
    avg_fill = arrival * (1.0 - slip)
    df = pd.DataFrame(
        {
            "symbol": ["AAA"] * n,
            "side": ["sell"] * n,
            "quantity": np.full(n, 1000.0),
            "adv": np.full(n, 1_000_000.0),
            "sigma": sigma,
            "participation": part,
            "arrival_price": arrival,
            "avg_fill_price": avg_fill,
        }
    )
    result = calibrate_impact(df)
    assert result.well_determined is True
    assert result.eta == pytest.approx(0.12, rel=0.1)


def test_calibrate_numeric_side() -> None:
    # Numeric side column (+1 buy, -1 sell) is accepted.
    rng = np.random.default_rng(11)
    n = 400
    part = rng.uniform(0.01, 0.2, size=n)
    sigma = np.full(n, 0.02)
    slip = 0.1 * sigma * np.sqrt(part)
    arrival = np.full(n, 100.0)
    avg_fill = arrival * (1.0 + slip)
    df = pd.DataFrame(
        {
            "symbol": ["AAA"] * n,
            "side": np.ones(n),  # numeric +1 = buy
            "quantity": np.full(n, 1000.0),
            "adv": np.full(n, 1_000_000.0),
            "sigma": sigma,
            "participation": part,
            "arrival_price": arrival,
            "avg_fill_price": avg_fill,
        }
    )
    result = calibrate_impact(df)
    assert result.well_determined is True


def test_calibrate_negative_slope_not_well_determined() -> None:
    # Construct fills where slippage DECREASES with participation -> negative
    # slope -> not a valid square-root law -> well_determined False.
    part = np.linspace(0.01, 0.2, 30)
    sigma = np.full(30, 0.02)
    slip = 0.002 - 0.005 * part  # decreasing, stays positive over range
    df = _make_fills(part, sigma, slip)
    result = calibrate_impact(df)
    assert result.well_determined is False


def test_calibrate_zero_arrival_price_excluded() -> None:
    # A row with arrival_price = 0 must be dropped, not crash.
    rng = np.random.default_rng(5)
    n = 50
    part = rng.uniform(0.01, 0.2, size=n)
    sigma = np.full(n, 0.02)
    slip = 0.1 * sigma * np.sqrt(part)
    df = _make_fills(part, sigma, slip)
    df.loc[0, "arrival_price"] = 0.0
    result = calibrate_impact(df)
    # One row dropped.
    assert result.n_obs == n - 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_calibrate_unparseable_side_defaults_to_buy() -> None:
    # A non-string, non-numeric side (e.g. None) must fall back to buy (+1)
    # without raising; the row's slippage is treated as a buy.
    rng = np.random.default_rng(13)
    n = 40
    part = rng.uniform(0.01, 0.2, size=n)
    sigma = np.full(n, 0.02)
    slip = 0.1 * sigma * np.sqrt(part)
    arrival = np.full(n, 100.0)
    avg_fill = arrival * (1.0 + slip)
    side: list[object] = ["buy"] * n
    side[0] = None  # unparseable -> default buy
    df = pd.DataFrame(
        {
            "symbol": ["AAA"] * n,
            "side": pd.Series(side, dtype=object),
            "quantity": np.full(n, 1000.0),
            "adv": np.full(n, 1_000_000.0),
            "sigma": sigma,
            "participation": part,
            "arrival_price": arrival,
            "avg_fill_price": avg_fill,
        }
    )
    result = calibrate_impact(df)
    assert result.n_obs == n
    assert result.well_determined is True


def test_expected_cost_bps_roundtrip() -> None:
    assert expected_cost_bps(0.0022) == pytest.approx(22.0, abs=_TOL)
    assert expected_cost_bps(0.0) == 0.0
