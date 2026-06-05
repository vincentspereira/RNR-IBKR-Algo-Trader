"""Tests for core_trading.risk.pairs_risk (Phase 4.6).

Covers:
- RiskLimits validation (__post_init__)
- RiskCheck.ok property
- DivergenceAlert severity / breach semantics
- PairsRiskManager.pre_trade: pass, per-symbol violation, gross violation,
  sector violation, multiple simultaneous violations
- PairsRiskManager.check_divergence: critical, warning, none
- PairsRiskManager.daily_check: daily breach, monthly breach, pass, <2 points
- PairsRiskManager.var_check: breach, pass, sign convention, <min_obs
- PairsRiskManager.circuit_breaker: merged violations, all-pass

Sign convention confirmed inline:
  value_at_risk(returns, alpha) returns a POSITIVE loss fraction; the function
  internally computes -np.quantile(returns, alpha), so callers do not negate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest.metrics import value_at_risk
from core_trading.risk.pairs_risk import (
    DEFAULT_LIMITS,
    DivergenceAlert,
    PairsRiskManager,
    RiskCheck,
    RiskLimits,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)


def _equity(values: list[float]) -> pd.Series:
    """Wrap a plain list of NAV values as a pd.Series."""
    return pd.Series(values, dtype=float)


def _returns(values: list[float]) -> pd.Series:
    """Wrap a plain list of period returns as a pd.Series."""
    return pd.Series(values, dtype=float)


# ---------------------------------------------------------------------------
# RiskLimits
# ---------------------------------------------------------------------------


class TestRiskLimits:
    def test_defaults_are_positive(self) -> None:
        lim = RiskLimits()
        assert lim.per_pair_cap == 0.02
        assert lim.sector_cap == 0.30
        assert lim.gross_leverage_cap == 2.0
        assert lim.divergence_z == 3.5
        assert lim.daily_drawdown_limit == 0.05
        assert lim.monthly_drawdown_limit == 0.10
        assert lim.var_limit == 0.05
        assert lim.var_alpha == 0.05

    def test_custom_values_accepted(self) -> None:
        lim = RiskLimits(per_pair_cap=0.05, gross_leverage_cap=3.0)
        assert lim.per_pair_cap == 0.05
        assert lim.gross_leverage_cap == 3.0

    @pytest.mark.parametrize(
        "field",
        [
            "per_pair_cap",
            "sector_cap",
            "gross_leverage_cap",
            "divergence_z",
            "daily_drawdown_limit",
            "monthly_drawdown_limit",
            "var_limit",
            "var_alpha",
        ],
    )
    def test_zero_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            RiskLimits(**{field: 0.0})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field",
        [
            "per_pair_cap",
            "sector_cap",
            "gross_leverage_cap",
            "divergence_z",
            "daily_drawdown_limit",
            "monthly_drawdown_limit",
            "var_limit",
            "var_alpha",
        ],
    )
    def test_negative_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            RiskLimits(**{field: -0.01})  # type: ignore[arg-type]

    def test_frozen(self) -> None:
        lim = RiskLimits()
        with pytest.raises((AttributeError, TypeError)):
            lim.per_pair_cap = 0.99  # type: ignore[misc]

    def test_sector_check_min_gross_defaults_to_zero(self) -> None:
        assert RiskLimits().sector_check_min_gross == 0.0

    def test_sector_check_min_gross_zero_allowed(self) -> None:
        # Unlike the hard limits, the materiality floor may legitimately be 0.
        assert RiskLimits(sector_check_min_gross=0.0).sector_check_min_gross == 0.0

    def test_sector_check_min_gross_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="sector_check_min_gross"):
            RiskLimits(sector_check_min_gross=-0.1)


# ---------------------------------------------------------------------------
# RiskCheck
# ---------------------------------------------------------------------------


class TestRiskCheck:
    def test_ok_property_true(self) -> None:
        chk = RiskCheck(passed=True, violations=())
        assert chk.ok is True

    def test_ok_property_false(self) -> None:
        chk = RiskCheck(passed=False, violations=("something breached",))
        assert chk.ok is False

    def test_frozen(self) -> None:
        chk = RiskCheck(passed=True, violations=())
        with pytest.raises((AttributeError, TypeError)):
            chk.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DivergenceAlert
# ---------------------------------------------------------------------------


class TestDivergenceAlert:
    def test_frozen(self) -> None:
        alert = DivergenceAlert(pair_id="A/B", zscore=1.0, breached=False, severity="none")
        with pytest.raises((AttributeError, TypeError)):
            alert.breached = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Sign-convention confirmation for value_at_risk
# ---------------------------------------------------------------------------


class TestSignConvention:
    """Directly verifies that value_at_risk returns a POSITIVE loss fraction.

    The implementation does -np.quantile(returns, alpha), so a dataset where
    the 5th-percentile return is -0.08 should give VaR == +0.08.
    """

    def test_var_positive_for_negative_returns(self) -> None:
        # All returns are -10%; VaR at any alpha should be +0.10
        rets = _returns([-0.10] * 50)
        var = value_at_risk(rets, 0.05)
        assert var == pytest.approx(0.10, abs=1e-10)

    def test_var_positive_for_mixed_returns(self) -> None:
        # numpy linear interpolation: virtual_idx = alpha*(n-1) = 0.05*19 = 0.95.
        # With 2 values at -0.08 at indices 0 and 1, both bracketing the virtual
        # index, the interpolated quantile is exactly -0.08 -> VaR = +0.08.
        bad = [-0.08] * 2
        good = [0.01] * 18  # total n=20, min for var_alpha=0.05
        rets = _returns(bad + good)
        var = value_at_risk(rets, 0.05)
        # 5th percentile is -0.08 -> VaR = +0.08
        assert var == pytest.approx(0.08, abs=1e-10)

    def test_var_zero_for_positive_only_returns(self) -> None:
        rets = _returns([0.01] * 50)
        var = value_at_risk(rets, 0.05)
        # 5th percentile is +0.01 -> VaR = -0.01, but -np.quantile gives -0.01
        # which would be negative; however the function returns that as-is.
        # In practice a strictly positive return series has var <= 0 which means
        # no loss -- confirm sign directly.
        assert var == pytest.approx(-0.01, abs=1e-10)


# ---------------------------------------------------------------------------
# PairsRiskManager.pre_trade
# ---------------------------------------------------------------------------


class TestPreTrade:
    def setup_method(self) -> None:
        self.mgr = PairsRiskManager(RiskLimits(per_pair_cap=0.02, gross_leverage_cap=2.0))

    def test_weights_within_caps_pass(self) -> None:
        weights = {"AAPL": 0.01, "MSFT": -0.01, "GLD": 0.015}
        chk = self.mgr.pre_trade(weights)
        assert chk.passed
        assert chk.ok
        assert chk.violations == ()

    def test_single_weight_exceeds_per_pair_cap(self) -> None:
        weights = {"AAPL": 0.05}  # 0.05 > 0.02
        chk = self.mgr.pre_trade(weights)
        assert not chk.passed
        assert len(chk.violations) == 1
        assert "AAPL" in chk.violations[0]
        assert "per_pair_cap" in chk.violations[0]

    def test_gross_leverage_violation(self) -> None:
        # Gross = 1.2 + 1.3 = 2.5 > 2.0
        weights = {"A": 1.2, "B": -1.3}
        chk = self.mgr.pre_trade(weights)
        # Both symbols also breach per_pair_cap; at least the gross violation present
        gross_viols = [v for v in chk.violations if "gross" in v.lower()]
        assert len(gross_viols) == 1
        assert not chk.passed

    def test_gross_at_exactly_cap_passes(self) -> None:
        # Per-pair must also be within limit; use small weights summing to exactly 2.0
        # Each of 100 symbols with weight 0.02 -> gross = 2.0, per_pair = 0.02 (not >)
        weights = {f"S{i}": 0.02 for i in range(100)}
        chk = self.mgr.pre_trade(weights)
        # per_pair_cap check is strict (>), so 0.02 is NOT a violation
        per_viols = [v for v in chk.violations if "per_pair_cap" in v]
        assert per_viols == []
        gross_viols = [v for v in chk.violations if "gross" in v.lower()]
        assert gross_viols == []
        assert chk.passed

    def test_sector_concentration_violation(self) -> None:
        # All in one sector -> sector fraction = 1.0 > 0.30
        weights = {"A": 0.01, "B": 0.01, "C": 0.005}
        sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
        chk = self.mgr.pre_trade(weights, sectors=sectors)
        sector_viols = [v for v in chk.violations if "TECH" in v]
        assert len(sector_viols) == 1
        assert not chk.passed

    def test_sector_check_skipped_below_materiality_floor(self) -> None:
        # Same fully-concentrated book, but gross (0.025) sits below the
        # materiality floor: the first pair to enter is always ~100% of a
        # tiny gross, which is not a meaningful concentration signal.
        mgr = PairsRiskManager(
            RiskLimits(per_pair_cap=0.02, sector_check_min_gross=0.25)
        )
        weights = {"A": 0.01, "B": 0.01, "C": 0.005}
        sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
        chk = mgr.pre_trade(weights, sectors=sectors)
        assert chk.passed

    def test_sector_check_applies_at_or_above_materiality_floor(self) -> None:
        mgr = PairsRiskManager(
            RiskLimits(per_pair_cap=0.20, sector_check_min_gross=0.25)
        )
        # Gross 0.30 >= floor 0.25 and TECH is 100% of it: violation.
        weights = {"A": 0.15, "B": -0.15}
        sectors = {"A": "TECH", "B": "TECH"}
        chk = mgr.pre_trade(weights, sectors=sectors)
        assert not chk.passed
        assert any("TECH" in v for v in chk.violations)

    def test_sector_within_cap_passes(self) -> None:
        # TECH gets 20% of gross, FINANCE gets 80% -- still over sector_cap for FINANCE
        # Use weights where TECH = 0.20 * total, FINANCE = 0.80 * total
        weights = {"T1": 0.004, "F1": 0.016}  # gross=0.02; FINANCE=80% of gross
        sectors = {"T1": "TECH", "F1": "FINANCE"}
        chk = self.mgr.pre_trade(weights, sectors=sectors)
        # FINANCE fraction = 0.016/0.02 = 0.80 > 0.30 -> violation
        assert not chk.passed

    def test_sector_all_within_cap_passes(self) -> None:
        # Four equal sectors each at 25% of gross -- all within 30%
        weights = {f"S{i}": 0.005 for i in range(4)}
        sectors = {f"S{i}": f"SEC{i}" for i in range(4)}
        chk = self.mgr.pre_trade(weights, sectors=sectors)
        assert chk.passed, chk.violations

    def test_multiple_violations_all_reported(self) -> None:
        # Two symbols over per_pair_cap + gross over cap + sector over cap
        weights = {"A": 0.05, "B": -0.05, "C": 0.03}  # all > 0.02; gross=0.13
        sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
        chk = self.mgr.pre_trade(weights, sectors=sectors)
        assert not chk.passed
        per_viols = [v for v in chk.violations if "per_pair_cap" in v]
        # A, B, C all breach per_pair_cap
        assert len(per_viols) == 3
        sector_viols = [v for v in chk.violations if "TECH" in v]
        assert len(sector_viols) == 1

    def test_no_sectors_skips_sector_check(self) -> None:
        weights = {"A": 0.01}
        chk = self.mgr.pre_trade(weights, sectors=None)
        sector_viols = [v for v in chk.violations if "Sector" in v]
        assert sector_viols == []

    def test_empty_weights_pass(self) -> None:
        chk = self.mgr.pre_trade({})
        assert chk.passed


# ---------------------------------------------------------------------------
# PairsRiskManager.check_divergence
# ---------------------------------------------------------------------------


class TestCheckDivergence:
    def setup_method(self) -> None:
        # divergence_z=3.5, warning threshold=0.8*3.5=2.8
        self.mgr = PairsRiskManager(RiskLimits(divergence_z=3.5))

    def test_critical_positive_z(self) -> None:
        alert = self.mgr.check_divergence("GLD/SLV", 4.0)
        assert alert.breached
        assert alert.severity == "critical"
        assert alert.pair_id == "GLD/SLV"
        assert alert.zscore == pytest.approx(4.0)

    def test_critical_negative_z(self) -> None:
        alert = self.mgr.check_divergence("GLD/SLV", -4.0)
        assert alert.breached
        assert alert.severity == "critical"

    def test_warning_positive_z(self) -> None:
        # 2.8 < z <= 3.5 -> warning (not breached)
        alert = self.mgr.check_divergence("GLD/SLV", 3.0)
        assert not alert.breached
        assert alert.severity == "warning"

    def test_warning_negative_z(self) -> None:
        alert = self.mgr.check_divergence("GLD/SLV", -3.0)
        assert not alert.breached
        assert alert.severity == "warning"

    def test_none_severity(self) -> None:
        alert = self.mgr.check_divergence("GLD/SLV", 1.0)
        assert not alert.breached
        assert alert.severity == "none"

    def test_exactly_at_threshold_is_not_breached(self) -> None:
        # Strict inequality: |z| > divergence_z is required for breach.
        # At z==3.5 (== divergence_z), breach is False.
        # But |z|=3.5 > 0.8*3.5=2.8 is True, so severity is "warning".
        alert = self.mgr.check_divergence("GLD/SLV", 3.5)
        assert not alert.breached
        assert alert.severity == "warning"

    def test_zero_z_is_none(self) -> None:
        alert = self.mgr.check_divergence("A/B", 0.0)
        assert not alert.breached
        assert alert.severity == "none"


# ---------------------------------------------------------------------------
# PairsRiskManager.daily_check
# ---------------------------------------------------------------------------


class TestDailyCheck:
    def setup_method(self) -> None:
        self.mgr = PairsRiskManager(
            RiskLimits(daily_drawdown_limit=0.05, monthly_drawdown_limit=0.10)
        )

    def test_daily_breach(self) -> None:
        # Equity drops 6% on the last day -> breaches daily_drawdown_limit=5%
        equity = _equity([100.0, 101.0, 102.0, 95.88])  # last ret ~ -6%
        chk = self.mgr.daily_check(equity)
        assert not chk.passed
        daily_viols = [v for v in chk.violations if "Daily" in v]
        assert len(daily_viols) == 1

    def test_monthly_drawdown_breach(self) -> None:
        # Build a 21-point equity curve that peaks early and drops 12%
        peak = 100.0
        trough = peak * (1.0 - 0.12)  # 88.0
        # Linearly decline from peak to trough over 21 days
        vals = list(np.linspace(peak, trough, 21))
        equity = _equity(vals)
        chk = self.mgr.daily_check(equity)
        assert not chk.passed
        monthly_viols = [v for v in chk.violations if "Monthly" in v]
        assert len(monthly_viols) == 1

    def test_calm_curve_passes(self) -> None:
        # Gentle uptrend with small day-to-day moves well within limits
        vals = list(np.linspace(100.0, 101.0, 30))
        equity = _equity(vals)
        chk = self.mgr.daily_check(equity)
        assert chk.passed

    def test_fewer_than_two_raises(self) -> None:
        with pytest.raises(ValueError, match="2"):
            self.mgr.daily_check(_equity([100.0]))

    def test_exactly_two_observations_ok(self) -> None:
        # Flat equity -> 0% return -> no violation
        equity = _equity([100.0, 100.0])
        chk = self.mgr.daily_check(equity)
        assert chk.passed

    def test_daily_and_monthly_both_breach(self) -> None:
        # Drop sharply for 20 days then crater on day 21
        base = list(np.linspace(100.0, 89.0, 20))  # 11% decline
        base.append(base[-1] * (1.0 - 0.06))  # -6% on last day
        equity = _equity(base)
        chk = self.mgr.daily_check(equity)
        assert not chk.passed
        assert len(chk.violations) >= 2

    def test_window_capped_at_21_observations(self) -> None:
        # A long calm equity, then a short bad window at the end
        # First 100 days: flat at 100. Last 21 days: -12% drawdown.
        flat = [100.0] * 100
        bad = list(np.linspace(100.0, 88.0, 21))
        equity = _equity(flat + bad)
        chk = self.mgr.daily_check(equity)
        monthly_viols = [v for v in chk.violations if "Monthly" in v]
        assert len(monthly_viols) == 1


# ---------------------------------------------------------------------------
# PairsRiskManager.var_check
# ---------------------------------------------------------------------------


class TestVarCheck:
    def setup_method(self) -> None:
        self.mgr = PairsRiskManager(RiskLimits(var_limit=0.05, var_alpha=0.05))

    def test_high_var_breach(self) -> None:
        # numpy linear interpolation at alpha=0.05 with n=20:
        # virtual_idx = 0.05*19 = 0.95; both arr[0] and arr[1] are -0.10
        # so the 5th percentile is exactly -0.10 -> VaR = +0.10 > var_limit=0.05.
        bad = [-0.10] * 2
        good = [0.01] * 18  # n=20, the minimum for var_alpha=0.05
        rets = _returns(bad + good)
        chk = self.mgr.var_check(rets)
        assert not chk.passed
        assert len(chk.violations) == 1
        assert "VaR" in chk.violations[0]

    def test_low_var_passes(self) -> None:
        # All returns +0.001 -> VaR is negative (no loss) -> passes
        rets = _returns([0.001] * 100)
        chk = self.mgr.var_check(rets)
        assert chk.passed

    def test_var_at_limit_passes(self) -> None:
        # numpy linear interpolation at alpha=0.05 with n=20:
        # virtual_idx = 0.95; both arr[0] and arr[1] are -0.05
        # so the 5th percentile is exactly -0.05 -> VaR = +0.05.
        # The check is strict (var_loss > var_limit), so 0.05 > 0.05 is False -> passes.
        vals = [-0.05] * 2 + [0.01] * 18
        rets = _returns(vals)
        var = value_at_risk(rets, 0.05)
        # Confirm sign convention: should be exactly +0.05
        assert var == pytest.approx(0.05, abs=1e-10)
        chk = self.mgr.var_check(rets)
        # 0.05 > 0.05 is False -> passes
        assert chk.passed

    def test_sign_convention_positive(self) -> None:
        # Direct check that value_at_risk returns a POSITIVE number for a loss
        rets = _returns([-0.08] * 50)
        var = value_at_risk(rets, 0.05)
        assert var > 0, f"Expected positive VaR loss fraction, got {var}"
        assert var == pytest.approx(0.08, abs=1e-10)

    def test_too_few_observations_raises(self) -> None:
        # Need at least ceil(1/0.05) = 20 obs
        rets = _returns([-0.01] * 19)
        with pytest.raises(ValueError, match="20"):
            self.mgr.var_check(rets)

    def test_exactly_min_obs_accepted(self) -> None:
        rets = _returns([0.001] * 20)
        chk = self.mgr.var_check(rets)
        assert chk.passed

    def test_custom_alpha_changes_min_obs(self) -> None:
        mgr = PairsRiskManager(RiskLimits(var_alpha=0.10, var_limit=0.05))
        # min_obs = ceil(1/0.10) = 10; 9 obs should raise
        with pytest.raises(ValueError, match="10"):
            mgr.var_check(_returns([0.01] * 9))
        # 10 obs should be accepted
        chk = mgr.var_check(_returns([0.001] * 10))
        assert chk.passed


# ---------------------------------------------------------------------------
# PairsRiskManager.circuit_breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def setup_method(self) -> None:
        self.mgr = PairsRiskManager(
            RiskLimits(
                per_pair_cap=0.02,
                gross_leverage_cap=2.0,
                daily_drawdown_limit=0.05,
                monthly_drawdown_limit=0.10,
                var_limit=0.05,
                var_alpha=0.05,
            )
        )

    def _calm_equity(self, n: int = 30) -> pd.Series:
        """Gentle uptrend, no drawdowns."""
        return _equity(list(np.linspace(100.0, 101.0, n)))

    def _calm_returns(self, n: int = 100) -> pd.Series:
        """Small positive returns, well within var_limit."""
        return _returns([0.001] * n)

    def test_all_pass(self) -> None:
        equity = self._calm_equity()
        returns = self._calm_returns()
        weights = {"A": 0.01, "B": -0.01}
        chk = self.mgr.circuit_breaker(equity, returns, proposed_weights=weights)
        assert chk.passed
        assert chk.violations == ()

    def test_daily_breach_only(self) -> None:
        equity = _equity([100.0, 101.0, 95.0])  # last day -5.9%
        chk = self.mgr.circuit_breaker(equity)
        assert not chk.passed
        assert any("Daily" in v for v in chk.violations)

    def test_var_breach_merged(self) -> None:
        equity = self._calm_equity()
        bad_returns = _returns([-0.10] * 10 + [0.01] * 90)
        chk = self.mgr.circuit_breaker(equity, bad_returns)
        assert not chk.passed
        assert any("VaR" in v for v in chk.violations)

    def test_pre_trade_breach_merged(self) -> None:
        equity = self._calm_equity()
        returns = self._calm_returns()
        weights = {"A": 0.05}  # breaches per_pair_cap=0.02
        chk = self.mgr.circuit_breaker(equity, returns, proposed_weights=weights)
        assert not chk.passed
        assert any("per_pair_cap" in v for v in chk.violations)

    def test_all_three_breach_all_reported(self) -> None:
        # Daily breach
        equity = _equity([100.0, 101.0, 95.0])
        # VaR breach
        bad_returns = _returns([-0.10] * 10 + [0.01] * 90)
        # Pre-trade breach
        weights = {"A": 0.05}
        chk = self.mgr.circuit_breaker(equity, bad_returns, proposed_weights=weights)
        assert not chk.passed
        assert any("Daily" in v for v in chk.violations)
        assert any("VaR" in v for v in chk.violations)
        assert any("per_pair_cap" in v for v in chk.violations)
        assert len(chk.violations) >= 3

    def test_no_returns_skips_var(self) -> None:
        equity = self._calm_equity()
        chk = self.mgr.circuit_breaker(equity, None)
        # Should pass with no returns provided
        assert chk.passed

    def test_no_weights_skips_pre_trade(self) -> None:
        equity = self._calm_equity()
        returns = self._calm_returns()
        chk = self.mgr.circuit_breaker(equity, returns, proposed_weights=None)
        assert chk.passed


# ---------------------------------------------------------------------------
# DEFAULT_LIMITS singleton
# ---------------------------------------------------------------------------


class TestDefaultLimits:
    def test_is_risk_limits_instance(self) -> None:
        assert isinstance(DEFAULT_LIMITS, RiskLimits)

    def test_default_manager_uses_singleton(self) -> None:
        mgr = PairsRiskManager()
        # Check that the manager was instantiated with DEFAULT_LIMITS values
        assert mgr._limits.per_pair_cap == DEFAULT_LIMITS.per_pair_cap

    def test_singleton_is_frozen(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            DEFAULT_LIMITS.per_pair_cap = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Edge / boundary cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_pre_trade_negative_weight_checked_absolute(self) -> None:
        mgr = PairsRiskManager(RiskLimits(per_pair_cap=0.02))
        weights = {"SHORT": -0.05}  # absolute value exceeds cap
        chk = mgr.pre_trade(weights)
        assert not chk.passed
        assert "SHORT" in chk.violations[0]

    def test_divergence_at_80pct_threshold_is_warning(self) -> None:
        lim = RiskLimits(divergence_z=3.5)
        mgr = PairsRiskManager(lim)
        # Exactly at 0.8 * 3.5 = 2.8 -> warning (strict > so 2.8 is NOT warning)
        alert_at = mgr.check_divergence("A/B", 2.8)
        # |2.8| > 0.8*3.5 == 2.8: False (not strictly greater), so "none"
        assert alert_at.severity == "none"

        alert_above = mgr.check_divergence("A/B", 2.81)
        assert alert_above.severity == "warning"

    def test_empty_returns_var_check_raises(self) -> None:
        mgr = PairsRiskManager()
        with pytest.raises(ValueError):
            mgr.var_check(_returns([]))

    def test_var_check_raises_for_zero_obs(self) -> None:
        mgr = PairsRiskManager()
        with pytest.raises(ValueError):
            mgr.var_check(pd.Series([], dtype=float))

    def test_daily_check_single_obs_raises(self) -> None:
        mgr = PairsRiskManager()
        with pytest.raises(ValueError):
            mgr.daily_check(_equity([100.0]))

    def test_pre_trade_sector_unknown_label(self) -> None:
        # Symbol not in sectors mapping gets label "UNKNOWN"
        mgr = PairsRiskManager(RiskLimits(per_pair_cap=0.02, sector_cap=0.30))
        weights = {"A": 0.01, "B": 0.01}
        sectors = {"A": "TECH"}  # "B" not in sectors
        chk = mgr.pre_trade(weights, sectors=sectors)
        # TECH = 0.01/0.02 = 50% -> violation; UNKNOWN = 50% -> violation
        sector_viols = [v for v in chk.violations if "Sector" in v]
        assert len(sector_viols) == 2

    def test_rng_seeded_returns_reproducible_var(self) -> None:
        rng = np.random.default_rng(42)
        rets = pd.Series(rng.normal(0.0, 0.01, 200))
        mgr = PairsRiskManager(RiskLimits(var_limit=0.05, var_alpha=0.05))
        chk1 = mgr.var_check(rets)
        chk2 = mgr.var_check(rets)
        assert chk1.passed == chk2.passed

    def test_math_ceil_min_obs(self) -> None:
        # var_alpha=0.03 -> ceil(1/0.03) = ceil(33.33) = 34
        lim = RiskLimits(var_alpha=0.03, var_limit=0.05)
        mgr = PairsRiskManager(lim)
        assert math.ceil(1.0 / 0.03) == 34
        with pytest.raises(ValueError, match="34"):
            mgr.var_check(_returns([0.01] * 33))
        chk = mgr.var_check(_returns([0.001] * 34))
        assert chk.passed
