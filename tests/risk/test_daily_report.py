"""Tests for core_trading.risk.daily_report (Phase 7 DOD).

Covers:
* DailyRiskConfig: validation errors (empty confidences, out-of-range values,
  horizon < 1, stress_loss_limit out of range).
* DailyRiskConfig: defaults are valid and sensible.
* generate_daily_risk_report:
  - Returns a DailyRiskReport with all sections populated.
  - VaR section: both confidence levels present; values are positive.
  - ES section: values are positive and >= corresponding VaR (ES >= VaR).
  - Stress section: all HISTORICAL_SCENARIOS present; hypothetical shocks
    present; StressReport worst_scenario is set.
  - Liquidity section populated when spreads/ADV/positions are provided.
  - Liquidity section is None when optional inputs are absent.
  - generated_at override is respected.
* render_daily_risk_report_markdown:
  - Returns a str containing ASCII characters only (ord(ch) < 128).
  - Contains "Daily Risk Report" header.
  - Contains VaR and Expected Shortfall table.
  - Contains stress scenario names from HISTORICAL_SCENARIOS.
  - Contains "Liquidity" section header when liquidity section is present.
  - Contains "Not available" when liquidity section is absent.
* CLI main():
  - --demo flag produces a non-empty report without error.
  - --demo --output <path> writes the file and main() returns.
  - Calling main([]) without --demo raises SystemExit.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core_trading.risk.daily_report import (
    DailyRiskConfig,
    DailyRiskReport,
    ESSection,
    LiquiditySection,
    StressSection,
    VaRSection,
    generate_daily_risk_report,
    main,
    render_daily_risk_report_markdown,
)
from core_trading.risk.stress import HISTORICAL_SCENARIOS

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_N_OBS = 252
_N_ASSETS = 3
_N_FACTORS = 5
_SEED = 7


def _make_returns_panel(
    seed: int = _SEED,
    n_obs: int = _N_OBS,
    n_assets: int = _N_ASSETS,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n_obs, freq="B")
    sigmas = np.array([0.01, 0.012, 0.015])[:n_assets]
    arr = rng.normal(0.0, 1.0, size=(n_obs, n_assets)) * sigmas
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(arr, index=dates, columns=cols)


def _make_weights(n_assets: int = _N_ASSETS) -> np.ndarray:
    return np.full(n_assets, 1.0 / n_assets, dtype=float)


def _make_factor_model(
    seed: int = _SEED,
    n_assets: int = _N_ASSETS,
    n_factors: int = _N_FACTORS,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    rng = np.random.default_rng(seed + 1)
    betas = rng.normal(0.0, 0.05, size=(n_assets, n_factors))
    betas[:, 0] = rng.uniform(0.7, 1.2, size=n_assets)
    raw = rng.normal(0.0, 1.0, size=(n_factors, n_factors))
    factor_cov = raw @ raw.T / float(n_factors) + np.eye(n_factors) * 0.01
    factor_names = [
        "equity_return",
        "vol_change",
        "rate_change",
        "credit_spread",
        "usd_move",
    ]
    return betas, factor_names, factor_cov


def _make_liquidity_inputs(
    assets: list[str], nav: float = 1_000_000.0, seed: int = _SEED
) -> dict[str, object]:
    rng = np.random.default_rng(seed + 2)
    n = len(assets)
    base_price = rng.uniform(20.0, 100.0, size=n)
    weights = np.full(n, 1.0 / n)
    shares = nav * weights / base_price
    return {
        "positions": {a: float(shares[i]) for i, a in enumerate(assets)},
        "position_values": {a: float(shares[i] * base_price[i]) for i, a in enumerate(assets)},
        "adv": {a: float(rng.uniform(1_000_000, 5_000_000)) for a in assets},
        "spreads_mean": {a: float(rng.uniform(0.0005, 0.002)) for a in assets},
        "spreads_std": {a: float(rng.uniform(0.0001, 0.0005)) for a in assets},
        "asset_vols": {a: 0.01 for a in assets},
        "nav": nav,
    }


def _full_report(config: DailyRiskConfig | None = None) -> DailyRiskReport:
    """Build a complete report with liquidity section for test use."""
    panel = _make_returns_panel()
    weights = _make_weights()
    betas, factor_names, factor_cov = _make_factor_model()
    assets = list(panel.columns)
    liq = _make_liquidity_inputs(assets)
    return generate_daily_risk_report(
        panel,
        weights,
        float(liq["nav"]),
        betas=betas,
        factor_names=factor_names,
        factor_cov=factor_cov,
        spreads_mean=liq["spreads_mean"],
        spreads_std=liq["spreads_std"],
        adv=liq["adv"],
        positions=liq["positions"],
        position_values=liq["position_values"],
        asset_vols=liq["asset_vols"],
        config=config,
    )


# ---------------------------------------------------------------------------
# DailyRiskConfig validation
# ---------------------------------------------------------------------------


class TestDailyRiskConfig:
    def test_defaults_valid(self) -> None:
        cfg = DailyRiskConfig()
        assert 0.95 in cfg.var_confidences
        assert 0.99 in cfg.var_confidences
        assert cfg.horizon == 1
        assert cfg.stress_loss_limit == 0.10

    def test_empty_confidences_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            DailyRiskConfig(var_confidences=())

    def test_out_of_range_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            DailyRiskConfig(var_confidences=(1.5,))

    def test_zero_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            DailyRiskConfig(var_confidences=(0.0,))

    def test_horizon_less_than_one_raises(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            DailyRiskConfig(horizon=0)

    def test_stress_limit_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="stress_loss_limit"):
            DailyRiskConfig(stress_loss_limit=0.0)

    def test_stress_limit_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="stress_loss_limit"):
            DailyRiskConfig(stress_loss_limit=1.5)

    def test_custom_config_valid(self) -> None:
        cfg = DailyRiskConfig(var_confidences=(0.90, 0.95), horizon=10)
        assert cfg.horizon == 10


# ---------------------------------------------------------------------------
# generate_daily_risk_report -- structure
# ---------------------------------------------------------------------------


class TestGenerateDailyRiskReport:
    def test_returns_daily_risk_report(self) -> None:
        report = _full_report()
        assert isinstance(report, DailyRiskReport)

    def test_sections_populated(self) -> None:
        report = _full_report()
        assert isinstance(report.var_section, VaRSection)
        assert isinstance(report.es_section, ESSection)
        assert isinstance(report.stress_section, StressSection)
        assert isinstance(report.liquidity_section, LiquiditySection)

    def test_generated_at_override(self) -> None:
        ts = "2025-01-01T00:00:00Z"
        cfg = DailyRiskConfig(generated_at=ts)
        report = _full_report(config=cfg)
        assert report.generated_at == ts

    def test_generated_at_auto_when_not_set(self) -> None:
        cfg = DailyRiskConfig()
        report = _full_report(config=cfg)
        assert "T" in report.generated_at
        assert report.generated_at.endswith("Z")


# ---------------------------------------------------------------------------
# VaR section
# ---------------------------------------------------------------------------


class TestVaRSection:
    def test_both_confidence_levels_present(self) -> None:
        report = _full_report()
        assert 0.95 in report.var_section.parametric
        assert 0.99 in report.var_section.parametric
        assert 0.95 in report.var_section.historical
        assert 0.99 in report.var_section.historical

    def test_var_values_are_positive(self) -> None:
        report = _full_report()
        for result in report.var_section.parametric.values():
            assert result.var >= 0.0, f"Expected non-negative VaR; got {result.var}"
        for result in report.var_section.historical.values():
            assert result.var >= 0.0

    def test_var_horizon_matches_config(self) -> None:
        cfg = DailyRiskConfig(horizon=5)
        report = _full_report(config=cfg)
        for result in report.var_section.parametric.values():
            assert result.horizon == 5

    def test_99_var_geq_95_var(self) -> None:
        report = _full_report()
        assert (
            report.var_section.parametric[0.99].var
            >= report.var_section.parametric[0.95].var - 1e-12
        )


# ---------------------------------------------------------------------------
# ES section
# ---------------------------------------------------------------------------


class TestESSection:
    def test_both_confidence_levels_present(self) -> None:
        report = _full_report()
        assert 0.95 in report.es_section.historical
        assert 0.99 in report.es_section.historical

    def test_es_positive(self) -> None:
        report = _full_report()
        for es_val in report.es_section.historical.values():
            assert es_val >= 0.0

    def test_es_geq_historical_var(self) -> None:
        report = _full_report()
        for conf in (0.95, 0.99):
            hist_var = report.var_section.historical[conf].var
            hist_es = report.es_section.historical[conf]
            # ES >= VaR by definition (both positive losses)
            assert hist_es >= hist_var - 1e-10, (
                f"At conf={conf}: ES={hist_es:.6f} < VaR={hist_var:.6f}"
            )


# ---------------------------------------------------------------------------
# Stress section
# ---------------------------------------------------------------------------


class TestStressSection:
    def test_all_historical_scenarios_present(self) -> None:
        report = _full_report()
        scenario_names = {r.scenario_name for r in report.stress_section.report.results}
        for scenario in HISTORICAL_SCENARIOS.values():
            assert scenario.name in scenario_names, (
                f"Missing scenario: {scenario.name}"
            )

    def test_hypothetical_shocks_present(self) -> None:
        report = _full_report()
        scenario_names = {r.scenario_name for r in report.stress_section.report.results}
        assert "Equity -10%" in scenario_names
        assert "Equity +10%" in scenario_names
        assert "Rates +50bps" in scenario_names

    def test_worst_scenario_is_set(self) -> None:
        report = _full_report()
        worst = report.stress_section.report.worst_scenario
        assert worst is not None
        assert isinstance(worst.pnl, float)
        assert math.isfinite(worst.pnl)

    def test_stress_report_has_all_results(self) -> None:
        report = _full_report()
        n_historical = len(HISTORICAL_SCENARIOS)
        n_hypothetical = 6   # Equity -/+, Vol -/+, Rates -/+
        assert len(report.stress_section.report.results) == n_historical + n_hypothetical

    def test_worst_pnl_is_max_of_all(self) -> None:
        report = _full_report()
        all_pnl = [r.pnl for r in report.stress_section.report.results]
        assert report.stress_section.report.worst_scenario.pnl == max(all_pnl)


# ---------------------------------------------------------------------------
# Liquidity section
# ---------------------------------------------------------------------------


class TestLiquiditySection:
    def test_present_when_inputs_provided(self) -> None:
        report = _full_report()
        assert report.liquidity_section is not None

    def test_absent_when_inputs_missing(self) -> None:
        panel = _make_returns_panel()
        weights = _make_weights()
        betas, factor_names, factor_cov = _make_factor_model()
        report = generate_daily_risk_report(
            panel,
            weights,
            1_000_000.0,
            betas=betas,
            factor_names=factor_names,
            factor_cov=factor_cov,
        )
        assert report.liquidity_section is None

    def test_dtl_result_is_portfolio_result(self) -> None:
        report = _full_report()
        assert report.liquidity_section is not None
        from core_trading.risk.liquidity import PortfolioLiquidityResult
        assert isinstance(report.liquidity_section.dtl_result, PortfolioLiquidityResult)

    def test_stress_report_nav_positive(self) -> None:
        report = _full_report()
        assert report.liquidity_section is not None
        assert report.liquidity_section.stress_report.nav > 0.0


# ---------------------------------------------------------------------------
# render_daily_risk_report_markdown
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_returns_str(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        assert isinstance(md, str)

    def test_ascii_only(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        for ch in md:
            assert ord(ch) < 128, (
                f"Non-ASCII character found: {ch!r} (ord={ord(ch)})"
            )

    def test_contains_header(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        assert "Daily Risk Report" in md

    def test_contains_var_table(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        assert "VaR and Expected Shortfall" in md
        assert "Parametric VaR" in md
        assert "Historical VaR" in md
        assert "Historical ES" in md

    def test_contains_stress_scenarios(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        # At least the GFC scenario name should appear
        assert "GFC" in md

    def test_contains_liquidity_section_when_present(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        assert "Liquidity" in md

    def test_contains_not_available_when_absent(self) -> None:
        panel = _make_returns_panel()
        weights = _make_weights()
        betas, factor_names, factor_cov = _make_factor_model()
        report = generate_daily_risk_report(
            panel,
            weights,
            1_000_000.0,
            betas=betas,
            factor_names=factor_names,
            factor_cov=factor_cov,
        )
        md = render_daily_risk_report_markdown(report)
        assert "Not available" in md

    def test_confidence_levels_in_table(self) -> None:
        report = _full_report()
        md = render_daily_risk_report_markdown(report)
        assert "95%" in md
        assert "99%" in md

    def test_generated_at_in_output(self) -> None:
        ts = "2026-06-05T12:00:00Z"
        cfg = DailyRiskConfig(generated_at=ts)
        report = _full_report(config=cfg)
        md = render_daily_risk_report_markdown(report)
        assert ts in md


# ---------------------------------------------------------------------------
# Liquidity renderer edge cases (cover inf DTL and flagged_assets branches)
# ---------------------------------------------------------------------------


class TestLiquidityRendererEdgeCases:
    def test_infinite_dtl_rendered_as_inf(self) -> None:
        """When weighted_avg_dtl is inf, the renderer should print 'inf'."""
        # Pass an asset with zero ADV to trigger infinite DTL.
        panel = _make_returns_panel()
        weights = _make_weights()
        betas, factor_names, factor_cov = _make_factor_model()
        assets = list(panel.columns)
        # Zero ADV for one asset forces infinite DTL.
        adv_zero = {a: 0.0 for a in assets}
        liq = _make_liquidity_inputs(assets)
        report = generate_daily_risk_report(
            panel,
            weights,
            float(liq["nav"]),
            betas=betas,
            factor_names=factor_names,
            factor_cov=factor_cov,
            spreads_mean=liq["spreads_mean"],
            spreads_std=liq["spreads_std"],
            adv=adv_zero,
            positions=liq["positions"],
            position_values=liq["position_values"],
            asset_vols=liq["asset_vols"],
        )
        assert report.liquidity_section is not None
        md = render_daily_risk_report_markdown(report)
        # The renderer must show "inf" (not a float) for infinite DTL.
        assert "inf" in md
        # All output still ASCII-only.
        for ch in md:
            assert ord(ch) < 128

    def test_flagged_assets_appear_in_markdown(self) -> None:
        """When zero-ADV assets exist, the DTL summary shows 'Zero-ADV flagged'."""
        panel = _make_returns_panel()
        weights = _make_weights()
        betas, factor_names, factor_cov = _make_factor_model()
        assets = list(panel.columns)
        liq = _make_liquidity_inputs(assets)
        # Set one asset to zero ADV to get a flagged asset.
        adv_with_zero = dict(liq["adv"])
        adv_with_zero[assets[0]] = 0.0
        report = generate_daily_risk_report(
            panel,
            weights,
            float(liq["nav"]),
            betas=betas,
            factor_names=factor_names,
            factor_cov=factor_cov,
            spreads_mean=liq["spreads_mean"],
            spreads_std=liq["spreads_std"],
            adv=adv_with_zero,
            positions=liq["positions"],
            position_values=liq["position_values"],
            asset_vols=liq["asset_vols"],
        )
        assert report.liquidity_section is not None
        assert len(report.liquidity_section.dtl_result.flagged_assets) >= 1
        md = render_daily_risk_report_markdown(report)
        assert "Zero-ADV flagged" in md


# ---------------------------------------------------------------------------
# CLI main() entry point
# ---------------------------------------------------------------------------


class TestCLIMain:
    def test_demo_runs_without_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "Daily Risk Report" in captured.out

    def test_demo_output_ascii_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        for ch in captured.out:
            assert ord(ch) < 128, f"Non-ASCII character in CLI output: {ch!r}"

    def test_demo_with_output_writes_file(
        self, tmp_path: Path
    ) -> None:
        out_file = tmp_path / "daily_risk.md"
        main(["--demo", "--output", str(out_file)])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "Daily Risk Report" in content
        for ch in content:
            assert ord(ch) < 128, f"Non-ASCII character in written file: {ch!r}"

    def test_no_flag_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            main([])

    def test_main_none_argv_uses_sys_argv(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["daily_report", "--demo"])
        main(None)
        captured = capsys.readouterr()
        assert "Daily Risk Report" in captured.out
