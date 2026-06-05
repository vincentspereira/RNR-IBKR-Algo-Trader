"""Live-vs-backtest (shadow) P&L divergence comparator (master plan Phase 10.3).

This module answers a single operational question: *is the live strategy
behaving like its backtested / shadow self, or has it silently drifted?*  A
sustained divergence between the realised live P&L and the P&L a shadow
(paper / replayed-backtest) book would have earned over the same period is one
of the earliest, cheapest signals that something is wrong -- a stale data feed,
a mis-wired cost model, a fat-finger sizing bug, or genuine alpha decay.

Scope and operator-gating
-------------------------
The live and shadow P&L feeds are *operator-gated*: wiring a real live account
and a parallel shadow book is a deployment concern handled outside this repo.
This module is therefore deliberately a **pure, deterministic comparator** --
the caller supplies two aligned daily-P&L series and this module performs the
alignment, the residual statistics, the alert decision and the ASCII report.
No clock, no filesystem, no network, no live-data source is touched.  This
mirrors the design of :mod:`core_trading.risk.daily_report` (a pure generator)
and the injectable-callback pattern used across the Phase 7 risk layer.

Residual and sign convention
-----------------------------
The *residual* on a given day is defined as::

    residual_t = live_pnl_t - shadow_pnl_t

so a **positive** residual means the live book *out-earned* the shadow book
that day, and a **negative** residual means the live book *under-earned*.  The
alert is two-sided: a large residual in EITHER direction is a divergence worth
investigating (out-performance can equally indicate a bug -- e.g. the shadow
book missing a fill the live book took).  This is the opposite polarity to the
risk layer's positive-loss convention; it is documented here precisely because
it differs, and the rendered report always spells out the direction.

Z-score and the no-self-contamination rule
-------------------------------------------
The alert statistic is a z-score of the latest residual against the rolling
standard deviation of the trailing residual window.  Critically, the trailing
window used to estimate the residual std **excludes today's residual**:

* The std is computed over the ``window`` residuals immediately *preceding*
  the latest one (residuals ``[-window-1 : -1]`` in series order).
* Today's residual is the value being *tested*; including it in its own
  dispersion estimate would shrink the z-score exactly when the residual is
  most extreme (self-contamination), masking the very spikes the monitor
  exists to catch.

The z-score is then ``z = latest_residual / trailing_std``.  The alert fires
when ``abs(z) > threshold`` (a strict inequality -- the boundary value
``abs(z) == threshold`` does NOT fire; this boundary is pinned by tests).

Insufficient history
--------------------
A meaningful trailing std needs at least ``window`` preceding residuals (plus
the one being tested), and the config's ``min_history`` provides a floor.  When
the aligned residual series is too short the verdict carries
``state = "INSUFFICIENT_HISTORY"``, ``alert = False`` and ``NaN`` statistics --
the monitor stays silent rather than firing on noise.

References
----------
* Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 11
  (backtest overfitting / live-vs-backtest performance decay).
* The "shadow trading" / parallel-paper-book pattern used by execution desks to
  detect implementation drift before it costs real money.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "DivergenceConfig",
    "DivergenceVerdict",
    "DEFAULT_DIVERGENCE_CONFIG",
    "divergence_series",
    "divergence_alert",
    "render_divergence",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DivergenceConfig:
    """Immutable configuration for live-vs-shadow divergence monitoring.

    Attributes
    ----------
    window:
        Number of trailing residuals (EXCLUDING the latest one) used to
        estimate the residual standard deviation for the z-score.  Must be
        ``>= 2`` (a sample standard deviation needs at least two points).
        Default ``20``.
    threshold:
        Alert threshold in residual-std units.  The alert fires when the
        absolute z-score *strictly exceeds* this value (``abs(z) > threshold``);
        the boundary ``abs(z) == threshold`` does not fire.  Must be ``> 0``.
        Default ``2.0``.
    min_history:
        Minimum number of aligned residuals required before any alert decision
        is made.  Below this the verdict is ``INSUFFICIENT_HISTORY``.  Must be
        ``>= window + 1`` so that a full trailing window plus the tested
        residual are available.  Default ``window + 1``.
    ddof:
        Delta degrees of freedom for the trailing-std estimate.  ``1`` (default)
        is the unbiased sample standard deviation; ``0`` is the population
        estimate.  Must be ``0`` or ``1`` (with ``window >= 2`` this always
        leaves at least one degree of freedom).
    """

    window: int = 20
    threshold: float = 2.0
    min_history: int | None = None
    ddof: int = 1

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError(f"window must be >= 2; got {self.window!r}")
        if not (self.threshold > 0.0):
            raise ValueError(f"threshold must be > 0; got {self.threshold!r}")
        if self.ddof not in (0, 1):
            raise ValueError(f"ddof must be 0 or 1; got {self.ddof!r}")
        # ddof in {0, 1} and window >= 2 guarantee ddof < window, so the
        # trailing-std estimate always has at least one degree of freedom.
        floor = self.window + 1
        if self.min_history is None:
            # frozen dataclass: assign via object.__setattr__.
            object.__setattr__(self, "min_history", floor)
        elif self.min_history < floor:
            raise ValueError(
                f"min_history must be >= window + 1 ({floor}); "
                f"got {self.min_history!r}"
            )


# Module-level singleton default (avoids ruff B008 -- no call in arg defaults).
DEFAULT_DIVERGENCE_CONFIG = DivergenceConfig()


# ---------------------------------------------------------------------------
# Verdict DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DivergenceVerdict:
    """Machine-readable outcome of a divergence check.

    Attributes
    ----------
    state:
        ``"OK"`` (decision made, no alert), ``"ALERT"`` (decision made, alert
        fired) or ``"INSUFFICIENT_HISTORY"`` (too few residuals to decide).
    alert:
        ``True`` iff ``state == "ALERT"``.  Convenience boolean mirroring
        ``state`` for callers that only need the gate.
    latest_residual:
        The most recent ``live - shadow`` residual (``NaN`` when state is
        ``INSUFFICIENT_HISTORY``).
    trailing_std:
        Standard deviation of the ``window`` residuals immediately preceding
        the latest one (self-excluded; ``NaN`` when insufficient history).
    z_score:
        ``latest_residual / trailing_std`` (``NaN`` when insufficient history,
        or ``+/-inf`` if the trailing window was perfectly flat -- a zero-std
        window with a non-zero latest residual is an unambiguous divergence).
    observed:
        The observed statistic compared against the limit, i.e. ``abs(z_score)``
        (``NaN`` when insufficient history).
    limit:
        The configured ``threshold`` the observed statistic is compared to.
    n_residuals:
        Number of aligned residuals available for this check.
    config:
        The :class:`DivergenceConfig` used to produce this verdict.
    """

    state: str
    alert: bool
    latest_residual: float
    trailing_std: float
    z_score: float
    observed: float
    limit: float
    n_residuals: int
    config: DivergenceConfig

    @property
    def insufficient_history(self) -> bool:
        """``True`` when the verdict could not be computed for lack of data."""
        return self.state == "INSUFFICIENT_HISTORY"


# ---------------------------------------------------------------------------
# Residual series
# ---------------------------------------------------------------------------


def divergence_series(
    live_pnl: pd.Series,
    shadow_pnl: pd.Series,
) -> pd.Series:
    """Align two daily-P&L series and return the residual ``live - shadow``.

    Alignment rules
    ---------------
    * The two series are aligned by an **inner join on their indices** (typically
      trading dates): only timestamps present in BOTH series contribute a
      residual.  Days the live book traded but the shadow did not (or vice
      versa) are dropped -- a residual is only meaningful when both books have a
      P&L for the same day.
    * The result is sorted by index ascending so trailing-window statistics are
      computed in chronological order regardless of input ordering.
    * **NaN policy**: any aligned pair where either side is ``NaN`` is dropped
      (a ``NaN`` P&L is treated as "no observation", not as zero).  The returned
      series is therefore guaranteed NaN-free.

    Parameters
    ----------
    live_pnl:
        Realised live daily P&L, indexed by date/bar.
    shadow_pnl:
        Shadow (paper / replayed-backtest) daily P&L over the same period,
        indexed by date/bar.

    Returns
    -------
    pandas.Series
        The aligned ``live - shadow`` residual series, sorted ascending by
        index, NaN-free, named ``"residual"``.  May be empty when the two
        indices do not overlap.

    Raises
    ------
    ValueError
        If either series has a non-unique index (duplicate dates make the
        inner join ambiguous).
    """
    if live_pnl.index.has_duplicates:
        raise ValueError("live_pnl index must not contain duplicate labels.")
    if shadow_pnl.index.has_duplicates:
        raise ValueError("shadow_pnl index must not contain duplicate labels.")

    live = live_pnl.astype(float)
    shadow = shadow_pnl.astype(float)

    # Inner join on the index: only days present in both books.
    aligned = pd.concat([live, shadow], axis=1, join="inner", keys=["live", "shadow"])
    aligned = aligned.sort_index()
    # Drop any day where either side is NaN (treat NaN as "no observation").
    aligned = aligned.dropna(how="any")

    residual = aligned["live"] - aligned["shadow"]
    residual.name = "residual"
    return residual


# ---------------------------------------------------------------------------
# Alert decision
# ---------------------------------------------------------------------------


def divergence_alert(
    live_pnl: pd.Series,
    shadow_pnl: pd.Series,
    *,
    config: DivergenceConfig = DEFAULT_DIVERGENCE_CONFIG,
) -> DivergenceVerdict:
    """Decide whether the latest live-vs-shadow residual is anomalously large.

    Algorithm
    ---------
    1. Build the aligned residual series via :func:`divergence_series`.
    2. If fewer than ``config.min_history`` residuals are available, return an
       ``INSUFFICIENT_HISTORY`` verdict with ``NaN`` statistics and no alert.
    3. Otherwise take the latest residual ``r`` and estimate the trailing std
       ``s`` over the ``config.window`` residuals *immediately preceding* ``r``
       (self-excluded -- see module docstring).
    4. Compute ``z = r / s``.  When ``s == 0`` (a perfectly flat trailing
       window) the z-score is ``+/-inf`` for a non-zero ``r`` (an unambiguous
       divergence) and ``0.0`` when ``r`` is also exactly zero.
    5. Fire the alert when ``abs(z) > config.threshold`` (strict inequality; the
       boundary does not fire).

    Parameters
    ----------
    live_pnl, shadow_pnl:
        Daily-P&L series; see :func:`divergence_series` for alignment rules.
    config:
        :class:`DivergenceConfig` controlling window, threshold and history
        floor.  Defaults to :data:`DEFAULT_DIVERGENCE_CONFIG`.

    Returns
    -------
    DivergenceVerdict
        The decision plus all supporting statistics, machine-readable.
    """
    residual = divergence_series(live_pnl, shadow_pnl)
    n = int(residual.shape[0])

    assert config.min_history is not None  # set in __post_init__
    if n < config.min_history:
        return DivergenceVerdict(
            state="INSUFFICIENT_HISTORY",
            alert=False,
            latest_residual=float("nan"),
            trailing_std=float("nan"),
            z_score=float("nan"),
            observed=float("nan"),
            limit=config.threshold,
            n_residuals=n,
            config=config,
        )

    values = residual.to_numpy(dtype=float)
    latest = float(values[-1])
    # Trailing window EXCLUDING the latest residual (no self-contamination).
    trailing = values[-(config.window + 1):-1]
    trailing_std = float(np.std(trailing, ddof=config.ddof))

    if trailing_std == 0.0:
        # Flat trailing window: any non-zero latest residual is an unambiguous
        # divergence (z -> +/-inf); an exactly-zero residual is not (z = 0).
        z_score = float(np.sign(latest)) * float("inf") if latest != 0.0 else 0.0
    else:
        z_score = latest / trailing_std

    observed = abs(z_score)
    fired = bool(observed > config.threshold)

    return DivergenceVerdict(
        state="ALERT" if fired else "OK",
        alert=fired,
        latest_residual=latest,
        trailing_std=trailing_std,
        z_score=z_score,
        observed=observed,
        limit=config.threshold,
        n_residuals=n,
        config=config,
    )


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    """Format a float for the ASCII report, handling NaN/inf cleanly."""
    if np.isnan(value):
        return "n/a"
    if np.isposinf(value):
        return "+inf"
    if np.isneginf(value):
        return "-inf"
    return f"{value:.6f}"


def render_divergence(verdict: DivergenceVerdict) -> str:
    """Render a :class:`DivergenceVerdict` as an ASCII-only one-pager.

    All output is 7-bit ASCII (ord < 128) -- suitable for Windows cp1252
    consoles, ops email bodies and log files, matching the renderer convention
    in :mod:`core_trading.risk.daily_report`.

    Parameters
    ----------
    verdict:
        The verdict to render.

    Returns
    -------
    str
        ASCII-only multi-line report.
    """
    lines: list[str] = []
    lines.append("# Live-vs-Backtest Divergence Report")
    lines.append("")
    lines.append(f"State          : {verdict.state}")

    if verdict.insufficient_history:
        lines.append(
            f"Residuals      : {verdict.n_residuals} "
            f"(need >= {verdict.config.min_history})"
        )
        lines.append("")
        lines.append(
            "Not enough aligned residual history to judge divergence. "
            "Monitor is silent."
        )
        lines.append("")
        return "\n".join(lines)

    # Direction commentary for the operator (sign convention spelled out).
    if verdict.latest_residual > 0.0:
        direction = "live OUT-earned shadow"
    elif verdict.latest_residual < 0.0:
        direction = "live UNDER-earned shadow"
    else:
        direction = "live matched shadow exactly"

    lines.append(f"Alert          : {'YES' if verdict.alert else 'no'}")
    lines.append(f"Residuals      : {verdict.n_residuals}")
    lines.append(f"Window         : {verdict.config.window} (trailing, self-excluded)")
    lines.append("")
    lines.append("## Statistics (residual = live_pnl - shadow_pnl)")
    lines.append("")
    lines.append(f"Latest residual: {_fmt(verdict.latest_residual)}  ({direction})")
    lines.append(f"Trailing std   : {_fmt(verdict.trailing_std)}")
    lines.append(f"Z-score        : {_fmt(verdict.z_score)}")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(f"Observed |z|   : {_fmt(verdict.observed)}")
    lines.append(f"Limit          : {_fmt(verdict.limit)}")
    comparator = ">" if verdict.alert else "<="
    lines.append(f"Test           : |z| {comparator} limit -> {verdict.state}")
    lines.append("")
    if verdict.alert:
        lines.append(
            "ACTION: live P&L has diverged from the shadow book beyond the "
            "configured tolerance. Investigate data feed, cost model, sizing "
            "and fills before the next trading session."
        )
    else:
        lines.append(
            "OK: live P&L tracks the shadow book within tolerance. "
            "No action required."
        )
    lines.append("")
    return "\n".join(lines)
