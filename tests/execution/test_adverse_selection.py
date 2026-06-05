"""Tests for core_trading.execution.adverse_selection (Phase 9.5).

Coverage targets
----------------
* AdverseSelectionConfig -- validation errors for every guarded field.
* bulk_volume_classify -- buy+sell == volume invariant; first-bar balanced;
  rising-price -> buy_frac ~ 1; falling-price -> buy_frac ~ 0; sigma=0 and
  insufficient-history fallbacks; CDF value for a known dP/sigma; input-shape
  validation.
* volume_buckets -- exact bucket volume; pro-rata split conservation; single
  large bar spanning multiple buckets; trailing partial discarded; empty input;
  validation.
* vpin -- known-value rising (~1) and symmetric-alternation (~0) cases; range
  [0, 1]; empty/short series; min_periods NaN warmup.
* toxicity_check -- absolute and percentile modes; percentile rank; raises on
  empty.
* markout_drift -- constant-positive (t=inf, drifting); constant non-positive
  (t=0); zero-mean noise not drifting; known t-statistic; window truncation;
  raises on < 2 obs.
* ExecutionToxicityMonitor -- starts ACTIVE; VPIN-triggered pause; markout
  pause; cooldown re-arm; dirty reading resets streak; replay determinism;
  audit-event log contents; status/paused properties; skip when inputs absent.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from core_trading.execution.adverse_selection import (
    DEFAULT_CONFIG,
    AdverseSelectionConfig,
    DriftVerdict,
    ExecutionToxicityMonitor,
    MonitorState,
    ToxicityEvent,
    ToxicityVerdict,
    TriggerType,
    bulk_volume_classify,
    markout_drift,
    toxicity_check,
    volume_buckets,
    vpin,
)

_EPS = 1e-9


# ---------------------------------------------------------------------------
# AdverseSelectionConfig validation
# ---------------------------------------------------------------------------


def test_default_config_is_valid() -> None:
    cfg = DEFAULT_CONFIG
    assert cfg.sigma_window == 50
    assert cfg.bucket_size == 1.0
    assert cfg.n_buckets == 50
    assert cfg.toxicity_mode == "absolute"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sigma_window": 1},
        {"bucket_size": 0.0},
        {"bucket_size": -1.0},
        {"n_buckets": 0},
        {"toxicity_mode": "weird"},
        {"toxicity_threshold": 0.0},
        {"toxicity_threshold": 1.5},
        {"toxicity_percentile": 0.0},
        {"toxicity_percentile": 100.0},
        {"markout_window": 1},
        {"drift_t_threshold": 0.0},
        {"drift_t_threshold": -1.0},
        {"cooldown_buckets": 0},
    ],
)
def test_config_rejects_bad_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AdverseSelectionConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# bulk_volume_classify
# ---------------------------------------------------------------------------


def test_bvc_buy_plus_sell_equals_volume() -> None:
    prices = pd.Series([100.0, 101.0, 99.5, 102.0, 101.5])
    volumes = pd.Series([10.0, 20.0, 5.0, 8.0, 12.0])
    buy, sell = bulk_volume_classify(prices, volumes, sigma_window=3)
    total = (buy + sell).to_numpy()
    np.testing.assert_allclose(total, volumes.to_numpy(), atol=_EPS)


def test_bvc_first_bar_is_balanced() -> None:
    prices = pd.Series([100.0, 105.0, 110.0])
    volumes = pd.Series([10.0, 10.0, 10.0])
    buy, sell = bulk_volume_classify(prices, volumes, sigma_window=2)
    # First bar has no prior price change -> balanced.
    assert buy.iloc[0] == pytest.approx(5.0)
    assert sell.iloc[0] == pytest.approx(5.0)


def test_bvc_rising_prices_buy_fraction_near_one() -> None:
    prices = pd.Series([100.0 + 1.5 * i for i in range(10)])
    volumes = pd.Series([10.0] * 10)
    buy, _ = bulk_volume_classify(prices, volumes, sigma_window=3)
    frac = (buy / volumes).to_numpy()
    # All steps strictly up: sigma=0 fallback -> 1.0, or large +z -> ~1.0.
    assert np.all(frac[1:] > 0.99)


def test_bvc_falling_prices_buy_fraction_near_zero() -> None:
    prices = pd.Series([100.0 - 1.5 * i for i in range(10)])
    volumes = pd.Series([10.0] * 10)
    buy, _ = bulk_volume_classify(prices, volumes, sigma_window=3)
    frac = (buy / volumes).to_numpy()
    assert np.all(frac[1:] < 0.01)


def test_bvc_sigma_zero_flat_bar_is_balanced() -> None:
    # Constant prices -> dP == 0, sigma == 0 -> flat fallback -> 0.5.
    prices = pd.Series([100.0, 100.0, 100.0, 100.0])
    volumes = pd.Series([10.0, 10.0, 10.0, 10.0])
    buy, sell = bulk_volume_classify(prices, volumes, sigma_window=3)
    np.testing.assert_allclose(buy.to_numpy(), 5.0, atol=_EPS)
    np.testing.assert_allclose(sell.to_numpy(), 5.0, atol=_EPS)


def test_bvc_known_cdf_value() -> None:
    # Construct a window where sigma_dP is known so we can pin the CDF value.
    # dP sequence: +1, +1, then a +2 step. With sigma_window=3 the sigma at the
    # +2 bar is std([1,1,2], ddof=1). buy_frac = norm.cdf(2 / sigma).
    prices = pd.Series([100.0, 101.0, 102.0, 104.0])
    volumes = pd.Series([10.0, 10.0, 10.0, 10.0])
    buy, _ = bulk_volume_classify(prices, volumes, sigma_window=3)
    sigma = float(np.std([1.0, 1.0, 2.0], ddof=1))
    expected_frac = float(norm.cdf(2.0 / sigma))
    assert (buy.iloc[3] / 10.0) == pytest.approx(expected_frac, abs=1e-9)


def test_bvc_length_mismatch_raises() -> None:
    prices = pd.Series([100.0, 101.0])
    volumes = pd.Series([10.0])
    with pytest.raises(ValueError, match="length mismatch"):
        bulk_volume_classify(prices, volumes, sigma_window=2)


def test_bvc_index_mismatch_raises() -> None:
    prices = pd.Series([100.0, 101.0], index=[0, 1])
    volumes = pd.Series([10.0, 20.0], index=[5, 6])
    with pytest.raises(ValueError, match="same index"):
        bulk_volume_classify(prices, volumes, sigma_window=2)


def test_bvc_negative_volume_raises() -> None:
    prices = pd.Series([100.0, 101.0])
    volumes = pd.Series([10.0, -1.0])
    with pytest.raises(ValueError, match="non-negative"):
        bulk_volume_classify(prices, volumes, sigma_window=2)


def test_bvc_bad_sigma_window_raises() -> None:
    prices = pd.Series([100.0, 101.0])
    volumes = pd.Series([10.0, 10.0])
    with pytest.raises(ValueError, match="sigma_window"):
        bulk_volume_classify(prices, volumes, sigma_window=1)


# ---------------------------------------------------------------------------
# volume_buckets
# ---------------------------------------------------------------------------


def test_buckets_exact_volume_and_conservation() -> None:
    buy = pd.Series([6.0, 4.0, 8.0, 2.0])
    sell = pd.Series([4.0, 6.0, 2.0, 8.0])
    out = volume_buckets(buy, sell, bucket_size=10.0)
    # Total volume 40 -> 4 buckets of exactly 10.
    assert len(out) == 4
    vols = (out["buy"] + out["sell"]).to_numpy()
    np.testing.assert_allclose(vols, 10.0, atol=_EPS)
    # Conservation of total buy / sell flow.
    assert out["buy"].sum() == pytest.approx(buy.sum())
    assert out["sell"].sum() == pytest.approx(sell.sum())


def test_buckets_prorata_split_single_large_bar() -> None:
    # One bar of volume 25 (buy 20, sell 5), bucket_size 10:
    #   bucket1: 8 buy / 2 sell, bucket2: 8 buy / 2 sell, carry: 4 buy / 1 sell.
    buy = pd.Series([20.0, 5.0])
    sell = pd.Series([5.0, 0.0])
    out = volume_buckets(buy, sell, bucket_size=10.0)
    assert len(out) == 3
    np.testing.assert_allclose(out["buy"].to_numpy()[:2], [8.0, 8.0], atol=_EPS)
    np.testing.assert_allclose(out["sell"].to_numpy()[:2], [2.0, 2.0], atol=_EPS)
    # Third bucket = carry (4 buy, 1 sell) + bar1 (5 buy, 0 sell) = 9 buy, 1 sell.
    assert out["buy"].iloc[2] == pytest.approx(9.0)
    assert out["sell"].iloc[2] == pytest.approx(1.0)
    # Completion labels: first two buckets complete in bar 0, third in bar 1.
    assert list(out.index) == [0, 0, 1]


def test_buckets_trailing_partial_discarded() -> None:
    buy = pd.Series([6.0, 4.0, 3.0])
    sell = pd.Series([4.0, 6.0, 2.0])
    # Total volume 25, bucket_size 10 -> 2 full buckets, 5 leftover discarded.
    out = volume_buckets(buy, sell, bucket_size=10.0)
    assert len(out) == 2


def test_buckets_imbalance_formula() -> None:
    buy = pd.Series([10.0])
    sell = pd.Series([0.0])
    out = volume_buckets(buy, sell, bucket_size=10.0)
    assert out["imbalance"].iloc[0] == pytest.approx(1.0)


def test_buckets_empty_when_insufficient_volume() -> None:
    buy = pd.Series([1.0, 1.0])
    sell = pd.Series([1.0, 1.0])
    out = volume_buckets(buy, sell, bucket_size=100.0)
    assert out.empty
    assert list(out.columns) == ["buy", "sell", "imbalance"]


def test_buckets_bar_within_epsilon_of_boundary_clamps_fraction() -> None:
    # A bar whose volume lands just below a bucket boundary (within the
    # bucketing epsilon) still completes the bucket; the pro-rata fraction is
    # clamped to 1.0 so no negative remainder leaks forward.
    vol = 10.0 - 0.5e-9
    out = volume_buckets(
        pd.Series([vol]), pd.Series([0.0]), bucket_size=10.0
    )
    assert len(out) == 1
    assert out["buy"].iloc[0] == pytest.approx(vol)
    assert out["sell"].iloc[0] == pytest.approx(0.0)


def test_buckets_bad_bucket_size_raises() -> None:
    buy = pd.Series([1.0])
    sell = pd.Series([1.0])
    with pytest.raises(ValueError, match="bucket_size"):
        volume_buckets(buy, sell, bucket_size=0.0)


def test_buckets_index_mismatch_raises() -> None:
    buy = pd.Series([1.0], index=[0])
    sell = pd.Series([1.0], index=[1])
    with pytest.raises(ValueError, match="same index"):
        volume_buckets(buy, sell, bucket_size=1.0)


# ---------------------------------------------------------------------------
# vpin -- known-value cases
# ---------------------------------------------------------------------------


def test_vpin_rising_prices_near_one() -> None:
    prices = pd.Series([100.0 + 1.5 * i for i in range(12)])
    volumes = pd.Series([10.0] * 12)
    cfg = AdverseSelectionConfig(sigma_window=3, bucket_size=20.0, n_buckets=2)
    series = vpin(prices, volumes, config=cfg)
    clean = series.dropna()
    assert len(clean) > 0
    assert float(clean.iloc[-1]) == pytest.approx(1.0, abs=1e-6)


def test_vpin_symmetric_alternation_near_zero() -> None:
    # +1, -1, +1, -1 ... around a constant level -> balanced buckets -> VPIN ~ 0.
    prices = pd.Series([100.0 + (1.0 if i % 2 == 0 else 0.0) for i in range(40)])
    volumes = pd.Series([10.0] * 40)
    cfg = AdverseSelectionConfig(sigma_window=5, bucket_size=20.0, n_buckets=5)
    series = vpin(prices, volumes, config=cfg)
    clean = series.dropna()
    assert len(clean) > 0
    assert float(clean.iloc[-1]) == pytest.approx(0.0, abs=1e-6)


def test_vpin_within_unit_range() -> None:
    rng = np.random.default_rng(42)
    steps = rng.normal(0.0, 1.0, size=200)
    prices = pd.Series(100.0 + np.cumsum(steps))
    volumes = pd.Series(rng.uniform(5.0, 50.0, size=200))
    cfg = AdverseSelectionConfig(sigma_window=20, bucket_size=100.0, n_buckets=10)
    series = vpin(prices, volumes, config=cfg).dropna()
    arr = series.to_numpy()
    assert np.all(arr >= -_EPS)
    assert np.all(arr <= 1.0 + _EPS)


def test_vpin_warmup_is_nan() -> None:
    prices = pd.Series([100.0 + 1.5 * i for i in range(12)])
    volumes = pd.Series([10.0] * 12)
    cfg = AdverseSelectionConfig(sigma_window=3, bucket_size=20.0, n_buckets=3)
    series = vpin(prices, volumes, config=cfg)
    # First (n_buckets - 1) buckets are NaN under min_periods.
    assert series.isna().iloc[0]


def test_vpin_empty_when_no_bucket_completes() -> None:
    prices = pd.Series([100.0, 101.0, 102.0])
    volumes = pd.Series([1.0, 1.0, 1.0])
    cfg = AdverseSelectionConfig(sigma_window=2, bucket_size=1000.0, n_buckets=2)
    series = vpin(prices, volumes, config=cfg)
    assert series.empty


# ---------------------------------------------------------------------------
# toxicity_check
# ---------------------------------------------------------------------------


def test_toxicity_absolute_toxic_and_clean() -> None:
    cfg = AdverseSelectionConfig(toxicity_mode="absolute", toxicity_threshold=0.7)
    toxic = toxicity_check(pd.Series([0.2, 0.5, 0.85]), config=cfg)
    assert toxic.toxic is True
    assert toxic.latest_vpin == pytest.approx(0.85)
    assert toxic.threshold == pytest.approx(0.7)
    assert toxic.mode == "absolute"

    clean = toxicity_check(pd.Series([0.2, 0.5, 0.6]), config=cfg)
    assert clean.toxic is False


def test_toxicity_percentile_mode() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="percentile", toxicity_percentile=90.0
    )
    # Latest value is the max -> strictly above the 90th percentile of history.
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.9])
    verdict = toxicity_check(series, config=cfg)
    assert verdict.mode == "percentile"
    assert verdict.toxic is True
    assert verdict.percentile == pytest.approx(100.0)


def test_toxicity_percentile_not_toxic_when_typical() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="percentile", toxicity_percentile=95.0
    )
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.25])
    verdict = toxicity_check(series, config=cfg)
    assert verdict.toxic is False


def test_toxicity_drops_nans_and_uses_latest() -> None:
    cfg = AdverseSelectionConfig(toxicity_mode="absolute", toxicity_threshold=0.5)
    series = pd.Series([0.9, np.nan, 0.1])
    verdict = toxicity_check(series, config=cfg)
    assert verdict.latest_vpin == pytest.approx(0.1)
    assert verdict.toxic is False


def test_toxicity_empty_raises() -> None:
    with pytest.raises(ValueError, match="no non-NaN"):
        toxicity_check(pd.Series([np.nan, np.nan]))


# ---------------------------------------------------------------------------
# markout_drift
# ---------------------------------------------------------------------------


def test_markout_drift_constant_positive_is_inf_and_drifting() -> None:
    cfg = AdverseSelectionConfig(markout_window=10)
    verdict = markout_drift(pd.Series([0.5] * 10), config=cfg)
    assert verdict.drifting is True
    assert math.isinf(verdict.t_stat)
    assert verdict.mean_markout == pytest.approx(0.5)
    assert verdict.p_value == pytest.approx(0.0)
    assert verdict.n_obs == 10


def test_markout_drift_constant_nonpositive_not_drifting() -> None:
    cfg = AdverseSelectionConfig(markout_window=10)
    verdict = markout_drift(pd.Series([-0.5] * 10), config=cfg)
    assert verdict.drifting is False
    assert verdict.t_stat == pytest.approx(0.0)
    assert verdict.p_value == pytest.approx(1.0)


def test_markout_drift_zero_mean_noise_not_drifting() -> None:
    rng = np.random.default_rng(7)
    cfg = AdverseSelectionConfig(markout_window=200, drift_t_threshold=2.0)
    verdict = markout_drift(pd.Series(rng.normal(0.0, 1.0, 200)), config=cfg)
    assert verdict.drifting is False


def test_markout_drift_known_t_statistic() -> None:
    cfg = AdverseSelectionConfig(markout_window=4, drift_t_threshold=0.5)
    series = pd.Series([0.0, 2.0, 0.0, 2.0])
    verdict = markout_drift(series, config=cfg)
    mean = 1.0
    sd = float(np.std([0.0, 2.0, 0.0, 2.0], ddof=1))
    expected_t = mean / (sd / math.sqrt(4))
    assert verdict.t_stat == pytest.approx(expected_t)
    assert verdict.mean_markout == pytest.approx(1.0)
    assert verdict.drifting is True  # ~1.73 > 0.5


def test_markout_drift_uses_trailing_window_only() -> None:
    cfg = AdverseSelectionConfig(markout_window=3, drift_t_threshold=2.0)
    # Strongly adverse tail, benign head -> window only sees the tail.
    series = pd.Series([-5.0, -5.0, -5.0, 1.0, 1.0, 1.0])
    verdict = markout_drift(series, config=cfg)
    assert verdict.n_obs == 3
    assert verdict.mean_markout == pytest.approx(1.0)


def test_markout_drift_too_few_obs_raises() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        markout_drift(pd.Series([1.0]))


# ---------------------------------------------------------------------------
# ExecutionToxicityMonitor
# ---------------------------------------------------------------------------


def _toxic_vpin() -> pd.Series:
    return pd.Series([0.1, 0.2, 0.95])


def _clean_vpin() -> pd.Series:
    return pd.Series([0.1, 0.2, 0.1])


def test_monitor_starts_active() -> None:
    mon = ExecutionToxicityMonitor()
    assert mon.state is MonitorState.ACTIVE
    assert mon.status is MonitorState.ACTIVE
    assert mon.paused is False
    assert mon.events == []


def test_monitor_vpin_pause_and_cooldown_rearm() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="absolute", toxicity_threshold=0.7, cooldown_buckets=3
    )
    mon = ExecutionToxicityMonitor(config=cfg)

    # Bar 0: clean -> still ACTIVE.
    assert mon.update(0, vpin_series=_clean_vpin()) is MonitorState.ACTIVE
    # Bar 1: toxic -> PAUSE.
    assert mon.update(1, vpin_series=_toxic_vpin()) is MonitorState.PAUSED
    assert mon.paused is True
    # Bars 2-3: clean but cooldown not yet satisfied -> stay PAUSED.
    assert mon.update(2, vpin_series=_clean_vpin()) is MonitorState.PAUSED
    assert mon.update(3, vpin_series=_clean_vpin()) is MonitorState.PAUSED
    # Bar 4: third consecutive clean reading -> RE-ARM to ACTIVE.
    assert mon.update(4, vpin_series=_clean_vpin()) is MonitorState.ACTIVE

    # Two transitions logged: PAUSE (VPIN) then re-arm (COOLDOWN).
    assert len(mon.events) == 2
    pause_evt, rearm_evt = mon.events
    assert pause_evt.trigger is TriggerType.VPIN
    assert pause_evt.from_state is MonitorState.ACTIVE
    assert pause_evt.to_state is MonitorState.PAUSED
    assert pause_evt.observed == pytest.approx(0.95)
    assert pause_evt.limit == pytest.approx(0.7)
    assert pause_evt.index == 1
    assert "VPIN" in pause_evt.reason

    assert rearm_evt.trigger is TriggerType.COOLDOWN
    assert rearm_evt.to_state is MonitorState.ACTIVE
    assert rearm_evt.index == 4
    assert mon.last_reason == rearm_evt.reason


def test_monitor_dirty_reading_resets_cooldown() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="absolute", toxicity_threshold=0.7, cooldown_buckets=2
    )
    mon = ExecutionToxicityMonitor(config=cfg)
    mon.update(0, vpin_series=_toxic_vpin())  # -> PAUSED
    assert mon.state is MonitorState.PAUSED
    mon.update(1, vpin_series=_clean_vpin())  # streak 1
    assert mon.clean_streak == 1
    mon.update(2, vpin_series=_toxic_vpin())  # dirty -> reset to 0
    assert mon.clean_streak == 0
    assert mon.state is MonitorState.PAUSED
    # Now two clean readings re-arm.
    mon.update(3, vpin_series=_clean_vpin())
    assert mon.update(4, vpin_series=_clean_vpin()) is MonitorState.ACTIVE


def test_monitor_markout_trigger() -> None:
    cfg = AdverseSelectionConfig(
        markout_window=5, drift_t_threshold=1.0, cooldown_buckets=1
    )
    mon = ExecutionToxicityMonitor(config=cfg)
    adverse = pd.Series([0.5] * 5)  # constant positive -> t=inf -> drifting
    state = mon.update("t0", markouts=adverse)
    assert state is MonitorState.PAUSED
    evt = mon.events[0]
    assert evt.trigger is TriggerType.MARKOUT_DRIFT
    assert evt.observed == pytest.approx(0.5)
    assert evt.limit == pytest.approx(1.0)
    assert "markout drift" in evt.reason


def test_monitor_skips_triggers_when_inputs_absent() -> None:
    mon = ExecutionToxicityMonitor()
    # No vpin, no markouts -> nothing to evaluate, stays ACTIVE, no events.
    assert mon.update(0) is MonitorState.ACTIVE
    # All-NaN vpin and single markout -> still skipped.
    assert (
        mon.update(1, vpin_series=pd.Series([np.nan]), markouts=pd.Series([1.0]))
        is MonitorState.ACTIVE
    )
    assert mon.events == []


def test_monitor_vpin_takes_precedence_over_markout() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="absolute",
        toxicity_threshold=0.7,
        markout_window=5,
        drift_t_threshold=1.0,
    )
    mon = ExecutionToxicityMonitor(config=cfg)
    # Both fire simultaneously; VPIN is reported as the latching trigger.
    mon.update(
        0,
        vpin_series=_toxic_vpin(),
        markouts=pd.Series([0.5] * 5),
    )
    assert mon.events[0].trigger is TriggerType.VPIN


def test_monitor_replay_is_deterministic() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="absolute", toxicity_threshold=0.7, cooldown_buckets=2
    )

    def run() -> list[MonitorState]:
        mon = ExecutionToxicityMonitor(config=cfg)
        trace: list[MonitorState] = []
        feed = [
            _clean_vpin(),
            _toxic_vpin(),
            _toxic_vpin(),
            _clean_vpin(),
            _clean_vpin(),
            _clean_vpin(),
        ]
        for i, series in enumerate(feed):
            trace.append(mon.update(i, vpin_series=series))
        return trace

    trace_a = run()
    trace_b = run()
    assert trace_a == trace_b
    # bar0 clean->ACTIVE; bar1 toxic->PAUSED; bar2 toxic->PAUSED (streak 0);
    # bar3 clean (streak 1); bar4 clean (streak 2 == cooldown)->ACTIVE;
    # bar5 clean->ACTIVE.
    assert trace_a == [
        MonitorState.ACTIVE,
        MonitorState.PAUSED,
        MonitorState.PAUSED,
        MonitorState.PAUSED,
        MonitorState.ACTIVE,
        MonitorState.ACTIVE,
    ]


def test_monitor_stays_paused_under_sustained_toxicity() -> None:
    cfg = AdverseSelectionConfig(
        toxicity_mode="absolute", toxicity_threshold=0.7, cooldown_buckets=2
    )
    mon = ExecutionToxicityMonitor(config=cfg)
    for i in range(5):
        mon.update(i, vpin_series=_toxic_vpin())
    assert mon.state is MonitorState.PAUSED
    # Only one PAUSE event despite repeated toxic readings.
    assert len(mon.events) == 1


def test_event_and_verdict_types_are_frozen() -> None:
    evt = ToxicityEvent(
        index=0,
        trigger=TriggerType.VPIN,
        from_state=MonitorState.ACTIVE,
        to_state=MonitorState.PAUSED,
        observed=0.9,
        limit=0.7,
        reason="x",
    )
    with pytest.raises(AttributeError):
        evt.observed = 0.0  # type: ignore[misc]

    verdict = ToxicityVerdict(
        toxic=True, latest_vpin=0.9, threshold=0.7, percentile=99.0, mode="absolute"
    )
    with pytest.raises(AttributeError):
        verdict.toxic = False  # type: ignore[misc]

    drift = DriftVerdict(
        drifting=False,
        mean_markout=0.0,
        t_stat=0.0,
        p_value=1.0,
        threshold=2.0,
        n_obs=5,
    )
    with pytest.raises(AttributeError):
        drift.drifting = True  # type: ignore[misc]
