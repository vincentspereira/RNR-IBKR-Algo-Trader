"""Leverage management and dynamic de-levering (master plan Phase 8.2).

This module sits one layer above :mod:`core_trading.money.sizing`: once each
position has been sized, the book as a whole must respect leverage limits and
react to adverse regimes by reducing exposure.  Two concerns are handled:

1. **Static limits** (:func:`apply_leverage_limits`) -- enforce a maximum gross
   exposure (sum of absolute weights), a maximum net exposure (absolute value
   of the signed sum), and optional per-asset-class gross caps.  Each binding
   limit triggers a *proportional* scale-down so relative position sizes are
   preserved.

2. **Dynamic de-levering** (:func:`dynamic_delever_factor`) -- compute a
   multiplicative exposure factor in ``(0, 1]`` that shrinks the book when the
   strategy is in drawdown and/or a high-volatility regime, in the spirit of
   the portfolio circuit breakers in :mod:`core_trading.risk.circuit_breakers`.
   :func:`apply_dynamic_delever` applies that factor to a weight book.

Conventions
-----------
* **Gross exposure** = ``sum(|w_i|)``.
* **Net exposure**   = ``|sum(w_i)|``.
* **Drawdown** follows the Phase 7 *positive-loss* convention: ``0.12`` means
  the equity curve is 12% below its high-water mark (a larger number is worse).

All routines are pure NumPy/pandas -- no external optimisation libraries.

References
----------
* Jacobs & Levy (2013), *Leverage Aversion and Portfolio Optimality*.
* Market-wide circuit-breaker philosophy: NYSE Rule 80B; mirrored at strategy
  scope in :mod:`core_trading.risk.circuit_breakers`.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "LeverageConfig",
    "LeverageReport",
    "apply_leverage_limits",
    "dynamic_delever_factor",
    "apply_dynamic_delever",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeverageConfig:
    """Immutable configuration for the leverage-management routines.

    Attributes
    ----------
    max_gross:
        Maximum permitted gross exposure ``sum(|w_i|)`` (must be positive).
        Default ``2.0`` (200% gross, i.e. up to 2x levered).
    max_net:
        Maximum permitted net exposure ``|sum(w_i)|`` (must be positive).
        Default ``1.0`` (100% net, i.e. fully invested with no net leverage).
    asset_class_caps:
        Optional mapping of asset-class label to a maximum gross exposure for
        the members of that class (each cap must be positive).  Classes absent
        from the mapping are unconstrained at class level.  Default: empty.
    drawdown_delever_threshold:
        Drawdown (positive-loss convention) at or above which the
        drawdown de-lever factor is applied.  In ``[0, 1]``.  Default ``0.10``.
    drawdown_delever_factor:
        Multiplicative exposure factor applied when the drawdown threshold is
        breached, in ``(0, 1]``.  Default ``0.5`` (halve exposure).
    high_vol_delever_factor:
        Multiplicative exposure factor applied when a high-volatility regime is
        flagged, in ``(0, 1]``.  Default ``0.5``.  Compounds with the drawdown
        factor when both conditions hold.
    """

    max_gross: float = 2.0
    max_net: float = 1.0
    asset_class_caps: Mapping[str, float] = field(default_factory=dict)
    drawdown_delever_threshold: float = 0.10
    drawdown_delever_factor: float = 0.5
    high_vol_delever_factor: float = 0.5

    def __post_init__(self) -> None:
        if self.max_gross <= 0:
            raise ValueError(f"max_gross must be positive; got {self.max_gross}")
        if self.max_net <= 0:
            raise ValueError(f"max_net must be positive; got {self.max_net}")
        for cls, cap in self.asset_class_caps.items():
            if cap <= 0:
                raise ValueError(
                    f"asset_class cap for {cls!r} must be positive; got {cap}"
                )
        if not (0 <= self.drawdown_delever_threshold <= 1):
            raise ValueError(
                "drawdown_delever_threshold must be in [0, 1]; got "
                f"{self.drawdown_delever_threshold}"
            )
        if not (0 < self.drawdown_delever_factor <= 1):
            raise ValueError(
                "drawdown_delever_factor must be in (0, 1]; got "
                f"{self.drawdown_delever_factor}"
            )
        if not (0 < self.high_vol_delever_factor <= 1):
            raise ValueError(
                "high_vol_delever_factor must be in (0, 1]; got "
                f"{self.high_vol_delever_factor}"
            )


# Module-level singleton default so that ruff B008 (no function call in argument
# defaults) is satisfied without rebuilding the config on every call.
_DEFAULT_LEVERAGE_CONFIG = LeverageConfig()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeverageReport:
    """Outcome of :func:`apply_leverage_limits`.

    Attributes
    ----------
    weights:
        The scaled weight book after all limits have been enforced.
    gross_before:
        Gross exposure ``sum(|w_i|)`` of the input book.
    gross_after:
        Gross exposure of the scaled book.
    net_before:
        Net exposure ``|sum(w_i)|`` of the input book.
    net_after:
        Net exposure of the scaled book.
    binding_constraints:
        Ordered list of the constraints that bound (triggered a scale-down).
        Possible members: ``"gross"``, ``"net"``, and ``"asset_class:<label>"``
        for each per-class cap that bound.  Empty when nothing bound.
    scale_factors:
        Mapping describing each applied scale factor.  Keys mirror
        ``binding_constraints`` (``"gross"``, ``"net"``,
        ``"asset_class:<label>"``); each value is the multiplicative factor in
        ``(0, 1)`` that was applied for that constraint.
    """

    weights: Mapping[str, float]
    gross_before: float
    gross_after: float
    net_before: float
    net_after: float
    binding_constraints: list[str]
    scale_factors: Mapping[str, float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gross(weights: Mapping[str, float]) -> float:
    """Return gross exposure sum(|w_i|)."""
    return sum(abs(v) for v in weights.values())


def _net(weights: Mapping[str, float]) -> float:
    """Return net exposure |sum(w_i)|."""
    return abs(sum(weights.values()))


# ---------------------------------------------------------------------------
# Static leverage limits
# ---------------------------------------------------------------------------


def apply_leverage_limits(
    weights: Mapping[str, float],
    *,
    config: LeverageConfig = _DEFAULT_LEVERAGE_CONFIG,
    asset_class_map: Mapping[str, str] | None = None,
) -> LeverageReport:
    """Enforce gross, net, and per-asset-class gross leverage limits.

    The limits are applied in a fixed order so the result is deterministic:

    1. **Gross cap** -- if ``sum(|w_i|) > max_gross`` the *entire* book is
       scaled by ``max_gross / gross`` (proportional whole-book scale-down,
       preserving every relative position size).
    2. **Net cap** -- if ``|sum(w_i)| > max_net`` the *entire* book is scaled by
       ``max_net / net``.  We deliberately choose the simpler **proportional
       whole-book** scale rather than scaling only the dominant side: a
       whole-book scale keeps the long/short ratio and every relative size
       intact, which is the least surprising behaviour for a sizing layer that
       has already chosen those ratios.  (Scaling only the dominant side would
       silently change the book's long/short balance.)
    3. **Per-asset-class gross caps** -- for each class whose members' gross
       exposure exceeds its cap, only the *members of that class* are scaled by
       ``cap / class_gross``.  Classes are processed in sorted label order for
       determinism.

    Because each step only ever *reduces* exposure, the order above cannot
    cause an earlier-satisfied constraint to be re-violated by a later step
    (a class-level scale-down can only lower gross and net).

    Parameters
    ----------
    weights:
        Mapping of identifier to signed weight (fraction of NAV).  Positive is
        long, negative is short.
    config:
        Leverage limits to enforce.
    asset_class_map:
        Optional mapping of identifier to asset-class label.  Required only if
        ``config.asset_class_caps`` is non-empty; identifiers absent from the
        map are treated as belonging to no capped class.

    Returns
    -------
    LeverageReport
        The scaled book plus before/after exposures, the binding-constraint
        list, and the applied scale factors.
    """
    scaled: dict[str, float] = dict(weights)
    gross_before = _gross(scaled)
    net_before = _net(scaled)

    binding: list[str] = []
    factors: dict[str, float] = {}

    # 1. Gross cap (whole-book proportional scale-down).
    gross = _gross(scaled)
    if gross > config.max_gross and gross > 0.0:
        factor = config.max_gross / gross
        scaled = {k: v * factor for k, v in scaled.items()}
        binding.append("gross")
        factors["gross"] = factor

    # 2. Net cap (whole-book proportional scale-down of the documented choice).
    net = _net(scaled)
    if net > config.max_net and net > 0.0:
        factor = config.max_net / net
        scaled = {k: v * factor for k, v in scaled.items()}
        binding.append("net")
        factors["net"] = factor

    # 3. Per-asset-class gross caps (scale only the offending class members).
    if config.asset_class_caps:
        class_map = asset_class_map or {}
        for cls in sorted(config.asset_class_caps):
            cap = config.asset_class_caps[cls]
            members = [k for k in scaled if class_map.get(k) == cls]
            if not members:
                continue
            class_gross = sum(abs(scaled[k]) for k in members)
            if class_gross > cap and class_gross > 0.0:
                factor = cap / class_gross
                for k in members:
                    scaled[k] = scaled[k] * factor
                label = f"asset_class:{cls}"
                binding.append(label)
                factors[label] = factor

    return LeverageReport(
        weights=scaled,
        gross_before=gross_before,
        gross_after=_gross(scaled),
        net_before=net_before,
        net_after=_net(scaled),
        binding_constraints=binding,
        scale_factors=factors,
    )


# ---------------------------------------------------------------------------
# Dynamic de-levering
# ---------------------------------------------------------------------------


def dynamic_delever_factor(
    *,
    current_drawdown: float,
    vol_regime_high: bool,
    config: LeverageConfig = _DEFAULT_LEVERAGE_CONFIG,
) -> float:
    """Return a multiplicative exposure factor in ``(0, 1]`` for de-levering.

    Two independent triggers each shrink exposure; they **compound** when both
    fire:

    * **Drawdown trigger** -- when ``current_drawdown >= drawdown_delever_threshold``
      the factor is multiplied by ``config.drawdown_delever_factor``.
    * **High-vol trigger** -- when ``vol_regime_high`` is true the factor is
      multiplied by ``config.high_vol_delever_factor``.

    With both triggers active the factor is the product of the two, e.g. with
    the defaults (0.5 and 0.5) a strategy that is both in drawdown and in a
    high-vol regime runs at ``0.25`` of its sized exposure.

    Drawdown uses the **positive-loss convention** (``0.12`` == 12% below the
    high-water mark), matching the Phase 7 risk modules.  A negative drawdown
    is rejected because it is meaningless under that convention.

    Parameters
    ----------
    current_drawdown:
        Current drawdown as a non-negative fraction (positive-loss convention).
    vol_regime_high:
        Whether the current volatility regime is classified as high.
    config:
        Source of the threshold and the two de-lever factors.

    Returns
    -------
    float
        Exposure multiplier in ``(0, 1]``.  ``1.0`` when neither trigger fires.

    Raises
    ------
    ValueError
        If ``current_drawdown`` is negative.
    """
    if current_drawdown < 0:
        raise ValueError(
            "current_drawdown must be non-negative (positive-loss convention); "
            f"got {current_drawdown}"
        )
    factor = 1.0
    if current_drawdown >= config.drawdown_delever_threshold:
        factor *= config.drawdown_delever_factor
    if vol_regime_high:
        factor *= config.high_vol_delever_factor
    return factor


def apply_dynamic_delever(
    weights: Mapping[str, float],
    factor: float,
) -> dict[str, float]:
    """Scale every weight by a de-lever ``factor``.

    Convenience companion to :func:`dynamic_delever_factor`: multiply a sized
    weight book by the exposure multiplier it returns.

    Parameters
    ----------
    weights:
        Mapping of identifier to signed weight.
    factor:
        Exposure multiplier, expected in ``(0, 1]`` (typically the output of
        :func:`dynamic_delever_factor`).  Must be non-negative.

    Returns
    -------
    dict[str, float]
        New mapping with every weight multiplied by ``factor``.

    Raises
    ------
    ValueError
        If ``factor`` is negative.
    """
    if factor < 0:
        raise ValueError(f"factor must be non-negative; got {factor}")
    return {k: v * factor for k, v in weights.items()}
