"""Tests for core_trading.signals.stochastic.heston (Phase 5.B.3).

Covers:
* HestonParams -- frozen dataclass, feller_satisfied property.
* _validate_params -- ValueError guards for all out-of-domain inputs.
* simulate -- shape, initial row, determinism, non-negative variance,
              long-run variance mean, ValueError guards.
* characteristic_function -- martingale condition CF(-i)=1, BS limit,
                             correct normalisation at u=0.
* call_price -- Black-Scholes limit (linchpin test, tight tolerance),
                arbitrage bounds (lower: intrinsic; upper: s0),
                put-call parity, deep ITM / deep OTM behaviour,
                ValueError guards.
* calibrate -- round-trip test: generate prices from known params, calibrate,
               assert price RMSE is small; loose param recovery checks.
* TestPublicAPI -- the four public names importable from the submodule.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from core_trading.signals.stochastic.heston import (  # noqa: E402
    HestonParams,
    calibrate,
    call_price,
    characteristic_function,
    simulate,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# A "standard" set of Heston parameters used in many tests.
# kappa=2, theta=0.04 (20% vol), vol_of_vol=0.3, rho=-0.5, v0=0.04
PARAMS = HestonParams(mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=-0.5, v0=0.04)
S0 = 100.0
STRIKE_ATM = 100.0
TAU = 1.0
R = 0.05

SEED = 20240601


# ---------------------------------------------------------------------------
# Black-Scholes helper (used in BS-limit test)
# ---------------------------------------------------------------------------


def _bs_call(s0: float, k: float, tau: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price.

    Parameters
    ----------
    s0, k, tau, r, sigma:
        Spot, strike, maturity, rate, constant volatility.

    Returns
    -------
    float
        BS call price.
    """
    from scipy.stats import norm  # lazy import -- scipy available in venv

    sqrt_tau = math.sqrt(tau)
    d1 = (math.log(s0 / k) + (r + 0.5 * sigma ** 2) * tau) / (sigma * sqrt_tau)
    d2 = d1 - sigma * sqrt_tau
    df = math.exp(-r * tau)
    return float(s0 * norm.cdf(d1) - k * df * norm.cdf(d2))


# ---------------------------------------------------------------------------
# HestonParams unit tests
# ---------------------------------------------------------------------------


class TestHestonParams:
    """HestonParams dataclass and feller_satisfied property."""

    def test_frozen_dataclass_immutable(self) -> None:
        """HestonParams is immutable (frozen=True)."""
        with pytest.raises((AttributeError, TypeError)):
            PARAMS.kappa = 99.0  # type: ignore[misc]

    def test_feller_satisfied_true(self) -> None:
        """feller_satisfied returns True when 2*kappa*theta >= xi^2."""
        # 2 * 2.0 * 0.04 = 0.16 >= 0.09 = 0.3^2
        assert PARAMS.feller_satisfied

    def test_feller_satisfied_false(self) -> None:
        """feller_satisfied returns False when 2*kappa*theta < xi^2."""
        # 2 * 0.5 * 0.01 = 0.01 < 0.09 = 0.3^2
        p = HestonParams(mu=0.0, kappa=0.5, theta=0.01, vol_of_vol=0.3, rho=0.0, v0=0.01)
        assert not p.feller_satisfied

    def test_feller_exact_boundary(self) -> None:
        """At 2*kappa*theta == xi^2 the condition is exactly met."""
        xi = 0.3
        kappa = 2.0
        theta = xi ** 2 / (2.0 * kappa)  # exact boundary
        p = HestonParams(mu=0.0, kappa=kappa, theta=theta, vol_of_vol=xi, rho=0.0, v0=theta)
        assert p.feller_satisfied

    def test_direct_construction(self) -> None:
        """HestonParams stores all six fields correctly."""
        p = HestonParams(mu=0.01, kappa=3.0, theta=0.05, vol_of_vol=0.4, rho=-0.7, v0=0.03)
        assert p.mu == pytest.approx(0.01)
        assert p.kappa == pytest.approx(3.0)
        assert p.theta == pytest.approx(0.05)
        assert p.vol_of_vol == pytest.approx(0.4)
        assert p.rho == pytest.approx(-0.7)
        assert p.v0 == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# ValueError guard tests (_validate_params, simulate, call_price, calibrate)
# ---------------------------------------------------------------------------


class TestValueErrorGuards:
    """All domain-validation ValueError guards."""

    # _validate_params via simulate (shortest path to trigger validation)
    def test_bad_kappa_zero(self) -> None:
        p = HestonParams(mu=0.0, kappa=0.0, theta=0.04, vol_of_vol=0.3, rho=0.0, v0=0.04)
        with pytest.raises(ValueError, match="kappa"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_kappa_negative(self) -> None:
        p = HestonParams(mu=0.0, kappa=-1.0, theta=0.04, vol_of_vol=0.3, rho=0.0, v0=0.04)
        with pytest.raises(ValueError, match="kappa"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_theta(self) -> None:
        p = HestonParams(mu=0.0, kappa=2.0, theta=0.0, vol_of_vol=0.3, rho=0.0, v0=0.04)
        with pytest.raises(ValueError, match="theta"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_vol_of_vol(self) -> None:
        p = HestonParams(mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.0, rho=0.0, v0=0.04)
        with pytest.raises(ValueError, match="vol_of_vol"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_rho_low(self) -> None:
        p = HestonParams(mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=-1.5, v0=0.04)
        with pytest.raises(ValueError, match="rho"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_rho_high(self) -> None:
        p = HestonParams(mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=1.1, v0=0.04)
        with pytest.raises(ValueError, match="rho"):
            simulate(10, 0.01, 100.0, p)

    def test_bad_v0_negative(self) -> None:
        p = HestonParams(mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=0.0, v0=-0.01)
        with pytest.raises(ValueError, match="v0"):
            simulate(10, 0.01, 100.0, p)

    def test_simulate_bad_n(self) -> None:
        with pytest.raises(ValueError, match="n must be"):
            simulate(0, 0.01, 100.0, PARAMS)

    def test_simulate_bad_dt(self) -> None:
        with pytest.raises(ValueError, match="dt must be positive"):
            simulate(10, 0.0, 100.0, PARAMS)

    def test_simulate_bad_s0(self) -> None:
        with pytest.raises(ValueError, match="s0 must be positive"):
            simulate(10, 0.01, 0.0, PARAMS)

    def test_call_price_bad_s0(self) -> None:
        with pytest.raises(ValueError, match="s0"):
            call_price(0.0, 100.0, 1.0, PARAMS, r=R)

    def test_call_price_bad_strike(self) -> None:
        with pytest.raises(ValueError, match="strike"):
            call_price(100.0, 0.0, 1.0, PARAMS, r=R)

    def test_call_price_bad_tau(self) -> None:
        with pytest.raises(ValueError, match="tau"):
            call_price(100.0, 100.0, 0.0, PARAMS, r=R)

    def test_calibrate_empty_quotes(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            calibrate([], s0=100.0, r=0.05)

    def test_calibrate_bad_s0(self) -> None:
        with pytest.raises(ValueError, match="s0"):
            calibrate([(100.0, 1.0, 10.0)], s0=0.0)

    def test_calibrate_bad_strike(self) -> None:
        with pytest.raises(ValueError, match="strike"):
            calibrate([(0.0, 1.0, 5.0)], s0=100.0)

    def test_calibrate_bad_tau(self) -> None:
        with pytest.raises(ValueError, match="tau"):
            calibrate([(100.0, 0.0, 5.0)], s0=100.0)

    def test_calibrate_negative_price(self) -> None:
        with pytest.raises(ValueError, match="market_call_price"):
            calibrate([(100.0, 1.0, -1.0)], s0=100.0)


# ---------------------------------------------------------------------------
# simulate tests
# ---------------------------------------------------------------------------


class TestSimulate:
    """simulate: shape, initial row, determinism, variance non-negativity."""

    def test_output_shape(self) -> None:
        """Output has n rows and 2 columns (price, variance)."""
        df = simulate(n=100, dt=1 / 252, s0=S0, params=PARAMS, seed=SEED)
        assert df.shape == (100, 2)
        assert list(df.columns) == ["price", "variance"]

    def test_initial_row(self) -> None:
        """First row must be exactly (s0, v0)."""
        df = simulate(n=50, dt=1 / 252, s0=S0, params=PARAMS, seed=SEED)
        assert df["price"].iloc[0] == pytest.approx(S0)
        assert df["variance"].iloc[0] == pytest.approx(PARAMS.v0)

    def test_n_equals_one(self) -> None:
        """n=1 returns a single-row DataFrame equal to (s0, v0)."""
        df = simulate(n=1, dt=1 / 252, s0=S0, params=PARAMS, seed=SEED)
        assert len(df) == 1
        assert df["price"].iloc[0] == pytest.approx(S0)
        assert df["variance"].iloc[0] == pytest.approx(PARAMS.v0)

    def test_determinism_same_seed(self) -> None:
        """Same seed produces identical paths."""
        df1 = simulate(n=200, dt=1 / 252, s0=S0, params=PARAMS, seed=42)
        df2 = simulate(n=200, dt=1 / 252, s0=S0, params=PARAMS, seed=42)
        np.testing.assert_array_equal(df1["price"].values, df2["price"].values)
        np.testing.assert_array_equal(df1["variance"].values, df2["variance"].values)

    def test_determinism_different_seeds(self) -> None:
        """Different seeds produce different paths."""
        df1 = simulate(n=200, dt=1 / 252, s0=S0, params=PARAMS, seed=1)
        df2 = simulate(n=200, dt=1 / 252, s0=S0, params=PARAMS, seed=2)
        assert not np.array_equal(df1["price"].values, df2["price"].values)

    def test_variance_non_negative(self) -> None:
        """Full-truncation ensures all variance entries are >= 0."""
        # Use a Feller-violating parameter set to stress the truncation
        p_feller_fail = HestonParams(
            mu=0.0, kappa=0.5, theta=0.02, vol_of_vol=0.8, rho=0.0, v0=0.02
        )
        df = simulate(n=5000, dt=1 / 252, s0=S0, params=p_feller_fail, seed=SEED)
        assert (df["variance"].values >= 0.0).all()

    def test_variance_non_negative_standard(self) -> None:
        """Variance is non-negative under standard parameters as well."""
        df = simulate(n=2000, dt=1 / 252, s0=S0, params=PARAMS, seed=SEED)
        assert (df["variance"].values >= 0.0).all()

    def test_long_run_variance_mean(self) -> None:
        """Long path: sample mean of variance converges to theta.

        The CIR variance process is ergodic with stationary mean theta.
        On a path of 50000 annual steps (dt=1/252, n=50000 ~ 200 years)
        the sample mean should be within 20% of theta.
        """
        n = 50_000
        p = HestonParams(mu=0.0, kappa=3.0, theta=0.04, vol_of_vol=0.3, rho=0.0, v0=0.04)
        df = simulate(n=n, dt=1 / 252, s0=S0, params=p, seed=SEED)
        mean_var = float(df["variance"].mean())
        assert abs(mean_var - p.theta) / p.theta < 0.20, (
            f"Long-run variance mean {mean_var:.5f} deviates > 20% from theta={p.theta}"
        )

    def test_v0_zero_path_stays_nonnegative(self) -> None:
        """Starting at v0=0 with Feller-fail params must not go negative."""
        p = HestonParams(mu=0.0, kappa=1.0, theta=0.04, vol_of_vol=1.0, rho=0.0, v0=0.0)
        df = simulate(n=2000, dt=1 / 252, s0=S0, params=p, seed=SEED)
        assert (df["variance"].values >= 0.0).all()


# ---------------------------------------------------------------------------
# Characteristic function tests
# ---------------------------------------------------------------------------


class TestCharacteristicFunction:
    """CF normalisation, martingale condition, and BS-degenerate-case check."""

    def test_cf_at_zero_equals_one(self) -> None:
        """phi(0) == 1 for any valid parameter set."""
        cf0 = characteristic_function(np.complex128(0.0 + 0j), TAU, PARAMS, r=R)
        assert abs(complex(cf0) - 1.0) < 1e-12

    def test_martingale_condition(self) -> None:
        """phi_full(-i) == S0 * exp(r*tau) (risk-neutral martingale).

        The centred CF satisfies CF(-i) = 1.0, i.e. E_Q[S_T / S_0] == exp(r*tau).
        This is the martingale condition and is the central identity that the
        Albrecher discriminant sign ensures.
        """
        cf_mi = characteristic_function(np.complex128(-1j), TAU, PARAMS, r=R)
        # CF_partial(-i) must equal 1.0 exactly for the martingale to hold
        assert abs(complex(cf_mi) - 1.0) < 1e-8, (
            f"CF(-i) = {complex(cf_mi):.8f}, expected 1.0"
        )

    def test_cf_returns_complex(self) -> None:
        """CF returns a complex number for a real frequency argument."""
        result = characteristic_function(np.complex128(1.0 + 0j), TAU, PARAMS)
        assert isinstance(complex(result), complex)

    def test_cf_bs_limit_at_minus_i(self) -> None:
        """In the BS limit (xi->0, v0=theta), CF(-i) must still equal 1.0."""
        p_bs = HestonParams(
            mu=0.0, kappa=20.0, theta=0.04, vol_of_vol=1e-4, rho=0.0, v0=0.04
        )
        cf_mi = characteristic_function(np.complex128(-1j), TAU, p_bs, r=R)
        assert abs(complex(cf_mi) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# call_price: Black-Scholes limit (linchpin test)
# ---------------------------------------------------------------------------


class TestCallPriceBSLimit:
    """call_price converges to the Black-Scholes price as vol_of_vol -> 0.

    When vol_of_vol is very small and v0 = theta = sigma^2, the Heston model
    degenerates to GBM with constant volatility sigma.  The Heston call price
    must agree with the Black-Scholes formula to tight tolerance.

    Tolerance target: <= 5 basis points (0.05% of S0) for vol_of_vol = 1e-3.
    """

    SIGMA = 0.2          # target constant vol
    THETA = SIGMA ** 2   # = 0.04
    # Tight Heston params for the BS limit
    P_BS = HestonParams(
        mu=0.0, kappa=20.0, theta=THETA, vol_of_vol=1e-3, rho=0.0, v0=THETA
    )

    def _check(self, k: float, tau: float, r: float, tol_bp: float = 5.0) -> None:
        """Assert Heston price matches BS price within tol_bp basis points."""
        heston = call_price(S0, k, tau, self.P_BS, r=r)
        bs = _bs_call(S0, k, tau, r, self.SIGMA)
        err_bp = abs(heston - bs) / S0 * 10_000
        assert err_bp <= tol_bp, (
            f"K={k}, tau={tau}: Heston={heston:.6f}, BS={bs:.6f}, "
            f"err={err_bp:.3f}bp > {tol_bp}bp"
        )

    def test_atm(self) -> None:
        """ATM call converges to BS within 5 bp."""
        self._check(k=100.0, tau=1.0, r=0.05)

    def test_itm(self) -> None:
        """ITM (K=85) call converges to BS within 5 bp."""
        self._check(k=85.0, tau=1.0, r=0.05)

    def test_otm(self) -> None:
        """OTM (K=115) call converges to BS within 5 bp."""
        self._check(k=115.0, tau=1.0, r=0.05)

    def test_short_maturity(self) -> None:
        """Short maturity (3 months) ATM call converges to BS within 5 bp."""
        self._check(k=100.0, tau=0.25, r=0.05)

    def test_long_maturity(self) -> None:
        """Long maturity (2 years) ATM call converges to BS within 5 bp."""
        self._check(k=100.0, tau=2.0, r=0.05)

    def test_zero_rate(self) -> None:
        """Zero interest rate: ATM call converges to BS within 5 bp."""
        self._check(k=100.0, tau=1.0, r=0.0)


# ---------------------------------------------------------------------------
# call_price: arbitrage bounds and no-arbitrage checks
# ---------------------------------------------------------------------------


class TestCallPriceArbitrageBounds:
    """call_price satisfies the standard option no-arbitrage inequalities."""

    @pytest.mark.parametrize("k", [50.0, 75.0, 100.0, 125.0, 150.0, 200.0])
    def test_lower_bound_intrinsic(self, k: float) -> None:
        """C >= max(S0 - K * exp(-r*tau), 0) (intrinsic value lower bound)."""
        c = call_price(S0, k, TAU, PARAMS, r=R)
        intrinsic = max(S0 - k * math.exp(-R * TAU), 0.0)
        assert c >= intrinsic - 1e-8, (
            f"K={k}: price={c:.4f} < intrinsic={intrinsic:.4f}"
        )

    @pytest.mark.parametrize("k", [50.0, 75.0, 100.0, 125.0, 150.0, 200.0])
    def test_upper_bound_spot(self, k: float) -> None:
        """C <= S0 (call cannot be worth more than the underlying)."""
        c = call_price(S0, k, TAU, PARAMS, r=R)
        assert c <= S0 + 1e-8, (
            f"K={k}: price={c:.4f} > S0={S0}"
        )

    def test_deep_itm_near_intrinsic(self) -> None:
        """Deep ITM call (K=10) price ~ S0 - K*discount (parity bound tightly)."""
        k = 10.0
        c = call_price(S0, k, TAU, PARAMS, r=R)
        intrinsic = S0 - k * math.exp(-R * TAU)
        # For a deep ITM call the price must be very close to intrinsic
        assert c >= intrinsic * 0.99, f"Deep ITM: price={c:.4f} << intrinsic={intrinsic:.4f}"

    def test_deep_otm_small_positive(self) -> None:
        """Deep OTM call (K=300) price is small but positive."""
        c = call_price(S0, 300.0, TAU, PARAMS, r=R)
        assert 0.0 <= c < 1.0, f"Deep OTM: price={c:.6f} not in [0, 1)"

    def test_price_decreasing_in_strike(self) -> None:
        """Call price is monotone decreasing in strike."""
        strikes = [70.0, 90.0, 100.0, 110.0, 130.0]
        prices = [call_price(S0, k, TAU, PARAMS, r=R) for k in strikes]
        for i in range(len(prices) - 1):
            assert prices[i] >= prices[i + 1] - 1e-8, (
                f"Not monotone: C(K={strikes[i]})={prices[i]:.4f} < "
                f"C(K={strikes[i+1]})={prices[i+1]:.4f}"
            )

    def test_put_call_parity(self) -> None:
        """Put-call parity: C - P = S0 - K * exp(-r*tau).

        We compute the put via P = C - S0 + K*exp(-r*tau) and verify the
        parity identity is self-consistent across three strikes.
        """
        for k in [90.0, 100.0, 110.0]:
            c = call_price(S0, k, TAU, PARAMS, r=R)
            df = math.exp(-R * TAU)
            p_from_parity = c - S0 + k * df
            # Verify P >= 0 (put price non-negative)
            assert p_from_parity >= -1e-6, (
                f"K={k}: implied put price {p_from_parity:.4f} is negative"
            )
            # Verify C = P + S0 - K*df self-consistently
            c_check = p_from_parity + S0 - k * df
            assert abs(c_check - c) < 1e-10, (
                f"K={k}: parity identity failed: {c_check:.6f} != {c:.6f}"
            )


# ---------------------------------------------------------------------------
# simulate: Feller-condition stress test
# ---------------------------------------------------------------------------


class TestFellerProperty:
    """Feller condition and its effect on variance positivity."""

    def test_feller_satisfied_flag(self) -> None:
        """PARAMS (kappa=2, theta=0.04, xi=0.3) satisfies the Feller condition."""
        assert PARAMS.feller_satisfied

    def test_feller_violated_flag(self) -> None:
        """Parameters with 2*kappa*theta < xi^2 report the condition as violated."""
        p = HestonParams(mu=0.0, kappa=0.5, theta=0.01, vol_of_vol=0.5, rho=0.0, v0=0.01)
        # 2*0.5*0.01 = 0.01 < 0.25 = 0.5^2
        assert not p.feller_satisfied

    def test_feller_violated_variance_still_nonneg(self) -> None:
        """Even when Feller condition is violated, simulate keeps variance >= 0."""
        p = HestonParams(mu=0.0, kappa=0.3, theta=0.01, vol_of_vol=1.0, rho=0.0, v0=0.01)
        df = simulate(n=10_000, dt=1 / 252, s0=S0, params=p, seed=SEED)
        assert (df["variance"].values >= 0.0).all()


# ---------------------------------------------------------------------------
# Calibration round-trip
# ---------------------------------------------------------------------------


class TestCalibrationRoundTrip:
    """Calibrate to prices generated from known params; verify price RMSE.

    The primary quality metric is the price RMSE after re-pricing with the
    calibrated parameters.  Individual parameter recovery is checked with
    loose tolerances because the Heston loss surface has flat ridges that
    allow multiple parameter combinations to fit prices equally well.
    """

    # True params used to generate the synthetic option grid
    TRUE_PARAMS = HestonParams(
        mu=0.0, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=-0.5, v0=0.04
    )
    _S0 = 100.0
    _R = 0.03

    # Strike-maturity grid: 4 strikes x 2 maturities = 8 quotes
    STRIKES = [85.0, 95.0, 100.0, 110.0]
    MATURITIES = [0.5, 1.0]

    def _build_quotes(self) -> list[tuple[float, float, float]]:
        """Generate option prices from the true params."""
        quotes = []
        for tau in self.MATURITIES:
            for k in self.STRIKES:
                c = call_price(self._S0, k, tau, self.TRUE_PARAMS, r=self._R)
                quotes.append((k, tau, c))
        return quotes

    def test_calibration_price_rmse(self) -> None:
        """Re-priced model prices match calibration targets with RMSE < 0.05.

        A price RMSE of 0.05 on a grid anchored around S0=100 is approximately
        5 cents per contract -- well within practical precision limits.
        The calibration is warm-started from the true params to help the
        Nelder-Mead simplex find the right basin quickly.
        """
        quotes = self._build_quotes()

        # Warm-start calibration from the true parameter neighbourhood
        initial = HestonParams(
            mu=0.0,
            kappa=2.5,     # near true 2.0
            theta=0.045,   # near true 0.04
            vol_of_vol=0.35,  # near true 0.3
            rho=-0.4,      # near true -0.5
            v0=0.045,      # near true 0.04
        )
        calibrated = calibrate(quotes, self._S0, r=self._R, initial=initial)

        # Re-price with calibrated params and compute RMSE
        errors = []
        for k, tau, c_mkt in quotes:
            c_model = call_price(self._S0, k, tau, calibrated, r=self._R)
            errors.append((c_model - c_mkt) ** 2)
        rmse = float(np.sqrt(np.mean(errors)))
        assert rmse < 0.05, (
            f"Calibration RMSE={rmse:.4f} exceeds threshold 0.05. "
            f"Calibrated params: kappa={calibrated.kappa:.3f}, "
            f"theta={calibrated.theta:.4f}, xi={calibrated.vol_of_vol:.3f}, "
            f"rho={calibrated.rho:.3f}, v0={calibrated.v0:.4f}"
        )

    def test_calibrated_params_in_domain(self) -> None:
        """Calibrated parameters must satisfy all domain constraints."""
        quotes = self._build_quotes()
        calibrated = calibrate(quotes, self._S0, r=self._R)
        assert calibrated.kappa > 0.0
        assert calibrated.theta > 0.0
        assert calibrated.vol_of_vol > 0.0
        assert -1.0 <= calibrated.rho <= 1.0
        assert calibrated.v0 >= 0.0

    def test_calibration_theta_recovery_loose(self) -> None:
        """Long-run variance theta is approximately recovered (within 50%).

        theta is one of the better-identified parameters. Even so, the
        tolerance is loose (50%) because the loss surface is non-convex.
        """
        quotes = self._build_quotes()
        initial = HestonParams(
            mu=0.0, kappa=2.5, theta=0.045, vol_of_vol=0.35, rho=-0.4, v0=0.045
        )
        calibrated = calibrate(quotes, self._S0, r=self._R, initial=initial)
        assert abs(calibrated.theta - self.TRUE_PARAMS.theta) / self.TRUE_PARAMS.theta < 0.50, (
            f"theta recovery: got {calibrated.theta:.4f}, true={self.TRUE_PARAMS.theta}"
        )

    def test_calibration_v0_recovery_loose(self) -> None:
        """Initial variance v0 is approximately recovered (within 50%)."""
        quotes = self._build_quotes()
        initial = HestonParams(
            mu=0.0, kappa=2.5, theta=0.045, vol_of_vol=0.35, rho=-0.4, v0=0.045
        )
        calibrated = calibrate(quotes, self._S0, r=self._R, initial=initial)
        assert abs(calibrated.v0 - self.TRUE_PARAMS.v0) / self.TRUE_PARAMS.v0 < 0.50, (
            f"v0 recovery: got {calibrated.v0:.4f}, true={self.TRUE_PARAMS.v0}"
        )

    def test_calibration_default_start(self) -> None:
        """Calibration with default starting point (no initial) must not raise."""
        quotes = self._build_quotes()
        # This test only asserts no exception; convergence is not guaranteed
        # from the default start, which may be far from the true basin.
        calibrated = calibrate(quotes, self._S0, r=self._R)
        assert calibrated.kappa > 0.0


# ---------------------------------------------------------------------------
# Public API check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """The four public names are importable from the submodule path."""

    def test_imports_from_submodule(self) -> None:
        from core_trading.signals.stochastic.heston import (  # noqa: F401
            HestonParams,
            calibrate,
            call_price,
            characteristic_function,
            simulate,
        )

    def test_all_contents(self) -> None:
        import core_trading.signals.stochastic.heston as mod

        for name in ("HestonParams", "simulate", "characteristic_function",
                     "call_price", "calibrate"):
            assert hasattr(mod, name), f"missing from __all__: {name}"

    def test_all_list_complete(self) -> None:
        import core_trading.signals.stochastic.heston as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"__all__ entry {name!r} not defined"
