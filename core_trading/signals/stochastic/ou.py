"""Ornstein-Uhlenbeck stochastic process -- general-purpose module (Phase 5.B.1).

This module is the canonical home for the OU process in the RNR-IBKR-Algo-Trader
codebase.  It provides simulation, OLS-regression-based fitting, and
closed-form maximum-likelihood fitting.

Relationship to core_trading.signals.pairs.spread
--------------------------------------------------
``core_trading.signals.pairs.spread`` contains a *pairs-specific* OU fit
(:func:`~core_trading.signals.pairs.spread.fit_ou`) that is tightly coupled to
spread-series construction and delegates to
:func:`core_trading.research.stat_tests.half_life` for the actual regression.
That module retains its own :class:`~core_trading.signals.pairs.spread.OUParams`
DTO (frozen dataclass, ``sigma_eq`` as a computed property rather than a stored
field) so that the pairs API is unchanged.

This module (Phase 5.B.1) is the *general-purpose* stochastic-process layer.
It defines its own :class:`OUParams` DTO that stores ``sigma_eq`` as a frozen
field alongside ``kappa``, ``mu``, ``sigma``, and ``half_life``.  Storing
``sigma_eq`` is the cleaner choice here because:
  1. Callers that need the equilibrium std do not have to recompute it.
  2. The field can be set once by :func:`fit_ou_mle` / :func:`fit_ou_ols` with
     full numeric precision (no repeated float division).
  3. There is no mutable state -- the dataclass is frozen -- so the stored value
     is always consistent with the other fields at construction time.

The pairs module is not imported from here; both coexist without circular
dependencies.

Mathematical references
-----------------------
OU SDE:  dx = kappa*(mu - x)*dt + sigma*dW_t
    * Uhlenbeck, G. E. & Ornstein, L. S. (1930).  "On the theory of the
      Brownian motion."  Physical Review, 36(5), 823-841.

Exact discrete transition (dt-step):
    x_{t+1} = x_t * exp(-kappa*dt)
             + mu * (1 - exp(-kappa*dt))
             + eps_t
    where eps_t ~ Normal(0, step_var),
    step_var = sigma^2 * (1 - exp(-2*kappa*dt)) / (2*kappa).

Stationary distribution:  X ~ Normal(mu, sigma_eq^2)
    where sigma_eq = sigma / sqrt(2*kappa).
    half_life = ln(2) / kappa.

OLS / AR(1) discretisation estimator (fit_ou_ols):
    Regress x_{t+1} on (1, x_t):
        x_{t+1} = c + phi*x_t + eps
    kappa = -ln(phi) / dt
    mu    = c / (1 - phi)
    sigma recovered from residual std and exact step-variance formula.

Closed-form MLE estimator for the exact OU discretisation (fit_ou_mle):
    Bias-corrected maximum-likelihood estimators from Ohlson (1977) /
    Singer (1993), commonly called the "exact OU MLE":
        Sx  = sum x_{t-1}
        Sy  = sum x_t
        Sxx = sum x_{t-1}^2
        Sxy = sum x_{t-1}*x_t
        Syy = sum x_t^2
    mu_hat  = (Sy*Sxx - Sx*Sxy) / (n*(Sxx - Sxy) - (Sx^2 - Sx*Sy))   [approx]
    phi_hat = (Sxy - mu_hat*(Sx + Sy) + n*mu_hat^2) /
              (Sxx - 2*mu_hat*Sx + n*mu_hat^2)
    kappa   = -ln(phi_hat) / dt
    sigma^2 from the MLE residual variance via the step-variance formula.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "OUParams",
    "simulate",
    "fit_ou_ols",
    "fit_ou_mle",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OUParams:
    """Fitted parameters for an Ornstein-Uhlenbeck process.

    The OU SDE is: dx = kappa*(mu - x)*dt + sigma*dW_t

    Attributes
    ----------
    kappa:
        Mean-reversion speed (per unit time, positive for mean-reverting).
    mu:
        Long-run (stationary) mean of the process.
    sigma:
        Instantaneous diffusion coefficient (volatility).
    half_life:
        Time for the gap to the mean to halve: ``ln(2) / kappa``.
        ``inf`` when kappa <= 0 (non-mean-reverting).
    sigma_eq:
        Equilibrium (stationary) standard deviation of the process:
        ``sigma / sqrt(2 * kappa)``.  ``inf`` when kappa <= 0.

    Notes
    -----
    All five fields are stored in the frozen dataclass.  ``sigma_eq`` and
    ``half_life`` are derived quantities that are computed once at
    construction time by the factory functions :func:`fit_ou_ols` and
    :func:`fit_ou_mle` (or :func:`_make_params`).  Storing them avoids
    repeated recomputation and ensures consistency.
    """

    kappa: float
    mu: float
    sigma: float
    half_life: float
    sigma_eq: float

    @property
    def is_mean_reverting(self) -> bool:
        """Return True when kappa > 0 and the half-life is finite."""
        return self.kappa > 0 and np.isfinite(self.half_life)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_params(kappa: float, mu: float, sigma: float) -> OUParams:
    """Construct an OUParams with analytically derived half_life and sigma_eq.

    Parameters
    ----------
    kappa:
        Mean-reversion speed.
    mu:
        Long-run mean.
    sigma:
        Instantaneous diffusion coefficient (must be >= 0).

    Returns
    -------
    OUParams
        Frozen DTO with all five fields populated.
    """
    if kappa > 0:
        hl = float(np.log(2.0) / kappa)
        seq = float(sigma / np.sqrt(2.0 * kappa))
    else:
        hl = float("inf")
        seq = float("inf")
    return OUParams(kappa=float(kappa), mu=float(mu), sigma=float(sigma),
                    half_life=hl, sigma_eq=seq)


def _clean_array(series: pd.Series) -> np.ndarray:
    """Drop NaN/Inf and return a contiguous 1-D float64 array."""
    arr = series.to_numpy(dtype=float)
    finite_mask = np.isfinite(arr)
    return np.ascontiguousarray(arr[finite_mask])


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def simulate(
    n: int,
    dt: float,
    x0: float,
    kappa: float,
    mu: float,
    sigma: float,
    seed: int | None = None,
) -> pd.Series:
    """Simulate an Ornstein-Uhlenbeck path using the exact discrete transition.

    The exact transition (not Euler-Maruyama) is:

        x_{t+1} = x_t * exp(-kappa*dt)
                 + mu * (1 - exp(-kappa*dt))
                 + eps_t

    where eps_t ~ Normal(0, step_var) and::

        step_var = sigma^2 * (1 - exp(-2*kappa*dt)) / (2*kappa)

    This is the variance of the conditional distribution of x_{t+1} given x_t
    for the continuous OU process, so the simulation is exact (no discretisation
    error) for any dt.

    Parameters
    ----------
    n:
        Number of time steps (output length).
    dt:
        Time step in consistent units (e.g. 1.0 for daily, 1/252 for annual).
    x0:
        Initial value of the process.
    kappa:
        Mean-reversion speed (must be > 0).
    mu:
        Long-run mean.
    sigma:
        Instantaneous diffusion coefficient (must be > 0).
    seed:
        Integer seed for the numpy Generator.  Pass ``None`` for a random seed.
        The same seed always produces the same path (deterministic).

    Returns
    -------
    pd.Series
        Simulated path of length ``n`` indexed 0..n-1.

    Raises
    ------
    ValueError
        If n < 1, dt <= 0, kappa <= 0, or sigma <= 0.

    Mathematical references
    -----------------------
    Uhlenbeck & Ornstein (1930); standard OU MLE discretisation.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if kappa <= 0.0:
        raise ValueError("kappa must be positive for a mean-reverting simulation")
    if sigma <= 0.0:
        raise ValueError("sigma must be positive")

    rng = np.random.default_rng(seed)

    exp_neg = float(np.exp(-kappa * dt))
    drift_const = mu * (1.0 - exp_neg)
    step_var = sigma ** 2 * (1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa)
    step_std = float(np.sqrt(step_var))

    path = np.empty(n, dtype=float)
    path[0] = x0
    if n > 1:
        noise = rng.normal(loc=0.0, scale=step_std, size=n - 1)
        for t in range(1, n):
            path[t] = path[t - 1] * exp_neg + drift_const + noise[t - 1]

    return pd.Series(path, dtype=float)


# ---------------------------------------------------------------------------
# Fitting -- OLS / AR(1) discretisation
# ---------------------------------------------------------------------------


def fit_ou_ols(series: pd.Series, dt: float = 1.0) -> OUParams:
    """Fit OU parameters via the AR(1) regression (OLS) discretisation.

    Regresses x_{t+1} on (1, x_t):

        x_{t+1} = c + phi * x_t + eps

    Back-transformation:
        kappa = -ln(phi) / dt
        mu    = c / (1 - phi)
        sigma recovered from the residual variance and the step-variance formula.

    Parameters
    ----------
    series:
        Observed path.  NaN / Inf are dropped before fitting.
    dt:
        Time step in the same units used for ``kappa``.  Default 1.0.

    Returns
    -------
    OUParams
        Fitted parameters.

    Raises
    ------
    ValueError
        If fewer than 3 finite observations remain after cleaning.

    Notes
    -----
    When the fitted ``phi >= 1`` (non-mean-reverting) ``kappa`` is set to a
    small positive floor (1e-8) so that ``half_life`` is large but finite,
    preventing division-by-zero downstream.  Callers should check
    :attr:`OUParams.is_mean_reverting`.

    Mathematical references
    -----------------------
    Uhlenbeck & Ornstein (1930); standard OU MLE discretisation.
    """
    if dt <= 0.0:
        raise ValueError("dt must be positive")

    arr = _clean_array(series)
    n = len(arr) - 1  # number of (x_t, x_{t+1}) pairs
    if n < 2:
        raise ValueError("fit_ou_ols needs at least 3 finite observations")

    x_lag = arr[:-1]   # x_t
    x_fwd = arr[1:]    # x_{t+1}

    # OLS: x_{t+1} = c + phi * x_t
    design = np.column_stack([np.ones(n), x_lag])
    coef, *_ = np.linalg.lstsq(design, x_fwd, rcond=None)
    c, phi = float(coef[0]), float(coef[1])

    # Recover OU parameters
    if phi <= 0.0:
        # Strongly mean-reverting or pathological; clamp phi to small positive
        phi = 1e-10

    if phi >= 1.0:
        # Non-mean-reverting: set kappa to floor to keep half_life finite
        kappa = 1e-8
        mu = float(arr.mean())
    else:
        kappa = float(-np.log(phi) / dt)
        mu = float(c / (1.0 - phi))

    # Recover sigma from OLS residual variance via exact step-variance formula
    resid = x_fwd - (c + phi * x_lag)
    resid_var = float(np.dot(resid, resid) / max(n - 2, 1))
    # step_var = sigma^2 * (1 - exp(-2*kappa*dt)) / (2*kappa)
    # => sigma^2 = resid_var * 2*kappa / (1 - exp(-2*kappa*dt))
    step_factor = (1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa)
    if step_factor <= 0.0:
        sigma = float(np.sqrt(max(resid_var, 0.0)))
    else:
        sigma = float(np.sqrt(max(resid_var / step_factor, 0.0)))

    return _make_params(kappa, mu, sigma)


# ---------------------------------------------------------------------------
# Fitting -- closed-form MLE
# ---------------------------------------------------------------------------


def fit_ou_mle(series: pd.Series, dt: float = 1.0) -> OUParams:
    """Fit OU parameters via the closed-form exact-discretisation MLE.

    Uses the analytically-derived MLE estimators for the exact OU transition
    (not Euler-Maruyama).  These are sometimes called "exact OU MLE" and
    provide lower bias than OLS for short time series or large dt.

    The estimators are (with sums over i = 1 ... n, pairing x_{i-1} and x_i):

        Sx  = sum x_{i-1}
        Sy  = sum x_i
        Sxx = sum x_{i-1}^2
        Sxy = sum x_{i-1} * x_i
        Syy = sum x_i^2

        mu_hat  = (Sy * Sxx - Sx * Sxy)
                  / (n*(Sxx - Sxy) - (Sx^2 - Sx*Sy))

        phi_hat = (Sxy - mu_hat*(Sx + Sy) + n*mu_hat^2)
                  / (Sxx - 2*mu_hat*Sx + n*mu_hat^2)

        kappa = -ln(phi_hat) / dt

        sigma^2 = MLE residual variance / step_factor,
                  step_factor = (1 - exp(-2*kappa*dt)) / (2*kappa)

    Parameters
    ----------
    series:
        Observed path.  NaN / Inf are dropped before fitting.
    dt:
        Time step in the same units used for ``kappa``.  Default 1.0.

    Returns
    -------
    OUParams
        Fitted parameters.

    Raises
    ------
    ValueError
        If fewer than 3 finite observations remain after cleaning.

    Notes
    -----
    When ``phi_hat >= 1`` (non-mean-reverting), ``kappa`` is floored to 1e-8
    so downstream callers receive a large-but-finite ``half_life``.  Check
    :attr:`OUParams.is_mean_reverting` to detect this case.

    Mathematical references
    -----------------------
    Uhlenbeck & Ornstein (1930); Ohlson (1977) "Risk and the rate of return
    on financial assets"; Singer (1993) "Continuous-time dynamical systems
    with sampled data" -- closed-form OU MLE.
    """
    if dt <= 0.0:
        raise ValueError("dt must be positive")

    arr = _clean_array(series)
    n = len(arr) - 1  # number of observation pairs
    if n < 2:
        raise ValueError("fit_ou_mle needs at least 3 finite observations")

    x_lag = arr[:-1]   # x_{t-1}
    x_fwd = arr[1:]    # x_t

    # Sufficient statistics
    sx = float(x_lag.sum())
    sy = float(x_fwd.sum())
    sxx = float(np.dot(x_lag, x_lag))
    sxy = float(np.dot(x_lag, x_fwd))

    # MLE mu estimator -- denominator may be near zero for a random walk
    denom_mu = float(n) * (sxx - sxy) - (sx * sx - sx * sy)
    if abs(denom_mu) < 1e-14 * max(abs(sxx), 1.0):
        # Numerically degenerate (near random-walk): fall back to sample mean
        mu = float(arr.mean())
    else:
        numer_mu = sy * sxx - sx * sxy
        mu = float(numer_mu / denom_mu)

    # MLE phi (AR coefficient) estimator
    numer_phi = sxy - mu * (sx + sy) + float(n) * mu * mu
    denom_phi = sxx - 2.0 * mu * sx + float(n) * mu * mu
    phi = (
        1.0
        if abs(denom_phi) < 1e-14 * max(abs(sxx), 1.0)
        else float(numer_phi / denom_phi)
    )

    if phi <= 0.0:
        phi = 1e-10

    if phi >= 1.0:
        kappa = 1e-8
        mu = float(arr.mean())
    else:
        kappa = float(-np.log(phi) / dt)

    # Recover sigma from MLE residuals
    exp_neg = np.exp(-kappa * dt)
    drift_const = mu * (1.0 - exp_neg)
    resid = x_fwd - (x_lag * exp_neg + drift_const)
    resid_var = float(np.dot(resid, resid) / max(n, 1))
    step_factor = (1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa)
    if step_factor <= 0.0:
        sigma = float(np.sqrt(max(resid_var, 0.0)))
    else:
        sigma = float(np.sqrt(max(resid_var / step_factor, 0.0)))

    return _make_params(kappa, mu, sigma)
