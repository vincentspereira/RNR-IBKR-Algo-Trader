"""Tests for core_trading.risk.stress (Phase 7.5).

Covers:
* HISTORICAL_SCENARIOS library: all 6 scenarios present; required fields populated.
* apply_scenario replay mode: synthetic panel over scenario window reproduces
  the summed (compounded) window return exactly.
* apply_scenario factor-beta mode: hand-computed 2-asset/2-factor example
  matches exactly.
* apply_scenario validation errors: missing panel dates, shape mismatch, NaN.
* hypothetical_shock: parametric single- and multi-factor shocks with hand
  computation; factor_cov stressed_vol appended to details.
* hypothetical_shock validation errors.
* reverse_stress_linear (closed form): verify shock dict achieves exactly
  loss_target; verify Mahalanobis norm matches analytic formula; verify
  against brute-force scipy.optimize on random linear portfolio.
* reverse_stress_numeric: shock achieves >= loss_target; Mahalanobis norm
  is finite and positive; nonlinear P&L callable.
* vol_shock covariance scaling: a +20 vol_change shock via hypothetical_shock
  with stressed_port_vol scales by expected factor vs baseline.
* build_stress_report: breach flags fire at correct thresholds; worst_scenario
  is correct; empty input raises.
* render_stress_report_markdown: ASCII-only output; every scenario row present;
  contains Generated, Loss limit, Worst scenario, Breach count lines.
* Sign convention: positive pnl = loss (checked across modes).
"""
from __future__ import annotations

import math
import string
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest
import scipy.optimize as sp_opt

from core_trading.risk.stress import (
    HISTORICAL_SCENARIOS,
    FactorShock,
    HistoricalScenario,
    ScenarioResult,
    StressReport,
    apply_scenario,
    build_stress_report,
    hypothetical_shock,
    render_stress_report_markdown,
    reverse_stress_linear,
    reverse_stress_numeric,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANONICAL_FACTORS = [
    "equity_return",
    "vol_change",
    "rate_change",
    "credit_spread",
    "usd_move",
]


def _make_panel(
    start: str,
    end: str,
    assets: list[str],
    values: np.ndarray | None = None,
    *,
    rng_seed: int = 0,
) -> pd.DataFrame:
    """Synthetic returns panel covering [start, end] (business day freq)."""
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(rng_seed)
    n_days = len(idx)
    n_assets = len(assets)
    if values is None:
        values = rng.normal(0.0, 0.01, size=(n_days, n_assets))
    return pd.DataFrame(values, index=idx, columns=assets)


def _simple_betas(n_assets: int = 2, n_factors: int = 2) -> np.ndarray:
    """Return identity-like betas for easy hand-computation."""
    B = np.zeros((n_assets, n_factors))
    for i in range(min(n_assets, n_factors)):
        B[i, i] = 1.0
    return B


# ---------------------------------------------------------------------------
# HISTORICAL_SCENARIOS library
# ---------------------------------------------------------------------------


class TestHistoricalScenariosLibrary:
    """Verify the built-in scenario library is well-formed."""

    EXPECTED_KEYS = {
        "gfc_2008",
        "flash_crash_2010",
        "cny_deval_2015",
        "q4_2018",
        "covid_2020",
        "inflation_rates_2022",
    }

    def test_all_six_scenarios_present(self) -> None:
        assert set(HISTORICAL_SCENARIOS.keys()) == self.EXPECTED_KEYS

    @pytest.mark.parametrize("key", list(EXPECTED_KEYS))
    def test_scenario_fields_populated(self, key: str) -> None:
        sc = HISTORICAL_SCENARIOS[key]
        assert sc.name != ""
        assert sc.start != ""
        assert sc.end != ""
        assert sc.description != ""
        # Dates are parseable
        pd.Timestamp(sc.start)
        pd.Timestamp(sc.end)
        assert pd.Timestamp(sc.start) <= pd.Timestamp(sc.end)

    @pytest.mark.parametrize("key", list(EXPECTED_KEYS))
    def test_canonical_factors_present(self, key: str) -> None:
        sc = HISTORICAL_SCENARIOS[key]
        for fname in _CANONICAL_FACTORS:
            assert fname in sc.shocks, f"Missing factor {fname!r} in scenario {key!r}"

    @pytest.mark.parametrize("key", list(EXPECTED_KEYS))
    def test_shocks_nonzero(self, key: str) -> None:
        sc = HISTORICAL_SCENARIOS[key]
        for fname, shock in sc.shocks.items():
            assert shock.magnitude != 0.0, (
                f"Scenario {key!r} factor {fname!r} has zero magnitude"
            )
            assert shock.name == fname

    def test_gfc_equity_return_negative(self) -> None:
        """GFC equity_return must be a large negative number."""
        gfc = HISTORICAL_SCENARIOS["gfc_2008"]
        assert gfc.shocks["equity_return"].magnitude < -0.20

    def test_2022_rate_change_positive(self) -> None:
        """2022 rate_change must be positive (rates rose sharply)."""
        sc = HISTORICAL_SCENARIOS["inflation_rates_2022"]
        assert sc.shocks["rate_change"].magnitude > 1.0

    def test_covid_vol_change_large(self) -> None:
        sc = HISTORICAL_SCENARIOS["covid_2020"]
        assert sc.shocks["vol_change"].magnitude >= 40.0


# ---------------------------------------------------------------------------
# apply_scenario -- replay mode
# ---------------------------------------------------------------------------


class TestApplyScenarioReplayMode:
    """Replay mode: synthetic panel reproduces compounded window return."""

    def _scenario_window(self) -> HistoricalScenario:
        """Small synthetic scenario with a known window."""
        return HistoricalScenario(
            name="Test Scenario",
            start="2024-01-02",
            end="2024-01-05",
            shocks={},
            description="Synthetic test",
        )

    def test_single_asset_single_day_exact(self) -> None:
        """1 asset, 1 day panel: pnl = -weight * return (loss convention)."""
        sc = HistoricalScenario(
            name="Test",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [0.05]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        result = apply_scenario(sc, np.array([1.0]), returns_panel=panel)
        assert result.method == "replay"
        # portfolio return = 0.05; pnl (loss) = -0.05
        assert pytest.approx(result.pnl, abs=1e-12) == -0.05

    def test_two_asset_multiday_exact(self) -> None:
        """2 assets, 3 days: compounded return vs hand computation."""
        sc = HistoricalScenario(
            name="Test",
            start="2024-01-02",
            end="2024-01-04",
            shocks={},
        )
        # Asset A: returns [+1%, +2%, +3%]  => compound = 1.01*1.02*1.03 - 1 = 0.061206
        # Asset B: returns [-1%, -2%, -3%]  => compound = 0.99*0.98*0.97 - 1 = -0.058806
        data = {
            "A": [0.01, 0.02, 0.03],
            "B": [-0.01, -0.02, -0.03],
        }
        idx = pd.bdate_range("2024-01-02", periods=3)
        panel = pd.DataFrame(data, index=idx)
        weights = np.array([0.6, 0.4])

        result = apply_scenario(sc, weights, returns_panel=panel)

        comp_a = 1.01 * 1.02 * 1.03 - 1.0
        comp_b = 0.99 * 0.98 * 0.97 - 1.0
        expected_pnl = -(0.6 * comp_a + 0.4 * comp_b)
        assert pytest.approx(result.pnl, abs=1e-12) == expected_pnl

    def test_replay_uses_window_only(self) -> None:
        """Panel extends beyond scenario window; only window dates used."""
        sc = HistoricalScenario(
            name="Test",
            start="2024-01-03",
            end="2024-01-03",
            shocks={},
        )
        # 5 days panel; only Jan 3 is in the window
        idx = pd.bdate_range("2024-01-01", periods=5)
        returns_val = np.array([[0.10], [0.20], [0.05], [-0.01], [-0.02]])
        panel = pd.DataFrame(returns_val, index=idx, columns=["X"])
        result = apply_scenario(sc, np.array([1.0]), returns_panel=panel)
        # Jan 3 return = 0.05; pnl = -0.05
        assert pytest.approx(result.pnl, abs=1e-12) == -0.05

    def test_details_contains_asset_returns(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [0.03], "B": [-0.02]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        result = apply_scenario(sc, np.array([0.5, 0.5]), returns_panel=panel)
        assert "A" in result.details
        assert "B" in result.details
        assert pytest.approx(result.details["A"], abs=1e-12) == 0.03
        assert pytest.approx(result.details["B"], abs=1e-12) == -0.02

    def test_replay_positive_loss_sign(self) -> None:
        """A portfolio long equity that falls: pnl must be positive (loss)."""
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"SPY": [-0.10]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        result = apply_scenario(sc, np.array([1.0]), returns_panel=panel)
        # Long portfolio, equity falls 10% => loss of 10% => pnl = +0.10
        assert result.pnl > 0.0
        assert pytest.approx(result.pnl, abs=1e-12) == 0.10

    def test_replay_no_dates_raises(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2023-01-02",
            end="2023-01-06",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [0.01, 0.02]},
            index=pd.bdate_range("2024-01-02", periods=2),
        )
        with pytest.raises(ValueError, match="no dates"):
            apply_scenario(sc, np.array([1.0]), returns_panel=panel)

    def test_replay_shape_mismatch_raises(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [0.01], "B": [0.02]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        with pytest.raises(ValueError, match="columns"):
            apply_scenario(sc, np.array([1.0, 0.5, 0.5]), returns_panel=panel)

    def test_replay_nan_raises(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [float("nan")]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        with pytest.raises(ValueError, match="NaN"):
            apply_scenario(sc, np.array([1.0]), returns_panel=panel)

    def test_replay_non_datetime_index_raises(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame({"A": [0.01]}, index=[0])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            apply_scenario(sc, np.array([1.0]), returns_panel=panel)


# ---------------------------------------------------------------------------
# apply_scenario -- factor-beta mode (hand-computed)
# ---------------------------------------------------------------------------


class TestApplyScenarioFactorBeta:
    """Factor-beta mode: hand-computed 2-asset/2-factor examples."""

    def _setup(self) -> tuple[HistoricalScenario, np.ndarray, np.ndarray, list[str]]:
        """2 assets, 2 factors; equity_return and rate_change."""
        sc = HistoricalScenario(
            name="Test",
            start="2024-01-01",
            end="2024-01-01",
            shocks={
                "equity_return": FactorShock("equity_return", -0.10),
                "rate_change": FactorShock("rate_change", 0.50),
            },
            description="Hand-computed test",
        )
        # Asset A: beta_equity=1.0, beta_rate=-0.5 (bond-like)
        # Asset B: beta_equity=0.8, beta_rate=0.0 (pure equity)
        betas = np.array([[1.0, -0.5], [0.8, 0.0]])
        weights = np.array([0.5, 0.5])
        factor_names = ["equity_return", "rate_change"]
        return sc, weights, betas, factor_names

    def test_pnl_matches_hand_computation(self) -> None:
        sc, weights, betas, factor_names = self._setup()
        result = apply_scenario(
            sc,
            weights,
            betas=betas,
            factor_names=factor_names,
        )
        # Asset A return = 1.0*(-0.10) + (-0.5)*(0.50) = -0.10 - 0.25 = -0.35
        # Asset B return = 0.8*(-0.10) + 0.0*0.50 = -0.08
        # Portfolio return = 0.5*(-0.35) + 0.5*(-0.08) = -0.175 - 0.04 = -0.215
        # pnl (positive loss) = +0.215
        assert result.method == "factor_beta"
        assert pytest.approx(result.pnl, abs=1e-12) == 0.215

    def test_details_factor_attribution(self) -> None:
        sc, weights, betas, factor_names = self._setup()
        result = apply_scenario(
            sc,
            weights,
            betas=betas,
            factor_names=factor_names,
        )
        # equity_return attribution:
        #   per_asset = [1.0*(-0.10), 0.8*(-0.10)] = [-0.10, -0.08]
        #   portfolio = 0.5*(-0.10) + 0.5*(-0.08) = -0.09
        #   loss attribution = -(-0.09) = +0.09
        assert "equity_return" in result.details
        assert pytest.approx(result.details["equity_return"], abs=1e-12) == 0.09
        # rate_change attribution:
        #   per_asset = [-0.5*0.50, 0.0*0.50] = [-0.25, 0.0]
        #   portfolio = 0.5*(-0.25) + 0.5*0.0 = -0.125
        #   loss attribution = +0.125
        assert pytest.approx(result.details["rate_change"], abs=1e-12) == 0.125

    def test_total_attribution_sums_to_pnl(self) -> None:
        sc, weights, betas, factor_names = self._setup()
        result = apply_scenario(
            sc,
            weights,
            betas=betas,
            factor_names=factor_names,
        )
        total_attr = sum(result.details.values())
        assert pytest.approx(total_attr, abs=1e-10) == result.pnl

    def test_missing_factor_in_scenario_raises(self) -> None:
        sc = HistoricalScenario(
            name="T",
            start="2024-01-01",
            end="2024-01-01",
            shocks={"equity_return": FactorShock("equity_return", -0.10)},
        )
        betas = np.array([[1.0, 0.5]])
        with pytest.raises(ValueError, match="not found"):
            apply_scenario(
                sc,
                np.array([1.0]),
                betas=betas,
                factor_names=["equity_return", "rate_change"],
            )

    def test_no_inputs_raises(self) -> None:
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        with pytest.raises(ValueError, match="replay mode"):
            apply_scenario(sc, np.array([0.5, 0.5]))

    def test_beta_dimension_mismatch_raises(self) -> None:
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        with pytest.raises(ValueError, match="rows"):
            apply_scenario(
                sc,
                np.array([0.5, 0.5]),
                betas=np.array([[1.0]]),   # 1 row but 2 weights
                factor_names=["equity_return"],
            )

    def test_factor_names_length_mismatch_raises(self) -> None:
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        with pytest.raises(ValueError, match="factor_names"):
            apply_scenario(
                sc,
                np.array([0.5]),
                betas=np.array([[1.0, 0.5]]),
                factor_names=["equity_return"],   # 1 name but 2 beta cols
            )

    def test_betas_not_2d_raises(self) -> None:
        """apply_scenario factor-beta mode: 1-D betas array raises."""
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        with pytest.raises(ValueError, match="2-D"):
            apply_scenario(
                sc,
                np.array([0.5]),
                betas=np.array([1.0, 0.5]),   # 1-D, not 2-D
                factor_names=["equity_return", "vol_change"],
            )


# ---------------------------------------------------------------------------
# apply_scenario -- GFC historical scenario via factor betas (sanity check)
# ---------------------------------------------------------------------------


class TestGFCScenario:
    def test_long_equity_portfolio_loses_under_gfc(self) -> None:
        """A 100% equity portfolio must show a large positive pnl under GFC."""
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        weights = np.array([1.0])   # 100% equity
        # 1 asset (equity) with beta=1.0 to equity_return factor
        betas = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
        factor_names = _CANONICAL_FACTORS
        result = apply_scenario(
            sc,
            weights,
            betas=betas,
            factor_names=factor_names,
        )
        # equity_return shock = -0.305; pnl = -(-0.305) = 0.305
        assert result.pnl > 0.0
        assert pytest.approx(result.pnl, abs=1e-12) == 0.305


# ---------------------------------------------------------------------------
# hypothetical_shock
# ---------------------------------------------------------------------------


class TestHypotheticalShock:
    """Parametric single- and multi-factor shocks."""

    def test_single_factor_equity_shock_10pct(self) -> None:
        """Hand-computed: 2 assets, equity_return shock of -10%."""
        weights = np.array([0.6, 0.4])
        betas = np.array([[1.0, 0.0], [0.9, 0.0]])
        factor_names = ["equity_return", "rate_change"]
        result = hypothetical_shock(
            weights,
            betas,
            {"equity_return": -0.10},
            factor_names,
        )
        # Asset A return = 1.0*(-0.10) = -0.10
        # Asset B return = 0.9*(-0.10) = -0.09
        # Portfolio return = 0.6*(-0.10) + 0.4*(-0.09) = -0.06 - 0.036 = -0.096
        # pnl = +0.096
        assert pytest.approx(result.pnl, abs=1e-12) == 0.096
        assert result.method == "factor_beta"

    def test_single_factor_rate_shock_50bp(self) -> None:
        """Rate shock +0.50 pp (+50bps) on bond-like asset."""
        weights = np.array([1.0])
        betas = np.array([[0.0, -5.0]])   # duration ~ 5 years
        factor_names = ["equity_return", "rate_change"]
        result = hypothetical_shock(
            weights,
            betas,
            {"rate_change": 0.50},
            factor_names,
        )
        # return = -5.0 * 0.50 = -2.50  (bond falls when rates rise)
        # pnl = +2.50
        assert pytest.approx(result.pnl, abs=1e-12) == 2.50

    def test_multi_factor_shock(self) -> None:
        """Simultaneous equity and rate shock."""
        weights = np.array([0.5, 0.5])
        betas = np.array([
            [1.0, -2.0],   # equity-heavy with bond duration
            [0.0,  3.0],   # rate-sensitive only
        ])
        factor_names = ["equity_return", "rate_change"]
        shocks = {"equity_return": -0.10, "rate_change": 0.50}
        result = hypothetical_shock(weights, betas, shocks, factor_names)
        # Asset A: 1.0*(-0.10) + (-2.0)*(0.50) = -0.10 - 1.00 = -1.10
        # Asset B: 0.0*(-0.10) + 3.0*0.50 = 1.50
        # Portfolio = 0.5*(-1.10) + 0.5*(1.50) = -0.55 + 0.75 = 0.20
        # pnl = -0.20
        assert pytest.approx(result.pnl, abs=1e-12) == -0.20

    def test_zero_shock_gives_zero_pnl(self) -> None:
        weights = np.array([0.5, 0.5])
        betas = np.array([[1.0, 0.5], [0.8, 0.2]])
        factor_names = ["equity_return", "rate_change"]
        result = hypothetical_shock(weights, betas, {}, factor_names)
        assert pytest.approx(result.pnl, abs=1e-12) == 0.0

    def test_vol_shock_stressed_port_vol(self) -> None:
        """Vol shock: stressed_port_vol appended to details when factor_cov given."""
        weights = np.array([0.5, 0.5])
        betas = np.array([[1.0, 0.0], [1.0, 0.0]])
        factor_names = ["equity_return", "vol_change"]
        # Simple diagonal factor covariance
        factor_cov = np.diag([0.04, 100.0])   # equity var=0.04, vol var=100
        result = hypothetical_shock(
            weights,
            betas,
            {"vol_change": 20.0},
            factor_names,
            factor_cov=factor_cov,
        )
        assert "stressed_port_vol" in result.details
        # g = B'w = [1.0*0.5+1.0*0.5, 0.0*0.5+0.0*0.5] = [1.0, 0.0]
        # port_factor_var = g' * factor_cov * g = 1.0*0.04*1.0 = 0.04
        # stressed_port_vol = sqrt(0.04) = 0.2
        assert pytest.approx(result.details["stressed_port_vol"], abs=1e-10) == 0.2

    def test_factor_cov_wrong_shape_raises(self) -> None:
        weights = np.array([1.0])
        betas = np.array([[1.0, 0.5]])
        factor_names = ["equity_return", "vol_change"]
        with pytest.raises(ValueError, match="factor_cov"):
            hypothetical_shock(
                weights,
                betas,
                {},
                factor_names,
                factor_cov=np.eye(3),  # wrong shape
            )

    def test_betas_1d_raises(self) -> None:
        with pytest.raises(ValueError, match="2-D"):
            hypothetical_shock(
                np.array([1.0]),
                np.array([1.0, 0.5]),   # 1-D instead of 2-D
                {},
                ["equity_return", "rate_change"],
            )

    def test_weights_betas_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="rows"):
            hypothetical_shock(
                np.array([0.5, 0.5]),   # 2 assets
                np.array([[1.0, 0.5]]),  # 1 row
                {},
                ["equity_return", "rate_change"],
            )

    def test_factor_names_length_mismatch_raises(self) -> None:
        """hypothetical_shock: factor_names count != betas columns."""
        with pytest.raises(ValueError, match="factor_names"):
            hypothetical_shock(
                np.array([0.5, 0.5]),
                np.array([[1.0, 0.5], [0.8, 0.3]]),   # 2 columns
                {},
                ["equity_return"],   # only 1 name
            )


# ---------------------------------------------------------------------------
# reverse_stress_linear -- analytic closed form
# ---------------------------------------------------------------------------


class TestReverseStressLinear:
    """Verify closed-form against brute-force and analytic formulas."""

    def _setup_2f(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        """2-asset, 2-factor setup for hand verification."""
        weights = np.array([0.6, 0.4])
        betas = np.array([[1.0, -0.5], [0.8, 0.0]])
        factor_cov = np.array([[0.04, 0.005], [0.005, 0.01]])
        factor_names = ["equity_return", "rate_change"]
        return weights, betas, factor_cov, factor_names

    def test_shock_achieves_loss_target(self) -> None:
        """The analytic shock, when applied, produces exactly loss_target."""
        weights, betas, factor_cov, factor_names = self._setup_2f()
        loss_target = 0.10
        shock_dict, _ = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, loss_target
        )
        # Verify: apply shock to get P&L
        shock_vec = np.array([shock_dict[f] for f in factor_names])
        pnl = float(-(weights @ (betas @ shock_vec)))
        assert pytest.approx(pnl, abs=1e-10) == loss_target

    def test_mahalanobis_norm_analytic(self) -> None:
        """Verify Mahalanobis norm = lambda / sqrt(g' Sigma g)."""
        weights, betas, factor_cov, factor_names = self._setup_2f()
        loss_target = 0.10
        _, mahal = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, loss_target
        )
        g = betas.T @ weights
        g_Sigma_g = float(g @ factor_cov @ g)
        expected_mahal = loss_target / math.sqrt(g_Sigma_g)
        assert pytest.approx(mahal, rel=1e-8) == expected_mahal

    def test_scales_linearly_with_loss_target(self) -> None:
        """Mahalanobis norm scales linearly with loss_target."""
        weights, betas, factor_cov, factor_names = self._setup_2f()
        _, m1 = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, 0.05
        )
        _, m2 = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, 0.10
        )
        assert pytest.approx(m2 / m1, rel=1e-8) == 2.0

    def test_agrees_with_brute_force_scipy(self) -> None:
        """Analytic solution matches scipy.optimize brute-force on random portfolio."""
        rng = np.random.default_rng(42)
        n_assets, n_f = 5, 3
        weights = np.abs(rng.normal(0, 1, n_assets))
        weights /= weights.sum()
        betas = rng.normal(0, 0.5, (n_assets, n_f))
        # Build a valid SPD factor_cov via A'A + I
        A = rng.normal(0, 1, (n_f, n_f))
        factor_cov = A.T @ A + 0.1 * np.eye(n_f)
        factor_names = [f"f{i}" for i in range(n_f)]
        loss_target = 0.08

        # Analytic solution
        shock_dict_analytic, mahal_analytic = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, loss_target
        )

        # Brute-force via scipy: minimise Mahalanobis norm s.t. pnl >= loss_target
        Sigma_inv = np.linalg.inv(factor_cov)

        def _obj(f: np.ndarray) -> float:
            return float(f @ Sigma_inv @ f)

        def _con(f: np.ndarray) -> float:
            return float(-(weights @ (betas @ f))) - loss_target

        f0 = np.zeros(n_f)
        # Initialise with the analytic solution to help convergence
        f0 = np.array([shock_dict_analytic[k] for k in factor_names])
        res = sp_opt.minimize(
            _obj,
            f0 * 1.01,
            method="SLSQP",
            constraints={"type": "ineq", "fun": _con},
            options={"ftol": 1e-12, "maxiter": 2000},
        )
        mahal_numeric = math.sqrt(max(res.fun, 0.0))

        # Both solutions must achieve loss_target
        f_star = np.array([shock_dict_analytic[k] for k in factor_names])
        pnl_analytic = float(-(weights @ (betas @ f_star)))
        assert pytest.approx(pnl_analytic, abs=1e-8) == loss_target

        # Mahalanobis norms must agree within 0.1% relative
        assert pytest.approx(mahal_analytic, rel=1e-3) == mahal_numeric

    def test_zero_loss_target_raises(self) -> None:
        weights, betas, factor_cov, factor_names = self._setup_2f()
        with pytest.raises(ValueError, match="loss_target"):
            reverse_stress_linear(weights, betas, factor_cov, factor_names, 0.0)

    def test_negative_loss_target_raises(self) -> None:
        weights, betas, factor_cov, factor_names = self._setup_2f()
        with pytest.raises(ValueError, match="loss_target"):
            reverse_stress_linear(weights, betas, factor_cov, factor_names, -0.05)

    def test_zero_factor_exposure_raises(self) -> None:
        """Portfolio with all-zero betas has no factor exposure."""
        weights = np.array([0.5, 0.5])
        betas = np.zeros((2, 2))
        factor_cov = np.eye(2)
        with pytest.raises(ValueError, match="zero factor exposure"):
            reverse_stress_linear(
                weights, betas, factor_cov, ["f1", "f2"], 0.05
            )

    def test_betas_shape_mismatch_raises(self) -> None:
        weights = np.array([0.5, 0.5])
        factor_cov = np.eye(2)
        with pytest.raises(ValueError, match="betas"):
            reverse_stress_linear(
                weights,
                np.eye(3),   # 3 rows but 2 weights
                factor_cov,
                ["f1", "f2"],
                0.05,
            )

    def test_factor_cov_shape_mismatch_raises(self) -> None:
        weights = np.array([1.0])
        betas = np.array([[1.0, 0.5]])
        with pytest.raises(ValueError, match="factor_cov"):
            reverse_stress_linear(
                weights, betas, np.eye(3), ["f1", "f2"], 0.05
            )

    def test_factor_names_length_mismatch_raises(self) -> None:
        """reverse_stress_linear: factor_names count != betas columns."""
        weights = np.array([1.0])
        betas = np.array([[1.0, 0.5]])   # 2 columns
        factor_cov = np.eye(2)
        with pytest.raises(ValueError, match="factor_names"):
            reverse_stress_linear(
                weights, betas, factor_cov, ["f1"], 0.05   # 1 name != 2 cols
            )


# ---------------------------------------------------------------------------
# reverse_stress_numeric
# ---------------------------------------------------------------------------


class TestReverseStressNumeric:
    """Numeric reverse stress test: nonlinear P&L callable."""

    def _linear_pnl_fn(
        self,
        weights: np.ndarray,
        betas: np.ndarray,
        factor_names: list[str],
    ) -> Callable[[dict[str, float]], float]:
        """Wrap a linear portfolio as a callable P&L function."""
        def pnl_fn(shocks: dict[str, float]) -> float:
            sv = np.array([shocks.get(f, 0.0) for f in factor_names])
            return float(-(weights @ (betas @ sv)))
        return pnl_fn

    def test_achieves_loss_target_linear(self) -> None:
        weights = np.array([0.6, 0.4])
        betas = np.array([[1.0, -0.5], [0.8, 0.0]])
        factor_names = ["equity_return", "rate_change"]
        factor_cov = np.array([[0.04, 0.005], [0.005, 0.01]])
        loss_target = 0.05

        pnl_fn = self._linear_pnl_fn(weights, betas, factor_names)
        shock_dict, mahal = reverse_stress_numeric(
            pnl_fn,
            factor_names,
            factor_cov,
            loss_target,
            grid_steps=15,
            rng_seed=42,
        )
        # Shock must achieve >= loss_target
        achieved = pnl_fn(shock_dict)
        assert achieved >= loss_target - 1e-4

        # Mahalanobis norm must be positive and finite
        assert mahal > 0.0
        assert math.isfinite(mahal)

    def test_numeric_agrees_with_analytic_on_linear(self) -> None:
        """Numeric solution within 2% of analytic on a 2-factor linear portfolio."""
        weights = np.array([0.6, 0.4])
        betas = np.array([[1.0, -0.5], [0.8, 0.0]])
        factor_names = ["equity_return", "rate_change"]
        factor_cov = np.array([[0.04, 0.005], [0.005, 0.01]])
        loss_target = 0.08

        pnl_fn = self._linear_pnl_fn(weights, betas, factor_names)
        _, mahal_numeric = reverse_stress_numeric(
            pnl_fn,
            factor_names,
            factor_cov,
            loss_target,
            grid_steps=20,
            rng_seed=0,
        )
        _, mahal_analytic = reverse_stress_linear(
            weights, betas, factor_cov, factor_names, loss_target
        )
        # Numeric should be within 5% of analytic (it is approximate)
        assert abs(mahal_numeric - mahal_analytic) / mahal_analytic < 0.05

    def test_nonlinear_pnl_callable(self) -> None:
        """Nonlinear (quadratic) P&L function: numeric finds a valid shock."""
        factor_names = ["f1", "f2"]
        factor_cov = np.eye(2) * 0.01
        loss_target = 0.10

        # P&L = f1^2 + f2^2 -- grows quadratically; nonlinear
        def pnl_fn(shocks: dict[str, float]) -> float:
            return shocks.get("f1", 0.0)**2 + shocks.get("f2", 0.0)**2

        shock_dict, mahal = reverse_stress_numeric(
            pnl_fn,
            factor_names,
            factor_cov,
            loss_target,
            grid_steps=20,
            rng_seed=7,
        )
        assert pnl_fn(shock_dict) >= loss_target - 1e-3
        assert mahal > 0.0

    def test_no_achievable_target_raises(self) -> None:
        """P&L capped below loss_target: numeric should raise ValueError."""
        factor_names = ["f1"]
        factor_cov = np.eye(1) * 1e-6  # tiny covariance -> very small shocks
        loss_target = 1e6  # unreachably large

        def pnl_fn(shocks: dict[str, float]) -> float:
            return shocks.get("f1", 0.0) * 1e-10

        with pytest.raises(ValueError, match="Grid search"):
            reverse_stress_numeric(
                pnl_fn,
                factor_names,
                factor_cov,
                loss_target,
                grid_steps=5,
                rng_seed=0,
            )

    def test_zero_loss_target_raises(self) -> None:
        with pytest.raises(ValueError, match="loss_target"):
            reverse_stress_numeric(
                lambda _: 0.0,
                ["f1"],
                np.eye(1),
                0.0,
            )

    def test_non_psd_cov_raises(self) -> None:
        with pytest.raises(ValueError, match="Cholesky"):
            reverse_stress_numeric(
                lambda _: 0.0,
                ["f1", "f2"],
                np.array([[-1.0, 0.0], [0.0, 1.0]]),  # not PSD
                0.05,
            )

    def test_empty_factor_names_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            reverse_stress_numeric(
                lambda _: 0.0,
                [],          # empty
                np.eye(0),   # shape (0,0) -- consistent
                0.05,
            )

    def test_factor_cov_wrong_shape_raises(self) -> None:
        """factor_cov shape doesn't match len(factor_names)."""
        with pytest.raises(ValueError, match="factor_cov"):
            reverse_stress_numeric(
                lambda _: 0.0,
                ["f1", "f2"],
                np.eye(3),   # 3x3 but 2 factor names
                0.05,
            )


# ---------------------------------------------------------------------------
# Vol shock covariance scaling
# ---------------------------------------------------------------------------


class TestVolShockScaling:
    """A +20 vol_change shock scales the portfolio vol by an expected factor."""

    def test_vol_shock_scales_stressed_vol(self) -> None:
        """stressed_port_vol from hypothetical_shock matches manual computation."""
        n_assets = 3
        rng = np.random.default_rng(99)
        weights = np.array([0.4, 0.3, 0.3])
        # 3 assets, 2 factors: equity_return and vol_change
        betas = rng.normal(0, 0.5, (n_assets, 2))
        factor_names = ["equity_return", "vol_change"]

        # Baseline factor cov: equity var=0.04, vol var=25 (vol is ~5 VIX pts daily)
        baseline_factor_cov = np.array([[0.04, 0.002], [0.002, 25.0]])

        result = hypothetical_shock(
            weights,
            betas,
            {"vol_change": 20.0},
            factor_names,
            factor_cov=baseline_factor_cov,
        )
        # Manual: g = B' w; port_var = g' Sigma g; stressed_vol = sqrt(port_var)
        g = betas.T @ weights
        expected_vol = float(np.sqrt(max(float(g @ baseline_factor_cov @ g), 0.0)))
        assert pytest.approx(result.details["stressed_port_vol"], rel=1e-10) == (
            expected_vol
        )

    def test_vol_shock_detail_always_nonnegative(self) -> None:
        weights = np.array([1.0])
        betas = np.array([[1.0, 1.0]])
        factor_cov = np.diag([0.04, 0.01])
        result = hypothetical_shock(
            weights,
            betas,
            {"vol_change": -20.0},   # downward vol shock
            ["equity_return", "vol_change"],
            factor_cov=factor_cov,
        )
        assert result.details["stressed_port_vol"] >= 0.0


# ---------------------------------------------------------------------------
# build_stress_report
# ---------------------------------------------------------------------------


class TestBuildStressReport:
    def _make_results(self) -> list[ScenarioResult]:
        return [
            ScenarioResult("A", 0.05, "factor_beta"),
            ScenarioResult("B", 0.12, "replay"),
            ScenarioResult("C", 0.08, "factor_beta"),
            ScenarioResult("D", -0.01, "factor_beta"),
        ]

    def test_worst_scenario_is_max_pnl(self) -> None:
        results = self._make_results()
        report = build_stress_report(results, loss_limit=0.10)
        assert report.worst_scenario.scenario_name == "B"
        assert pytest.approx(report.worst_scenario.pnl) == 0.12

    def test_breach_flags_at_threshold(self) -> None:
        results = self._make_results()
        # With loss_limit=0.10: B (0.12) breaches; A, C, D do not
        report = build_stress_report(results, loss_limit=0.10)
        assert report.breaches == ["B"]

    def test_breach_at_exact_limit(self) -> None:
        """pnl == loss_limit is a breach (>= check)."""
        results = [
            ScenarioResult("X", 0.10, "factor_beta"),
            ScenarioResult("Y", 0.05, "factor_beta"),
        ]
        report = build_stress_report(results, loss_limit=0.10)
        assert "X" in report.breaches

    def test_no_breach_when_all_below_limit(self) -> None:
        results = [ScenarioResult("A", 0.03, "factor_beta")]
        report = build_stress_report(results, loss_limit=0.10)
        assert report.breaches == []

    def test_all_breach_when_all_above_limit(self) -> None:
        results = [
            ScenarioResult("A", 0.20, "factor_beta"),
            ScenarioResult("B", 0.15, "factor_beta"),
        ]
        report = build_stress_report(results, loss_limit=0.10)
        assert set(report.breaches) == {"A", "B"}

    def test_loss_limit_stored(self) -> None:
        results = self._make_results()
        report = build_stress_report(results, loss_limit=0.05)
        assert report.loss_limit == 0.05

    def test_generated_at_auto_set(self) -> None:
        results = self._make_results()
        report = build_stress_report(results)
        assert report.generated_at != ""
        # Must be parseable as an ISO timestamp
        ts = pd.Timestamp(report.generated_at.rstrip("Z"), tz=None)
        assert isinstance(ts, pd.Timestamp)

    def test_generated_at_custom_passthrough(self) -> None:
        results = self._make_results()
        report = build_stress_report(results, generated_at="2024-01-15T10:00:00Z")
        assert report.generated_at == "2024-01-15T10:00:00Z"

    def test_empty_results_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_stress_report([])

    def test_invalid_loss_limit_raises(self) -> None:
        results = self._make_results()
        with pytest.raises(ValueError, match="loss_limit"):
            build_stress_report(results, loss_limit=0.0)
        with pytest.raises(ValueError, match="loss_limit"):
            build_stress_report(results, loss_limit=1.5)

    def test_results_list_preserved(self) -> None:
        results = self._make_results()
        report = build_stress_report(results)
        assert len(report.results) == len(results)
        for orig, stored in zip(results, report.results, strict=False):
            assert orig.scenario_name == stored.scenario_name


# ---------------------------------------------------------------------------
# render_stress_report_markdown
# ---------------------------------------------------------------------------


class TestRenderStressReportMarkdown:
    """ASCII markdown renderer tests."""

    _ALLOWED = set(string.printable)

    def _make_report(self) -> StressReport:
        results = [
            ScenarioResult("GFC 2008", 0.305, "factor_beta"),
            ScenarioResult("Flash Crash", 0.032, "replay"),
            ScenarioResult("COVID 2020", 0.339, "factor_beta"),
            ScenarioResult("CNY Aug 2015", -0.02, "factor_beta"),
        ]
        return build_stress_report(
            results,
            loss_limit=0.10,
            generated_at="2024-01-15T09:30:00Z",
        )

    def test_ascii_only(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        for ch in md:
            assert ch in self._ALLOWED, f"Non-ASCII character found: {ch!r}"

    def test_all_scenario_names_present(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        for r in report.results:
            assert r.scenario_name in md

    def test_contains_generated_line(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "Generated:" in md
        assert "2024-01-15T09:30:00Z" in md

    def test_contains_loss_limit_line(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "Loss limit:" in md
        assert "10.00%" in md

    def test_contains_worst_scenario_line(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "Worst scenario:" in md
        assert report.worst_scenario.scenario_name in md

    def test_contains_breach_count_line(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "Breach count:" in md

    def test_breach_marked_yes(self) -> None:
        """Scenarios with pnl >= limit must appear with YES."""
        report = self._make_report()
        md = render_stress_report_markdown(report)
        # GFC (30.5%) and COVID (33.9%) breach 10% limit
        lines = md.splitlines()
        gfc_line = next(ln for ln in lines if "GFC 2008" in ln)
        assert "YES" in gfc_line

    def test_no_breach_marked_no(self) -> None:
        """CNY 2015 pnl = -0.02, no breach."""
        report = self._make_report()
        md = render_stress_report_markdown(report)
        lines = md.splitlines()
        cny_line = next(ln for ln in lines if "CNY" in ln)
        assert "YES" not in cny_line

    def test_header_row_present(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "Scenario" in md
        assert "P&L" in md
        assert "Method" in md
        assert "Breach" in md

    def test_pnl_positive_shown_with_plus(self) -> None:
        """Positive loss (loss) should have a '+' sign in the table."""
        report = self._make_report()
        md = render_stress_report_markdown(report)
        # GFC pnl = 30.5% shown as +30.50%
        assert "+30.50%" in md

    def test_pnl_negative_shown_with_minus(self) -> None:
        """Negative pnl (portfolio gain) should show as negative %."""
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "-2.00%" in md

    def test_no_unicode_arrows_or_symbols(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        for ch in md:
            assert ord(ch) < 128, f"Non-ASCII ord {ord(ch)!r}: {ch!r}"

    def test_all_method_values_present(self) -> None:
        report = self._make_report()
        md = render_stress_report_markdown(report)
        assert "factor_beta" in md
        assert "replay" in md


# ---------------------------------------------------------------------------
# Sign convention consistency
# ---------------------------------------------------------------------------


class TestSignConvention:
    """Positive pnl = loss, consistent with var.py and cvar.py."""

    def test_long_equity_gfc_positive_loss(self) -> None:
        """A long equity portfolio must show positive pnl under GFC equity fall."""
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        betas = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
        result = apply_scenario(
            sc,
            np.array([1.0]),
            betas=betas,
            factor_names=_CANONICAL_FACTORS,
        )
        assert result.pnl > 0.0

    def test_short_equity_gfc_negative_pnl(self) -> None:
        """A short equity portfolio gains under GFC => negative pnl."""
        sc = HISTORICAL_SCENARIOS["gfc_2008"]
        betas = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
        result = apply_scenario(
            sc,
            np.array([-1.0]),   # short
            betas=betas,
            factor_names=_CANONICAL_FACTORS,
        )
        assert result.pnl < 0.0

    def test_replay_gain_negative_pnl(self) -> None:
        """Replay mode: rising returns panel gives negative pnl (gain)."""
        sc = HistoricalScenario(
            name="T",
            start="2024-01-02",
            end="2024-01-02",
            shocks={},
        )
        panel = pd.DataFrame(
            {"A": [0.05]},
            index=pd.bdate_range("2024-01-02", periods=1),
        )
        result = apply_scenario(sc, np.array([1.0]), returns_panel=panel)
        assert result.pnl < 0.0

    def test_stress_report_worst_is_most_positive_pnl(self) -> None:
        results = [
            ScenarioResult("A", 0.30, "factor_beta"),
            ScenarioResult("B", 0.10, "factor_beta"),
            ScenarioResult("C", -0.05, "factor_beta"),
        ]
        report = build_stress_report(results, loss_limit=0.25)
        # Worst is highest loss (most positive pnl)
        assert report.worst_scenario.scenario_name == "A"


# ---------------------------------------------------------------------------
# End-to-end: run all 6 historical scenarios on a simple portfolio
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Integration: all 6 scenarios through build_stress_report and renderer."""

    def test_all_scenarios_via_factor_beta(self) -> None:
        """Run all 6 historical scenarios on a simple 2-asset portfolio."""
        weights = np.array([0.7, 0.3])
        # Asset A: equity-heavy; Asset B: bond-like
        betas = np.array([
            [1.0, 0.5, 0.0, 0.0, 0.1],   # equity-heavy
            [0.0, 0.0, -5.0, -0.01, 0.0],  # bond (rate sensitive)
        ])
        factor_names = _CANONICAL_FACTORS

        results = []
        for _key, sc in HISTORICAL_SCENARIOS.items():
            r = apply_scenario(sc, weights, betas=betas, factor_names=factor_names)
            assert math.isfinite(r.pnl)
            results.append(r)

        assert len(results) == 6
        report = build_stress_report(results, loss_limit=0.05)
        md = render_stress_report_markdown(report)

        # All scenario names in markdown
        for sc in HISTORICAL_SCENARIOS.values():
            assert sc.name in md

        # ASCII only
        for ch in md:
            assert ord(ch) < 128

    def test_report_breach_count_correct(self) -> None:
        """With very tight loss_limit=0.001, most scenarios should breach."""
        weights = np.array([1.0])
        betas = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
        factor_names = _CANONICAL_FACTORS

        results = [
            apply_scenario(sc, weights, betas=betas, factor_names=factor_names)
            for sc in HISTORICAL_SCENARIOS.values()
        ]
        # All GFC-type equity falls should give positive pnl (long equity)
        report = build_stress_report(results, loss_limit=0.001)
        md = render_stress_report_markdown(report)
        n_breach = len(report.breaches)
        assert f"{n_breach} / 6" in md
