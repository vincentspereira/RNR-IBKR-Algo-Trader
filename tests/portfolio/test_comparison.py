"""Tests for core_trading.portfolio.comparison (Phase 6 DOD).

Covers:
* Structural validity on a factor-structured universe: every method
  produces long-only fully-invested weights; metrics are finite; the
  fit/oos split accounts for every bar.
* The defining cross-method facts: equal weight has HHI = 1/N and
  effective N = N exactly; risk parity pins the max risk contribution to
  1/N; MVO's risk concentration is at least risk parity's.
* The Phase 6 DOD runtime gate measured inside the comparison itself
  (every method < 1 s on 20 assets).
* The zero-variance OOS branch (Sharpe reported as 0, not NaN).
* comparison_report: ASCII-only rendering containing every method row.
* The validation battery (NaN panel, too-short panel, bad fractions).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.comparison import (
    MethodComparison,
    compare_methods,
    comparison_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factor_universe(seed: int, n_obs: int, n_assets: int) -> pd.DataFrame:
    """3-factor + idiosyncratic synthetic daily returns."""
    rng = np.random.default_rng(seed)
    k = 3
    loadings = rng.uniform(0.3, 1.2, size=(n_assets, k))
    factor_vols = np.array([0.010, 0.006, 0.004])
    factors = rng.standard_normal((n_obs, k)) * factor_vols + 0.0002
    idio = rng.standard_normal((n_obs, n_assets)) * rng.uniform(
        0.005, 0.015, size=n_assets
    )
    data = factors @ loadings.T + idio
    index = pd.date_range("2023-01-02", periods=n_obs, freq="B")
    return pd.DataFrame(data, index=index, columns=[f"A{i:02d}" for i in range(n_assets)])


_METHODS = ["equal", "min_variance", "mvo", "hrp", "risk_parity"]


# ---------------------------------------------------------------------------
# Structure and cross-method facts
# ---------------------------------------------------------------------------


class TestCompareMethods:
    @pytest.fixture(scope="class")
    def result(self) -> MethodComparison:
        return compare_methods(
            _factor_universe(0, 400, 20), risk_aversion=4.0, oos_fraction=0.5
        )

    def test_metrics_shape_and_finiteness(self, result: MethodComparison) -> None:
        assert list(result.metrics.index) == _METHODS
        assert np.isfinite(result.metrics.to_numpy()).all()
        assert result.n_fit + result.n_oos == 400
        assert result.n_fit == 200
        assert result.ann_factor == 252.0

    def test_all_methods_long_only_fully_invested(
        self, result: MethodComparison
    ) -> None:
        for method in _METHODS:
            w = result.weights[method].to_numpy()
            assert float(w.sum()) == pytest.approx(1.0, abs=1e-6), method
            assert bool((w >= -1e-9).all()), method

    def test_equal_weight_concentration_facts(
        self, result: MethodComparison
    ) -> None:
        row = result.metrics.loc["equal"]
        assert row["hhi"] == pytest.approx(1.0 / 20.0, abs=1e-12)
        assert row["effective_n"] == pytest.approx(20.0, abs=1e-9)
        assert row["max_weight"] == pytest.approx(0.05, abs=1e-12)

    def test_risk_parity_pins_max_risk_contribution(
        self, result: MethodComparison
    ) -> None:
        assert result.metrics.loc["risk_parity", "max_risk_contribution"] == (
            pytest.approx(1.0 / 20.0, abs=1e-6)
        )

    def test_mvo_concentrates_risk_at_least_as_much_as_rp(
        self, result: MethodComparison
    ) -> None:
        assert (
            result.metrics.loc["mvo", "max_risk_contribution"]
            >= result.metrics.loc["risk_parity", "max_risk_contribution"] - 1e-9
        )

    def test_dod_runtime_gate(self, result: MethodComparison) -> None:
        for method in _METHODS:
            assert result.metrics.loc[method, "runtime_ms"] < 1000.0, method

    def test_zero_variance_oos_reports_zero_sharpe(self) -> None:
        rng = np.random.default_rng(1)
        fit = rng.standard_normal((20, 4)) * 0.01
        oos = np.zeros((10, 4))
        panel = pd.DataFrame(
            np.vstack([fit, oos]),
            index=pd.date_range("2023-01-02", periods=30, freq="B"),
            columns=[f"A{i:02d}" for i in range(4)],
        )
        result = compare_methods(panel, oos_fraction=1.0 / 3.0)
        assert (result.metrics["oos_sharpe_ann"] == 0.0).all()
        assert (result.metrics["oos_vol_ann"] == 0.0).all()
        assert (result.metrics["oos_max_drawdown"] == 0.0).all()


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


class TestComparisonReport:
    def test_ascii_table_contains_everything(self) -> None:
        result = compare_methods(_factor_universe(2, 120, 6), oos_fraction=0.4)
        text = comparison_report(result)
        text.encode("ascii")  # raises UnicodeEncodeError on any non-ASCII
        for method in _METHODS:
            assert method in text
        assert "fit bars: 72" in text
        assert "oos bars: 48" in text
        for column in ["oos_vol", "oos_shrp", "max_dd", "max_w", "eff_n"]:
            assert column in text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_nan_panel_raises(self) -> None:
        panel = _factor_universe(3, 60, 4)
        panel.iloc[5, 2] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            compare_methods(panel)

    @pytest.mark.parametrize("frac", [0.0, 1.0, -0.2])
    def test_bad_oos_fraction(self, frac: float) -> None:
        with pytest.raises(ValueError, match="oos_fraction"):
            compare_methods(_factor_universe(4, 60, 4), oos_fraction=frac)

    @pytest.mark.parametrize("ann", [0.0, -252.0, float("nan")])
    def test_bad_ann_factor(self, ann: float) -> None:
        with pytest.raises(ValueError, match="ann_factor"):
            compare_methods(_factor_universe(5, 60, 4), ann_factor=ann)

    def test_too_short_panel_raises(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            compare_methods(_factor_universe(6, 3, 4), oos_fraction=0.5)
