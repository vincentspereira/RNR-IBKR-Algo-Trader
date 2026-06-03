"""Parameter-recovery tests for the AFML ch. 4 sample-uniqueness weights.

Every quantity is hand-computed on tiny, fully-specified label layouts:

* num_concurrent_events -- exact concurrency on a known overlap pattern.
* average_uniqueness -- the mean of 1/concurrency over each label's span.
* return_attribution_weights -- concurrency-split log returns with a hand-checked
  normalised 1:2 ratio, plus the all-zero (constant price) guard.
* time_decay_weights -- the linear decay recovered exactly for last_weight in
  {1 (no decay), 0.5, 0 (decay to zero), -0.5 (oldest observations zeroed)}.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.sample_weights import (
    average_uniqueness,
    num_concurrent_events,
    return_attribution_weights,
    time_decay_weights,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


# ---------------------------------------------------------------------------
# num_concurrent_events
# ---------------------------------------------------------------------------


class TestNumConcurrentEvents:
    def test_empty_after_dropna_raises(self) -> None:
        bars = _bdays(5)
        t1 = pd.Series([pd.NaT, pd.NaT], index=bars[:2])
        with pytest.raises(ValueError, match="at least one observable event"):
            num_concurrent_events(bars, t1)

    def test_non_overlapping_is_one(self) -> None:
        bars = _bdays(6)
        t1 = pd.Series([bars[1], bars[4]], index=[bars[0], bars[3]])
        count = num_concurrent_events(bars, t1)
        # bars 0-1 covered by label A, 3-4 by label B; bar 2 by neither.
        assert count.loc[bars[0]] == 1
        assert count.loc[bars[1]] == 1
        assert count.loc[bars[2]] == 0
        assert count.loc[bars[3]] == 1

    def test_overlap_counts_exactly(self) -> None:
        bars = _bdays(7)
        t1 = pd.Series([bars[2], bars[4], bars[5]], index=[bars[0], bars[1], bars[3]])
        count = num_concurrent_events(bars, t1)
        # span is bars 0..5 (first start to last end); bar 6 excluded.
        assert list(count.to_numpy()) == [1, 2, 2, 2, 2, 1]
        assert list(count.index) == list(bars[:6])


# ---------------------------------------------------------------------------
# average_uniqueness
# ---------------------------------------------------------------------------


class TestAverageUniqueness:
    def test_recovers_hand_computed(self) -> None:
        bars = _bdays(7)
        t1 = pd.Series([bars[2], bars[4], bars[5]], index=[bars[0], bars[1], bars[3]])
        co = num_concurrent_events(bars, t1)
        avg = average_uniqueness(t1, co)
        # label0 over conc [1,2,2] -> mean(1, .5, .5); label1 over [2,2,2,2] -> .5;
        # label2 over [2,2,1] -> mean(.5, .5, 1).
        assert avg.loc[bars[0]] == pytest.approx(2.0 / 3.0)
        assert avg.loc[bars[1]] == pytest.approx(0.5)
        assert avg.loc[bars[3]] == pytest.approx(2.0 / 3.0)

    def test_isolated_label_is_fully_unique(self) -> None:
        bars = _bdays(4)
        t1 = pd.Series([bars[1]], index=[bars[0]])
        co = num_concurrent_events(bars, t1)
        avg = average_uniqueness(t1, co)
        assert avg.loc[bars[0]] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# return_attribution_weights
# ---------------------------------------------------------------------------


class TestReturnAttributionWeights:
    def test_normalised_ratio(self) -> None:
        bars = _bdays(4)
        # constant 10% steps -> every log return equals ln(1.1).
        close = pd.Series([100.0, 110.0, 121.0, 133.1], index=bars)
        t1 = pd.Series([bars[1], bars[3]], index=[bars[0], bars[2]])
        co = num_concurrent_events(bars, t1)
        w = return_attribution_weights(t1, co, close)
        # label0 accrues one step (the first bar's return is NaN), label1 two ->
        # raw 1:2, renormalised to average 1 (sum == 2 events).
        assert w.sum() == pytest.approx(2.0)
        assert w.iloc[1] / w.iloc[0] == pytest.approx(2.0)

    def test_unnormalised_raw_returns(self) -> None:
        bars = _bdays(4)
        close = pd.Series([100.0, 110.0, 121.0, 133.1], index=bars)
        t1 = pd.Series([bars[1], bars[3]], index=[bars[0], bars[2]])
        co = num_concurrent_events(bars, t1)
        w = return_attribution_weights(t1, co, close, normalize=False)
        step = float(np.log(1.1))
        assert w.iloc[0] == pytest.approx(step)
        assert w.iloc[1] == pytest.approx(2.0 * step)

    def test_zero_returns_not_normalised(self) -> None:
        bars = _bdays(4)
        close = pd.Series(100.0, index=bars)  # flat -> all log returns 0
        t1 = pd.Series([bars[1], bars[3]], index=[bars[0], bars[2]])
        co = num_concurrent_events(bars, t1)
        w = return_attribution_weights(t1, co, close)
        # total weight is 0; normalisation is skipped rather than dividing by zero.
        assert (w.to_numpy() == 0.0).all()


# ---------------------------------------------------------------------------
# time_decay_weights
# ---------------------------------------------------------------------------


class TestTimeDecayWeights:
    @pytest.mark.parametrize("bad", [-1.0, -1.5, 1.01, 2.0])
    def test_validation(self, bad: float) -> None:
        avg = pd.Series([0.5, 0.5], index=_bdays(2))
        with pytest.raises(ValueError, match="last_weight must be in"):
            time_decay_weights(avg, last_weight=bad)

    def test_no_decay_when_last_weight_one(self) -> None:
        avg = pd.Series([0.4, 0.7, 0.3, 0.9], index=_bdays(4))
        decay = time_decay_weights(avg, last_weight=1.0)
        np.testing.assert_allclose(decay.to_numpy(), 1.0)

    def test_linear_decay_to_zero(self) -> None:
        avg = pd.Series([0.5, 0.5, 0.5, 0.5], index=_bdays(4))
        decay = time_decay_weights(avg, last_weight=0.0)
        # equal uniqueness -> cumulative is linear -> weights 1/4, 2/4, 3/4, 1.
        np.testing.assert_allclose(decay.to_numpy(), [0.25, 0.5, 0.75, 1.0])

    def test_partial_decay(self) -> None:
        avg = pd.Series([0.5, 0.5, 0.5, 0.5], index=_bdays(4))
        decay = time_decay_weights(avg, last_weight=0.5)
        np.testing.assert_allclose(decay.to_numpy(), [0.625, 0.75, 0.875, 1.0])

    def test_negative_last_weight_zeros_oldest(self) -> None:
        avg = pd.Series([0.5, 0.5, 0.5, 0.5], index=_bdays(4))
        decay = time_decay_weights(avg, last_weight=-0.5)
        # raw decay [-0.5, 0, 0.5, 1.0] -> negatives clipped to 0.
        np.testing.assert_allclose(decay.to_numpy(), [0.0, 0.0, 0.5, 1.0])
