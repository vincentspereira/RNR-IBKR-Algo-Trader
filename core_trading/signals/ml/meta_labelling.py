"""Meta-labelling: a secondary model that sizes a primary signal (Phase 5.D.5).

Meta-labelling is Marcos Lopez de Prado's two-stage architecture (AFML ch. 3).
A *primary* model decides the **side** of each bet (long / short); a *secondary*
("meta") model then decides **whether to act** on that side and **how large** the
bet should be. The secondary model is a binary classifier trained on the
``{0, 1}`` meta-labels produced by :func:`core_trading.signals.ml.labeling.get_bins`
with a ``side`` series -- 1 iff acting on the primary side was profitable.

Separating *side* from *size* lets the primary model keep a high recall (it can
fire often) while the meta-model lifts precision (it vetoes the unprofitable
fires and concentrates capital on the high-confidence ones). The same primary
signal can therefore be reused with different meta-models.

Components
----------
1. :func:`bet_size_from_prob` -- map a predicted probability to a bet size in
   ``(-1, 1)`` via the de Prado z-score / Gaussian-CDF transform (AFML snippet
   10.1), with optional discretisation onto a step grid (AFML snippet 10.3) to
   curb over-trading from tiny size changes.
2. :class:`MetaLabelConfig` -- frozen hyper-parameters for the default random
   forest and the bet-sizing gate.
3. :class:`MetaLabeler` -- fit the secondary classifier on event features and
   meta-labels, then emit act / no-act decisions and signed bet sizes for a
   primary ``side`` series.

This is the *model* layer of Phase 5.D; it consumes the labels from the 5.D
labeling foundation. Leakage-aware evaluation (purged / embargoed K-fold CV,
AFML ch. 7) and feature importance (MDI / MDA, AFML ch. 8) are deliberately a
later 5.D batch -- this module keeps to the fit / size contract.

``scikit-learn`` is lazy-imported inside the methods that need it, mirroring the
``statsmodels`` handling elsewhere in Phase 5, so the module is importable in
minimal environments and only pulls the heavy dependency when a model is fit.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 3 (meta-labelling) and Chapter 10 (bet sizing from predicted
  probabilities, snippets 10.1-10.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__all__ = [
    "MetaLabelConfig",
    "MetaLabeler",
    "bet_size_from_prob",
]


# ---------------------------------------------------------------------------
# 1. Bet sizing from a predicted probability (AFML snippets 10.1 / 10.3)
# ---------------------------------------------------------------------------


def bet_size_from_prob(
    prob: float | np.ndarray | pd.Series,
    *,
    num_classes: int = 2,
    step_size: float = 0.0,
) -> np.ndarray:
    """Map a predicted probability to a bet size in ``(-1, 1)`` (AFML snippet 10.1).

    The size is the signed deviation of the probability from the no-information
    level ``1 / num_classes``, scaled by its statistical significance::

        z    = (prob - 1 / num_classes) / sqrt(prob * (1 - prob))
        size = 2 * Phi(z) - 1

    where ``Phi`` is the standard-normal CDF. The size is 0 when ``prob`` equals
    ``1 / num_classes`` (no edge), approaches ``+1`` as ``prob -> 1`` and ``-1``
    as ``prob -> 0``. Probabilities are clipped just inside ``(0, 1)`` so the
    z-score never divides by zero (``predict_proba`` can return exactly 0 or 1).

    Parameters
    ----------
    prob:
        Predicted probability (or array / Series of them) of the class whose bet
        size is wanted. For meta-labelling this is ``P(act = 1)``.
    num_classes:
        Number of classes the probability is drawn from (>= 2). Sets the
        no-information reference ``1 / num_classes``.
    step_size:
        Discretisation grid in ``[0, 1]``. When > 0 the size is rounded to the
        nearest multiple of ``step_size`` (AFML snippet 10.3) to avoid churning
        on negligible probability changes. 0 leaves the size continuous.

    Returns
    -------
    np.ndarray
        The bet size(s); same shape as ``prob`` (0-d for a scalar input).

    Raises
    ------
    ValueError
        If ``num_classes < 2``, ``step_size`` is outside ``[0, 1]``, or ``prob``
        contains non-finite values.
    """
    if num_classes < 2:
        raise ValueError("num_classes must be >= 2")
    if not 0.0 <= step_size <= 1.0:
        raise ValueError("step_size must be in [0, 1]")

    from scipy.stats import norm

    p = np.asarray(prob, dtype=float)
    if not np.isfinite(p).all():
        raise ValueError("prob must be finite")

    eps = 1e-12
    p = np.clip(p, eps, 1.0 - eps)
    z = (p - 1.0 / num_classes) / np.sqrt(p * (1.0 - p))
    size = 2.0 * np.asarray(norm.cdf(z), dtype=float) - 1.0

    if step_size > 0.0:
        size = np.round(size / step_size) * step_size
        size = np.clip(size, -1.0, 1.0)

    result: np.ndarray = np.asarray(size, dtype=float)
    return result


# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetaLabelConfig:
    """Hyper-parameters for :class:`MetaLabeler`.

    Attributes
    ----------
    threshold:
        Probability gate in ``(0, 1)``: act on a bet only when
        ``P(act = 1) >= threshold``. Should be ``>= 0.5`` so that acting events
        are the model's predicted positive class.
    step_size:
        Bet-size discretisation grid passed to :func:`bet_size_from_prob`.
    n_estimators:
        Number of trees in the default random forest (>= 1).
    max_depth:
        Maximum tree depth for the default forest (None = unbounded, else >= 1).
    min_samples_leaf:
        Minimum samples per leaf for the default forest (>= 1); a regulariser
        against the noisy financial labels.
    random_state:
        Seed for the default forest, for reproducibility.
    """

    threshold: float = 0.5
    step_size: float = 0.0
    n_estimators: int = 200
    max_depth: int | None = None
    min_samples_leaf: int = 1
    random_state: int = 0

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("threshold must be in (0, 1)")
        if not 0.0 <= self.step_size <= 1.0:
            raise ValueError("step_size must be in [0, 1]")
        if self.n_estimators < 1:
            raise ValueError("n_estimators must be >= 1")
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError("max_depth must be None or >= 1")
        if self.min_samples_leaf < 1:
            raise ValueError("min_samples_leaf must be >= 1")


def _default_estimator(config: MetaLabelConfig) -> Any:
    """Build the default random-forest secondary classifier (lazy sklearn import)."""
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        random_state=config.random_state,
    )


# ---------------------------------------------------------------------------
# 3. The meta-labelling model
# ---------------------------------------------------------------------------


class MetaLabeler:
    """Secondary classifier that decides whether to act on -- and size -- a bet.

    Fit the model on a feature matrix and the binary meta-labels from
    :func:`core_trading.signals.ml.labeling.get_bins` (built with a primary
    ``side``). The fitted model then yields, for fresh event features:

    * :meth:`predict_proba` -- ``P(act = 1)`` per event,
    * :meth:`act` -- the boolean act / no-act gate at the configured threshold,
    * :meth:`bet_sizes` -- signed position sizes in ``[-1, 1]`` (the bet-size
      magnitude from :func:`bet_size_from_prob`, zeroed where the gate is off and
      multiplied by the primary ``side``),
    * :meth:`feature_importances` -- the estimator's importances per feature.

    Parameters
    ----------
    config:
        Hyper-parameters; defaults to :class:`MetaLabelConfig`.
    estimator:
        An optional pre-built classifier exposing the scikit-learn
        ``fit`` / ``predict_proba`` / ``classes_`` API. When omitted a
        :class:`~sklearn.ensemble.RandomForestClassifier` is built from
        ``config``. Injecting an estimator is the seam used by the tests and by
        callers who want a different model (e.g. gradient boosting).
    """

    def __init__(
        self,
        *,
        config: MetaLabelConfig | None = None,
        estimator: Any | None = None,
    ) -> None:
        self._config = config if config is not None else MetaLabelConfig()
        self._injected_estimator = estimator
        self._estimator: Any | None = None
        self._classes: np.ndarray | None = None
        self._feature_names: list[Any] = []

    @property
    def config(self) -> MetaLabelConfig:
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
            raise RuntimeError("MetaLabeler is not fitted")
        return self._classes

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        *,
        sample_weight: pd.Series | None = None,
    ) -> MetaLabeler:
        """Fit the secondary classifier on event features and meta-labels.

        Parameters
        ----------
        features:
            Event feature matrix, indexed by event start (one row per event).
        labels:
            Binary meta-labels in ``{0, 1}`` (the ``bin`` column of
            :func:`get_bins`), sharing ``features``' index.
        sample_weight:
            Optional per-event weights (e.g. AFML return-attribution or
            uniqueness weights), sharing the index.

        Returns
        -------
        MetaLabeler
            ``self``, fitted.

        Raises
        ------
        ValueError
            If inputs are empty, mis-aligned, non-finite, or the labels are not
            binary.
        """
        if features.empty:
            raise ValueError("features must be non-empty")
        if not features.index.equals(labels.index):
            raise ValueError("features and labels must share the same index")

        x = features.to_numpy(dtype=float)
        if not np.isfinite(x).all():
            raise ValueError("features contain non-finite values")
        y = labels.to_numpy()

        estimator = (
            self._injected_estimator
            if self._injected_estimator is not None
            else _default_estimator(self._config)
        )
        weight = (
            None
            if sample_weight is None
            else sample_weight.reindex(labels.index).to_numpy(dtype=float)
        )
        estimator.fit(x, y, sample_weight=weight)

        classes = np.asarray(estimator.classes_)
        if classes.shape[0] != 2:
            raise ValueError("meta-labelling requires exactly 2 classes")

        self._estimator = estimator
        self._classes = classes
        self._feature_names = list(features.columns)
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.Series:
        """``P(act = 1)`` per event (the probability of the positive class).

        Parameters
        ----------
        features:
            Event features with the same columns (in the same order) as at fit.

        Returns
        -------
        pd.Series
            Positive-class probability indexed like ``features``.
        """
        estimator = self._require_fitted(features)
        proba = np.asarray(estimator.predict_proba(features.to_numpy(dtype=float)), dtype=float)
        # sklearn sorts classes_ ascending, so the positive meta-label (1) is last.
        pos = int(np.argmax(self.classes_))
        return pd.Series(proba[:, pos], index=features.index, name="prob")

    def act(self, features: pd.DataFrame, *, threshold: float | None = None) -> pd.Series:
        """Boolean act / no-act gate: ``P(act = 1) >= threshold`` (AFML ch. 3).

        Parameters
        ----------
        features:
            Event features (see :meth:`predict_proba`).
        threshold:
            Override the configured probability gate for this call.

        Returns
        -------
        pd.Series
            Boolean act decision indexed like ``features``.
        """
        gate = self._config.threshold if threshold is None else threshold
        proba = self.predict_proba(features)
        return pd.Series(proba.to_numpy() >= gate, index=features.index, name="act")

    def bet_sizes(
        self,
        features: pd.DataFrame,
        *,
        side: pd.Series | None = None,
        threshold: float | None = None,
    ) -> pd.Series:
        """Signed bet sizes in ``[-1, 1]`` from the meta-model (AFML ch. 10).

        For each event the bet-size magnitude is :func:`bet_size_from_prob` of
        ``P(act = 1)``, set to 0 where the act gate is off, and multiplied by the
        primary ``side`` (if given) to produce a directional position size.

        Parameters
        ----------
        features:
            Event features (see :meth:`predict_proba`).
        side:
            Optional primary-side series in ``{-1, +1}`` to direct the size; when
            omitted the unsigned magnitude is returned.
        threshold:
            Override the configured act gate for this call.

        Returns
        -------
        pd.Series
            Bet size per event indexed like ``features``.
        """
        gate = self._config.threshold if threshold is None else threshold
        proba = self.predict_proba(features).to_numpy()
        n_classes = int(self.classes_.shape[0])
        magnitude = bet_size_from_prob(
            proba, num_classes=n_classes, step_size=self._config.step_size
        )
        size = np.where(proba >= gate, magnitude, 0.0)
        if side is not None:
            size = size * side.reindex(features.index).to_numpy(dtype=float)
        return pd.Series(size, index=features.index, name="bet_size")

    def feature_importances(self) -> pd.Series:
        """The fitted estimator's feature importances, indexed by feature name.

        Returns
        -------
        pd.Series
            Importances aligned to the training columns, descending.

        Raises
        ------
        RuntimeError
            If the model is not fit or the estimator exposes no importances.
        """
        if self._estimator is None:
            raise RuntimeError("MetaLabeler is not fitted")
        if not hasattr(self._estimator, "feature_importances_"):
            raise RuntimeError("estimator does not expose feature_importances_")
        importances = np.asarray(self._estimator.feature_importances_, dtype=float)
        series = pd.Series(importances, index=pd.Index(self._feature_names), name="importance")
        return series.sort_values(ascending=False)

    def _require_fitted(self, features: pd.DataFrame) -> Any:
        """Return the fitted estimator, validating feature alignment."""
        if self._estimator is None:
            raise RuntimeError("MetaLabeler is not fitted")
        if list(features.columns) != self._feature_names:
            raise ValueError("features columns must match the training columns and order")
        return self._estimator
