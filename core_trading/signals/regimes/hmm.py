"""Hidden Markov Model regime detection (master plan Phase 5.A.1).

Fits a Gaussian HMM to financial return series to identify latent market
regimes (bull, bear, sideways, crisis).  The module deliberately keeps all
``hmmlearn`` imports inside function bodies so the heavy C extension is only
loaded when regime detection is actually requested.

Design notes
------------
* :class:`RegimeConfig` and :class:`RegimeResult` are frozen slotted
  dataclasses so they are thread-safe and can be cached without risk of
  mutation.
* Feature matrix: ``[log_return_t, realised_vol_t]`` where realised volatility
  is a rolling standard deviation of log returns computed on a trailing window
  (look-ahead-free).  Both columns are z-scored using training-set statistics
  so that the Gaussian HMM covariance matrices remain well-conditioned across
  all ``random_state`` initialisations.
* The scaler (training mean / std) is stored on the detector after ``fit``
  so that out-of-sample ``predict`` applies the same transformation.
* State means reported in :class:`RegimeResult` are in the *original*
  (unscaled) feature space so that the return magnitude is directly
  interpretable.
* Stable labelling: states are relabelled in ascending order of mean
  log-return (original space) so state 0 is always the most bearish regime.
  This makes labels comparable across separate fits.
* Two inference modes are exposed:
  - ``fit_predict`` (full-sample smoothing): fits AND decodes the same series.
  - ``fit`` + ``predict`` (out-of-sample): fits on a training window then
    infers forward on held-out data.

Mathematical references
-----------------------
Hamilton (1989) regime-switching model:
    Hamilton, J.D. (1989). "A new approach to the economic analysis of
    nonstationary time series and the business cycle." Econometrica, 57(2),
    357-384.
Rabiner (1989) HMM tutorial:
    Rabiner, L.R. (1989). "A tutorial on hidden Markov models and selected
    applications in speech recognition." Proceedings of the IEEE, 77(2),
    257-286.
Gaussian HMM emissions:
    Each state k has Gaussian emission: x_t | s_t=k ~ N(mean_k, Sigma_k).
    The Baum-Welch (EM) algorithm maximises the expected complete-data
    log-likelihood over parameters (transition matrix A, means, covariances).
    Viterbi decoding recovers argmax_{s_1,...,s_T} P(s | x, theta).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "RegimeConfig",
    "RegimeResult",
    "RegimeDetector",
    "LABEL_BULL",
    "LABEL_BEAR",
    "LABEL_SIDEWAYS",
    "LABEL_CRISIS",
]

# ---------------------------------------------------------------------------
# Regime label constants (state indices after stable relabelling)
# ---------------------------------------------------------------------------

LABEL_BEAR: int = 0
"""State with the lowest mean log-return (most bearish regime)."""

LABEL_BULL: int = 1
"""State with the highest mean log-return (most bullish regime in 2-state).

In 3- or 4-state models LABEL_BULL is 1 only if fewer than 3 states lie
above the bear state.  Use the ascending-mean ordering directly for
multi-state models.
"""

LABEL_SIDEWAYS: int = 2
"""Intermediate sideways regime (only present when n_states >= 3)."""

LABEL_CRISIS: int = 3
"""Crisis / tail-risk regime (only present when n_states == 4)."""


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    """Configuration for the Gaussian HMM regime detector.

    Attributes
    ----------
    n_states:
        Number of hidden states.  Must be 2, 3, or 4.
        2 => bull / bear.
        3 => bull / bear / sideways.
        4 => bull / bear / sideways / crisis.
    n_iter:
        Maximum Baum-Welch EM iterations.
    covariance_type:
        Covariance structure for each state emission distribution.
        One of ``"full"``, ``"tied"``, ``"diag"``, ``"spherical"``.
        Default ``"full"`` allows each state its own covariance matrix.
    vol_window:
        Rolling window (in observations) used to compute realised volatility
        from log returns.  Must be >= 2.  Default 21 (approx one trading month).
    random_state:
        Integer seed passed to ``GaussianHMM`` for reproducible fits.
    tol:
        Convergence tolerance for the Baum-Welch EM algorithm.  Iteration
        stops when the log-likelihood improvement falls below ``tol``.
    """

    n_states: int = 2
    n_iter: int = 500
    covariance_type: str = "full"
    vol_window: int = 21
    random_state: int = 42
    tol: float = 1e-6

    def __post_init__(self) -> None:
        if self.n_states not in (2, 3, 4):
            raise ValueError("n_states must be 2, 3, or 4")
        if self.n_iter < 1:
            raise ValueError("n_iter must be >= 1")
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        if self.covariance_type not in ("full", "tied", "diag", "spherical"):
            raise ValueError(
                "covariance_type must be 'full', 'tied', 'diag', or 'spherical'"
            )


@dataclass(frozen=True, slots=True)
class RegimeResult:
    """Output of a Gaussian HMM regime fit.

    Attributes
    ----------
    state_means:
        Mean feature vector per state in the *original* (unscaled) feature
        space, shape ``(n_states, n_features)``.  Column 0 is mean log-return;
        column 1 is mean realised volatility.  States are sorted in ascending
        order of column 0 so state 0 is always the most bearish regime.
    state_covariances:
        Covariance matrix per state in the *scaled* feature space,
        shape ``(n_states, n_features, n_features)``.
        For ``covariance_type='tied'`` all rows are identical.
    posterior_probs:
        DataFrame of shape ``(n_obs, n_states)``.  Each row sums to 1.0.
        Indexed identically to the input series.  Column ``i`` is the
        posterior probability of being in state ``i`` at that timestamp.
    viterbi_path:
        Most-likely state sequence (Viterbi), aligned to the same index as
        ``posterior_probs``.
    log_likelihood:
        Log-likelihood of the observed sequence under the fitted model
        (in the scaled feature space).
    n_states:
        Number of hidden states (mirrors ``RegimeConfig.n_states``).
    """

    state_means: np.ndarray
    state_covariances: np.ndarray
    posterior_probs: pd.DataFrame
    viterbi_path: pd.Series
    log_likelihood: float
    n_states: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_feature_matrix(
    log_returns: np.ndarray,
    vol_window: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a 2-column feature matrix from a 1-D log-return array.

    Parameters
    ----------
    log_returns:
        1-D array of log returns, length T.
    vol_window:
        Rolling window for realised-volatility computation.

    Returns
    -------
    features:
        Array of shape ``(T - vol_window + 1, 2)`` with columns
        ``[log_return, realised_vol]``.  The first ``vol_window - 1`` rows
        are dropped because they lack a full volatility window.
    valid_mask:
        Boolean mask of length T that selects the rows kept; used to align
        the original index back to the features.
    """
    t = len(log_returns)
    # Realised vol: rolling std over vol_window, look-ahead-free.
    # Result[i] uses log_returns[i-vol_window+1 : i+1].
    # First valid position is index vol_window - 1.
    vol = np.empty(t)
    vol[:] = np.nan
    for i in range(vol_window - 1, t):
        window = log_returns[i - vol_window + 1 : i + 1]
        vol[i] = float(np.std(window, ddof=1))

    valid = np.isfinite(vol)
    features = np.column_stack([log_returns[valid], vol[valid]])
    return features.astype(float), valid


def _scale_features(
    features: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
) -> np.ndarray:
    """Z-score a feature matrix using pre-computed mean and std.

    Parameters
    ----------
    features:
        Array of shape ``(n_obs, n_features)``.
    mu:
        Column means, shape ``(n_features,)``.
    sigma:
        Column standard deviations, shape ``(n_features,)``.  Any zero
        entry is replaced by 1.0 to avoid division by zero.

    Returns
    -------
    np.ndarray
        Standardised feature matrix, same shape as ``features``.
    """
    sigma_safe: np.ndarray = np.where(sigma == 0.0, 1.0, sigma)
    result: np.ndarray = (features - mu) / sigma_safe
    return result


def _relabel_states(
    model: object,
    features_scaled: np.ndarray,
    n_states: int,
    mu: np.ndarray,
    sigma: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute posteriors and Viterbi path with states sorted by mean return.

    Parameters
    ----------
    model:
        A fitted ``GaussianHMM`` instance.
    features_scaled:
        Standardised feature matrix used for inference, shape
        ``(n_obs, n_features)``.
    n_states:
        Number of hidden states.
    mu:
        Per-column training mean (original space), shape ``(n_features,)``.
    sigma:
        Per-column training std (original space), shape ``(n_features,)``.

    Returns
    -------
    posteriors:
        Array of shape ``(n_obs, n_states)``, states in relabelled order.
    viterbi:
        1-D integer array of relabelled state indices, length ``n_obs``.
    perm:
        Permutation array: ``perm[i]`` is the original state index whose
        mean return is the i-th smallest.
    means_original:
        State means back-transformed to the original feature space,
        shape ``(n_states, n_features)``, in relabelled order.
    """
    posteriors_orig: np.ndarray = model.predict_proba(features_scaled)  # type: ignore[attr-defined]
    viterbi_orig: np.ndarray = model.predict(features_scaled)  # type: ignore[attr-defined]
    means_scaled: np.ndarray = model.means_  # type: ignore[attr-defined]

    # Back-transform means to original space for interpretable ordering.
    sigma_safe = np.where(sigma == 0.0, 1.0, sigma)
    means_original_all = means_scaled * sigma_safe + mu

    # Sort states by ascending mean return (column 0, original space).
    perm: np.ndarray = np.argsort(means_original_all[:, 0])

    # Build inverse permutation: old_state -> new_state
    inv_perm = np.empty(n_states, dtype=int)
    for new_idx, old_idx in enumerate(perm):
        inv_perm[old_idx] = new_idx

    posteriors = posteriors_orig[:, perm]
    viterbi = inv_perm[viterbi_orig]
    means_original = means_original_all[perm]

    return posteriors, viterbi, perm, means_original


def _extract_covariances(model: object, perm: np.ndarray, n_states: int) -> np.ndarray:
    """Extract per-state covariance matrices from a fitted model.

    In hmmlearn 0.3.x the ``covars_`` property (via ``fill_covars``) returns a
    ``(n_states, n_features, n_features)`` array for ``"full"``, ``"tied"``,
    and ``"diag"`` covariance types.  For ``"spherical"`` the property returns
    a flat-then-expanded array whose first dimension is ``n_states * n_features``
    rather than ``n_states``; this function works around that by reading the
    internal ``_covars_`` storage (shape ``(n_states, n_features)``) and
    constructing the output directly.

    Parameters
    ----------
    model:
        A fitted ``GaussianHMM`` instance.
    perm:
        Permutation array (ascending mean-return order) from
        :func:`_relabel_states`.
    n_states:
        Number of hidden states.

    Returns
    -------
    np.ndarray
        Covariance array of shape ``(n_states, n_features, n_features)``.
    """
    cov_type: str = model.covariance_type  # type: ignore[attr-defined]
    n_features: int = model.means_.shape[1]  # type: ignore[attr-defined]

    if cov_type == "spherical":
        # Internal storage is (n_states, n_features) -- one scalar variance
        # per feature per state (hmmlearn stores the per-feature spherical
        # variance, not a single scalar, when n_features > 1).
        covars_internal: np.ndarray = model._covars_  # type: ignore[attr-defined]
        result = np.zeros((n_states, n_features, n_features))
        for new_idx, orig in enumerate(perm):
            # Use the mean per-feature variance as the spherical scalar.
            scalar = float(np.mean(covars_internal[orig]))
            result[new_idx] = np.eye(n_features) * scalar
        return result

    # For "full", "tied", and "diag" the covars_ property already returns
    # (n_states, n_features, n_features).
    covars_full: np.ndarray = model.covars_  # type: ignore[attr-defined]
    perm_result: np.ndarray = covars_full[perm]
    return perm_result


# ---------------------------------------------------------------------------
# Public detector class
# ---------------------------------------------------------------------------


class RegimeDetector:
    """Gaussian HMM regime detector.

    Parameters
    ----------
    config:
        :class:`RegimeConfig` controlling the HMM architecture and fitting
        parameters.  Defaults to ``RegimeConfig()`` (2-state, full covariance).

    Examples
    --------
    Full-sample fit and decode on a price series::

        import pandas as pd
        from core_trading.signals.regimes import RegimeDetector, RegimeConfig

        prices = pd.Series(...)  # daily close prices
        config = RegimeConfig(n_states=3, random_state=0)
        detector = RegimeDetector(config)
        result = detector.fit_predict(prices)
        print(result.viterbi_path.value_counts())

    Walk-forward (out-of-sample) usage::

        train_prices = prices.iloc[:252]
        test_prices = prices.iloc[252:]
        detector.fit(train_prices)
        result = detector.predict(test_prices)
    """

    def __init__(self, config: RegimeConfig | None = None) -> None:
        self._config: RegimeConfig = config if config is not None else RegimeConfig()
        self._model: object | None = None
        self._scale_mu: np.ndarray | None = None
        self._scale_sigma: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def config(self) -> RegimeConfig:
        """The :class:`RegimeConfig` used by this detector."""
        return self._config

    @property
    def is_fitted(self) -> bool:
        """True after :meth:`fit` or :meth:`fit_predict` has been called."""
        return self._model is not None

    def fit(self, prices: pd.Series) -> RegimeDetector:
        """Fit the HMM on a training price series.

        Only the model parameters are stored; no result object is returned.
        Call :meth:`predict` to infer regimes on a held-out series.

        Parameters
        ----------
        prices:
            Price or index-level series (not returns).  Must have at least
            ``config.vol_window + 1`` non-NaN observations.

        Returns
        -------
        RegimeDetector
            ``self``, enabling method chaining.
        """
        log_ret = self._log_returns(prices)
        features, _ = _build_feature_matrix(log_ret, self._config.vol_window)
        self._validate_enough_obs(features)

        mu = features.mean(axis=0)
        sigma = features.std(axis=0, ddof=1)
        features_scaled = _scale_features(features, mu, sigma)

        self._scale_mu = mu
        self._scale_sigma = sigma
        self._model = self._fit_hmm(features_scaled)
        return self

    def predict(self, prices: pd.Series) -> RegimeResult:
        """Infer regimes on a new price series using the already-fitted model.

        The model must have been fitted via :meth:`fit` before calling this
        method.  This path is look-ahead-free when the training set does not
        overlap the prediction set.

        Parameters
        ----------
        prices:
            Price or index-level series to decode.  Must have at least
            ``config.vol_window + 1`` non-NaN observations.

        Returns
        -------
        RegimeResult
            Decoded regimes for ``prices``.

        Raises
        ------
        RuntimeError
            If the detector has not been fitted yet.
        """
        if self._model is None or self._scale_mu is None or self._scale_sigma is None:
            raise RuntimeError("call fit() before predict()")
        log_ret = self._log_returns(prices)
        features, valid = _build_feature_matrix(log_ret, self._config.vol_window)
        self._validate_enough_obs(features)
        features_scaled = _scale_features(features, self._scale_mu, self._scale_sigma)
        return self._decode(prices, features_scaled, valid)

    def fit_predict(self, prices: pd.Series) -> RegimeResult:
        """Fit the HMM and decode the same series (full-sample smoothing).

        This mode uses the entire series for both fitting and decoding.  It is
        appropriate for research / retrospective analysis.  For live or
        walk-forward use, call :meth:`fit` on a training window then
        :meth:`predict` on new data.

        Parameters
        ----------
        prices:
            Price or index-level series.  Must have at least
            ``config.vol_window + 1`` non-NaN observations.

        Returns
        -------
        RegimeResult
            Fitted and decoded result.
        """
        self.fit(prices)
        log_ret = self._log_returns(prices)
        features, valid = _build_feature_matrix(log_ret, self._config.vol_window)
        features_scaled = _scale_features(
            features, self._scale_mu, self._scale_sigma  # type: ignore[arg-type]
        )
        return self._decode(prices, features_scaled, valid)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _log_returns(self, prices: pd.Series) -> np.ndarray:
        """Compute log returns from a price series, dropping leading NaN."""
        clean = prices.dropna()
        if len(clean) < 2:
            raise ValueError("prices must have at least 2 non-NaN observations")
        log_prices = np.log(clean.to_numpy(dtype=float))
        return np.diff(log_prices)

    def _validate_enough_obs(self, features: np.ndarray) -> None:
        """Raise ValueError if the feature matrix is too small to fit."""
        cfg = self._config
        min_obs = cfg.n_states * 2
        if features.shape[0] < min_obs:
            raise ValueError(
                f"Not enough observations after feature construction: "
                f"got {features.shape[0]}, need at least {min_obs} "
                f"(n_states * 2)."
            )

    def _fit_hmm(self, features_scaled: np.ndarray) -> object:
        """Construct and fit a GaussianHMM on standardised features."""
        from hmmlearn.hmm import GaussianHMM  # lazy import

        cfg = self._config
        model = GaussianHMM(
            n_components=cfg.n_states,
            covariance_type=cfg.covariance_type,
            n_iter=cfg.n_iter,
            tol=cfg.tol,
            random_state=cfg.random_state,
        )
        model.fit(features_scaled)
        return model

    def _decode(
        self,
        prices: pd.Series,
        features_scaled: np.ndarray,
        valid: np.ndarray,
    ) -> RegimeResult:
        """Build a :class:`RegimeResult` from fitted model and features."""
        cfg = self._config
        model = self._model
        mu: np.ndarray = self._scale_mu  # type: ignore[assignment]
        sigma: np.ndarray = self._scale_sigma  # type: ignore[assignment]

        posteriors, viterbi, perm, means_orig = _relabel_states(
            model, features_scaled, cfg.n_states, mu, sigma
        )
        covars = _extract_covariances(model, perm, cfg.n_states)

        log_lik: float = float(model.score(features_scaled))  # type: ignore[union-attr]

        # Reconstruct the index for rows that survived the vol window.
        # prices.dropna() has N rows.
        # log_ret has N-1 rows (diff drops first).
        # valid is a boolean mask over log_ret indices.
        clean_idx = prices.dropna().index
        ret_idx = clean_idx[1:]
        obs_idx = ret_idx[valid]

        state_cols = [f"state_{i}" for i in range(cfg.n_states)]
        posterior_df = pd.DataFrame(posteriors, index=obs_idx, columns=state_cols)
        viterbi_s = pd.Series(viterbi, index=obs_idx, name="regime", dtype=int)

        return RegimeResult(
            state_means=means_orig,
            state_covariances=covars,
            posterior_probs=posterior_df,
            viterbi_path=viterbi_s,
            log_likelihood=log_lik,
            n_states=cfg.n_states,
        )
