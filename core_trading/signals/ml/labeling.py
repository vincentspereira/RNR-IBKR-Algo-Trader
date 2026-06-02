"""Financial-ML labeling primitives: the triple-barrier method (Phase 5.D foundation).

This module supplies the supervised-learning *labels* on which the Phase 5.D
machine-learning signals (tree ensembles, meta-labelling, etc.) are trained. It
implements Marcos Lopez de Prado's "Advances in Financial Machine Learning"
(2018) labeling toolkit, which replaces naive fixed-horizon return labels with
**path-dependent** labels that respect profit-taking and stop-loss barriers --
the way a real position is actually closed.

It is pure ``pandas`` / ``numpy`` (no ML dependency): producing the label is the
prerequisite; *fitting a model* to it is a later 5.D batch. This is the same
foundation-before-gate-wiring cadence used for the 5.C factor modules.

Components
----------
1. ``daily_volatility``  -- EWMA return volatility, used to size barriers per the
   local volatility regime (AFML snippet 3.1).
2. ``cusum_filter``      -- symmetric CUSUM event sampler: emit an event only when
   cumulative (log) returns drift past a threshold, so the model trains on
   informative bars rather than every bar (AFML snippet 2.4).
3. ``add_vertical_barrier`` -- the time barrier ``t1``: the timestamp ``num_bars``
   ahead of each event (AFML snippet 3.4).
4. ``triple_barrier_events`` -- for each event, the first time one of the three
   barriers (profit-take, stop-loss, vertical/time) is touched (AFML snippets
   3.2-3.6). With a ``side`` series this becomes the meta-labelling setup.
5. ``get_bins``          -- realised return and label from the first-touch times.
   Without ``side``: the label is the sign of the return (direction). With
   ``side``: the label is ``{0, 1}`` -- whether acting on the primary side made
   money (the meta-label).

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 2 (CUSUM sampling) and Chapter 3 (the triple-barrier method and
  meta-labelling).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "daily_volatility",
    "cusum_filter",
    "add_vertical_barrier",
    "triple_barrier_events",
    "get_bins",
]


# ---------------------------------------------------------------------------
# 1. Volatility estimate for barrier sizing
# ---------------------------------------------------------------------------


def daily_volatility(close: pd.Series, *, span: int = 100, lookback: int = 1) -> pd.Series:
    """EWMA volatility of ``lookback``-bar returns (AFML snippet 3.1).

    Used to size the profit-take / stop-loss barriers to the local volatility
    regime: a wider barrier in turbulent periods, a tighter one in calm periods.

    Parameters
    ----------
    close:
        Price series (strictly positive), ascending index.
    span:
        EWMA span (the volatility's effective memory in bars). Must be >= 2.
    lookback:
        Return horizon in bars: ``ret[t] = close[t] / close[t - lookback] - 1``.
        Must be >= 1.

    Returns
    -------
    pd.Series
        EWMA standard deviation of the returns, indexed like ``close`` (NaN for
        the warmup bars where the return is undefined).

    Raises
    ------
    ValueError
        If ``span < 2`` or ``lookback < 1``.
    """
    if span < 2:
        raise ValueError("span must be >= 2")
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    returns = close / close.shift(lookback) - 1.0
    return returns.ewm(span=span).std()


# ---------------------------------------------------------------------------
# 2. CUSUM event sampling
# ---------------------------------------------------------------------------


def cusum_filter(close: pd.Series, *, threshold: float) -> pd.Index:
    """Symmetric CUSUM filter: sample an event on each material drift (AFML 2.4).

    Accumulates log returns in a positive and a negative running sum; when either
    breaches ``threshold`` an event is recorded and that sum resets. This samples
    bars where price has moved meaningfully (in either direction), rather than at
    a fixed clock frequency.

    Parameters
    ----------
    close:
        Price series (strictly positive), ascending index.
    threshold:
        Symmetric CUSUM threshold in log-return units. Must be > 0.

    Returns
    -------
    pd.Index
        The subset of ``close.index`` at which an event was triggered.

    Raises
    ------
    ValueError
        If ``threshold <= 0``.
    """
    if threshold <= 0.0:
        raise ValueError("threshold must be > 0")

    log_ret = np.log(close).diff()
    events: list = []
    s_pos = 0.0
    s_neg = 0.0
    index = close.index
    values = log_ret.to_numpy()
    for i in range(1, len(values)):
        delta = values[i]
        if not np.isfinite(delta):
            continue
        s_pos = max(0.0, s_pos + delta)
        s_neg = min(0.0, s_neg + delta)
        if s_neg < -threshold:
            s_neg = 0.0
            events.append(index[i])
        elif s_pos > threshold:
            s_pos = 0.0
            events.append(index[i])
    return pd.Index(events, name=index.name)


# ---------------------------------------------------------------------------
# 3. Vertical (time) barrier
# ---------------------------------------------------------------------------


def add_vertical_barrier(close: pd.Series, t_events: pd.Index, *, num_bars: int) -> pd.Series:
    """The vertical barrier ``t1``: the timestamp ``num_bars`` ahead (AFML 3.4).

    For each event start, ``t1`` is the index value ``num_bars`` positions later.
    Events whose vertical barrier would fall past the end of ``close`` are
    dropped (they cannot be fully observed).

    Parameters
    ----------
    close:
        Price series whose index defines the bar calendar.
    t_events:
        Event start timestamps (a subset of ``close.index``).
    num_bars:
        Number of bars ahead for the time barrier. Must be >= 1.

    Returns
    -------
    pd.Series
        ``t1`` indexed by the (observable) event starts; values are timestamps
        from ``close.index``.

    Raises
    ------
    ValueError
        If ``num_bars < 1``.
    """
    if num_bars < 1:
        raise ValueError("num_bars must be >= 1")
    index = close.index
    positions = index.get_indexer(t_events)
    starts = []
    ends = []
    for start_pos in positions:
        if start_pos < 0:
            continue
        end_pos = start_pos + num_bars
        if end_pos < len(index):
            starts.append(index[start_pos])
            ends.append(index[end_pos])
    return pd.Series(ends, index=pd.Index(starts, name=index.name), name="t1")


# ---------------------------------------------------------------------------
# 4. Triple-barrier event times
# ---------------------------------------------------------------------------


def triple_barrier_events(
    close: pd.Series,
    t_events: pd.Index,
    *,
    pt_sl: tuple[float, float],
    target: pd.Series,
    min_ret: float = 0.0,
    vertical_barrier: pd.Series | None = None,
    side: pd.Series | None = None,
) -> pd.DataFrame:
    """First-touch times for the triple-barrier method (AFML snippets 3.2-3.6).

    For each event the upper (profit-take) and lower (stop-loss) horizontal
    barriers are ``+pt_sl[0] * target`` and ``-pt_sl[1] * target`` on the
    (optionally side-adjusted) return path from the event start to its vertical
    barrier. The event's outcome time ``t1`` is the earliest of: the profit-take
    touch, the stop-loss touch, and the vertical barrier.

    Parameters
    ----------
    close:
        Price series (strictly positive), ascending index.
    t_events:
        Event start timestamps (e.g. from :func:`cusum_filter`).
    pt_sl:
        ``(profit_take_mult, stop_loss_mult)``, both >= 0. A multiplier of 0
        disables that horizontal barrier. When ``side`` is None the barriers are
        symmetric and only ``pt_sl[0]`` is used for both.
    target:
        Per-event barrier width in return units (e.g. :func:`daily_volatility`),
        indexed to cover ``t_events``. Events with ``target <= min_ret`` are
        dropped.
    min_ret:
        Minimum target return to keep an event.
    vertical_barrier:
        ``t1`` time barrier per event (see :func:`add_vertical_barrier`). When
        None, the last bar of ``close`` is used as the vertical barrier for all
        events.
    side:
        Optional ``{-1, +1}`` primary-side series (meta-labelling). When given,
        the return path is multiplied by the side before the barriers are
        applied, and the side is carried into the output.

    Returns
    -------
    pd.DataFrame
        Indexed by the retained event starts, with columns ``t1`` (first-touch
        time), ``target``, and -- when ``side`` is provided -- ``side``.

    Raises
    ------
    ValueError
        If either multiplier in ``pt_sl`` is negative.
    """
    if pt_sl[0] < 0.0 or pt_sl[1] < 0.0:
        raise ValueError("pt_sl multipliers must be >= 0")

    # Keep only events with a target above the floor.
    target = target.reindex(t_events)
    target = target[target > min_ret]
    events_index = target.index

    if vertical_barrier is None:
        t1 = pd.Series(close.index[-1], index=events_index, name="t1")
    else:
        t1 = vertical_barrier.reindex(events_index)
        t1 = t1.fillna(close.index[-1])

    if side is None:
        side_ = pd.Series(1.0, index=events_index)
        pt, sl = pt_sl[0], pt_sl[0]
    else:
        side_ = side.reindex(events_index).astype(float)
        pt, sl = pt_sl[0], pt_sl[1]

    upper = pt * target if pt > 0.0 else pd.Series(np.nan, index=events_index)
    lower = -sl * target if sl > 0.0 else pd.Series(np.nan, index=events_index)

    touch_times = []
    for t0 in events_index:
        vbar = t1.loc[t0]
        path = close.loc[t0:vbar]
        path_ret = (path / close.loc[t0] - 1.0) * side_.loc[t0]
        first_pt = _first_breach(path_ret, upper.loc[t0], above=True)
        first_sl = _first_breach(path_ret, lower.loc[t0], above=False)
        touch_times.append(_earliest(first_pt, first_sl, vbar))

    out = pd.DataFrame({"t1": touch_times, "target": target.to_numpy()}, index=events_index)
    if side is not None:
        out["side"] = side_
    return out


def _first_breach(path_ret: pd.Series, level: float, *, above: bool) -> Any:
    """Earliest index where ``path_ret`` crosses ``level`` (NaT if never / no barrier)."""
    if not np.isfinite(level):
        return pd.NaT
    hit = path_ret[path_ret >= level] if above else path_ret[path_ret <= level]
    if hit.empty:
        return pd.NaT
    return hit.index[0]


def _earliest(*times: Any) -> Any:
    """Earliest non-NaT timestamp among the arguments."""
    valid = [t for t in times if not pd.isna(t)]
    return min(valid)


# ---------------------------------------------------------------------------
# 5. Labels from first-touch times
# ---------------------------------------------------------------------------


def get_bins(events: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    """Realised return and label for each triple-barrier event (AFML snippet 3.5/3.7).

    The realised return is ``close[t1] / close[t0] - 1``. When the events carry a
    ``side`` (meta-labelling) the return is multiplied by it and the label is
    ``{0, 1}`` -- 1 iff acting on the primary side made money. Without a side the
    label is the sign of the return, in ``{-1, 0, +1}`` (direction).

    Parameters
    ----------
    events:
        Output of :func:`triple_barrier_events` (must contain ``t1``; may contain
        ``side``).
    close:
        The same price series used to build ``events``.

    Returns
    -------
    pd.DataFrame
        Indexed by event start, with columns ``ret`` (realised return) and
        ``bin`` (the label).
    """
    starts = events.index
    t1 = events["t1"]
    px0 = close.reindex(starts).to_numpy(dtype=float)
    px1 = close.reindex(pd.Index(t1.to_numpy())).to_numpy(dtype=float)
    ret = px1 / px0 - 1.0

    if "side" in events.columns:
        ret = ret * events["side"].to_numpy(dtype=float)
        bins = (ret > 0.0).astype(float)
    else:
        bins = np.sign(ret)

    return pd.DataFrame({"ret": ret, "bin": bins}, index=starts)
