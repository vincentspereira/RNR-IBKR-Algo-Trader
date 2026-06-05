"""Tests for core_trading.risk.position_risk (Phase 7, module 7.2).

Covers:
* wilder_atr: hand-computed 3-bar example; matches Wilder seed formula.
* absolute_stop: long/short exact values; distance_pct; validation.
* atr_stop: long/short exact values; validation.
* volatility_stop: exact values with horizon scaling; validation.
* check_stop_hit: long/short hit/no-hit; first-bar hit; boundary.
* trailing_stop (pct): monotone-up-then-down path: analytically known hit bar.
* trailing_stop (pct): short mirror case.
* trailing_stop (atr): basic functionality; NaN forward-fill; no-hit case.
* component_var: Euler sum to portfolio_var to 1e-12; 2-asset hand example;
  marginal VaR matches finite-difference numerics; zero-variance; assets label.
* bsm_greeks: put-call parity on delta (delta_c - delta_p == exp(-qT));
  gamma/vega call == put; theta spot-check near Hull textbook value;
  finite-difference delta/gamma/vega/theta/rho vs analytic.
* position_greeks: scaled by quantity*multiplier; short = negated.
* build_snapshot: full round-trip with all components; partial (no VaR/greeks).
* Input validation throughout.
* Performance: full stack completes in < 2s.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest
import scipy.stats as _st

from core_trading.risk.position_risk import (
    absolute_stop,
    atr_stop,
    bsm_greeks,
    build_snapshot,
    check_stop_hit,
    component_var,
    position_greeks,
    trailing_stop,
    volatility_stop,
    wilder_atr,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bsm_price(S, K, T, r, sigma, q=0.0, opt="call"):
    """Standalone BSM price for finite-difference verification."""
    sq = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sq)
    d2 = d1 - sigma * sq
    N = _st.norm.cdf
    if opt == "call":
        return S * math.exp(-q * T) * N(d1) - K * math.exp(-r * T) * N(d2)
    return K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)


# ---------------------------------------------------------------------------
# wilder_atr
# ---------------------------------------------------------------------------


class TestWilderATR:
    def test_seed_value_matches_simple_mean(self) -> None:
        """ATR[period] == mean(TR[1..period]) by definition."""
        # 5 bars: bar 0 is the previous close; bars 1-4 are the window.
        # Use high=low=close so TR_t = |close_t - close_{t-1}|.
        close = np.array([10.0, 11.0, 9.0, 12.0, 10.5, 11.5], dtype=float)
        high = close.copy()
        low = close.copy()
        period = 4
        atr = wilder_atr(high, low, close, period=period)
        # TR values (index 1 onward): |11-10|=1, |9-11|=2, |12-9|=3, |10.5-12|=1.5
        expected_tr = np.array([1.0, 2.0, 3.0, 1.5])
        expected_seed = float(np.mean(expected_tr))
        assert math.isnan(atr[0])
        assert all(math.isnan(atr[i]) for i in range(1, period))
        assert atr[period] == pytest.approx(expected_seed, rel=1e-12)

    def test_wilder_recursion(self) -> None:
        """ATR[t] = ATR[t-1]*(1-alpha) + TR[t]*alpha after seed."""
        close = np.array([10.0, 11.0, 9.0, 12.0, 10.5, 11.5, 13.0], dtype=float)
        high = close.copy()
        low = close.copy()
        period = 3
        atr = wilder_atr(high, low, close, period=period)
        alpha = 1.0 / period
        # TR[1..3] = 1, 2, 3  -> seed = 2.0
        seed = 2.0
        # TR[4] = |10.5 - 12| = 1.5
        expected_t4 = seed * (1 - alpha) + 1.5 * alpha
        # TR[5] = |11.5 - 10.5| = 1.0
        expected_t5 = expected_t4 * (1 - alpha) + 1.0 * alpha
        # TR[6] = |13 - 11.5| = 1.5
        expected_t6 = expected_t5 * (1 - alpha) + 1.5 * alpha
        assert atr[period] == pytest.approx(seed, rel=1e-12)
        assert atr[4] == pytest.approx(expected_t4, rel=1e-12)
        assert atr[5] == pytest.approx(expected_t5, rel=1e-12)
        assert atr[6] == pytest.approx(expected_t6, rel=1e-12)

    def test_true_range_uses_previous_close(self) -> None:
        """TR uses |High - prev_close| and |Low - prev_close|, not just H-L."""
        # Gap scenario: previous close 100, next bar gaps up to 110-112.
        high = np.array([100.0, 112.0, 112.0], dtype=float)
        low = np.array([100.0, 110.0, 110.0], dtype=float)
        close = np.array([100.0, 111.0, 111.0], dtype=float)
        atr = wilder_atr(high, low, close, period=2)
        # TR[1] = max(112-110, |112-100|, |110-100|) = max(2, 12, 10) = 12
        # TR[2] = max(112-110, |112-111|, |110-111|) = max(2, 1, 1) = 2
        # seed (period=2) = mean(TR[1..2]) = mean(12, 2) = 7
        assert atr[2] == pytest.approx(7.0, rel=1e-12)

    def test_pandas_series_input(self) -> None:
        import pandas as pd
        close = pd.Series([10.0, 11.0, 9.0, 12.0, 10.5, 11.5])
        high = close.copy()
        low = close.copy()
        result = wilder_atr(high, low, close, period=3)
        assert isinstance(result, np.ndarray)
        assert result.shape == (6,)

    def test_validation_period_too_small(self) -> None:
        h = np.ones(5)
        with pytest.raises(ValueError, match="period"):
            wilder_atr(h, h, h, period=1)

    def test_validation_too_few_bars(self) -> None:
        h = np.ones(3)
        with pytest.raises(ValueError, match="period"):
            wilder_atr(h, h, h, period=3)

    def test_validation_mismatched_lengths(self) -> None:
        h = np.ones(6)
        lo = np.ones(5)
        c = np.ones(6)
        with pytest.raises(ValueError, match="length"):
            wilder_atr(h, lo, c)


# ---------------------------------------------------------------------------
# absolute_stop
# ---------------------------------------------------------------------------


class TestAbsoluteStop:
    def test_long_exact(self) -> None:
        sl = absolute_stop(entry=100.0, pct=0.05)
        assert sl.stop == pytest.approx(95.0)
        assert sl.distance_pct == pytest.approx(0.05)
        assert sl.method == "absolute"
        assert sl.direction == "long"

    def test_short_exact(self) -> None:
        sl = absolute_stop(entry=100.0, pct=0.03, direction="short")
        assert sl.stop == pytest.approx(103.0)
        assert sl.distance_pct == pytest.approx(0.03)
        assert sl.direction == "short"

    def test_distance_pct_equals_pct_input(self) -> None:
        for p in (0.01, 0.05, 0.10, 0.20):
            sl_long = absolute_stop(entry=50.0, pct=p, direction="long")
            sl_short = absolute_stop(entry=50.0, pct=p, direction="short")
            assert sl_long.distance_pct == pytest.approx(p, rel=1e-12)
            assert sl_short.distance_pct == pytest.approx(p, rel=1e-12)

    def test_frozen_dataclass(self) -> None:
        from dataclasses import FrozenInstanceError
        sl = absolute_stop(100.0, 0.02)
        with pytest.raises(FrozenInstanceError):
            sl.stop = 0.0  # type: ignore[misc]

    def test_validation_entry_zero(self) -> None:
        with pytest.raises(ValueError, match="entry"):
            absolute_stop(0.0, 0.05)

    def test_validation_pct_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="pct"):
            absolute_stop(100.0, 1.1)
        with pytest.raises(ValueError, match="pct"):
            absolute_stop(100.0, 0.0)

    def test_validation_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            absolute_stop(100.0, 0.05, direction="flat")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# atr_stop
# ---------------------------------------------------------------------------


class TestATRStop:
    def test_long_exact(self) -> None:
        sl = atr_stop(entry=100.0, atr_value=2.0, multiplier=3.0)
        assert sl.stop == pytest.approx(94.0)   # 100 - 3*2 = 94
        assert sl.distance_pct == pytest.approx(0.06)
        assert sl.method == "atr"

    def test_short_exact(self) -> None:
        sl = atr_stop(entry=50.0, atr_value=1.0, multiplier=2.5, direction="short")
        assert sl.stop == pytest.approx(52.5)   # 50 + 2.5*1 = 52.5

    def test_validation_negative_atr(self) -> None:
        with pytest.raises(ValueError, match="atr_value"):
            atr_stop(100.0, -1.0)

    def test_validation_zero_multiplier(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            atr_stop(100.0, 1.0, multiplier=0.0)


# ---------------------------------------------------------------------------
# volatility_stop
# ---------------------------------------------------------------------------


class TestVolatilityStop:
    def test_long_exact_h1(self) -> None:
        # offset = 2 * 0.01 * sqrt(1) * 100 = 2.0
        sl = volatility_stop(entry=100.0, sigma=0.01, multiplier=2.0)
        assert sl.stop == pytest.approx(98.0)
        assert sl.distance_pct == pytest.approx(0.02, rel=1e-12)

    def test_long_exact_h10(self) -> None:
        # offset = 2 * 0.01 * sqrt(10) * 100
        expected = 100.0 - 2.0 * 0.01 * math.sqrt(10) * 100.0
        sl = volatility_stop(entry=100.0, sigma=0.01, multiplier=2.0, horizon=10)
        assert sl.stop == pytest.approx(expected, rel=1e-12)

    def test_short_exact(self) -> None:
        # offset = 1 * 0.02 * sqrt(1) * 200 = 4.0
        sl = volatility_stop(entry=200.0, sigma=0.02, multiplier=1.0, direction="short")
        assert sl.stop == pytest.approx(204.0)

    def test_validation_bad_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            volatility_stop(100.0, 0.01, horizon=0)

    def test_validation_bad_sigma(self) -> None:
        with pytest.raises(ValueError, match="sigma"):
            volatility_stop(100.0, -0.01)


# ---------------------------------------------------------------------------
# check_stop_hit
# ---------------------------------------------------------------------------


class TestCheckStopHit:
    def test_long_not_hit(self) -> None:
        sl = absolute_stop(100.0, 0.10)  # stop at 90
        prices = np.array([100.0, 101.0, 99.0, 95.0, 92.0])
        result = check_stop_hit(prices, sl)
        assert not result.hit
        assert result.hit_index is None

    def test_long_hit_index_correct(self) -> None:
        sl = absolute_stop(100.0, 0.10)  # stop at 90
        prices = np.array([100.0, 95.0, 88.0, 75.0])
        result = check_stop_hit(prices, sl)
        assert result.hit
        assert result.hit_index == 2   # first at or below 90

    def test_long_hit_at_exactly_stop(self) -> None:
        sl = absolute_stop(100.0, 0.10)  # stop at 90
        prices = np.array([100.0, 95.0, 90.0, 95.0])
        result = check_stop_hit(prices, sl)
        assert result.hit
        assert result.hit_index == 2

    def test_short_hit_index_correct(self) -> None:
        sl = absolute_stop(100.0, 0.05, direction="short")  # stop at 105
        prices = np.array([100.0, 102.0, 106.0, 104.0])
        result = check_stop_hit(prices, sl)
        assert result.hit
        assert result.hit_index == 2

    def test_short_not_hit(self) -> None:
        sl = absolute_stop(100.0, 0.05, direction="short")  # stop at 105
        prices = np.array([100.0, 102.0, 103.0, 104.9])
        result = check_stop_hit(prices, sl)
        assert not result.hit

    def test_first_bar_hit(self) -> None:
        sl = absolute_stop(100.0, 0.10)  # stop at 90
        prices = np.array([85.0, 95.0])
        result = check_stop_hit(prices, sl)
        assert result.hit
        assert result.hit_index == 0

    def test_empty_prices_raises(self) -> None:
        sl = absolute_stop(100.0, 0.05)
        with pytest.raises(ValueError, match="non-empty"):
            check_stop_hit(np.array([]), sl)


# ---------------------------------------------------------------------------
# trailing_stop
# ---------------------------------------------------------------------------


class TestTrailingStopPct:
    def test_monotone_up_then_down_long_analytically_known_hit(self) -> None:
        """Analytically compute the hit bar.

        Price goes: 100, 102, 105, 108, 105, 100, 95, 90.
        5% trailing stop.  HWM after bar 3 = 108; stop = 108*0.95 = 102.6.
        Bar 4: price=105 > 102.6 -> no hit.
        Bar 5: price=100 < 102.6 -> HIT at bar 5.
        """
        prices = np.array([100.0, 102.0, 105.0, 108.0, 105.0, 100.0, 95.0, 90.0])
        result = trailing_stop(prices, pct=0.05)
        assert result.direction == "long"
        assert result.method == "pct"
        assert result.hit
        # After bars 0-3 the HWM climbs to 108; stop rises to 102.6.
        # Bar 4 price 105 is above stop 102.6 (hwm still 108 since 105 < 108).
        # Bar 5 price 100 is below 102.6 -> first breach.
        assert result.hit_index == 5

    def test_initial_stop_correct(self) -> None:
        prices = np.array([100.0, 105.0, 110.0])
        result = trailing_stop(prices, pct=0.10)
        assert result.initial_stop == pytest.approx(90.0)

    def test_stop_path_never_decreases_long(self) -> None:
        rng = np.random.default_rng(42)
        prices = 100.0 + np.cumsum(rng.standard_normal(50))
        result = trailing_stop(prices, pct=0.05)
        diffs = np.diff(result.stop_path)
        assert np.all(diffs >= -1e-14), "long stop must never decrease"

    def test_no_hit_returns_none_index(self) -> None:
        # Prices only go up
        prices = np.linspace(100, 200, 50)
        result = trailing_stop(prices, pct=0.50)  # 50% - very loose
        assert not result.hit
        assert result.hit_index is None

    def test_short_mirror_monotone_down_then_up(self) -> None:
        """Short trailing stop mirror case.

        Price: 100, 98, 95, 92, 95, 100, 105.
        5% short trailing: stop = lwm * 1.05.
        LWM after bar 3 = 92; stop = 92*1.05 = 96.6.
        Bar 4: price=95 < 96.6 -> no hit (stop at min of prev and new).
        Bar 5: price=100 >= 96.6 -> HIT.
        """
        prices = np.array([100.0, 98.0, 95.0, 92.0, 95.0, 100.0, 105.0])
        result = trailing_stop(prices, direction="short", pct=0.05)
        assert result.hit
        assert result.hit_index == 5

    def test_stop_path_never_increases_short(self) -> None:
        rng = np.random.default_rng(7)
        prices = 100.0 + np.cumsum(rng.standard_normal(50))
        result = trailing_stop(prices, direction="short", pct=0.05)
        diffs = np.diff(result.stop_path)
        assert np.all(diffs <= 1e-14), "short stop must never increase"

    def test_validation_both_modes_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            trailing_stop(np.ones(5), pct=0.05, atr_values=np.ones(5))

    def test_validation_neither_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            trailing_stop(np.ones(5))

    def test_validation_empty_prices(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            trailing_stop(np.array([]), pct=0.05)


class TestTrailingStopATR:
    def test_basic_atr_mode_long(self) -> None:
        prices = np.array([100.0, 102.0, 105.0, 108.0, 105.0, 100.0])
        # Constant ATR = 2.0, multiplier = 2.0 -> distance = 4.0
        atr = np.full(6, 2.0)
        result = trailing_stop(prices, atr_values=atr, atr_multiplier=2.0)
        assert result.method == "atr"
        # initial stop = 100 - 2*2 = 96
        assert result.initial_stop == pytest.approx(96.0)

    def test_nan_atr_forward_filled(self) -> None:
        prices = np.array([100.0, 102.0, 104.0, 102.0, 100.0, 98.0])
        # First 3 ATR values are NaN (no valid history yet); rest = 2.0
        atr = np.array([float("nan"), float("nan"), float("nan"), 2.0, 2.0, 2.0])
        result = trailing_stop(prices, atr_values=atr, atr_multiplier=1.0)
        # Bars 0-2: forward-fill gives ATR=0.0.  HWM rises to 104; stop = hwm - 0 = hwm.
        # stop[0]=100, stop[1]=102, stop[2]=104.
        assert result.stop_path[0] == pytest.approx(100.0)
        assert result.stop_path[2] == pytest.approx(104.0)
        # Bar 3: ATR=2.0 becomes available; new_stop = hwm(=104) - 2 = 102.
        # But stop never decreases -> stop[3] = max(stop[2]=104, 102) = 104.
        assert result.stop_path[3] == pytest.approx(104.0)

    def test_atr_no_hit(self) -> None:
        prices = np.linspace(100, 150, 20)
        atr = np.full(20, 1.0)
        result = trailing_stop(prices, atr_values=atr, atr_multiplier=1.0)
        # Stop rises with the trend; prices always above stop
        assert not result.hit

    def test_atr_length_mismatch(self) -> None:
        prices = np.ones(5)
        atr = np.ones(4)
        with pytest.raises(ValueError, match="length"):
            trailing_stop(prices, atr_values=atr)

    def test_atr_negative_multiplier(self) -> None:
        prices = np.ones(5)
        atr = np.ones(5)
        with pytest.raises(ValueError, match="atr_multiplier"):
            trailing_stop(prices, atr_values=atr, atr_multiplier=-1.0)


# ---------------------------------------------------------------------------
# component_var
# ---------------------------------------------------------------------------


class TestComponentVar:
    def _two_asset_hand(self):
        """2-asset example with known analytic solution.

        w = [0.6, 0.4], Sigma = [[0.04, 0.012], [0.012, 0.09]]
        sigma_p^2 = 0.6^2*0.04 + 2*0.6*0.4*0.012 + 0.4^2*0.09
                  = 0.0144 + 0.00576 + 0.0144 = 0.0345(6)
        sigma_p   = sqrt(0.034560) ~ 0.18591...
        At 95%: z = 1.644853...
        VaR_p = z * sigma_p
        (Sigma @ w)[0] = 0.04*0.6 + 0.012*0.4 = 0.024+0.0048 = 0.0288
        (Sigma @ w)[1] = 0.012*0.6 + 0.09*0.4 = 0.0072+0.036 = 0.0432
        mVaR_0 = z * 0.0288 / sigma_p
        mVaR_1 = z * 0.0432 / sigma_p
        CVaR_0 = 0.6 * mVaR_0
        CVaR_1 = 0.4 * mVaR_1
        """
        import scipy.stats as stats
        w = np.array([0.6, 0.4])
        cov = np.array([[0.04, 0.012], [0.012, 0.09]])
        sig2 = float(w @ cov @ w)
        sig = math.sqrt(sig2)
        z = float(stats.norm.ppf(0.95))
        port_var = z * sig
        cov_iw = cov @ w
        mvars = z * cov_iw / sig
        cvars = w * mvars
        return w, cov, port_var, mvars, cvars

    def test_euler_sum_to_portfolio_var(self) -> None:
        w, cov, port_var, _, _ = self._two_asset_hand()
        result = component_var(w, cov)
        assert abs(np.sum(result.component_var) - result.portfolio_var) < 1e-12

    def test_two_asset_hand_computed(self) -> None:
        w, cov, port_var, mvars, cvars = self._two_asset_hand()
        result = component_var(w, cov, confidence=0.95)
        assert result.portfolio_var == pytest.approx(port_var, rel=1e-10)
        assert result.marginal_var[0] == pytest.approx(mvars[0], rel=1e-10)
        assert result.marginal_var[1] == pytest.approx(mvars[1], rel=1e-10)
        assert result.component_var[0] == pytest.approx(cvars[0], rel=1e-10)
        assert result.component_var[1] == pytest.approx(cvars[1], rel=1e-10)

    def test_euler_sum_large_portfolio(self) -> None:
        rng = np.random.default_rng(1)
        n = 10
        a = rng.standard_normal((100, n))
        cov = (a.T @ a) / 100.0
        w = rng.dirichlet(np.ones(n))
        result = component_var(w, cov)
        assert abs(np.sum(result.component_var) - result.portfolio_var) < 1e-12

    def test_marginal_var_matches_finite_difference(self) -> None:
        """mVaR_i should equal finite-difference dVaR/dw_i."""
        import scipy.stats as stats
        rng = np.random.default_rng(99)
        n = 4
        a = rng.standard_normal((50, n))
        cov = (a.T @ a) / 50.0
        w = rng.dirichlet(np.ones(n))
        confidence = 0.95
        z = float(stats.norm.ppf(confidence))
        h = 1e-6
        result = component_var(w, cov, confidence=confidence)
        for i in range(n):
            wp = w.copy()
            wp[i] += h
            wm = w.copy()
            wm[i] -= h
            var_p = z * math.sqrt(float(wp @ cov @ wp))
            var_m = z * math.sqrt(float(wm @ cov @ wm))
            fd = (var_p - var_m) / (2 * h)
            assert result.marginal_var[i] == pytest.approx(fd, rel=1e-4)

    def test_zero_variance_portfolio(self) -> None:
        """w = 0 -> portfolio_var = 0, all component/marginal VaR = 0."""
        w = np.zeros(3)
        cov = np.eye(3) * 0.01
        result = component_var(w, cov)
        assert result.portfolio_var == 0.0
        assert np.all(result.component_var == 0.0)
        assert np.all(result.marginal_var == 0.0)

    def test_assets_labels_applied(self) -> None:
        w = np.array([0.5, 0.5])
        cov = np.eye(2) * 0.01
        result = component_var(w, cov, assets=["SPY", "TLT"])
        assert result.assets == ["SPY", "TLT"]

    def test_default_asset_labels(self) -> None:
        w = np.array([0.4, 0.6])
        cov = np.eye(2) * 0.01
        result = component_var(w, cov)
        assert result.assets == ["A0", "A1"]

    def test_validation_bad_confidence(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            component_var(np.ones(2), np.eye(2), confidence=1.5)

    def test_validation_shape_mismatch(self) -> None:
        with pytest.raises(ValueError, match="shape"):
            component_var(np.ones(3), np.eye(2))

    def test_validation_non_psd_covariance(self) -> None:
        # [[1,2],[2,1]] is indefinite (eigenvalues 3 and -1).
        # With w=[1,-1]: w'Cw = 1 - 2*2 + 1 = -2 < -1e-12 -> should raise.
        bad_cov = np.array([[1.0, 2.0], [2.0, 1.0]])
        with pytest.raises(ValueError):
            component_var(np.array([1.0, -1.0]), bad_cov)

    def test_validation_assets_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="assets"):
            component_var(np.ones(2), np.eye(2), assets=["A", "B", "C"])

    def test_result_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        result = component_var(np.array([0.5, 0.5]), np.eye(2) * 0.01)
        with pytest.raises(FrozenInstanceError):
            result.portfolio_var = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# bsm_greeks
# ---------------------------------------------------------------------------


class TestBSMGreeks:
    """Standard params: S=100, K=100, T=0.25, r=0.05, sigma=0.20, q=0."""

    _S = 100.0
    _K = 100.0
    _T = 0.25
    _r = 0.05
    _sigma = 0.20
    _q = 0.0

    def _call(self, **kw):
        p = dict(S=self._S, K=self._K, T=self._T, r=self._r, sigma=self._sigma, q=self._q)
        p.update(kw)
        return bsm_greeks(**p, option_type="call")

    def _put(self, **kw):
        p = dict(S=self._S, K=self._K, T=self._T, r=self._r, sigma=self._sigma, q=self._q)
        p.update(kw)
        return bsm_greeks(**p, option_type="put")

    # Put-call parity on delta: delta_call - delta_put = exp(-q*T)
    def test_put_call_parity_delta(self) -> None:
        c = self._call()
        p = self._put()
        expected = math.exp(-self._q * self._T)
        assert c.delta - p.delta == pytest.approx(expected, rel=1e-10)

    def test_put_call_parity_delta_with_dividend(self) -> None:
        q = 0.03
        c = self._call(q=q)
        p = self._put(q=q)
        expected = math.exp(-q * self._T)
        assert c.delta - p.delta == pytest.approx(expected, rel=1e-10)

    # gamma and vega identical for call and put
    def test_gamma_same_call_put(self) -> None:
        assert self._call().gamma == pytest.approx(self._put().gamma, rel=1e-12)

    def test_vega_same_call_put(self) -> None:
        assert self._call().vega == pytest.approx(self._put().vega, rel=1e-12)

    # Put-call parity on price: C - P = S*exp(-qT) - K*exp(-rT)
    def test_put_call_price_parity(self) -> None:
        c = self._call()
        p = self._put()
        lhs = c.option_price - p.option_price
        rhs = self._S * math.exp(-self._q * self._T) - self._K * math.exp(-self._r * self._T)
        assert lhs == pytest.approx(rhs, rel=1e-8)

    def test_call_delta_bounds(self) -> None:
        c = self._call()
        assert 0 < c.delta < 1

    def test_put_delta_bounds(self) -> None:
        p = self._put()
        assert -1 < p.delta < 0

    def test_gamma_non_negative(self) -> None:
        assert self._call().gamma >= 0.0
        assert self._put().gamma >= 0.0

    def test_theta_negative_atm_call(self) -> None:
        assert self._call().theta < 0.0

    def test_theta_negative_atm_put(self) -> None:
        assert self._put().theta < 0.0

    # Hull textbook theta spot-check.
    # Hull 11e, Example 19.3: S=49, K=50, T=0.3846yr, r=5%, sigma=20%, q=0.
    # theta_annual ~ -4.31 (Hull rounds to -4.31 $/year).
    # Per calendar day: -4.31 / 365 ~ -0.01181.
    # We verify our implementation is within 1% of the hand-computed value.
    def test_theta_hull_spot_check(self) -> None:
        c = bsm_greeks(S=49.0, K=50.0, T=0.3846, r=0.05, sigma=0.20, option_type="call")
        # Annual theta ~ -4.305; per day ~ -0.01179
        assert c.theta == pytest.approx(-4.305 / 365.0, rel=0.01)

    # Finite-difference helpers
    def _fd_delta(self, opt="call", h=0.01) -> float:
        up = _bsm_price(self._S + h, self._K, self._T, self._r, self._sigma, self._q, opt)
        dn = _bsm_price(self._S - h, self._K, self._T, self._r, self._sigma, self._q, opt)
        return (up - dn) / (2 * h)

    def _fd_gamma(self, opt="call", h=0.01) -> float:
        S = self._S
        up = _bsm_price(S + h, self._K, self._T, self._r, self._sigma, self._q, opt)
        mid = _bsm_price(S, self._K, self._T, self._r, self._sigma, self._q, opt)
        dn = _bsm_price(S - h, self._K, self._T, self._r, self._sigma, self._q, opt)
        return (up - 2 * mid + dn) / (h ** 2)

    def _fd_vega(self, opt="call", h=0.001) -> float:
        up = _bsm_price(self._S, self._K, self._T, self._r, self._sigma + h, self._q, opt)
        dn = _bsm_price(self._S, self._K, self._T, self._r, self._sigma - h, self._q, opt)
        return (up - dn) / (2 * h)

    def _fd_theta(self, opt="call", h=1.0/365.0) -> float:
        mid = _bsm_price(self._S, self._K, self._T, self._r, self._sigma, self._q, opt)
        bwd = _bsm_price(self._S, self._K, self._T - h, self._r, self._sigma, self._q, opt)
        return bwd - mid

    def _fd_rho(self, opt="call", h=1e-4) -> float:
        up = _bsm_price(self._S, self._K, self._T, self._r + h, self._sigma, self._q, opt)
        dn = _bsm_price(self._S, self._K, self._T, self._r - h, self._sigma, self._q, opt)
        return (up - dn) / (2 * h)

    def test_delta_matches_fd_call(self) -> None:
        c = self._call()
        assert c.delta == pytest.approx(self._fd_delta("call"), rel=1e-4)

    def test_delta_matches_fd_put(self) -> None:
        p = self._put()
        assert p.delta == pytest.approx(self._fd_delta("put"), rel=1e-4)

    def test_gamma_matches_fd(self) -> None:
        c = self._call()
        assert c.gamma == pytest.approx(self._fd_gamma("call"), rel=1e-3)

    def test_vega_matches_fd(self) -> None:
        c = self._call()
        assert c.vega == pytest.approx(self._fd_vega("call"), rel=1e-4)

    def test_theta_matches_fd(self) -> None:
        c = self._call()
        assert c.theta == pytest.approx(self._fd_theta("call"), rel=2e-2)

    def test_rho_call_matches_fd(self) -> None:
        c = self._call()
        assert c.rho == pytest.approx(self._fd_rho("call"), rel=1e-4)

    def test_rho_put_matches_fd(self) -> None:
        p = self._put()
        assert p.rho == pytest.approx(self._fd_rho("put"), rel=1e-4)

    def test_d2_equals_d1_minus_sigma_sqrt_T(self) -> None:
        c = self._call()
        expected_d2 = c.d1 - self._sigma * math.sqrt(self._T)
        assert c.d2 == pytest.approx(expected_d2, rel=1e-12)

    def test_deep_itm_call_delta_near_one(self) -> None:
        c = bsm_greeks(S=200.0, K=100.0, T=0.25, r=0.05, sigma=0.20)
        assert c.delta == pytest.approx(1.0, abs=0.005)

    def test_validation_negative_S(self) -> None:
        with pytest.raises(ValueError, match="S"):
            bsm_greeks(-1.0, 100.0, 0.25, 0.05, 0.20)

    def test_validation_zero_T(self) -> None:
        with pytest.raises(ValueError, match="T"):
            bsm_greeks(100.0, 100.0, 0.0, 0.05, 0.20)

    def test_validation_bad_option_type(self) -> None:
        with pytest.raises(ValueError, match="option_type"):
            bsm_greeks(100.0, 100.0, 0.25, 0.05, 0.20, option_type="straddle")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# position_greeks
# ---------------------------------------------------------------------------


class TestPositionGreeks:
    def test_long_call_scaled(self) -> None:
        g = bsm_greeks(100.0, 100.0, 0.25, 0.05, 0.20)
        pg = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, quantity=5.0)
        assert pg.position_delta == pytest.approx(5.0 * 100.0 * g.delta, rel=1e-12)
        assert pg.position_gamma == pytest.approx(5.0 * 100.0 * g.gamma, rel=1e-12)
        assert pg.position_vega == pytest.approx(5.0 * 100.0 * g.vega, rel=1e-12)
        assert pg.position_theta == pytest.approx(5.0 * 100.0 * g.theta, rel=1e-12)
        assert pg.position_rho == pytest.approx(5.0 * 100.0 * g.rho, rel=1e-12)
        assert pg.quantity == 5.0
        assert pg.multiplier == 100.0

    def test_short_call_negates_greeks(self) -> None:
        pg_long = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, quantity=1.0)
        pg_short = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, quantity=-1.0)
        assert pg_short.position_delta == pytest.approx(-pg_long.position_delta)
        assert pg_short.position_gamma == pytest.approx(-pg_long.position_gamma)

    def test_custom_multiplier(self) -> None:
        pg = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, quantity=1.0, multiplier=50.0)
        g = bsm_greeks(100.0, 100.0, 0.25, 0.05, 0.20)
        assert pg.position_delta == pytest.approx(50.0 * g.delta, rel=1e-12)

    def test_put_position(self) -> None:
        pg = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, 2.0, option_type="put")
        assert pg.per_contract.option_type == "put"
        assert pg.position_delta < 0   # long put has negative delta

    def test_validation_negative_multiplier(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, 1.0, multiplier=-10.0)


# ---------------------------------------------------------------------------
# build_snapshot
# ---------------------------------------------------------------------------


class TestBuildSnapshot:
    def test_full_round_trip(self) -> None:
        sl_abs = absolute_stop(100.0, 0.05)
        sl_atr = atr_stop(100.0, 1.5, 2.0)
        w = np.array([0.6, 0.4])
        cov = np.array([[0.04, 0.012], [0.012, 0.09]])
        cv_result = component_var(w, cov)
        pg = position_greeks(100.0, 100.0, 0.25, 0.05, 0.20, quantity=10.0)
        snap = build_snapshot(
            asset="AAPL",
            entry=100.0,
            direction="long",
            quantity=100.0,
            stop_levels=[sl_abs, sl_atr],
            component_var_result=cv_result,
            asset_index=0,
            greeks=pg,
        )
        assert snap.asset == "AAPL"
        assert snap.entry == 100.0
        assert snap.direction == "long"
        assert snap.quantity == 100.0
        assert len(snap.stop_levels) == 2
        assert snap.component_var is not None
        assert snap.marginal_var is not None
        assert snap.greeks is not None
        assert snap.component_var == pytest.approx(cv_result.component_var[0])
        assert snap.marginal_var == pytest.approx(cv_result.marginal_var[0])

    def test_no_optional_fields(self) -> None:
        snap = build_snapshot(asset="SPY", entry=450.0, direction="short", quantity=-50.0)
        assert snap.stop_levels == []
        assert snap.component_var is None
        assert snap.marginal_var is None
        assert snap.greeks is None

    def test_component_var_result_without_index_raises(self) -> None:
        cv_result = component_var(np.array([0.5, 0.5]), np.eye(2) * 0.01)
        with pytest.raises(ValueError, match="asset_index"):
            build_snapshot(
                asset="X", entry=10.0, direction="long", quantity=1.0,
                component_var_result=cv_result,
            )

    def test_asset_index_out_of_range_raises(self) -> None:
        cv_result = component_var(np.array([0.5, 0.5]), np.eye(2) * 0.01)
        with pytest.raises(ValueError, match="out of range"):
            build_snapshot(
                asset="X", entry=10.0, direction="long", quantity=1.0,
                component_var_result=cv_result, asset_index=5,
            )

    def test_frozen_snapshot(self) -> None:
        from dataclasses import FrozenInstanceError
        snap = build_snapshot(asset="X", entry=10.0, direction="long", quantity=1.0)
        with pytest.raises(FrozenInstanceError):
            snap.entry = 99.0  # type: ignore[misc]

    def test_stop_levels_list_is_copy(self) -> None:
        sl = absolute_stop(100.0, 0.05)
        stops = [sl]
        snap = build_snapshot(asset="X", entry=100.0, direction="long", quantity=1.0,
                              stop_levels=stops)
        stops.append(atr_stop(100.0, 2.0))  # mutate original
        assert len(snap.stop_levels) == 1   # snapshot unchanged


# ---------------------------------------------------------------------------
# Performance smoke test
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_full_stack_under_2s(self) -> None:
        rng = np.random.default_rng(0)
        n = 5
        a = rng.standard_normal((200, n))
        cov = (a.T @ a) / 200.0
        w = rng.dirichlet(np.ones(n))
        start = time.time()
        for _ in range(500):
            _ = component_var(w, cov)
        for _ in range(500):
            _ = bsm_greeks(100.0, 100.0, 0.25, 0.05, 0.20)
        prices = rng.standard_normal(200).cumsum() + 100.0
        for _ in range(100):
            _ = trailing_stop(prices, pct=0.05)
        h = rng.standard_normal(100).cumsum() + 100.0
        lo = h - 2.0
        c = h - 1.0
        for _ in range(100):
            _ = wilder_atr(h, lo, c, period=14)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Full stack took {elapsed:.2f}s (> 2s limit)"



# ---------------------------------------------------------------------------
# Additional validation coverage for remaining uncovered branches
# ---------------------------------------------------------------------------


class TestAdditionalValidation:
    # line 133: atr_stop entry <= 0
    def test_atr_stop_entry_negative(self) -> None:
        with pytest.raises(ValueError, match="entry"):
            atr_stop(entry=-1.0, atr_value=1.0)

    # line 139: atr_stop direction bad
    def test_atr_stop_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            atr_stop(100.0, 1.0, direction="flat")  # type: ignore[arg-type]

    # line 166: volatility_stop entry <= 0
    def test_vol_stop_entry_negative(self) -> None:
        with pytest.raises(ValueError, match="entry"):
            volatility_stop(entry=0.0, sigma=0.01)

    # line 170: volatility_stop multiplier <= 0
    def test_vol_stop_multiplier_zero(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            volatility_stop(100.0, 0.01, multiplier=0.0)

    # line 174: volatility_stop bad direction
    def test_vol_stop_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            volatility_stop(100.0, 0.01, direction="neutral")  # type: ignore[arg-type]

    # line 322: trailing_stop bad direction
    def test_trailing_stop_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            trailing_stop(np.ones(5), pct=0.05, direction="neutral")  # type: ignore[arg-type]

    # line 326: pct out of range
    def test_trailing_stop_pct_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="pct"):
            trailing_stop(np.ones(5), pct=1.5)

    # lines 414-420: _trailing_stop_atr short branch
    def test_trailing_stop_atr_short(self) -> None:
        # prices=[100,98,95,97,99,102], ATR=1.0 everywhere, mult=1.5
        # short stop is a descending ceiling: stop[t] = min(prev_stop, lwm+mult*ATR)
        # bar0: lwm=100, stop=101.5
        # bar1: lwm=98,  stop=min(101.5,99.5)=99.5
        # bar2: lwm=95,  stop=min(99.5,96.5)=96.5
        # bar3: lwm=95,  stop=min(96.5,96.5)=96.5; price=97>=96.5 -> HIT at index 3
        prices = np.array([100.0, 98.0, 95.0, 97.0, 99.0, 102.0])
        atr = np.full(6, 1.0)
        result = trailing_stop(prices, direction="short", atr_values=atr, atr_multiplier=1.5)
        assert result.method == "atr"
        assert result.direction == "short"
        # initial stop = 100 + 1.5*1.0 = 101.5
        assert result.initial_stop == pytest.approx(101.5)
        # stop should hit when price rises above the descending ceiling
        assert result.hit
        assert result.hit_index == 3  # price=97 >= stop=96.5

    # line 659: bsm_greeks K <= 0
    def test_bsm_greeks_K_zero(self) -> None:
        with pytest.raises(ValueError, match="K"):
            bsm_greeks(100.0, 0.0, 0.25, 0.05, 0.20)

    # line 663: bsm_greeks sigma <= 0
    def test_bsm_greeks_sigma_zero(self) -> None:
        with pytest.raises(ValueError, match="sigma"):
            bsm_greeks(100.0, 100.0, 0.25, 0.05, 0.0)

    # lines 826 / 828: build_snapshot entry/direction validation
    def test_build_snapshot_bad_entry(self) -> None:
        with pytest.raises(ValueError, match="entry"):
            build_snapshot("X", 0.0, "long", 1.0)

    def test_build_snapshot_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            build_snapshot("X", 10.0, "flat", 1.0)  # type: ignore[arg-type]
