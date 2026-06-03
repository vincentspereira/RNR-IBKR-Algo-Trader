"""Feature importance for the 5.D models (Phase 5.D, AFML ch. 8).

Once a classifier is trained on the triple-barrier labels and evaluated under
purged cross-validation, the next question is *which features actually drive it*.
Lopez de Prado (AFML ch. 8) warns that the obvious answer -- the tree ensemble's
built-in importances -- is in-sample and biased, and pairs it with out-of-sample
methods that share credit honestly and survive the substitution effects of
correlated features.

Three complementary methods, all returning a ``mean`` / ``std`` table sorted by
importance:

1. :func:`mdi_feature_importance` -- **Mean Decrease Impurity** (snippet 8.2). The
   ensemble's own split-impurity importances, averaged across trees with the
   standard error of that mean. Fast and in-sample; biased towards high-
   cardinality features and masked by substitution, so it is a first look, not a
   verdict.
2. :func:`mda_feature_importance` -- **Mean Decrease Accuracy** (snippet 8.3).
   Out-of-sample permutation importance computed *under*
   :class:`~core_trading.signals.ml.cross_validation.PurgedKFold`: fit on each
   purged training fold, score the held-out fold, then permute one feature column
   at a time and measure how much the score degrades. The leakage-aware analogue
   of permutation importance.
3. :func:`single_feature_importance` -- **Single Feature Importance** (snippet
   8.4). Each feature's standalone purged-CV score, fit in isolation. Immune to
   substitution effects (no other feature can stand in) but blind to joint
   effects.

``scikit-learn`` is lazy-imported, as elsewhere in 5.D. The MDA permutation uses
an explicit seeded generator (``random_state``) so the result is reproducible --
a deliberate departure from de Prado's reliance on global ``numpy`` random state.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 8 (Feature Importance), snippets 8.2-8.4.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from core_trading.signals.ml.cross_validation import PurgedKFold, purged_cv_score

__all__ = [
    "mdi_feature_importance",
    "mda_feature_importance",
    "single_feature_importance",
]


# ---------------------------------------------------------------------------
# 1. Mean Decrease Impurity (in-sample, snippet 8.2)
# ---------------------------------------------------------------------------


def mdi_feature_importance(forest: Any, feature_names: Sequence[Any]) -> pd.DataFrame:
    """Mean Decrease Impurity from a fitted tree ensemble (AFML snippet 8.2).

    Averages each tree's split-impurity importances and normalises the means to
    sum to 1. Importances of exactly 0 are treated as missing rather than
    averaged in: with ``max_features=1`` (de Prado's recommendation for MDI) a
    tree that never split on a feature leaves it at 0, and counting those zeros
    would understate a feature that is decisive *when chosen*.

    Parameters
    ----------
    forest:
        A fitted bagged ensemble exposing ``estimators_`` (e.g.
        :class:`~sklearn.ensemble.RandomForestClassifier`); ideally fit with
        ``max_features=1`` so the importances are not masked by substitution.
    feature_names:
        Column names in the order the ensemble was trained on.

    Returns
    -------
    pd.DataFrame
        Indexed by feature, with ``mean`` (normalised importance) and ``std``
        (standard error of the per-tree mean), sorted by ``mean`` descending.

    Raises
    ------
    ValueError
        If ``forest`` is not a fitted bagged ensemble.
    """
    if not hasattr(forest, "estimators_"):
        raise ValueError("forest must be a fitted bagged ensemble exposing estimators_")

    per_tree = {i: tree.feature_importances_ for i, tree in enumerate(forest.estimators_)}
    frame = pd.DataFrame.from_dict(per_tree, orient="index")
    frame.columns = list(feature_names)
    frame = frame.replace(0.0, np.nan)  # a tree that never split on a feature

    out = pd.DataFrame(
        {
            "mean": frame.mean(),
            "std": frame.std() * frame.shape[0] ** -0.5,
        }
    )
    total = float(out["mean"].sum())
    if total > 0.0:
        out = out / total
    return out.sort_values("mean", ascending=False)


# ---------------------------------------------------------------------------
# 2. Mean Decrease Accuracy (out-of-sample permutation, snippet 8.3)
# ---------------------------------------------------------------------------


def mda_feature_importance(
    estimator: Any,
    x: pd.DataFrame,
    y: pd.Series,
    *,
    t1: pd.Series,
    n_splits: int = 5,
    embargo_pct: float = 0.0,
    scoring: str = "neg_log_loss",
    sample_weight: pd.Series | None = None,
    random_state: int = 0,
) -> pd.DataFrame:
    """Mean Decrease Accuracy under purged CV (AFML snippet 8.3).

    For each fold the cloned estimator is fit on the purged training set and
    scored on the held-out fold; then each feature column of the held-out fold is
    permuted in turn and re-scored. A feature's importance is the relative score
    degradation it causes -- large when permuting it hurts, near 0 when it does
    not -- averaged across folds.

    Parameters
    ----------
    estimator:
        A cloneable scikit-learn classifier (``fit`` / ``predict`` /
        ``predict_proba``).
    x, y:
        Feature frame and integer labels, both indexed like ``t1``.
    t1:
        First-touch series for purging / embargoing.
    n_splits, embargo_pct:
        Passed to :class:`PurgedKFold`.
    scoring:
        One of ``"neg_log_loss"``, ``"accuracy"`` or ``"f1"``.
    sample_weight:
        Optional per-observation weights indexed like ``t1``.
    random_state:
        Seed for the permutation generator, for reproducibility.

    Returns
    -------
    pd.DataFrame
        Indexed by feature, with ``mean`` and ``std`` of the per-fold importance,
        sorted by ``mean`` descending.
    """
    from sklearn.base import clone

    cv = PurgedKFold(n_splits, t1=t1, embargo_pct=embargo_pct)
    classes = np.unique(y.to_numpy())
    columns = list(x.columns)
    rng = np.random.default_rng(random_state)

    baseline: list[float] = []
    permuted: dict[Any, list[float]] = {col: [] for col in columns}

    for train_idx, test_idx in cv.split(x):
        model = clone(estimator)
        x_train = x.iloc[train_idx]
        y_train = y.iloc[train_idx].to_numpy()
        x_test = x.iloc[test_idx]
        y_test = y.iloc[test_idx].to_numpy()

        if sample_weight is None:
            w_train = None
            w_test = None
        else:
            w_train = sample_weight.iloc[train_idx].to_numpy(dtype=float)
            w_test = sample_weight.iloc[test_idx].to_numpy(dtype=float)

        model.fit(x_train.to_numpy(dtype=float), y_train, sample_weight=w_train)
        baseline.append(_fold_score(model, x_test.to_numpy(dtype=float), y_test, classes, scoring, w_test))

        for col in columns:
            x_perm = x_test.copy()
            x_perm[col] = rng.permutation(x_perm[col].to_numpy())
            permuted[col].append(
                _fold_score(model, x_perm.to_numpy(dtype=float), y_test, classes, scoring, w_test)
            )

    base = pd.Series(baseline, dtype=float)
    perm = pd.DataFrame(permuted, dtype=float)
    diff = perm.rsub(base, axis=0)  # baseline - permuted, per fold
    denom = -perm if scoring == "neg_log_loss" else 1.0 - perm
    denom = denom.where(denom.abs() > 1e-12)  # avoid a divide-by-zero (-> NaN, skipped)
    imp = diff / denom

    out = pd.DataFrame({"mean": imp.mean(), "std": imp.std() * imp.shape[0] ** -0.5})
    return out.sort_values("mean", ascending=False)


def _fold_score(
    model: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    classes: np.ndarray,
    scoring: str,
    sample_weight: np.ndarray | None,
) -> float:
    """Score one fold under the requested metric (mirrors the CV module's scorer)."""
    from sklearn.metrics import accuracy_score, f1_score, log_loss

    if scoring == "neg_log_loss":
        proba = model.predict_proba(x_test)
        return float(-log_loss(y_test, proba, labels=classes, sample_weight=sample_weight))

    pred = model.predict(x_test)
    if scoring == "accuracy":
        return float(accuracy_score(y_test, pred, sample_weight=sample_weight))
    if scoring == "f1":
        return float(f1_score(y_test, pred, sample_weight=sample_weight))
    raise ValueError(f"unknown scoring: {scoring!r}")


# ---------------------------------------------------------------------------
# 3. Single Feature Importance (standalone purged-CV score, snippet 8.4)
# ---------------------------------------------------------------------------


def single_feature_importance(
    estimator: Any,
    x: pd.DataFrame,
    y: pd.Series,
    *,
    t1: pd.Series,
    n_splits: int = 5,
    embargo_pct: float = 0.0,
    scoring: str = "neg_log_loss",
    sample_weight: pd.Series | None = None,
) -> pd.DataFrame:
    """Single Feature Importance: each feature's standalone purged-CV score (8.4).

    Fits the estimator on one feature at a time and reports its cross-validated
    score under :func:`purged_cv_score`. Because every feature is judged alone,
    substitution effects cannot mask one feature with another; the cost is that
    joint (interaction) effects are invisible.

    Parameters
    ----------
    estimator:
        A cloneable scikit-learn classifier.
    x, y:
        Feature frame and integer labels, both indexed like ``t1``.
    t1:
        First-touch series for purging / embargoing.
    n_splits, embargo_pct, scoring, sample_weight:
        Passed through to :func:`purged_cv_score`.

    Returns
    -------
    pd.DataFrame
        Indexed by feature, with ``mean`` and ``std`` of the per-fold score,
        sorted by ``mean`` descending.
    """
    rows: dict[Any, tuple[float, float]] = {}
    for col in x.columns:
        scores = purged_cv_score(
            estimator,
            x[[col]],
            y,
            t1=t1,
            n_splits=n_splits,
            embargo_pct=embargo_pct,
            scoring=scoring,
            sample_weight=sample_weight,
        )
        rows[col] = (float(scores.mean()), float(scores.std() * scores.shape[0] ** -0.5))

    out = pd.DataFrame.from_dict(rows, orient="index", columns=["mean", "std"])
    return out.sort_values("mean", ascending=False)
