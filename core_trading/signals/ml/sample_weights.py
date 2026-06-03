"""Sample-uniqueness weights for overlapping labels (Phase 5.D, AFML ch. 4).

The triple-barrier labels of :mod:`core_trading.signals.ml.labeling` are *not*
IID: a label spans ``[t0, t1]`` and overlaps its neighbours, so two events that
share most of their outcome window carry almost the same information. Training a
classifier as if every label were an independent draw over-counts those
overlapping observations and inflates the apparent sample size.

This module supplies Lopez de Prado's correction (AFML ch. 4): weight each label
by how *uniquely* it observes its return, so overlapping labels share the credit
for the bars they have in common. The weights feed directly into the
``sample_weight`` argument of
:meth:`core_trading.signals.ml.meta_labelling.MetaLabeler.fit` and of
:func:`core_trading.signals.ml.cross_validation.purged_cv_score`.

Components
----------
1. :func:`num_concurrent_events` -- how many labels are *live* at each bar
   (AFML snippet 4.1). The denominator for every uniqueness calculation.
2. :func:`average_uniqueness` -- per label, the average of ``1 / concurrency``
   over its span (AFML snippet 4.2): 1.0 when the label never overlaps another,
   shrinking towards 0 as overlap grows.
3. :func:`return_attribution_weights` -- per label, the absolute
   concurrency-adjusted log return it accrues over its span (AFML snippet 4.10);
   labels spanning larger unique moves get more weight.
4. :func:`time_decay_weights` -- an optional linear time decay over cumulative
   uniqueness (AFML snippet 4.11) so older observations count for less, with the
   newest fixed at weight 1.

All functions are pure ``pandas`` / ``numpy``; the ``t1`` input is the
first-touch series produced by
:func:`core_trading.signals.ml.labeling.triple_barrier_events` (its ``t1``
column): index = event start, value = event end.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 4 (Sample Weights), snippets 4.1, 4.2, 4.10, 4.11.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "num_concurrent_events",
    "average_uniqueness",
    "return_attribution_weights",
    "time_decay_weights",
]


# ---------------------------------------------------------------------------
# 1. Concurrency: how many labels are live at each bar
# ---------------------------------------------------------------------------


def num_concurrent_events(bar_index: pd.Index, t1: pd.Series) -> pd.Series:
    """Count the labels live at each bar (AFML snippet 4.1).

    A label with span ``[t0, t1]`` is *live* on every bar in that closed
    interval. The count is taken over the bars actually spanned by some label
    (from the earliest event start to the latest event end).

    Parameters
    ----------
    bar_index:
        The full ascending bar calendar (e.g. ``close.index``).
    t1:
        First-touch series: index = event start, value = event end. NaT ends are
        dropped (an unobservable label cannot be concurrent).

    Returns
    -------
    pd.Series
        Integer concurrency indexed by the spanned subset of ``bar_index``.

    Raises
    ------
    ValueError
        If ``t1`` is empty after dropping NaT ends.
    """
    t1 = t1.dropna()
    if t1.empty:
        raise ValueError("t1 must contain at least one observable event")

    first = t1.index[0]
    last = t1.max()
    iloc = bar_index.searchsorted([first, last])
    span = bar_index[iloc[0] : iloc[1] + 1]
    count = pd.Series(0, index=span, name="concurrency")
    for t_in, t_out in t1.items():
        count.loc[t_in:t_out] += 1
    return count


# ---------------------------------------------------------------------------
# 2. Average uniqueness per label
# ---------------------------------------------------------------------------


def average_uniqueness(t1: pd.Series, num_co_events: pd.Series) -> pd.Series:
    """Average ``1 / concurrency`` over each label's span (AFML snippet 4.2).

    A label that never overlaps another scores 1.0; heavily overlapped labels
    tend towards 0.

    Parameters
    ----------
    t1:
        First-touch series (index = event start, value = event end).
    num_co_events:
        Concurrency from :func:`num_concurrent_events`, covering every label
        span.

    Returns
    -------
    pd.Series
        Average uniqueness in ``(0, 1]`` indexed by event start.
    """
    out = pd.Series(index=t1.index, dtype=float, name="uniqueness")
    for t_in, t_out in t1.dropna().items():
        out.loc[t_in] = float((1.0 / num_co_events.loc[t_in:t_out]).mean())
    return out


# ---------------------------------------------------------------------------
# 3. Return-attribution weights
# ---------------------------------------------------------------------------


def return_attribution_weights(
    t1: pd.Series,
    num_co_events: pd.Series,
    close: pd.Series,
    *,
    normalize: bool = True,
) -> pd.Series:
    """Concurrency-adjusted absolute return accrued by each label (AFML 4.10).

    Each bar's log return is split among the labels live on it (divided by the
    concurrency), then summed over the label's span and taken in absolute value:
    a label that uniquely spans a large move gets more weight than one whose move
    was shared with many overlapping labels.

    Parameters
    ----------
    t1:
        First-touch series (index = event start, value = event end).
    num_co_events:
        Concurrency from :func:`num_concurrent_events`.
    close:
        Price series (strictly positive) used to compute log returns.
    normalize:
        When True the weights are rescaled to average 1 (sum to the number of
        events), the scale scikit-learn's ``sample_weight`` expects.

    Returns
    -------
    pd.Series
        Non-negative weights indexed by event start.
    """
    log_ret = np.log(close).diff()
    out = pd.Series(index=t1.index, dtype=float, name="weight")
    for t_in, t_out in t1.dropna().items():
        out.loc[t_in] = float((log_ret.loc[t_in:t_out] / num_co_events.loc[t_in:t_out]).sum())
    out = out.abs()
    total = float(out.sum())
    if normalize and total > 0.0:
        out *= out.shape[0] / total
    return out


# ---------------------------------------------------------------------------
# 4. Time-decay weights
# ---------------------------------------------------------------------------


def time_decay_weights(av_uniqueness: pd.Series, *, last_weight: float = 1.0) -> pd.Series:
    """Linear time decay over cumulative uniqueness (AFML snippet 4.11).

    The newest observation always has weight 1; the oldest has weight
    ``last_weight``. ``last_weight = 1`` disables the decay (all weights 1);
    ``last_weight = 0`` decays the oldest observation to (near) 0; a negative
    ``last_weight`` zeroes out the oldest fraction of observations entirely.

    Parameters
    ----------
    av_uniqueness:
        Average uniqueness per event from :func:`average_uniqueness`.
    last_weight:
        Decay target for the oldest observation, in ``(-1, 1]``.

    Returns
    -------
    pd.Series
        Non-negative time-decay weights indexed (and ordered) by event start.

    Raises
    ------
    ValueError
        If ``last_weight`` is not in ``(-1, 1]``.
    """
    if not -1.0 < last_weight <= 1.0:
        raise ValueError("last_weight must be in (-1, 1]")

    cum = av_uniqueness.sort_index().cumsum()
    final = float(cum.iloc[-1])
    if last_weight >= 0.0:
        slope = (1.0 - last_weight) / final
    else:
        slope = 1.0 / ((last_weight + 1.0) * final)
    const = 1.0 - slope * final
    decay = const + slope * cum
    decay[decay < 0.0] = 0.0
    decay.name = "time_decay"
    return decay
