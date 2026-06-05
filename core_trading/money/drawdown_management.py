"""Drawdown-based continuous de-risking (master plan Phase 8.4).

This module scales *gross exposure* continuously as a function of the live
equity drawdown.  It is the CONTINUOUS complement to the DISCRETE circuit
breakers in :mod:`core_trading.risk.circuit_breakers`:

* Circuit breakers (Phase 7.8) are a *state machine* -- they fire hard, sticky
  PAUSE / DERISK / HALT transitions at named thresholds and require explicit
  re-arm / cooldown / manual reset.  They answer "should we stop?".
* This module is a *smooth controller* -- it returns a single exposure
  multiplier in ``[0, 1]`` that steps down a ladder as the drawdown deepens,
  optionally halves on a volatility-of-volatility spike, and only restores to
  full size when equity prints a new high-water mark.  It answers "how much
  should we run *right now*?".

The two are designed to coexist: a caller multiplies its target gross exposure
by BOTH the breaker's de-risk factor (when DERISKED) and this module's
:func:`target_exposure`.  This module deliberately does NOT reimplement any
breaker state, sticky halts, or cooldown logic.

Sign convention
---------------
Drawdown uses the POSITIVE-loss convention, matching the Phase 7 risk layer and
:mod:`core_trading.risk.circuit_breakers`: a drawdown of ``0.12`` means equity
is 12% BELOW its running high-water mark.  Zero means at a new high.

Exposure ladder
---------------
A monotone step ladder maps drawdown depth to an exposure multiplier, e.g. the
default::

    drawdown < 0.05            -> 1.00  (full size)
    0.05 <= drawdown < 0.10    -> 0.75
    0.10 <= drawdown < 0.15    -> 0.50
    drawdown >= 0.15           -> 0.25

Deeper drawdown always means smaller (or equal) exposure -- enforced in
:meth:`DrawdownConfig.__post_init__`.

Volatility-of-volatility overlay
--------------------------------
When realised volatility is itself RISING *and* the drawdown is GROWING, the
regime is deteriorating faster than the ladder alone reflects, so exposure is
HALVED on top of the ladder.  This captures the empirical clustering of large
losses during volatility regime shifts (the "vol of vol" or "crisis" signal).

Re-leverage hysteresis
----------------------
Exposure is restored to full size ONLY once equity makes a NEW high-water mark
(touches or exceeds the prior peak).  Restoring as soon as the drawdown merely
shrinks would whipsaw leverage up and down through a choppy recovery, paying
the spread repeatedly and re-risking into a lower high.  Requiring a genuine
new high is a deliberate, conservative hysteresis band.

References
----------
* Grossman, S. & Zhou, Z. (1993). "Optimal Investment Strategies for
  Controlling Drawdowns." Mathematical Finance, 3(3).  (Exposure as a function
  of distance from the high-water mark.)
* Cont, R. (2001). "Empirical properties of asset returns: stylized facts and
  statistical issues." Quantitative Finance, 1(2).  (Volatility clustering ->
  the vol-of-vol overlay.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "DrawdownConfig",
    "compute_drawdown",
    "exposure_multiplier",
    "vol_of_vol_indicator",
    "releverage_allowed",
    "target_exposure",
    "DEFAULT_DRAWDOWN_CONFIG",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _default_ladder() -> dict[float, float]:
    """Return the default drawdown-depth -> exposure-multiplier ladder."""
    return {0.05: 0.75, 0.10: 0.50, 0.15: 0.25}


@dataclass(frozen=True, slots=True)
class DrawdownConfig:
    """Immutable configuration for continuous drawdown de-risking.

    Attributes
    ----------
    ladder:
        Mapping of drawdown DEPTH (positive fraction below high-water mark) to
        the exposure multiplier applied at or beyond that depth.  Depths above
        the smallest key but below it use full exposure (1.0).  Keys must be in
        ``(0, 1]`` and the mapping must be MONOTONE: a deeper key maps to a
        smaller-or-equal multiplier (validated).  Default
        ``{0.05: 0.75, 0.10: 0.50, 0.15: 0.25}``.
    vol_window:
        Rolling window (bars) for the realised-volatility estimate used by the
        vol-of-vol overlay.  Default 20.
    vol_of_vol_window:
        Number of trailing realised-vol observations compared to decide whether
        volatility is RISING.  The overlay compares the latest realised vol to
        the realised vol ``vol_of_vol_window`` bars earlier.  Default 5.
    halve_on_vol_of_vol:
        When ``True`` (default), a rising-vol + growing-drawdown regime halves
        the ladder multiplier.  Set ``False`` to disable the overlay.
    releverage_high_water_tol:
        Fractional tolerance for "new high": equity within this fraction of the
        running peak counts as a new high for re-leverage purposes, absorbing
        floating-point noise.  Default ``1e-9``.  Must be in ``[0, 1)``.
    vol_of_vol_halving_factor:
        Multiplier applied when the vol-of-vol overlay fires.  Default 0.5
        ("halve").  Must be in ``(0, 1)``.
    """

    ladder: dict[float, float] = field(default_factory=_default_ladder)
    vol_window: int = 20
    vol_of_vol_window: int = 5
    halve_on_vol_of_vol: bool = True
    releverage_high_water_tol: float = 1e-9
    vol_of_vol_halving_factor: float = 0.5

    def __post_init__(self) -> None:
        """Validate ladder monotonicity and window parameters."""
        if not self.ladder:
            raise ValueError("ladder must contain at least one threshold.")
        depths = sorted(self.ladder)
        for depth in depths:
            if not 0.0 < depth <= 1.0:
                raise ValueError(
                    f"ladder drawdown depths must be in (0, 1]; got {depth}"
                )
        for depth in depths:
            mult = self.ladder[depth]
            if not 0.0 <= mult <= 1.0:
                raise ValueError(
                    f"ladder multipliers must be in [0, 1]; got {mult} "
                    f"at depth {depth}"
                )
        # Monotone: deeper drawdown -> smaller-or-equal exposure.
        prev_mult = 1.0
        for depth in depths:
            mult = self.ladder[depth]
            if mult > prev_mult:
                raise ValueError(
                    "ladder must be monotone non-increasing in drawdown depth; "
                    f"multiplier {mult} at depth {depth} exceeds the "
                    f"shallower multiplier {prev_mult}"
                )
            prev_mult = mult
        if self.vol_window < 2:
            raise ValueError(f"vol_window must be >= 2; got {self.vol_window}")
        if self.vol_of_vol_window < 1:
            raise ValueError(
                f"vol_of_vol_window must be >= 1; got {self.vol_of_vol_window}"
            )
        if not 0.0 <= self.releverage_high_water_tol < 1.0:
            raise ValueError(
                f"releverage_high_water_tol must be in [0, 1); "
                f"got {self.releverage_high_water_tol}"
            )
        if not 0.0 < self.vol_of_vol_halving_factor < 1.0:
            raise ValueError(
                f"vol_of_vol_halving_factor must be in (0, 1); "
                f"got {self.vol_of_vol_halving_factor}"
            )


# Module-level singleton default (satisfies ruff B008 -- no call in defaults).
DEFAULT_DRAWDOWN_CONFIG = DrawdownConfig()


# ---------------------------------------------------------------------------
# Drawdown and ladder primitives
# ---------------------------------------------------------------------------


def compute_drawdown(equity_curve: pd.Series) -> pd.Series:
    """Return the positive drawdown series from the running high-water mark.

    Parameters
    ----------
    equity_curve:
        Strictly positive account-equity (or cumulative NAV) series, indexed
        in ascending time order.

    Returns
    -------
    pd.Series
        Drawdown at each bar as a POSITIVE fraction below the running peak:
        ``drawdown_t = 1 - equity_t / running_max(equity)_t``.  At a new high
        the value is exactly 0.0.  Same index as ``equity_curve``.

    Raises
    ------
    ValueError
        When the series is empty, contains non-finite values, or is not
        strictly positive.
    """
    if equity_curve.empty:
        raise ValueError("equity_curve must be non-empty.")
    values = equity_curve.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("equity_curve contains NaN or infinite values.")
    if (values <= 0.0).any():
        raise ValueError("equity_curve must be strictly positive.")
    running_max = np.maximum.accumulate(values)
    drawdown = 1.0 - values / running_max
    # Clip tiny negative noise from float division to exactly zero.
    drawdown = np.maximum(drawdown, 0.0)
    return pd.Series(drawdown, index=equity_curve.index)


def exposure_multiplier(
    current_drawdown: float,
    *,
    config: DrawdownConfig = DEFAULT_DRAWDOWN_CONFIG,
) -> float:
    """Look up the ladder exposure multiplier for a given drawdown depth.

    Parameters
    ----------
    current_drawdown:
        Drawdown depth as a POSITIVE fraction below the high-water mark
        (``0.12`` == 12% drawdown).  Negative values are treated as 0.
    config:
        Ladder configuration; defaults to :data:`DEFAULT_DRAWDOWN_CONFIG`.

    Returns
    -------
    float
        Exposure multiplier in ``[0, 1]``: 1.0 when shallower than the
        smallest ladder key, otherwise the multiplier of the DEEPEST ladder
        threshold the drawdown has reached.

    Raises
    ------
    ValueError
        When ``current_drawdown`` is not finite.
    """
    if not np.isfinite(current_drawdown):
        raise ValueError(
            f"current_drawdown must be finite; got {current_drawdown}"
        )
    depth = max(float(current_drawdown), 0.0)
    multiplier = 1.0
    for threshold in sorted(config.ladder):
        if depth >= threshold:
            multiplier = config.ladder[threshold]
        else:
            break
    return multiplier


# ---------------------------------------------------------------------------
# Volatility-of-volatility overlay
# ---------------------------------------------------------------------------


def vol_of_vol_indicator(
    returns: pd.Series,
    *,
    config: DrawdownConfig = DEFAULT_DRAWDOWN_CONFIG,
) -> bool:
    """Return True when realised vol is RISING and drawdown is GROWING.

    The indicator combines two trailing signals computed from the return
    series:

    1. *Rising vol*: the rolling realised volatility (window ``vol_window``)
       at the last bar exceeds the rolling realised volatility
       ``vol_of_vol_window`` bars earlier.
    2. *Growing drawdown*: the equity curve implied by ``cumprod(1 + returns)``
       is below its level ``vol_of_vol_window`` bars earlier (i.e. losing
       ground), which under the high-water-mark convention means the drawdown
       is widening over that window.

    Both must hold simultaneously.  When ``halve_on_vol_of_vol`` is ``False``
    the overlay is disabled and this always returns ``False``.

    Parameters
    ----------
    returns:
        Per-bar simple returns, ascending time order.  Non-finite values
        raise.
    config:
        Configuration; defaults to :data:`DEFAULT_DRAWDOWN_CONFIG`.

    Returns
    -------
    bool
        ``True`` when the deteriorating-regime condition holds at the last
        bar; ``False`` otherwise (including when there is insufficient
        history).

    Raises
    ------
    ValueError
        When ``returns`` contains non-finite values.
    """
    if not config.halve_on_vol_of_vol:
        return False
    if returns.empty:
        return False
    arr = returns.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("returns contains NaN or infinite values.")

    need = config.vol_window + config.vol_of_vol_window
    if arr.shape[0] < need:
        return False

    rolling_vol = (
        pd.Series(arr).rolling(window=config.vol_window).std(ddof=1).to_numpy()
    )
    # With ``arr.shape[0] >= need`` both indices fall on or after the first
    # fully-populated window (index ``vol_window - 1``), so both rolling-vol
    # values are finite by construction (a zero-variance window yields a finite
    # 0.0, not NaN).
    last_vol = rolling_vol[-1]
    prior_vol = rolling_vol[-1 - config.vol_of_vol_window]
    vol_rising = bool(last_vol > prior_vol)

    equity = np.cumprod(1.0 + arr)
    drawdown_growing = bool(equity[-1] < equity[-1 - config.vol_of_vol_window])
    return vol_rising and drawdown_growing


# ---------------------------------------------------------------------------
# Re-leverage hysteresis
# ---------------------------------------------------------------------------


def releverage_allowed(
    equity_curve: pd.Series,
    *,
    config: DrawdownConfig = DEFAULT_DRAWDOWN_CONFIG,
) -> bool:
    """Return True only when equity is at (or above) a new high-water mark.

    Hysteresis rationale: restoring full leverage the instant a drawdown
    shrinks would whipsaw exposure through a choppy recovery -- repeatedly
    re-risking into a lower high and paying transaction costs.  Requiring the
    equity to actually touch its prior peak (within
    ``releverage_high_water_tol``) before re-leveraging enforces a clean,
    one-way recovery gate.

    Parameters
    ----------
    equity_curve:
        Strictly positive equity series, ascending time order.
    config:
        Configuration; defaults to :data:`DEFAULT_DRAWDOWN_CONFIG`.

    Returns
    -------
    bool
        ``True`` when the latest equity is within ``releverage_high_water_tol``
        of (or above) the running peak -- i.e. drawdown is effectively zero.

    Raises
    ------
    ValueError
        When the curve is empty, non-finite, or non-positive (via
        :func:`compute_drawdown`).
    """
    drawdown = compute_drawdown(equity_curve)
    return bool(drawdown.iloc[-1] <= config.releverage_high_water_tol)


# ---------------------------------------------------------------------------
# Combined target exposure
# ---------------------------------------------------------------------------


def target_exposure(
    equity_curve: pd.Series,
    returns: pd.Series,
    *,
    config: DrawdownConfig = DEFAULT_DRAWDOWN_CONFIG,
) -> float:
    """Combine ladder, vol-of-vol overlay and hysteresis into one multiplier.

    Algorithm
    ---------
    1. ``dd = compute_drawdown(equity_curve).iloc[-1]`` (current depth).
    2. If :func:`releverage_allowed` (equity at a new high), return ``1.0`` --
       a genuine new high overrides everything and restores full size.
    3. Otherwise ``base = exposure_multiplier(dd, config=config)``.
    4. If :func:`vol_of_vol_indicator` fires, multiply ``base`` by
       ``vol_of_vol_halving_factor`` (default 0.5).
    5. Clip the result to ``[0, 1]`` and return it.

    Parameters
    ----------
    equity_curve:
        Strictly positive equity series, ascending time order.
    returns:
        Per-bar simple returns aligned to ``equity_curve`` (used only by the
        vol-of-vol overlay).
    config:
        Configuration; defaults to :data:`DEFAULT_DRAWDOWN_CONFIG`.

    Returns
    -------
    float
        Final exposure multiplier in ``[0, 1]`` to apply to target gross
        exposure at the latest bar.

    Raises
    ------
    ValueError
        Propagated from :func:`compute_drawdown` / :func:`vol_of_vol_indicator`
        on invalid inputs.
    """
    if releverage_allowed(equity_curve, config=config):
        return 1.0
    drawdown = compute_drawdown(equity_curve)
    current = float(drawdown.iloc[-1])
    base = exposure_multiplier(current, config=config)
    if vol_of_vol_indicator(returns, config=config):
        base *= config.vol_of_vol_halving_factor
    return float(min(max(base, 0.0), 1.0))
