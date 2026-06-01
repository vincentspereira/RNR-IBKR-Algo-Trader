"""Heston stochastic-volatility model -- Phase 5.B.3.

This module is the canonical Heston (1993) implementation for the IBKR Algo
Trader codebase.  It provides Monte Carlo simulation via the full-truncation
Euler scheme, a numerically stable characteristic function (the ``little
Heston trap'' formulation), semi-closed-form European call pricing via the
two-probability Gil-Pelaez representation, and market-implied parameter
calibration.

Relationship to other modules
------------------------------
This module is self-contained.  It does not depend on ``ou.py``, ``gbm.py``,
or any other stochastic-process module.  It is imported by the integrator
via ``core_trading.signals.stochastic.heston``.

Model equations
---------------
The Heston (1993) SDE system under any measure with drift mu:

    dS_t = mu * S_t * dt + sqrt(v_t) * S_t * dW1_t
    dv_t = kappa * (theta - v_t) * dt + xi * sqrt(v_t) * dW2_t

where corr(dW1_t, dW2_t) = rho.  Under the risk-neutral measure set mu = r.

Parameters:

    mu       -- drift (physical) or risk-free rate r (risk-neutral)
    kappa    -- mean-reversion speed of the variance process (> 0)
    theta    -- long-run variance (> 0)
    xi       -- vol_of_vol: volatility of the variance process (> 0)
    rho      -- correlation between the two Brownians, in [-1, 1]
    v0       -- initial variance (>= 0)

Feller condition: 2 * kappa * theta >= xi^2 ensures v_t > 0 a.s.
When violated, v_t can touch zero; the full-truncation Euler scheme handles
this by clamping negative realised variance to zero before each step.

Characteristic function -- Albrecher "little Heston trap"
----------------------------------------------------------
The module computes phi(u) = E_Q[exp(i*u * (log(S_T) - log(S_0) - r*tau))]
(the CF of the centred log-return under the risk-neutral measure), using the
``little Heston trap'' variant (Albrecher et al. 2007).

Standard (Heston 1993) discriminant:

    d = sqrt((kappa - rho * xi * i * u)^2 + xi^2 * (i*u + u^2))

Little-trap choice for g (avoids log branch cut):

    g2 = (b - d) / (b + d)   where b = kappa - rho * xi * i * u

With the Albrecher convention the exponent becomes:

    A  = kappa * theta / xi^2
           * ((b - d) * tau - 2 * log((1 - g2 * exp(-d*tau)) / (1 - g2)))
       + v0 / xi^2 * (b - d) * (1 - exp(-d*tau)) / (1 - g2 * exp(-d*tau))

    phi(u) = exp(A)

The full CF of log(S_T) (not centred) is then:

    phi_full(u) = exp(i*u * (log(S_0) + r * tau)) * phi(u)

Option pricing -- Gil-Pelaez P1 / P2 form
------------------------------------------
For a European call with strike K and maturity tau:

    C = S_0 * P1 - K * exp(-r * tau) * P2

where the two risk-neutral probabilities are recovered by inversion:

    P2 = 0.5 + (1/pi) * Int_0^inf Re[exp(-i*u*log(K)) * phi_full(u) / (i*u)] du

    P1 = 0.5 + (1/pi) * Int_0^inf Re[exp(-i*u*log(K)) * phi_full(u-i) / (i*u*phi_full(-i))] du

phi_full(-i) = E_Q[S_T] = S_0 * exp(r * tau) by the risk-neutral martingale
condition (and is verified numerically to hold to machine precision).

Both integrals are evaluated by scipy.integrate.quad over the finite interval
(1e-4, 200).  The upper limit of 200 is sufficient for all standard parameter
combinations (the integrand decays as exp(-const * u^2) for large u); the
small lower bound avoids the 1/u pole at u=0 (the integrand has a finite
removable singularity there).

Mathematical references
-----------------------
* Heston, S. L. (1993). "A closed-form solution for options with stochastic
  volatility with applications to bond and currency options." Review of
  Financial Studies, 6(2), 327-343.
* Albrecher, H., Mayer, P., Schoutens, W. & Tistaert, J. (2007). "The little
  Heston trap." Wilmott Magazine, January 2007, 83-92.
* Lord, R., Koekkoek, R. & van Dijk, D. (2010). "A comparison of biased
  simulation schemes for stochastic volatility models." Quantitative Finance,
  10(2), 177-194.  (Full-truncation Euler scheme.)
* Gatheral, J. (2006). The Volatility Surface: A Practitioner's Guide.
  Wiley Finance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "HestonParams",
    "simulate",
    "characteristic_function",
    "call_price",
    "calibrate",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HestonParams:
    """Parameters for the Heston (1993) stochastic-volatility model.

    Attributes
    ----------
    mu:
        Drift of the asset (per unit time).  Set to the risk-free rate r
        under the risk-neutral measure.
    kappa:
        Mean-reversion speed of the variance process.  Must be > 0.
    theta:
        Long-run (stationary) variance.  Must be > 0.
    vol_of_vol:
        Volatility of the variance process (xi in the SDE).  Must be > 0.
    rho:
        Correlation between the asset and variance Brownian motions.
        Must be in [-1, 1].
    v0:
        Initial instantaneous variance.  Must be >= 0.

    Notes
    -----
    The Feller condition 2 * kappa * theta >= vol_of_vol^2 ensures the
    variance process stays strictly positive.  The :attr:`feller_satisfied`
    property checks this condition.  When it fails, the full-truncation Euler
    scheme in :func:`simulate` still works by clamping variance at zero.
    """

    mu: float
    kappa: float
    theta: float
    vol_of_vol: float
    rho: float
    v0: float

    @property
    def feller_satisfied(self) -> bool:
        """Return True when 2*kappa*theta >= vol_of_vol^2 (strong Feller)."""
        return 2.0 * self.kappa * self.theta >= self.vol_of_vol ** 2


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


def _validate_params(params: HestonParams) -> None:
    """Raise ValueError for out-of-domain HestonParams.

    Parameters
    ----------
    params:
        The parameter set to validate.

    Raises
    ------
    ValueError
        If any parameter violates its domain constraint.
    """
    if params.kappa <= 0.0:
        raise ValueError(f"kappa must be > 0, got {params.kappa}")
    if params.theta <= 0.0:
        raise ValueError(f"theta must be > 0, got {params.theta}")
    if params.vol_of_vol <= 0.0:
        raise ValueError(f"vol_of_vol must be > 0, got {params.vol_of_vol}")
    if not (-1.0 <= params.rho <= 1.0):
        raise ValueError(f"rho must be in [-1, 1], got {params.rho}")
    if params.v0 < 0.0:
        raise ValueError(f"v0 must be >= 0, got {params.v0}")


# ---------------------------------------------------------------------------
# Simulation -- full-truncation Euler scheme (Lord, Koekkoek & van Dijk 2010)
# ---------------------------------------------------------------------------


def simulate(
    n: int,
    dt: float,
    s0: float,
    params: HestonParams,
    seed: int | None = None,
) -> pd.DataFrame:
    """Simulate a Heston price/variance path via the full-truncation Euler scheme.

    The full-truncation (FT) scheme from Lord, Koekkoek & van Dijk (2010) is
    used for the variance process.  Rather than reflecting or taking the
    absolute value of negative simulated variance, FT replaces any negative
    v_t with zero before computing the drift and diffusion of the *next* step.
    This significantly reduces the positive bias present in the standard
    Euler-Maruyama and reflection schemes.

    Discretisation at step t (letting v+ = max(v_t, 0)):

        v_{t+1} = v_t + kappa * (theta - v+) * dt
                  + xi * sqrt(v+) * sqrt(dt) * Z2_t
        v_{t+1} = max(v_{t+1}, 0)            [truncate after update]

        log(S_{t+1}/S_t) = (mu - 0.5 * v+) * dt + sqrt(v+) * sqrt(dt) * Z1_t

    where (Z1_t, Z2_t) are correlated standard normals with corr = rho,
    drawn via the Cholesky decomposition of [[1, rho], [rho, 1]]:

        Z1 = eps1
        Z2 = rho * eps1 + sqrt(1 - rho^2) * eps2,  eps1, eps2 ~ iid N(0,1)

    Parameters
    ----------
    n:
        Total number of rows to return (including the initial row).
        Row 0 is (s0, v0); rows 1..n-1 are the simulated path.
    dt:
        Size of each time step (e.g. 1/252 for daily, 1/52 for weekly,
        in the same time units as the parameters).
    s0:
        Initial asset price.  Must be > 0.
    params:
        Heston model parameters.  Validated before use.
    seed:
        Integer seed for ``numpy.random.default_rng``.  ``None`` uses a
        random seed.  The same seed always reproduces an identical path.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``price`` and ``variance``, of length ``n``.
        Row 0 is exactly ``(s0, params.v0)``; subsequent rows follow the
        simulated path.  All variance entries are >= 0 by construction.

    Raises
    ------
    ValueError
        If ``n < 1``, ``dt <= 0``, ``s0 <= 0``, or any parameter violates
        its domain constraint.

    Mathematical references
    -----------------------
    Lord, Koekkoek & van Dijk (2010), Quantitative Finance 10(2), 177-194.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if s0 <= 0.0:
        raise ValueError("s0 must be positive")
    _validate_params(params)

    kappa = params.kappa
    theta = params.theta
    xi = params.vol_of_vol
    rho = params.rho
    mu = params.mu
    v0 = params.v0

    prices = np.empty(n, dtype=float)
    variances = np.empty(n, dtype=float)
    prices[0] = s0
    variances[0] = v0

    if n > 1:
        rng = np.random.default_rng(seed)
        sqrt_dt = float(np.sqrt(dt))
        # sqrt(1 - rho^2) for the orthogonal component of dW2
        rho_perp = float(np.sqrt(max(1.0 - rho * rho, 0.0)))

        # Draw all independent standard normals in one call (cache-friendly)
        z1 = rng.standard_normal(n - 1)
        z2_ind = rng.standard_normal(n - 1)

        v_curr = float(v0)
        s_curr = float(s0)

        for t in range(1, n):
            v_plus = max(v_curr, 0.0)   # full-truncation: clamp before use
            sqrt_v = float(np.sqrt(v_plus))

            # Correlated Brownian increments
            dw1 = z1[t - 1] * sqrt_dt
            dw2 = (rho * z1[t - 1] + rho_perp * z2_ind[t - 1]) * sqrt_dt

            # Variance step: full-truncation uses v_plus in both drift and diffusion
            v_next = v_curr + kappa * (theta - v_plus) * dt + xi * sqrt_v * dw2
            v_next = max(v_next, 0.0)   # truncate the output too

            # Log-price step
            log_ret = (mu - 0.5 * v_plus) * dt + sqrt_v * dw1
            s_next = s_curr * float(np.exp(log_ret))

            prices[t] = s_next
            variances[t] = v_next

            s_curr = s_next
            v_curr = v_next

    return pd.DataFrame({"price": prices, "variance": variances})


# ---------------------------------------------------------------------------
# Characteristic function -- Albrecher "little Heston trap"
# ---------------------------------------------------------------------------


def characteristic_function(
    u: complex | np.ndarray,
    tau: float,
    params: HestonParams,
    r: float = 0.0,  # noqa: ARG001 -- kept for interface symmetry with call_price
) -> complex | np.ndarray:
    """Heston characteristic function of the centred log-return under Q.

    Computes phi(u) = E_Q[exp(i*u * (log(S_T) - log(S_0) - r*tau))] using
    the ``little Heston trap'' formulation of Albrecher et al. (2007).

    This variant uses the reversed-sign choice of g (called g2 here with
    denominator b+d rather than b-d) to ensure |g2| <= 1 on the integration
    contour, eliminating the logarithm branch-cut discontinuity present in
    the original Heston (1993) formulation.

    Formula (all variables are complex-valued):

        b  = kappa - rho * xi * i * u

        d  = sqrt(b^2 + xi^2 * (i*u + u^2))       [correct sign: +xi^2*iu]

        g2 = (b - d) / (b + d)                     [little-trap choice]

        A  = kappa * theta / xi^2
               * ((b - d) * tau - 2 * log((1 - g2 * exp(-d * tau)) / (1 - g2)))
             + v0 / xi^2 * (b - d) * (1 - exp(-d * tau)) / (1 - g2 * exp(-d * tau))

        phi(u) = exp(A)

    Note on the discriminant sign: the discriminant must be
    b^2 + xi^2*(i*u + u^2), NOT b^2 - xi^2*(i*u - u^2).  Although these are
    algebraically equal, different implementations sometimes use the minus
    form which requires careful handling of the complex square-root sign
    choice.  The plus form used here consistently selects the correct branch.

    The full characteristic function of log(S_T) (not centred) is:

        phi_full(u) = exp(i*u*(log(S_0) + r*tau)) * phi(u)

    Parameters
    ----------
    u:
        Frequency argument.  May be a scalar complex number or a numpy
        array of complex values.  For the P1/P2 pricing integrals, pass
        real values (with u along the real axis), and complex shifts such
        as u - i (written as ``complex(u_real, -1.0)``).
    tau:
        Time to maturity in the same units as the parameters.  Must be > 0.
    params:
        Heston parameters.  Validated before use.
    r:
        Continuously-compounded risk-free rate.  Included for interface
        consistency; the centred CF does not depend on r directly (r enters
        only via the forward-price normalisation in phi_full).

    Returns
    -------
    complex | np.ndarray
        Value of the (centred) characteristic function at each u.  The
        return type matches the input type (scalar or array).

    Mathematical references
    -----------------------
    Albrecher, Mayer, Schoutens & Tistaert (2007), Wilmott Magazine, Jan 2007.
    Gatheral (2006), The Volatility Surface, Wiley Finance, Chapter 2.
    Heston (1993), Review of Financial Studies 6(2), 327-343.
    """
    _validate_params(params)

    kappa = params.kappa
    theta = params.theta
    xi = params.vol_of_vol
    rho = params.rho
    v0 = params.v0
    xi2 = xi * xi

    # b = kappa - rho * xi * i * u
    b = kappa - rho * xi * 1j * u

    # Discriminant: d = sqrt(b^2 + xi^2 * (iu + u^2))
    # This is the key sign: +xi^2*(iu+u^2), which ensures that at u=-i we
    # get disc = (kappa - xi*(- rho))^2 + xi^2*(1 + (-1)) = kappa^2 (for rho=0),
    # yielding d = kappa, and the correct CF_partial(-i) = 1.0 (martingale).
    disc = b * b + xi2 * (1j * u + u * u)
    d = np.sqrt(disc)

    # Little-trap g2: use b+d in denominator so |g2| <= 1 on contour
    g2 = (b - d) / (b + d)

    exp_neg_d_tau = np.exp(-d * tau)
    one_minus_g2 = 1.0 - g2
    one_minus_g2_exp = 1.0 - g2 * exp_neg_d_tau

    log_term = np.log(one_minus_g2_exp / one_minus_g2)

    # Exponent A: kappa*theta part
    a_kappa_theta = kappa * theta / xi2 * ((b - d) * tau - 2.0 * log_term)

    # Exponent A: v0 part
    a_v0 = v0 / xi2 * (b - d) * (1.0 - exp_neg_d_tau) / one_minus_g2_exp

    result: complex | np.ndarray = np.exp(a_kappa_theta + a_v0)
    return result


# ---------------------------------------------------------------------------
# European call price -- Gil-Pelaez P1/P2 form
# ---------------------------------------------------------------------------


def call_price(
    s0: float,
    strike: float,
    tau: float,
    params: HestonParams,
    r: float = 0.0,
) -> float:
    """Price a European call option using the Heston semi-closed form.

    Implements the Gil-Pelaez inversion formula for the two exercise
    probabilities P1 and P2 (Heston 1993, Gatheral 2006):

        C = S_0 * P1 - K * exp(-r * tau) * P2

    where:

        P2 = 0.5 + (1/pi) * Int_0^inf Re[exp(-i*u*log(K)) * phi_full(u)
                                            / (i*u)] du

        P1 = 0.5 + (1/pi) * Int_0^inf Re[exp(-i*u*log(K)) * phi_full(u-i)
                                            / (i*u * phi_full(-i))] du

    and phi_full(u) = exp(i*u*(log(S_0)+r*tau)) * CF(u) is the full CF of
    log(S_T).  Both integrals are evaluated with scipy.integrate.quad over
    the finite interval (1e-4, 200).  The integrand decays exponentially for
    large u (O(exp(-const*u^2))), so the upper bound of 200 introduces
    negligible truncation error for all standard parameter values.

    Parameters
    ----------
    s0:
        Current asset price.  Must be > 0.
    strike:
        Option strike price.  Must be > 0.
    tau:
        Time to maturity.  Must be > 0.
    params:
        Heston parameters.  Validated before use.
    r:
        Continuously-compounded risk-free rate.

    Returns
    -------
    float
        European call price.  Guaranteed to satisfy the no-arbitrage bounds::

            max(s0 - strike * exp(-r * tau), 0) <= C <= s0

    Raises
    ------
    ValueError
        If ``s0 <= 0``, ``strike <= 0``, ``tau <= 0``, or any parameter
        violates its domain constraint.

    Mathematical references
    -----------------------
    Heston (1993), Review of Financial Studies 6(2), 327-343.
    Gatheral (2006), The Volatility Surface, Wiley, Chapter 2.
    """
    import scipy.integrate  # lazy import

    if s0 <= 0.0:
        raise ValueError(f"s0 must be positive, got {s0}")
    if strike <= 0.0:
        raise ValueError(f"strike must be positive, got {strike}")
    if tau <= 0.0:
        raise ValueError(f"tau must be positive, got {tau}")
    _validate_params(params)

    log_s0 = float(np.log(s0))
    log_k = float(np.log(strike))
    df = float(np.exp(-r * tau))

    # Full CF of log(S_T): phi_full(u) = exp(iu*(log_s0+r*tau)) * CF(u)
    # phi_full(-i) = E_Q[S_T] = S_0 * exp(r*tau)  by the Q-martingale condition.
    phi_full_mi = s0 * float(np.exp(r * tau))  # use analytic value for stability

    def _integrand_p2(u_real: float) -> float:
        u = np.complex128(complex(u_real, 0.0))
        phi_u = np.exp(1j * u * (log_s0 + r * tau)) * characteristic_function(
            u, tau, params, r=r
        )
        val = np.exp(-1j * u * log_k) * phi_u / (1j * u)
        return float(np.real(val))

    def _integrand_p1(u_real: float) -> float:
        u = np.complex128(complex(u_real, 0.0))
        # Shifted argument u - i: complex(u_real, -1.0)
        u_shift = np.complex128(complex(u_real, -1.0))
        phi_u_shift = np.exp(1j * u_shift * (log_s0 + r * tau)) * characteristic_function(
            u_shift, tau, params, r=r
        )
        val = np.exp(-1j * u * log_k) * phi_u_shift / (1j * u * phi_full_mi)
        return float(np.real(val))

    # Integrate over a finite domain to avoid IntegrationWarning.
    # Upper limit 200 is sufficient for all standard Heston parameters;
    # the integrand is O(exp(-v0*tau*u^2)) for large u.
    i2, _ = scipy.integrate.quad(
        _integrand_p2, 1e-4, 200.0, epsabs=1e-8, epsrel=1e-6, limit=200
    )
    i1, _ = scipy.integrate.quad(
        _integrand_p1, 1e-4, 200.0, epsabs=1e-8, epsrel=1e-6, limit=200
    )

    p2 = 0.5 + i2 / float(np.pi)
    p1 = 0.5 + i1 / float(np.pi)

    raw_price = s0 * p1 - strike * df * p2

    # Enforce no-arbitrage bounds
    intrinsic = max(s0 - strike * df, 0.0)
    return float(np.clip(raw_price, intrinsic, s0))


# ---------------------------------------------------------------------------
# Calibration -- unconstrained optimisation with parameter transforms
# ---------------------------------------------------------------------------


def calibrate(
    market_quotes: list[tuple[float, float, float]],
    s0: float,
    r: float = 0.0,
    *,
    initial: HestonParams | None = None,
) -> HestonParams:
    """Calibrate Heston risk-neutral parameters to market option quotes.

    Finds the 5 risk-neutral parameters (kappa, theta, vol_of_vol, rho, v0)
    that minimise the sum of squared pricing errors between Heston model
    prices and observed market call prices.  The drift mu is not identifiable
    from option prices; it is fixed to r (or carried from ``initial.mu``).

    Optimisation is performed over an unconstrained transformed parameter
    space to enforce domain constraints without explicit bounds:

        transformed[0] = log(kappa)          -> kappa = exp(x[0]) > 0
        transformed[1] = log(theta)          -> theta = exp(x[1]) > 0
        transformed[2] = log(vol_of_vol)     -> vol_of_vol = exp(x[2]) > 0
        transformed[3] = atanh(rho)          -> rho = tanh(x[3]) in (-1, 1)
        transformed[4] = log(v0 + 1e-8)      -> v0 = exp(x[4]) - 1e-8 >= 0

    The Nelder-Mead simplex method is used (no gradient required); it is
    robust to the flat and multi-modal loss surface typical of Heston
    calibration.  ``adaptive=True`` scales the simplex to the problem
    dimension, improving convergence in 5D.

    Parameters
    ----------
    market_quotes:
        List of (strike, tau, market_call_price) tuples.  All values must
        be positive (call prices must be >= 0).  At least one quote is
        required.
    s0:
        Current asset price.  Must be > 0.
    r:
        Continuously-compounded risk-free rate.
    initial:
        Optional starting HestonParams.  When ``None``, the default starting
        point is kappa=2, theta=0.04, vol_of_vol=0.3, rho=-0.5, v0=0.04.
        The ``mu`` field is carried from ``initial`` if provided, else set
        to r.

    Returns
    -------
    HestonParams
        Calibrated parameters with mu fixed to r (or initial.mu).

    Raises
    ------
    ValueError
        If ``market_quotes`` is empty, ``s0 <= 0``, or any quote has a
        non-positive strike, non-positive tau, or negative price.

    Notes
    -----
    Heston calibration is an ill-posed inverse problem: the loss surface
    is non-convex with multiple local minima, and parameter recovery may be
    non-unique even for dense grids.  The returned parameters produce the
    best-fit model prices from the given starting point but may not be the
    globally optimal parameters.  Quality should be measured by the price
    RMSE, not by closeness of individual parameters to any true values.

    Mathematical references
    -----------------------
    Gatheral (2006), The Volatility Surface, Wiley Finance.
    """
    import scipy.optimize  # lazy import

    if not market_quotes:
        raise ValueError("market_quotes must be non-empty")
    if s0 <= 0.0:
        raise ValueError(f"s0 must be positive, got {s0}")
    for k_i, t_i, c_i in market_quotes:
        if k_i <= 0.0:
            raise ValueError(f"strike must be positive, got {k_i}")
        if t_i <= 0.0:
            raise ValueError(f"tau must be positive, got {t_i}")
        if c_i < 0.0:
            raise ValueError(f"market_call_price must be >= 0, got {c_i}")

    # Determine starting point
    if initial is not None:
        mu_fixed = float(initial.mu)
        p0_kappa = float(initial.kappa)
        p0_theta = float(initial.theta)
        p0_xi = float(initial.vol_of_vol)
        p0_rho = float(initial.rho)
        p0_v0 = float(initial.v0)
    else:
        mu_fixed = float(r)
        p0_kappa = 2.0
        p0_theta = 0.04
        p0_xi = 0.3
        p0_rho = -0.5
        p0_v0 = 0.04

    def _to_unconstrained(
        kappa: float, theta: float, xi: float, rho: float, v0: float
    ) -> list[float]:
        return [
            float(np.log(max(kappa, 1e-8))),
            float(np.log(max(theta, 1e-8))),
            float(np.log(max(xi, 1e-8))),
            float(np.arctanh(np.clip(rho, -0.999, 0.999))),
            float(np.log(max(v0 + 1e-8, 1e-12))),
        ]

    def _from_unconstrained(x: np.ndarray) -> HestonParams:
        kappa = float(np.exp(x[0]))
        theta = float(np.exp(x[1]))
        xi = float(np.exp(x[2]))
        rho = float(np.tanh(x[3]))
        v0 = float(max(np.exp(x[4]) - 1e-8, 0.0))
        return HestonParams(
            mu=mu_fixed, kappa=kappa, theta=theta, vol_of_vol=xi, rho=rho, v0=v0
        )

    x0 = _to_unconstrained(p0_kappa, p0_theta, p0_xi, p0_rho, p0_v0)

    def _objective(x: np.ndarray) -> float:
        p = _from_unconstrained(x)
        sse = 0.0
        for k_i, t_i, c_mkt in market_quotes:
            try:
                c_model = call_price(s0, k_i, t_i, p, r=r)
                sse += (c_model - c_mkt) ** 2
            except (ValueError, OverflowError, ZeroDivisionError):
                sse += 1e6  # pragma: no cover
        return float(sse)

    result = scipy.optimize.minimize(
        _objective,
        x0,
        method="Nelder-Mead",
        options={
            "maxiter": 5000,
            "xatol": 1e-7,
            "fatol": 1e-10,
            "adaptive": True,
        },
    )

    return _from_unconstrained(np.asarray(result.x))
