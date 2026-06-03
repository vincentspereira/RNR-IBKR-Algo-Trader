"""Tests for purged / embargoed cross-validation (AFML ch. 7).

The headline test is the *no-leakage property*: for every fold produced by
:class:`PurgedKFold`, no training label window overlaps the fold's test window.
That is the entire point of purging, and it is checked directly rather than by a
proxy. Around it:

* purged_train_times -- exact purge on a known disjoint layout.
* PurgedKFold -- construction validation, the splitter protocol, the embargo band
  removal, and that the test folds partition the observations.
* purged_cv_score -- per-fold scores for each metric, the sample-weight path, and
  the unknown-metric error, using a real random forest on a separable problem.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.cross_validation import (
    PurgedKFold,
    purged_cv_score,
    purged_train_times,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _overlapping_panel(
    n_events: int = 24, horizon: int = 3
) -> tuple[pd.DataFrame, pd.Series]:
    """Events at every bar with a fixed ``horizon``-bar label span.

    The bar calendar extends ``horizon`` bars beyond the last event so every
    label closes on a real (later) bar -- the realistic setup in which label ends
    are not themselves event starts near the tail.
    """
    cal = _bdays(n_events + horizon)
    starts = cal[:n_events]
    ends = cal[horizon : n_events + horizon]
    t1 = pd.Series(ends, index=starts, name="t1")
    x = pd.DataFrame({"f": np.arange(n_events, dtype=float)}, index=starts)
    return x, t1


# ---------------------------------------------------------------------------
# purged_train_times
# ---------------------------------------------------------------------------


class TestPurgedTrainTimes:
    def test_purges_all_overlap_modes(self) -> None:
        bars = _bdays(10)
        t1 = pd.Series(
            [bars[1], bars[3], bars[5], bars[7], bars[9]],
            index=[bars[0], bars[2], bars[4], bars[6], bars[8]],
        )
        test_times = pd.Series([bars[6]], index=[bars[3]])  # test period [d3, d6]
        train = purged_train_times(t1, test_times)
        # d2->d3 ends inside, d4->d5 starts inside, d6->d7 starts inside -> purged;
        # d0->d1 and d8->d9 are clear of [d3, d6] -> kept.
        assert list(train.index) == [bars[0], bars[8]]


# ---------------------------------------------------------------------------
# PurgedKFold -- construction and protocol
# ---------------------------------------------------------------------------


class TestPurgedKFoldConstruction:
    def test_n_splits_validation(self) -> None:
        _, t1 = _overlapping_panel()
        with pytest.raises(ValueError, match="n_splits must be >= 2"):
            PurgedKFold(1, t1=t1)

    def test_embargo_validation(self) -> None:
        _, t1 = _overlapping_panel()
        with pytest.raises(ValueError, match="embargo_pct must be in"):
            PurgedKFold(4, t1=t1, embargo_pct=1.0)

    def test_non_monotonic_t1_index_raises(self) -> None:
        _, t1 = _overlapping_panel()
        shuffled = t1.iloc[::-1]
        with pytest.raises(ValueError, match="t1 index must be ascending"):
            PurgedKFold(4, t1=shuffled)

    def test_get_n_splits(self) -> None:
        _, t1 = _overlapping_panel()
        assert PurgedKFold(4, t1=t1).get_n_splits() == 4

    def test_split_requires_matching_index(self) -> None:
        x, t1 = _overlapping_panel()
        cv = PurgedKFold(4, t1=t1)
        wrong = x.copy()
        wrong.index = _bdays(len(x)) + pd.Timedelta(days=30)
        with pytest.raises(ValueError, match="x index must match"):
            list(cv.split(wrong))


# ---------------------------------------------------------------------------
# PurgedKFold -- the no-leakage property
# ---------------------------------------------------------------------------


class TestPurgedKFoldNoLeakage:
    def test_no_train_label_overlaps_test_window(self) -> None:
        x, t1 = _overlapping_panel(n_events=24, horizon=3)
        cv = PurgedKFold(4, t1=t1)
        starts = t1.index
        seen_test: list[int] = []
        for train_idx, test_idx in cv.split(x):
            seen_test.extend(test_idx.tolist())
            test_start = starts[test_idx[0]]
            test_end = t1.iloc[test_idx].max()
            for tr in train_idx:
                train_start = starts[tr]
                train_end = t1.iloc[tr]
                # safe iff the training span lies entirely before or after the
                # test window (touching the boundary is allowed, per de Prado).
                assert train_end <= test_start or train_start >= test_end
        # every observation is tested exactly once -> folds partition the data.
        assert sorted(seen_test) == list(range(len(x)))

    def test_embargo_removes_post_fold_band(self) -> None:
        x, t1 = _overlapping_panel(n_events=24, horizon=3)
        no_embargo = next(iter(PurgedKFold(4, t1=t1, embargo_pct=0.0).split(x)))
        with_embargo = next(iter(PurgedKFold(4, t1=t1, embargo_pct=0.1).split(x)))
        train_no, _ = no_embargo
        train_emb, _ = with_embargo
        # fold 0's right block starts at index 8; a 10% embargo (2 bars) drops 8, 9.
        assert 8 in train_no and 9 in train_no
        assert 8 not in train_emb and 9 not in train_emb


# ---------------------------------------------------------------------------
# purged_cv_score
# ---------------------------------------------------------------------------


def _separable_panel(n: int = 40) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    cal = _bdays(n + 1)
    starts = cal[:n]
    labels = np.tile([0, 1], n // 2)
    t1 = pd.Series(cal[1 : n + 1], index=starts, name="t1")  # 1-bar horizon
    x = pd.DataFrame({"f": labels.astype(float)}, index=starts)
    y = pd.Series(labels, index=starts, name="bin")
    return x, y, t1


def _forest() -> object:
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(n_estimators=20, random_state=0)


class TestPurgedCvScore:
    def test_neg_log_loss_default(self) -> None:
        x, y, t1 = _separable_panel()
        scores = purged_cv_score(_forest(), x, y, t1=t1, n_splits=4)
        assert scores.shape == (4,)
        assert np.isfinite(scores).all()
        assert (scores <= 0.0).all()  # negative log loss

    def test_accuracy_on_separable_is_perfect(self) -> None:
        x, y, t1 = _separable_panel()
        scores = purged_cv_score(_forest(), x, y, t1=t1, n_splits=4, scoring="accuracy")
        assert (scores >= 0.9).all()

    def test_f1_metric_path(self) -> None:
        x, y, t1 = _separable_panel()
        scores = purged_cv_score(_forest(), x, y, t1=t1, n_splits=4, scoring="f1")
        assert scores.shape == (4,)
        assert np.isfinite(scores).all()

    def test_sample_weight_path(self) -> None:
        x, y, t1 = _separable_panel()
        weights = pd.Series(np.linspace(0.5, 1.5, len(x)), index=x.index)
        scores = purged_cv_score(
            _forest(), x, y, t1=t1, n_splits=4, scoring="accuracy", sample_weight=weights
        )
        assert scores.shape == (4,)
        assert np.isfinite(scores).all()

    def test_unknown_scoring_raises(self) -> None:
        x, y, t1 = _separable_panel()
        with pytest.raises(ValueError, match="unknown scoring"):
            purged_cv_score(_forest(), x, y, t1=t1, n_splits=4, scoring="bogus")
