"""Property-based invariant tests for the quant core (master plan Phase 10.1).

Each test asserts a *mathematical invariant* that must hold for every valid
input, rather than a single hand-picked example.  Hypothesis generates the
inputs; the invariants are the specification.

Scope of the invariants checked here
------------------------------------
* ``core_trading.money.sizing.scale_to_budget`` -- output gross never exceeds
  the budget; signs and relative ratios of the input book are preserved.
* ``core_trading.money.leverage.apply_leverage_limits`` -- post-scaling gross
  and net exposures respect the configured caps (within float tolerance) and
  every per-asset-class gross cap is honoured.
* ``core_trading.money.turnover.realised_turnover`` -- per-period turnover is
  always non-negative and is invariant to padding the weight panel with
  all-NaN (never-held) asset columns.
* ``core_trading.money.drawdown_management.compute_drawdown`` -- drawdown of a
  strictly-positive equity curve lies in ``[0, 1)`` and is exactly 0 at every
  running high-water mark.
* ``core_trading.execution.exec_algorithms`` -- every schedule generator
  (Almgren-Chriss trades, POV, arrival-price, adaptive-liquidity) returns
  non-negative clips that sum to the requested total within tolerance.
* ``core_trading.execution.adverse_selection`` -- VPIN values lie in ``[0, 1]``
  and Bulk Volume Classification preserves total volume exactly
  (``buy + sell == volume``).
* ``core_trading.risk.var`` -- parametric and historical VaR are non-negative
  under the positive-loss convention for arbitrary finite return samples.

Determinism / CI policy
-----------------------
A single Hypothesis profile (``phase101``) is registered and loaded at import
time: ``max_examples=50``, ``deadline=None`` (so a slow first JIT/import does
not flake), ``derandomize=True`` (the example stream is a deterministic
function of the test, identical run to run).  No global conftest is touched.
Health checks are suppressed only where a generated example is deliberately
filtered (documented inline).  Strategies are constrained to finite, sane
ranges; NaN/inf are introduced only where a NaN-handling invariant is the point.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from core_trading.execution.adverse_selection import (
    AdverseSelectionConfig,
    bulk_volume_classify,
    vpin,
)
from core_trading.execution.exec_algorithms import (
    ACParams,
    ac_trajectory,
    adaptive_liquidity_schedule,
    arrival_price_schedule,
    pov_schedule,
)
from core_trading.money.drawdown_management import compute_drawdown
from core_trading.money.leverage import (
    LeverageConfig,
    apply_leverage_limits,
)
from core_trading.money.sizing import scale_to_budget
from core_trading.money.turnover import realised_turnover
from core_trading.risk.var import historical_var, parametric_var

# ---------------------------------------------------------------------------
# Hypothesis profile -- deterministic and CI-friendly (no global conftest edits)
# ---------------------------------------------------------------------------

settings.register_profile(
    "phase101",
    max_examples=50,
    deadline=None,
    derandomize=True,
)
settings.load_profile("phase101")


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Finite floats in a sane trading range (no NaN/inf).
_FINITE = st.floats(
    min_value=-1e6,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)

# A signed weight book: identifier -> finite weight.  At least one entry.
_WEIGHT_BOOK = st.dictionaries(
    keys=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        min_size=1,
        max_size=4,
    ),
    values=st.floats(
        min_value=-5.0,
        max_value=5.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    min_size=1,
    max_size=8,
)


# ===========================================================================
# core_trading.money.sizing.scale_to_budget
# ===========================================================================


@given(weights=_WEIGHT_BOOK, gross_budget=st.floats(0.01, 50.0))
def test_scale_to_budget_respects_budget(
    weights: dict[str, float], gross_budget: float
) -> None:
    """Output gross never exceeds the budget (within float tolerance)."""
    scaled = scale_to_budget(weights, gross_budget=gross_budget)
    out_gross = sum(abs(v) for v in scaled.values())
    assert out_gross <= gross_budget + 1e-9


@given(weights=_WEIGHT_BOOK, gross_budget=st.floats(0.01, 50.0))
def test_scale_to_budget_preserves_signs_and_ratios(
    weights: dict[str, float], gross_budget: float
) -> None:
    """Scaling preserves the sign of every weight and the pairwise ratios.

    ``scale_to_budget`` multiplies the whole book by a single non-negative
    scalar, so signs cannot flip and ``w_i / w_j`` is invariant for any pair of
    non-zero weights.
    """
    scaled = scale_to_budget(weights, gross_budget=gross_budget)
    assert set(scaled) == set(weights)
    for k, v in weights.items():
        # Sign preserved (zero maps to zero).
        assert math.copysign(1.0, scaled[k]) == math.copysign(1.0, v) or v == 0.0
    # Pairwise ratio preserved for non-tiny weights.
    keys = [k for k, v in weights.items() if abs(v) > 1e-6]
    if len(keys) >= 2:
        a, b = keys[0], keys[1]
        in_ratio = weights[a] / weights[b]
        out_ratio = scaled[a] / scaled[b]
        assert math.isclose(in_ratio, out_ratio, rel_tol=1e-9, abs_tol=1e-12)


# ===========================================================================
# core_trading.money.leverage.apply_leverage_limits
# ===========================================================================


@given(
    weights=_WEIGHT_BOOK,
    max_gross=st.floats(0.1, 10.0),
    max_net=st.floats(0.1, 10.0),
)
def test_apply_leverage_limits_caps_gross_and_net(
    weights: dict[str, float], max_gross: float, max_net: float
) -> None:
    """Post-scaling gross <= max_gross and |net| <= max_net (within tol)."""
    config = LeverageConfig(max_gross=max_gross, max_net=max_net)
    report = apply_leverage_limits(weights, config=config)
    tol = 1e-9
    assert report.gross_after <= max_gross + tol
    assert report.net_after <= max_net + tol


@given(
    weights=_WEIGHT_BOOK,
    cap=st.floats(0.05, 5.0),
    max_gross=st.floats(0.1, 20.0),
    max_net=st.floats(0.1, 20.0),
)
def test_apply_leverage_limits_respects_class_cap(
    weights: dict[str, float],
    cap: float,
    max_gross: float,
    max_net: float,
) -> None:
    """A per-asset-class gross cap is honoured for the capped class.

    Every identifier is assigned to class ``"X"``; that class is capped at
    ``cap``.  Because the per-class scale-down runs last and only ever reduces
    exposure, the capped class's gross must end at or below ``cap``.
    """
    config = LeverageConfig(
        max_gross=max_gross,
        max_net=max_net,
        asset_class_caps={"X": cap},
    )
    class_map = {k: "X" for k in weights}
    report = apply_leverage_limits(
        weights, config=config, asset_class_map=class_map
    )
    class_gross = sum(
        abs(report.weights[k]) for k in weights if class_map[k] == "X"
    )
    assert class_gross <= cap + 1e-9


# ===========================================================================
# core_trading.money.turnover.realised_turnover
# ===========================================================================

# A wide weight panel: rows = periods, columns = assets, finite weights.
_WEIGHT_PANEL = st.lists(
    st.lists(
        st.floats(-2.0, 2.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=5,
    ),
    min_size=1,
    max_size=8,
).map(lambda rows: _rectangular(rows))


def _rectangular(rows: list[list[float]]) -> list[list[float]]:
    """Pad ragged generated rows to a common width so they form a panel."""
    width = max(len(r) for r in rows)
    return [r + [0.0] * (width - len(r)) for r in rows]


@given(panel=_WEIGHT_PANEL)
def test_realised_turnover_non_negative(panel: list[list[float]]) -> None:
    """Per-period one-sided turnover is always >= 0."""
    cols = [f"a{i}" for i in range(len(panel[0]))]
    df = pd.DataFrame(panel, columns=cols)
    turnover = realised_turnover(df)
    assert (turnover.to_numpy() >= -1e-12).all()


@given(panel=_WEIGHT_PANEL)
def test_realised_turnover_invariant_to_nan_columns(
    panel: list[list[float]],
) -> None:
    """Adding all-NaN (never-held) columns does not change turnover.

    A column that is NaN in every row is treated as a permanent zero position,
    so it can never contribute to the L1 weight change.
    """
    cols = [f"a{i}" for i in range(len(panel[0]))]
    df = pd.DataFrame(panel, columns=cols)
    base = realised_turnover(df)

    padded = df.copy()
    padded["nan_a"] = np.nan
    padded["nan_b"] = np.nan
    padded_turnover = realised_turnover(padded)

    np.testing.assert_allclose(
        base.to_numpy(), padded_turnover.to_numpy(), rtol=0.0, atol=1e-12
    )


# ===========================================================================
# core_trading.money.drawdown_management.compute_drawdown
# ===========================================================================

_POSITIVE_EQUITY = st.lists(
    st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=64,
)


@given(values=_POSITIVE_EQUITY)
def test_compute_drawdown_in_unit_interval(values: list[float]) -> None:
    """Drawdown of a positive equity curve lies in [0, 1)."""
    curve = pd.Series(values)
    dd = compute_drawdown(curve).to_numpy()
    assert (dd >= 0.0).all()
    # Strictly below 1: equity > 0 and running_max > 0 => 1 - e/rm < 1.
    assert (dd < 1.0).all()


@given(values=_POSITIVE_EQUITY)
def test_compute_drawdown_zero_at_running_highs(values: list[float]) -> None:
    """Drawdown is exactly 0 at every bar that sets a new running high."""
    curve = pd.Series(values)
    arr = curve.to_numpy(dtype=float)
    running_max = np.maximum.accumulate(arr)
    at_high = arr >= running_max  # bars that touch the running peak
    dd = compute_drawdown(curve).to_numpy()
    assert np.all(dd[at_high] == 0.0)


# ===========================================================================
# core_trading.execution.exec_algorithms -- schedule generators
# ===========================================================================

_TOTAL = st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False)
_N_INTERVALS = st.integers(min_value=1, max_value=50)
_SCHED_ATOL = 1e-6


@given(
    total=_TOTAL,
    n=_N_INTERVALS,
    lam=st.floats(min_value=0.0, max_value=1e-3, allow_nan=False, allow_infinity=False),
)
def test_ac_trajectory_sums_to_total(total: float, n: int, lam: float) -> None:
    """Almgren-Chriss trade list is non-negative and sums to the total."""
    params = ACParams(horizon=1.0, sigma=0.2, eta=0.5, gamma=0.0, lam=lam)
    sched = ac_trajectory(total, n, params=params)
    trades = sched.trades
    assert np.all(trades >= -_SCHED_ATOL)
    assert math.isclose(float(trades.sum()), total, abs_tol=1e-3, rel_tol=1e-9)


@given(
    total=_TOTAL,
    volumes=st.lists(
        st.floats(min_value=0.0, max_value=1e5, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=40,
    ),
    rate=st.floats(min_value=1e-3, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_pov_schedule_sums_to_total(
    total: float, volumes: list[float], rate: float
) -> None:
    """POV schedule (cleanup=True) is non-negative and sums to the total."""
    clip = pov_schedule(total, volumes, rate, cleanup=True)
    assert np.all(clip >= -_SCHED_ATOL)
    assert math.isclose(float(clip.sum()), total, abs_tol=_SCHED_ATOL, rel_tol=1e-9)


@given(
    total=_TOTAL,
    n=_N_INTERVALS,
    flf=st.floats(min_value=1e-3, max_value=5.0, allow_nan=False, allow_infinity=False),
)
def test_arrival_price_schedule_sums_to_total(
    total: float, n: int, flf: float
) -> None:
    """Exponential-decay arrival-price schedule sums to the total."""
    clip = arrival_price_schedule(total, n, front_load_factor=flf)
    assert np.all(clip >= -_SCHED_ATOL)
    assert math.isclose(float(clip.sum()), total, abs_tol=_SCHED_ATOL, rel_tol=1e-9)


@given(
    total=_TOTAL,
    volumes=st.lists(
        st.floats(min_value=0.0, max_value=1e5, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=40,
    ),
    max_part=st.floats(min_value=1e-3, max_value=1.0, allow_nan=False, allow_infinity=False),
    urgency=st.floats(min_value=1e-3, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_adaptive_liquidity_schedule_sums_to_total(
    total: float,
    volumes: list[float],
    max_part: float,
    urgency: float,
) -> None:
    """Adaptive liquidity-seeking schedule is non-negative and completes."""
    clip = adaptive_liquidity_schedule(
        total,
        volumes,
        min_clip=0.0,
        max_participation=max_part,
        urgency=urgency,
    )
    assert np.all(clip >= -_SCHED_ATOL)
    assert math.isclose(float(clip.sum()), total, abs_tol=_SCHED_ATOL, rel_tol=1e-9)


# ===========================================================================
# core_trading.execution.adverse_selection -- VPIN / BVC
# ===========================================================================

# A price/volume bar series.  Prices strictly positive; volumes non-negative.
_BARS = st.lists(
    st.tuples(
        st.floats(min_value=1.0, max_value=1e4, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=1e5, allow_nan=False, allow_infinity=False),
    ),
    min_size=2,
    max_size=60,
)


@given(bars=_BARS)
def test_bulk_volume_classify_conserves_volume(
    bars: list[tuple[float, float]],
) -> None:
    """BVC preserves total volume exactly: buy + sell == volume per bar."""
    prices = pd.Series([p for p, _ in bars])
    volumes = pd.Series([v for _, v in bars])
    buy, sell = bulk_volume_classify(prices, volumes, sigma_window=5)
    np.testing.assert_allclose(
        (buy + sell).to_numpy(), volumes.to_numpy(), rtol=0.0, atol=1e-9
    )
    assert (buy.to_numpy() >= -1e-12).all()
    assert (sell.to_numpy() >= -1e-12).all()


@given(bars=_BARS)
@settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_vpin_in_unit_interval(bars: list[tuple[float, float]]) -> None:
    """Every non-NaN VPIN value lies in [0, 1].

    ``filter_too_much`` is suppressed because the ``assume`` below rejects bar
    sets whose total volume is too small to complete a single bucket, leaving
    an empty VPIN series with nothing to assert.
    """
    prices = pd.Series([p for p, _ in bars])
    volumes = pd.Series([v for _, v in bars])
    # Need enough total volume that at least one bucket can complete.
    total_vol = float(volumes.sum())
    assume(total_vol > 0.0)
    # Choose a bucket size / window so buckets actually complete.
    bucket_size = max(total_vol / 4.0, 1e-6)
    config = AdverseSelectionConfig(
        sigma_window=2, bucket_size=bucket_size, n_buckets=1
    )
    series = vpin(prices, volumes, config=config)
    clean = series.dropna().to_numpy()
    assume(clean.size > 0)
    assert (clean >= -1e-12).all()
    assert (clean <= 1.0 + 1e-9).all()


# ===========================================================================
# core_trading.risk.var -- positive-loss convention
# ===========================================================================

_RETURNS = st.lists(
    st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=200,
)


@given(returns=_RETURNS)
def test_parametric_var_non_negative(returns: list[float]) -> None:
    """Parametric VaR is non-negative under the positive-loss convention."""
    arr = np.asarray(returns, dtype=float)
    # Parametric VaR = -z * sigma with z < 0, so it is >= 0 for any sigma >= 0.
    result = parametric_var(arr)
    assert result.var >= -1e-12


@given(returns=_RETURNS)
def test_historical_var_non_negative_for_loss_samples(
    returns: list[float],
) -> None:
    """Historical VaR is non-negative whenever the loss tail is non-positive.

    Historical VaR negates the empirical alpha-quantile.  It can legitimately
    be negative only when the alpha-quantile itself is positive (i.e. even the
    worst 5% of outcomes are gains).  We therefore assert non-negativity on the
    samples where the 5% quantile is a loss (<= 0), which is the regime the
    positive-loss convention is defined for.
    """
    arr = np.asarray(returns, dtype=float)
    q = float(np.quantile(arr, 0.05))
    assume(q <= 0.0)
    result = historical_var(arr)
    assert result.var >= -1e-12
