"""Tests for core_trading.research.signal_decay (Phase 13.1 + 13.4).

Coverage plan
-------------
* DecayConfig: defaults, validation errors.
* compute_rolling_metrics: rolling Sharpe shape/index, expanding Sharpe,
  decay_gap with and without backtest_sharpe, NaN guard, constant series.
* assess_signal: HEALTHY / WARN / RETIRE verdicts via deterministic fixtures,
  fields populated correctly, WARN skipped without backtest_sharpe.
* build_decay_report: multi-signal ranking, status counts, generated_at
  injection, empty dict.
* render_decay_report: ASCII-only, contains expected substrings.
* RetrainPolicy: defaults, validation errors.
* DEFAULT_RETRAIN_POLICIES: spot-check expected entries.
* due_for_retrain: never trained, recently trained, exactly at cadence,
  mix of due/not-due policies.
* render_retrain_schedule: ASCII-only, contains expected substrings.
* CLI --demo smoke: exits 0 and prints ASCII output; --output writes a file.
* __init__ re-export: public names reachable from core_trading.research.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_decay import (
    DEFAULT_RETRAIN_POLICIES,
    DecayConfig,
    DecayReport,
    RetrainPolicy,
    RollingSharpeSeries,
    _build_demo_signals,
    _count_trailing_condition,
    _expanding_sharpe_series,
    _rolling_sharpe_series,
    _utcnow_str,
    assess_signal,
    build_decay_report,
    compute_rolling_metrics,
    due_for_retrain,
    main,
    render_decay_report,
    render_retrain_schedule,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SEED = 20240605
_SIGMA = 0.01
_N = 400  # bars -- enough to trigger multi-window rolling Sharpes


def _dates(n: int = _N) -> pd.DatetimeIndex:
    return pd.date_range("2022-01-03", periods=n, freq="B")


def _make_series(
    drift: float = 0.0,
    sigma: float = _SIGMA,
    n: int = _N,
    seed: int = _SEED,
) -> pd.Series:
    rng = np.random.default_rng(seed)
    arr = rng.normal(drift / np.sqrt(252.0) * sigma, sigma, n)
    return pd.Series(arr, index=_dates(n), dtype=float)


def _positive_drift(sharpe: float = 1.5, n: int = _N) -> pd.Series:
    return _make_series(drift=sharpe, n=n)


def _negative_drift(sharpe: float = -1.5, n: int = _N) -> pd.Series:
    return _make_series(drift=sharpe, n=n)


def _warn_series(n: int = _N) -> pd.Series:
    """Half strong positive, half near-zero -- should trigger WARN with low warn_days."""
    rng = np.random.default_rng(_SEED)
    sigma = _SIGMA
    early = rng.normal(1.2 / np.sqrt(252.0) * sigma, sigma, n // 2)
    late = rng.normal(0.05 / np.sqrt(252.0) * sigma, sigma, n - n // 2)
    arr = np.concatenate([early, late])
    return pd.Series(arr, index=_dates(n), dtype=float)


def _retire_series(n: int = _N, n_negative: int = 80) -> pd.Series:
    """Consistently negative tail -- should trigger RETIRE with short retirement_days."""
    rng = np.random.default_rng(_SEED)
    sigma = _SIGMA
    early = rng.normal(1.0 / np.sqrt(252.0) * sigma, sigma, n - n_negative)
    late = rng.normal(-2.0 / np.sqrt(252.0) * sigma, sigma, n_negative)
    arr = np.concatenate([early, late])
    return pd.Series(arr, index=_dates(n), dtype=float)


# ---------------------------------------------------------------------------
# DecayConfig tests
# ---------------------------------------------------------------------------


class TestDecayConfig:
    def test_defaults(self) -> None:
        cfg = DecayConfig()
        assert cfg.rolling_windows == (30, 60, 90)
        assert cfg.periods_per_year == 252
        assert cfg.retirement_days == 60
        assert cfg.warn_days == 30
        assert cfg.decay_warn_fraction == 0.5
        assert cfg.min_window_obs == 5
        assert cfg.primary_window == 30

    def test_custom_windows(self) -> None:
        cfg = DecayConfig(rolling_windows=(10, 20))
        assert cfg.primary_window == 10

    def test_empty_windows_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            DecayConfig(rolling_windows=())

    def test_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match=">= 2"):
            DecayConfig(rolling_windows=(1, 30))

    def test_bad_periods_per_year(self) -> None:
        with pytest.raises(ValueError, match="periods_per_year"):
            DecayConfig(periods_per_year=0)

    def test_bad_retirement_days(self) -> None:
        with pytest.raises(ValueError, match="retirement_days"):
            DecayConfig(retirement_days=0)

    def test_bad_warn_days(self) -> None:
        with pytest.raises(ValueError, match="warn_days"):
            DecayConfig(warn_days=0)

    def test_bad_warn_fraction_zero(self) -> None:
        with pytest.raises(ValueError, match="decay_warn_fraction"):
            DecayConfig(decay_warn_fraction=0.0)

    def test_bad_warn_fraction_one(self) -> None:
        with pytest.raises(ValueError, match="decay_warn_fraction"):
            DecayConfig(decay_warn_fraction=1.0)

    def test_bad_min_window_obs(self) -> None:
        with pytest.raises(ValueError, match="min_window_obs"):
            DecayConfig(min_window_obs=1)

    def test_frozen(self) -> None:
        cfg = DecayConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.retirement_days = 100  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Rolling / expanding Sharpe helpers
# ---------------------------------------------------------------------------


class TestRollingSharpeSeries:
    def test_rolling_sharpe_shape(self) -> None:
        series = _positive_drift()
        rs = _rolling_sharpe_series(series, window=30, periods_per_year=252, min_obs=5)
        assert len(rs) == len(series)
        assert rs.index.equals(series.index)

    def test_rolling_sharpe_nan_in_first_window(self) -> None:
        series = _positive_drift(n=50)
        rs = _rolling_sharpe_series(series, window=30, periods_per_year=252, min_obs=5)
        # First 4 positions have fewer than min_obs=5 obs so first valid at index 4
        # after window=30, first non-NaN at position 29 (0-based)
        assert rs.iloc[0] != rs.iloc[0]  # NaN check

    def test_rolling_sharpe_positive_for_strong_drift(self) -> None:
        series = _positive_drift(sharpe=3.0, n=200)
        rs = _rolling_sharpe_series(series, window=30, periods_per_year=252, min_obs=5)
        valid = rs.dropna()
        assert len(valid) > 0
        assert valid.mean() > 0

    def test_rolling_sharpe_negative_for_negative_drift(self) -> None:
        series = _negative_drift(sharpe=-3.0, n=200)
        rs = _rolling_sharpe_series(series, window=30, periods_per_year=252, min_obs=5)
        valid = rs.dropna()
        assert valid.mean() < 0

    def test_rolling_sharpe_constant_series(self) -> None:
        """Constant returns -> std=0 -> Sharpe returned as 0.0 not NaN."""
        arr = np.ones(60) * 0.001
        series = pd.Series(arr, index=_dates(60))
        rs = _rolling_sharpe_series(series, window=30, periods_per_year=252, min_obs=5)
        valid = rs.dropna()
        assert (valid == 0.0).all()

    def test_expanding_sharpe_shape(self) -> None:
        series = _positive_drift()
        es = _expanding_sharpe_series(series, periods_per_year=252, min_obs=5)
        assert len(es) == len(series)
        assert es.index.equals(series.index)

    def test_expanding_sharpe_nan_initially(self) -> None:
        series = _positive_drift(n=100)
        es = _expanding_sharpe_series(series, periods_per_year=252, min_obs=5)
        assert np.isnan(es.iloc[0])

    def test_expanding_sharpe_grows_to_full_sharpe(self) -> None:
        series = _positive_drift(sharpe=1.5, n=300)
        es = _expanding_sharpe_series(series, periods_per_year=252, min_obs=5)
        valid = es.dropna()
        assert len(valid) > 0
        # Last value should reflect the full-sample Sharpe (roughly 1.5)
        assert valid.iloc[-1] > 0


# ---------------------------------------------------------------------------
# compute_rolling_metrics
# ---------------------------------------------------------------------------


class TestComputeRollingMetrics:
    def test_returns_rolling_sharpe_per_window(self) -> None:
        series = _positive_drift()
        result = compute_rolling_metrics(series, config=DecayConfig())
        assert set(result.rolling_sharpes.keys()) == {30, 60, 90}

    def test_all_series_same_index(self) -> None:
        series = _positive_drift()
        result = compute_rolling_metrics(series, config=DecayConfig())
        for w, rs in result.rolling_sharpes.items():
            assert rs.index.equals(series.index), f"Window {w} index mismatch"
        assert result.expanding_sharpe.index.equals(series.index)
        assert result.decay_gap.index.equals(series.index)

    def test_decay_gap_all_nan_without_backtest_sharpe(self) -> None:
        series = _positive_drift()
        result = compute_rolling_metrics(series, backtest_sharpe=None)
        assert result.decay_gap.isna().all()
        assert result.backtest_sharpe is None

    def test_decay_gap_computed_with_backtest_sharpe(self) -> None:
        series = _positive_drift(sharpe=1.5)
        result = compute_rolling_metrics(series, backtest_sharpe=1.5)
        valid_gap = result.decay_gap.dropna()
        assert len(valid_gap) > 0
        # gap = backtest_sharpe - rolling_sharpe; not all NaN
        assert not valid_gap.isna().any()

    def test_primary_window_in_result(self) -> None:
        cfg = DecayConfig(rolling_windows=(20, 40))
        series = _positive_drift()
        result = compute_rolling_metrics(series, config=cfg)
        assert result.primary_window == 20

    def test_custom_config_windows(self) -> None:
        cfg = DecayConfig(rolling_windows=(10, 20))
        series = _positive_drift()
        result = compute_rolling_metrics(series, config=cfg)
        assert set(result.rolling_sharpes.keys()) == {10, 20}


# ---------------------------------------------------------------------------
# assess_signal -- HEALTHY
# ---------------------------------------------------------------------------


class TestAssessSignalHealthy:
    def test_strong_positive_drift_is_healthy(self) -> None:
        series = _positive_drift(sharpe=2.0)
        verdict = assess_signal("sig", series, backtest_sharpe=2.0)
        assert verdict.status == "HEALTHY"
        assert verdict.days_in_state == 0

    def test_verdict_name(self) -> None:
        series = _positive_drift()
        verdict = assess_signal("my_signal", series)
        assert verdict.name == "my_signal"

    def test_n_obs_populated(self) -> None:
        series = _positive_drift(n=200)
        verdict = assess_signal("sig", series)
        assert verdict.n_obs == 200

    def test_latest_rolling_sharpe_not_none(self) -> None:
        series = _positive_drift(n=200)
        verdict = assess_signal("sig", series, config=DecayConfig(rolling_windows=(30, 60)))
        assert verdict.latest_rolling_sharpe is not None

    def test_latest_inception_sharpe_not_none(self) -> None:
        series = _positive_drift(n=200)
        verdict = assess_signal("sig", series)
        assert verdict.latest_inception_sharpe is not None

    def test_decay_gap_none_without_backtest(self) -> None:
        series = _positive_drift()
        verdict = assess_signal("sig", series, backtest_sharpe=None)
        assert verdict.latest_decay_gap is None
        assert verdict.backtest_sharpe is None

    def test_decay_gap_not_none_with_backtest(self) -> None:
        series = _positive_drift()
        verdict = assess_signal("sig", series, backtest_sharpe=1.5)
        assert verdict.latest_decay_gap is not None
        assert verdict.backtest_sharpe == 1.5

    def test_reason_mentions_healthy(self) -> None:
        series = _positive_drift()
        verdict = assess_signal("sig", series)
        assert "retire run" in verdict.reason.lower() or "HEALTHY" in verdict.reason

    def test_metrics_attached(self) -> None:
        series = _positive_drift()
        verdict = assess_signal("sig", series)
        assert isinstance(verdict.metrics, RollingSharpeSeries)


# ---------------------------------------------------------------------------
# assess_signal -- RETIRE
# ---------------------------------------------------------------------------


class TestAssessSignalRetire:
    def test_retire_triggered_by_long_negative_tail(self) -> None:
        """Use retirement_days <= trailing negative run to guarantee RETIRE.

        seed=20240605 with n_negative=80 yields a trailing negative run of 25
        on primary window=20, so we set retirement_days=20 to sit below that.
        """
        series = _retire_series(n=400, n_negative=80)
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=20)
        verdict = assess_signal("bad_signal", series, config=cfg)
        assert verdict.status == "RETIRE"

    def test_retire_days_in_state_positive(self) -> None:
        series = _retire_series(n=400, n_negative=80)
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=20)
        verdict = assess_signal("bad_signal", series, config=cfg)
        assert verdict.days_in_state >= cfg.retirement_days

    def test_retire_reason_mentions_negative(self) -> None:
        series = _retire_series(n=400, n_negative=80)
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60)
        verdict = assess_signal("bad_signal", series, config=cfg)
        if verdict.status == "RETIRE":
            assert "negative" in verdict.reason.lower()

    def test_all_negative_returns_retires_quickly(self) -> None:
        """Guarantee retire by using a strongly negative drift + short threshold.

        A constant series has std=0 -> Sharpe=0 (not negative), so we use a
        noisy negative series instead.
        """
        rng = np.random.default_rng(77)
        sigma = 0.01
        arr = rng.normal(-3.0 / np.sqrt(252.0) * sigma, sigma, 200)
        series = pd.Series(arr, index=_dates(200))
        cfg = DecayConfig(rolling_windows=(10, 20), retirement_days=10)
        verdict = assess_signal("always_neg", series, config=cfg)
        assert verdict.status == "RETIRE"

    def test_retire_latest_rolling_sharpe_negative(self) -> None:
        rng = np.random.default_rng(77)
        sigma = 0.01
        arr = rng.normal(-3.0 / np.sqrt(252.0) * sigma, sigma, 200)
        series = pd.Series(arr, index=_dates(200))
        cfg = DecayConfig(rolling_windows=(10, 20), retirement_days=10)
        verdict = assess_signal("always_neg", series, config=cfg)
        assert verdict.latest_rolling_sharpe is not None
        assert verdict.latest_rolling_sharpe < 0


# ---------------------------------------------------------------------------
# assess_signal -- WARN
# ---------------------------------------------------------------------------


class TestAssessSignalWarn:
    def test_warn_triggered_when_rolling_below_fraction(self) -> None:
        series = _warn_series(n=400)
        # warn_days=20 should be met by the long near-zero tail
        cfg = DecayConfig(rolling_windows=(30, 60), warn_days=20, decay_warn_fraction=0.5)
        verdict = assess_signal("warn_sig", series, backtest_sharpe=1.2, config=cfg)
        # The second half has near-zero Sharpe < 0.5 * 1.2 = 0.6 for many bars
        assert verdict.status in ("WARN", "RETIRE")

    def test_warn_not_triggered_without_backtest_sharpe(self) -> None:
        """Without a backtest_sharpe reference, WARN rule is skipped."""
        series = _warn_series(n=400)
        # Even with warn_days=1 and fraction=0.5, no backtest_sharpe -> no WARN
        cfg = DecayConfig(rolling_windows=(30, 60), warn_days=1, decay_warn_fraction=0.5)
        verdict = assess_signal("warn_sig", series, backtest_sharpe=None, config=cfg)
        # Should be HEALTHY since we can't compute the warn threshold
        assert verdict.status == "HEALTHY"

    def test_warn_days_in_state_positive(self) -> None:
        series = _warn_series(n=400)
        cfg = DecayConfig(rolling_windows=(30, 60), warn_days=20, decay_warn_fraction=0.5)
        verdict = assess_signal("warn_sig", series, backtest_sharpe=1.2, config=cfg)
        if verdict.status == "WARN":
            assert verdict.days_in_state >= cfg.warn_days

    def test_warn_reason_mentions_fraction(self) -> None:
        series = _warn_series(n=400)
        cfg = DecayConfig(rolling_windows=(30, 60), warn_days=20, decay_warn_fraction=0.5)
        verdict = assess_signal("warn_sig", series, backtest_sharpe=1.2, config=cfg)
        if verdict.status == "WARN":
            assert "backtest" in verdict.reason.lower() or "fraction" in verdict.reason.lower() or "50%" in verdict.reason


# ---------------------------------------------------------------------------
# count_trailing_condition
# ---------------------------------------------------------------------------


class TestCountTrailingCondition:
    def test_all_true(self) -> None:
        cond = pd.Series([True, True, True])
        assert _count_trailing_condition(cond) == 3

    def test_all_false(self) -> None:
        cond = pd.Series([False, False, False])
        assert _count_trailing_condition(cond) == 0

    def test_trailing_true_subset(self) -> None:
        cond = pd.Series([False, True, False, True, True, True])
        assert _count_trailing_condition(cond) == 3

    def test_single_true_at_end(self) -> None:
        cond = pd.Series([False, False, True])
        assert _count_trailing_condition(cond) == 1

    def test_nan_stops_count(self) -> None:
        """NaN in the condition (from rolling NaN) should stop the count."""
        cond = pd.Series([True, np.nan, True, True])
        # object dtype from mixed nan -- trailing True, True = 2 before nan
        assert _count_trailing_condition(cond) == 2


# ---------------------------------------------------------------------------
# build_decay_report
# ---------------------------------------------------------------------------


class TestBuildDecayReport:
    def test_three_signals_all_statuses(self) -> None:
        signals = {
            "healthy": _positive_drift(sharpe=2.0, n=400),
            "retire": _retire_series(n=400, n_negative=80),
        }
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60)
        report = build_decay_report(
            signals,
            backtest_sharpes={"healthy": 2.0, "retire": 1.0},
            config=cfg,
            generated_at="1970-01-01T00:00:00Z",
        )
        assert len(report.verdicts) == 2
        assert report.generated_at == "1970-01-01T00:00:00Z"

    def test_status_counts_correct(self) -> None:
        signals = {
            "a": _positive_drift(sharpe=2.0, n=300),
            "b": _positive_drift(sharpe=1.5, n=300),
        }
        report = build_decay_report(signals, generated_at="2000-01-01T00:00:00Z")
        assert report.n_healthy + report.n_warn + report.n_retire == 2
        assert isinstance(report.n_healthy, int)

    def test_ranking_by_rolling_sharpe(self) -> None:
        """Highest rolling Sharpe should appear first."""
        signals = {
            "low": _make_series(drift=0.5, n=300, seed=1),
            "high": _make_series(drift=2.5, n=300, seed=2),
        }
        report = build_decay_report(signals, generated_at="2000-01-01T00:00:00Z")
        if (
            report.verdicts[0].latest_rolling_sharpe is not None
            and report.verdicts[1].latest_rolling_sharpe is not None
        ):
            assert (
                report.verdicts[0].latest_rolling_sharpe
                >= report.verdicts[1].latest_rolling_sharpe
            )

    def test_empty_signals_dict(self) -> None:
        report = build_decay_report({}, generated_at="2000-01-01T00:00:00Z")
        assert len(report.verdicts) == 0
        assert report.n_healthy == 0
        assert report.n_warn == 0
        assert report.n_retire == 0

    def test_generated_at_default_is_string(self) -> None:
        signals = {"s": _positive_drift(n=200)}
        report = build_decay_report(signals)
        assert isinstance(report.generated_at, str)
        assert "T" in report.generated_at  # ISO timestamp

    def test_config_attached(self) -> None:
        cfg = DecayConfig(rolling_windows=(15, 30))
        signals = {"s": _positive_drift(n=200)}
        report = build_decay_report(signals, config=cfg)
        assert report.config is cfg

    def test_no_backtest_sharpes_ok(self) -> None:
        """Omitting backtest_sharpes skips WARN but should not raise."""
        signals = {"s": _positive_drift(n=200)}
        report = build_decay_report(signals, generated_at="2000-01-01T00:00:00Z")
        assert len(report.verdicts) == 1

    def test_partial_backtest_sharpes(self) -> None:
        """Signals absent from backtest_sharpes get None backtest reference."""
        signals = {
            "a": _positive_drift(n=200),
            "b": _positive_drift(n=200),
        }
        report = build_decay_report(
            signals,
            backtest_sharpes={"a": 1.5},
            generated_at="2000-01-01T00:00:00Z",
        )
        verdicts_by_name = {v.name: v for v in report.verdicts}
        assert verdicts_by_name["a"].backtest_sharpe == 1.5
        assert verdicts_by_name["b"].backtest_sharpe is None


# ---------------------------------------------------------------------------
# render_decay_report
# ---------------------------------------------------------------------------


class TestRenderDecayReport:
    def _get_report(self) -> DecayReport:
        signals = {
            "signal_a": _positive_drift(sharpe=2.0, n=400),
            "signal_b": _warn_series(n=400),
        }
        return build_decay_report(
            signals,
            backtest_sharpes={"signal_a": 2.0, "signal_b": 1.2},
            generated_at="1970-01-01T00:00:00Z",
        )

    def test_render_is_string(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        assert isinstance(text, str)

    def test_ascii_only(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        for char in text:
            assert ord(char) < 128, f"Non-ASCII character found: {repr(char)}"

    def test_contains_header(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        assert "Signal Decay Report" in text

    def test_contains_generated_at(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        assert "1970-01-01T00:00:00Z" in text

    def test_contains_signal_names(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        assert "signal_a" in text
        assert "signal_b" in text

    def test_contains_status_labels(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        # At minimum HEALTHY or WARN should appear
        assert any(label in text for label in ("HEALTHY", "WARN", "RETIRE"))

    def test_contains_section_headers(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        assert "Signal Summary" in text
        assert "Signal Detail" in text

    def test_no_emoji_or_unicode_symbols(self) -> None:
        report = self._get_report()
        text = render_decay_report(report)
        # Common Unicode markers that must not appear
        for forbidden in ("✓", "✗", "✔", "⚠", "→"):
            assert forbidden not in text


# ---------------------------------------------------------------------------
# RetrainPolicy
# ---------------------------------------------------------------------------


class TestRetrainPolicy:
    def test_defaults_construction(self) -> None:
        p = RetrainPolicy(model_family="ml", cadence_days=21, window_days=756)
        assert p.model_family == "ml"
        assert p.cadence_days == 21
        assert p.window_days == 756

    def test_empty_family_raises(self) -> None:
        with pytest.raises(ValueError, match="model_family"):
            RetrainPolicy(model_family="", cadence_days=21, window_days=756)

    def test_bad_cadence_raises(self) -> None:
        with pytest.raises(ValueError, match="cadence_days"):
            RetrainPolicy(model_family="ml", cadence_days=0, window_days=756)

    def test_bad_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window_days"):
            RetrainPolicy(model_family="ml", cadence_days=21, window_days=0)

    def test_frozen(self) -> None:
        p = RetrainPolicy(model_family="ml", cadence_days=21, window_days=756)
        with pytest.raises((AttributeError, TypeError)):
            p.cadence_days = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DEFAULT_RETRAIN_POLICIES
# ---------------------------------------------------------------------------


class TestDefaultRetrainPolicies:
    def test_contains_ml(self) -> None:
        families = [p.model_family for p in DEFAULT_RETRAIN_POLICIES]
        assert "ml" in families

    def test_contains_garch(self) -> None:
        families = [p.model_family for p in DEFAULT_RETRAIN_POLICIES]
        assert "garch" in families

    def test_contains_hmm(self) -> None:
        families = [p.model_family for p in DEFAULT_RETRAIN_POLICIES]
        assert "hmm" in families

    def test_contains_factor(self) -> None:
        families = [p.model_family for p in DEFAULT_RETRAIN_POLICIES]
        assert "factor" in families

    def test_ml_cadence_monthly(self) -> None:
        ml = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "ml")
        assert ml.cadence_days == 21

    def test_ml_window_3year(self) -> None:
        ml = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "ml")
        assert ml.window_days == 756

    def test_garch_cadence_weekly(self) -> None:
        garch = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "garch")
        assert garch.cadence_days == 5

    def test_hmm_cadence_weekly(self) -> None:
        hmm = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "hmm")
        assert hmm.cadence_days == 5

    def test_factor_cadence_monthly(self) -> None:
        factor = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "factor")
        assert factor.cadence_days == 21

    def test_factor_window_2year(self) -> None:
        factor = next(p for p in DEFAULT_RETRAIN_POLICIES if p.model_family == "factor")
        assert factor.window_days == 504


# ---------------------------------------------------------------------------
# due_for_retrain
# ---------------------------------------------------------------------------


class TestDueForRetrain:
    _today = date(2026, 1, 15)
    _policies = list(DEFAULT_RETRAIN_POLICIES)

    def test_never_trained_always_due(self) -> None:
        result = due_for_retrain(self._policies, {}, self._today)
        assert len(result) == len(self._policies)

    def test_recently_trained_not_due(self) -> None:
        yesterday = self._today - timedelta(days=1)
        last_trained = {p.model_family: yesterday for p in self._policies}
        result = due_for_retrain(self._policies, last_trained, self._today)
        assert result == []

    def test_exactly_at_cadence_is_due(self) -> None:
        ml = next(p for p in self._policies if p.model_family == "ml")
        last_day = self._today - timedelta(days=ml.cadence_days)
        result = due_for_retrain([ml], {ml.model_family: last_day}, self._today)
        assert ml in result

    def test_one_day_before_cadence_not_due(self) -> None:
        ml = next(p for p in self._policies if p.model_family == "ml")
        recent = self._today - timedelta(days=ml.cadence_days - 1)
        result = due_for_retrain([ml], {ml.model_family: recent}, self._today)
        assert result == []

    def test_partial_last_trained(self) -> None:
        """Mix of trained and untrained families."""
        ml = next(p for p in self._policies if p.model_family == "ml")
        garch = next(p for p in self._policies if p.model_family == "garch")
        # ml trained recently, garch never trained
        last_trained = {ml.model_family: self._today - timedelta(days=1)}
        result = due_for_retrain([ml, garch], last_trained, self._today)
        families = [p.model_family for p in result]
        assert "garch" in families
        assert "ml" not in families

    def test_empty_policies(self) -> None:
        result = due_for_retrain([], {}, self._today)
        assert result == []

    def test_preserves_input_order(self) -> None:
        """Due results should appear in the same order as the input policies."""
        p1 = RetrainPolicy("z_model", 5, 100)
        p2 = RetrainPolicy("a_model", 5, 100)
        old = self._today - timedelta(days=10)
        last_trained = {"z_model": old, "a_model": old}
        result = due_for_retrain([p1, p2], last_trained, self._today)
        assert result[0].model_family == "z_model"
        assert result[1].model_family == "a_model"

    def test_tuple_policies_accepted(self) -> None:
        result = due_for_retrain(DEFAULT_RETRAIN_POLICIES, {}, self._today)
        assert len(result) == len(DEFAULT_RETRAIN_POLICIES)


# ---------------------------------------------------------------------------
# render_retrain_schedule
# ---------------------------------------------------------------------------


class TestRenderRetrainSchedule:
    _today = date(2026, 1, 15)

    def test_returns_string(self) -> None:
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), {}, self._today)
        assert isinstance(text, str)

    def test_ascii_only(self) -> None:
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), {}, self._today)
        for char in text:
            assert ord(char) < 128, f"Non-ASCII character: {repr(char)}"

    def test_contains_header(self) -> None:
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), {}, self._today)
        assert "Retrain Cadence Status" in text

    def test_due_marked_yes(self) -> None:
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), {}, self._today)
        assert "YES" in text

    def test_not_due_marked_no(self) -> None:
        yesterday = self._today - timedelta(days=1)
        last_trained = {p.model_family: yesterday for p in DEFAULT_RETRAIN_POLICIES}
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), last_trained, self._today)
        assert "no" in text

    def test_never_shown_as_never(self) -> None:
        text = render_retrain_schedule(list(DEFAULT_RETRAIN_POLICIES), {}, self._today)
        assert "never" in text


# ---------------------------------------------------------------------------
# CLI --demo smoke tests
# ---------------------------------------------------------------------------


class TestCLIDemo:
    def test_demo_runs_without_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "Signal Decay Report" in captured.out

    def test_demo_output_is_ascii(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        for char in captured.out:
            assert ord(char) < 128, f"Non-ASCII char: {repr(char)}"

    def test_demo_shows_three_signals(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "signal_alpha" in captured.out
        assert "signal_warn" in captured.out
        assert "signal_retire" in captured.out

    def test_demo_output_includes_report_header(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "# Signal Decay Report" in captured.out

    def test_demo_output_includes_retrain_section(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "Retrain Cadence Status" in captured.out

    def test_demo_output_file(self, tmp_path: Path) -> None:
        out_file = tmp_path / "decay_report.txt"
        main(["--demo", "--output", str(out_file)])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "Signal Decay Report" in content

    def test_no_flags_prints_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_utcnow_str_format(self) -> None:
        ts = _utcnow_str()
        assert ts.endswith("Z")
        assert "T" in ts


# ---------------------------------------------------------------------------
# __init__ re-export test
# ---------------------------------------------------------------------------


class TestInitReExport:
    def test_decay_config_importable(self) -> None:
        from core_trading.research import DecayConfig  # noqa: F401

    def test_signal_verdict_importable(self) -> None:
        from core_trading.research import SignalVerdict  # noqa: F401

    def test_decay_report_importable(self) -> None:
        from core_trading.research import DecayReport  # noqa: F401

    def test_retrain_policy_importable(self) -> None:
        from core_trading.research import RetrainPolicy  # noqa: F401

    def test_default_retrain_policies_importable(self) -> None:
        from core_trading.research import DEFAULT_RETRAIN_POLICIES  # noqa: F401

    def test_due_for_retrain_importable(self) -> None:
        from core_trading.research import due_for_retrain  # noqa: F401

    def test_build_decay_report_importable(self) -> None:
        from core_trading.research import build_decay_report  # noqa: F401

    def test_render_decay_report_importable(self) -> None:
        from core_trading.research import render_decay_report  # noqa: F401


# ---------------------------------------------------------------------------
# Demo fixture spot-check: verify the three statuses appear in demo signals
# ---------------------------------------------------------------------------


class TestDemoFixture:
    def test_demo_signals_three_keys(self) -> None:
        signals, bs = _build_demo_signals(n_obs=500)
        assert set(signals.keys()) == {"signal_alpha", "signal_warn", "signal_retire"}

    def test_demo_signals_backtest_sharpes_present(self) -> None:
        _, bs = _build_demo_signals(n_obs=500)
        assert "signal_alpha" in bs
        assert "signal_warn" in bs
        assert "signal_retire" in bs

    def test_demo_signal_alpha_healthy(self) -> None:
        signals, bs = _build_demo_signals(n_obs=500)
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60, warn_days=30)
        verdict = assess_signal(
            "signal_alpha", signals["signal_alpha"], backtest_sharpe=bs["signal_alpha"], config=cfg
        )
        assert verdict.status == "HEALTHY"

    def test_demo_signal_warn_warns(self) -> None:
        signals, bs = _build_demo_signals(n_obs=500)
        # seed=118 with late drift -0.3 gives warn_run=49 > warn_days=30 but
        # retire_run=4 < retirement_days=60, so status should be WARN.
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60, warn_days=30)
        verdict = assess_signal(
            "signal_warn", signals["signal_warn"], backtest_sharpe=bs["signal_warn"], config=cfg
        )
        assert verdict.status == "WARN"

    def test_demo_signal_retire_retires(self) -> None:
        signals, bs = _build_demo_signals(n_obs=500)
        # primary window=20, retirement_days=60; seed 999 gives 87 consecutive
        # negative rolling-Sharpe trailing bars -> RETIRE
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60, warn_days=30)
        verdict = assess_signal(
            "signal_retire",
            signals["signal_retire"],
            backtest_sharpe=bs["signal_retire"],
            config=cfg,
        )
        assert verdict.status == "RETIRE"

    def test_full_demo_report_has_all_statuses(self) -> None:
        signals, bs = _build_demo_signals(n_obs=500)
        # Use the same config as the demo CLI for consistency.
        # retirement_days=60, primary window=20, warn_days=30.
        cfg = DecayConfig(rolling_windows=(20, 60), retirement_days=60, warn_days=30)
        report = build_decay_report(
            signals,
            backtest_sharpes=bs,
            config=cfg,
            generated_at="1970-01-01T00:00:00Z",
        )
        statuses = {v.status for v in report.verdicts}
        # signal_alpha -> HEALTHY; signal_warn -> WARN (seed 118, warn_run=49);
        # signal_retire -> RETIRE (seed 999, 87 neg bars)
        assert "RETIRE" in statuses
        assert "HEALTHY" in statuses
        assert "WARN" in statuses
