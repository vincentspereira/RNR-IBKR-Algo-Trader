"""Position-sizing toolkit (master plan Phase 4.4).

Implements three complementary sizing rules that are each computed independently
and then combined by taking the *most conservative* (smallest) magnitude:

1. Fractional Kelly -- based on expected edge and per-period volatility.
2. Volatility targeting -- scales exposure so realised annualised vol equals
   a target, independent of the Kelly estimate.
3. Per-position cap -- hard upper bound as a fraction of portfolio NAV.

The combination gives:

    final_magnitude = min(|kelly|, vol_target, per_position_cap)

Direction (long/short) is supplied by the caller (the trading signal), not
inferred from the Kelly sign, because the signal layer owns conviction while
this layer owns *how much*.

Phase 8.1 adds four further standalone sizing rules that map a trade idea to a
concrete share/unit count or weight without the three-way Kelly/vol/cap blend:

4. Fixed-fractional risk -- risk a fixed fraction of NAV per trade based on the
   entry-to-stop distance (the classic stop-loss money-management rule).
5. Fixed-dollar -- allocate a fixed dollar amount per trade.
6. Naive risk parity -- inverse-volatility weights normalised to a total risk
   budget (a covariance-free sizing heuristic; the full covariance-based
   optimiser lives in :mod:`core_trading.portfolio.risk_parity`).
7. Optimal f -- Ralph Vince's terminal-wealth-maximising fixed fraction.

All routines are pure NumPy/pandas -- no external optimisation libraries.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

__all__ = [
    "SizingConfig",
    "PositionSize",
    "fractional_kelly",
    "vol_target_weight",
    "size_position",
    "scale_to_budget",
    "fixed_fractional",
    "fixed_dollar",
    "risk_parity_size",
    "optimal_f",
]


# ---------------------------------------------------------------------------
# Configuration and result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SizingConfig:
    """Immutable configuration for :func:`size_position`.

    Attributes
    ----------
    kelly_fraction:
        Fraction of full Kelly to use, in ``(0, 1]``.  A value of ``0.25``
        (quarter-Kelly) is the standard conservative choice; it cuts the
        optimal Kelly bet by 75 %, substantially reducing drawdown variance.
    target_vol:
        Target *annualised* volatility per position, expressed as a decimal
        fraction of portfolio NAV (e.g. ``0.10`` = 10 %).
    per_position_cap:
        Hard maximum absolute weight per pair as a fraction of NAV,
        in ``(0, 1]``.
    periods_per_year:
        Number of trading periods per year used for annualisation (252 for
        daily, 52 for weekly, etc.).
    max_leverage:
        Ceiling applied to the raw Kelly weight and vol-target weight before
        the three-way minimum is taken.  Provides a sanity backstop against
        extreme parameter estimates.
    """

    kelly_fraction: float = 0.25
    target_vol: float = 0.10
    per_position_cap: float = 0.02
    periods_per_year: int = 252
    max_leverage: float = 1.0

    def __post_init__(self) -> None:
        if not (0 < self.kelly_fraction <= 1):
            raise ValueError(
                f"kelly_fraction must be in (0, 1]; got {self.kelly_fraction}"
            )
        if self.target_vol <= 0:
            raise ValueError(f"target_vol must be positive; got {self.target_vol}")
        if not (0 < self.per_position_cap <= 1):
            raise ValueError(
                f"per_position_cap must be in (0, 1]; got {self.per_position_cap}"
            )
        if self.periods_per_year <= 0:
            raise ValueError(
                f"periods_per_year must be positive; got {self.periods_per_year}"
            )


@dataclass(frozen=True, slots=True)
class PositionSize:
    """Outcome of :func:`size_position`.

    Attributes
    ----------
    weight:
        Final signed position weight after all caps are applied.  Positive
        means long, negative means short.
    kelly_weight:
        Raw fractional-Kelly weight *before* the three-way minimum, signed
        by ``direction``.  Useful for diagnostics.
    vol_target_weight:
        Unsigned magnitude from the vol-targeting rule *before* the three-way
        minimum.  Useful for diagnostics.
    binding_constraint:
        Which rule determined the final magnitude:
        ``"kelly"``, ``"vol_target"``, ``"per_position_cap"``, or ``"none"``
        (when ``direction == 0``).
    """

    weight: float
    kelly_weight: float
    vol_target_weight: float
    binding_constraint: str


# Module-level singleton used as the default for size_position so that ruff B008
# (no function calls in argument defaults) is satisfied without recomputing the
# config object on every call.
_DEFAULT_SIZING_CONFIG = SizingConfig()


# ---------------------------------------------------------------------------
# Public sizing primitives
# ---------------------------------------------------------------------------


def fractional_kelly(
    mu: float,
    sigma: float,
    *,
    kelly_fraction: float = 0.25,
) -> float:
    """Return the fractional-Kelly optimal weight for a Gaussian return stream.

    Derivation
    ----------
    Under continuously-compounded, i.i.d. Gaussian returns with per-period
    mean ``mu`` and standard deviation ``sigma``, the full-Kelly fraction that
    maximises the expected log-growth of wealth is:

        f* = mu / sigma**2

    This is the continuous analogue of the discrete Kelly formula
    ``f* = (p*(b+1) - 1) / b`` specialised to a normal distribution.
    The fractional version is simply:

        f = kelly_fraction * f*

    Quarter-Kelly (``kelly_fraction = 0.25``) is the conventional conservative
    choice: the growth rate is approximately 94 % of the Kelly optimum while
    drawdowns are roughly halved.  See Thorp (1997), *The Kelly Criterion in
    Blackjack, Sports Betting and the Stock Market*.

    Parameters
    ----------
    mu:
        Expected per-period return (arithmetic mean of log-returns).
    sigma:
        Per-period return standard deviation.  Values ``<= 0`` yield ``0.0``.
    kelly_fraction:
        Fraction of full Kelly to apply, in ``(0, 1]``.

    Returns
    -------
    float
        Signed fractional-Kelly weight (can exceed 1.0 if ``mu`` is large
        relative to ``sigma``; callers should clip to ``max_leverage``).
    """
    if sigma <= 0:
        return 0.0
    full_kelly = mu / (sigma ** 2)
    return kelly_fraction * full_kelly


def vol_target_weight(
    returns: Sequence[float] | pd.Series,
    *,
    target_vol: float = 0.10,
    periods_per_year: int = 252,
) -> float:
    """Return the unsigned weight that targets a given annualised volatility.

    The position weight is chosen so that, if realised volatility equals the
    historical estimate, the resulting annualised portfolio volatility
    contribution from this position equals ``target_vol``:

        weight = target_vol / realised_annualised_vol(returns)

    where:

        realised_annualised_vol = std(returns, ddof=1) * sqrt(periods_per_year)

    This is the core of the *constant-volatility* or *risk-parity* sizing
    approach.  See Hurst, Ooi, Pedersen (2013), *Demystifying Managed Futures*.

    Parameters
    ----------
    returns:
        Sequence of per-period returns (e.g. daily log-returns or P&L).
        NaN and Inf are excluded before estimation.
    target_vol:
        Target annualised volatility as a decimal fraction.
    periods_per_year:
        Number of periods per year for annualisation.

    Returns
    -------
    float
        Unsigned position weight (magnitude only; sign comes from the signal).
        Returns ``0.0`` when fewer than 2 finite observations exist or
        realised vol is zero.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    if finite.size < 2:
        return 0.0
    per_period_vol = float(np.std(finite, ddof=1))
    if per_period_vol == 0.0:
        return 0.0
    annualised_vol = per_period_vol * math.sqrt(periods_per_year)
    return target_vol / annualised_vol


def size_position(
    *,
    direction: int,
    mu: float,
    sigma: float,
    returns: Sequence[float] | pd.Series,
    config: SizingConfig = _DEFAULT_SIZING_CONFIG,
) -> PositionSize:
    """Combine Kelly, vol-target, and cap rules into a final position weight.

    Algorithm
    ---------
    1. Compute ``kelly_raw = fractional_kelly(mu, sigma, kelly_fraction)``,
       clipped to ``[-max_leverage, max_leverage]``.
    2. Compute ``vt_mag = vol_target_weight(returns, ...)``,
       clipped to ``[0, max_leverage]``.
    3. Three-way minimum of magnitudes:

           final_mag = min(|kelly_raw|, vt_mag, per_position_cap)

       The binding constraint is whichever rule produced the minimum.
    4. ``weight = direction * final_mag``.

    ``direction`` must be in ``{-1, 0, +1}``.  When ``direction == 0`` the
    weight is 0 and ``binding_constraint`` is ``"none"``.

    Parameters
    ----------
    direction:
        Trade direction: ``+1`` for long, ``-1`` for short, ``0`` for flat.
    mu:
        Expected per-period return passed to :func:`fractional_kelly`.
    sigma:
        Per-period return standard deviation passed to :func:`fractional_kelly`.
    returns:
        Historical returns passed to :func:`vol_target_weight`.
    config:
        Sizing parameters.

    Returns
    -------
    PositionSize
        Dataclass with the final weight and diagnostic fields.
    """
    if direction not in {-1, 0, 1}:
        raise ValueError(f"direction must be -1, 0, or +1; got {direction}")

    kelly_raw = fractional_kelly(mu, sigma, kelly_fraction=config.kelly_fraction)
    kelly_raw = float(np.clip(kelly_raw, -config.max_leverage, config.max_leverage))

    vt_mag = vol_target_weight(
        returns,
        target_vol=config.target_vol,
        periods_per_year=config.periods_per_year,
    )
    vt_mag = float(np.clip(vt_mag, 0.0, config.max_leverage))

    # diagnostic: signed kelly weight (direction applied to raw magnitude)
    kelly_signed = direction * abs(kelly_raw)

    if direction == 0:
        return PositionSize(
            weight=0.0,
            kelly_weight=0.0,
            vol_target_weight=0.0,
            binding_constraint="none",
        )

    kelly_mag = abs(kelly_raw)
    cap = config.per_position_cap

    final_mag = min(kelly_mag, vt_mag, cap)

    # Determine which constraint was binding (first minimum wins).
    if final_mag == cap:
        binding = "per_position_cap"
    elif final_mag == vt_mag:
        binding = "vol_target"
    else:
        binding = "kelly"

    return PositionSize(
        weight=direction * final_mag,
        kelly_weight=float(kelly_signed),
        vol_target_weight=float(vt_mag),
        binding_constraint=binding,
    )


def scale_to_budget(
    weights: Mapping[str, float],
    *,
    gross_budget: float,
) -> dict[str, float]:
    """Scale a set of position weights so gross exposure does not exceed a budget.

    If the sum of absolute weights already satisfies the budget, the weights
    are returned unchanged.  Otherwise all weights are scaled proportionally
    so that ``sum(|w|) == gross_budget``.

    This is a portfolio-level money-management primitive: it allows individual
    pair weights to be sized independently and then normalised to respect a
    total gross-leverage constraint before order submission.

    Parameters
    ----------
    weights:
        Mapping of identifier to signed weight.
    gross_budget:
        Maximum permitted gross exposure (sum of absolute weights).

    Returns
    -------
    dict[str, float]
        Scaled weights preserving signs and relative magnitudes.
    """
    if gross_budget <= 0:
        raise ValueError(f"gross_budget must be positive; got {gross_budget}")
    if not weights:
        return {}
    gross = sum(abs(v) for v in weights.values())
    if gross <= gross_budget or gross == 0.0:
        return dict(weights)
    scale = gross_budget / gross
    return {k: v * scale for k, v in weights.items()}


# ---------------------------------------------------------------------------
# Phase 8.1 standalone sizing rules
# ---------------------------------------------------------------------------


def fixed_fractional(
    nav: float,
    risk_fraction: float,
    entry_price: float,
    stop_price: float,
) -> float:
    """Return the position size that risks a fixed fraction of NAV per trade.

    This is the classic stop-based money-management rule (sometimes called the
    *percent-risk* or *fixed-fractional* model; see Tharp (2008), *Trade Your
    Way to Financial Freedom*, ch. 14).  The dollar amount put at risk is

        risk_dollars = nav * risk_fraction

    and the per-unit risk is the distance from entry to the protective stop

        per_unit_risk = abs(entry_price - stop_price)

    so the number of units to trade is

        units = risk_dollars / per_unit_risk

    Unit convention
    ---------------
    The return value is an **unsigned position size in shares/units** (not a
    weight).  Direction (long vs short) is owned by the signal layer, exactly
    as in :func:`size_position`; the entry/stop ordering does not encode it.
    To convert to a fraction-of-NAV weight, multiply by ``entry_price`` and
    divide by ``nav``::

        weight = units * entry_price / nav

    Parameters
    ----------
    nav:
        Portfolio net asset value (must be positive).
    risk_fraction:
        Fraction of NAV to risk on the trade, in ``(0, 1]`` (e.g. ``0.01`` for
        the conventional 1%-risk rule).
    entry_price:
        Anticipated entry price (must be positive).
    stop_price:
        Protective stop price.  Must differ from ``entry_price`` so the
        entry-to-stop distance is non-zero.

    Returns
    -------
    float
        Unsigned position size in shares/units.

    Raises
    ------
    ValueError
        If ``nav`` or ``entry_price`` is non-positive, ``risk_fraction`` is
        outside ``(0, 1]``, or ``entry_price == stop_price`` (zero stop
        distance, which would imply an infinite size).
    """
    if nav <= 0:
        raise ValueError(f"nav must be positive; got {nav}")
    if not (0 < risk_fraction <= 1):
        raise ValueError(
            f"risk_fraction must be in (0, 1]; got {risk_fraction}"
        )
    if entry_price <= 0:
        raise ValueError(f"entry_price must be positive; got {entry_price}")
    per_unit_risk = abs(entry_price - stop_price)
    if per_unit_risk == 0.0:
        raise ValueError(
            "entry_price and stop_price must differ (zero stop distance "
            "implies infinite size)"
        )
    risk_dollars = nav * risk_fraction
    return risk_dollars / per_unit_risk


def fixed_dollar(dollar_amount: float, price: float) -> float:
    """Return the number of units for a fixed dollar allocation per trade.

    The simplest possible sizing rule: allocate a constant cash amount to the
    trade regardless of volatility or edge::

        units = dollar_amount / price

    The result is an unsigned position size in shares/units; direction is
    supplied by the signal layer, as elsewhere in this module.

    Parameters
    ----------
    dollar_amount:
        Cash to allocate to the position (must be positive).
    price:
        Per-unit price (must be positive).

    Returns
    -------
    float
        Unsigned position size in shares/units.

    Raises
    ------
    ValueError
        If ``dollar_amount`` or ``price`` is non-positive.
    """
    if dollar_amount <= 0:
        raise ValueError(
            f"dollar_amount must be positive; got {dollar_amount}"
        )
    if price <= 0:
        raise ValueError(f"price must be positive; got {price}")
    return dollar_amount / price


def risk_parity_size(
    vol_estimates: Mapping[str, float],
    total_risk_budget: float,
) -> dict[str, float]:
    """Return naive (inverse-volatility) risk-parity weights for sizing.

    This is the *covariance-free* risk-parity heuristic: each position is
    sized inversely to its own standalone volatility so that, ignoring
    correlations, every position contributes an equal amount of risk.  Raw
    weights ``1 / vol_i`` are normalised so that the sum of risk contributions
    equals the requested budget::

        raw_i      = 1 / vol_i
        risk_i     = raw_i * vol_i = 1                  (constant per position)
        scale      = total_risk_budget / sum_j(raw_j * vol_j)
                   = total_risk_budget / N
        weight_i   = scale * raw_i

    so that ``sum_i (weight_i * vol_i) == total_risk_budget`` exactly.

    This is deliberately a *standalone sizing* heuristic.  The full
    covariance-based equal-risk-contribution optimiser (Spinu 2013;
    Griveau-Billion, Richard & Roncalli 2013) lives in
    :func:`core_trading.portfolio.risk_parity` and should be preferred when a
    covariance matrix is available; this function is for the common case where
    only per-asset volatilities are known.

    Parameters
    ----------
    vol_estimates:
        Mapping of identifier to a strictly positive volatility estimate (same
        units for every asset, e.g. annualised return standard deviation).
    total_risk_budget:
        Target total risk, i.e. the value of ``sum_i(weight_i * vol_i)`` after
        normalisation (must be positive).

    Returns
    -------
    dict[str, float]
        Mapping of identifier to its (positive) inverse-vol weight.  An empty
        input yields an empty mapping.

    Raises
    ------
    ValueError
        If ``total_risk_budget`` is non-positive or any volatility estimate is
        non-positive.
    """
    if total_risk_budget <= 0:
        raise ValueError(
            f"total_risk_budget must be positive; got {total_risk_budget}"
        )
    if not vol_estimates:
        return {}
    for key, vol in vol_estimates.items():
        if vol <= 0:
            raise ValueError(
                f"volatility estimate for {key!r} must be positive; got {vol}"
            )
    raw = {k: 1.0 / v for k, v in vol_estimates.items()}
    # sum of risk contributions of the raw (un-normalised) weights:
    # raw_i * vol_i == 1 for every asset, so this equals N.
    risk_sum = sum(raw[k] * vol_estimates[k] for k in vol_estimates)
    scale = total_risk_budget / risk_sum
    return {k: scale * raw[k] for k in raw}


def optimal_f(
    returns: Sequence[float] | pd.Series,
    *,
    max_f: float = 1.0,
    grid: int = 1000,
    fraction: float = 1.0,
) -> float:
    """Return Ralph Vince's Optimal f via a deterministic grid search.

    Optimal f is the fixed fraction of capital that maximises the terminal
    wealth relative (TWR) of a sequence of holding-period returns, where risk
    is normalised by the single largest losing trade.  Following Vince (1990),
    *Portfolio Management Formulas*, define the biggest loss

        biggest_loss = min_t(r_t)           (the most negative trade)

    which is negative whenever any losing trade exists.  For a candidate
    fraction ``f`` the holding-period return relative of trade ``t`` is

        HPR_t(f) = 1 + f * (-r_t / biggest_loss)

    so a winning trade (``r_t > 0``) gives ``HPR > 1`` and the worst losing
    trade gives exactly ``HPR = 1 - f`` (it reaches ``0`` at ``f = 1``).

    and the terminal wealth relative is the product over all trades

        TWR(f) = prod_t HPR_t(f).

    Optimal f is ``argmax_f TWR(f)`` searched over a uniform grid of ``grid``
    points in ``(0, max_f]``.  Because every HPR factor must stay positive,
    the natural upper bound on a usable ``f`` is 1 (at ``f = 1`` the
    worst-loss trade contributes exactly ``HPR = 0`` and bankrupts the
    account), which is why ``max_f`` defaults to 1.0.

    Undefined case
    --------------
    Optimal f is undefined when there are **no losing trades**: with
    ``biggest_loss >= 0`` the normalisation is ill-posed and any fraction
    increases wealth without bound.  In that case this function returns
    ``0.0`` (size nothing) rather than raising, so callers can treat "no
    losers in the sample" as "insufficient information to size".

    Fractional optimal f
    ---------------------
    Just as fractional Kelly scales the full-Kelly bet, the ``fraction``
    parameter scales the grid-optimal ``f`` (e.g. ``fraction=0.5`` for
    half-optimal-f), trading geometric growth for a smoother equity curve.

    Parameters
    ----------
    returns:
        Sequence of per-trade returns (decimal fractions; a 2% gain is
        ``0.02``).  NaN and Inf are excluded before the search.
    max_f:
        Upper bound of the search grid, in ``(0, 1]``.
    grid:
        Number of grid points across ``(0, max_f]`` (must be positive).  The
        grid is ``max_f * k / grid`` for ``k = 1 .. grid`` so the endpoint
        ``max_f`` is always evaluated and ``f = 0`` is excluded.
    fraction:
        Multiplier applied to the grid-optimal ``f``, in ``(0, 1]``.

    Returns
    -------
    float
        ``fraction * f_opt`` where ``f_opt`` maximises TWR on the grid; or
        ``0.0`` when no losing trades are present.

    Raises
    ------
    ValueError
        If ``max_f`` is outside ``(0, 1]``, ``grid`` is non-positive, or
        ``fraction`` is outside ``(0, 1]``.
    """
    if not (0 < max_f <= 1):
        raise ValueError(f"max_f must be in (0, 1]; got {max_f}")
    if grid <= 0:
        raise ValueError(f"grid must be positive; got {grid}")
    if not (0 < fraction <= 1):
        raise ValueError(f"fraction must be in (0, 1]; got {fraction}")

    arr = np.asarray(returns, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0

    biggest_loss = float(finite.min())
    if biggest_loss >= 0.0:
        # No losing trades -> Optimal f undefined; size nothing.
        return 0.0

    # Candidate fractions: max_f * k / grid for k = 1..grid (excludes 0,
    # includes max_f).  Shape (grid,).
    f_grid = max_f * (np.arange(1, grid + 1, dtype=float) / grid)
    # HPR matrix: rows = candidate f, cols = trades.  (grid, n_trades)
    # biggest_loss is negative, so a winning trade maps to a positive multiple.
    normalised = -finite / biggest_loss  # (n_trades,)
    hpr = 1.0 + np.outer(f_grid, normalised)
    # Guard against non-positive HPR (bankruptcy): such an f gives TWR <= 0,
    # which can never be the maximiser, so clip the product contribution.
    twr = np.prod(hpr, axis=1)
    best_idx = int(np.argmax(twr))
    f_opt = float(f_grid[best_idx])
    return fraction * f_opt
