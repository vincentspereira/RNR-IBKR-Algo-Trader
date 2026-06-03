"""Phase 5 signal-evaluation adapter: tree-ensemble ML directional signal (5.D.1).

Wires the random-forest directional signal
(:class:`~core_trading.signals.ml.trees.RandomForestSignal`, master plan 5.D.1)
through the evaluation gate (:mod:`~core_trading.research.signal_evaluation`).

The problem this adapter solves
-------------------------------
Every other Phase 5 adapter starts from a *dense, per-bar* signal: the OU z-score,
the trend slope, the momentum panel -- one value at every bar. The ML signal is
different. It is sampled at **CUSUM events** (a sparse subset of bars), and each
event carries a triple-barrier horizon. The backtest engine, however, wants a
continuous per-bar target weight. So the core job here is the *sparse-to-dense*
map: turn a handful of event-level bet sizes into a held-position weight series.

The map is de Prado's ``avgActiveSignals`` (AFML snippet 10.2): at each bar the
target weight is the **average of the bet sizes of every event currently active**
-- i.e. every event whose holding window covers that bar -- and zero when no event
is active. Averaging (not summing) keeps the net position bounded by the largest
single bet, so the weight stays in ``[-1, 1]``.

Look-ahead discipline (read this before trusting the verdict)
-------------------------------------------------------------
Two distinct look-ahead questions arise, and they are answered differently:

1. **The held-position map is causal.** A bar's weight uses only events whose
   start is at or before that bar, and each event is held for a **fixed** horizon
   that is known the moment the event fires -- the *vertical* (time) barrier, not
   the path-dependent first-touch ``t1``. Using the first-touch time would leak
   the exit (it is only known once the future price path reveals which barrier was
   hit). :func:`event_positions_to_weights` therefore takes an explicit
   ``hold_until`` series and the caller must pass the vertical barrier. This
   causality is what :func:`event_positions_to_weights` is unit-tested for
   (appending later events never changes an earlier bar's weight).

2. **The out-of-fold bet sizes are a whole-sample skill estimate, not a causal
   live signal.** ``RandomForestSignal.oof_signal`` builds its probabilities with
   :func:`~core_trading.signals.ml.cross_validation.purged_cv_predict`: purged,
   embargoed cross-validation over the *entire* event sample. That is exactly the
   right instrument for asking "does this model have out-of-sample skill?" -- no
   observation is sized by a model that trained on it -- but it is intrinsically a
   whole-sample construct (the fold partition depends on every event), so it is
   *not* truncation-invariant and is not a real-time signal. This adapter
   therefore evaluates **model skill**: does the forest's out-of-fold conviction,
   held over fixed horizons, clear the deflated-Sharpe bar? The deployment analogue
   is :meth:`RandomForestSignal.signal` (a trailing-window refit), gated separately
   on real data and the paper-trading wall-clock (master plan Phase 1 / 4.9).

Compute-once / sweep-cheap
--------------------------
The expensive out-of-fold path (the purged-CV forest) is computed *once* by the
caller and handed to :func:`build_ml_signal_weight_fn`; the swept knob is a cheap
**conviction floor** ``min_size`` that drops low-conviction events before the
average, mirroring the threshold sweeps of the other adapters.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 10 (bet sizing), snippet 10.2 (``avgActiveSignals``) and the
  triple-barrier holding horizon of Chapter 3.
* Deflated Sharpe gate: Bailey, D. & Lopez de Prado, M. (2014), as applied by
  :mod:`~core_trading.research.signal_evaluation`.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from core_trading.research.signal_evaluation import WeightRule

__all__ = [
    "event_positions_to_weights",
    "build_ml_signal_weight_fn",
    "ml_signal_grid",
]


# ---------------------------------------------------------------------------
# Step 1 -- the sparse-to-dense held-position map (de Prado avgActiveSignals)
# ---------------------------------------------------------------------------


def event_positions_to_weights(
    positions: pd.Series,
    hold_until: pd.Series,
    index: pd.Index,
    *,
    symbol: str = "SIM",
) -> pd.DataFrame:
    """Average active event bet sizes into a dense per-bar weight frame.

    Implements de Prado's ``avgActiveSignals`` (AFML snippet 10.2): each event
    contributes its bet size to every bar in its holding window ``[start,
    hold_until)``; a bar's target weight is the mean of the bet sizes active on
    it, and zero where none is active. The holding window must end at a horizon
    known when the event fires (the *vertical* barrier), so the map is causal --
    a bar's weight never depends on a later event.

    Parameters
    ----------
    positions:
        Signed bet sizes in ``[-1, 1]``, indexed by event start timestamp (a
        subset of ``index``). Typically
        :meth:`~core_trading.signals.ml.trees.RandomForestSignal.oof_signal`.
    hold_until:
        Per-event holding-window end timestamp, indexed like ``positions``. Pass
        the **vertical (time) barrier** from
        :func:`~core_trading.signals.ml.labeling.add_vertical_barrier`, not the
        path-dependent first-touch ``t1`` -- using the latter leaks the exit. An
        end at or beyond the last bar is clipped to the end of ``index``.
    index:
        The full bar calendar to expand onto (e.g. ``close.index``), ascending.
    symbol:
        Column label for the single-instrument weight frame.

    Returns
    -------
    pd.DataFrame
        One-column (``symbol``) target-weight frame indexed by ``index``; each
        value is the average active bet size, in ``[-1, 1]``.

    Raises
    ------
    ValueError
        If ``positions`` and ``hold_until`` are mis-aligned, if any event start or
        holding end is absent from ``index``, or if any holding window is empty
        (``hold_until`` at or before its event start).
    """
    if not positions.index.equals(hold_until.index):
        raise ValueError("positions and hold_until must share the same index")

    n = len(index)
    weight_sum = np.zeros(n, dtype=float)
    active_count = np.zeros(n, dtype=float)

    start_pos = index.get_indexer(positions.index)
    if np.any(start_pos < 0):
        raise ValueError("every event start must be present in index")
    # Clip a holding end that runs off the calendar to one-past-the-last bar.
    raw_end_pos = index.get_indexer(hold_until.to_numpy())
    end_pos = np.where(raw_end_pos < 0, n, raw_end_pos)

    sizes = np.asarray(positions.to_numpy(), dtype=float)
    for i in range(len(sizes)):
        s = int(start_pos[i])
        e = int(end_pos[i])
        if e <= s:
            raise ValueError("each holding window must end after its event start")
        weight_sum[s:e] += sizes[i]
        active_count[s:e] += 1.0

    with np.errstate(divide="ignore", invalid="ignore"):
        weights = np.where(active_count > 0.0, weight_sum / active_count, 0.0)
    return pd.DataFrame({symbol: weights}, index=index)


# ---------------------------------------------------------------------------
# Step 2 -- weight-rule factory (positions precomputed; sweep the conviction floor)
# ---------------------------------------------------------------------------


def build_ml_signal_weight_fn(
    *,
    oof_positions: pd.Series,
    hold_until: pd.Series,
    index: pd.Index,
    symbol: str = "SIM",
) -> WeightRule:
    """Build a :data:`WeightRule` from precomputed out-of-fold event positions.

    The expensive out-of-fold path (the purged-CV forest behind
    ``oof_positions``) is computed by the caller, so the returned rule is cheap:
    for each configuration it drops events whose absolute bet size is below the
    ``"min_size"`` conviction floor, then averages the survivors into a dense
    held-position frame via :func:`event_positions_to_weights`. Sweeping
    ``min_size`` (the de Prado bet-size gate) over :func:`ml_signal_grid` reuses
    the single computed position series.

    Parameters
    ----------
    oof_positions:
        Signed out-of-fold bet sizes, indexed by event start (see
        :meth:`~core_trading.signals.ml.trees.RandomForestSignal.oof_signal`).
    hold_until:
        Per-event vertical-barrier end, indexed like ``oof_positions`` (see
        :func:`event_positions_to_weights`).
    index:
        The full bar calendar to expand onto -- the same timestamps that back the
        OHLCV panel passed to the gate.
    symbol:
        Single-instrument column label; must match the panel's symbol.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable. ``params`` must contain
        ``"min_size"`` (a conviction floor in ``[0, 1)``).
    """

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        min_size = float(params["min_size"])
        keep = oof_positions.abs() >= min_size
        kept_positions = oof_positions[keep]
        kept_hold = hold_until[keep]

        # Expand onto the panel's own timestamp calendar so a positional reindex
        # is exact (the index passed here and the panel's timestamps are the same
        # chronological bars), preventing a silent all-zero misalignment.
        ts_index = panel.index.get_level_values("timestamp").unique().sort_values()
        target_index = ts_index if len(ts_index) == len(index) else index
        return event_positions_to_weights(
            kept_positions, kept_hold, target_index, symbol=symbol
        )

    return weight_rule


# ---------------------------------------------------------------------------
# Step 3 -- parameter grid
# ---------------------------------------------------------------------------


def ml_signal_grid(
    *,
    min_sizes: Sequence[float] = (0.0, 0.1, 0.2, 0.3),
) -> list[dict[str, float]]:
    """Standard conviction-floor grid for the ML directional-signal sweep.

    Parameters
    ----------
    min_sizes:
        Absolute bet-size floors to evaluate; an event is traded only when its
        out-of-fold conviction is at least this. Must contain >= 1 element; each
        must be in ``[0, 1)``. The default ``(0.0, 0.1, 0.2, 0.3)`` gives four
        trials -- enough for a meaningful deflated-Sharpe discount.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per floor.

    Raises
    ------
    ValueError
        If ``min_sizes`` is empty or any value is outside ``[0, 1)``.
    """
    floors = list(min_sizes)
    if not floors:
        raise ValueError("min_sizes must contain at least one floor")
    if any(not 0.0 <= f < 1.0 for f in floors):
        raise ValueError("each min_size must be in [0, 1)")
    return [{"min_size": float(f)} for f in floors]
