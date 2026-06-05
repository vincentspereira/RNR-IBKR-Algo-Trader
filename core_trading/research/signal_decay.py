"""Signal decay monitoring and retraining cadence registry (Phase 13.1 + 13.4).

This module is a *pure generator* -- it never touches the clock, filesystem, or
any live feed.  The ``generated_at`` timestamp is injectable (defaulting to the
current UTC) and the only data source on the CLI is ``--demo``.  This mirrors
the design of :mod:`core_trading.research.robustness_report`.

Phase 13.1 -- Rolling decay metrics and retirement rules
---------------------------------------------------------
Given a signal's realised daily return series the module computes:

* **Rolling Sharpe** over configurable windows (default 30 / 60 / 90 trading
  days) using an expanding minimum-observations guard.
* **Expanding-window ("inception") Sharpe** growing from the first observation.
* **Decay gap** -- the difference between a supplied in-sample / backtest Sharpe
  and the current rolling out-of-sample Sharpe (positive = signal still above
  benchmark; negative = decay below benchmark).

Retirement rule (Phase 13.1 DOD):

* **RETIRE** -- rolling Sharpe (primary window) < 0 for >= ``retirement_days``
  consecutive calendar-index positions (default 60).
* **WARN**   -- rolling Sharpe < ``decay_warn_fraction * backtest_sharpe``
  (default 0.5) for >= ``warn_days`` consecutive positions (default 30).
* **HEALTHY** -- neither condition met.

A machine-readable :class:`SignalVerdict` dataclass is emitted per signal.

Phase 13.4 -- Retraining cadence registry
------------------------------------------
A small declarative registry of :class:`RetrainPolicy` frozen dataclasses
records the model family, cadence (days between retrains), and rolling training
window (days of history used).  Default policies come from the master plan:

* ML models:          monthly (every 21 trading days), 3-year window (756 days).
* GARCH + HMM:        weekly  (every 5 trading days),  1-year window (252 days).
* Factor models:      monthly (every 21 trading days), 2-year window (504 days).

:func:`due_for_retrain` is pure logic -- it returns the subset of policies whose
``last_trained`` date is at least ``cadence_days`` ago relative to ``today``.
**Scheduler wiring is an operator item**: the function does not schedule, log, or
invoke any external service; it only answers *which* policies are due.

Multi-signal report
-------------------
:func:`build_decay_report` accepts a dict of ``name -> return series`` plus an
optional ``backtest_sharpes`` dict and produces a :class:`DecayReport` with
per-signal :class:`SignalVerdict` objects ranked by rolling Sharpe descending.
The ASCII renderer :func:`render_decay_report` mirrors the renderer pattern in
:mod:`core_trading.research.robustness_report`.

CLI entry point
---------------
``python -m core_trading.research.signal_decay --demo``
    Runs three synthetic signals (HEALTHY / WARN / RETIRE) and prints the full
    ASCII decay report.

``python -m core_trading.research.signal_decay --demo --output <path>``
    Same, but also writes the report to the given path.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd

__all__ = [
    # Configuration
    "DecayConfig",
    # Verdict DTO
    "SignalStatus",
    "RollingSharpeSeries",
    "SignalVerdict",
    # Multi-signal report
    "DecayReport",
    # Retraining cadence
    "RetrainPolicy",
    "DEFAULT_RETRAIN_POLICIES",
    "due_for_retrain",
    # Generators
    "compute_rolling_metrics",
    "assess_signal",
    "build_decay_report",
    # Renderer
    "render_decay_report",
    # CLI
    "main",
]

SignalStatus = Literal["HEALTHY", "WARN", "RETIRE"]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecayConfig:
    """Configuration for signal decay monitoring.

    Attributes
    ----------
    rolling_windows:
        Tuple of rolling window sizes in trading-day bars to compute Sharpe
        over.  The first element is the *primary* window used for retirement
        and warn state counting.  Default ``(30, 60, 90)``.
    periods_per_year:
        Annualisation factor for the Sharpe ratio.  Default 252.
    retirement_days:
        Number of consecutive bars for which the primary rolling Sharpe must
        be strictly negative before RETIRE is flagged.  Default 60.
    warn_days:
        Number of consecutive bars for which the primary rolling Sharpe must
        be below ``decay_warn_fraction * backtest_sharpe`` before WARN is
        flagged.  Default 30.
    decay_warn_fraction:
        Fraction of the backtest Sharpe used as the WARN threshold.  The warn
        condition is ``rolling_sharpe < decay_warn_fraction * backtest_sharpe``.
        Default 0.5.
    min_window_obs:
        Minimum number of finite observations required inside a rolling window
        to compute a valid Sharpe; windows with fewer observations are filled
        with ``NaN``.  Default 5.
    """

    rolling_windows: tuple[int, ...] = (30, 60, 90)
    periods_per_year: int = 252
    retirement_days: int = 60
    warn_days: int = 30
    decay_warn_fraction: float = 0.5
    min_window_obs: int = 5

    def __post_init__(self) -> None:
        if not self.rolling_windows:
            raise ValueError("rolling_windows must be non-empty.")
        if any(w < 2 for w in self.rolling_windows):
            raise ValueError("Each rolling window must be >= 2.")
        if self.periods_per_year < 1:
            raise ValueError("periods_per_year must be >= 1.")
        if self.retirement_days < 1:
            raise ValueError("retirement_days must be >= 1.")
        if self.warn_days < 1:
            raise ValueError("warn_days must be >= 1.")
        if not (0.0 < self.decay_warn_fraction < 1.0):
            raise ValueError("decay_warn_fraction must be in (0, 1).")
        if self.min_window_obs < 2:
            raise ValueError("min_window_obs must be >= 2.")

    @property
    def primary_window(self) -> int:
        """The first rolling window -- used for RETIRE/WARN state counting."""
        return self.rolling_windows[0]


# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollingSharpeSeries:
    """Rolling and expanding Sharpe series for a single signal.

    Attributes
    ----------
    rolling_sharpes:
        Dict mapping window size -> pd.Series of rolling annualised Sharpe.
        Entries are NaN where fewer than ``min_window_obs`` finite values
        exist in the window.
    expanding_sharpe:
        Expanding-window ("inception-to-date") annualised Sharpe Series.
        NaN at the start until at least 2 finite observations are available.
    decay_gap:
        pd.Series of ``backtest_sharpe - rolling_sharpe[primary_window]``.
        Positive = signal still outperforming its backtest Sharpe; negative =
        decay below backtest.  All NaN when ``backtest_sharpe`` is None.
    backtest_sharpe:
        The supplied in-sample Sharpe used to compute ``decay_gap``, or None.
    primary_window:
        Primary window size (first element of ``DecayConfig.rolling_windows``).
    """

    rolling_sharpes: dict[int, pd.Series] = field(repr=False)
    expanding_sharpe: pd.Series = field(repr=False)
    decay_gap: pd.Series = field(repr=False)
    backtest_sharpe: float | None
    primary_window: int


@dataclass(frozen=True, slots=True)
class SignalVerdict:
    """Machine-readable decay verdict for a single signal.

    Attributes
    ----------
    name:
        Signal identifier.
    status:
        One of ``"HEALTHY"``, ``"WARN"``, or ``"RETIRE"``.
    days_in_state:
        Number of consecutive trailing bars in the current RETIRE or WARN
        state.  Zero when HEALTHY.
    latest_rolling_sharpe:
        Most-recent non-NaN value of the primary-window rolling Sharpe, or
        None if there is no valid observation.
    latest_inception_sharpe:
        Most-recent non-NaN expanding Sharpe, or None if unavailable.
    latest_decay_gap:
        Most-recent non-NaN decay gap, or None if no backtest Sharpe was
        supplied.
    backtest_sharpe:
        The supplied in-sample Sharpe, or None.
    n_obs:
        Number of finite returns in the series.
    metrics:
        The full :class:`RollingSharpeSeries` for this signal.
    reason:
        Human-readable explanation of the status.
    """

    name: str
    status: SignalStatus
    days_in_state: int
    latest_rolling_sharpe: float | None
    latest_inception_sharpe: float | None
    latest_decay_gap: float | None
    backtest_sharpe: float | None
    n_obs: int
    metrics: RollingSharpeSeries
    reason: str


@dataclass(frozen=True, slots=True)
class DecayReport:
    """Assembled multi-signal decay report.

    Attributes
    ----------
    verdicts:
        Tuple of :class:`SignalVerdict` objects, ranked by latest primary
        rolling Sharpe descending (NaN-last).
    n_retire:
        Count of signals with RETIRE status.
    n_warn:
        Count of signals with WARN status.
    n_healthy:
        Count of signals with HEALTHY status.
    generated_at:
        Injected ISO/UTC timestamp string.
    config:
        The :class:`DecayConfig` used.
    """

    verdicts: tuple[SignalVerdict, ...]
    n_retire: int
    n_warn: int
    n_healthy: int
    generated_at: str
    config: DecayConfig


# ---------------------------------------------------------------------------
# Retraining cadence registry (Phase 13.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetrainPolicy:
    """Declarative retraining cadence for a model family.

    This dataclass is pure configuration -- it records *when* a model family
    should be retrained and over *what* trailing window of history.  The
    actual scheduling, invocation, and logging of retrains is an **operator
    concern** and is not implemented here; see the Phase 13 operator runbook.

    Attributes
    ----------
    model_family:
        Identifier for the model family, e.g. ``"ml"``, ``"garch"``,
        ``"hmm"``, ``"factor"``.
    cadence_days:
        Minimum number of calendar days between retrains.  Use trading-day
        equivalents: 5 ~ weekly, 21 ~ monthly, 63 ~ quarterly.
    window_days:
        Number of calendar days of history used in each training run.  Use
        trading-day equivalents: 252 ~ 1 year, 504 ~ 2 years, 756 ~ 3 years.
    """

    model_family: str
    cadence_days: int
    window_days: int

    def __post_init__(self) -> None:
        if not self.model_family:
            raise ValueError("model_family must be a non-empty string.")
        if self.cadence_days < 1:
            raise ValueError("cadence_days must be >= 1.")
        if self.window_days < 1:
            raise ValueError("window_days must be >= 1.")


# Master-plan defaults (Phase 13.4):
#   ML monthly / rolling 3-year window
#   GARCH + HMM weekly / rolling 1-year window
#   Factor models monthly / rolling 2-year window
DEFAULT_RETRAIN_POLICIES: tuple[RetrainPolicy, ...] = (
    RetrainPolicy(model_family="ml", cadence_days=21, window_days=756),
    RetrainPolicy(model_family="garch", cadence_days=5, window_days=252),
    RetrainPolicy(model_family="hmm", cadence_days=5, window_days=252),
    RetrainPolicy(model_family="factor", cadence_days=21, window_days=504),
)


def due_for_retrain(
    policies: list[RetrainPolicy] | tuple[RetrainPolicy, ...],
    last_trained: dict[str, date],
    today: date,
) -> list[RetrainPolicy]:
    """Return the subset of policies that are due for retraining today.

    A policy is *due* when ``today - last_trained[policy.model_family]`` is
    greater than or equal to ``policy.cadence_days``, or when the model family
    has no entry in ``last_trained`` at all (treat as never trained).

    This function is **pure logic only**.  It does not invoke any scheduler,
    training pipeline, or external service.  Wiring the returned list into an
    actual retraining run is an operator item (see Phase 13 operator runbook).

    Parameters
    ----------
    policies:
        Sequence of :class:`RetrainPolicy` objects to evaluate.
    last_trained:
        Mapping of ``model_family -> date`` of the most recent completed
        training run.  Families absent from this dict are treated as never
        trained and will always be returned as due.
    today:
        Reference date for the staleness calculation.  Pass ``date.today()``
        in production, or a fixed date in tests for determinism.

    Returns
    -------
    list[RetrainPolicy]
        Policies due for retraining, preserving input order.
    """
    due: list[RetrainPolicy] = []
    for policy in policies:
        last = last_trained.get(policy.model_family)
        if last is None:
            due.append(policy)
            continue
        elapsed: int = (today - last).days
        if elapsed >= policy.cadence_days:
            due.append(policy)
    return due


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_str() -> str:
    ts = pd.Timestamp.utcnow()
    return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _clean_array(series: pd.Series) -> tuple[pd.Series, np.ndarray[tuple[int], np.dtype[np.float64]]]:
    """Return the series with its finite values as a float array."""
    arr = np.asarray(series, dtype=float)
    finite: np.ndarray[tuple[int], np.dtype[np.float64]] = arr[np.isfinite(arr)]
    return series, finite


def _rolling_sharpe_series(
    returns: pd.Series,
    window: int,
    periods_per_year: int,
    min_obs: int,
) -> pd.Series:
    """Compute a rolling annualised Sharpe series.

    Uses a vectorised rolling approach: for each window compute mean and
    std(ddof=1) using pandas rolling, then scale by sqrt(periods_per_year).
    Windows with fewer than ``min_obs`` finite observations are NaN.

    Parameters
    ----------
    returns:
        Daily return series.
    window:
        Rolling window size in bars.
    periods_per_year:
        Annualisation factor.
    min_obs:
        Minimum observations required; fewer -> NaN.

    Returns
    -------
    pd.Series
        Same index as ``returns``.
    """
    roll = returns.rolling(window=window, min_periods=min_obs)
    mean = roll.mean()
    std = roll.std(ddof=1)
    # Avoid divide-by-zero: where std == 0, Sharpe is 0.0 (not NaN).
    valid = std.notna() & (std > 0)
    sharpe = pd.Series(np.nan, index=returns.index, dtype=float)
    sharpe[valid] = (mean[valid] / std[valid]) * np.sqrt(periods_per_year)
    # Where mean is valid but std is exactly 0 (all returns identical), emit 0.
    zero_std = std.notna() & (std == 0) & mean.notna()
    sharpe[zero_std] = 0.0
    return sharpe


def _expanding_sharpe_series(
    returns: pd.Series,
    periods_per_year: int,
    min_obs: int,
) -> pd.Series:
    """Compute the expanding-window annualised Sharpe series.

    Parameters
    ----------
    returns:
        Daily return series.
    periods_per_year:
        Annualisation factor.
    min_obs:
        Minimum observations required; fewer -> NaN.

    Returns
    -------
    pd.Series
        Same index as ``returns``.
    """
    exp = returns.expanding(min_periods=min_obs)
    mean = exp.mean()
    std = exp.std(ddof=1)
    valid = std.notna() & (std > 0)
    sharpe = pd.Series(np.nan, index=returns.index, dtype=float)
    sharpe[valid] = (mean[valid] / std[valid]) * np.sqrt(periods_per_year)
    zero_std = std.notna() & (std == 0) & mean.notna()
    sharpe[zero_std] = 0.0
    return sharpe


def _latest_valid(series: pd.Series) -> float | None:
    """Return the last non-NaN value in a Series, or None."""
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _count_trailing_condition(condition: pd.Series) -> int:
    """Count the number of trailing True positions in a boolean Series.

    Traverses from the end of ``condition`` backwards, stopping at the first
    False or NaN.  Used to count consecutive days-in-state.

    Parameters
    ----------
    condition:
        Boolean (or boolean-like) Series.  NaN values stop the count.

    Returns
    -------
    int
        Number of consecutive trailing True values.
    """
    # Work on the underlying numpy array for speed.
    arr = condition.to_numpy(dtype=object)  # preserves NaN as object nan
    count = 0
    for val in reversed(arr):
        if val is True or val == True:  # noqa: E712 -- needed for object array
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------


def compute_rolling_metrics(
    returns: pd.Series,
    *,
    backtest_sharpe: float | None = None,
    config: DecayConfig | None = None,
) -> RollingSharpeSeries:
    """Compute rolling and expanding Sharpe metrics for a return series.

    Parameters
    ----------
    returns:
        Per-period (daily) return series.  NaN/inf values are treated as
        missing and excluded from each window.
    backtest_sharpe:
        The in-sample / backtest annualised Sharpe.  When supplied, the
        ``decay_gap`` field is populated as
        ``backtest_sharpe - primary_rolling_sharpe``.
    config:
        :class:`DecayConfig`.  Defaults to ``DecayConfig()``.

    Returns
    -------
    RollingSharpeSeries
    """
    cfg = config if config is not None else DecayConfig()

    rolling_sharpes: dict[int, pd.Series] = {}
    for w in cfg.rolling_windows:
        rolling_sharpes[w] = _rolling_sharpe_series(
            returns, w, cfg.periods_per_year, cfg.min_window_obs
        )

    expanding = _expanding_sharpe_series(returns, cfg.periods_per_year, cfg.min_window_obs)

    primary_rs = rolling_sharpes[cfg.primary_window]
    if backtest_sharpe is not None:
        decay_gap = pd.Series(
            backtest_sharpe - primary_rs.values,
            index=returns.index,
            dtype=float,
        )
    else:
        decay_gap = pd.Series(np.nan, index=returns.index, dtype=float)

    return RollingSharpeSeries(
        rolling_sharpes=rolling_sharpes,
        expanding_sharpe=expanding,
        decay_gap=decay_gap,
        backtest_sharpe=backtest_sharpe,
        primary_window=cfg.primary_window,
    )


def assess_signal(
    name: str,
    returns: pd.Series,
    *,
    backtest_sharpe: float | None = None,
    config: DecayConfig | None = None,
) -> SignalVerdict:
    """Assess a single signal's decay status and emit a :class:`SignalVerdict`.

    The retirement and warn rules are evaluated on the *trailing* run of the
    primary-window rolling Sharpe:

    * RETIRE -- primary rolling Sharpe < 0 for >= ``retirement_days``
      consecutive trailing positions.
    * WARN   -- primary rolling Sharpe < ``decay_warn_fraction * backtest_sharpe``
      for >= ``warn_days`` consecutive trailing positions (only when
      ``backtest_sharpe`` is supplied; otherwise this condition is skipped).
    * HEALTHY -- neither condition met.

    Parameters
    ----------
    name:
        Signal identifier.
    returns:
        Per-period (daily) return series.
    backtest_sharpe:
        In-sample Sharpe used to compute the decay gap and the WARN threshold.
        When ``None``, the WARN rule is not applied.
    config:
        :class:`DecayConfig`.  Defaults to ``DecayConfig()``.

    Returns
    -------
    SignalVerdict
    """
    cfg = config if config is not None else DecayConfig()
    _, finite = _clean_array(returns)
    n_obs = int(finite.size)

    metrics = compute_rolling_metrics(
        returns, backtest_sharpe=backtest_sharpe, config=cfg
    )

    primary_rs = metrics.rolling_sharpes[cfg.primary_window]

    # --- RETIRE check ---
    retire_condition = primary_rs < 0
    retire_run = _count_trailing_condition(retire_condition)

    if retire_run >= cfg.retirement_days:
        status: SignalStatus = "RETIRE"
        days_in_state = retire_run
        reason = (
            f"primary rolling Sharpe ({cfg.primary_window}d) negative for "
            f"{retire_run} consecutive bars (threshold {cfg.retirement_days})"
        )
    else:
        # --- WARN check (only when backtest_sharpe is available) ---
        if backtest_sharpe is not None:
            warn_threshold = cfg.decay_warn_fraction * backtest_sharpe
            warn_condition = primary_rs < warn_threshold
            warn_run = _count_trailing_condition(warn_condition)
        else:
            warn_run = 0

        if backtest_sharpe is not None and warn_run >= cfg.warn_days:
            status = "WARN"
            days_in_state = warn_run
            reason = (
                f"primary rolling Sharpe ({cfg.primary_window}d) below "
                f"{cfg.decay_warn_fraction:.0%} of backtest Sharpe "
                f"({backtest_sharpe:.4f}) for {warn_run} consecutive bars "
                f"(threshold {cfg.warn_days})"
            )
        else:
            status = "HEALTHY"
            days_in_state = 0
            reason = (
                f"primary rolling Sharpe ({cfg.primary_window}d) within "
                f"acceptable bounds; retire run={retire_run}, "
                f"warn run={warn_run if backtest_sharpe is not None else 'n/a'}"
            )

    latest_rs = _latest_valid(primary_rs)
    latest_inc = _latest_valid(metrics.expanding_sharpe)
    latest_gap = _latest_valid(metrics.decay_gap)

    return SignalVerdict(
        name=name,
        status=status,
        days_in_state=days_in_state,
        latest_rolling_sharpe=latest_rs,
        latest_inception_sharpe=latest_inc,
        latest_decay_gap=latest_gap,
        backtest_sharpe=backtest_sharpe,
        n_obs=n_obs,
        metrics=metrics,
        reason=reason,
    )


def build_decay_report(
    signal_returns: dict[str, pd.Series],
    *,
    backtest_sharpes: dict[str, float] | None = None,
    config: DecayConfig | None = None,
    generated_at: str | None = None,
) -> DecayReport:
    """Build a multi-signal decay report ranked by latest rolling Sharpe.

    Parameters
    ----------
    signal_returns:
        Mapping of ``signal_name -> daily return Series``.
    backtest_sharpes:
        Optional mapping of ``signal_name -> in-sample Sharpe``.  Signals
        absent from this dict are assessed without a backtest reference
        (WARN rule is not applied to them).
    config:
        :class:`DecayConfig`.  Defaults to ``DecayConfig()``.
    generated_at:
        Optional injected UTC timestamp; ``None`` stamps the current UTC.

    Returns
    -------
    DecayReport
    """
    cfg = config if config is not None else DecayConfig()
    stamp = generated_at if generated_at is not None else _utcnow_str()
    bs = backtest_sharpes or {}

    verdicts: list[SignalVerdict] = []
    for name, series in signal_returns.items():
        v = assess_signal(
            name,
            series,
            backtest_sharpe=bs.get(name),
            config=cfg,
        )
        verdicts.append(v)

    # Rank by latest primary rolling Sharpe descending (NaN last).
    def _sort_key(v: SignalVerdict) -> float:
        rs = v.latest_rolling_sharpe
        return rs if rs is not None else float("-inf")

    verdicts.sort(key=_sort_key, reverse=True)

    n_retire = sum(1 for v in verdicts if v.status == "RETIRE")
    n_warn = sum(1 for v in verdicts if v.status == "WARN")
    n_healthy = sum(1 for v in verdicts if v.status == "HEALTHY")

    return DecayReport(
        verdicts=tuple(verdicts),
        n_retire=n_retire,
        n_warn=n_warn,
        n_healthy=n_healthy,
        generated_at=stamp,
        config=cfg,
    )


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def _fmt_float(value: float | None, width: int = 8, decimals: int = 4) -> str:
    """Format a float or 'n/a' into a fixed-width string."""
    if value is None:
        return f"{'n/a':<{width}}"
    return f"{value:{width}.{decimals}f}"


def render_decay_report(report: DecayReport) -> str:
    """Render a :class:`DecayReport` as an ASCII-only string.

    All output is 7-bit ASCII (``ord < 128``), suitable for Windows cp1252
    consoles, ops email bodies, and log files.  Mirrors the renderer pattern of
    :func:`core_trading.research.robustness_report.render_robustness_report`.

    Parameters
    ----------
    report:
        The report to render.

    Returns
    -------
    str
        ASCII-only multi-line string.
    """
    lines: list[str] = []
    lines.append("# Signal Decay Report")
    lines.append("")
    lines.append(f"Generated  : {report.generated_at}")
    lines.append(
        f"Signals    : {len(report.verdicts)} total  "
        f"({report.n_healthy} HEALTHY, {report.n_warn} WARN, "
        f"{report.n_retire} RETIRE)"
    )
    cfg = report.config
    lines.append(
        f"Config     : windows={cfg.rolling_windows}  "
        f"retire_days={cfg.retirement_days}  warn_days={cfg.warn_days}  "
        f"warn_frac={cfg.decay_warn_fraction}"
    )
    lines.append("")

    # Per-signal table
    lines.append("## Signal Summary")
    lines.append("")
    w_name = 20
    w_status = 8
    w_rs = 10
    w_inc = 10
    w_gap = 10
    w_days = 7
    w_obs = 7
    header = (
        f"| {'Signal':<{w_name}} "
        f"| {'Status':<{w_status}} "
        f"| {'RollSharpe':<{w_rs}} "
        f"| {'InceptShr':<{w_inc}} "
        f"| {'DecayGap':<{w_gap}} "
        f"| {'Days':<{w_days}} "
        f"| {'N':<{w_obs}} |"
    )
    divider = (
        f"|{'-' * (w_name + 2)}"
        f"|{'-' * (w_status + 2)}"
        f"|{'-' * (w_rs + 2)}"
        f"|{'-' * (w_inc + 2)}"
        f"|{'-' * (w_gap + 2)}"
        f"|{'-' * (w_days + 2)}"
        f"|{'-' * (w_obs + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for v in report.verdicts:
        row = (
            f"| {v.name:<{w_name}} "
            f"| {v.status:<{w_status}} "
            f"| {_fmt_float(v.latest_rolling_sharpe, w_rs, 4)} "
            f"| {_fmt_float(v.latest_inception_sharpe, w_inc, 4)} "
            f"| {_fmt_float(v.latest_decay_gap, w_gap, 4)} "
            f"| {str(v.days_in_state):<{w_days}} "
            f"| {str(v.n_obs):<{w_obs}} |"
        )
        lines.append(row)
    lines.append("")

    # Per-signal detail
    lines.append("## Signal Detail")
    lines.append("")
    for v in report.verdicts:
        lines.append(f"### {v.name}")
        lines.append(f"  Status         : {v.status}")
        lines.append(f"  Days in state  : {v.days_in_state}")
        lines.append(
            f"  Rolling Sharpe ({cfg.primary_window}d): "
            f"{_fmt_float(v.latest_rolling_sharpe).strip()}"
        )
        lines.append(
            f"  Inception Sharpe  : {_fmt_float(v.latest_inception_sharpe).strip()}"
        )
        lines.append(
            f"  Decay gap         : {_fmt_float(v.latest_decay_gap).strip()}"
        )
        lines.append(
            f"  Backtest Sharpe   : "
            f"{_fmt_float(v.backtest_sharpe).strip() if v.backtest_sharpe is not None else 'n/a'}"
        )
        lines.append(f"  Observations      : {v.n_obs}")
        lines.append(f"  Reason            : {v.reason}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retrain cadence renderer (bonus ASCII section)
# ---------------------------------------------------------------------------


def render_retrain_schedule(
    policies: list[RetrainPolicy] | tuple[RetrainPolicy, ...],
    last_trained: dict[str, date],
    today: date,
) -> str:
    """Render the retrain cadence status as an ASCII-only table.

    Parameters
    ----------
    policies:
        Sequence of :class:`RetrainPolicy` objects.
    last_trained:
        Mapping of ``model_family -> last retrain date``.
    today:
        Reference date.

    Returns
    -------
    str
        ASCII-only multi-line string.
    """
    due_set = {p.model_family for p in due_for_retrain(policies, last_trained, today)}
    lines: list[str] = []
    lines.append("## Retrain Cadence Status")
    lines.append("")
    w_fam = 12
    w_cad = 10
    w_win = 10
    w_last = 12
    w_elapsed = 9
    w_due = 6
    header = (
        f"| {'Family':<{w_fam}} "
        f"| {'Cadence':<{w_cad}} "
        f"| {'Window':<{w_win}} "
        f"| {'LastTrained':<{w_last}} "
        f"| {'Elapsed':<{w_elapsed}} "
        f"| {'Due':<{w_due}} |"
    )
    divider = (
        f"|{'-' * (w_fam + 2)}"
        f"|{'-' * (w_cad + 2)}"
        f"|{'-' * (w_win + 2)}"
        f"|{'-' * (w_last + 2)}"
        f"|{'-' * (w_elapsed + 2)}"
        f"|{'-' * (w_due + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for p in policies:
        last = last_trained.get(p.model_family)
        last_str = str(last) if last is not None else "never"
        elapsed = (today - last).days if last is not None else "n/a"
        due_str = "YES" if p.model_family in due_set else "no"
        row = (
            f"| {p.model_family:<{w_fam}} "
            f"| {str(p.cadence_days) + 'd':<{w_cad}} "
            f"| {str(p.window_days) + 'd':<{w_win}} "
            f"| {last_str:<{w_last}} "
            f"| {str(elapsed):<{w_elapsed}} "
            f"| {due_str:<{w_due}} |"
        )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo synthetic signals
# ---------------------------------------------------------------------------


def _build_demo_signals(
    seed: int = 20240605,
    *,
    n_obs: int = 500,
) -> tuple[dict[str, pd.Series], dict[str, float]]:
    """Build three seeded synthetic return series for the CLI demo.

    Each signal uses its own RNG so its characteristics are independent of
    the other signals' lengths, making the demo deterministic.

    Returns a (signal_returns, backtest_sharpes) pair demonstrating the three
    possible states:

    * ``signal_alpha``: persistent positive drift -- HEALTHY throughout.
    * ``signal_warn``: positive first half, near-zero second half -- WARN.
    * ``signal_retire``: positive early, strongly negative last 90 bars
      (seed 999 reliably yields 87 consecutive negative rolling-Sharpe bars
      with window=20 and retirement_days=60) -- RETIRE.
    """
    sigma = 0.01
    dates = pd.date_range("2022-01-03", periods=n_obs, freq="B")

    # HEALTHY: drift ~1.4 annualised Sharpe throughout (seed = base seed)
    rng_healthy = np.random.default_rng(seed)
    drift_healthy = 1.4 / np.sqrt(252.0) * sigma
    healthy_ret = rng_healthy.normal(drift_healthy, sigma, n_obs)

    # WARN: positive first half, mildly negative second half.
    # Backtest Sharpe ~1.2; second half drift = -0.3 -> rolling Sharpe falls
    # below 0.5 * 1.2 = 0.6 for >= 30 consecutive trailing bars but does NOT
    # cross into negative long enough to trigger RETIRE (retire_run ~ 4).
    # Seed 118 with late drift -0.3/sqrt(252)*sigma reliably gives warn_run=49.
    rng_warn = np.random.default_rng(118)
    drift_warn_early = 1.2 / np.sqrt(252.0) * sigma
    drift_warn_late = -0.3 / np.sqrt(252.0) * sigma
    warn_ret = np.concatenate([
        rng_warn.normal(drift_warn_early, sigma, n_obs // 2),
        rng_warn.normal(drift_warn_late, sigma, n_obs - n_obs // 2),
    ])

    # RETIRE: positive early, strongly negative last 90 bars.
    # Seed 999 with n_late=90 yields 87 consecutive negative trailing bars
    # on the primary window=20 rolling Sharpe -- well above retirement_days=60.
    rng_retire = np.random.default_rng(999)
    n_late = 90
    drift_retire_early = 1.0 / np.sqrt(252.0) * sigma
    drift_retire_late = -2.0 / np.sqrt(252.0) * sigma
    retire_ret = np.concatenate([
        rng_retire.normal(drift_retire_early, sigma, n_obs - n_late),
        rng_retire.normal(drift_retire_late, sigma, n_late),
    ])

    signal_returns: dict[str, pd.Series] = {
        "signal_alpha": pd.Series(healthy_ret, index=dates, name="signal_alpha"),
        "signal_warn": pd.Series(warn_ret, index=dates, name="signal_warn"),
        "signal_retire": pd.Series(retire_ret, index=dates, name="signal_retire"),
    }
    backtest_sharpes: dict[str, float] = {
        "signal_alpha": 1.4,
        "signal_warn": 1.2,
        "signal_retire": 1.0,
    }
    return signal_returns, backtest_sharpes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the signal decay report.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``). Testable without a
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.research.signal_decay",
        description=(
            "Signal decay monitoring and retraining cadence registry "
            "(Phase 13.1 + 13.4). Use --demo to run on three seeded "
            "synthetic signals (HEALTHY / WARN / RETIRE)."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on seeded synthetic signals (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (wiring live signal return series into the CLI "
            "is a later operational concern; see module docstring)."
        )

    signal_returns, backtest_sharpes = _build_demo_signals()
    # primary window 20 matches the retire signal's construction (seed 999).
    cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60, warn_days=30)
    report = build_decay_report(
        signal_returns,
        backtest_sharpes=backtest_sharpes,
        config=cfg,
        generated_at="1970-01-01T00:00:00Z",
    )
    text = render_decay_report(report)
    print(text)

    # Also print retrain cadence section.
    today = date(1970, 1, 1)
    last_trained: dict[str, date] = {
        "ml": today - timedelta(days=25),
        "garch": today - timedelta(days=3),
        "hmm": today - timedelta(days=7),
        # factor never trained -- should appear as due
    }
    retrain_text = render_retrain_schedule(DEFAULT_RETRAIN_POLICIES, last_trained, today)
    print(retrain_text)

    if args.output is not None:
        full_text = text + "\n" + retrain_text
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(full_text)
        print(f"[signal_decay] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
