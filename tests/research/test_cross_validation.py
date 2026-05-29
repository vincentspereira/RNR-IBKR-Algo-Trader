"""Tests for core_trading.research.cross_validation.

Leakage prevention is verified structurally: for every split we assert that no
training sample's label span overlaps the test window (purge) and that the
embargo zone immediately after each test block is empty.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.research import cross_validation as cv


@pytest.fixture
def times() -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=200, freq="D", tz="UTC")


def _no_overlap(train: np.ndarray, test: np.ndarray) -> bool:
    return len(np.intersect1d(train, test)) == 0


class TestMakeLabelEndTimes:
    def test_integer_horizon(self, times) -> None:
        t1 = cv.make_label_end_times(times, 5)
        assert len(t1) == len(times)
        # label for bar i ends at bar i+5 (clipped at the end)
        assert t1.iloc[0] == times[5]
        assert t1.iloc[-1] == times[-1]

    def test_timedelta_horizon(self, times) -> None:
        t1 = cv.make_label_end_times(times, pd.Timedelta(days=10))
        assert t1.iloc[0] == times[10]
        assert t1.iloc[-1] == times[-1]  # clipped

    def test_bad_integer_horizon(self, times) -> None:
        with pytest.raises(ValueError):
            cv.make_label_end_times(times, 0)

    def test_unsorted_raises(self) -> None:
        idx = pd.DatetimeIndex(["2020-01-03", "2020-01-01"], tz="UTC")
        with pytest.raises(ValueError):
            cv.make_label_end_times(idx, 1)


class TestPurgedKFold:
    def test_split_count(self, times) -> None:
        splits = list(cv.PurgedKFold(n_splits=5).split(times))
        assert len(splits) == 5

    def test_test_folds_partition_sample(self, times) -> None:
        splits = list(cv.PurgedKFold(n_splits=5, embargo_pct=0.0).split(times))
        all_test = np.concatenate([s.test_indices for s in splits])
        assert sorted(all_test.tolist()) == list(range(len(times)))

    def test_train_test_disjoint(self, times) -> None:
        for s in cv.PurgedKFold(n_splits=5).split(times):
            assert _no_overlap(s.train_indices, s.test_indices)

    def test_purge_removes_overlapping_labels(self, times) -> None:
        t1 = cv.make_label_end_times(times, 10)
        event_vals = times.values
        t1_vals = pd.DatetimeIndex(t1.values).values
        for s in cv.PurgedKFold(n_splits=5, embargo_pct=0.0).split(times, t1):
            test_start = event_vals[s.test_indices[0]]
            test_end = t1_vals[s.test_indices].max()
            for p in s.train_indices:
                overlaps = not (t1_vals[p] < test_start or event_vals[p] > test_end)
                assert not overlaps

    def test_embargo_zone_empty(self, times) -> None:
        embargo_pct = 0.05
        embargo = int(len(times) * embargo_pct)
        for s in cv.PurgedKFold(n_splits=5, embargo_pct=embargo_pct).split(times):
            last = int(s.test_indices[-1])
            zone = set(range(last + 1, min(last + 1 + embargo, len(times))))
            assert zone.isdisjoint(set(s.train_indices.tolist()))

    def test_invalid_n_splits(self) -> None:
        with pytest.raises(ValueError):
            cv.PurgedKFold(n_splits=1)

    def test_invalid_embargo(self) -> None:
        with pytest.raises(ValueError):
            cv.PurgedKFold(embargo_pct=1.0)

    def test_more_splits_than_obs(self) -> None:
        idx = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
        with pytest.raises(ValueError):
            list(cv.PurgedKFold(n_splits=5).split(idx))

    def test_label_length_mismatch(self, times) -> None:
        with pytest.raises(ValueError):
            list(cv.PurgedKFold().split(times, pd.Series([1, 2, 3])))

    def test_get_n_splits(self) -> None:
        assert cv.PurgedKFold(n_splits=7).get_n_splits() == 7


class TestCombinatorialPurgedCV:
    def test_num_combinations(self) -> None:
        c = cv.CombinatorialPurgedCV(n_groups=6, n_test_groups=2)
        assert c.num_combinations == math.comb(6, 2)

    def test_n_paths(self) -> None:
        c = cv.CombinatorialPurgedCV(n_groups=6, n_test_groups=2)
        assert c.n_paths == math.comb(5, 1)

    def test_split_count_matches_combinations(self, times) -> None:
        c = cv.CombinatorialPurgedCV(n_groups=6, n_test_groups=2, embargo_pct=0.0)
        assert len(list(c.split(times))) == c.num_combinations

    def test_test_groups_recorded(self, times) -> None:
        c = cv.CombinatorialPurgedCV(n_groups=6, n_test_groups=2, embargo_pct=0.0)
        for s in c.split(times):
            assert len(s.test_groups) == 2
            assert _no_overlap(s.train_indices, s.test_indices)

    def test_purge_applied(self, times) -> None:
        n = len(times)
        n_groups = 6
        t1 = cv.make_label_end_times(times, 8)
        event_vals = times.values
        t1_vals = pd.DatetimeIndex(t1.values).values
        groups = np.array_split(np.arange(n), n_groups)
        c = cv.CombinatorialPurgedCV(n_groups=n_groups, n_test_groups=2, embargo_pct=0.0)
        for s in c.split(times, t1):
            test_set = set(s.test_indices.tolist())
            # CPCV purges against EACH contiguous test block independently.
            blocks = [groups[g] for g in s.test_groups]
            for p in s.train_indices:
                assert p not in test_set
                for block in blocks:
                    b_start = event_vals[block[0]]
                    b_end = t1_vals[block].max()
                    overlaps = not (t1_vals[p] < b_start or event_vals[p] > b_end)
                    assert not overlaps

    def test_invalid_groups(self) -> None:
        with pytest.raises(ValueError):
            cv.CombinatorialPurgedCV(n_groups=2)

    def test_invalid_test_groups(self) -> None:
        with pytest.raises(ValueError):
            cv.CombinatorialPurgedCV(n_groups=6, n_test_groups=6)

    def test_invalid_embargo(self) -> None:
        with pytest.raises(ValueError):
            cv.CombinatorialPurgedCV(embargo_pct=-0.1)

    def test_fewer_obs_than_groups(self) -> None:
        idx = pd.date_range("2020-01-01", periods=4, freq="D", tz="UTC")
        with pytest.raises(ValueError):
            list(cv.CombinatorialPurgedCV(n_groups=6).split(idx))

    def test_label_length_mismatch(self, times) -> None:
        with pytest.raises(ValueError):
            list(cv.CombinatorialPurgedCV().split(times, pd.Series([1, 2, 3])))


class TestWalkForwardSplit:
    def test_anchored_train_grows(self, times) -> None:
        splits = list(cv.WalkForwardSplit(n_splits=4, test_size=20, anchored=True).split(times))
        assert len(splits) == 4
        train_lengths = [len(s.train_indices) for s in splits]
        assert train_lengths == sorted(train_lengths)
        assert train_lengths[0] < train_lengths[-1]

    def test_rolling_train_fixed(self, times) -> None:
        splits = list(
            cv.WalkForwardSplit(n_splits=4, test_size=20, train_size=50, anchored=False).split(
                times
            )
        )
        assert all(len(s.train_indices) == 50 for s in splits)

    def test_train_before_test(self, times) -> None:
        for s in cv.WalkForwardSplit(n_splits=4, test_size=20).split(times):
            assert s.train_indices.max() < s.test_indices.min()

    def test_embargo_gap(self, times) -> None:
        embargo = 5
        for s in cv.WalkForwardSplit(n_splits=3, test_size=20, embargo=embargo).split(times):
            gap = s.test_indices.min() - s.train_indices.max() - 1
            assert gap >= embargo

    def test_auto_test_size(self, times) -> None:
        splits = list(cv.WalkForwardSplit(n_splits=5).split(times))
        assert len(splits) == 5
        assert all(_no_overlap(s.train_indices, s.test_indices) for s in splits)

    def test_rolling_requires_train_size(self) -> None:
        with pytest.raises(ValueError):
            cv.WalkForwardSplit(anchored=False)

    def test_invalid_n_splits(self) -> None:
        with pytest.raises(ValueError):
            cv.WalkForwardSplit(n_splits=0)

    def test_negative_embargo(self) -> None:
        with pytest.raises(ValueError):
            cv.WalkForwardSplit(embargo=-1)

    def test_windows_exceed_sample(self, times) -> None:
        with pytest.raises(ValueError):
            list(cv.WalkForwardSplit(n_splits=3, test_size=500).split(times))

    def test_auto_test_size_too_many_splits(self) -> None:
        idx = pd.date_range("2020-01-01", periods=10, freq="D", tz="UTC")
        with pytest.raises(ValueError):
            list(cv.WalkForwardSplit(n_splits=20).split(idx))

    def test_early_break_yields_fewer(self, times) -> None:
        # Requesting more windows than fit yields as many as possible, no error.
        splits = list(cv.WalkForwardSplit(n_splits=50, test_size=20).split(times))
        assert 0 < len(splits) < 50

    def test_rolling_auto_test_size(self, times) -> None:
        splits = list(cv.WalkForwardSplit(n_splits=4, train_size=60, anchored=False).split(times))
        assert all(len(s.train_indices) == 60 for s in splits)

    def test_get_n_splits(self) -> None:
        assert cv.WalkForwardSplit(n_splits=6).get_n_splits() == 6


class TestCVSplit:
    def test_default_test_groups_empty(self) -> None:
        s = cv.CVSplit(train_indices=np.array([0, 1]), test_indices=np.array([2]))
        assert s.test_groups == ()
