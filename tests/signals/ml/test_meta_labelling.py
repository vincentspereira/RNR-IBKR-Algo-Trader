"""Tests for the meta-labelling model layer (Phase 5.D.5).

Two tiers:

* The bet-sizing transform :func:`bet_size_from_prob` is pure math, verified by
  parameter recovery against an independent ``scipy.stats.norm`` computation, its
  no-edge zero, monotonicity, the ``p <-> 1-p`` antisymmetry, the divide-by-zero
  clipping at ``prob in {0, 1}``, and the discretisation grid.
* :class:`MetaLabeler` is exercised both with a deterministic stub classifier
  (so probabilities -- and therefore act gates and bet sizes -- are known
  exactly) and with the real :class:`~sklearn.ensemble.RandomForestClassifier`
  on a separable problem (so we can assert it recovers the labels and ranks the
  informative feature above noise).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from core_trading.signals.ml.meta_labelling import (
    MetaLabelConfig,
    MetaLabeler,
    bet_size_from_prob,
)


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2021-01-01", periods=n, freq="B")


class _StubClassifier:
    """Deterministic 2-class classifier: ``P(class 1) = clip(feature[0], 0, 1)``.

    Lets the tests assert exact probabilities (and the act / bet-size logic built
    on them) without any model randomness. Exposes the minimal scikit-learn
    surface :class:`MetaLabeler` relies on; deliberately has NO
    ``feature_importances_`` so the "estimator exposes no importances" path is
    reachable.
    """

    def __init__(self) -> None:
        self.classes_: np.ndarray | None = None
        self.seen_sample_weight: np.ndarray | None = None

    def fit(
        self, _x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None
    ) -> _StubClassifier:
        self.classes_ = np.unique(y)
        self.seen_sample_weight = sample_weight
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        p1 = np.clip(x[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - p1, p1])


# ---------------------------------------------------------------------------
# bet_size_from_prob
# ---------------------------------------------------------------------------


class TestBetSizeFromProb:
    def test_num_classes_validation(self) -> None:
        with pytest.raises(ValueError, match="num_classes must be >= 2"):
            bet_size_from_prob(0.6, num_classes=1)

    def test_step_size_validation(self) -> None:
        with pytest.raises(ValueError, match="step_size must be in"):
            bet_size_from_prob(0.6, step_size=1.5)

    def test_non_finite_raises(self) -> None:
        with pytest.raises(ValueError, match="prob must be finite"):
            bet_size_from_prob(np.array([0.5, np.nan]))

    def test_no_edge_is_zero(self) -> None:
        assert float(bet_size_from_prob(0.5)) == pytest.approx(0.0)
        # The no-information level shifts with the number of classes.
        assert float(bet_size_from_prob(1.0 / 3.0, num_classes=3)) == pytest.approx(0.0)

    def test_recovers_de_prado_formula(self) -> None:
        prob = 0.8
        z = (prob - 0.5) / np.sqrt(prob * (1.0 - prob))
        expected = 2.0 * float(norm.cdf(z)) - 1.0
        assert float(bet_size_from_prob(prob)) == pytest.approx(expected)

    def test_monotonic_in_prob(self) -> None:
        sizes = bet_size_from_prob(np.array([0.5, 0.6, 0.7, 0.8, 0.9]))
        assert np.all(np.diff(sizes) > 0.0)

    def test_antisymmetric(self) -> None:
        assert float(bet_size_from_prob(0.8)) == pytest.approx(-float(bet_size_from_prob(0.2)))

    def test_clips_at_unit_probabilities(self) -> None:
        # prob in {0, 1} would divide by zero without clipping; stays finite.
        hi = float(bet_size_from_prob(1.0))
        lo = float(bet_size_from_prob(0.0))
        assert np.isfinite(hi) and hi > 0.999
        assert np.isfinite(lo) and lo < -0.999

    def test_step_size_discretises(self) -> None:
        # continuous size ~0.547 rounds to the nearest 0.25 -> 0.5.
        continuous = float(bet_size_from_prob(0.8))
        assert continuous == pytest.approx(0.5467, abs=1e-3)
        assert float(bet_size_from_prob(0.8, step_size=0.25)) == pytest.approx(0.5)

    def test_array_shape_preserved(self) -> None:
        out = bet_size_from_prob(np.array([0.5, 0.8]))
        assert out.shape == (2,)
        assert float(out[0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# MetaLabelConfig
# ---------------------------------------------------------------------------


class TestMetaLabelConfig:
    def test_defaults_valid(self) -> None:
        cfg = MetaLabelConfig()
        assert cfg.threshold == 0.5
        assert cfg.n_estimators == 200

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"threshold": 0.0}, "threshold must be in"),
            ({"threshold": 1.0}, "threshold must be in"),
            ({"step_size": -0.1}, "step_size must be in"),
            ({"n_estimators": 0}, "n_estimators must be >= 1"),
            ({"max_depth": 0}, "max_depth must be None or >= 1"),
            ({"min_samples_leaf": 0}, "min_samples_leaf must be >= 1"),
        ],
    )
    def test_validation(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            MetaLabelConfig(**kwargs)

    def test_max_depth_none_allowed(self) -> None:
        assert MetaLabelConfig(max_depth=None).max_depth is None


# ---------------------------------------------------------------------------
# MetaLabeler -- deterministic stub estimator
# ---------------------------------------------------------------------------


def _stub_dataset() -> tuple[pd.DataFrame, pd.Series]:
    idx = _index(6)
    features = pd.DataFrame(
        {"p": [0.9, 0.1, 0.7, 0.2, 0.95, 0.3], "noise": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]},
        index=idx,
    )
    labels = pd.Series([1, 0, 1, 0, 1, 0], index=idx)
    return features, labels


class TestMetaLabelerWithStub:
    def test_fitted_flag_and_classes(self) -> None:
        features, labels = _stub_dataset()
        cfg = MetaLabelConfig(threshold=0.55)
        model = MetaLabeler(config=cfg, estimator=_StubClassifier())
        assert not model.fitted
        assert model.config is cfg
        model.fit(features, labels)
        assert model.fitted
        assert list(model.classes_) == [0, 1]

    def test_predict_proba_is_first_feature(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        proba = model.predict_proba(features)
        # The stub maps P(act=1) to the first feature exactly.
        np.testing.assert_allclose(proba.to_numpy(), features["p"].to_numpy())
        assert list(proba.index) == list(features.index)

    def test_act_gate_default_and_override(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        # default threshold 0.5: p >= 0.5 acts.
        assert list(model.act(features)) == [True, False, True, False, True, False]
        # raised threshold vetoes the 0.7 event.
        assert list(model.act(features, threshold=0.8)) == [
            True,
            False,
            False,
            False,
            True,
            False,
        ]

    def test_bet_sizes_zero_below_gate_and_match_formula(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        sizes = model.bet_sizes(features)
        expected = np.where(
            features["p"].to_numpy() >= 0.5,
            bet_size_from_prob(features["p"].to_numpy()),
            0.0,
        )
        np.testing.assert_allclose(sizes.to_numpy(), expected)
        # gated-off events are exactly zero.
        assert sizes.iloc[1] == 0.0

    def test_bet_sizes_directed_by_side(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        side = pd.Series([1.0, 1.0, -1.0, 1.0, -1.0, 1.0], index=features.index)
        sizes = model.bet_sizes(features, side=side)
        # event 2 (p=0.7, acts) carries a short side -> negative size.
        assert sizes.iloc[2] < 0.0
        assert sizes.iloc[0] > 0.0  # long side, acts

    def test_bet_sizes_step_size_discretised(self) -> None:
        features, labels = _stub_dataset()
        cfg = MetaLabelConfig(step_size=0.25)
        model = MetaLabeler(config=cfg, estimator=_StubClassifier()).fit(features, labels)
        sizes = model.bet_sizes(features)
        nonzero = sizes[sizes != 0.0].to_numpy()
        # every size lands on the 0.25 grid.
        np.testing.assert_allclose(nonzero / 0.25, np.round(nonzero / 0.25))

    def test_sample_weight_forwarded(self) -> None:
        features, labels = _stub_dataset()
        stub = _StubClassifier()
        weights = pd.Series(np.arange(1.0, 7.0), index=features.index)
        MetaLabeler(estimator=stub).fit(features, labels, sample_weight=weights)
        assert stub.seen_sample_weight is not None
        np.testing.assert_allclose(stub.seen_sample_weight, weights.to_numpy())

    def test_feature_importances_requires_support(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        with pytest.raises(RuntimeError, match="does not expose feature_importances_"):
            model.feature_importances()


# ---------------------------------------------------------------------------
# MetaLabeler -- input validation / lifecycle
# ---------------------------------------------------------------------------


class TestMetaLabelerValidation:
    def test_classes_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = MetaLabeler().classes_

    def test_predict_before_fit_raises(self) -> None:
        features, _ = _stub_dataset()
        with pytest.raises(RuntimeError, match="not fitted"):
            MetaLabeler().predict_proba(features)

    def test_feature_importances_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            MetaLabeler().feature_importances()

    def test_empty_features_raise(self) -> None:
        empty = pd.DataFrame({"p": []})
        with pytest.raises(ValueError, match="features must be non-empty"):
            MetaLabeler(estimator=_StubClassifier()).fit(empty, pd.Series([], dtype=float))

    def test_misaligned_index_raises(self) -> None:
        features, labels = _stub_dataset()
        labels2 = labels.copy()
        labels2.index = _index(6) + pd.Timedelta(days=1)
        with pytest.raises(ValueError, match="must share the same index"):
            MetaLabeler(estimator=_StubClassifier()).fit(features, labels2)

    def test_non_finite_features_raise(self) -> None:
        features, labels = _stub_dataset()
        features.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            MetaLabeler(estimator=_StubClassifier()).fit(features, labels)

    def test_non_binary_labels_raise(self) -> None:
        idx = _index(6)
        features = pd.DataFrame({"p": [0.1, 0.5, 0.9, 0.2, 0.6, 0.8]}, index=idx)
        labels = pd.Series([0, 1, 2, 0, 1, 2], index=idx)  # 3 classes
        cfg = MetaLabelConfig(n_estimators=10)
        with pytest.raises(ValueError, match="exactly 2 classes"):
            MetaLabeler(config=cfg).fit(features, labels)

    def test_predict_column_mismatch_raises(self) -> None:
        features, labels = _stub_dataset()
        model = MetaLabeler(estimator=_StubClassifier()).fit(features, labels)
        wrong = features.rename(columns={"noise": "other"})
        with pytest.raises(ValueError, match="match the training columns"):
            model.predict_proba(wrong)


# ---------------------------------------------------------------------------
# MetaLabeler -- real random forest on a separable problem
# ---------------------------------------------------------------------------


def _separable_dataset() -> tuple[pd.DataFrame, pd.Series]:
    # signal in [-1, -0.5] -> label 0, in [0.5, 1] -> label 1, split cleanly at 0.
    n = 40
    half = n // 2
    signal = np.concatenate(
        [np.linspace(-1.0, -0.5, half), np.linspace(0.5, 1.0, half)]
    )
    order = np.argsort(np.concatenate([np.arange(half) * 2 + 1, np.arange(half) * 2]))
    signal = signal[order]
    labels = (signal > 0.0).astype(int)
    noise = np.tile([0.0, 1.0], half)
    idx = _index(n)
    features = pd.DataFrame({"signal": signal, "noise": noise}, index=idx)
    return features, pd.Series(labels, index=idx)


class TestMetaLabelerRandomForest:
    def test_recovers_separable_labels(self) -> None:
        features, labels = _separable_dataset()
        cfg = MetaLabelConfig(n_estimators=50, random_state=0)
        model = MetaLabeler(config=cfg).fit(features, labels)
        recovered = model.act(features).astype(int)
        np.testing.assert_array_equal(recovered.to_numpy(), labels.to_numpy())

    def test_informative_feature_ranked_above_noise(self) -> None:
        features, labels = _separable_dataset()
        cfg = MetaLabelConfig(n_estimators=50, random_state=0)
        model = MetaLabeler(config=cfg).fit(features, labels)
        importances = model.feature_importances()
        assert importances.index[0] == "signal"
        assert importances["signal"] > importances["noise"]

    def test_bet_sizes_track_confidence(self) -> None:
        features, labels = _separable_dataset()
        cfg = MetaLabelConfig(n_estimators=50, random_state=0)
        model = MetaLabeler(config=cfg).fit(features, labels)
        side = pd.Series(np.where(labels.to_numpy() == 1, 1.0, -1.0), index=features.index)
        sizes = model.bet_sizes(features, side=side)
        # Longs (label 1) act long, shorts (label 0) are gated off (P(act) < 0.5).
        assert (sizes[labels == 1] > 0.0).all()
        assert (sizes[labels == 0] == 0.0).all()
