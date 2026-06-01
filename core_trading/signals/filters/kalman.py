"""Linear Gaussian Kalman filter and RTS smoother (master plan Phase 5.A.2).

Implements a standard discrete-time linear Gaussian state-space model in pure
numpy (no filterpy dependency).  The module is self-contained: importing it
requires only numpy and pandas; the optional filterpy library is used ONLY in
the test suite for numerical validation.

The linear Gaussian state-space model is:

    State transition:    x_t = F * x_{t-1} + w_t,   w_t ~ N(0, Q)
    Observation:         z_t = H * x_t + v_t,        v_t ~ N(0, R)

where:
    x_t is the hidden state vector (n x 1)
    z_t is the observation vector (m x 1)
    F   is the transition matrix (n x n)
    H   is the observation matrix (m x n)
    Q   is the process noise covariance (n x n)
    R   is the observation noise covariance (m x m)

The forward (filtering) pass produces the Kalman filter estimates.
The backward (smoothing) pass implements the Rauch-Tung-Striebel (RTS)
algorithm to produce smoothed state estimates using all observations.

The module also provides :func:`time_varying_beta`, a financial application
that estimates a time-varying dynamic hedge ratio (alpha_t, beta_t) between
two return series using a random-walk state model -- the classic approach for
pairs-trading spread estimation.

Design notes
------------
* :class:`KalmanResult` is a frozen slotted dataclass.
* :class:`KalmanFilter` is stateful; the system matrices are set at
  construction and are not mutated.
* Missing observations (NaN) are handled by skipping the update step for
  that time step, leaving the predicted distribution as the filtered estimate.
* All ``float(...)`` coercions prevent mypy ``warn_return_any`` violations from
  numpy scalar returns.

Mathematical references
-----------------------
Kalman (1960) original filter:
    Kalman, R.E. (1960). "A new approach to linear filtering and prediction
    problems." Transactions of the ASME--Journal of Basic Engineering,
    82(Series D), 35-45.

Rauch-Tung-Striebel (RTS) smoother:
    Rauch, H.E., Tung, F., and Striebel, C.T. (1965). "Maximum likelihood
    estimates of linear dynamic systems." AIAA Journal, 3(8), 1445-1450.

Harvey (1989) structural time series:
    Harvey, A.C. (1989). "Forecasting, Structural Time Series Models and the
    Kalman Filter." Cambridge University Press.

West and Harrison (1997) discount / time-varying regression:
    West, M. and Harrison, J. (1997). "Bayesian Forecasting and Dynamic
    Models." 2nd ed. Springer.  Chapter 6 (discount-factor process covariance).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "KalmanResult",
    "KalmanFilter",
    "time_varying_beta",
]

# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KalmanResult:
    """Output of a forward Kalman filter pass.

    All arrays use a time-first (T, ...) layout.

    Attributes
    ----------
    filtered_state_means:
        Posterior state estimates after each observation,
        shape (T, n).
    filtered_state_covariances:
        Posterior state covariance matrices, shape (T, n, n).
    predicted_state_means:
        One-step-ahead prior state estimates (before the update step),
        shape (T, n).
    predicted_state_covariances:
        One-step-ahead prior state covariance matrices, shape (T, n, n).
    log_likelihood:
        Total Gaussian log-likelihood of the observation sequence under
        the model, summed over all non-missing time steps.

    Notes
    -----
    The predicted arrays at index t correspond to E[x_t | z_1,...,z_{t-1}].
    The filtered arrays at index t correspond to E[x_t | z_1,...,z_t].
    """

    filtered_state_means: np.ndarray
    filtered_state_covariances: np.ndarray
    predicted_state_means: np.ndarray
    predicted_state_covariances: np.ndarray
    log_likelihood: float


# ---------------------------------------------------------------------------
# Main filter class
# ---------------------------------------------------------------------------


class KalmanFilter:
    """Discrete-time linear Gaussian Kalman filter with RTS smoother.

    Parameters
    ----------
    transition_matrix:
        State transition matrix F, shape (n, n).
    observation_matrix:
        Observation (emission) matrix H, shape (m, n).
    process_covariance:
        Process noise covariance Q, shape (n, n).
    observation_covariance:
        Observation noise covariance R, shape (m, m).
    initial_state_mean:
        Prior mean of the state at t=0, shape (n,).
    initial_state_covariance:
        Prior covariance of the state at t=0, shape (n, n).

    Examples
    --------
    Fit a local-level model to a noisy signal::

        import numpy as np
        from core_trading.signals.filters import KalmanFilter

        kf = KalmanFilter(
            transition_matrix=np.eye(1),
            observation_matrix=np.eye(1),
            process_covariance=np.array([[0.01]]),
            observation_covariance=np.array([[1.0]]),
            initial_state_mean=np.array([0.0]),
            initial_state_covariance=np.eye(1),
        )
        obs = np.random.default_rng(0).normal(size=(200, 1))
        result = kf.filter(obs)

    Time-varying hedge ratio::

        from core_trading.signals.filters import time_varying_beta
        df = time_varying_beta(y_series, x_series)
        # df has columns 'alpha' and 'beta'
    """

    def __init__(
        self,
        transition_matrix: np.ndarray,
        observation_matrix: np.ndarray,
        process_covariance: np.ndarray,
        observation_covariance: np.ndarray,
        initial_state_mean: np.ndarray,
        initial_state_covariance: np.ndarray,
    ) -> None:
        self._F = np.asarray(transition_matrix, dtype=float)
        self._H = np.asarray(observation_matrix, dtype=float)
        self._Q = np.asarray(process_covariance, dtype=float)
        self._R = np.asarray(observation_covariance, dtype=float)
        self._x0 = np.asarray(initial_state_mean, dtype=float).flatten()
        self._P0 = np.asarray(initial_state_covariance, dtype=float)

        n = self._F.shape[0]
        m = self._H.shape[0]
        self._n = n
        self._m = m

        # Validate shapes
        if self._F.shape != (n, n):
            raise ValueError(
                f"transition_matrix must be square (n x n), got {self._F.shape}"
            )
        if self._H.shape != (m, n):
            raise ValueError(
                f"observation_matrix must be (m x n), got {self._H.shape}"
            )
        if self._Q.shape != (n, n):
            raise ValueError(
                f"process_covariance must be (n x n), got {self._Q.shape}"
            )
        if self._R.shape != (m, m):
            raise ValueError(
                f"observation_covariance must be (m x m), got {self._R.shape}"
            )
        if self._x0.shape != (n,):
            raise ValueError(
                f"initial_state_mean must be length n={n}, got {self._x0.shape}"
            )
        if self._P0.shape != (n, n):
            raise ValueError(
                f"initial_state_covariance must be (n x n), got {self._P0.shape}"
            )

    # ------------------------------------------------------------------
    # Properties exposing system matrices (read-only views)
    # ------------------------------------------------------------------

    @property
    def n_states(self) -> int:
        """Dimension of the hidden state vector."""
        return self._n

    @property
    def n_obs(self) -> int:
        """Dimension of the observation vector."""
        return self._m

    # ------------------------------------------------------------------
    # Single-step primitives
    # ------------------------------------------------------------------

    def predict(
        self,
        state_mean: np.ndarray,
        state_cov: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Kalman predict step: propagate the state one time step forward.

        Computes:
            x_pred = F * x
            P_pred = F * P * F^T + Q

        Parameters
        ----------
        state_mean:
            Current posterior state mean, shape (n,).
        state_cov:
            Current posterior state covariance, shape (n, n).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            (predicted_mean, predicted_cov), both of shape (n,) and (n, n).
        """
        x_pred: np.ndarray = self._F @ state_mean
        P_pred: np.ndarray = self._F @ state_cov @ self._F.T + self._Q
        return x_pred, P_pred

    def update(
        self,
        state_mean: np.ndarray,
        state_cov: np.ndarray,
        observation: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        """Kalman update step: incorporate a new observation.

        Computes the innovation, Kalman gain, posterior state, and
        the Gaussian log-likelihood contribution of this observation.

        Innovation:
            y = z - H * x_pred
        Innovation covariance:
            S = H * P_pred * H^T + R
        Kalman gain:
            K = P_pred * H^T * S^{-1}
        Posterior:
            x = x_pred + K * y
            P = (I - K * H) * P_pred

        Parameters
        ----------
        state_mean:
            Predicted (prior) state mean, shape (n,).
        state_cov:
            Predicted (prior) state covariance, shape (n, n).
        observation:
            Observed vector z_t, shape (m,).

        Returns
        -------
        tuple[np.ndarray, np.ndarray, float]
            (posterior_mean, posterior_cov, log_likelihood_contribution).
            posterior_mean has shape (n,), posterior_cov has shape (n, n).
        """
        z = np.asarray(observation, dtype=float).flatten()
        H = self._H
        R = self._R
        n = self._n
        m = self._m

        innov: np.ndarray = z - H @ state_mean
        S: np.ndarray = H @ state_cov @ H.T + R
        # Use solve for numerical stability instead of explicit inverse
        K: np.ndarray = np.linalg.solve(S.T, (state_cov @ H.T).T).T
        x_post: np.ndarray = state_mean + K @ innov
        P_post: np.ndarray = (np.eye(n) - K @ H) @ state_cov

        # Gaussian log-likelihood: -0.5*(m*log(2pi) + log|S| + y^T S^{-1} y)
        sign, logdet = np.linalg.slogdet(S)
        if sign <= 0:  # pragma: no cover
            log_prob = float("-inf")
        else:
            innov_col = innov.reshape(m, 1)
            quad = float(np.squeeze(innov_col.T @ np.linalg.solve(S, innov_col)))
            log_prob = float(
                -0.5 * (m * np.log(2.0 * np.pi) + logdet + quad)
            )

        return x_post, P_post, log_prob

    # ------------------------------------------------------------------
    # Batch forward pass
    # ------------------------------------------------------------------

    def filter(self, observations: np.ndarray) -> KalmanResult:
        """Run the forward Kalman filter over a batch of observations.

        Parameters
        ----------
        observations:
            Observation array.  Shape (T, m) or (T,) for m=1.  Rows with
            all-NaN values are treated as missing: the predicted distribution
            is passed through unchanged as the filtered estimate for that
            time step, and no log-likelihood contribution is accumulated.

        Returns
        -------
        KalmanResult
            Filtered (and predicted) state means, covariances, and total
            log-likelihood.

        Raises
        ------
        ValueError
            If the observation array has the wrong number of columns.
        """
        obs = np.asarray(observations, dtype=float)
        if obs.ndim == 1:
            obs = obs.reshape(-1, 1)
        T, m_obs = obs.shape
        if m_obs != self._m:
            raise ValueError(
                f"observations has {m_obs} columns but model expects m={self._m}"
            )

        n = self._n
        filt_means = np.empty((T, n), dtype=float)
        filt_covs = np.empty((T, n, n), dtype=float)
        pred_means = np.empty((T, n), dtype=float)
        pred_covs = np.empty((T, n, n), dtype=float)

        x = self._x0.copy()
        P = self._P0.copy()
        total_ll = 0.0

        for t in range(T):
            # Predict
            x_pred, P_pred = self.predict(x, P)
            pred_means[t] = x_pred
            pred_covs[t] = P_pred

            # Check for missing observation (all NaN)
            z_t = obs[t]
            if np.all(np.isnan(z_t)):
                # Missing: pass through prediction
                filt_means[t] = x_pred
                filt_covs[t] = P_pred
                x, P = x_pred, P_pred
            else:
                x, P, ll = self.update(x_pred, P_pred, z_t)
                filt_means[t] = x
                filt_covs[t] = P
                total_ll += ll

        return KalmanResult(
            filtered_state_means=filt_means,
            filtered_state_covariances=filt_covs,
            predicted_state_means=pred_means,
            predicted_state_covariances=pred_covs,
            log_likelihood=float(total_ll),
        )

    # ------------------------------------------------------------------
    # RTS backward smoother
    # ------------------------------------------------------------------

    def rts_smooth(
        self,
        result: KalmanResult,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Rauch-Tung-Striebel backward smoother.

        Given the filtered output from :meth:`filter`, runs the RTS backward
        pass to produce smoothed state estimates that condition on ALL T
        observations rather than only the past.

        The RTS recursion (running backward from t=T-1 to 0):
            G_t = P_t^filt * F^T * (P_{t+1}^pred)^{-1}
            x_t^smooth = x_t^filt + G_t * (x_{t+1}^smooth - x_{t+1}^pred)
            P_t^smooth = P_t^filt + G_t * (P_{t+1}^smooth - P_{t+1}^pred) * G_t^T

        Parameters
        ----------
        result:
            :class:`KalmanResult` from a prior :meth:`filter` call on the
            same observation sequence.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            (smoothed_means, smoothed_covs) each of shape (T, n) and
            (T, n, n) respectively.

        Notes
        -----
        The smoothed variance is always <= the filtered variance (element-
        wise for diagonal entries) because smoothing adds information.

        Mathematical references
        -----------------------
        Rauch, Tung & Striebel (1965); Harvey (1989) Chapter 3.
        """
        T = result.filtered_state_means.shape[0]
        F = self._F

        sm_means = result.filtered_state_means.copy()
        sm_covs = result.filtered_state_covariances.copy()

        for t in range(T - 2, -1, -1):
            P_filt = result.filtered_state_covariances[t]
            P_pred_next = result.predicted_state_covariances[t + 1]
            # G_t = P_filt * F^T * P_pred_{t+1}^{-1}
            G: np.ndarray = np.linalg.solve(P_pred_next.T, (P_filt @ F.T).T).T
            sm_means[t] = (
                result.filtered_state_means[t]
                + G @ (sm_means[t + 1] - result.predicted_state_means[t + 1])
            )
            diff_cov = sm_covs[t + 1] - P_pred_next
            sm_covs[t] = P_filt + G @ diff_cov @ G.T

        return sm_means, sm_covs


# ---------------------------------------------------------------------------
# Financial helper: time-varying beta (dynamic hedge ratio)
# ---------------------------------------------------------------------------


def time_varying_beta(
    y: pd.Series,
    x: pd.Series,
    *,
    delta: float = 1e-4,
    obs_var: float = 1e-3,
) -> pd.DataFrame:
    """Estimate a time-varying dynamic hedge ratio via a Kalman filter.

    Implements the dynamic linear regression model:
        y_t = alpha_t + beta_t * x_t + v_t,   v_t ~ N(0, obs_var)
        alpha_t = alpha_{t-1} + w_t^alpha
        beta_t  = beta_{t-1}  + w_t^beta
        [w_t^alpha, w_t^beta]^T ~ N(0, V_W)

    where V_W is the process covariance derived from the West-Harrison
    discount factor ``delta``:
        V_W = delta / (1 - delta) * C_{t-1}

    For simplicity this function uses a fixed scalar process covariance
    proportional to ``delta``, which is the standard approximation used in
    financial time series applications.

    Parameters
    ----------
    y:
        Dependent variable series (e.g., spread leg 1 returns).
    x:
        Independent variable series (e.g., spread leg 2 returns).
        Must be aligned with ``y`` (same index).
    delta:
        Discount factor controlling the rate of variation of the state.
        Smaller delta => state changes faster (more responsive).
        Typical values: 1e-4 to 1e-2.
    obs_var:
        Observation noise variance.  Default 1e-3.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed like ``y`` with two columns:
        ``alpha`` (time-varying intercept) and ``beta`` (time-varying slope).
        Rows where either ``y`` or ``x`` is NaN are filled with NaN.

    Raises
    ------
    ValueError
        If ``delta <= 0`` or ``delta >= 1``, or if the aligned series have
        fewer than 2 finite observations.

    Notes
    -----
    The state vector is [alpha_t, beta_t].
    At each step the observation is: y_t = H_t * [alpha_t, beta_t]^T + v_t
    where H_t = [1, x_t] varies with x_t.  This requires time-varying H,
    so the single-step predict / update primitives of :class:`KalmanFilter`
    are called directly rather than using :meth:`KalmanFilter.filter`.

    Mathematical references
    -----------------------
    West and Harrison (1997) Chapter 6 (discount factor / DLM).
    Harvey (1989) Chapter 2 (time-varying regression).
    """
    if delta <= 0.0 or delta >= 1.0:
        raise ValueError(f"delta must be in (0, 1), got {delta}")
    if obs_var <= 0.0:
        raise ValueError(f"obs_var must be positive, got {obs_var}")

    # Align on the shared index
    aligned = pd.DataFrame({"y": y, "x": x}).dropna()
    n = len(aligned)
    if n < 2:
        raise ValueError("time_varying_beta needs at least 2 non-NaN aligned observations")

    y_arr = aligned["y"].to_numpy(dtype=float)
    x_arr = aligned["x"].to_numpy(dtype=float)

    # Initial state: [alpha=0, beta=1], large covariance
    x_state = np.array([0.0, 1.0])
    P_state = np.eye(2) * 1.0

    # Fixed system matrices (transition is identity for random walk)
    F = np.eye(2)
    Q = (delta / (1.0 - delta)) * np.eye(2)
    R = np.array([[obs_var]])

    alphas = np.empty(n, dtype=float)
    betas = np.empty(n, dtype=float)

    for i in range(n):
        # Predict
        x_pred = F @ x_state
        P_pred = F @ P_state @ F.T + Q

        # Time-varying observation row: H_t = [1, x_t]
        H_t = np.array([[1.0, x_arr[i]]])

        # Update
        z_t = np.array([y_arr[i]])
        innov = z_t - H_t @ x_pred
        S = H_t @ P_pred @ H_t.T + R
        K = np.linalg.solve(S.T, (P_pred @ H_t.T).T).T
        x_state = x_pred + K.flatten() * float(innov[0])
        P_state = (np.eye(2) - K @ H_t) @ P_pred

        alphas[i] = float(x_state[0])
        betas[i] = float(x_state[1])

    result = pd.DataFrame(
        {"alpha": alphas, "beta": betas},
        index=aligned.index,
    )

    # Reindex to original y index, introducing NaN for missing rows
    return result.reindex(y.index)
