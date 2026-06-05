"""Tests for the live-vs-backtest divergence comparator (Phase 10.3).

Covers: config validation, residual alignment rules (inner join, NaN policy,
misaligned / overlapping date ranges), known-value residuals, the alert
boundary (fires exactly at strictly > 2 sigma, not at == 2 sigma), the
no-self-contamination trailing-std rule, insufficient-history handling, the
zero-trailing-std (flat window) edge, determinism, and the ASCII renderer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.ops.divergence import (
    DEFAULT_DIVERGENCE_CONFIG,
    DivergenceConfig,
    DivergenceVerdict,
    _fmt,
    divergence_alert,
    divergence_series,
    render_divergence,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq="B")


# ---------------------------------------------------------------------------
# DivergenceConfig
# ---------------------------------------------------------------------------


class TestDivergenceConfig:
    def test_defaults(self):
        cfg = DivergenceConfig()
        assert cfg.window == 20
        assert cfg.threshold == 2.0
        assert cfg.ddof == 1
        # min_history defaults to window + 1.
        assert cfg.min_history == 21

    def test_default_singleton(self):
        assert DEFAULT_DIVERGENCE_CONFIG.window == 20
        assert DEFAULT_DIVERGENCE_CONFIG.threshold == 2.0

    def test_explicit_min_history(self):
        cfg = DivergenceConfig(window=5, min_history=10)
        assert cfg.min_history == 10

    def test_min_history_floor_applied(self):
        cfg = DivergenceConfig(window=5)
        assert cfg.min_history == 6

    def test_rejects_small_window(self):
        with pytest.raises(ValueError, match="window must be >= 2"):
            DivergenceConfig(window=1)

    def test_rejects_nonpositive_threshold(self):
        with pytest.raises(ValueError, match="threshold must be > 0"):
            DivergenceConfig(threshold=0.0)

    def test_rejects_bad_ddof(self):
        with pytest.raises(ValueError, match="ddof must be 0 or 1"):
            DivergenceConfig(ddof=2)

    def test_rejects_min_history_below_floor(self):
        with pytest.raises(ValueError, match="min_history must be"):
            DivergenceConfig(window=5, min_history=5)

    def test_frozen(self):
        import dataclasses

        cfg = DivergenceConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.window = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# divergence_series
# ---------------------------------------------------------------------------


class TestDivergenceSeries:
    def test_known_value_residuals(self):
        idx = _dates(4)
        live = pd.Series([10.0, 20.0, 30.0, 40.0], index=idx)
        shadow = pd.Series([9.0, 22.0, 27.0, 41.0], index=idx)
        res = divergence_series(live, shadow)
        assert list(res.to_numpy()) == [1.0, -2.0, 3.0, -1.0]
        assert res.name == "residual"

    def test_inner_join_on_overlap_only(self):
        live = pd.Series([1.0, 2.0, 3.0], index=_dates(3))
        # Shadow shifted by one business day: overlaps on 2 of 3 days.
        shadow = pd.Series(
            [10.0, 20.0, 30.0],
            index=pd.date_range("2026-01-02", periods=3, freq="B"),
        )
        res = divergence_series(live, shadow)
        # Overlap dates are 2026-01-02 and 2026-01-05 (business days).
        assert res.shape[0] == 2
        # live[2026-01-02]=2 - shadow[2026-01-02]=10 = -8
        assert res.iloc[0] == pytest.approx(-8.0)

    def test_no_overlap_returns_empty(self):
        live = pd.Series([1.0, 2.0], index=_dates(2))
        shadow = pd.Series(
            [1.0, 2.0],
            index=pd.date_range("2030-01-01", periods=2, freq="B"),
        )
        res = divergence_series(live, shadow)
        assert res.empty

    def test_nan_pairs_dropped(self):
        idx = _dates(4)
        live = pd.Series([1.0, np.nan, 3.0, 4.0], index=idx)
        shadow = pd.Series([0.0, 1.0, np.nan, 1.0], index=idx)
        res = divergence_series(live, shadow)
        # Day 2 (live NaN) and day 3 (shadow NaN) dropped -> days 1 and 4.
        assert res.shape[0] == 2
        assert list(res.to_numpy()) == [1.0, 3.0]
        assert not res.isna().any()

    def test_unsorted_input_sorted_ascending(self):
        idx = _dates(3)
        live = pd.Series([3.0, 1.0, 2.0], index=[idx[2], idx[0], idx[1]])
        shadow = pd.Series([0.0, 0.0, 0.0], index=idx)
        res = divergence_series(live, shadow)
        assert list(res.index) == list(idx)
        assert list(res.to_numpy()) == [1.0, 2.0, 3.0]

    def test_duplicate_live_index_raises(self):
        idx = pd.DatetimeIndex(["2026-01-01", "2026-01-01"])
        live = pd.Series([1.0, 2.0], index=idx)
        shadow = pd.Series([0.0, 0.0], index=_dates(2))
        with pytest.raises(ValueError, match="live_pnl index"):
            divergence_series(live, shadow)

    def test_duplicate_shadow_index_raises(self):
        idx = pd.DatetimeIndex(["2026-01-01", "2026-01-01"])
        shadow = pd.Series([1.0, 2.0], index=idx)
        live = pd.Series([0.0, 0.0], index=_dates(2))
        with pytest.raises(ValueError, match="shadow_pnl index"):
            divergence_series(live, shadow)


# ---------------------------------------------------------------------------
# divergence_alert -- insufficient history
# ---------------------------------------------------------------------------


class TestInsufficientHistory:
    def test_too_few_residuals(self):
        cfg = DivergenceConfig(window=5)  # min_history = 6
        idx = _dates(5)
        live = pd.Series(np.arange(5, dtype=float), index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.state == "INSUFFICIENT_HISTORY"
        assert v.insufficient_history is True
        assert v.alert is False
        assert np.isnan(v.latest_residual)
        assert np.isnan(v.trailing_std)
        assert np.isnan(v.z_score)
        assert v.n_residuals == 5

    def test_empty_overlap_is_insufficient(self):
        cfg = DivergenceConfig(window=5)
        live = pd.Series([1.0], index=_dates(1))
        shadow = pd.Series(
            [1.0], index=pd.date_range("2040-01-01", periods=1, freq="B")
        )
        v = divergence_alert(live, shadow, config=cfg)
        assert v.state == "INSUFFICIENT_HISTORY"
        assert v.n_residuals == 0


# ---------------------------------------------------------------------------
# divergence_alert -- boundary / known values
# ---------------------------------------------------------------------------


class TestAlertBoundary:
    def _build(self, trailing: list[float], latest: float):
        """Construct live/shadow so the residual series is exactly
        ``trailing + [latest]`` (shadow is zero so residual == live)."""
        seq = [*trailing, latest]
        idx = _dates(len(seq))
        live = pd.Series(seq, index=idx, dtype=float)
        shadow = pd.Series(np.zeros(len(seq)), index=idx)
        return live, shadow

    def test_alert_fires_strictly_above_threshold(self):
        # Trailing window of constant +/-1 -> std (ddof=1) = ~1.0264 over the
        # exact pattern; instead build a window with a clean std.
        # Window = [ -1, 1, -1, 1 ] has mean 0, sample std = sqrt(4/3) ~ 1.1547.
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        trailing = [-1.0, 1.0, -1.0, 1.0]
        std = float(np.std(trailing, ddof=1))
        # Latest just above 2*std -> fires.
        latest = 2.0 * std + 0.01
        live, shadow = self._build(trailing, latest)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.alert is True
        assert v.state == "ALERT"
        assert v.observed > 2.0

    def test_alert_does_not_fire_at_exact_boundary(self):
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        trailing = [-1.0, 1.0, -1.0, 1.0]
        std = float(np.std(trailing, ddof=1))
        latest = 2.0 * std  # exactly 2 sigma -> |z| == 2.0, NOT > 2.0
        live, shadow = self._build(trailing, latest)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.z_score == pytest.approx(2.0)
        assert v.observed == pytest.approx(2.0)
        assert v.alert is False
        assert v.state == "OK"

    def test_alert_does_not_fire_below_threshold(self):
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        trailing = [-1.0, 1.0, -1.0, 1.0]
        std = float(np.std(trailing, ddof=1))
        latest = 1.5 * std
        live, shadow = self._build(trailing, latest)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.observed == pytest.approx(1.5)
        assert v.alert is False

    def test_negative_residual_two_sided(self):
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        trailing = [-1.0, 1.0, -1.0, 1.0]
        std = float(np.std(trailing, ddof=1))
        latest = -(2.0 * std + 0.01)  # large NEGATIVE residual still alerts.
        live, shadow = self._build(trailing, latest)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.z_score < 0.0
        assert v.observed > 2.0
        assert v.alert is True

    def test_known_z_score_value(self):
        # Trailing = [0,0,0,0,4,0] window=... pick a simple computable std.
        # Use trailing of [1,2,3,4]; sample std (ddof=1) = sqrt(5/3) ~ 1.290994.
        cfg = DivergenceConfig(window=4, threshold=10.0, ddof=1)
        trailing = [1.0, 2.0, 3.0, 4.0]
        latest = 5.0
        std = float(np.std(trailing, ddof=1))
        live, shadow = self._build(trailing, latest)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.trailing_std == pytest.approx(std)
        assert v.z_score == pytest.approx(5.0 / std)


class TestNoSelfContamination:
    def test_latest_excluded_from_std(self):
        # Flat trailing window (all 5.0) then a spike. If the latest were
        # included the std would be non-zero; excluded, std == 0 -> z = inf.
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        idx = _dates(5)
        live = pd.Series([5.0, 5.0, 5.0, 5.0, 9.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.trailing_std == 0.0
        assert np.isposinf(v.z_score)
        assert v.alert is True

    def test_window_is_exactly_preceding_residuals(self):
        # Residuals: [10, 0, 0, 0, 0, 1]. window=4 std over [0,0,0,0] = 0.
        # The leading 10 must NOT enter the trailing window.
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1, min_history=6)
        idx = _dates(6)
        live = pd.Series([10.0, 0.0, 0.0, 0.0, 0.0, 1.0], index=idx)
        shadow = pd.Series(np.zeros(6), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.trailing_std == 0.0  # the [0,0,0,0] window, not touching the 10
        assert np.isposinf(v.z_score)


class TestFlatWindow:
    def test_flat_window_zero_latest_no_alert(self):
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        idx = _dates(5)
        live = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0], index=idx)
        shadow = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0], index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        # All residuals zero: flat window, latest zero -> z = 0, no alert.
        assert v.trailing_std == 0.0
        assert v.z_score == 0.0
        assert v.alert is False
        assert v.state == "OK"

    def test_flat_window_negative_spike_neg_inf(self):
        cfg = DivergenceConfig(window=4, threshold=2.0, ddof=1)
        idx = _dates(5)
        live = pd.Series([0.0, 0.0, 0.0, 0.0, -7.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        assert np.isneginf(v.z_score)
        assert v.alert is True


class TestDeterminism:
    def test_repeatable(self):
        rng = np.random.default_rng(123)
        idx = _dates(60)
        live = pd.Series(rng.normal(0, 1, 60), index=idx)
        shadow = pd.Series(rng.normal(0, 1, 60), index=idx)
        v1 = divergence_alert(live, shadow)
        v2 = divergence_alert(live, shadow)
        assert v1 == v2

    def test_ddof_zero_path(self):
        cfg = DivergenceConfig(window=4, threshold=10.0, ddof=0)
        trailing = [1.0, 2.0, 3.0, 4.0]
        idx = _dates(5)
        live = pd.Series([*trailing, 5.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        assert v.trailing_std == pytest.approx(float(np.std(trailing, ddof=0)))


# ---------------------------------------------------------------------------
# render_divergence
# ---------------------------------------------------------------------------


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


class TestRenderDivergence:
    def test_renders_insufficient_history(self):
        cfg = DivergenceConfig(window=5)
        idx = _dates(3)
        live = pd.Series([1.0, 2.0, 3.0], index=idx)
        shadow = pd.Series(np.zeros(3), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert _is_ascii(out)
        assert "INSUFFICIENT_HISTORY" in out
        assert "Monitor is silent" in out

    def test_renders_ok(self):
        cfg = DivergenceConfig(window=4, threshold=2.0)
        trailing = [-1.0, 1.0, -1.0, 1.0]
        idx = _dates(5)
        live = pd.Series([*trailing, 0.5], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert _is_ascii(out)
        assert "State          : OK" in out
        assert "No action required" in out

    def test_renders_alert_and_direction(self):
        cfg = DivergenceConfig(window=4, threshold=2.0)
        idx = _dates(5)
        live = pd.Series([1.0, 1.0, 1.0, 1.0, 50.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert _is_ascii(out)
        assert v.alert is True
        assert "ALERT" in out
        assert "OUT-earned" in out
        assert "ACTION:" in out

    def test_renders_under_earned_direction(self):
        cfg = DivergenceConfig(window=4, threshold=2.0)
        idx = _dates(5)
        live = pd.Series([1.0, 1.0, 1.0, 1.0, -50.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert "UNDER-earned" in out

    def test_renders_inf_zscore_cleanly(self):
        cfg = DivergenceConfig(window=4, threshold=2.0)
        idx = _dates(5)
        live = pd.Series([0.0, 0.0, 0.0, 0.0, 9.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert "+inf" in out

    def test_render_exact_match_direction(self):
        # Latest residual exactly zero but enough history and non-flat window.
        cfg = DivergenceConfig(window=4, threshold=2.0)
        idx = _dates(5)
        live = pd.Series([2.0, -2.0, 2.0, -2.0, 0.0], index=idx)
        shadow = pd.Series(np.zeros(5), index=idx)
        v = divergence_alert(live, shadow, config=cfg)
        out = render_divergence(v)
        assert "matched shadow exactly" in out


class TestFmtHelper:
    def test_fmt_nan(self):
        assert _fmt(float("nan")) == "n/a"

    def test_fmt_pos_inf(self):
        assert _fmt(float("inf")) == "+inf"

    def test_fmt_neg_inf(self):
        assert _fmt(float("-inf")) == "-inf"

    def test_fmt_finite(self):
        assert _fmt(1.5) == "1.500000"


class TestVerdictType:
    def test_returns_verdict_instance(self):
        idx = _dates(30)
        live = pd.Series(np.zeros(30), index=idx)
        shadow = pd.Series(np.zeros(30), index=idx)
        v = divergence_alert(live, shadow)
        assert isinstance(v, DivergenceVerdict)
        assert v.limit == 2.0
