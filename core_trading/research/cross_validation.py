"""Leakage-free cross-validation (master plan Phase 2.4).

Financial ML cross-validation must respect that (a) labels span time (a label
observed at ``t`` may only be realised at ``t1 > t``), and (b) serial
correlation leaks information across adjacent samples. Naive k-fold therefore
overstates out-of-sample skill. This module implements the de Prado toolkit
(*Advances in Financial Machine Learning*, ch. 7 & 12):

* :func:`make_label_end_times` -- build label-span series (``t1``) from a bar
  index and a horizon.
* :class:`PurgedKFold` -- k-fold that **purges** training samples whose label
  span overlaps the test window and **embargoes** samples immediately after it.
* :class:`CombinatorialPurgedCV` -- CPCV: tests ``k`` of ``N`` groups in every
  combination, yielding many backtest paths instead of one.
* :class:`WalkForwardSplit` -- anchored or rolling walk-forward with an embargo
  gap.

All splitters yield :class:`CVSplit` objects carrying **positional** integer
index arrays, so callers slice with ``X[split.train_indices]`` regardless of the
original pandas index.
"""
from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

__all__ = [
    "CVSplit",
    "make_label_end_times",
    "PurgedKFold",
    "CombinatorialPurgedCV",
    "WalkForwardSplit",
]


@dataclass(frozen=True, slots=True)
class CVSplit:
    """One train/test split, as positional integer indices.

    ``test_groups`` is populated only by :class:`CombinatorialPurgedCV` and lists
    the group ids that make up the test set for this combination.
    """

    train_indices: np.ndarray
    test_indices: np.ndarray
    test_groups: tuple[int, ...] = ()


def _as_datetime_index(event_times: Sequence | pd.Index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(event_times)
    if not idx.is_monotonic_increasing:
        raise ValueError("event_times must be sorted ascending")
    return idx


def make_label_end_times(
    event_times: Sequence | pd.Index,
    horizon: int | pd.Timedelta,
) -> pd.Series:
    """Build a label-span series ``t1`` from bar times and a horizon.

    The label for the sample observed at ``event_times[i]`` is realised after
    ``horizon``. ``horizon`` may be an integer number of bars or a
    :class:`pandas.Timedelta`. The last labels, which would extend past the end
    of the sample, are clipped to the final bar.

    Returns a Series indexed by ``event_times`` whose values are the label-end
    timestamps -- the input expected by every splitter here.
    """
    idx = _as_datetime_index(event_times)
    if isinstance(horizon, int):
        if horizon < 1:
            raise ValueError("integer horizon must be >= 1 bar")
        end_pos = np.minimum(np.arange(len(idx)) + horizon, len(idx) - 1)
        return pd.Series(idx[end_pos], index=idx)
    ends = idx + horizon
    clipped = ends.where(ends <= idx[-1], idx[-1])
    return pd.Series(clipped, index=idx)


def _default_t1(event_times: pd.DatetimeIndex) -> pd.Series:
    """Trivial label spans: each label ends at its own bar (no overlap)."""
    return pd.Series(event_times, index=event_times)


def _purge_and_embargo(
    n: int,
    test_pos: np.ndarray,
    event_vals: np.ndarray,
    t1_vals: np.ndarray,
    embargo: int,
) -> np.ndarray:
    """Return the positional train indices after purge + embargo for one block.

    A train sample is purged when its label span ``[event, t1]`` overlaps the
    test window ``[test_start, test_end]``. After the test block, ``embargo``
    further samples are dropped to break serial-correlation leakage.
    """
    test_start = event_vals[test_pos[0]]
    test_end = t1_vals[test_pos].max()

    keep = np.ones(n, dtype=bool)
    keep[test_pos] = False
    overlap = ~((t1_vals < test_start) | (event_vals > test_end))
    keep &= ~overlap

    if embargo > 0:
        last = int(test_pos[-1])
        keep[last + 1 : min(last + 1 + embargo, n)] = False
    return np.flatnonzero(keep)


class PurgedKFold:
    """k-fold cross-validation with purging and embargo.

    Parameters
    ----------
    n_splits:
        Number of contiguous test folds.
    embargo_pct:
        Fraction of the sample embargoed immediately after each test fold.
    """

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if not 0.0 <= embargo_pct < 1.0:
            raise ValueError("embargo_pct must be in [0, 1)")
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def get_n_splits(self) -> int:
        return self.n_splits

    def split(
        self,
        event_times: Sequence | pd.Index,
        label_end_times: pd.Series | None = None,
    ) -> Iterator[CVSplit]:
        """Yield :class:`CVSplit` objects (positional indices)."""
        idx = _as_datetime_index(event_times)
        n = len(idx)
        if n < self.n_splits:
            raise ValueError("fewer observations than n_splits")
        t1 = _default_t1(idx) if label_end_times is None else label_end_times
        if len(t1) != n:
            raise ValueError("label_end_times length must match event_times")

        event_vals = idx.values
        t1_vals = pd.DatetimeIndex(t1.values).values
        embargo = int(n * self.embargo_pct)

        for fold in np.array_split(np.arange(n), self.n_splits):
            test_pos = np.asarray(fold)
            if test_pos.size == 0:
                continue
            train_pos = _purge_and_embargo(n, test_pos, event_vals, t1_vals, embargo)
            yield CVSplit(train_indices=train_pos, test_indices=test_pos)


class CombinatorialPurgedCV:
    """Combinatorial Purged Cross-Validation (de Prado, AFML ch. 12).

    Splits the sample into ``n_groups`` contiguous groups and, in every
    combination, uses ``n_test_groups`` of them as the test set (the rest train,
    purged and embargoed). This yields ``C(n_groups, n_test_groups)``
    combinations and reconstructs ``C(n_groups-1, n_test_groups-1)`` distinct
    backtest paths -- a *distribution* of out-of-sample performance rather than
    a single number.
    """

    def __init__(
        self,
        n_groups: int = 6,
        n_test_groups: int = 2,
        embargo_pct: float = 0.01,
    ) -> None:
        if n_groups < 3:
            raise ValueError("n_groups must be >= 3")
        if not 1 <= n_test_groups < n_groups:
            raise ValueError("n_test_groups must be in [1, n_groups)")
        if not 0.0 <= embargo_pct < 1.0:
            raise ValueError("embargo_pct must be in [0, 1)")
        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.embargo_pct = embargo_pct

    @property
    def num_combinations(self) -> int:
        return math.comb(self.n_groups, self.n_test_groups)

    @property
    def n_paths(self) -> int:
        """Number of distinct backtest paths reconstructable from the splits."""
        return math.comb(self.n_groups - 1, self.n_test_groups - 1)

    def split(
        self,
        event_times: Sequence | pd.Index,
        label_end_times: pd.Series | None = None,
    ) -> Iterator[CVSplit]:
        idx = _as_datetime_index(event_times)
        n = len(idx)
        if n < self.n_groups:
            raise ValueError("fewer observations than n_groups")
        t1 = _default_t1(idx) if label_end_times is None else label_end_times
        if len(t1) != n:
            raise ValueError("label_end_times length must match event_times")

        event_vals = idx.values
        t1_vals = pd.DatetimeIndex(t1.values).values
        embargo = int(n * self.embargo_pct)
        groups = np.array_split(np.arange(n), self.n_groups)

        for combo in combinations(range(self.n_groups), self.n_test_groups):
            test_blocks = [groups[g] for g in combo]
            test_pos = np.concatenate(test_blocks)
            test_pos.sort()

            # Purge/embargo against every contiguous test block, then intersect.
            keep = np.ones(n, dtype=bool)
            keep[test_pos] = False
            for block in test_blocks:
                block = np.asarray(block)
                if block.size == 0:
                    continue
                block_train = _purge_and_embargo(n, block, event_vals, t1_vals, embargo)
                block_keep = np.zeros(n, dtype=bool)
                block_keep[block_train] = True
                keep &= block_keep
            train_pos = np.flatnonzero(keep)
            yield CVSplit(
                train_indices=train_pos,
                test_indices=test_pos,
                test_groups=tuple(combo),
            )


class WalkForwardSplit:
    """Anchored or rolling walk-forward splits with an embargo gap.

    Parameters
    ----------
    n_splits:
        Number of successive test windows.
    test_size:
        Size of each test window, in bars. If ``None``, the sample after the
        initial training window is divided evenly into ``n_splits`` windows.
    train_size:
        Rolling training-window size in bars. Required when ``anchored`` is
        False; ignored when ``anchored`` is True.
    anchored:
        When True the training window starts at 0 and expands; when False it
        rolls with a fixed ``train_size``.
    embargo:
        Bars to skip between the end of training and the start of the test
        window (prevents label leakage across the boundary).
    """

    def __init__(
        self,
        n_splits: int = 5,
        *,
        test_size: int | None = None,
        train_size: int | None = None,
        anchored: bool = True,
        embargo: int = 0,
    ) -> None:
        if n_splits < 1:
            raise ValueError("n_splits must be >= 1")
        if not anchored and train_size is None:
            raise ValueError("rolling walk-forward requires train_size")
        if embargo < 0:
            raise ValueError("embargo must be >= 0")
        self.n_splits = n_splits
        self.test_size = test_size
        self.train_size = train_size
        self.anchored = anchored
        self.embargo = embargo

    def get_n_splits(self) -> int:
        return self.n_splits

    def split(
        self,
        event_times: Sequence | pd.Index,
        label_end_times: pd.Series | None = None,  # noqa: ARG002 - interface parity
    ) -> Iterator[CVSplit]:
        # ``label_end_times`` is accepted so every splitter shares one signature
        # and is interchangeable; walk-forward uses a bar-count embargo gap
        # rather than label-span purging, so it does not consult ``t1``.
        idx = _as_datetime_index(event_times)
        n = len(idx)

        if self.test_size is not None:
            test_size = self.test_size
            min_train = self.train_size if not self.anchored else test_size
            if min_train + self.embargo + test_size > n:
                raise ValueError("window sizes exceed the sample length")
            first_test_start = min_train + self.embargo
        else:
            # Reserve the first chunk for training, divide the rest evenly.
            reserve = self.train_size if not self.anchored else max(n // (self.n_splits + 1), 1)
            usable = n - reserve - self.embargo
            if usable < self.n_splits:
                raise ValueError("sample too small for the requested n_splits")
            test_size = usable // self.n_splits
            first_test_start = reserve + self.embargo

        positions = np.arange(n)
        test_start = first_test_start
        produced = 0
        while produced < self.n_splits:
            test_end = test_start + test_size
            if test_end > n:
                break
            test_pos = positions[test_start:test_end]
            train_end = test_start - self.embargo
            if self.anchored:
                train_pos = positions[0:train_end]
            else:
                train_start = max(train_end - self.train_size, 0)
                train_pos = positions[train_start:train_end]
            if train_pos.size == 0:
                raise ValueError("empty training window; check sizes/embargo")
            yield CVSplit(train_indices=train_pos, test_indices=test_pos)
            produced += 1
            test_start = test_end
