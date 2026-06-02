"""Parameter-recovery tests for the triple-barrier labeling primitives (5.D foundation).

Labels are path-dependent and *forward-looking by construction* (the label of an
event is determined by what happens after it). The look-ahead concern in ML
trading is about FEATURES, not labels, so there is no truncation-invariance test
here; instead we verify the labels exactly on synthetic paths whose barrier
touches are known a priori.

Covers:
* daily_volatility -- validation, NaN warmup, recovery of a known vol level.
* cusum_filter -- validation, no-event flat series, symmetric up/down triggering.
* add_vertical_barrier -- validation, exact t1, end-of-series dropping.
* triple_barrier_events -- profit-take / stop-loss / vertical first-touch on
  known paths, target filtering, disabled barriers, the side (meta) path, and
  the default (no vertical barrier) path.
* get_bins -- exact realised returns, directional sign labels, and {0,1}
  meta-labels (including a profitable short).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.labeling import (
    add_vertical_barrier,
    cusum_filter,
    daily_volatility,
    get_bins,
    triple_barrier_events,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


# ---------------------------------------------------------------------------
# daily_volatility
# ---------------------------------------------------------------------------


class TestDailyVolatility:
    def test_span_validation(self) -> None:
        close = pd.Series([100.0, 101.0, 102.0])
        with pytest.raises(ValueError, match="span must be >= 2"):
            daily_volatility(close, span=1)

    def test_lookback_validation(self) -> None:
        close = pd.Series([100.0, 101.0, 102.0])
        with pytest.raises(ValueError, match="lookback must be >= 1"):
            daily_volatility(close, lookback=0)

    def test_index_preserved_and_warmup_nan(self) -> None:
        close = pd.Series([100.0, 101.0, 99.0, 102.0], index=_bdays(4))
        vol = daily_volatility(close, span=2)
        pd.testing.assert_index_equal(vol.index, close.index)
        assert np.isnan(vol.iloc[0])  # first return is undefined

    def test_recovers_known_vol(self) -> None:
        rng = np.random.default_rng(0)
        sigma = 0.02
        close = pd.Series(
            100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, 4000))),
            index=_bdays(4000),
        )
        vol = daily_volatility(close, span=100)
        # EWMA std of the returns should hover near the generating sigma.
        assert abs(vol.tail(500).mean() - sigma) < 0.004


# ---------------------------------------------------------------------------
# cusum_filter
# ---------------------------------------------------------------------------


class TestCusumFilter:
    def test_threshold_validation(self) -> None:
        close = pd.Series([100.0, 101.0], index=_bdays(2))
        with pytest.raises(ValueError, match="threshold must be > 0"):
            cusum_filter(close, threshold=0.0)

    def test_flat_series_no_events(self) -> None:
        close = pd.Series(100.0, index=_bdays(50))
        assert len(cusum_filter(close, threshold=0.01)) == 0

    def test_events_are_subset_of_index(self) -> None:
        rng = np.random.default_rng(1)
        close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=_bdays(300))
        events = cusum_filter(close, threshold=0.02)
        assert set(events).issubset(set(close.index))

    def test_upward_jump_triggers(self) -> None:
        # Flat then a single +5% jump -> one event at the jump bar.
        prices = [100.0] * 10 + [105.0] * 10
        close = pd.Series(prices, index=_bdays(20))
        events = cusum_filter(close, threshold=0.03)
        assert len(events) == 1
        assert events[0] == close.index[10]

    def test_downward_jump_triggers(self) -> None:
        prices = [100.0] * 10 + [95.0] * 10
        close = pd.Series(prices, index=_bdays(20))
        events = cusum_filter(close, threshold=0.03)
        assert len(events) == 1
        assert events[0] == close.index[10]

    def test_skips_non_finite_returns(self) -> None:
        # A NaN price yields a non-finite log return; the filter skips it cleanly.
        prices = [100.0] * 5 + [float("nan")] + [105.0] * 5
        close = pd.Series(prices, index=_bdays(11))
        events = cusum_filter(close, threshold=0.03)
        assert isinstance(events, pd.Index)


# ---------------------------------------------------------------------------
# add_vertical_barrier
# ---------------------------------------------------------------------------


class TestAddVerticalBarrier:
    def test_num_bars_validation(self) -> None:
        close = pd.Series([1.0, 2.0, 3.0], index=_bdays(3))
        with pytest.raises(ValueError, match="num_bars must be >= 1"):
            add_vertical_barrier(close, close.index, num_bars=0)

    def test_exact_t1(self) -> None:
        close = pd.Series(range(10), index=_bdays(10), dtype=float)
        t_events = close.index[[0, 1, 2]]
        t1 = add_vertical_barrier(close, t_events, num_bars=3)
        assert t1.loc[close.index[0]] == close.index[3]
        assert t1.loc[close.index[2]] == close.index[5]

    def test_drops_events_past_end(self) -> None:
        close = pd.Series(range(10), index=_bdays(10), dtype=float)
        t_events = close.index[[7, 8, 9]]  # 7+3=10 (out of range) etc.
        t1 = add_vertical_barrier(close, t_events, num_bars=3)
        assert len(t1) == 0

    def test_skips_event_not_in_index(self) -> None:
        close = pd.Series(range(10), index=_bdays(10), dtype=float)
        bogus = pd.DatetimeIndex(["1999-01-01"])  # absent from close.index
        t_events = close.index[[0]].append(bogus)
        t1 = add_vertical_barrier(close, t_events, num_bars=3)
        assert len(t1) == 1  # only the valid event survives


# ---------------------------------------------------------------------------
# triple_barrier_events + get_bins
# ---------------------------------------------------------------------------


def _rising(n: int = 20, step: float = 0.01) -> pd.Series:
    return pd.Series(100.0 * (1.0 + step) ** np.arange(n), index=_bdays(n))


def _falling(n: int = 20, step: float = 0.01) -> pd.Series:
    return pd.Series(100.0 * (1.0 - step) ** np.arange(n), index=_bdays(n))


def _flat(n: int = 20) -> pd.Series:
    return pd.Series(100.0, index=_bdays(n))


class TestTripleBarrierEvents:
    def test_negative_pt_sl_raises(self) -> None:
        close = _rising()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        with pytest.raises(ValueError, match="pt_sl multipliers must be >= 0"):
            triple_barrier_events(close, t0, pt_sl=(-1.0, 1.0), target=target)

    def test_profit_take_touched_first(self) -> None:
        close = _rising(step=0.01)
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar)
        # +1%/bar: cum return crosses +2% at bar index 2.
        assert ev["t1"].iloc[0] == close.index[2]

    def test_stop_loss_touched_first(self) -> None:
        close = _falling(step=0.01)
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar)
        # -1%/bar: cum return crosses -2% at bar index 3 (-2.97%); index 2 is -1.99%.
        assert ev["t1"].iloc[0] == close.index[3]

    def test_vertical_barrier_touched_when_flat(self) -> None:
        close = _flat()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=10)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar)
        assert ev["t1"].iloc[0] == close.index[10]

    def test_target_min_ret_filters_events(self) -> None:
        close = _rising()
        t_events = close.index[:3]
        target = pd.Series([0.01, 0.05, 0.005], index=t_events)
        ev = triple_barrier_events(
            close, t_events, pt_sl=(1.0, 1.0), target=target, min_ret=0.008
        )
        # Only the 0.01 and 0.05 targets survive the 0.008 floor.
        assert len(ev) == 2

    def test_disabled_upper_barrier(self) -> None:
        # pt multiplier 0 -> no profit-take; a rising path runs to the vertical barrier.
        close = _rising(step=0.01)
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=8)
        ev = triple_barrier_events(close, t0, pt_sl=(0.0, 1.0), target=target, vertical_barrier=vbar)
        assert ev["t1"].iloc[0] == close.index[8]

    def test_default_vertical_barrier_is_last_bar(self) -> None:
        close = _flat()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target)
        assert ev["t1"].iloc[0] == close.index[-1]

    def test_side_carried_into_output(self) -> None:
        close = _rising()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        side = pd.Series(-1.0, index=t0)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, side=side)
        assert "side" in ev.columns
        assert ev["side"].iloc[0] == -1.0


class TestGetBins:
    def test_directional_sign_label_rising(self) -> None:
        close = _rising(step=0.01)
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar)
        bins = get_bins(ev, close)
        assert bins["bin"].iloc[0] == 1.0
        assert bins["ret"].iloc[0] == pytest.approx(0.0201, abs=1e-4)

    def test_directional_sign_label_falling(self) -> None:
        close = _falling(step=0.01)
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar)
        bins = get_bins(ev, close)
        assert bins["bin"].iloc[0] == -1.0

    def test_meta_label_profitable_long(self) -> None:
        close = _rising()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        side = pd.Series(1.0, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(
            close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar, side=side
        )
        bins = get_bins(ev, close)
        assert bins["bin"].iloc[0] == 1.0  # long made money

    def test_meta_label_unprofitable_long(self) -> None:
        close = _falling()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        side = pd.Series(1.0, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(
            close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar, side=side
        )
        bins = get_bins(ev, close)
        assert bins["bin"].iloc[0] == 0.0  # long lost money

    def test_meta_label_profitable_short(self) -> None:
        close = _falling()
        t0 = close.index[:1]
        target = pd.Series(0.02, index=t0)
        side = pd.Series(-1.0, index=t0)
        vbar = add_vertical_barrier(close, t0, num_bars=15)
        ev = triple_barrier_events(
            close, t0, pt_sl=(1.0, 1.0), target=target, vertical_barrier=vbar, side=side
        )
        bins = get_bins(ev, close)
        assert bins["bin"].iloc[0] == 1.0  # short profits when price falls
        assert bins["ret"].iloc[0] > 0.0
