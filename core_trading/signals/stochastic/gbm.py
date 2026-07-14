"""Geometric Brownian Motion stochastic process module (Phase 5.B.4).

This module is the canonical GBM baseline for the RNR-IBKR-Algo-Trader codebase.
It provides simulation, MLE-based fitting, and an optional log-likelihood
helper.  GBM is the standard continuous-time model for asset prices used in
the Black-Scholes framework; the lognormal step is computed exactly (no
Euler-Maruyama discretisation error).

Mathematical references
-----------------------
GBM SDE:  dS = mu * S * dt + sigma * S * dW_t

Exact lognormal transition (dt-step):

    S_{t+1} = S_t * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)

where Z ~ Normal(0, 1).  The exponent is the log-return:

    r_t = log(S_{t+1} / S_t) ~ Normal((mu - 0.5 * sigma^2) * dt, sigma^2 * dt)

MLE estimators from log-returns r_1, ..., r_{n-1}:

    sigma_hat = std(r) / sqrt(dt)
    mu_hat    = mean(r) / dt + 0.5 * sigma_hat^2

The mu correction (+0.5 * sigma_hat^2) converts the log-return mean to the
arithmetic drift of the SDE (Ito correction).

Expected log-price (useful for testing):

    E[log(S_t / S_0)] = (mu - 0.5 * sigma^2) * t

    * Black, F. & Scholes, M. (1973). "The pricing of options and corporate
      liabilities." Journal of Political Economy, 81(3), 637-654.
    * Hull, J. C. (2022). Options, Futures, and Other Derivatives (11th ed.).
      Pearson.  Chapter 15: lognormal property of stock prices.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "GBMParams",
    "simulate",
    "fit_gbm",
    "log_likelihood",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GBMParams:
    """Fitted parameters for a Geometric Brownian Motion process.

    The GBM SDE is: dS = mu * S * dt + sigma * S * dW_t

    Attributes
    ----------
    mu:
        Arithmetic drift per unit time (the SDE drift, not the log-return
        mean -- they differ by 0.5 * sigma^2 via the Ito correction).
    sigma:
        Diffusion coefficient (volatility per square-root of time).

    Notes
    -----
    The log-return mean is ``(mu - 0.5 * sigma^2) * dt``.
    The log-return std is ``sigma * sqrt(dt)``.
    """

    mu: float
    sigma: float

    @property
    def is_valid(self) -> bool:
        """Return True when sigma > 0 (a proper diffusion process)."""
        return self.sigma > 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_positive_array(series: pd.Series) -> np.ndarray:
    """Drop NaN/Inf, require all values to be positive, return float64 array.

    Parameters
    ----------
    series:
        Input price series.

    Returns
    -------
    np.ndarray
        Contiguous 1-D float64 array of finite, positive values.

    Raises
    ------
    ValueError
        If any finite value is <= 0.
    """
    arr = series.to_numpy(dtype=float)
    finite_mask = np.isfinite(arr)
    arr = np.ascontiguousarray(arr[finite_mask])
    if arr.size > 0 and np.any(arr <= 0.0):
        raise ValueError("All prices must be positive; found non-positive values.")
    return arr


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def simulate(
    n: int,
    dt: float,
    s0: float,
    mu: float,
    sigma: float,
    seed: int | None = None,
) -> pd.Series:
    """Simulate a Geometric Brownian Motion price path using the exact lognormal step.

    The exact transition (not Euler-Maruyama) is:

        S_{t+1} = S_t * exp((mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z)

    where Z ~ Normal(0, 1).  This is exact for any dt.

    Parameters
    ----------
    n:
        Number of time steps (output length, including the initial value s0).
    dt:
        Time step in consistent units (e.g. 1.0 for daily, 1/252 for annual).
    s0:
        Initial price (must be > 0).
    mu:
        Arithmetic drift per unit time.
    sigma:
        Diffusion coefficient (volatility per sqrt of time, must be > 0).
    seed:
        Integer seed for the numpy Generator.  Pass ``None`` for a random seed.
        The same seed always produces the same path (deterministic).

    Returns
    -------
    pd.Series
        Simulated price path of length ``n`` indexed 0..n-1.

    Raises
    ------
    ValueError
        If n < 1, dt <= 0, s0 <= 0, or sigma <= 0.

    Mathematical references
    -----------------------
    Black & Scholes (1973); Hull (2022) Chapter 15.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if s0 <= 0.0:
        raise ValueError("s0 must be positive")
    if sigma <= 0.0:
        raise ValueError("sigma must be positive")

    rng = np.random.default_rng(seed)

    log_drift = (mu - 0.5 * sigma * sigma) * dt
    log_diffusion = sigma * float(np.sqrt(dt))

    path = np.empty(n, dtype=float)
    path[0] = s0
    if n > 1:
        z = rng.standard_normal(n - 1)
        log_returns = log_drift + log_diffusion * z
        # cumulative product via cumsum in log space
        log_path = np.empty(n, dtype=float)
        log_path[0] = float(np.log(s0))
        log_path[1:] = float(np.log(s0)) + np.cumsum(log_returns)
        path = np.exp(log_path)

    return pd.Series(path, dtype=float)


# ---------------------------------------------------------------------------
# Fitting -- MLE from log-returns
# ---------------------------------------------------------------------------


def fit_gbm(prices: pd.Series, dt: float = 1.0) -> GBMParams:
    """Fit GBM parameters via MLE from observed log-returns.

    Given a price series, the log-returns are:

        r_t = log(S_{t+1} / S_t)

    Under GBM, r_t ~ Normal((mu - 0.5 * sigma^2) * dt, sigma^2 * dt).

    The MLE estimators are:

        sigma_hat = std(r) / sqrt(dt)
        mu_hat    = mean(r) / dt + 0.5 * sigma_hat^2

    where std uses the bias-corrected (ddof=1) sample standard deviation.

    Parameters
    ----------
    prices:
        Observed price series.  NaN / Inf are dropped.  All prices must be
        positive.
    dt:
        Time step between observations in consistent units.  Default 1.0.

    Returns
    -------
    GBMParams
        Fitted parameters with the arithmetic drift (mu) and volatility (sigma).

    Raises
    ------
    ValueError
        If fewer than 3 finite prices remain after cleaning, or any finite
        price is non-positive, or dt <= 0.

    Notes
    -----
    Drift (mu) is notoriously hard to estimate precisely from finite samples --
    its standard error scales as sigma / sqrt(T) where T is total time.  With
    daily data over one year the 95% confidence interval for mu spans roughly
    +/- 30 % * sigma.  Tests that check mu recovery must use wide tolerances or
    very long series (N >= 20 000).

    Mathematical references
    -----------------------
    Black & Scholes (1973); Hull (2022) Chapter 15.
    """
    if dt <= 0.0:
        raise ValueError("dt must be positive")

    arr = _clean_positive_array(prices)
    if len(arr) < 3:
        raise ValueError("fit_gbm needs at least 3 finite, positive prices")

    log_ret = np.diff(np.log(arr))
    # sample mean and std of log-returns (ddof=1 for unbiased std)
    mean_r = float(np.mean(log_ret))
    std_r = float(np.std(log_ret, ddof=1))

    sqrt_dt = float(np.sqrt(dt))
    sigma_hat = std_r / sqrt_dt
    mu_hat = mean_r / dt + 0.5 * sigma_hat * sigma_hat

    return GBMParams(mu=float(mu_hat), sigma=float(sigma_hat))


# ---------------------------------------------------------------------------
# Log-likelihood helper
# ---------------------------------------------------------------------------


def log_likelihood(prices: pd.Series, params: GBMParams, dt: float = 1.0) -> float:
    """Compute the GBM log-likelihood for a price series.

    The log-returns r_t = log(S_{t+1} / S_t) are assumed i.i.d.:

        r_t ~ Normal((mu - 0.5 * sigma^2) * dt, sigma^2 * dt)

    Parameters
    ----------
    prices:
        Observed price series.  NaN / Inf are dropped.  All prices must be
        positive.
    params:
        GBM parameters (mu, sigma).
    dt:
        Time step between observations.  Default 1.0.

    Returns
    -------
    float
        Total log-likelihood (sum of log-densities over all log-returns).

    Raises
    ------
    ValueError
        If fewer than 3 finite prices remain, any non-positive price, or dt <= 0.

    Mathematical references
    -----------------------
    Black & Scholes (1973); Hull (2022) Chapter 15.
    """
    import scipy.stats  # lazy import -- scipy may not be present at module load

    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if params.sigma <= 0.0:
        raise ValueError("sigma must be positive")

    arr = _clean_positive_array(prices)
    if len(arr) < 3:
        raise ValueError("log_likelihood needs at least 3 finite, positive prices")

    log_ret = np.diff(np.log(arr))
    loc = (params.mu - 0.5 * params.sigma * params.sigma) * dt
    scale = params.sigma * float(np.sqrt(dt))
    return float(np.sum(scipy.stats.norm.logpdf(log_ret, loc=loc, scale=scale)))
