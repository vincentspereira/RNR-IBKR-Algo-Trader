"""Market-impact models for execution cost estimation (master plan Phase 9.3).

This module implements three canonical market-impact models plus a deterministic
monthly calibration routine that fits a square-root impact law to a trader's own
fills.

Models
------
1. **Almgren-Chriss square-root model** -- splits expected cost into a
   *temporary* (liquidity-demand) component and a *permanent* (information-leak)
   component.  The temporary component follows a power law in the participation
   rate ``v / V`` (default exponent ``beta = 0.5``, the square-root law); the
   permanent component is linear in the total order's fraction of volume
   ``Q / V``.  Both per-slice and whole-schedule expected costs are provided.

2. **Obizhaeva-Wang transient impact** -- models a limit-order book with finite
   depth and exponential *resilience*.  Each child trade displaces the price; the
   displacement decays as ``exp(-rho * dt)`` between trades.  The expected impact
   path and total transient cost of an arbitrary child schedule are returned.

3. **Kissell-Glantz I-Star** -- an empirical model in which the instantaneous
   ("I-Star") impact ``I* = a1 * (Q / ADV)^a2 * sigma^a3`` is split into a
   temporary part scaling with the percentage-of-volume (POV) rate and a
   permanent part via the mixing coefficient ``b1``.

Calibration
-----------
:func:`calibrate_impact` fits the square-root law to a fills DataFrame by ordinary
least squares on the log-linearised relation

    log|slippage| = log(eta) + beta * log(participation) + log(sigma)

(equivalently a regression of ``log|slippage| - log(sigma)`` on
``log(participation)``).  It is fully deterministic, returns goodness-of-fit
statistics, and never raises on degenerate input -- instead it sets
``well_determined = False``.

Units and sign conventions
--------------------------
* All impact / cost figures are returned as a **decimal fraction of the arrival
  price** (i.e. a slippage fraction).  Multiply by ``10_000`` for basis points;
  the :func:`expected_cost_bps` helpers do this for you.
* The sign follows the repo-wide *positive-loss* convention used in
  ``core_trading.risk`` and ``core_trading.money``: a **positive** cost is a
  cost *to the trader* (adverse price move), regardless of trade direction.
  Models here return non-negative impact magnitudes; the execution layer applies
  the trade sign when comparing realised fill prices to arrival.
* ``sigma`` denotes per-period (typically daily) return volatility as a decimal
  fraction.  ``participation = v / V`` and ``Q / ADV`` are dimensionless ratios.

References
----------
* Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio
  Transactions." Journal of Risk, 3(2), 5-39.
* Almgren, R., Thum, C., Hauptmann, E. & Li, H. (2005). "Direct Estimation of
  Equity Market Impact." Risk, 18(7), 58-62.
* Obizhaeva, A. & Wang, J. (2013). "Optimal Trading Strategy and
  Supply/Demand Dynamics." Journal of Financial Markets, 16(1), 1-32.
* Kissell, R. & Glantz, M. (2003). "Optimal Trading Strategies: Quantitative
  Approaches for Managing Market Impact and Trading Risk." AMACOM.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

__all__ = [
    # Parameter / result dataclasses
    "ACParams",
    "OWParams",
    "IStarParams",
    "CalibrationResult",
    # Almgren-Chriss square-root model
    "ac_temporary_impact",
    "ac_permanent_impact",
    "ac_slice_cost",
    "ac_schedule_cost",
    # Obizhaeva-Wang transient impact
    "ow_impact_path",
    "ow_schedule_cost",
    # Kissell-Glantz I-Star
    "istar_impact",
    "kissell_glantz_cost",
    # Calibration
    "calibrate_impact",
    # Helpers
    "expected_cost_bps",
]


_BPS_PER_UNIT = 10_000.0


# ---------------------------------------------------------------------------
# Parameter / result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ACParams:
    """Immutable parameters for the Almgren-Chriss square-root model.

    Attributes
    ----------
    eta:
        Temporary-impact coefficient (dimensionless).  Scales the temporary
        impact ``eta * sigma * participation**beta``.  Must be ``>= 0``.
    gamma:
        Permanent-impact coefficient (dimensionless).  Scales the permanent
        impact ``gamma * sigma * (Q / V)``.  Must be ``>= 0``.
    beta:
        Power-law exponent on the participation rate for the temporary impact.
        ``0.5`` recovers the classic square-root law.  Must be ``> 0``.
    sigma:
        Per-period (e.g. daily) return volatility as a decimal fraction.  Must
        be ``>= 0``.
    """

    eta: float = 0.1
    gamma: float = 0.05
    beta: float = 0.5
    sigma: float = 0.02

    def __post_init__(self) -> None:
        if self.eta < 0:
            raise ValueError(f"eta must be non-negative; got {self.eta}")
        if self.gamma < 0:
            raise ValueError(f"gamma must be non-negative; got {self.gamma}")
        if self.beta <= 0:
            raise ValueError(f"beta must be positive; got {self.beta}")
        if self.sigma < 0:
            raise ValueError(f"sigma must be non-negative; got {self.sigma}")


@dataclass(frozen=True, slots=True)
class OWParams:
    """Immutable parameters for the Obizhaeva-Wang transient-impact model.

    Attributes
    ----------
    kappa:
        Instantaneous impact per unit of participation rate (the inverse of
        order-book depth).  A child trade of participation ``v`` displaces the
        price by ``kappa * v`` (as a fraction of the arrival price) at the
        moment of execution.  Must be ``>= 0``.
    rho:
        Resilience (mean-reversion) rate, in units of inverse time.  Between two
        trades separated by ``dt``, the outstanding displacement decays by
        ``exp(-rho * dt)``.  Must be ``> 0``.
    """

    kappa: float = 0.1
    rho: float = 1.0

    def __post_init__(self) -> None:
        if self.kappa < 0:
            raise ValueError(f"kappa must be non-negative; got {self.kappa}")
        if self.rho <= 0:
            raise ValueError(f"rho must be positive; got {self.rho}")


@dataclass(frozen=True, slots=True)
class IStarParams:
    """Immutable parameters for the Kissell-Glantz I-Star model.

    Attributes
    ----------
    a1:
        Overall scale of the instantaneous impact ``I*``.  Must be ``>= 0``.
    a2:
        Exponent on the order's fraction of average daily volume ``Q / ADV``.
        Must be ``> 0``.
    a3:
        Exponent on the volatility ``sigma``.  Must be ``> 0``.
    a4:
        Exponent on the percentage-of-volume (POV) rate in the temporary term.
        Must be ``> 0``.
    b1:
        Temporary/permanent mixing coefficient in ``[0, 1]``.  ``b1`` weights the
        POV-dependent (temporary) part; ``1 - b1`` weights the permanent part.
    """

    a1: float = 750.0
    a2: float = 0.5
    a3: float = 0.75
    a4: float = 0.5
    b1: float = 0.9

    def __post_init__(self) -> None:
        if self.a1 < 0:
            raise ValueError(f"a1 must be non-negative; got {self.a1}")
        if self.a2 <= 0:
            raise ValueError(f"a2 must be positive; got {self.a2}")
        if self.a3 <= 0:
            raise ValueError(f"a3 must be positive; got {self.a3}")
        if self.a4 <= 0:
            raise ValueError(f"a4 must be positive; got {self.a4}")
        if not (0.0 <= self.b1 <= 1.0):
            raise ValueError(f"b1 must be in [0, 1]; got {self.b1}")


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Outcome of :func:`calibrate_impact`.

    Attributes
    ----------
    eta:
        Fitted temporary-impact coefficient (``exp(intercept)``).
    beta:
        Fitted participation exponent (the regression slope).
    r_squared:
        Coefficient of determination of the log-linear fit, in ``[0, 1]``.
        ``0.0`` when undefined (e.g. zero variance in the response).
    n_obs:
        Number of usable observations after filtering non-finite / non-positive
        rows.
    well_determined:
        ``True`` only when enough finite observations with non-degenerate
        participation variation were available to identify the slope.  When
        ``False``, ``eta`` and ``beta`` fall back to the supplied defaults and
        callers should treat the fit as unreliable rather than acting on it.
    """

    eta: float
    beta: float
    r_squared: float
    n_obs: int
    well_determined: bool

    def __post_init__(self) -> None:
        if self.eta < 0:
            raise ValueError(f"eta must be non-negative; got {self.eta}")
        if self.beta <= 0:
            raise ValueError(f"beta must be positive; got {self.beta}")
        if not (0.0 <= self.r_squared <= 1.0):
            raise ValueError(
                f"r_squared must be in [0, 1]; got {self.r_squared}"
            )
        if self.n_obs < 0:
            raise ValueError(f"n_obs must be non-negative; got {self.n_obs}")


# ---------------------------------------------------------------------------
# Almgren-Chriss square-root model
# ---------------------------------------------------------------------------


def ac_temporary_impact(participation: float, params: ACParams) -> float:
    """Return the temporary impact of trading at a given participation rate.

    The temporary (liquidity-demand) impact is

        h(v) = eta * sigma * (v / V)**beta

    where ``participation = v / V`` is the slice's share of period volume.  With
    the default ``beta = 0.5`` this is the classic square-root law of
    Almgren et al. (2005).

    Parameters
    ----------
    participation:
        Slice volume as a fraction of the venue / period volume, ``v / V``.
        Must be ``>= 0``.  Zero yields zero impact.
    params:
        Model coefficients.

    Returns
    -------
    float
        Temporary impact as a non-negative decimal fraction of arrival price.

    Raises
    ------
    ValueError
        If ``participation`` is negative.
    """
    if participation < 0:
        raise ValueError(
            f"participation must be non-negative; got {participation}"
        )
    if participation == 0.0:
        return 0.0
    return float(params.eta * params.sigma * (participation ** params.beta))


def ac_permanent_impact(order_fraction: float, params: ACParams) -> float:
    """Return the permanent impact of an order of a given size.

    The permanent (information) impact is linear in the order's fraction of
    period volume:

        g(Q) = gamma * sigma * (Q / V)

    Parameters
    ----------
    order_fraction:
        Total order size as a fraction of period volume, ``Q / V``.  Must be
        ``>= 0``.
    params:
        Model coefficients.

    Returns
    -------
    float
        Permanent impact as a non-negative decimal fraction of arrival price.

    Raises
    ------
    ValueError
        If ``order_fraction`` is negative.
    """
    if order_fraction < 0:
        raise ValueError(
            f"order_fraction must be non-negative; got {order_fraction}"
        )
    return params.gamma * params.sigma * order_fraction


def ac_slice_cost(
    participation: float,
    order_fraction: float,
    params: ACParams,
) -> float:
    """Return the expected per-slice cost under Almgren-Chriss.

    The slice cost combines the temporary impact incurred by *this* slice with
    the permanent impact already imprinted on the price by the *whole* order:

        cost = h(participation) + g(order_fraction)

    Both terms are expressed as a fraction of the arrival price.  The temporary
    term is the marginal cost of demanding liquidity for this slice; the
    permanent term is the standing displacement that any slice executed after
    information leakage must pay.

    Parameters
    ----------
    participation:
        This slice's participation rate ``v / V``.
    order_fraction:
        The full order's fraction of period volume ``Q / V``.
    params:
        Model coefficients.

    Returns
    -------
    float
        Expected slice cost as a non-negative decimal fraction of arrival price.
    """
    temp = ac_temporary_impact(participation, params)
    perm = ac_permanent_impact(order_fraction, params)
    return temp + perm


def ac_schedule_cost(
    slice_participations: Sequence[float] | np.ndarray,
    params: ACParams,
    *,
    permanent_on_half: bool = True,
) -> float:
    """Return the total expected cost of an execution schedule.

    The schedule is described by the per-slice participation rates
    ``slice_participations = [v_1/V_1, ..., v_n/V_n]``.  The volume-weighted
    *temporary* cost is the mean of the per-slice temporary impacts weighted by
    each slice's participation (larger slices cost proportionally more), and the
    *permanent* cost is charged once on the whole order's fraction of volume,
    ``Q / V = sum(slice_participations)``.

    The factor ``1/2`` on the permanent term (enabled by ``permanent_on_half``)
    reflects the Almgren-Chriss result that, for a schedule that builds the
    position linearly, the *average* execution price pays only half of the final
    permanent displacement.

    Parameters
    ----------
    slice_participations:
        Per-slice participation rates ``v_i / V_i``.  All entries must be
        ``>= 0``.  An empty schedule has zero cost.
    params:
        Model coefficients.
    permanent_on_half:
        When ``True`` (default) the permanent term is multiplied by ``0.5`` per
        the linear-schedule result; set ``False`` to charge the full permanent
        displacement (worst case).

    Returns
    -------
    float
        Total expected cost as a non-negative decimal fraction of arrival price.

    Raises
    ------
    ValueError
        If any participation entry is negative.
    """
    arr = np.asarray(slice_participations, dtype=float).ravel()
    if arr.size == 0:
        return 0.0
    if np.any(arr < 0):
        raise ValueError("all slice participations must be non-negative")

    total_fraction = float(arr.sum())
    # Volume-weighted temporary cost: each slice's temporary impact weighted by
    # the fraction of the parent order that the slice represents.
    temp_per_slice = params.eta * params.sigma * np.power(arr, params.beta)
    if total_fraction > 0.0:
        weights = arr / total_fraction
        temp_cost = float(np.dot(weights, temp_per_slice))
    else:
        temp_cost = 0.0

    perm_full = ac_permanent_impact(total_fraction, params)
    perm_cost = 0.5 * perm_full if permanent_on_half else perm_full
    return temp_cost + perm_cost


# ---------------------------------------------------------------------------
# Obizhaeva-Wang transient impact
# ---------------------------------------------------------------------------


def ow_impact_path(
    participations: Sequence[float] | np.ndarray,
    dt: Sequence[float] | np.ndarray | float,
    params: OWParams,
) -> np.ndarray:
    """Return the price-displacement path under the Obizhaeva-Wang model.

    Each child trade ``i`` of participation ``v_i`` adds an instantaneous
    displacement ``kappa * v_i`` to the outstanding price displacement.  Between
    trade ``i`` and trade ``i + 1`` (separated by ``dt_i``) the outstanding
    displacement decays by ``exp(-rho * dt_i)`` (the limit-order book replenishes
    -- "resilience").

    The returned array ``D`` has ``D[i]`` equal to the displacement *immediately
    after* the ``i``-th child trade executes, i.e. the impact that trade ``i``
    pays:

        D[0] = kappa * v_0
        D[i] = D[i-1] * exp(-rho * dt_{i-1}) + kappa * v_i

    Parameters
    ----------
    participations:
        Child-trade participation rates ``v_i`` (fractions of period volume).
        All entries must be ``>= 0``.
    dt:
        Inter-trade time gaps.  Either a scalar (uniform spacing applied between
        every consecutive pair) or a sequence.  When a sequence, it may have
        length ``n`` or ``n - 1`` (only the first ``n - 1`` gaps are used).  All
        gaps must be ``>= 0``.
    params:
        Model coefficients.

    Returns
    -------
    numpy.ndarray
        Displacement path ``D`` of length ``n``, in fractions of arrival price.

    Raises
    ------
    ValueError
        If any participation or gap is negative, or ``dt`` length is incompatible.
    """
    v = np.asarray(participations, dtype=float).ravel()
    n = v.size
    if n == 0:
        return np.zeros(0, dtype=float)
    if np.any(v < 0):
        raise ValueError("all participations must be non-negative")

    dt_arr = np.asarray(dt, dtype=float)
    n_gaps = max(n - 1, 0)
    if dt_arr.ndim == 0:
        gaps: np.ndarray = np.full(n_gaps, float(dt_arr), dtype=float)
    else:
        gaps_in = dt_arr.ravel()
        if gaps_in.size == n:
            gaps = gaps_in[:n_gaps] if n > 1 else np.zeros(0, dtype=float)
        elif gaps_in.size == n_gaps:
            gaps = gaps_in
        else:
            raise ValueError(
                f"dt length {gaps_in.size} incompatible with {n} trades"
            )
    if bool(np.any(gaps < 0.0)):
        raise ValueError("all time gaps must be non-negative")

    displacement = np.empty(n, dtype=float)
    running = 0.0
    for i in range(n):
        if i > 0:
            running *= math.exp(-params.rho * gaps[i - 1])
        running += params.kappa * v[i]
        displacement[i] = running
    return displacement


def ow_schedule_cost(
    participations: Sequence[float] | np.ndarray,
    dt: Sequence[float] | np.ndarray | float,
    params: OWParams,
) -> float:
    """Return the total transient-impact cost of a child schedule.

    The cost paid is the participation-weighted average displacement along the
    path returned by :func:`ow_impact_path`:

        cost = sum_i v_i * D[i] / sum_i v_i

    i.e. each child trade pays the outstanding displacement at the instant it
    executes, and the whole-order cost is the volume-weighted mean of those
    payments (a decimal fraction of the arrival price).

    Parameters
    ----------
    participations:
        Child-trade participation rates ``v_i``.
    dt:
        Inter-trade time gaps (scalar or sequence; see :func:`ow_impact_path`).
    params:
        Model coefficients.

    Returns
    -------
    float
        Total transient cost as a non-negative decimal fraction of arrival price.
        Zero when total participation is zero.
    """
    v = np.asarray(participations, dtype=float).ravel()
    path = ow_impact_path(v, dt, params)
    total = float(v.sum())
    if total <= 0.0:
        return 0.0
    return float(np.dot(v, path) / total)


# ---------------------------------------------------------------------------
# Kissell-Glantz I-Star
# ---------------------------------------------------------------------------


def istar_impact(
    order_fraction: float,
    sigma: float,
    params: IStarParams,
) -> float:
    """Return the instantaneous ("I-Star") impact of an order.

    The I-Star quantity is the theoretical cost of executing the entire order
    instantaneously:

        I* = a1 * (Q / ADV)**a2 * sigma**a3

    Following Kissell & Glantz, ``a1`` is conventionally expressed so that ``I*``
    is in **basis points**; this function returns ``I*`` in the same basis-point
    units as ``a1``.  Use :func:`kissell_glantz_cost` for a decimal-fraction
    cost with the temporary/permanent split applied.

    Parameters
    ----------
    order_fraction:
        Order size as a fraction of average daily volume, ``Q / ADV``.  Must be
        ``>= 0``.
    sigma:
        Per-period return volatility as a decimal fraction.  Must be ``>= 0``.
    params:
        Model coefficients.

    Returns
    -------
    float
        Instantaneous impact ``I*`` in the basis-point units implied by ``a1``.

    Raises
    ------
    ValueError
        If ``order_fraction`` or ``sigma`` is negative.
    """
    if order_fraction < 0:
        raise ValueError(
            f"order_fraction must be non-negative; got {order_fraction}"
        )
    if sigma < 0:
        raise ValueError(f"sigma must be non-negative; got {sigma}")
    if order_fraction == 0.0 or sigma == 0.0:
        return 0.0
    return float(params.a1 * (order_fraction ** params.a2) * (sigma ** params.a3))


def kissell_glantz_cost(
    order_fraction: float,
    sigma: float,
    pov: float,
    params: IStarParams,
) -> float:
    """Return the Kissell-Glantz market-impact cost with temporary split.

    The total market impact mixes a temporary part (scaling with the
    percentage-of-volume rate ``POV``) and a permanent part:

        MI = b1 * I* * POV**a4 + (1 - b1) * I*

    where ``I*`` is from :func:`istar_impact`.  The first term is the temporary
    cost a trader can reduce by trading more passively (lower POV); the second is
    the permanent displacement that is paid regardless of trading speed.

    Units
    -----
    The returned value is a decimal fraction of the arrival price.  Because
    ``I*`` is in the basis-point units implied by ``a1``, the result is divided
    by ``10_000`` to convert basis points to a decimal fraction.

    Parameters
    ----------
    order_fraction:
        Order size as a fraction of ADV, ``Q / ADV``.
    sigma:
        Per-period return volatility as a decimal fraction.
    pov:
        Percentage-of-volume execution rate in ``[0, 1]`` (e.g. ``0.10`` = trade
        at 10 percent of market volume).  Must be ``>= 0``.
    params:
        Model coefficients.

    Returns
    -------
    float
        Market-impact cost as a non-negative decimal fraction of arrival price.

    Raises
    ------
    ValueError
        If ``pov`` is negative.
    """
    if pov < 0:
        raise ValueError(f"pov must be non-negative; got {pov}")
    i_star_bps = istar_impact(order_fraction, sigma, params)
    temp = params.b1 * i_star_bps * float(pov ** params.a4)
    perm = (1.0 - params.b1) * i_star_bps
    return (temp + perm) / _BPS_PER_UNIT


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

_CAL_REQUIRED_COLUMNS = (
    "symbol",
    "side",
    "quantity",
    "adv",
    "sigma",
    "participation",
    "arrival_price",
    "avg_fill_price",
)


def calibrate_impact(
    fills: pd.DataFrame,
    *,
    default_eta: float = 0.1,
    default_beta: float = 0.5,
    min_obs: int = 5,
) -> CalibrationResult:
    """Calibrate the square-root impact law to a trader's own fills.

    The square-root temporary-impact law in log space is

        log|slippage| = log(eta) + beta * log(participation) + log(sigma)

    so subtracting ``log(sigma)`` linearises the relation to

        y = log|slippage| - log(sigma) = log(eta) + beta * log(participation).

    An ordinary least-squares fit of ``y`` on ``log(participation)`` (via
    :func:`numpy.linalg.lstsq`) recovers ``beta`` (slope) and ``log(eta)``
    (intercept).  The fit is fully deterministic and never raises on degenerate
    input; instead ``well_determined`` is set ``False`` and the defaults are
    returned.

    Required columns
    ----------------
    The ``fills`` DataFrame must contain:

    * ``symbol`` -- instrument identifier (unused by the fit but documented for
      provenance).
    * ``side`` -- ``"buy"`` / ``"sell"`` (or ``+1`` / ``-1``); used to sign the
      realised slippage so that a positive value is a cost.
    * ``quantity`` -- absolute shares filled (unused directly; provenance).
    * ``adv`` -- average daily volume (provenance).
    * ``sigma`` -- per-fill return volatility (decimal fraction).
    * ``participation`` -- realised participation rate ``v / V`` for the fill.
    * ``arrival_price`` -- decision/arrival price.
    * ``avg_fill_price`` -- realised volume-weighted average fill price.

    The realised slippage fraction is computed as

        slippage = side_sign * (avg_fill_price - arrival_price) / arrival_price

    where ``side_sign`` is ``+1`` for buys and ``-1`` for sells, so that paying
    *above* arrival on a buy (or *below* on a sell) yields a **positive** cost,
    consistent with the repo positive-loss convention.  Only rows with strictly
    positive ``participation``, ``sigma``, ``arrival_price`` and *positive*
    slippage (adverse fills) enter the log-linear fit.

    Parameters
    ----------
    fills:
        DataFrame of historical fills (see required columns above).
    default_eta:
        Fallback temporary-impact coefficient when the fit is not well
        determined.
    default_beta:
        Fallback participation exponent when the fit is not well determined.
    min_obs:
        Minimum number of usable observations required to attempt the fit.

    Returns
    -------
    CalibrationResult
        Fitted ``eta`` and ``beta`` with ``r_squared``, ``n_obs`` and a
        ``well_determined`` flag.  When ``well_determined`` is ``False`` the
        ``eta`` / ``beta`` fields equal the supplied defaults.

    Notes
    -----
    Calibration is intended to be run monthly on the prior month's fills.  The
    routine is pure and deterministic: identical input always yields identical
    output.
    """
    missing = [c for c in _CAL_REQUIRED_COLUMNS if c not in fills.columns]
    if missing:
        raise ValueError(
            f"fills is missing required columns: {sorted(missing)}"
        )

    if fills.shape[0] == 0:
        return CalibrationResult(
            eta=default_eta,
            beta=default_beta,
            r_squared=0.0,
            n_obs=0,
            well_determined=False,
        )

    arrival = fills["arrival_price"].to_numpy(dtype=float)
    avg_fill = fills["avg_fill_price"].to_numpy(dtype=float)
    participation = fills["participation"].to_numpy(dtype=float)
    sigma = fills["sigma"].to_numpy(dtype=float)

    side_raw = fills["side"].to_numpy()
    side_sign = _side_to_sign(side_raw)

    # Guard against division by zero before computing slippage.
    safe_arrival = np.where(arrival > 0.0, arrival, np.nan)
    slippage = side_sign * (avg_fill - safe_arrival) / safe_arrival

    valid = (
        np.isfinite(slippage)
        & np.isfinite(participation)
        & np.isfinite(sigma)
        & (participation > 0.0)
        & (sigma > 0.0)
        & (slippage > 0.0)
    )
    n_obs = int(np.count_nonzero(valid))
    if n_obs < min_obs:
        return CalibrationResult(
            eta=default_eta,
            beta=default_beta,
            r_squared=0.0,
            n_obs=n_obs,
            well_determined=False,
        )

    log_part = np.log(participation[valid])
    y = np.log(slippage[valid]) - np.log(sigma[valid])

    # Need variation in the regressor to identify the slope.
    if float(np.ptp(log_part)) <= 0.0:
        return CalibrationResult(
            eta=default_eta,
            beta=default_beta,
            r_squared=0.0,
            n_obs=n_obs,
            well_determined=False,
        )

    design = np.column_stack([np.ones_like(log_part), log_part])
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(design, y, rcond=None)
    intercept, slope = float(coeffs[0]), float(coeffs[1])

    # Goodness of fit.
    y_hat = design @ coeffs
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 0.0 if ss_tot <= 0.0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))

    eta = math.exp(intercept)
    # A negative or zero slope is not a valid square-root-type law; flag it.
    well_determined = slope > 0.0 and math.isfinite(eta) and eta > 0.0
    if not well_determined:
        return CalibrationResult(
            eta=default_eta,
            beta=default_beta,
            r_squared=r_squared,
            n_obs=n_obs,
            well_determined=False,
        )

    return CalibrationResult(
        eta=eta,
        beta=slope,
        r_squared=r_squared,
        n_obs=n_obs,
        well_determined=True,
    )


def _side_to_sign(side_raw: np.ndarray) -> np.ndarray:
    """Map a fills ``side`` column to ``+1`` (buy) / ``-1`` (sell) signs.

    Accepts string labels (``"buy"`` / ``"sell"``, case-insensitive) or numeric
    values (positive -> buy, negative -> sell).  Unrecognised entries map to
    ``+1`` (buy) so the routine never raises on malformed side labels.
    """
    signs = np.ones(side_raw.shape[0], dtype=float)
    for i, raw in enumerate(side_raw):
        if isinstance(raw, str):
            signs[i] = -1.0 if raw.strip().lower().startswith("s") else 1.0
        else:
            try:
                signs[i] = -1.0 if float(raw) < 0 else 1.0
            except (TypeError, ValueError):
                signs[i] = 1.0
    return signs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def expected_cost_bps(cost_fraction: float) -> float:
    """Convert a decimal-fraction cost to basis points.

    Parameters
    ----------
    cost_fraction:
        Cost expressed as a decimal fraction of the arrival price (the unit
        returned by every cost function in this module).

    Returns
    -------
    float
        The same cost expressed in basis points (``cost_fraction * 10_000``).
    """
    return cost_fraction * _BPS_PER_UNIT
