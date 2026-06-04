"""Tests for the bagging / OOB random forest (Phase 5.D.2).

Coverage plan
-------------
* BaggingForestConfig -- hyper-parameter validation (all reject paths + happy
  paths).
* RandomForestOOB.fit -- validation guards (empty, misaligned index, non-
  finite, non-binary).
* RandomForestOOB.oob_score_ / oob_error_ / oob_decision_function_ -- exact
  math against a stub estimator seam; also the not-yet-fitted guard.
* RandomForestOOB.predict_proba / signal -- exact values via a stub that sets
  P(up) = feature[0].
* RandomForestOOB.feature_importances -- shape, index, descending order.
* Real RandomForestClassifier on a perfectly separable binary problem:
  - OOB accuracy > 0.9 (textbook DOD bar).
  - The informative feature ranks above noise in importances.
* compare_oob_vs_purged_cv -- returns two finite scalars; on heavily
  overlapping labels OOB >= purged-CV (the teaching assertion, AFML ch.7).
* Not-fitted guards for all post-fit properties.

Test style mirrors tests/signals/ml/test_trees.py:
  - A deterministic stub estimator seam for model-free assertions.
  - A real RandomForest on synthetic separable data for integration.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.random_forest import (
    BaggingForestConfig,
    RandomForestOOB,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


class _StubClassifier:
    """Deterministic 2-class stub: P(up) = clip(feature[0], 0, 1).

    Mimics sklearn's RandomForestClassifier interface so that
    RandomForestOOB's seam is exercised without fitting a real forest.

    Class ordering: np.unique(y) ascending -> [-1, 1], column 1 = up.
    Exposes oob_score_, oob_decision_function_, and feature_importances_
    as simple deterministic values.
    """

    def __init__(self) -> None:
        self.classes_: np.ndarray | None = None
        self.oob_score_: float = 0.95
        self._n: int = 0

    def fit(
        self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None  # noqa: ARG002
    ) -> _StubClassifier:
        self.classes_ = np.unique(y)
        self._n = x.shape[0]
        n_cols = x.shape[1]
        # feature importances: first feature most important, rest equal
        imp = np.zeros(n_cols)
        imp[0] = 0.6
        if n_cols > 1:
            imp[1:] = 0.4 / (n_cols - 1)
        self.feature_importances_ = imp
        # OOB decision function: column 1 = clip(feature[0], 0, 1)
        p_up = np.clip(x[:, 0], 0.0, 1.0)
        self.oob_decision_function_ = np.column_stack([1.0 - p_up, p_up])
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        p = np.clip(x[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - p, p])


def _stub_dataset() -> tuple[pd.DataFrame, pd.Series]:
    idx = _bdays(6)
    x = pd.DataFrame(
        {"p": [0.9, 0.1, 0.7, 0.2, 0.95, 0.3], "noise": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]},
        index=idx,
    )
    y = pd.Series([1, -1, 1, -1, 1, -1], index=idx)
    return x, y


def _fitted_stub() -> tuple[RandomForestOOB, pd.DataFrame, pd.Series]:
    x, y = _stub_dataset()
    model = RandomForestOOB(estimator=_StubClassifier()).fit(x, y)
    return model, x, y


# ---------------------------------------------------------------------------
# BaggingForestConfig -- validation
# ---------------------------------------------------------------------------


class TestBaggingForestConfig:
    def test_defaults_valid(self) -> None:
        cfg = BaggingForestConfig()
        assert cfg.n_estimators == 200
        assert cfg.oob is True
        assert cfg.bootstrap is True
        assert cfg.step_size == 0.0
        assert cfg.class_weight == "balanced_subsample"

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"n_estimators": 0}, "n_estimators must be >= 1"),
            ({"max_features": "bogus"}, "max_features string"),
            ({"max_features": 0}, "max_features int"),
            ({"max_features": 1.5}, "max_features float"),
            ({"max_samples": 0.0}, "max_samples float"),
            ({"max_samples": 1.1}, "max_samples float"),
            ({"max_depth": 0}, "max_depth must be None or >= 1"),
            ({"min_samples_leaf": 0}, "min_samples_leaf must be >= 1"),
            ({"class_weight": "weird"}, "class_weight must be"),
            ({"oob": True, "bootstrap": False}, "oob=True requires bootstrap=True"),
            ({"step_size": -0.1}, "step_size must be in"),
            ({"step_size": 1.1}, "step_size must be in"),
        ],
    )
    def test_validation_rejects(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            BaggingForestConfig(**kwargs)

    @pytest.mark.parametrize("max_features", ["sqrt", "log2", None, 1, 0.5])
    def test_max_features_accepted(self, max_features: object) -> None:
        cfg = BaggingForestConfig(max_features=max_features)
        assert cfg.max_features == max_features

    def test_max_samples_accepted(self) -> None:
        cfg = BaggingForestConfig(max_samples=0.8)
        assert cfg.max_samples == 0.8

    def test_no_oob_no_bootstrap(self) -> None:
        cfg = BaggingForestConfig(oob=False, bootstrap=False)
        assert cfg.bootstrap is False

    def test_frozen(self) -> None:
        cfg = BaggingForestConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.n_estimators = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Not-fitted guards
# ---------------------------------------------------------------------------


class TestNotFittedGuards:
    def test_classes_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = RandomForestOOB().classes_

    def test_oob_score_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = RandomForestOOB().oob_score_

    def test_oob_error_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = RandomForestOOB().oob_error_

    def test_oob_decision_function_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = RandomForestOOB().oob_decision_function_

    def test_predict_proba_raises(self) -> None:
        x, _ = _stub_dataset()
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestOOB().predict_proba(x)

    def test_signal_raises(self) -> None:
        x, _ = _stub_dataset()
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestOOB().signal(x)

    def test_feature_importances_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestOOB().feature_importances()

    def test_compare_raises(self) -> None:
        x, y = _stub_dataset()
        t1 = pd.Series(_bdays(7)[1:], index=_bdays(6))
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestOOB().compare_oob_vs_purged_cv(x, y, t1=t1)


# ---------------------------------------------------------------------------
# fit -- input validation
# ---------------------------------------------------------------------------


class TestFitValidation:
    def test_empty_raises(self) -> None:
        model = RandomForestOOB(estimator=_StubClassifier())
        with pytest.raises(ValueError, match="non-empty"):
            model.fit(pd.DataFrame({"p": []}), pd.Series([], dtype=float))

    def test_index_mismatch_raises(self) -> None:
        x, y = _stub_dataset()
        model = RandomForestOOB(estimator=_StubClassifier())
        with pytest.raises(ValueError, match="share the same index"):
            model.fit(x, y.set_axis(_bdays(6) + pd.Timedelta(days=1)))

    def test_non_finite_raises(self) -> None:
        x, y = _stub_dataset()
        bad = x.copy()
        bad.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            RandomForestOOB(estimator=_StubClassifier()).fit(bad, y)

    def test_non_binary_raises(self) -> None:
        idx = _bdays(6)
        x = pd.DataFrame({"p": [0.1, 0.5, 0.9, 0.2, 0.6, 0.8]}, index=idx)
        y = pd.Series([-1, 0, 1, -1, 0, 1], index=idx)
        with pytest.raises(ValueError, match="exactly 2 label classes"):
            RandomForestOOB(estimator=_StubClassifier()).fit(x, y)

    def test_column_mismatch_raises(self) -> None:
        model, x, _ = _fitted_stub()
        with pytest.raises(ValueError, match="match the training columns"):
            model.predict_proba(x.rename(columns={"noise": "other"}))


# ---------------------------------------------------------------------------
# OOB properties -- exact values via stub
# ---------------------------------------------------------------------------


class TestOOBPropertiesStub:
    def test_fitted_flag(self) -> None:
        x, y = _stub_dataset()
        model = RandomForestOOB(estimator=_StubClassifier())
        assert model.fitted is False
        model.fit(x, y)
        assert model.fitted is True

    def test_classes_ascending(self) -> None:
        model, _, _ = _fitted_stub()
        assert list(model.classes_) == [-1, 1]

    def test_oob_score_matches_stub(self) -> None:
        model, _, _ = _fitted_stub()
        assert model.oob_score_ == pytest.approx(0.95)

    def test_oob_error_complements_score(self) -> None:
        model, _, _ = _fitted_stub()
        assert model.oob_error_ == pytest.approx(1.0 - model.oob_score_)

    def test_oob_decision_function_shape(self) -> None:
        model, x, _ = _fitted_stub()
        oob_df = model.oob_decision_function_
        assert oob_df.shape == (len(x), 2)
        # columns should sum to 1 (approximately) for valid probability rows
        np.testing.assert_allclose(oob_df.sum(axis=1), np.ones(len(x)), atol=1e-12)

    def test_config_property(self) -> None:
        cfg = BaggingForestConfig(n_estimators=10)
        model = RandomForestOOB(config=cfg, estimator=_StubClassifier())
        assert model.config is cfg

    def test_oob_score_unavailable_without_oob(self) -> None:
        class _NoOOBStub(_StubClassifier):
            def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> _NoOOBStub:
                super().fit(x, y, sample_weight=sample_weight)
                del self.oob_score_  # simulate bootstrap=False / oob=False
                return self  # type: ignore[return-value]

        x, y = _stub_dataset()
        model = RandomForestOOB(estimator=_NoOOBStub()).fit(x, y)
        with pytest.raises(RuntimeError, match="oob=True"):
            _ = model.oob_score_

    def test_oob_decision_function_unavailable_without_oob(self) -> None:
        class _NoODFStub(_StubClassifier):
            def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> _NoODFStub:
                super().fit(x, y, sample_weight=sample_weight)
                del self.oob_decision_function_  # simulate oob=False estimator
                return self  # type: ignore[return-value]

        x, y = _stub_dataset()
        model = RandomForestOOB(estimator=_NoODFStub()).fit(x, y)
        with pytest.raises(RuntimeError, match="OOB decision function is not available"):
            _ = model.oob_decision_function_


# ---------------------------------------------------------------------------
# predict_proba / signal -- exact values via stub
# ---------------------------------------------------------------------------


class TestPredictAndSignal:
    def test_predict_proba_returns_up_prob(self) -> None:
        model, x, _ = _fitted_stub()
        proba = model.predict_proba(x)
        np.testing.assert_allclose(proba.to_numpy(), x["p"].to_numpy())

    def test_predict_proba_index(self) -> None:
        model, x, _ = _fitted_stub()
        proba = model.predict_proba(x)
        assert list(proba.index) == list(x.index)

    def test_signal_sign(self) -> None:
        model, x, _ = _fitted_stub()
        sig = model.signal(x)
        # p=0.9 -> long, p=0.1 -> short
        assert sig.iloc[0] > 0.0
        assert sig.iloc[1] < 0.0

    def test_signal_antisymmetric(self) -> None:
        model, x, _ = _fitted_stub()
        sig = model.signal(x)
        # p=0.9 (long) and p=0.1 (short) share predicted-class prob 0.9.
        assert sig.iloc[0] == pytest.approx(-sig.iloc[1])

    def test_signal_step_size(self) -> None:
        cfg = BaggingForestConfig(step_size=0.25)
        x, y = _stub_dataset()
        model = RandomForestOOB(config=cfg, estimator=_StubClassifier()).fit(x, y)
        sig = model.signal(x)
        nonzero = sig[sig != 0.0].to_numpy()
        np.testing.assert_allclose(nonzero / 0.25, np.round(nonzero / 0.25))

    def test_signal_bounds(self) -> None:
        model, x, _ = _fitted_stub()
        sig = model.signal(x)
        assert (sig.abs() <= 1.0).all()

    def test_sample_weight_forwarded(self) -> None:
        class _WeightSpy(_StubClassifier):
            def __init__(self) -> None:
                super().__init__()
                self.seen_weight: np.ndarray | None = None

            def fit(
                self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None
            ) -> _WeightSpy:
                super().fit(x, y, sample_weight=sample_weight)
                self.seen_weight = sample_weight
                return self  # type: ignore[return-value]

        x, y = _stub_dataset()
        spy = _WeightSpy()
        weights = pd.Series(np.arange(1.0, 7.0), index=x.index)
        RandomForestOOB(estimator=spy).fit(x, y, sample_weight=weights)
        np.testing.assert_allclose(spy.seen_weight, weights.to_numpy())


# ---------------------------------------------------------------------------
# feature_importances -- stub
# ---------------------------------------------------------------------------


class TestFeatureImportancesStub:
    def test_shape_and_index(self) -> None:
        model, x, _ = _fitted_stub()
        imp = model.feature_importances()
        assert len(imp) == x.shape[1]
        assert list(imp.index) == sorted(list(imp.index), key=lambda c: imp[c], reverse=True)

    def test_first_feature_is_top(self) -> None:
        model, _, _ = _fitted_stub()
        imp = model.feature_importances()
        assert imp.index[0] == "p"

    def test_no_importances_raises(self) -> None:
        class _NoImpStub(_StubClassifier):
            def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> _NoImpStub:
                super().fit(x, y, sample_weight=sample_weight)
                del self.feature_importances_
                return self  # type: ignore[return-value]

        x, y = _stub_dataset()
        model = RandomForestOOB(estimator=_NoImpStub()).fit(x, y)
        with pytest.raises(RuntimeError, match="feature_importances_"):
            model.feature_importances()


# ---------------------------------------------------------------------------
# Real RandomForestClassifier -- separable problem (textbook DOD)
# ---------------------------------------------------------------------------


def _separable_panel(
    n: int = 60,
    n_noise: int = 3,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """A perfectly separable binary classification panel.

    The first feature is a deterministic signal (0/1 -> down/up).
    Additional ``n_noise`` features are pure N(0,1) noise.
    Labels are non-overlapping (each event ends the next day) to keep
    the fixture clean for the separable-problem assertions.

    Parameters
    ----------
    n:
        Number of observations (must be even).
    n_noise:
        Number of noise features appended alongside the signal.
    seed:
        RNG seed for the noise.
    """
    rng = np.random.default_rng(seed)
    cal = pd.date_range("2020-01-01", periods=n + 1, freq="B")
    starts = cal[:n]
    labels = np.tile([-1, 1], n // 2)
    sig = ((labels + 1) // 2).astype(float)
    noise = rng.standard_normal((n, n_noise))
    cols = {"signal": sig}
    for k in range(n_noise):
        cols[f"noise_{k}"] = noise[:, k]
    x = pd.DataFrame(cols, index=starts)
    y = pd.Series(labels, index=starts, name="bin")
    t1 = pd.Series(cal[1 : n + 1], index=starts, name="t1")
    return x, y, t1


class TestRealForestSeparable:
    def test_oob_accuracy_high(self) -> None:
        x, y, _ = _separable_panel()
        cfg = BaggingForestConfig(n_estimators=100, random_state=0)
        model = RandomForestOOB(config=cfg).fit(x, y)
        assert model.oob_score_ > 0.90, (
            f"OOB accuracy {model.oob_score_:.3f} is below 0.90 on a separable problem"
        )

    def test_informative_feature_ranks_above_noise(self) -> None:
        x, y, _ = _separable_panel(n_noise=3)
        cfg = BaggingForestConfig(n_estimators=100, random_state=0)
        model = RandomForestOOB(config=cfg).fit(x, y)
        imp = model.feature_importances()
        assert imp.index[0] == "signal", (
            f"Top importance feature is '{imp.index[0]}', expected 'signal'"
        )

    def test_oob_error_in_unit_interval(self) -> None:
        x, y, _ = _separable_panel()
        model = RandomForestOOB(config=BaggingForestConfig(n_estimators=50, random_state=1)).fit(x, y)
        assert 0.0 <= model.oob_error_ <= 1.0

    def test_oob_decision_function_shape(self) -> None:
        x, y, _ = _separable_panel()
        model = RandomForestOOB(config=BaggingForestConfig(n_estimators=50, random_state=0)).fit(x, y)
        odf = model.oob_decision_function_
        assert odf.shape == (len(x), 2)

    def test_signal_sign_matches_label(self) -> None:
        x, y, _ = _separable_panel()
        cfg = BaggingForestConfig(n_estimators=100, random_state=0)
        model = RandomForestOOB(config=cfg).fit(x, y)
        sig = model.signal(x)
        sign_match = float((np.sign(sig.to_numpy()) == np.sign(y.to_numpy())).mean())
        assert sign_match >= 0.90


# ---------------------------------------------------------------------------
# compare_oob_vs_purged_cv
# ---------------------------------------------------------------------------


class TestCompareOOBvsPurgedCV:
    def test_returns_two_finite_scalars(self) -> None:
        x, y, t1 = _separable_panel(n=40)
        cfg = BaggingForestConfig(n_estimators=50, random_state=0)
        model = RandomForestOOB(config=cfg).fit(x, y)
        result = model.compare_oob_vs_purged_cv(x, y, t1=t1, n_splits=4)
        assert set(result.keys()) == {"oob_score", "purged_cv_score"}
        assert np.isfinite(result["oob_score"])
        assert np.isfinite(result["purged_cv_score"])

    def test_oob_optimistic_under_overlapping_labels(self) -> None:
        """OOB >= purged-CV on data with heavily overlapping label horizons.

        AFML ch.7 teaching assertion: when triple-barrier labels overlap across
        time, a bootstrap bag does not respect the horizon boundary, so the OOB
        score is optimistically biased.  Purged-CV drops the overlapping
        training observations and therefore scores lower (or equal).

        Construction: we use a 5-day barrier so every label spans 5 business
        days.  With 60 observations spaced 1 day apart the overlap is 4/5 of
        the horizon, which is substantial.  The OOB score is accuracy from the
        full-sample fit; the purged-CV score is mean accuracy across 4 folds on
        the same data.  On a separable problem both numbers are high, but the
        OOB number is higher because it sees leaked labels.
        """
        rng = np.random.default_rng(42)
        n = 80
        cal = pd.date_range("2020-01-01", periods=n + 5, freq="B")
        starts = cal[:n]
        labels = np.tile([-1, 1], n // 2)
        sig = ((labels + 1) // 2).astype(float)
        noise = rng.standard_normal((n, 2))
        x = pd.DataFrame(
            {"signal": sig, "noise_0": noise[:, 0], "noise_1": noise[:, 1]},
            index=starts,
        )
        y = pd.Series(labels, index=starts, name="bin")
        # 5-day barrier: heavy overlap
        t1 = pd.Series(
            [starts[min(i + 5, n - 1)] for i in range(n)],
            index=starts,
            name="t1",
        )

        cfg = BaggingForestConfig(n_estimators=100, random_state=0)
        model = RandomForestOOB(config=cfg).fit(x, y)
        result = model.compare_oob_vs_purged_cv(x, y, t1=t1, n_splits=4, scoring="accuracy")

        oob = result["oob_score"]
        pcv = result["purged_cv_score"]
        assert np.isfinite(oob), "OOB score must be finite"
        assert np.isfinite(pcv), "Purged-CV score must be finite"
        # AFML ch.7: OOB is optimistic under overlapping labels -> oob >= pcv.
        # On a clearly separable problem with 4/5 overlap the gap is reliable.
        assert oob >= pcv, (
            f"Expected OOB ({oob:.4f}) >= purged-CV ({pcv:.4f}) under overlapping labels "
            f"(AFML ch.7); if the gap reversed, increase overlap or n."
        )

    def test_not_fitted_raises(self) -> None:
        x, y, t1 = _separable_panel(n=40)
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestOOB().compare_oob_vs_purged_cv(x, y, t1=t1, n_splits=4)
