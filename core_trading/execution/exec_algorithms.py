"""Execution-algorithm schedule generators (master plan Phase 9.1).

This module is the **schedule-generation layer** of the execution stack.  Its
job is to compute, ahead of time, the *child-order schedule* -- how many shares
to trade in each of ``N`` discrete time intervals -- that a downstream executor
or backtester then sends to the market.  Everything here is **pure and
deterministic**: each function takes plain floats / NumPy arrays and returns a
schedule with no I/O, no clocks, and no broker calls.

Division of labour
------------------
* The *execution* of a schedule is owned by the async executors elsewhere in
  this package:

  - TWAP / VWAP slicing: :mod:`core_trading.execution.algo_orders`
    (``TWAPExecutor`` / ``VWAPExecutor``).
  - Iceberg / reserve display: :class:`core_trading.execution.advanced_orders`
    ``IcebergOrder``.

  Those classes consume a per-interval (or per-clip) quantity sequence; this
  module *produces* that sequence.  We deliberately do **not** re-implement the
  iceberg state machine -- :func:`iceberg_clip_sizes` only computes the clip
  list that ``IcebergOrder`` would slice into.

* The market-impact coefficients (``eta``, ``gamma``, ``sigma``, ...) are taken
  here as **explicit arguments**.  Calibrated values for a given symbol are
  produced by :mod:`core_trading.execution.impact_models` (written separately);
  this module never imports it, so the schedule generators stay self-contained
  and unit-testable with hand-chosen parameters.

Almgren-Chriss optimal execution
---------------------------------
The centrepiece is the closed-form Almgren-Chriss (2001) solution for the
Implementation-Shortfall problem of liquidating ``X`` shares over horizon ``T``
split into ``N`` intervals of length ``tau = T / N``.  With a linear temporary
impact coefficient ``eta`` and permanent impact ``gamma`` the model defines the
adjusted temporary-impact coefficient

    eta_tilde = eta - 0.5 * gamma * tau

and a trade-off parameter

    kappa_tilde^2 = lambda * sigma^2 / eta_tilde

where ``lambda >= 0`` is the trader's risk aversion and ``sigma`` is the
per-unit-time price volatility.  The optimal *holdings* trajectory is

    x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T),   t_j = j * tau

where ``kappa`` (units of inverse time) solves

    cosh(kappa * tau) = 1 + 0.5 * kappa_tilde^2 * tau^2.

The per-interval trade list is ``n_j = x_{j-1} - x_j`` for ``j = 1..N``.  The
expected implementation-shortfall cost and its variance are

    E[C] = 0.5 * gamma * X^2 + epsilon * sum_j |n_j|
                              + (eta_tilde / tau) * sum_j n_j^2
    V[C] = sigma^2 * tau * sum_{j=1..N} x_j^2

(``epsilon`` is the fixed half-spread cost per share; default 0).

As ``lambda -> 0`` the trade-off vanishes, ``kappa -> 0``, and the trajectory
degenerates to the straight line ``x_j = X * (1 - j / N)`` -- i.e. equal-sized
slices, the TWAP trajectory.  This limit is handled with an explicit
small-``kappa`` branch (the ``sinh`` ratio is numerically unstable near zero)
and is pinned by the test-suite.

Along the efficient frontier (sweeping ``lambda``) the expected cost ``E``
increases and the cost variance ``V`` decreases as ``lambda`` rises: a more
risk-averse trader front-loads execution, paying more impact to shed timing
risk sooner.

Schedule invariants (all generators)
------------------------------------
Every schedule returned by this module satisfies, up to a small float
tolerance:

* ``len(schedule) == n_intervals``
* every clip ``>= 0`` (these are unsigned magnitudes; the caller applies the
  buy/sell sign)
* ``sum(schedule) == total_shares``

:func:`validate_schedule` checks these and is called internally by the
generators.

References
----------
  * Almgren, R. & Chriss, N. (2001). "Optimal execution of portfolio
    transactions." Journal of Risk, 3(2), 5-39.
  * Almgren, R. (2003). "Optimal execution with nonlinear impact functions and
    trading-enhanced risk." Applied Mathematical Finance, 10(1), 1-18.
  * Kissell, R. & Glantz, M. (2003). "Optimal Trading Strategies." AMACOM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

__all__ = [
    "ACParams",
    "ACSchedule",
    "ac_trajectory",
    "efficient_frontier",
    "pov_schedule",
    "arrival_price_schedule",
    "adaptive_liquidity_schedule",
    "iceberg_clip_sizes",
    "validate_schedule",
]

# Absolute tolerance (in shares) for the sum-to-total invariant.  Schedules are
# computed in double precision; accumulated rounding across a few hundred
# intervals stays well under this bound.
_SUM_ATOL: float = 1e-6

# Below this value of ``kappa * tau`` the sinh-ratio trajectory is replaced by
# its linear (TWAP) limit to avoid catastrophic cancellation.  ``cosh(x) - 1``
# is ~5e-11 here, i.e. lambda is numerically indistinguishable from zero.
_KAPPA_TAU_LINEAR_THRESHOLD: float = 1e-5


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_schedule(
    schedule: npt.NDArray[np.float64],
    total: float,
    *,
    atol: float = _SUM_ATOL,
) -> None:
    """Validate the common invariants shared by all schedule generators.

    Parameters
    ----------
    schedule:
        One-dimensional array of per-interval trade magnitudes (unsigned).
    total:
        The total number of shares the schedule must sum to.
    atol:
        Absolute tolerance (in shares) for the sum-to-total check.

    Raises
    ------
    ValueError
        If the schedule is not 1-D, contains a negative or non-finite clip, or
        does not sum to ``total`` within ``atol``.
    """
    arr = np.asarray(schedule, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"schedule must be 1-D; got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("schedule contains non-finite values")
    if np.any(arr < -atol):
        raise ValueError("schedule contains a negative clip")
    actual = float(arr.sum())
    if not math.isclose(actual, total, abs_tol=atol, rel_tol=0.0):
        raise ValueError(
            f"schedule sums to {actual}, expected {total} (atol={atol})"
        )


# ---------------------------------------------------------------------------
# Almgren-Chriss parameters and result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ACParams:
    """Immutable Almgren-Chriss market and preference parameters.

    Attributes
    ----------
    horizon:
        Total liquidation horizon ``T`` (in arbitrary time units; ``sigma`` and
        ``lam`` must be expressed consistently).  Must be positive.
    sigma:
        Per-unit-time price volatility (price units per share, per sqrt-time).
        Must be positive.
    eta:
        Linear temporary-impact coefficient.  Price concession per unit trading
        *rate*.  Must be positive and large enough that the adjusted coefficient
        ``eta_tilde = eta - 0.5 * gamma * tau`` stays positive.
    gamma:
        Linear permanent-impact coefficient.  Non-negative.  Contributes the
        ``lambda``-independent ``0.5 * gamma * X^2`` term to expected cost.
    lam:
        Risk-aversion ``lambda >= 0``.  ``lambda = 0`` recovers the
        risk-neutral TWAP trajectory.
    epsilon:
        Fixed per-share cost (e.g. half the bid-ask spread).  Non-negative.
    """

    horizon: float
    sigma: float
    eta: float
    gamma: float = 0.0
    lam: float = 0.0
    epsilon: float = 0.0

    def __post_init__(self) -> None:
        if self.horizon <= 0:
            raise ValueError(f"horizon must be positive; got {self.horizon}")
        if self.sigma <= 0:
            raise ValueError(f"sigma must be positive; got {self.sigma}")
        if self.eta <= 0:
            raise ValueError(f"eta must be positive; got {self.eta}")
        if self.gamma < 0:
            raise ValueError(f"gamma must be non-negative; got {self.gamma}")
        if self.lam < 0:
            raise ValueError(f"lam must be non-negative; got {self.lam}")
        if self.epsilon < 0:
            raise ValueError(f"epsilon must be non-negative; got {self.epsilon}")


@dataclass(frozen=True, slots=True)
class ACSchedule:
    """Result of an Almgren-Chriss trajectory computation.

    Attributes
    ----------
    holdings:
        Array of length ``n_intervals + 1`` giving the remaining holdings
        ``x_j`` at times ``t_j = j * tau`` for ``j = 0..N``.  ``holdings[0]``
        equals ``total_shares`` and ``holdings[-1]`` equals 0.
    trades:
        Array of length ``n_intervals`` giving the shares traded in each
        interval, ``n_j = x_{j-1} - x_j`` for ``j = 1..N``.  All entries are
        non-negative and sum to ``total_shares``.
    expected_cost:
        Closed-form expected implementation-shortfall cost ``E[C]``.
    cost_variance:
        Closed-form cost variance ``V[C]``.
    kappa:
        The solved decay rate ``kappa`` (inverse time units).  Near zero for
        the TWAP limit.
    """

    holdings: npt.NDArray[np.float64]
    trades: npt.NDArray[np.float64]
    expected_cost: float
    cost_variance: float
    kappa: float


def _solve_kappa(params: ACParams, n_intervals: int) -> tuple[float, float]:
    """Return ``(kappa, eta_tilde)`` for the given parameters.

    Solves ``cosh(kappa * tau) = 1 + 0.5 * kappa_tilde^2 * tau^2`` for
    ``kappa``, where ``kappa_tilde^2 = lam * sigma^2 / eta_tilde``.  Returns
    ``kappa = 0`` exactly when ``lam == 0``.
    """
    tau = params.horizon / n_intervals
    eta_tilde = params.eta - 0.5 * params.gamma * tau
    if eta_tilde <= 0:
        raise ValueError(
            "eta_tilde = eta - 0.5*gamma*tau must be positive; "
            f"got {eta_tilde} (increase eta or n_intervals, or lower gamma)"
        )
    if params.lam == 0.0:
        return 0.0, eta_tilde
    kappa_tilde_sq = params.lam * params.sigma**2 / eta_tilde
    rhs = 1.0 + 0.5 * kappa_tilde_sq * tau * tau
    # arccosh is well-conditioned for rhs >= 1, which holds since the RHS >= 1.
    kappa = math.acosh(rhs) / tau
    return kappa, eta_tilde


def ac_trajectory(
    total_shares: float,
    n_intervals: int,
    *,
    params: ACParams,
) -> ACSchedule:
    """Compute the Almgren-Chriss optimal liquidation trajectory.

    Parameters
    ----------
    total_shares:
        Total shares ``X`` to liquidate.  Must be positive.  The returned
        trades are unsigned magnitudes; the caller applies the buy/sell sign.
    n_intervals:
        Number of discrete trading intervals ``N >= 1``.
    params:
        Market and preference parameters (see :class:`ACParams`).

    Returns
    -------
    ACSchedule
        Holdings path, per-interval trade list, closed-form expected cost and
        variance, and the solved ``kappa``.

    Notes
    -----
    For ``lambda = 0`` (or numerically ``kappa * tau`` below the linear
    threshold) the trajectory is the exact straight line ``x_j = X(1 - j/N)``.
    """
    if total_shares <= 0:
        raise ValueError(f"total_shares must be positive; got {total_shares}")
    if n_intervals < 1:
        raise ValueError(f"n_intervals must be >= 1; got {n_intervals}")

    tau = params.horizon / n_intervals
    kappa, eta_tilde = _solve_kappa(params, n_intervals)

    j = np.arange(n_intervals + 1, dtype=np.float64)
    if kappa * tau < _KAPPA_TAU_LINEAR_THRESHOLD:
        # Risk-neutral / numerically-zero kappa: exact linear (TWAP) trajectory.
        holdings = total_shares * (1.0 - j / n_intervals)
    else:
        t_j = j * tau
        holdings = (
            total_shares
            * np.sinh(kappa * (params.horizon - t_j))
            / math.sinh(kappa * params.horizon)
        )
    # Pin the endpoints exactly (guards against any float drift in sinh ratio).
    holdings[0] = total_shares
    holdings[-1] = 0.0

    trades = holdings[:-1] - holdings[1:]

    expected_cost = (
        0.5 * params.gamma * total_shares**2
        + params.epsilon * float(np.sum(np.abs(trades)))
        + (eta_tilde / tau) * float(np.sum(trades**2))
    )
    cost_variance = (
        params.sigma**2 * tau * float(np.sum(holdings[1:] ** 2))
    )

    validate_schedule(trades, total_shares)
    return ACSchedule(
        holdings=holdings,
        trades=trades,
        expected_cost=expected_cost,
        cost_variance=cost_variance,
        kappa=kappa,
    )


def efficient_frontier(
    lambdas: npt.NDArray[np.float64] | list[float],
    total_shares: float,
    n_intervals: int,
    *,
    base_params: ACParams,
) -> list[tuple[float, float, float]]:
    """Trace the Almgren-Chriss efficient frontier over a grid of ``lambda``.

    For each ``lambda`` in ``lambdas`` the optimal trajectory is solved and the
    triple ``(lambda, expected_cost, cost_variance)`` recorded.  ``base_params``
    supplies all market parameters; its ``lam`` field is overridden by each grid
    value.

    Parameters
    ----------
    lambdas:
        Iterable of non-negative risk-aversion values.
    total_shares:
        Total shares ``X`` to liquidate.
    n_intervals:
        Number of trading intervals.
    base_params:
        Template parameters; ``lam`` is replaced per grid point.

    Returns
    -------
    list of (lambda, E[C], V[C])
        One tuple per input ``lambda``, in input order.  As ``lambda``
        increases, ``E[C]`` is (weakly) increasing and ``V[C]`` is (weakly)
        decreasing.
    """
    points: list[tuple[float, float, float]] = []
    for lam in lambdas:
        lam_f = float(lam)
        params = ACParams(
            horizon=base_params.horizon,
            sigma=base_params.sigma,
            eta=base_params.eta,
            gamma=base_params.gamma,
            lam=lam_f,
            epsilon=base_params.epsilon,
        )
        sched = ac_trajectory(total_shares, n_intervals, params=params)
        points.append((lam_f, sched.expected_cost, sched.cost_variance))
    return points


# ---------------------------------------------------------------------------
# Participation rate (POV)
# ---------------------------------------------------------------------------


def pov_schedule(
    total_shares: float,
    expected_volumes: npt.NDArray[np.float64] | list[float],
    participation_rate: float,
    *,
    cleanup: bool = True,
) -> npt.NDArray[np.float64]:
    """Percent-of-volume (POV) child schedule.

    The child quantity in interval ``i`` is ``participation_rate * volume_i``,
    capped so the cumulative quantity never exceeds ``total_shares``.

    Parameters
    ----------
    total_shares:
        Total shares to execute (positive).
    expected_volumes:
        Forecast market volume in each interval (non-negative).  Defines the
        number of intervals.
    participation_rate:
        Target fraction of interval volume to capture, in ``(0, 1]``.
    cleanup:
        Remainder handling.  If ``True`` (default) any shares not placed by the
        natural POV rule are added to the final interval so the schedule sums
        exactly to ``total_shares`` (final-interval *cleanup*).  If ``False``
        the schedule is *truncated*: it may sum to less than ``total_shares``
        when forecast volume is insufficient, and the (smaller) actual total is
        used for the sum-invariant check.

    Returns
    -------
    numpy.ndarray
        Per-interval child quantities, one per element of ``expected_volumes``.
    """
    if total_shares <= 0:
        raise ValueError(f"total_shares must be positive; got {total_shares}")
    if not (0.0 < participation_rate <= 1.0):
        raise ValueError(
            f"participation_rate must be in (0, 1]; got {participation_rate}"
        )
    vols = np.asarray(expected_volumes, dtype=np.float64)
    if vols.ndim != 1 or vols.size == 0:
        raise ValueError("expected_volumes must be a non-empty 1-D array")
    if np.any(vols < 0):
        raise ValueError("expected_volumes must be non-negative")

    raw = participation_rate * vols
    # Cap cumulative trades at total_shares.
    cumulative = np.cumsum(raw)
    overflow = np.maximum(cumulative - total_shares, 0.0)
    # Per-interval overflow to subtract: difference of clamped overflow.
    prev_overflow = np.concatenate(([0.0], overflow[:-1]))
    clip: npt.NDArray[np.float64] = np.maximum(
        raw - (overflow - prev_overflow), 0.0
    )

    placed = float(clip.sum())
    if cleanup:
        remainder = total_shares - placed
        if remainder > _SUM_ATOL:
            clip[-1] += remainder
        validate_schedule(clip, total_shares)
    else:
        # Truncation: schedule may under-fill; validate against actual placed.
        validate_schedule(clip, placed)
    return clip


# ---------------------------------------------------------------------------
# Arrival price (front-loaded)
# ---------------------------------------------------------------------------


def arrival_price_schedule(
    total_shares: float,
    n_intervals: int,
    *,
    params: ACParams | None = None,
    front_load_factor: float | None = None,
) -> npt.NDArray[np.float64]:
    """Front-loaded arrival-price schedule minimising drift vs the decision price.

    Two equivalent ways to express the same intent -- trade urgently early to
    minimise exposure to price drift away from the arrival (decision) price --
    are offered:

    * **Almgren-Chriss high-urgency** (``params`` given): the schedule is the
      AC trade list with a large ``lambda``.  This is the *principled* arrival-
      price strategy; the front-loading emerges from the optimisation.

    * **Exponential decay** (``front_load_factor`` given): a closed-form
      geometric profile ``n_i proportional to exp(-front_load_factor * i)``.
      This reproduces the *shape* of the AC solution -- the AC holdings path
      ``sinh(kappa(T - t))`` decays roughly geometrically with rate ``kappa``,
      so ``front_load_factor`` plays the role of ``kappa * tau`` -- but without
      requiring market-impact calibration.  Larger ``front_load_factor`` =
      more aggressive front-loading; ``front_load_factor -> 0`` recovers TWAP.

    Exactly one of ``params`` / ``front_load_factor`` must be supplied.

    Parameters
    ----------
    total_shares:
        Total shares to execute (positive).
    n_intervals:
        Number of trading intervals (>= 1).
    params:
        Almgren-Chriss parameters with the desired (large) ``lam``.
    front_load_factor:
        Positive exponential-decay rate for the explicit geometric variant.

    Returns
    -------
    numpy.ndarray
        Per-interval child quantities summing to ``total_shares``.
    """
    if (params is None) == (front_load_factor is None):
        raise ValueError(
            "supply exactly one of params or front_load_factor"
        )
    if total_shares <= 0:
        raise ValueError(f"total_shares must be positive; got {total_shares}")
    if n_intervals < 1:
        raise ValueError(f"n_intervals must be >= 1; got {n_intervals}")

    if params is not None:
        return ac_trajectory(total_shares, n_intervals, params=params).trades

    assert front_load_factor is not None  # narrowed for mypy
    if front_load_factor <= 0:
        raise ValueError(
            f"front_load_factor must be positive; got {front_load_factor}"
        )
    i = np.arange(n_intervals, dtype=np.float64)
    weights = np.exp(-front_load_factor * i)
    clip = total_shares * weights / float(weights.sum())
    validate_schedule(clip, total_shares)
    return clip


# ---------------------------------------------------------------------------
# Adaptive liquidity-seeking (Sniper-style)
# ---------------------------------------------------------------------------


def adaptive_liquidity_schedule(
    total_shares: float,
    observed_volumes: npt.NDArray[np.float64] | list[float],
    *,
    min_clip: float,
    max_participation: float,
    urgency: float = 1.0,
) -> npt.NDArray[np.float64]:
    """Deterministic adaptive liquidity-seeking (Sniper-style) schedule.

    A rule-based scheduler that trades *more* where observed liquidity is high
    while respecting a participation ceiling and a minimum clip, and that
    *guarantees completion* by the end of the horizon via a catch-up term.

    For each interval ``i`` with remaining shares ``R`` and remaining intervals
    ``m``:

    1. Liquidity-proportional desire: ``urgency * max_participation * volume_i``.
    2. Catch-up floor: ``R / m`` -- the even split of what is left.  As ``m``
       shrinks this term grows and becomes binding, forcing completion.
    3. The clip is the *max* of (1) and (2) -- so a quiet interval near the end
       still trades enough to finish -- then capped by both
       ``max_participation * volume_i`` and the remaining ``R``.
    4. The clip is raised to ``min_clip`` when below it, *except* when fewer
       than ``min_clip`` shares remain (the final remainder), in which case the
       remainder is traded.

    The schedule is fully deterministic given its inputs.

    Parameters
    ----------
    total_shares:
        Total shares to execute (positive).
    observed_volumes:
        Observed / forecast interval volumes (non-negative).  Defines the
        number of intervals.
    min_clip:
        Minimum trade size per active interval (non-negative).
    max_participation:
        Hard ceiling on the fraction of interval volume captured, in ``(0, 1]``.
    urgency:
        Scales the liquidity-proportional desire in ``(0, 1]``.  ``1.0`` trades
        at the full participation ceiling whenever liquidity allows.

    Returns
    -------
    numpy.ndarray
        Per-interval child quantities summing to ``total_shares``.
    """
    if total_shares <= 0:
        raise ValueError(f"total_shares must be positive; got {total_shares}")
    if min_clip < 0:
        raise ValueError(f"min_clip must be non-negative; got {min_clip}")
    if not (0.0 < max_participation <= 1.0):
        raise ValueError(
            f"max_participation must be in (0, 1]; got {max_participation}"
        )
    if not (0.0 < urgency <= 1.0):
        raise ValueError(f"urgency must be in (0, 1]; got {urgency}")
    vols = np.asarray(observed_volumes, dtype=np.float64)
    if vols.ndim != 1 or vols.size == 0:
        raise ValueError("observed_volumes must be a non-empty 1-D array")
    if np.any(vols < 0):
        raise ValueError("observed_volumes must be non-negative")

    n = vols.size
    clip = np.zeros(n, dtype=np.float64)
    remaining = total_shares
    for i in range(n):
        intervals_left = n - i
        if remaining <= _SUM_ATOL:
            break
        cap = max_participation * vols[i]
        catch_up = remaining / intervals_left
        desire = urgency * cap
        qty = max(desire, catch_up)
        # Cap by participation ceiling -- but never let the ceiling prevent
        # completion: the catch-up term may exceed the (possibly tiny) cap.
        qty = max(min(qty, cap), catch_up) if cap > 0 else catch_up
        # Apply the minimum clip, unless the entire remainder is smaller.
        if qty < min_clip:
            qty = min(min_clip, remaining)
        # Never over-trade the remainder.
        qty = min(qty, remaining)
        clip[i] = qty
        remaining -= qty

    # Defensive net: the per-interval ``remaining`` bookkeeping already clears
    # the order exactly (the final interval's catch-up term equals ``remaining``
    # since ``intervals_left == 1``), so this correction is not expected to fire
    # in normal operation -- it guards only against pathological float drift.
    residual = total_shares - float(clip.sum())
    if abs(residual) > _SUM_ATOL:  # pragma: no cover - defensive
        clip[n - 1] += residual
    validate_schedule(clip, total_shares)
    return clip


# ---------------------------------------------------------------------------
# Iceberg clip helper
# ---------------------------------------------------------------------------


def iceberg_clip_sizes(
    total: float,
    display_size: float,
) -> list[float]:
    """Clip-size list for an iceberg order.

    This is a *schedule helper only*.  The actual reserve-display state machine
    -- showing one clip, refreshing on fill -- lives in
    :class:`core_trading.execution.advanced_orders.IcebergOrder`; pass the
    ``total`` and ``display_size`` to that executor for live trading.  Here we
    merely enumerate the sequence of visible clips: ``display_size`` repeated as
    many times as fits, with a smaller final clip for the remainder.

    Parameters
    ----------
    total:
        Total order size (positive).
    display_size:
        Visible clip size (positive).  If ``display_size >= total`` a single
        clip of ``total`` is returned.

    Returns
    -------
    list of float
        Clip sizes that sum to ``total``.  All but possibly the last equal
        ``display_size``; the last is the remainder.
    """
    if total <= 0:
        raise ValueError(f"total must be positive; got {total}")
    if display_size <= 0:
        raise ValueError(f"display_size must be positive; got {display_size}")

    if display_size >= total:
        return [float(total)]

    n_full = int(math.floor(total / display_size + _SUM_ATOL))
    clips = [float(display_size)] * n_full
    remainder = total - n_full * display_size
    if remainder > _SUM_ATOL:
        clips.append(float(remainder))
    validate_schedule(np.asarray(clips, dtype=np.float64), total)
    return clips
