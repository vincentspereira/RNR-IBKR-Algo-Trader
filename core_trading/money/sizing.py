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
