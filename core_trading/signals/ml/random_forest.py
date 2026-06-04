"""Bagging / out-of-bag estimation for random forests (Phase 5.D.2).

This module is the **OOB complement** to
:mod:`core_trading.signals.ml.trees` (Phase 5.D.1).  ``trees.py`` builds a
directional signal from out-of-fold purged-CV probabilities; this module adds
the *out-of-bag* generalisation estimate that sklearn produces for free during
the bootstrap.

Why both?  Because they measure different things and the comparison is the
core teaching point of AFML ch. 4 and ch. 7:

* **OOB accuracy** -- each tree scores on the roughly one-third of samples it
  was not trained on.  Conceptually honest, but the "held-out" partition is a
  random bootstrap bag whose time boundaries are completely ignored.  When the
  triple-barrier labels overlap in time (the normal case) a tree trained on
  ``t`` may still see a label whose observation window ``[t0, t1]`` straddles
  the OOB sample -- the label has leaked.  The OOB score is therefore
  *optimistically biased* under overlapping labels.

* **Purged-CV score** -- :func:`core_trading.signals.ml.cross_validation.purged_cv_score`
  enforces that no training label overlaps the held-out period (AFML ch. 7
  purging + embargo).  It is the honest generalisation estimate on financial
  time-series.

:meth:`RandomForestOOB.compare_oob_vs_purged_cv` returns both numbers side by
side so the caller can see the optimism gap.  On data with heavily overlapping
labels the OOB accuracy will exceed the purged-CV score; on clean, non-
overlapping labels they converge.

Components
----------
1. :class:`BaggingForestConfig` -- frozen hyper-parameters (n_estimators,
   max_features, max_samples, bootstrap, oob, random_state, etc.).
2. :class:`RandomForestOOB` -- wraps
   :class:`sklearn.ensemble.RandomForestClassifier` with ``oob_score=True``
   and exposes: ``oob_score_``, ``oob_error_``, ``oob_decision_function_``
   (per-sample OOB probabilities), ``feature_importances()``, and a
   directional bet-sized signal that mirrors ``trees.py``'s sizing.

``scikit-learn`` and ``scipy`` are lazy-imported inside the methods that need
them, following the rest of the 5.D package.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 4 (bagging, sequential bootstrap, OOB as a generalisation estimator)
  and Chapter 7 (why purged-CV is more honest than OOB under overlapping
  labels; the OOB optimism gap).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core_trading.signals.ml.cross_validation import purged_cv_score
from core_trading.signals.ml.meta_labelling import bet_size_from_prob

__all__ = [
    "BaggingForestConfig",
    "RandomForestOOB",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaggingForestConfig:
    """Hyper-parameters for :class:`RandomForestOOB`.

    Attributes
    ----------
    n_estimators:
        Number of trees (>= 1).
    max_features:
        Features considered per split: an int (>= 1), a float in ``(0, 1]``,
        one of ``"sqrt"`` / ``"log2"``, or None (all features).
    max_samples:
        Fraction of the training set drawn per bag: a float in ``(0, 1]`` or
        None (all samples, i.e. the standard bootstrap with replacement).  Has
        no effect when ``bootstrap=False``.
    max_depth:
        Maximum tree depth (None = unbounded, else >= 1).
    min_samples_leaf:
        Minimum samples per leaf (>= 1); regularises against noisy financial
        labels (AFML ch. 4).
    class_weight:
        scikit-learn class weighting: None, ``"balanced"`` or
        ``"balanced_subsample"``.
    bootstrap:
        Whether to use bootstrap sampling.  Must be True when ``oob=True``
        (OOB requires bootstrap bags).
    oob:
        Whether to compute out-of-bag estimates (``oob_score=True``).
    random_state:
        Seed for reproducibility.
    step_size:
        Bet-size discretisation grid in ``[0, 1]`` (0 leaves the size
        continuous).
    """

    n_estimators: int = 200
    max_features: int | float | str | None = "sqrt"
    max_samples: float | None = None
    max_depth: int | None = None
    min_samples_leaf: int = 1
    class_weight: str | None = "balanced_subsample"
    bootstrap: bool = True
    oob: bool = True
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
        if self.max_samples is not None and not 0.0 < self.max_samples <= 1.0:
            raise ValueError("max_samples float must be in (0, 1]")
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError("max_depth must be None or >= 1")
        if self.min_samples_leaf < 1:
            raise ValueError("min_samples_leaf must be >= 1")
        if self.class_weight is not None and self.class_weight not in {
            "balanced",
            "balanced_subsample",
        }:
            raise ValueError("class_weight must be None, 'balanced' or 'balanced_subsample'")
        if self.oob and not self.bootstrap:
            raise ValueError("oob=True requires bootstrap=True")
        if not 0.0 <= self.step_size <= 1.0:
            raise ValueError("step_size must be in [0, 1]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_binary(y: pd.Series) -> None:
    """Require exactly two label classes."""
    if len(np.unique(y.to_numpy())) != 2:
        raise ValueError(
            "directional signal requires exactly 2 label classes (drop flat/0 labels)"
        )


def _positions_from_up_prob(p_up: np.ndarray, *, step_size: float) -> np.ndarray:
    """Signed bet sizes from the up-probability (AFML snippet 10.2).

    Mirrors the same helper in :mod:`core_trading.signals.ml.trees` so the
    live signal from :class:`RandomForestOOB` is sized identically.
    """
    p = np.asarray(p_up, dtype=float)
    direction = np.where(p >= 0.5, 1.0, -1.0)
    prob_predicted = np.where(p >= 0.5, p, 1.0 - p)
    magnitude = bet_size_from_prob(prob_predicted, num_classes=2, step_size=step_size)
    result: np.ndarray = np.asarray(direction * magnitude, dtype=float)
    return result


def _build_estimator(config: BaggingForestConfig) -> Any:
    """Construct a :class:`~sklearn.ensemble.RandomForestClassifier` from *config*."""
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=config.n_estimators,
        max_features=config.max_features,
        max_samples=config.max_samples,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        class_weight=config.class_weight,
        bootstrap=config.bootstrap,
        oob_score=config.oob,
        random_state=config.random_state,
    )


# ---------------------------------------------------------------------------
# The OOB-aware forest
# ---------------------------------------------------------------------------


class RandomForestOOB:
    """Random forest with out-of-bag error estimation (AFML ch. 4 / ch. 7).

    After :meth:`fit`, the following read-only properties are available when
    ``config.oob=True``:

    * :attr:`oob_score_` -- scalar OOB accuracy (fraction of OOB samples
      correctly classified).  Optimistically biased under overlapping labels;
      see :meth:`compare_oob_vs_purged_cv` for the honest companion.
    * :attr:`oob_error_` -- ``1 - oob_score_`` (the OOB misclassification
      rate).
    * :attr:`oob_decision_function_` -- per-sample OOB predicted probability
      array of shape ``(n_samples, n_classes)`` (sklearn's attribute passed
      through).

    Parameters
    ----------
    config:
        Hyper-parameters; defaults to :class:`BaggingForestConfig`.
    estimator:
        An optional pre-built scikit-learn classifier.  When supplied it
        replaces the default forest.  The injected estimator is the test seam
        (a deterministic stub or a pre-configured forest) -- mirroring
        ``trees.py``.
    """

    def __init__(
        self,
        *,
        config: BaggingForestConfig | None = None,
        estimator: Any | None = None,
    ) -> None:
        self._config = config if config is not None else BaggingForestConfig()
        self._injected = estimator
        self._estimator: Any | None = None
        self._classes: np.ndarray | None = None
        self._feature_names: list[Any] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> BaggingForestConfig:
        """The model's hyper-parameters."""
        return self._config

    @property
    def fitted(self) -> bool:
        """Whether :meth:`fit` has been called."""
        return self._estimator is not None

    @property
    def classes_(self) -> np.ndarray:
        """The fitted class labels (ascending).

        Raises
        ------
        RuntimeError
            If the model has not been fit.
        """
        if self._classes is None:
            raise RuntimeError("RandomForestOOB is not fitted")
        return self._classes

    @property
    def oob_score_(self) -> float:
        """OOB accuracy (fraction correct on OOB samples).

        Optimistically biased when labels overlap in time; use
        :meth:`compare_oob_vs_purged_cv` to see the honest purged-CV score.

        Raises
        ------
        RuntimeError
            If the model is not fitted or was built with ``oob=False``.
        """
        est = self._require_fitted_estimator()
        if not hasattr(est, "oob_score_"):
            raise RuntimeError(
                "OOB score is not available; fit with config.oob=True (bootstrap=True)"
            )
        return float(est.oob_score_)

    @property
    def oob_error_(self) -> float:
        """OOB misclassification rate: ``1 - oob_score_``.

        Raises
        ------
        RuntimeError
            If the model is not fitted or was built with ``oob=False``.
        """
        return 1.0 - self.oob_score_

    @property
    def oob_decision_function_(self) -> np.ndarray:
        """Per-sample OOB predicted probability matrix (n_samples, n_classes).

        Samples that were in-bag for every tree have a row of zeros (sklearn
        convention).

        Raises
        ------
        RuntimeError
            If the model is not fitted or was built with ``oob=False``.
        """
        est = self._require_fitted_estimator()
        if not hasattr(est, "oob_decision_function_"):
            raise RuntimeError(
                "OOB decision function is not available; fit with config.oob=True"
            )
        return np.asarray(est.oob_decision_function_, dtype=float)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        *,
        sample_weight: pd.Series | None = None,
    ) -> RandomForestOOB:
        """Fit the forest and compute OOB estimates.

        Parameters
        ----------
        x:
            Feature frame indexed by event start.
        y:
            Binary direction labels in ``{-1, +1}`` sharing ``x``'s index.
        sample_weight:
            Optional per-event weights (e.g. from
            :mod:`core_trading.signals.ml.sample_weights`).

        Returns
        -------
        RandomForestOOB
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
        """Up-probability ``P(class = max)`` per row (full-sample model).

        Parameters
        ----------
        x:
            Feature frame with the same columns and order as at fit.

        Returns
        -------
        pd.Series
            Up-probability indexed like ``x``.
        """
        estimator = self._require_fitted(x)
        proba = np.asarray(estimator.predict_proba(x.to_numpy(dtype=float)), dtype=float)
        up = int(np.argmax(self.classes_))
        return pd.Series(proba[:, up], index=x.index, name="prob_up")

    def signal(self, x: pd.DataFrame) -> pd.Series:
        """Live bet-sized directional position in ``[-1, 1]``.

        Mirrors :meth:`core_trading.signals.ml.trees.RandomForestSignal.signal`:
        the up-probability from the full-sample fit is converted to a signed
        position via the de Prado bet-size transform (AFML snippet 10.2).

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

    def feature_importances(self) -> pd.Series:
        """Mean-decrease-impurity importances, sorted descending.

        Returns
        -------
        pd.Series
            Importances aligned to the training columns, descending.

        Raises
        ------
        RuntimeError
            If the model is not fitted or the estimator exposes no importances.
        """
        est = self._require_fitted_estimator()
        if not hasattr(est, "feature_importances_"):
            raise RuntimeError("estimator does not expose feature_importances_")
        importances = np.asarray(est.feature_importances_, dtype=float)
        series = pd.Series(
            importances, index=pd.Index(self._feature_names), name="importance"
        )
        return series.sort_values(ascending=False)

    def compare_oob_vs_purged_cv(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        *,
        t1: pd.Series,
        n_splits: int = 5,
        embargo_pct: float = 0.0,
        scoring: str = "accuracy",
        sample_weight: pd.Series | None = None,
    ) -> dict[str, float]:
        """Return both the OOB score and the purged-CV score for comparison.

        This is the key diagnostic of Phase 5.D.2 (AFML ch. 4 + ch. 7).
        On data with **overlapping** triple-barrier labels the OOB score will
        exceed the purged-CV score because the bootstrap bags do not respect
        the label horizon ``t1``: a tree that was trained on bar ``s`` may have
        labels whose window ``[s, t1(s)]`` overlaps the OOB bar ``t``, leaking
        information.  Purged-CV explicitly drops those observations, so its
        score is lower -- and more honest.

        On non-overlapping (e.g. daily) labels the two numbers converge.

        The method re-fits a fresh estimator clone for the purged-CV pass; the
        already-fitted ``self._estimator`` contributes the OOB score, so the
        comparison is fair: both numbers use the same hyper-parameters and the
        same data.

        Parameters
        ----------
        x:
            Feature frame indexed like ``t1``.
        y:
            Binary direction labels in ``{-1, +1}`` indexed like ``t1``.
        t1:
            First-touch series for purging / embargoing.
        n_splits, embargo_pct:
            Passed through to :func:`purged_cv_score`.
        scoring:
            One of ``"accuracy"``, ``"neg_log_loss"``, or ``"f1"``.  Note
            that ``neg_log_loss`` requires ``oob_score`` to also be based on
            log-loss; since :attr:`oob_score_` is always accuracy, prefer
            ``"accuracy"`` for a like-for-like comparison.
        sample_weight:
            Optional per-observation weights, passed to the purged-CV fit.

        Returns
        -------
        dict[str, float]
            ``{"oob_score": ..., "purged_cv_score": ...}`` where
            ``purged_cv_score`` is the mean across folds.

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called first.
        """
        self._require_fitted_estimator()
        oob = self.oob_score_

        cv_scores = purged_cv_score(
            self._make_estimator(),
            x,
            y,
            t1=t1,
            n_splits=n_splits,
            embargo_pct=embargo_pct,
            scoring=scoring,
            sample_weight=sample_weight,
        )
        return {"oob_score": oob, "purged_cv_score": float(np.mean(cv_scores))}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_estimator(self) -> Any:
        """Return the injected estimator or a fresh default forest."""
        if self._injected is not None:
            return self._injected
        return _build_estimator(self._config)

    def _require_fitted_estimator(self) -> Any:
        """Return the fitted estimator; raise if not yet fit."""
        if self._estimator is None:
            raise RuntimeError("RandomForestOOB is not fitted")
        return self._estimator

    def _require_fitted(self, x: pd.DataFrame) -> Any:
        """Return the fitted estimator, validating feature alignment."""
        est = self._require_fitted_estimator()
        if list(x.columns) != self._feature_names:
            raise ValueError("features columns must match the training columns and order")
        return est
