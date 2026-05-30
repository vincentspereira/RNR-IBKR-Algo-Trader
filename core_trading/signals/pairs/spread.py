"""Spread modelling for pairs trading (master plan Phase 4.2).

Provides static (OLS) and dynamic (Kalman filter) hedge-ratio estimation,
Ornstein-Uhlenbeck parameter fitting, spread construction, and z-score
normalisation.

Design notes
------------
* :class:`StaticHedge` and :class:`OUParams` are frozen dataclasses so they
  can be safely passed across threads and cached.
* :class:`KalmanHedge` implements the standard linear Kalman recursion with
  numpy only; no external Kalman-filter library is required at runtime.
* ``zscore`` supports three modes: rolling window (look-ahead-free), OU
  equilibrium (analytic), and full-sample.
* ``fit_ou`` delegates parameter estimation to
  :func:`core_trading.research.stat_tests.half_life` so that the OU fit is
  identical across the research and signal layers.

Mathematical references
-----------------------
OU process:  ds = kappa*(mu - s)*dt + sigma*dW
Equilibrium std: sigma_eq = sigma / sqrt(2*kappa)  (closed-form variance of
    the stationary distribution).
Kalman recursion: see Harvey (1990) "Forecasting, Structural Time Series
    Models and the Kalman Filter", Chapter 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "StaticHedge",
    "OUParams",
    "KalmanHedge",
    "static_hedge_ratio",
    "compute_spread",
    "fit_ou",
    "zscore",
]


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StaticHedge:
    """OLS-estimated static hedge ratio.

    The spread is defined as ``spread = y - (alpha + beta * x)``.

    Attributes
    ----------
    alpha:
        Intercept term from the OLS regression of y on x.
    beta:
        Slope (hedge ratio) from the OLS regression of y on x.
    """

    alpha: float
    beta: float


@dataclass(frozen=True, slots=True)
class OUParams:
    """Ornstein-Uhlenbeck parameter estimates for a spread series.

    The OU SDE is ``ds = kappa*(mu - s)*dt + sigma*dW``.

    Attributes
    ----------
    kappa:
        Mean-reversion speed (per period). Positive values indicate mean
        reversion.
    mu:
        Long-run mean of the spread.
    sigma:
        Instantaneous volatility (diffusion coefficient).
    half_life:
        Periods to revert half-way to ``mu``: ``ln(2) / kappa``.
        ``inf`` when the process is not mean-reverting.
    """

    kappa: float
    mu: float
    sigma: float
    half_life: float

    @property
    def is_mean_reverting(self) -> bool:
        """Return True when kappa > 0 and the half-life is finite."""
        return np.isfinite(self.half_life) and self.kappa > 0

    @property
    def sigma_eq(self) -> float:
        """Equilibrium (stationary) standard deviation: sigma / sqrt(2*kappa).

        Undefined (returns inf) when kappa <= 0.
        """
        if self.kappa <= 0:
            return float("inf")
        return float(self.sigma / np.sqrt(2.0 * self.kappa))


# ---------------------------------------------------------------------------
# Static hedge ratio
# ---------------------------------------------------------------------------


def static_hedge_ratio(y: pd.Series, x: pd.Series) -> StaticHedge:
    """Estimate a static (OLS) hedge ratio by regressing y on x.

    Uses numpy least-squares (``np.linalg.lstsq``) to fit
    ``y = alpha + beta * x + epsilon``.  The two series are aligned on their
    common index and rows with NaN are dropped before fitting.

    Parameters
    ----------
    y:
        Dependent price series (the leg to be hedged).
    x:
        Independent price series (the hedge instrument).

    Returns
    -------
    StaticHedge
        Fitted intercept and slope.
    """
    combined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if combined.shape[0] < 2:
        raise ValueError("static_hedge_ratio needs at least 2 overlapping observations")

    y_arr = combined["y"].to_numpy(dtype=float)
    x_arr = combined["x"].to_numpy(dtype=float)

    design = np.column_stack([np.ones_like(x_arr), x_arr])
    coef, *_ = np.linalg.lstsq(design, y_arr, rcond=None)
    return StaticHedge(alpha=float(coef[0]), beta=float(coef[1]))


# ---------------------------------------------------------------------------
# Spread construction
# ---------------------------------------------------------------------------


def compute_spread(
    y: pd.Series,
    x: pd.Series,
    hedge: StaticHedge | float,
) -> pd.Series:
    """Compute the residual spread series given a hedge ratio.

    ``spread_t = y_t - (alpha + beta * x_t)``

    If ``hedge`` is a plain float it is treated as beta with alpha=0.

    Parameters
    ----------
    y:
        Dependent price series.
    x:
        Independent price series.
    hedge:
        Either a :class:`StaticHedge` (intercept + slope) or a bare float
        (slope only, intercept=0).

    Returns
    -------
    pd.Series
        Spread series on the common index of y and x, NaNs dropped.
    """
    if isinstance(hedge, int | float):
        alpha = 0.0
        beta = float(hedge)
    else:
        alpha = hedge.alpha
        beta = hedge.beta

    combined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    spread = combined["y"] - (alpha + beta * combined["x"])
    spread.name = "spread"
    return spread


# ---------------------------------------------------------------------------
# OU parameter fitting
# ---------------------------------------------------------------------------


def fit_ou(spread: pd.Series) -> OUParams:
    """Fit Ornstein-Uhlenbeck parameters to a spread series.

    Delegates to :func:`core_trading.research.stat_tests.half_life`, which
    fits ``Delta(s_t) = a + b * s_{t-1} + eps`` by OLS.  The OU parameters
    are recovered as kappa = -b, mu = -a/b.

    Parameters
    ----------
    spread:
        Spread series (should be approximately stationary for meaningful
        results).

    Returns
    -------
    OUParams
        Fitted OU parameters including the implied half-life.
    """
    from core_trading.research.stat_tests import half_life as _half_life

    result = _half_life(spread.dropna())
    return OUParams(
        kappa=result.kappa,
        mu=result.mu,
        sigma=result.sigma,
        half_life=result.half_life,
    )


# ---------------------------------------------------------------------------
# Kalman filter (dynamic hedge ratio)
# ---------------------------------------------------------------------------


class KalmanHedge:
    """Dynamic (time-varying) hedge ratio via a linear Kalman filter.

    State vector ``theta_t = [alpha_t, beta_t]^T`` follows a random walk:

        theta_t = theta_{t-1} + eta_t,   eta_t ~ N(0, Q)

    Observation model:

        y_t = [1, x_t] * theta_t + eps_t,   eps_t ~ N(0, R)

    where ``Q = delta/(1-delta) * I_2`` and ``R = obs_cov``.  This is the
    standard univariate regression Kalman filter described in Avellaneda &
    Lee (2010, Section 3).

    Parameters
    ----------
    delta:
        State-transition noise scaler.  ``Q = delta/(1-delta) * I``.
        Smaller delta = slower adaptation (smoother beta track).
        Default 1e-4.
    obs_cov:
        Observation noise variance (``R``).  Default 1e-3.
    """

    def __init__(self, delta: float = 1e-4, obs_cov: float = 1e-3) -> None:
        if delta <= 0 or delta >= 1:
            raise ValueError("delta must be in (0, 1)")
        if obs_cov <= 0:
            raise ValueError("obs_cov must be positive")
        self._delta = delta
        self._obs_cov = obs_cov

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def filter(self, y: pd.Series, x: pd.Series) -> pd.DataFrame:
        """Run the Kalman filter and return time-varying hedge estimates.

        The estimate at time t uses data up to and including t (no
        look-ahead).  Both series are aligned on their common index and
        rows with NaN are dropped before filtering.

        Parameters
        ----------
        y:
            Dependent price series.
        x:
            Independent price series.

        Returns
        -------
        pd.DataFrame
            Columns ``["alpha", "beta"]`` indexed by timestamp.  One row per
            observation, aligned to the common index of y and x.
        """
        combined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
        if combined.shape[0] < 2:
            raise ValueError("KalmanHedge.filter needs at least 2 observations")

        y_arr = combined["y"].to_numpy(dtype=float)
        x_arr = combined["x"].to_numpy(dtype=float)
        n = len(y_arr)

        q = self._delta / (1.0 - self._delta)
        Q = q * np.eye(2)
        R = self._obs_cov

        # Initialise state with a diffuse prior
        theta = np.zeros(2)
        P = np.eye(2) * 1.0

        alphas = np.empty(n)
        betas = np.empty(n)

        for t in range(n):
            # Observation vector
            F = np.array([1.0, x_arr[t]])

            # Predict
            P_pred = P + Q

            # Innovation variance
            S = float(F @ P_pred @ F) + R
            # Kalman gain
            K = (P_pred @ F) / S
            # Innovation
            y_hat = float(F @ theta)
            innov = y_arr[t] - y_hat
            # Update state
            theta = theta + K * innov
            # Update covariance (Joseph form for numerical stability)
            KF = np.outer(K, F)
            P = (np.eye(2) - KF) @ P_pred

            alphas[t] = theta[0]
            betas[t] = theta[1]

        return pd.DataFrame(
            {"alpha": alphas, "beta": betas},
            index=combined.index,
        )

    def dynamic_spread(self, y: pd.Series, x: pd.Series) -> pd.Series:
        """Compute the dynamic spread using Kalman-filtered hedge estimates.

        ``spread_t = y_t - (alpha_t + beta_t * x_t)``

        Parameters
        ----------
        y:
            Dependent price series.
        x:
            Independent price series.

        Returns
        -------
        pd.Series
            Spread series on the common index of y and x.
        """
        hedge_df = self.filter(y, x)
        combined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
        spread = combined["y"] - (hedge_df["alpha"] + hedge_df["beta"] * combined["x"])
        spread.name = "kalman_spread"
        return spread


# ---------------------------------------------------------------------------
# Z-score
# ---------------------------------------------------------------------------


def zscore(
    spread: pd.Series,
    *,
    window: int | None = None,
    ou: OUParams | None = None,
) -> pd.Series:
    """Normalise a spread series to a z-score.

    Three modes (in precedence order):

    1. **Rolling window** (``window`` is given): trailing-window mean and
       standard deviation.  ``min_periods = window`` so early bars are NaN
       rather than noisy.  Look-ahead-free.
    2. **OU equilibrium** (``ou`` is given): ``z = (spread - mu) / sigma_eq``
       where ``sigma_eq = sigma / sqrt(2*kappa)`` is the analytic equilibrium
       standard deviation of the stationary OU distribution.
    3. **Full-sample**: ``z = (spread - mean) / std`` over the entire series.

    Parameters
    ----------
    spread:
        The spread series to normalise.
    window:
        Look-back window for rolling normalisation.  Must be >= 2 when
        provided.
    ou:
        Fitted OU parameters for analytic normalisation.

    Returns
    -------
    pd.Series
        Z-score series with the same index as ``spread``.
    """
    if window is not None:
        if window < 2:
            raise ValueError("window must be >= 2")
        roll = spread.rolling(window=window, min_periods=window)
        z = (spread - roll.mean()) / roll.std(ddof=1)
        z.name = "zscore"
        return z

    if ou is not None:
        sigma_eq = ou.sigma_eq
        if not np.isfinite(sigma_eq) or sigma_eq == 0:
            raise ValueError(
                "ou.sigma_eq is not finite or zero; process may not be mean-reverting"
            )
        z = (spread - ou.mu) / sigma_eq
        z.name = "zscore"
        return z

    # Full-sample z-score
    mu = spread.mean()
    std = spread.std(ddof=1)
    if std == 0 or not np.isfinite(std):
        raise ValueError("spread has zero or non-finite standard deviation")
    z = (spread - mu) / std
    z.name = "zscore"
    return z
