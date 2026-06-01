"""Merton jump-diffusion stochastic process module (Phase 5.B.2).

This module implements the Merton (1976) jump-diffusion model for asset prices.
Log-returns consist of a continuous GBM diffusion term plus a compound-Poisson
process whose jump sizes are lognormally distributed.  This captures the
non-Gaussian, fat-tailed return distributions observed in equity markets.

Mathematical references
-----------------------
Log-price SDE:

    d(log S) = (mu - 0.5 * sigma^2 - jump_intensity * (exp(jump_mean +
                0.5 * jump_std^2) - 1)) * dt
               + sigma * dW_t + sum_{i=1}^{N(dt)} Y_i

where:
    * N(dt) ~ Poisson(jump_intensity * dt) -- number of jumps in [t, t+dt]
    * Y_i ~ Normal(jump_mean, jump_std^2) -- log-size of each jump
    * W_t -- standard Brownian motion

Discrete log-return per step dt:

    r_t = (mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z
          + sum_{i=1}^{N_t} Y_i

where N_t ~ Poisson(jump_intensity * dt), Z ~ Normal(0,1) independent.

Merton return density (mixture of normals):

    f(r) = sum_{k=0}^{inf} [Pois(k; lambda*dt) *
           Normal(r; (mu - 0.5*sigma^2)*dt + k*jump_mean,
                     sigma^2*dt + k*jump_std^2)]

Moments implied by the model (dt=1 for simplicity):
    E[r]       = (mu - 0.5 * sigma^2) + jump_intensity * jump_mean
    Var[r]     = sigma^2 + jump_intensity * (jump_mean^2 + jump_std^2)
    Skew[r]    = jump_intensity * jump_mean * (3*jump_std^2 + jump_mean^2)
                 / Var[r]^(3/2)
    ExKurt[r]  = jump_intensity * (3*jump_std^4 + 6*jump_mean^2*jump_std^2
                                   + jump_mean^4) / Var[r]^2

Note on jump-parameter identifiability
---------------------------------------
Jump intensity (lambda), jump_mean, and jump_std are jointly weakly identified
from log-returns alone.  The MLE can converge to different (lambda, jump_mean,
jump_std) triplets that produce the same mixture-of-normals density.  The
standard practical recommendation (Honore 1998) is to:
  1. Fix a truncation max_jumps (default 10, sufficient when lambda * dt << 1).
  2. Initialize from method-of-moments on return variance/skew/kurtosis.
  3. Work in transformed space: optimize over (log(sigma), log(lambda + eps),
     log(jump_std)) to keep positivity constraints automatic.
  4. Validate fit by comparing model-implied moments to sample moments rather
     than demanding exact parameter recovery.

The fit_merton function follows all four recommendations.

    * Merton, R. C. (1976). "Option pricing when underlying stock returns are
      discontinuous." Journal of Financial Economics, 3(1-2), 125-144.
    * Honore, P. (1998). "Pitfalls in estimating jump-diffusion models."
      Working paper, Aarhus School of Business.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "MertonParams",
    "simulate",
    "fit_merton",
    "model_moments",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MertonParams:
    """Fitted parameters for a Merton jump-diffusion process.

    The model log-return per dt-step is:

        r = (mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * Z
            + sum_{i=1}^{N} Y_i

    where N ~ Poisson(jump_intensity * dt), Y_i ~ Normal(jump_mean, jump_std^2).

    Attributes
    ----------
    mu:
        Diffusion drift per unit time (arithmetic drift of the continuous part).
    sigma:
        Diffusion volatility per square-root of time (must be > 0).
    jump_intensity:
        Expected number of jumps per unit time (lambda >= 0).
    jump_mean:
        Mean of the Normal log-jump-size distribution.
    jump_std:
        Standard deviation of the log-jump-size distribution (must be >= 0).
    """

    mu: float
    sigma: float
    jump_intensity: float
    jump_mean: float
    jump_std: float

    @property
    def is_valid(self) -> bool:
        """Return True when sigma > 0 and jump_intensity >= 0 and jump_std >= 0."""
        return self.sigma > 0.0 and self.jump_intensity >= 0.0 and self.jump_std >= 0.0


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


def _log_returns(arr: np.ndarray) -> np.ndarray:
    """Compute log-returns from a price array."""
    return np.diff(np.log(arr))


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def simulate(
    n: int,
    dt: float,
    s0: float,
    params: MertonParams,
    seed: int | None = None,
) -> pd.Series:
    """Simulate a Merton jump-diffusion price path.

    Each step the log-return is:

        r_t = (mu - 0.5 * sigma^2) * dt
              + sigma * sqrt(dt) * Z
              + sum_{i=1}^{N_t} Y_i

    where:
        * Z ~ Normal(0,1) (diffusion shock)
        * N_t ~ Poisson(jump_intensity * dt) (number of jumps this step)
        * Y_i ~ Normal(jump_mean, jump_std^2) (individual jump log-sizes)

    When N_t = 0 the step is pure diffusion.  When N_t > 0 the compound jump
    contribution is Normal(N_t * jump_mean, N_t * jump_std^2).

    Parameters
    ----------
    n:
        Number of time steps (output length, including the initial value s0).
    dt:
        Time step in consistent units (e.g. 1.0 for daily, 1/252 for annual).
    s0:
        Initial price (must be > 0).
    params:
        MertonParams DTO with all model parameters.
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
        If n < 1, dt <= 0, s0 <= 0, sigma <= 0, or jump_intensity < 0.

    Mathematical references
    -----------------------
    Merton (1976); Cont & Tankov (2004) "Financial Modelling with Jump Processes".
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if dt <= 0.0:
        raise ValueError("dt must be positive")
    if s0 <= 0.0:
        raise ValueError("s0 must be positive")
    if params.sigma <= 0.0:
        raise ValueError("sigma must be positive")
    if params.jump_intensity < 0.0:
        raise ValueError("jump_intensity must be >= 0")

    rng = np.random.default_rng(seed)

    mu = params.mu
    sigma = params.sigma
    lam = params.jump_intensity
    jm = params.jump_mean
    js = params.jump_std

    log_drift = (mu - 0.5 * sigma * sigma) * dt
    diff_scale = sigma * float(np.sqrt(dt))
    lam_dt = lam * dt

    if n == 1:
        return pd.Series([s0], dtype=float)

    log_s = np.empty(n, dtype=float)
    log_s[0] = float(np.log(s0))

    # diffusion shocks for all steps at once
    z = rng.standard_normal(n - 1)
    # number of jumps per step
    n_jumps = rng.poisson(lam=lam_dt, size=n - 1)

    for t in range(n - 1):
        diffusion = log_drift + diff_scale * z[t]
        k = int(n_jumps[t])
        if k == 0:
            jump_total = 0.0
        elif js <= 0.0:
            # degenerate: zero jump std, all jumps are deterministic
            jump_total = float(k) * jm
        else:
            jump_total = float(rng.normal(loc=float(k) * jm,
                                          scale=js * float(np.sqrt(float(k)))))
        log_s[t + 1] = log_s[t] + diffusion + jump_total

    return pd.Series(np.exp(log_s), dtype=float)


# ---------------------------------------------------------------------------
# Model moments (for validation)
# ---------------------------------------------------------------------------


def model_moments(params: MertonParams, dt: float = 1.0) -> dict[str, float]:
    """Compute the first four central moments of the Merton log-return distribution.

    These are the theoretical moments of the log-return r per step dt:

        mean   = (mu - 0.5 * sigma^2) * dt + jump_intensity * dt * jump_mean
        var    = sigma^2 * dt + jump_intensity * dt * (jump_mean^2 + jump_std^2)
        skew   = jump contribution / var^(3/2)
        exkurt = jump contribution / var^2

    Parameters
    ----------
    params:
        MertonParams DTO.
    dt:
        Time step.  Default 1.0.

    Returns
    -------
    dict[str, float]
        Dictionary with keys ``mean``, ``var``, ``skew``, ``exkurt``.

    Mathematical references
    -----------------------
    Merton (1976) eq. (14); Cont & Tankov (2004) pp. 109-110.
    """
    mu = params.mu
    sigma = params.sigma
    lam = params.jump_intensity
    jm = params.jump_mean
    js = params.jump_std

    lam_dt = lam * dt
    m1 = (mu - 0.5 * sigma * sigma) * dt + lam_dt * jm
    v = sigma * sigma * dt + lam_dt * (jm * jm + js * js)
    v = max(v, 1e-16)  # guard against zero variance

    # Third cumulant of Poisson-lognormal
    c3 = lam_dt * jm * (3.0 * js * js + jm * jm)
    # Fourth cumulant
    c4 = lam_dt * (3.0 * js * js * js * js
                   + 6.0 * jm * jm * js * js
                   + jm * jm * jm * jm)

    skew = c3 / (v ** 1.5)
    exkurt = c4 / (v * v)

    return {
        "mean": float(m1),
        "var": float(v),
        "skew": float(skew),
        "exkurt": float(exkurt),
    }


# ---------------------------------------------------------------------------
# Fitting -- Merton MLE via Poisson-mixture of normals
# ---------------------------------------------------------------------------


def fit_merton(
    prices: pd.Series,
    dt: float = 1.0,
    *,
    max_jumps: int = 10,
) -> MertonParams:
    """Fit Merton jump-diffusion parameters via mixture-of-normals MLE.

    The log-return density under Merton is a Poisson-weighted mixture:

        f(r) = sum_{k=0}^{max_jumps} w_k * Normal(r; loc_k, var_k)

    where:
        w_k    = Pois(k; lambda * dt)
        loc_k  = (mu - 0.5 * sigma^2) * dt + k * jump_mean
        var_k  = sigma^2 * dt + k * jump_std^2

    The log-likelihood is maximized numerically via scipy.optimize.minimize
    with Nelder-Mead (gradient-free, robust to flat regions) after a
    method-of-moments initialization.

    Optimization is performed in transformed space to enforce positivity:
        theta[0] = mu             (unconstrained)
        theta[1] = log(sigma)     (sigma = exp(theta[1]) > 0)
        theta[2] = log(lambda + eps)   (lambda >= 0; eps=1e-6 floor)
        theta[3] = jump_mean      (unconstrained)
        theta[4] = log(jump_std + eps)  (jump_std >= 0; eps=1e-6 floor)

    Parameters
    ----------
    prices:
        Observed price series.  NaN / Inf are dropped.  All prices must be
        positive.
    dt:
        Time step between observations.  Default 1.0.
    max_jumps:
        Truncation of the Poisson sum.  Default 10 is sufficient when
        lambda * dt << 1.  Increase for very high jump intensities.

    Returns
    -------
    MertonParams
        Fitted parameter DTO.

    Raises
    ------
    ValueError
        If fewer than 10 finite prices remain after cleaning, any finite price
        is non-positive, or dt <= 0.

    Notes
    -----
    Jump parameters (jump_intensity, jump_mean, jump_std) are weakly identified
    from returns alone -- multiple (lambda, jump_mean, jump_std) triplets can
    produce nearly the same mixture density.  This is a fundamental identifiability
    limitation documented by Honore (1998).  Validate the fit using model_moments
    rather than expecting exact parameter recovery.

    Mathematical references
    -----------------------
    Merton (1976); Honore (1998).
    """
    import scipy.optimize  # lazy import  # noqa: I001
    import scipy.stats  # lazy import

    if dt <= 0.0:
        raise ValueError("dt must be positive")

    arr = _clean_positive_array(prices)
    if len(arr) < 10:
        raise ValueError(
            "fit_merton needs at least 10 finite, positive prices"
        )

    r = _log_returns(arr)
    # Poisson weights for k = 0 .. max_jumps
    ks = np.arange(max_jumps + 1, dtype=float)

    # ------------------------------------------------------------------
    # Method-of-moments initialization
    # ------------------------------------------------------------------
    r_mean = float(np.mean(r))
    r_var = float(np.var(r, ddof=1))
    r_skew = float(_safe_skew(r))
    r_kurt = float(_safe_exkurt(r))

    # Start with a mostly-diffusion guess: jump_intensity = 1/year,
    # small jumps contributing ~10% of variance.
    lam0 = 1.0
    js0 = float(np.sqrt(max(r_var * 0.10 / max(lam0 * dt, 1e-6), 1e-4)))
    jm0 = 0.0

    # If there is clear positive excess kurtosis, try to absorb it with jumps.
    if r_kurt > 0.5:
        # ExKurt ~ lambda * dt * kurt_contrib / var^2 => estimate lambda
        kurt_contrib = 3.0 * js0 ** 4
        lam0 = max(r_kurt * r_var * r_var / max(kurt_contrib * dt, 1e-8), 1e-2)
        lam0 = min(lam0, 50.0)  # cap to reasonable range

    # If strong skew, init jump_mean from skew (simplified moment-of-moments)
    if abs(r_skew) > 0.1:
        jm0 = (r_skew * (r_var ** 1.5) / max(3.0 * lam0 * dt * js0 * js0, 1e-8))
        jm0 = float(np.clip(jm0, -2.0, 2.0))

    # Diffusion vol: subtract jump contribution from total variance
    jump_var0 = lam0 * dt * (jm0 * jm0 + js0 * js0)
    sigma0 = float(np.sqrt(max(r_var - jump_var0, r_var * 0.1) / dt))
    sigma0 = max(sigma0, 1e-4)

    mu0 = r_mean / dt + 0.5 * sigma0 * sigma0

    _EPS = 1e-6  # positivity floor for log-transform

    def _pack(mu: float, sigma: float, lam: float,
              jm: float, js: float) -> np.ndarray:
        return np.array([
            mu,
            float(np.log(max(sigma, _EPS))),
            float(np.log(max(lam, _EPS))),
            jm,
            float(np.log(max(js, _EPS))),
        ])

    def _unpack(theta: np.ndarray) -> tuple[float, float, float, float, float]:
        mu = float(theta[0])
        sigma = float(np.exp(theta[1]))
        lam = float(np.exp(theta[2]))
        jm = float(theta[3])
        js = float(np.exp(theta[4]))
        return mu, sigma, lam, jm, js

    def _neg_log_lik(theta: np.ndarray) -> float:
        mu, sigma, lam, jm, js = _unpack(theta)
        lam_dt = lam * dt
        # Poisson weights
        log_pois = _log_poisson_weights(lam_dt, ks)  # shape (max_jumps+1,)
        # Mixture component means and variances
        loc_k = (mu - 0.5 * sigma * sigma) * dt + ks * jm   # (max_jumps+1,)
        var_k = sigma * sigma * dt + ks * (js * js)          # (max_jumps+1,)
        var_k = np.maximum(var_k, 1e-16)
        std_k = np.sqrt(var_k)
        # r has shape (n_obs,); broadcast against k dimension
        # log-density of each component: (n_obs, max_jumps+1)
        r_col = r[:, np.newaxis]        # (n_obs, 1)
        log_pois_row = log_pois[np.newaxis, :]   # (1, max_jumps+1)
        log_norm = (-0.5 * ((r_col - loc_k) / std_k) ** 2
                    - np.log(std_k)
                    - 0.5 * float(np.log(2.0 * np.pi)))   # (n_obs, max_jumps+1)
        # log-sum-exp over k for each observation
        log_w_plus_norm = log_pois_row + log_norm          # (n_obs, max_jumps+1)
        # stable logsumexp along k axis
        lse = _logsumexp(log_w_plus_norm, axis=1)          # (n_obs,)
        return float(-np.sum(lse))

    theta0 = _pack(mu0, sigma0, lam0, jm0, js0)

    result = scipy.optimize.minimize(
        _neg_log_lik,
        theta0,
        method="Nelder-Mead",
        options={"maxiter": 20000, "xatol": 1e-6, "fatol": 1e-6, "adaptive": True},
    )

    mu_f, sigma_f, lam_f, jm_f, js_f = _unpack(result.x)

    # Clamp to valid domain with small floor to avoid degenerate params
    sigma_f = max(sigma_f, 1e-8)
    lam_f = max(lam_f - _EPS, 0.0)  # undo the log-floor to allow true zero
    js_f = max(js_f - _EPS, 0.0)

    return MertonParams(
        mu=float(mu_f),
        sigma=float(sigma_f),
        jump_intensity=float(lam_f),
        jump_mean=float(jm_f),
        jump_std=float(js_f),
    )


# ---------------------------------------------------------------------------
# Private numerical utilities
# ---------------------------------------------------------------------------


def _log_poisson_weights(lam_dt: float, ks: np.ndarray) -> np.ndarray:
    """Compute log Poisson PMF values for k=0..max_jumps.

    Parameters
    ----------
    lam_dt:
        lambda * dt (Poisson rate).
    ks:
        Array of k values (0, 1, ..., max_jumps).

    Returns
    -------
    np.ndarray
        Log-PMF values, shape matching ks.
    """
    if lam_dt <= 0.0:
        # All mass on k=0
        out: np.ndarray = np.full(len(ks), -np.inf)
        out[0] = 0.0
        return out
    log_w: np.ndarray = np.asarray(
        ks * float(np.log(lam_dt)) - lam_dt - _log_factorial_array(ks),
        dtype=float,
    )
    return log_w


def _log_factorial_array(ks: np.ndarray) -> np.ndarray:
    """Compute log(k!) for each k in ks using gammaln."""
    # gammaln(k+1) = log(k!); scipy not guaranteed, use numpy-compatible approach
    # For small k (k <= max_jumps=10), direct computation is fine.
    result = np.zeros(len(ks))
    for i, k in enumerate(ks):
        ki = int(k)
        if ki <= 1:
            result[i] = 0.0
        else:
            result[i] = float(np.sum(np.log(np.arange(2, ki + 1, dtype=float))))
    return result


def _logsumexp(a: np.ndarray, axis: int) -> np.ndarray:
    """Numerically stable log-sum-exp along a given axis."""
    a_max = np.max(a, axis=axis, keepdims=True)
    # Replace -inf max (all-zero weight case) with 0 to avoid nan
    a_max_squeezed: np.ndarray = np.squeeze(a_max, axis=axis)
    finite_max: np.ndarray = np.isfinite(a_max_squeezed)
    log_sum: np.ndarray = np.log(np.sum(np.exp(a - a_max), axis=axis))
    out: np.ndarray = np.where(
        finite_max,
        log_sum + a_max_squeezed,
        a_max_squeezed,
    )
    return out


def _safe_skew(r: np.ndarray) -> float:
    """Sample skewness with guard against near-zero variance."""
    n = len(r)
    if n < 3:
        return 0.0
    m = float(np.mean(r))
    s = float(np.std(r, ddof=1))
    if s < 1e-14:
        return 0.0
    return float(np.mean(((r - m) / s) ** 3))


def _safe_exkurt(r: np.ndarray) -> float:
    """Sample excess kurtosis with guard against near-zero variance."""
    n = len(r)
    if n < 4:
        return 0.0
    m = float(np.mean(r))
    s = float(np.std(r, ddof=1))
    if s < 1e-14:
        return 0.0
    return float(np.mean(((r - m) / s) ** 4)) - 3.0
