"""Purged, embargoed cross-validation for overlapping labels (5.D, AFML ch. 7).

Standard k-fold cross-validation assumes IID observations. Financial labels
violate that twice over: a triple-barrier label spans ``[t0, t1]`` and overlaps
its neighbours, and serial correlation links a test fold to the observations
immediately after it. Naive k-fold therefore leaks information from the test set
into training -- through labels that straddle the fold boundary and through the
auto-correlated bars right after the fold -- and the out-of-sample score it
reports is optimistically biased.

Lopez de Prado's fix (AFML ch. 7) is two-fold:

* **Purging** -- drop any training observation whose label span overlaps the test
  set's time window. A label that is partly observed inside the test period
  shares information with it and must not be trained on.
* **Embargo** -- additionally drop a small band of training observations
  immediately *after* the test set, to sever the serial-correlation leak that
  purging alone does not catch.

Components
----------
1. :func:`purged_train_times` -- given explicit test periods, the training
   ``t1`` with all overlapping observations purged (AFML snippet 7.1).
2. :class:`PurgedKFold` -- a scikit-learn-compatible cross-validator
   (``split`` / ``get_n_splits``) that purges and embargoes around each
   contiguous test fold (AFML snippet 7.3). Usable anywhere a CV splitter is
   accepted.
3. :func:`purged_cv_score` -- per-fold scores of a scikit-learn classifier under
   :class:`PurgedKFold`, defaulting to ``neg_log_loss`` (the probabilistic score
   de Prado recommends for meta-labelling) and honouring sample weights
   (AFML snippet 7.4).

The ``t1`` input is the first-touch series from
:func:`core_trading.signals.ml.labeling.triple_barrier_events` (its ``t1``
column): index = event start, value = event end. ``scikit-learn`` is
lazy-imported, mirroring the rest of Phase 5.D.

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 7 (Cross-Validation in Finance), snippets 7.1-7.4.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "purged_train_times",
    "PurgedKFold",
    "purged_cv_score",
    "purged_cv_predict",
]


# ---------------------------------------------------------------------------
# 1. Purge training observations overlapping explicit test periods
# ---------------------------------------------------------------------------


def purged_train_times(t1: pd.Series, test_times: pd.Series) -> pd.Series:
    """Purge training observations overlapping the test periods (AFML snippet 7.1).

    A training label ``[t0, t1]`` is dropped when it overlaps any test period
    ``[start, end]`` in any of the three ways: it starts inside the test period,
    it ends inside it, or it envelops it.

    Parameters
    ----------
    t1:
        Training first-touch series (index = event start, value = event end).
    test_times:
        Test periods (index = period start, value = period end).

    Returns
    -------
    pd.Series
        The subset of ``t1`` with all test-overlapping observations removed.
    """
    train = t1.copy(deep=True)
    for start, end in test_times.items():
        starts_within = train[(start <= train.index) & (train.index <= end)].index
        ends_within = train[(start <= train) & (train <= end)].index
        envelops = train[(train.index <= start) & (end <= train)].index
        train = train.drop(starts_within.union(ends_within).union(envelops))
    return train


# ---------------------------------------------------------------------------
# 2. Purged + embargoed K-fold cross-validator
# ---------------------------------------------------------------------------


class PurgedKFold:
    """K-fold cross-validator that purges and embargoes around each test fold.

    Test folds are contiguous blocks of the (time-ordered) observations -- folds
    are never shuffled, because shuffling would destroy the time structure that
    purging and the embargo rely on. For each fold the training set keeps only
    observations whose label window does not overlap the fold's time span, with a
    further ``embargo_pct`` band of post-fold observations removed.

    Implements the scikit-learn splitter protocol (``split`` and
    ``get_n_splits``), so it can be passed to any scikit-learn API that accepts a
    ``cv`` splitter, as well as to :func:`purged_cv_score`.

    Parameters
    ----------
    n_splits:
        Number of folds (>= 2).
    t1:
        First-touch series (index = event start, value = event end), ascending.
        Its index must equal the index of the ``X`` passed to :meth:`split`.
    embargo_pct:
        Fraction of the total observations to embargo immediately after each test
        fold, in ``[0, 1)``.

    Raises
    ------
    ValueError
        If ``n_splits < 2``, ``embargo_pct`` is outside ``[0, 1)``, or ``t1`` is
        not strictly ascending in its index.
    """

    def __init__(self, n_splits: int = 5, *, t1: pd.Series, embargo_pct: float = 0.0) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if not 0.0 <= embargo_pct < 1.0:
            raise ValueError("embargo_pct must be in [0, 1)")
        if not t1.index.is_monotonic_increasing:
            raise ValueError("t1 index must be ascending")
        self.n_splits = n_splits
        self.t1 = t1
        self.embargo_pct = embargo_pct

    def get_n_splits(
        self, _x: Any = None, _y: Any = None, _groups: Any = None
    ) -> int:
        """Number of folds (the scikit-learn splitter protocol)."""
        return self.n_splits

    def split(
        self, x: pd.DataFrame, _y: Any = None, _groups: Any = None
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield ``(train_indices, test_indices)`` for each purged/embargoed fold.

        Parameters
        ----------
        x:
            Feature frame whose index must equal ``t1``'s index (same events in
            the same order).
        _y, _groups:
            Ignored; present for splitter-protocol compatibility.

        Yields
        ------
        tuple[np.ndarray, np.ndarray]
            Integer positional train and test indices into ``x``.

        Raises
        ------
        ValueError
            If ``x``'s index does not match ``t1``'s index.
        """
        if not x.index.equals(self.t1.index):
            raise ValueError("x index must match the t1 index")

        n = x.shape[0]
        indices = np.arange(n)
        embargo = int(n * self.embargo_pct)
        test_ranges = [(block[0], block[-1] + 1) for block in np.array_split(indices, self.n_splits)]

        for start, end in test_ranges:
            test_indices = indices[start:end]
            t0 = self.t1.index[start]  # test fold start time
            test_label_max = self.t1.iloc[test_indices].max()
            max_t1_idx = int(self.t1.index.searchsorted(test_label_max))

            # Left training block: labels that close at or before the fold start.
            left = np.asarray(
                self.t1.index.searchsorted(self.t1[self.t1 <= t0].index), dtype=int
            )
            train_indices = left[left < n]

            # Right training block: resumes after the fold's last label + embargo.
            if max_t1_idx < n:
                right = indices[max_t1_idx + embargo :]
                train_indices = np.concatenate((train_indices, right))

            yield train_indices, test_indices


# ---------------------------------------------------------------------------
# 3. Cross-validated score under PurgedKFold
# ---------------------------------------------------------------------------


def purged_cv_score(
    estimator: Any,
    x: pd.DataFrame,
    y: pd.Series,
    *,
    t1: pd.Series,
    n_splits: int = 5,
    embargo_pct: float = 0.0,
    scoring: str = "neg_log_loss",
    sample_weight: pd.Series | None = None,
) -> np.ndarray:
    """Per-fold scores of a classifier under :class:`PurgedKFold` (AFML 7.4).

    The estimator is freshly cloned and fit on each fold's purged/embargoed
    training set, then scored on the held-out fold. ``neg_log_loss`` (the
    default) is evaluated against the full class set so a fold missing a class
    still scores correctly.

    Parameters
    ----------
    estimator:
        A scikit-learn classifier (cloneable, exposing ``fit`` / ``predict`` /
        ``predict_proba``) -- the same model a
        :class:`~core_trading.signals.ml.meta_labelling.MetaLabeler` would wrap.
    x:
        Feature frame indexed like ``t1``.
    y:
        Integer labels (e.g. the ``bin`` column from ``get_bins``) indexed like
        ``t1``.
    t1:
        First-touch series for purging / embargoing.
    n_splits, embargo_pct:
        Passed through to :class:`PurgedKFold`.
    scoring:
        One of ``"neg_log_loss"``, ``"accuracy"`` or ``"f1"``.
    sample_weight:
        Optional per-observation weights (e.g. from
        :mod:`core_trading.signals.ml.sample_weights`), indexed like ``t1``;
        applied to both fit and score.

    Returns
    -------
    np.ndarray
        One score per fold, in fold order.
    """
    from sklearn.base import clone

    cv = PurgedKFold(n_splits, t1=t1, embargo_pct=embargo_pct)
    classes = np.unique(y.to_numpy())
    scores: list[float] = []

    for train_idx, test_idx in cv.split(x):
        model = clone(estimator)
        x_train = x.iloc[train_idx].to_numpy(dtype=float)
        y_train = y.iloc[train_idx].to_numpy()
        x_test = x.iloc[test_idx].to_numpy(dtype=float)
        y_test = y.iloc[test_idx].to_numpy()

        if sample_weight is None:
            w_train = None
            w_test = None
        else:
            w_train = sample_weight.iloc[train_idx].to_numpy(dtype=float)
            w_test = sample_weight.iloc[test_idx].to_numpy(dtype=float)

        model.fit(x_train, y_train, sample_weight=w_train)
        scores.append(_score_fold(model, x_test, y_test, classes, scoring, w_test))

    result: np.ndarray = np.asarray(scores, dtype=float)
    return result


def purged_cv_predict(
    estimator: Any,
    x: pd.DataFrame,
    y: pd.Series,
    *,
    t1: pd.Series,
    n_splits: int = 5,
    embargo_pct: float = 0.0,
    sample_weight: pd.Series | None = None,
) -> pd.DataFrame:
    """Out-of-fold class probabilities under :class:`PurgedKFold`.

    The leakage-free analogue of scikit-learn's ``cross_val_predict``: for each
    fold the cloned estimator is fit on the purged/embargoed training set and
    predicts probabilities on the held-out fold. Every observation therefore
    receives a probability from a model that never trained on it -- nor on any
    label overlapping it -- which is exactly the signal a backtest may consume
    without look-ahead. Because :class:`PurgedKFold`'s test folds partition the
    observations, every row of ``x`` appears once in the result.

    Parameters
    ----------
    estimator:
        A cloneable scikit-learn classifier (``fit`` / ``predict_proba``).
    x:
        Feature frame indexed like ``t1``.
    y:
        Integer labels indexed like ``t1``.
    t1:
        First-touch series for purging / embargoing.
    n_splits, embargo_pct:
        Passed to :class:`PurgedKFold`.
    sample_weight:
        Optional per-observation training weights indexed like ``t1``.

    Returns
    -------
    pd.DataFrame
        Out-of-fold probabilities indexed by observation, one column per class
        (the union of ``y``'s classes); a fold that never saw a class leaves its
        column at 0 for that fold's rows.
    """
    from sklearn.base import clone

    cv = PurgedKFold(n_splits, t1=t1, embargo_pct=embargo_pct)
    classes = np.unique(y.to_numpy())
    blocks: list[pd.DataFrame] = []

    for train_idx, test_idx in cv.split(x):
        model = clone(estimator)
        x_train = x.iloc[train_idx].to_numpy(dtype=float)
        y_train = y.iloc[train_idx].to_numpy()
        weight = (
            None
            if sample_weight is None
            else sample_weight.iloc[train_idx].to_numpy(dtype=float)
        )
        model.fit(x_train, y_train, sample_weight=weight)

        proba = np.asarray(
            model.predict_proba(x.iloc[test_idx].to_numpy(dtype=float)), dtype=float
        )
        block = pd.DataFrame(0.0, index=x.index[test_idx], columns=classes)
        for col_pos, cls in enumerate(model.classes_):
            block[cls] = proba[:, col_pos]
        blocks.append(block)

    out: pd.DataFrame = pd.concat(blocks).sort_index()
    return out


def _score_fold(
    model: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    classes: np.ndarray,
    scoring: str,
    sample_weight: np.ndarray | None,
) -> float:
    """Score one held-out fold under the requested metric."""
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
