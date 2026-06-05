"""Tests for core_trading.research.robustness_report (Phase 10.2).

Validated regimes (deterministic seeds):
* A genuinely-skilled synthetic strategy (persistent positive drift) with a
  trial bank where it dominates -> all gates PASS -> ``PROMOTE``.
* A data-mined best-of-N pure-noise strategy -> DSR / PBO / Reality-Check / CI
  gates FAIL -> ``REJECT``.
* No-trials fallback: DSR / PBO / Reality-Check marked ``NOT_EVALUATED`` and the
  PSR-vs-zero is reported instead; DSR/PBO/RC DTOs are ``None``.
* INSUFFICIENT_DATA when fewer than ``min_observations`` returns.
* RobustnessConfig validation, renderer golden substrings, CLI --demo smoke.

Every gate's observed-vs-limit fields are pinned. Runtime is kept < 30s by
using a reduced bootstrap iteration count in the heavy fixtures.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core_trading.research.robustness_report import (
    BootstrapCIResult,
    CPCVDistribution,
    GateResult,
    RobustnessConfig,
    RobustnessReport,
    _cpcv_oos_distribution,
    _utcnow_str,
    main,
    render_robustness_report,
    run_robustness_report,
    stationary_bootstrap_sharpe_ci,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SEED = 20240605
_T = 1008
_SIGMA = 0.01


def _fast_config() -> RobustnessConfig:
    """Config with reduced bootstrap iterations to keep the suite fast."""
    return RobustnessConfig(bootstrap_iterations=250)


@pytest.fixture(scope="module")
def skilled() -> tuple[pd.Series, pd.DataFrame]:
    """Skilled strategy (drift) + trial bank where it dominates."""
    rng = np.random.default_rng(_SEED)
    drift = 1.6 / np.sqrt(252.0) * _SIGMA
    strat = rng.normal(drift, _SIGMA, _T)
    noise_bank = rng.normal(0.0, _SIGMA, (_T, 15))
    trial_mat = np.column_stack([strat, noise_bank])
    dates = pd.date_range("2020-01-01", periods=_T, freq="B")
    series = pd.Series(strat, index=dates, name="candidate")
    cols = ["candidate"] + [f"noise{i + 1}" for i in range(15)]
    trials = pd.DataFrame(trial_mat, index=dates, columns=cols)
    return series, trials


@pytest.fixture(scope="module")
def mined() -> tuple[pd.Series, pd.DataFrame]:
    """Best-of-N pure-noise data-mined strategy + its noise trial bank."""
    rng = np.random.default_rng(_SEED)
    noise = rng.normal(0.0, _SIGMA, (_T, 60))
    col_sr = noise.mean(axis=0) / noise.std(axis=0, ddof=1)
    best = int(np.argmax(col_sr))
    dates = pd.date_range("2020-01-01", periods=_T, freq="B")
    series = pd.Series(noise[:, best], index=dates, name="mined")
    trials = pd.DataFrame(
        noise, index=dates, columns=[f"n{i}" for i in range(60)]
    )
    return series, trials


@pytest.fixture(scope="module")
def skilled_report(
    skilled: tuple[pd.Series, pd.DataFrame],
) -> RobustnessReport:
    """Computed once and shared across the PROMOTE assertion tests."""
    series, trials = skilled
    return run_robustness_report(
        series, trial_returns=trials, config=_fast_config(), generated_at="X"
    )


@pytest.fixture(scope="module")
def skilled_no_trials_report(
    skilled: tuple[pd.Series, pd.DataFrame],
) -> RobustnessReport:
    """No-trials report on the skilled series, computed once."""
    series, _ = skilled
    return run_robustness_report(
        series, trial_returns=None, config=_fast_config(), generated_at="X"
    )


@pytest.fixture(scope="module")
def mined_report(mined: tuple[pd.Series, pd.DataFrame]) -> RobustnessReport:
    """Computed once and shared across the REJECT assertion tests."""
    series, trials = mined
    return run_robustness_report(
        series, trial_returns=trials, config=_fast_config(), generated_at="X"
    )


def _gate_by_name(report: RobustnessReport, name: str) -> GateResult:
    for g in report.gates:
        if g.name == name:
            return g
    raise KeyError(name)


# ---------------------------------------------------------------------------
# RobustnessConfig validation
# ---------------------------------------------------------------------------


class TestRobustnessConfig:
    def test_defaults_valid(self) -> None:
        cfg = RobustnessConfig()
        assert cfg.dsr_min == 0.95
        assert cfg.pbo_max == 0.5
        assert cfg.reality_check_p_max == 0.10
        assert cfg.min_observations == 252

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"bootstrap_iterations": 0},
            {"block_length": 0.0},
            {"confidence_level": 0.0},
            {"confidence_level": 1.0},
            {"periods_per_year": 0},
            {"cpcv_n_groups": 2},
            {"cpcv_n_test_groups": 0},
            {"cpcv_n_test_groups": 6},
            {"cpcv_embargo_pct": 1.0},
            {"pbo_n_splits": 3},
            {"pbo_n_splits": 0},
            {"dsr_min": 0.0},
            {"dsr_min": 1.0},
            {"pbo_max": 0.0},
            {"pbo_max": 1.0},
            {"reality_check_p_max": 0.0},
            {"reality_check_p_max": 1.0},
            {"cpcv_frac_negative_max": -0.1},
            {"cpcv_frac_negative_max": 1.1},
            {"min_observations": 1},
        ],
    )
    def test_invalid(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            RobustnessConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Bootstrap CI wrapper
# ---------------------------------------------------------------------------


class TestBootstrapSharpeCI:
    def test_ci_brackets_point(self, skilled: tuple[pd.Series, pd.DataFrame]) -> None:
        series, _ = skilled
        ci = stationary_bootstrap_sharpe_ci(
            series, n_bootstrap=400, block_length=20.0, seed=0
        )
        assert isinstance(ci, BootstrapCIResult)
        assert ci.lower < ci.point_sharpe < ci.upper
        assert ci.lower > 0.0  # skilled strategy CI excludes zero

    def test_too_few_raises(self) -> None:
        with pytest.raises(ValueError):
            stationary_bootstrap_sharpe_ci(np.array([0.01]))

    def test_flat_column_zero_sharpe(self) -> None:
        ci = stationary_bootstrap_sharpe_ci(
            np.full(300, 0.01), n_bootstrap=50, seed=1
        )
        assert ci.point_sharpe == 0.0
        assert ci.lower == 0.0 and ci.upper == 0.0

    def test_deterministic(self, skilled: tuple[pd.Series, pd.DataFrame]) -> None:
        series, _ = skilled
        a = stationary_bootstrap_sharpe_ci(series, n_bootstrap=200, seed=7)
        b = stationary_bootstrap_sharpe_ci(series, n_bootstrap=200, seed=7)
        assert a.lower == b.lower and a.upper == b.upper


# ---------------------------------------------------------------------------
# PROMOTE path (skilled)
# ---------------------------------------------------------------------------


class TestPromote:
    def test_verdict_promote(self, skilled_report: RobustnessReport) -> None:
        rep = skilled_report
        assert rep.verdict == "PROMOTE"
        assert rep.promoted is True
        assert all(g.passed for g in rep.gates)
        assert rep.n_trials == 16
        assert rep.generated_at == "X"  # injected timestamp is honoured

    def test_gate_observed_vs_limit(
        self, skilled_report: RobustnessReport
    ) -> None:
        rep = skilled_report
        dsr = _gate_by_name(rep, "Deflated Sharpe Ratio")
        assert dsr.limit == 0.95
        assert dsr.comparison == ">="
        assert dsr.observed is not None and dsr.observed >= 0.95

        pbo = _gate_by_name(rep, "Probability of Backtest Overfitting")
        assert pbo.limit == 0.5
        assert pbo.comparison == "<="
        assert pbo.observed is not None and pbo.observed <= 0.5

        rc = _gate_by_name(rep, "White's Reality Check")
        assert rc.limit == 0.10
        assert rc.observed is not None and rc.observed <= 0.10

        ci_gate = _gate_by_name(rep, "Bootstrap Sharpe CI lower bound")
        assert ci_gate.observed is not None and ci_gate.observed >= 0.0

        cpcv = _gate_by_name(rep, "CPCV out-of-sample stability")
        assert cpcv.observed is not None and cpcv.observed <= 0.5

    def test_distribution_dtos_populated(
        self, skilled_report: RobustnessReport
    ) -> None:
        rep = skilled_report
        assert isinstance(rep.cpcv, CPCVDistribution)
        assert rep.cpcv.n_combinations > 0
        assert rep.cpcv.fraction_negative == 0.0
        assert rep.cpcv.mean > 0.0
        assert rep.spa is not None  # Hansen SPA computed when trials present
        assert rep.point_sharpe is not None and rep.point_sharpe > 1.0


# ---------------------------------------------------------------------------
# REJECT path (mined)
# ---------------------------------------------------------------------------


class TestReject:
    def test_verdict_reject(self, mined_report: RobustnessReport) -> None:
        rep = mined_report
        assert rep.verdict == "REJECT"
        assert rep.promoted is False

    def test_overfitting_gates_fail(
        self, mined_report: RobustnessReport
    ) -> None:
        rep = mined_report
        dsr = _gate_by_name(rep, "Deflated Sharpe Ratio")
        pbo = _gate_by_name(rep, "Probability of Backtest Overfitting")
        rc = _gate_by_name(rep, "White's Reality Check")
        assert dsr.status == "FAIL" and dsr.observed is not None and dsr.observed < 0.95
        assert pbo.status == "FAIL" and pbo.observed is not None and pbo.observed > 0.5
        assert rc.status == "FAIL" and rc.observed is not None and rc.observed > 0.10


# ---------------------------------------------------------------------------
# No-trials fallback path
# ---------------------------------------------------------------------------


class TestNoTrialsFallback:
    def test_dsr_pbo_rc_not_evaluated(
        self, skilled_no_trials_report: RobustnessReport
    ) -> None:
        rep = skilled_no_trials_report
        assert rep.n_trials == 0
        assert rep.deflated_sharpe is None
        assert rep.pbo is None
        assert rep.reality_check is None
        assert rep.spa is None
        assert rep.psr is not None  # PSR reported as the fallback statistic

        for name in (
            "Deflated Sharpe Ratio",
            "Probability of Backtest Overfitting",
            "White's Reality Check",
        ):
            g = _gate_by_name(rep, name)
            assert g.status == "NOT_EVALUATED"
            assert g.observed is None
            assert not g.evaluated

    def test_verdict_rests_on_data_gates(
        self, skilled_no_trials_report: RobustnessReport
    ) -> None:
        # The skilled fixture has CI lower > 0 and zero negative CPCV folds, so
        # the two data-only required gates pass and the verdict is PROMOTE even
        # without any trials.
        assert skilled_no_trials_report.verdict == "PROMOTE"

    def test_single_trial_column_is_no_trials(
        self, skilled: tuple[pd.Series, pd.DataFrame]
    ) -> None:
        # A 1-column matrix cannot support PBO/DSR-spread; treated as no trials.
        series, trials = skilled
        one = trials.iloc[:, [0]]
        rep = run_robustness_report(
            series, trial_returns=one, config=_fast_config(), generated_at="X"
        )
        assert rep.deflated_sharpe is None
        assert _gate_by_name(rep, "Deflated Sharpe Ratio").status == "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# INSUFFICIENT_DATA path
# ---------------------------------------------------------------------------


class TestInsufficientData:
    def test_short_series(self) -> None:
        rng = np.random.default_rng(0)
        short = pd.Series(rng.normal(0.0, 0.01, 100))
        rep = run_robustness_report(
            short, trial_returns=None, config=_fast_config(), generated_at="X"
        )
        assert rep.verdict == "INSUFFICIENT_DATA"
        assert rep.point_sharpe is None
        assert rep.bootstrap_ci is None
        assert rep.cpcv is None
        assert len(rep.gates) == 1
        g = rep.gates[0]
        assert g.name == "Minimum observations"
        assert g.status == "FAIL"
        assert g.observed == 100.0
        assert g.limit == 252.0

    def test_nan_filtered_before_count(self) -> None:
        # 300 values but 250 NaN -> 50 finite -> insufficient.
        vals = np.concatenate([np.full(250, np.nan), np.full(50, 0.01)])
        rep = run_robustness_report(
            pd.Series(vals), trial_returns=None, generated_at="X"
        )
        assert rep.verdict == "INSUFFICIENT_DATA"
        assert rep.n_obs == 50


# ---------------------------------------------------------------------------
# CPCV distribution flat-fold guard
# ---------------------------------------------------------------------------


class TestCPCVFlatFold:
    def test_constant_series_yields_zero_sharpes(self) -> None:
        # An entirely constant series makes every CPCV test fold flat
        # (std == 0), exercising the zero-Sharpe fallback branch.
        cfg = RobustnessConfig(
            cpcv_n_groups=6, cpcv_n_test_groups=2, min_observations=2
        )
        dist = _cpcv_oos_distribution(np.full(60, 0.001), cfg)
        assert isinstance(dist, CPCVDistribution)
        assert np.all(dist.sharpes == 0.0)
        assert dist.fraction_negative == 0.0
        assert dist.std == 0.0


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_ascii_only_and_substrings(
        self, skilled_report: RobustnessReport
    ) -> None:
        text = render_robustness_report(skilled_report)
        assert all(ord(ch) < 128 for ch in text)
        assert "# Statistical Robustness Report" in text
        assert "Verdict    : PROMOTE" in text
        assert "## Promotion Gates" in text
        assert "## Gate Detail" in text
        assert "Deflated Sharpe Ratio" in text
        assert "Probability of Backtest Overfitting" in text
        assert "White's Reality Check" in text
        assert "CPCV out-of-sample stability" in text
        assert "[PASS]" in text

    def test_renders_not_evaluated(
        self, skilled_no_trials_report: RobustnessReport
    ) -> None:
        text = render_robustness_report(skilled_no_trials_report)
        assert "not evaluated (no trials)" in text
        assert "[NOT_EVALUATED]" in text

    def test_renders_insufficient(self) -> None:
        rep = run_robustness_report(
            pd.Series(np.full(50, 0.01)), trial_returns=None, generated_at="X"
        )
        text = render_robustness_report(rep)
        assert all(ord(ch) < 128 for ch in text)
        assert "Verdict    : INSUFFICIENT_DATA" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_demo_smoke(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        out = capsys.readouterr().out
        assert "Statistical Robustness Report" in out
        assert "Verdict    : PROMOTE" in out

    def test_demo_writes_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_path = tmp_path / "report.md"
        main(["--demo", "--output", str(out_path)])
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "Statistical Robustness Report" in content
        assert "Report written to" in capsys.readouterr().out

    def test_requires_demo(self) -> None:
        with pytest.raises(SystemExit):
            main([])


# ---------------------------------------------------------------------------
# Default (live-clock) timestamp
# ---------------------------------------------------------------------------


class TestTimestamp:
    def test_utcnow_str_format(self) -> None:
        # Exercises the live-clock fallback used when generated_at is None.
        stamp = _utcnow_str()
        assert stamp.endswith("Z")
        assert len(stamp) == len("1970-01-01T00:00:00Z")
        # ISO date/time skeleton with the expected separators.
        assert stamp[4] == "-" and stamp[7] == "-" and stamp[10] == "T"

    def test_run_stamps_when_omitted(self) -> None:
        rep = run_robustness_report(
            pd.Series(np.full(50, 0.01)), trial_returns=None
        )
        assert rep.generated_at.endswith("Z")
        assert rep.verdict == "INSUFFICIENT_DATA"
