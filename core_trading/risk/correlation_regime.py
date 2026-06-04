"""Correlation regime detection for portfolio risk management (Phase 7, module 7.9).

This module characterises the *correlation regime* of a multi-asset returns
panel -- identifying crowding, crisis-driven correlation spikes, and structural
breaks in the cross-asset covariance structure.  All computations are purely
functional and deterministic given their inputs, making them suitable for both
live daily runs and historical backtest replay.

Architecture overview
---------------------
1. ``RollingCorrelationResult``  -- per-window correlation matrices and the
   scalar mean pairwise correlation series (crowding gauge).
2. ``SpectralResult``            -- eigendecomposition output: largest eigenvalue
   share, absorption ratio for the top-k eigenvectors, and the Marchenko-Pastur
   noise floor.
3. ``AbsorptionShiftResult``     -- standardised AR shift (delta-AR indicator)
   measuring how unusually large the recent absorption ratio is relative to its
   long-run trailing distribution.
4. ``CorrelationAlert``          -- typed regime-shift alert record; structurally
   consistent with ``DivergenceAlert`` in ``core_trading.risk.pairs_risk``.
5. ``rolling_correlation``       -- build the rolling correlation panel.
6. ``spectral_analysis``         -- eigendecompose a single correlation matrix.
7. ``absorption_shift``          -- delta-AR indicator over a scalar AR series.
8. ``frobenius_distance``        -- matrix distance between successive corr mats.
9. ``market_mode_rotation``      -- eigenvector-rotation angle of the first PC.
10. ``detect_regime_alerts``     -- unified alert detector over a returns panel.

Mathematical references
-----------------------
Absorption ratio (Kritzman-Li-Page-Rigobon 2011):
    AR_k = sum_{i=1}^{k} lambda_i / sum_{i=1}^{N} lambda_i
where lambda_1 >= ... >= lambda_N are the eigenvalues of the correlation
matrix and k is the number of eigenvectors absorbing the "market mode".
A high AR_k signals tight factor structure -- markets move together, indicating
fragility / crisis risk.

Standardised AR shift (delta-AR):
    delta-AR = (AR_short - AR_long) / std_long
where AR_short is the mean absorption ratio over a short trailing window,
AR_long is the mean over a long trailing window, and std_long is the standard
deviation of the long window.  A positive spike in delta-AR that exceeds a
z-score threshold flags an emerging crowding or crisis regime.

Random-matrix theory -- Marchenko-Pastur upper edge (Laloux et al. 1999):
    lambda_+ = sigma^2 (1 + sqrt(N/T))^2
For a pure-noise (iid) correlation matrix, sigma = 1 and:
    lambda_+ = (1 + sqrt(N/T))^2
Eigenvalues above lambda_+ carry genuine factor signal beyond the noise floor.
Counting them gives the number of statistically significant factors in the panel.

Frobenius matrix distance:
    d_F(A, B) = ||A - B||_F = sqrt(sum_{ij} (A_ij - B_ij)^2)
Measures "how far" two successive correlation matrices have moved -- a large
jump signals a regime shift in the covariance structure.

Eigenvector rotation angle (market mode):
    theta = arccos(clip(|u_t . u_{t-1}|, 0, 1))   [radians]
where u_t and u_{t-1} are the leading eigenvectors at consecutive windows.
A large rotation means the dominant risk direction has pivoted -- another
signature of regime change even when eigenvalue magnitudes are stable.

References:
  * Kritzman, M., Li, Y., Page, S. & Rigobon, R. (2011). "Principal Components
    as a Measure of Systemic Risk." Journal of Portfolio Management, 37(4),
    112-126.
  * Laloux, L., Cizeau, P., Bouchaud, J.-P. & Potters, M. (1999). "Noise
    Dressing of Financial Correlation Matrices." Physical Review Letters, 83(7),
    1467-1470.
  * Marchenko, V.A. & Pastur, L.A. (1967). "Distribution of Eigenvalues for
    Some Sets of Random Matrices." Mathematics of the USSR-Sbornik, 1(4),
    457-483.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

__all__ = [
    "RollingCorrelationResult",
    "SpectralResult",
    "AbsorptionShiftResult",
    "CorrelationAlert",
    "rolling_correlation",
    "spectral_analysis",
    "absorption_shift",
    "frobenius_distance",
    "market_mode_rotation",
    "detect_regime_alerts",
]

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollingCorrelationResult:
    """Output of :func:`rolling_correlation`.

    Attributes
    ----------
    matrices:
        Dict mapping the *last* DatetimeIndex timestamp in each window to the
        N x N correlation matrix (as a ``pd.DataFrame`` with asset columns/index).
        Windows with fewer valid rows than ``window`` are omitted.
    mean_correlation:
        ``pd.Series`` indexed by the same timestamps as ``matrices``.  Each
        value is the mean of the strictly off-diagonal entries of the
        corresponding correlation matrix -- the scalar crowding gauge.
    """

    matrices: dict[pd.Timestamp, pd.DataFrame] = field(compare=False)
    mean_correlation: pd.Series = field(compare=False)  # type: ignore[type-arg]


@dataclass(frozen=True, slots=True)
class SpectralResult:
    """Spectral decomposition of a single correlation matrix.

    Attributes
    ----------
    eigenvalues:
        Eigenvalues sorted in descending order (shape N).
    eigenvectors:
        Corresponding eigenvectors as columns (shape N x N); the leading
        eigenvector (column 0) is the "market mode".
    largest_share:
        Fraction of total variance explained by the largest eigenvalue:
        ``eigenvalues[0] / sum(eigenvalues)``.  A high value signals a
        dominant market-wide factor.
    absorption_ratio:
        Variance fraction absorbed by the top ``k`` eigenvectors:
        ``sum(eigenvalues[:k]) / sum(eigenvalues)``.
    n_signal_factors:
        Number of eigenvalues that exceed the Marchenko-Pastur noise floor
        ``lambda_+ = (1 + sqrt(N/T))^2`` -- i.e. the count of statistically
        significant factors given ratio ``q = N / T``.
    mp_lambda_plus:
        Marchenko-Pastur upper edge used as the noise floor.
    """

    eigenvalues: np.ndarray = field(compare=False)
    eigenvectors: np.ndarray = field(compare=False)
    largest_share: float
    absorption_ratio: float
    n_signal_factors: int
    mp_lambda_plus: float


@dataclass(frozen=True, slots=True)
class AbsorptionShiftResult:
    """Standardised absorption-ratio shift indicator (delta-AR).

    Attributes
    ----------
    timestamps:
        ``pd.DatetimeIndex`` aligned to the input AR series (indices with
        sufficient history to compute both short and long windows).
    delta_ar:
        ``np.ndarray`` of standardised delta-AR values.  Positive spikes
        above the configured z-score threshold flag crowding / crisis entry.
    short_window:
        Length of the short trailing window used.
    long_window:
        Length of the long trailing window used.
    """

    timestamps: pd.DatetimeIndex = field(compare=False)
    delta_ar: np.ndarray = field(compare=False)
    short_window: int
    long_window: int


@dataclass(frozen=True, slots=True)
class CorrelationAlert:
    """Regime-shift alert for correlation structure change.

    Stylistically consistent with ``DivergenceAlert`` in
    ``core_trading.risk.pairs_risk``.

    Attributes
    ----------
    timestamp:
        Bar at which the alert was generated.
    metric:
        Name of the metric that fired: ``"mean_correlation"``,
        ``"absorption_ratio"``, ``"delta_ar"``, ``"frobenius_distance"``, or
        ``"mode_rotation"``.
    value:
        Current observed value of the metric.
    threshold:
        The threshold that was breached.
    severity:
        ``"warning"`` or ``"critical"``; ``"critical"`` when the value exceeds
        ``critical_multiplier * threshold``, ``"warning"`` otherwise.
    """

    timestamp: pd.Timestamp
    metric: str
    value: float
    threshold: float
    severity: Literal["warning", "critical"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _corr_from_array(arr: np.ndarray, labels: pd.Index) -> pd.DataFrame:
    """Compute correlation matrix from a 2-D float array; return as DataFrame."""
    # Demean columns
    x = arr - arr.mean(axis=0)
    # Column standard deviations (ddof=1 for the window)
    std = x.std(axis=0, ddof=1)
    # Handle constant columns gracefully: set std to 1 so corr = 0
    safe_std = np.where(std > 0.0, std, 1.0)
    x_norm = x / safe_std
    cov = (x_norm.T @ x_norm) / float(arr.shape[0] - 1)
    # Clip diagonal to exactly 1 against float noise
    np.fill_diagonal(cov, 1.0)
    # Force symmetry
    cov = (cov + cov.T) / 2.0
    np.fill_diagonal(cov, 1.0)
    return pd.DataFrame(cov, index=labels, columns=labels)


def _mean_off_diagonal(corr_arr: np.ndarray) -> float:
    """Mean of strictly off-diagonal entries of a symmetric N x N array.

    Caller guarantees N >= 2 (validated by rolling_correlation).
    """
    n = corr_arr.shape[0]
    total = float(corr_arr.sum()) - float(np.trace(corr_arr))
    n_off = n * (n - 1)
    return total / float(n_off)


def _eigh_descending(corr_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Eigendecompose a symmetric matrix; return (eigenvalues, eigenvectors) descending."""
    sym = (corr_arr + corr_arr.T) / 2.0
    vals, vecs = np.linalg.eigh(sym)
    # eigh returns ascending order; reverse both
    order = np.argsort(vals)[::-1]
    return vals[order].copy(), vecs[:, order].copy()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rolling_correlation(
    returns: pd.DataFrame,
    *,
    window: int,
) -> RollingCorrelationResult:
    """Build rolling correlation matrices and the mean pairwise correlation series.

    At each bar t >= window - 1, the correlation matrix is computed from the
    returns slice ``returns.iloc[t - window + 1 : t + 1]``.  Rows t < window - 1
    are omitted (insufficient history).

    All columns in ``returns`` must be NaN-free (the correlation is undefined
    for constant columns but will not raise -- such columns produce zero
    off-diagonal correlations and a diagonal entry fixed at 1.0).

    Parameters
    ----------
    returns:
        Returns panel: DatetimeIndex rows x asset-symbol columns; NaN-free.
    window:
        Rolling window length in bars.  Must satisfy
        ``2 <= window <= len(returns)``.

    Returns
    -------
    RollingCorrelationResult

    Raises
    ------
    ValueError
        If ``returns`` contains NaN, has fewer than 2 columns, has fewer than
        ``window`` rows, or ``window < 2``.
    """
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; fill or drop missing data "
            "before computing rolling correlation."
        )
    n_obs, n_assets = returns.shape
    if n_assets < 2:
        raise ValueError(
            f"returns panel must have at least 2 asset columns; got {n_assets}."
        )
    if window < 2:
        raise ValueError(f"window must be >= 2; got {window}.")
    if n_obs < window:
        raise ValueError(
            f"returns panel has {n_obs} rows, which is fewer than window={window}."
        )

    arr = returns.to_numpy(dtype=float)
    labels = returns.columns

    matrices: dict[pd.Timestamp, pd.DataFrame] = {}
    mean_corr_values: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for end_idx in range(window - 1, n_obs):
        start_idx = end_idx - window + 1
        window_arr = arr[start_idx : end_idx + 1]
        corr_df = _corr_from_array(window_arr, labels)
        ts = returns.index[end_idx]
        matrices[ts] = corr_df
        mean_corr_values.append(_mean_off_diagonal(corr_df.to_numpy()))
        timestamps.append(ts)

    mean_correlation: pd.Series = pd.Series(  # type: ignore[type-arg]
        mean_corr_values,
        index=pd.DatetimeIndex(timestamps),
        name="mean_pairwise_correlation",
    )
    return RollingCorrelationResult(
        matrices=matrices,
        mean_correlation=mean_correlation,
    )


def spectral_analysis(
    corr_matrix: pd.DataFrame | np.ndarray,
    *,
    k: int = 1,
    q: float = 0.0,
) -> SpectralResult:
    """Decompose a correlation matrix; compute absorption ratio and noise floor.

    Parameters
    ----------
    corr_matrix:
        Symmetric N x N correlation matrix.  May be passed as a
        ``pd.DataFrame`` or a plain ``np.ndarray``.
    k:
        Number of top eigenvectors used for the absorption ratio.
        Must satisfy ``1 <= k <= N``.
    q:
        Ratio N / T (number of assets over number of observations).
        Used to compute the Marchenko-Pastur upper edge
        ``lambda_+ = (1 + sqrt(q))^2``.  Pass ``q = 0`` (default) to
        disable the MP filter (``n_signal_factors`` will equal N).

    Returns
    -------
    SpectralResult

    Raises
    ------
    ValueError
        If the matrix is not square, k is out of range, or q < 0.
    """
    if isinstance(corr_matrix, pd.DataFrame):
        arr = corr_matrix.to_numpy(dtype=float)
    else:
        arr = np.asarray(corr_matrix, dtype=float)

    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(
            f"corr_matrix must be square 2-D; got shape {arr.shape}."
        )
    n = arr.shape[0]
    if not 1 <= k <= n:
        raise ValueError(
            f"k must satisfy 1 <= k <= N ({n}); got {k}."
        )
    if q < 0.0:
        raise ValueError(f"q must be >= 0; got {q}.")

    eigenvalues, eigenvectors = _eigh_descending(arr)

    total_var = float(eigenvalues.sum())
    if total_var <= 0.0:
        largest_share = 0.0
        absorption_ratio = 0.0
    else:
        largest_share = float(eigenvalues[0]) / total_var
        absorption_ratio = float(eigenvalues[:k].sum()) / total_var

    mp_lambda_plus = float((1.0 + np.sqrt(q)) ** 2) if q > 0.0 else 0.0

    n_signal = int((eigenvalues > mp_lambda_plus).sum()) if q > 0.0 else n

    return SpectralResult(
        eigenvalues=eigenvalues,
        eigenvectors=eigenvectors,
        largest_share=largest_share,
        absorption_ratio=absorption_ratio,
        n_signal_factors=n_signal,
        mp_lambda_plus=mp_lambda_plus,
    )


def absorption_shift(
    ar_series: pd.Series,  # type: ignore[type-arg]
    *,
    short_window: int,
    long_window: int,
) -> AbsorptionShiftResult:
    """Compute the standardised absorption-ratio shift indicator (delta-AR).

    At each position t with sufficient history (t >= long_window), delta-AR is:

        AR_short_mean  = mean(ar_series[t - short_window + 1 : t + 1])
        AR_long_mean   = mean(ar_series[t - long_window + 1 : t + 1])
        AR_long_std    = std(ar_series[t - long_window + 1 : t + 1])
        delta_AR[t]    = (AR_short_mean - AR_long_mean) / AR_long_std

    When ``AR_long_std`` is zero (all values identical over the long window),
    ``delta_AR[t]`` is set to 0.

    Parameters
    ----------
    ar_series:
        1-D scalar time series of absorption-ratio values; must be NaN-free.
    short_window:
        Length of the short trailing window.  Must be >= 1 and < long_window.
    long_window:
        Length of the long trailing window.  Must be > short_window.

    Returns
    -------
    AbsorptionShiftResult
        Contains only the timestamps for which both windows are fully populated.

    Raises
    ------
    ValueError
        If short_window >= long_window, short_window < 1, or the series is
        shorter than long_window.
    """
    if short_window < 1:
        raise ValueError(f"short_window must be >= 1; got {short_window}.")
    if short_window >= long_window:
        raise ValueError(
            f"short_window ({short_window}) must be < long_window ({long_window})."
        )
    arr = ar_series.to_numpy(dtype=float)
    n = len(arr)
    if n < long_window:
        raise ValueError(
            f"ar_series has {n} elements, fewer than long_window={long_window}."
        )

    result_idx: list[int] = []
    delta_vals: list[float] = []

    for t in range(long_window - 1, n):
        long_slice = arr[t - long_window + 1 : t + 1]
        short_slice = arr[t - short_window + 1 : t + 1]
        ar_long_mean = float(long_slice.mean())
        ar_long_std = float(long_slice.std(ddof=1))
        ar_short_mean = float(short_slice.mean())
        delta = 0.0 if ar_long_std <= 0.0 else (ar_short_mean - ar_long_mean) / ar_long_std
        result_idx.append(t)
        delta_vals.append(delta)

    ts_index = pd.DatetimeIndex(ar_series.index[result_idx])
    return AbsorptionShiftResult(
        timestamps=ts_index,
        delta_ar=np.array(delta_vals, dtype=float),
        short_window=short_window,
        long_window=long_window,
    )


def frobenius_distance(
    matrix_a: pd.DataFrame | np.ndarray,
    matrix_b: pd.DataFrame | np.ndarray,
) -> float:
    """Frobenius norm of the difference between two matrices.

    ``d_F(A, B) = ||A - B||_F = sqrt(sum_{ij} (A_ij - B_ij)^2)``

    Parameters
    ----------
    matrix_a, matrix_b:
        Two matrices of the same shape.

    Returns
    -------
    float
        Non-negative Frobenius distance.

    Raises
    ------
    ValueError
        If the shapes differ.
    """
    a = np.asarray(matrix_a, dtype=float) if not isinstance(matrix_a, np.ndarray) else matrix_a.astype(float)
    b = np.asarray(matrix_b, dtype=float) if not isinstance(matrix_b, np.ndarray) else matrix_b.astype(float)

    if isinstance(matrix_a, pd.DataFrame):
        a = matrix_a.to_numpy(dtype=float)
    if isinstance(matrix_b, pd.DataFrame):
        b = matrix_b.to_numpy(dtype=float)

    if a.shape != b.shape:
        raise ValueError(
            f"matrix_a shape {a.shape} and matrix_b shape {b.shape} must match."
        )
    diff = a - b
    return float(np.sqrt((diff * diff).sum()))


def market_mode_rotation(
    vec_a: np.ndarray,
    vec_b: np.ndarray,
) -> float:
    """Angle (in radians) between two leading eigenvectors.

    The market mode is the leading eigenvector of the correlation matrix.
    The rotation angle between consecutive windows is:

        theta = arccos(clip(|u_a . u_b|, 0, 1))

    The absolute value of the dot product is used because the sign of an
    eigenvector is arbitrary; only the direction matters.

    Parameters
    ----------
    vec_a, vec_b:
        Unit-norm leading eigenvectors (1-D float arrays of the same length).

    Returns
    -------
    float
        Angle in radians, in [0, pi/2].

    Raises
    ------
    ValueError
        If the two vectors have different lengths or are zero-norm.
    """
    a = np.asarray(vec_a, dtype=float).ravel()
    b = np.asarray(vec_b, dtype=float).ravel()
    if a.shape != b.shape:
        raise ValueError(
            f"vec_a length {a.shape[0]} and vec_b length {b.shape[0]} must match."
        )
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        raise ValueError("Both eigenvectors must have non-zero norm.")
    # Normalise defensively
    a_unit = a / norm_a
    b_unit = b / norm_b
    cos_theta = float(np.clip(abs(float(np.dot(a_unit, b_unit))), 0.0, 1.0))
    return float(np.arccos(cos_theta))


def detect_regime_alerts(
    returns: pd.DataFrame,
    *,
    window: int = 60,
    k: int = 1,
    short_window: int = 10,
    long_window: int = 60,
    mean_corr_z_threshold: float = 2.0,
    ar_z_threshold: float = 2.0,
    delta_ar_threshold: float = 2.0,
    frob_z_threshold: float = 2.0,
    rotation_z_threshold: float = 2.0,
    critical_multiplier: float = 1.5,
) -> list[CorrelationAlert]:
    """Detect regime-shift alerts from a multi-asset returns panel.

    Runs five detectors in sequence; each compares a rolling metric against
    a z-score threshold derived from its trailing distribution:

    (a) **Mean pairwise correlation spike**: the scalar crowding gauge from
        :func:`rolling_correlation` standardised against its own trailing
        distribution (long_window values) flags crowding entry.
    (b) **Absorption ratio spike**: AR_k from :func:`spectral_analysis` applied
        to each rolling window's correlation matrix; same z-score gate.
    (c) **Delta-AR spike**: standardised AR shift via :func:`absorption_shift`.
        Direct threshold on the delta-AR value (already in z-score units).
    (d) **Frobenius distance spike**: distance between consecutive correlation
        matrices z-scored against its trailing distribution.
    (e) **Market-mode rotation spike**: leading eigenvector rotation angle
        z-scored against its trailing distribution.

    For all z-score detectors the trailing distribution is the long_window of
    the metric series; alerts are only emitted where both windows are full.

    Parameters
    ----------
    returns:
        Returns panel: NaN-free DatetimeIndex x asset-symbol DataFrame.
    window:
        Rolling correlation window in bars (default 60).
    k:
        Number of top eigenvectors for the absorption ratio (default 1).
    short_window:
        Short window for delta-AR indicator (default 10).
    long_window:
        Long trailing window for standardisation and delta-AR (default 60).
    mean_corr_z_threshold:
        Z-score above which a mean-correlation spike is an alert (default 2.0).
    ar_z_threshold:
        Z-score above which an absorption-ratio spike is an alert (default 2.0).
    delta_ar_threshold:
        Raw delta-AR value above which an alert fires; delta-AR is already
        expressed in long-window standard-deviation units (default 2.0).
    frob_z_threshold:
        Z-score above which a Frobenius distance spike is an alert (default 2.0).
    rotation_z_threshold:
        Z-score above which a mode-rotation spike is an alert (default 2.0).
    critical_multiplier:
        A metric value >= critical_multiplier * threshold produces a
        ``"critical"`` alert; otherwise ``"warning"`` (default 1.5).

    Returns
    -------
    list[CorrelationAlert]
        All fired alerts, sorted by timestamp then metric name.

    Raises
    ------
    ValueError
        On invalid returns panel (propagated from :func:`rolling_correlation`).
    """
    rolling = rolling_correlation(returns, window=window)
    ts_list = list(rolling.mean_correlation.index)
    n_windows = len(ts_list)

    # Build per-window spectral results
    n_assets = returns.shape[1]
    n_obs = returns.shape[0]
    q = float(n_assets) / float(n_obs)

    ar_values: list[float] = []
    lead_vecs: list[np.ndarray] = []
    corr_arrs: list[np.ndarray] = []

    for ts in ts_list:
        corr_df = rolling.matrices[ts]
        sp = spectral_analysis(corr_df, k=k, q=q)
        ar_values.append(sp.absorption_ratio)
        lead_vecs.append(sp.eigenvectors[:, 0].copy())
        corr_arrs.append(corr_df.to_numpy(dtype=float))

    ar_series: pd.Series = pd.Series(  # type: ignore[type-arg]
        ar_values,
        index=pd.DatetimeIndex(ts_list),
        name="absorption_ratio",
    )
    mean_corr_arr = rolling.mean_correlation.to_numpy(dtype=float)

    # Frobenius distances between consecutive windows
    frob_values: list[float] = []
    frob_ts: list[pd.Timestamp] = []
    for i in range(1, n_windows):
        d = frobenius_distance(corr_arrs[i], corr_arrs[i - 1])
        frob_values.append(d)
        frob_ts.append(ts_list[i])

    # Rotation angles between consecutive market-mode vectors
    rot_values: list[float] = []
    rot_ts: list[pd.Timestamp] = []
    for i in range(1, n_windows):
        theta = market_mode_rotation(lead_vecs[i], lead_vecs[i - 1])
        rot_values.append(theta)
        rot_ts.append(ts_list[i])

    alerts: list[CorrelationAlert] = []

    def _z_alerts(
        values: list[float],
        timestamps_list: list[pd.Timestamp],
        metric_name: str,
        threshold: float,
    ) -> None:
        """Z-score standardise and fire alerts where value exceeds threshold."""
        arr = np.array(values, dtype=float)
        n = len(arr)
        if n < long_window:
            return
        for t in range(long_window - 1, n):
            window_slice = arr[t - long_window + 1 : t + 1]
            mean_w = float(window_slice.mean())
            std_w = float(window_slice.std(ddof=1))
            if std_w <= 0.0:
                continue
            z_val = (arr[t] - mean_w) / std_w
            if z_val > threshold:
                sev: Literal["warning", "critical"] = (
                    "critical" if z_val >= critical_multiplier * threshold else "warning"
                )
                alerts.append(
                    CorrelationAlert(
                        timestamp=timestamps_list[t],
                        metric=metric_name,
                        value=float(arr[t]),
                        threshold=threshold,
                        severity=sev,
                    )
                )

    # (a) Mean correlation spike
    _z_alerts(
        list(mean_corr_arr),
        ts_list,
        "mean_correlation",
        mean_corr_z_threshold,
    )

    # (b) Absorption ratio spike
    _z_alerts(
        ar_values,
        ts_list,
        "absorption_ratio",
        ar_z_threshold,
    )

    # (c) Delta-AR indicator
    if len(ar_series) >= long_window:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ar_shift = absorption_shift(
                ar_series, short_window=short_window, long_window=long_window
            )
        for i, ts in enumerate(ar_shift.timestamps):
            delta = float(ar_shift.delta_ar[i])
            if delta > delta_ar_threshold:
                sev_d: Literal["warning", "critical"] = (
                    "critical"
                    if delta >= critical_multiplier * delta_ar_threshold
                    else "warning"
                )
                alerts.append(
                    CorrelationAlert(
                        timestamp=ts,
                        metric="delta_ar",
                        value=delta,
                        threshold=delta_ar_threshold,
                        severity=sev_d,
                    )
                )

    # (d) Frobenius distance spike
    _z_alerts(frob_values, frob_ts, "frobenius_distance", frob_z_threshold)

    # (e) Market-mode rotation spike
    _z_alerts(rot_values, rot_ts, "mode_rotation", rotation_z_threshold)

    alerts.sort(key=lambda a: (a.timestamp, a.metric))
    return alerts
