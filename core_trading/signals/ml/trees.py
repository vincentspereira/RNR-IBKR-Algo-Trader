"""Tree-ensemble directional signal (Phase 5.D.1).

The piece that turns the 5.D machine-learning toolkit into a tradeable alpha. A
random forest is trained on the triple-barrier *direction* labels (``{-1, +1}``
from :func:`core_trading.signals.ml.labeling.get_bins` with the flat ``0`` events
dropped); its predicted up-probability is converted into a bet-sized position in
``(-1, 1)`` via the de Prado probability-to-size transform.

Two signal paths, sharing the same sizing:

* :meth:`RandomForestSignal.oof_signal` -- the **backtest** signal. Out-of-fold
  probabilities from
  :func:`core_trading.signals.ml.cross_validation.purged_cv_predict`, so every
  position is produced by a model that never trained on that observation (nor on
  any overlapping label). This is the only honest way to evaluate an ML signal on
  the same sample it was learned from.
* :meth:`RandomForestSignal.signal` -- the **live** signal. A full-sample fit's
  probabilities sized the same way, for forward prediction once the model is
  trusted.

The forest defaults follow de Prado's recommendations for noisy financial labels:
``class_weight="balanced_subsample"`` to counter label imbalance and a small
per-leaf floor to regularise. ``scikit-learn`` is lazy-imported, as elsewhere in
5.D.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 6 (Ensemble Methods) and Chapter 10 (bet sizing, snippet 10.2 -- the
  signed size from the predicted-class probability).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core_trading.signals.ml.cross_validation import purged_cv_predict
from core_trading.signals.ml.meta_labelling import bet_size_from_prob

__all__ = [
    "TreeSignalConfig",
    "RandomForestSignal",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TreeSignalConfig:
    """Hyper-parameters for :class:`RandomForestSignal`'s default forest.

    Attributes
    ----------
    n_estimators:
        Number of trees (>= 1).
    max_features:
        Features considered per split: an int (>= 1), a float in ``(0, 1]``, one
        of ``"sqrt"`` / ``"log2"``, or None (all features).
    max_depth:
        Maximum tree depth (None = unbounded, else >= 1).
    min_samples_leaf:
        Minimum samples per leaf (>= 1); a regulariser against noisy labels.
    class_weight:
        scikit-learn class weighting: None, ``"balanced"`` or
        ``"balanced_subsample"`` (the default, to counter label imbalance).
    random_state:
        Seed for reproducibility.
    step_size:
        Bet-size discretisation grid in ``[0, 1]`` (0 leaves the size continuous).
    """

    n_estimators: int = 200
    max_features: int | float | str | None = "sqrt"
    max_depth: int | None = None
    min_samples_leaf: int = 1
    class_weight: str | None = "balanced_subsample"
    random_state: int = 0
    step_size: float = 0.0

    def __post_init__(self) -> None:
        if self.n_estimators < 1:
            raise ValueError("n_estimators must be >= 1")
        if isinstance(self.max_features, str) and self.max_features not in {"sqrt", "log2"}:
            raise ValueError("max_features string must be 'sqrt' or 'log2'")
        if isinstance(self.max_features, int) and self.max_features < 1:
            raise ValueError("max_features int must be >= 1")
        if isinstance(self.max_features, float) and not 0.0 < self.max_features <= 1.0:
            raise ValueError("max_features float must be in (0, 1]")
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError("max_depth must be None or >= 1")
        if self.min_samples_leaf < 1:
            raise ValueError("min_samples_leaf must be >= 1")
        if self.class_weight is not None and self.class_weight not in {
            "balanced",
            "balanced_subsample",
        }:
            raise ValueError("class_weight must be None, 'balanced' or 'balanced_subsample'")
        if not 0.0 <= self.step_size <= 1.0:
            raise ValueError("step_size must be in [0, 1]")


def _default_estimator(config: TreeSignalConfig) -> Any:
    """Build the default random forest from ``config`` (lazy sklearn import)."""
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=config.n_estimators,
        max_features=config.max_features,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        class_weight=config.class_weight,
        random_state=config.random_state,
    )


def _check_binary(y: pd.Series) -> None:
    """Require exactly two label classes (a directional signal is up vs down)."""
    if len(np.unique(y.to_numpy())) != 2:
        raise ValueError(
            "directional signal requires exactly 2 label classes (drop flat/0 labels)"
        )


def _positions_from_up_prob(p_up: np.ndarray, *, step_size: float) -> np.ndarray:
    """Signed bet sizes from the up-probability (AFML snippet 10.2).

    The predicted direction is the more-likely side; its bet-size magnitude comes
    from the probability of *that* side via :func:`bet_size_from_prob`, so the
    position is near 0 at ``p_up = 0.5`` and approaches +/-1 as conviction grows.
    """
    p = np.asarray(p_up, dtype=float)
    direction = np.where(p >= 0.5, 1.0, -1.0)
    prob_predicted = np.where(p >= 0.5, p, 1.0 - p)
    magnitude = bet_size_from_prob(prob_predicted, num_classes=2, step_size=step_size)
    result: np.ndarray = np.asarray(direction * magnitude, dtype=float)
    return result


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------


class RandomForestSignal:
    """A leakage-aware random-forest directional signal.

    Parameters
    ----------
    config:
        Hyper-parameters; defaults to :class:`TreeSignalConfig`.
    estimator:
        An optional pre-built scikit-learn classifier (exposing
        ``fit`` / ``predict_proba`` / ``classes_``). When omitted a
        :class:`~sklearn.ensemble.RandomForestClassifier` is built from
        ``config``. The injected estimator is the seam used by the tests.
    """

    def __init__(
        self,
        *,
        config: TreeSignalConfig | None = None,
        estimator: Any | None = None,
    ) -> None:
        self._config = config if config is not None else TreeSignalConfig()
        self._injected = estimator
        self._estimator: Any | None = None
        self._classes: np.ndarray | None = None
        self._feature_names: list[Any] = []

    @property
    def config(self) -> TreeSignalConfig:
        """The model's hyper-parameters."""
        return self._config

    @property
    def fitted(self) -> bool:
        """Whether :meth:`fit` has been called."""
        return self._estimator is not None

    @property
    def classes_(self) -> np.ndarray:
        """The fitted class labels (ascending). Raises if not yet fit."""
        if self._classes is None:
            raise RuntimeError("RandomForestSignal is not fitted")
        return self._classes

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        *,
        sample_weight: pd.Series | None = None,
    ) -> RandomForestSignal:
        """Fit the forest on features and binary direction labels (live model).

        Parameters
        ----------
        x:
            Feature frame, indexed by event start.
        y:
            Binary direction labels in ``{-1, +1}`` sharing ``x``'s index.
        sample_weight:
            Optional per-event weights (e.g. from
            :mod:`core_trading.signals.ml.sample_weights`).

        Returns
        -------
        RandomForestSignal
            ``self``, fitted.

        Raises
        ------
        ValueError
            If inputs are empty, mis-aligned, non-finite, or not binary.
        """
        if x.empty:
            raise ValueError("features must be non-empty")
        if not x.index.equals(y.index):
            raise ValueError("features and labels must share the same index")
        values = x.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("features contain non-finite values")
        _check_binary(y)

        estimator = self._make_estimator()
        weight = (
            None
            if sample_weight is None
            else sample_weight.reindex(y.index).to_numpy(dtype=float)
        )
        estimator.fit(values, y.to_numpy(), sample_weight=weight)

        self._estimator = estimator
        self._classes = np.asarray(estimator.classes_)
        self._feature_names = list(x.columns)
        return self

    def predict_proba(self, x: pd.DataFrame) -> pd.Series:
        """The up-probability ``P(class = max)`` per row (the live model).

        Parameters
        ----------
        x:
            Feature frame with the same columns (and order) as at fit.

        Returns
        -------
        pd.Series
            Up-probability indexed like ``x``.
        """
        estimator = self._require_fitted(x)
        proba = np.asarray(estimator.predict_proba(x.to_numpy(dtype=float)), dtype=float)
        up = int(np.argmax(self.classes_))  # sorted ascending -> +1/up is last
        return pd.Series(proba[:, up], index=x.index, name="prob_up")

    def signal(self, x: pd.DataFrame) -> pd.Series:
        """Live bet-sized position in ``[-1, 1]`` from a full-sample fit.

        Parameters
        ----------
        x:
            Feature frame (see :meth:`predict_proba`).

        Returns
        -------
        pd.Series
            Signed position indexed like ``x``.
        """
        positions = _positions_from_up_prob(
            self.predict_proba(x).to_numpy(), step_size=self._config.step_size
        )
        return pd.Series(positions, index=x.index, name="signal")

    def oof_signal(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        *,
        t1: pd.Series,
        n_splits: int = 5,
        embargo_pct: float = 0.0,
        sample_weight: pd.Series | None = None,
    ) -> pd.Series:
        """Out-of-fold bet-sized positions -- the honest backtest signal.

        Builds out-of-fold up-probabilities with
        :func:`purged_cv_predict` (no observation is sized by a model that trained
        on it or an overlapping label) and converts them to positions. Independent
        of :meth:`fit`.

        Parameters
        ----------
        x, y:
            Feature frame and binary direction labels, both indexed like ``t1``.
        t1:
            First-touch series for purging / embargoing.
        n_splits, embargo_pct, sample_weight:
            Passed through to :func:`purged_cv_predict`.

        Returns
        -------
        pd.Series
            Signed out-of-fold position per observation.

        Raises
        ------
        ValueError
            If inputs are mis-aligned, non-finite, or not binary.
        """
        if not x.index.equals(y.index):
            raise ValueError("features and labels must share the same index")
        if not np.isfinite(x.to_numpy(dtype=float)).all():
            raise ValueError("features contain non-finite values")
        _check_binary(y)

        proba = purged_cv_predict(
            self._make_estimator(),
            x,
            y,
            t1=t1,
            n_splits=n_splits,
            embargo_pct=embargo_pct,
            sample_weight=sample_weight,
        )
        up_class = proba.columns.max()  # the +1/up class
        positions = _positions_from_up_prob(
            proba[up_class].to_numpy(), step_size=self._config.step_size
        )
        return pd.Series(positions, index=proba.index, name="signal")

    def _make_estimator(self) -> Any:
        """Return the injected estimator or a fresh default forest."""
        if self._injected is not None:
            return self._injected
        return _default_estimator(self._config)

    def _require_fitted(self, x: pd.DataFrame) -> Any:
        """Return the fitted estimator, validating feature alignment."""
        if self._estimator is None:
            raise RuntimeError("RandomForestSignal is not fitted")
        if list(x.columns) != self._feature_names:
            raise ValueError("features columns must match the training columns and order")
        return self._estimator
