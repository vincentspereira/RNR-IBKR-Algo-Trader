"""Tests for the tree-ensemble directional signal (Phase 5.D.1).

* TreeSignalConfig -- hyper-parameter validation.
* _positions_from_up_prob -- the up-probability -> signed-size math, recovered
  exactly (zero at 0.5, antisymmetric in p <-> 1-p, grid discretisation).
* RandomForestSignal.signal / predict_proba -- a deterministic stub estimator
  (P(up) = first feature) gives exact, model-free assertions on the live path.
* RandomForestSignal.oof_signal -- a real random forest on a separable directional
  problem recovers the label direction out-of-fold (the honest backtest path).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.meta_labelling import bet_size_from_prob
from core_trading.signals.ml.trees import (
    RandomForestSignal,
    TreeSignalConfig,
    _positions_from_up_prob,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


class _StubClassifier:
    """Deterministic 2-class stub: ``P(up) = clip(feature[0], 0, 1)``.

    Class order is ``np.unique(y)`` ascending (e.g. ``[-1, 1]``), so column 1 is
    the up class -- matching what RandomForestSignal reads via ``argmax(classes_)``.
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
        p = np.clip(x[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - p, p])


def _stub_dataset() -> tuple[pd.DataFrame, pd.Series]:
    idx = _bdays(6)
    x = pd.DataFrame(
        {"p": [0.9, 0.1, 0.7, 0.2, 0.95, 0.3], "b": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]},
        index=idx,
    )
    y = pd.Series([1, -1, 1, -1, 1, -1], index=idx)
    return x, y


# ---------------------------------------------------------------------------
# TreeSignalConfig
# ---------------------------------------------------------------------------


class TestTreeSignalConfig:
    def test_defaults_valid(self) -> None:
        cfg = TreeSignalConfig()
        assert cfg.n_estimators == 200
        assert cfg.class_weight == "balanced_subsample"

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"n_estimators": 0}, "n_estimators must be >= 1"),
            ({"max_features": "bogus"}, "max_features string"),
            ({"max_features": 0}, "max_features int"),
            ({"max_features": 1.5}, "max_features float"),
            ({"max_depth": 0}, "max_depth must be None or >= 1"),
            ({"min_samples_leaf": 0}, "min_samples_leaf must be >= 1"),
            ({"class_weight": "weird"}, "class_weight must be"),
            ({"step_size": -0.1}, "step_size must be in"),
        ],
    )
    def test_validation(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            TreeSignalConfig(**kwargs)

    @pytest.mark.parametrize("max_features", ["sqrt", "log2", None, 1, 0.5])
    def test_max_features_accepted(self, max_features: object) -> None:
        assert TreeSignalConfig(max_features=max_features).max_features == max_features


# ---------------------------------------------------------------------------
# _positions_from_up_prob
# ---------------------------------------------------------------------------


class TestPositionsFromUpProb:
    def test_no_conviction_is_zero(self) -> None:
        assert float(_positions_from_up_prob(np.array([0.5]), step_size=0.0)[0]) == pytest.approx(
            0.0
        )

    def test_up_and_down_are_signed(self) -> None:
        pos = _positions_from_up_prob(np.array([0.8, 0.2]), step_size=0.0)
        assert pos[0] > 0.0  # up conviction -> long
        assert pos[1] < 0.0  # down conviction -> short

    def test_antisymmetric(self) -> None:
        up = float(_positions_from_up_prob(np.array([0.8]), step_size=0.0)[0])
        down = float(_positions_from_up_prob(np.array([0.2]), step_size=0.0)[0])
        # both have predicted-class probability 0.8; opposite directions.
        assert down == pytest.approx(-up)
        assert up == pytest.approx(float(bet_size_from_prob(0.8)))

    def test_step_size_discretises(self) -> None:
        pos = _positions_from_up_prob(np.array([0.8]), step_size=0.25)
        assert float(pos[0]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# RandomForestSignal -- deterministic stub (live path)
# ---------------------------------------------------------------------------


class TestRandomForestSignalStub:
    def test_lifecycle_and_classes(self) -> None:
        x, y = _stub_dataset()
        cfg = TreeSignalConfig(step_size=0.0)
        model = RandomForestSignal(config=cfg, estimator=_StubClassifier())
        assert not model.fitted
        assert model.config is cfg
        with pytest.raises(RuntimeError, match="not fitted"):
            _ = model.classes_
        model.fit(x, y)
        assert model.fitted
        assert list(model.classes_) == [-1, 1]

    def test_predict_proba_is_up_probability(self) -> None:
        x, y = _stub_dataset()
        model = RandomForestSignal(estimator=_StubClassifier()).fit(x, y)
        proba = model.predict_proba(x)
        np.testing.assert_allclose(proba.to_numpy(), x["p"].to_numpy())

    def test_signal_sign_and_symmetry(self) -> None:
        x, y = _stub_dataset()
        model = RandomForestSignal(estimator=_StubClassifier()).fit(x, y)
        sig = model.signal(x)
        # p=0.9 (long) and p=0.1 (short) share predicted-class prob 0.9.
        assert sig.iloc[0] > 0.0
        assert sig.iloc[1] < 0.0
        assert sig.iloc[1] == pytest.approx(-sig.iloc[0])

    def test_signal_step_size(self) -> None:
        x, y = _stub_dataset()
        cfg = TreeSignalConfig(step_size=0.25)
        model = RandomForestSignal(config=cfg, estimator=_StubClassifier()).fit(x, y)
        sig = model.signal(x)
        nonzero = sig[sig != 0.0].to_numpy()
        np.testing.assert_allclose(nonzero / 0.25, np.round(nonzero / 0.25))

    def test_sample_weight_forwarded(self) -> None:
        x, y = _stub_dataset()
        stub = _StubClassifier()
        weights = pd.Series(np.arange(1.0, 7.0), index=x.index)
        RandomForestSignal(estimator=stub).fit(x, y, sample_weight=weights)
        np.testing.assert_allclose(stub.seen_sample_weight, weights.to_numpy())

    def test_fit_validation(self) -> None:
        x, y = _stub_dataset()
        model = RandomForestSignal(estimator=_StubClassifier())
        with pytest.raises(ValueError, match="non-empty"):
            model.fit(pd.DataFrame({"p": []}), pd.Series([], dtype=float))
        with pytest.raises(ValueError, match="share the same index"):
            model.fit(x, y.set_axis(_bdays(6) + pd.Timedelta(days=1)))
        bad = x.copy()
        bad.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            model.fit(bad, y)

    def test_non_binary_labels_raise(self) -> None:
        idx = _bdays(6)
        x = pd.DataFrame({"p": [0.1, 0.5, 0.9, 0.2, 0.6, 0.8]}, index=idx)
        y = pd.Series([-1, 0, 1, -1, 0, 1], index=idx)  # flat 0s not dropped
        with pytest.raises(ValueError, match="exactly 2 label classes"):
            RandomForestSignal(estimator=_StubClassifier()).fit(x, y)

    def test_predict_before_fit_and_column_mismatch(self) -> None:
        x, y = _stub_dataset()
        with pytest.raises(RuntimeError, match="not fitted"):
            RandomForestSignal(estimator=_StubClassifier()).predict_proba(x)
        model = RandomForestSignal(estimator=_StubClassifier()).fit(x, y)
        with pytest.raises(ValueError, match="match the training columns"):
            model.predict_proba(x.rename(columns={"b": "other"}))


# ---------------------------------------------------------------------------
# RandomForestSignal -- real forest out-of-fold (backtest path)
# ---------------------------------------------------------------------------


def _directional_panel(n: int = 40) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    cal = _bdays(n + 1)
    starts = cal[:n]
    labels = np.tile([-1, 1], n // 2)
    sig = ((labels + 1) // 2).astype(float)  # up -> 1.0, down -> 0.0
    x = pd.DataFrame({"sig": sig}, index=starts)
    y = pd.Series(labels, index=starts, name="bin")
    t1 = pd.Series(cal[1 : n + 1], index=starts, name="t1")
    return x, y, t1


def _signal_model() -> RandomForestSignal:
    return RandomForestSignal(config=TreeSignalConfig(n_estimators=40, random_state=0))


class TestRandomForestSignalOOF:
    def test_recovers_direction_out_of_fold(self) -> None:
        x, y, t1 = _directional_panel()
        positions = _signal_model().oof_signal(x, y, t1=t1, n_splits=4)
        assert list(positions.index) == list(x.index)
        assert (positions.abs() <= 1.0).all()
        sign_match = float((np.sign(positions.to_numpy()) == np.sign(y.to_numpy())).mean())
        assert sign_match >= 0.9

    def test_oof_sample_weight_path(self) -> None:
        x, y, t1 = _directional_panel()
        weights = pd.Series(np.linspace(0.5, 1.5, len(x)), index=x.index)
        positions = _signal_model().oof_signal(x, y, t1=t1, n_splits=4, sample_weight=weights)
        assert len(positions) == len(x)

    def test_oof_validation(self) -> None:
        x, y, t1 = _directional_panel()
        model = _signal_model()
        with pytest.raises(ValueError, match="share the same index"):
            model.oof_signal(x, y.iloc[:-1], t1=t1, n_splits=4)
        bad = x.copy()
        bad.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            model.oof_signal(bad, y, t1=t1, n_splits=4)
        flat = y.copy()
        flat.iloc[:5] = 0
        with pytest.raises(ValueError, match="exactly 2 label classes"):
            model.oof_signal(x, flat, t1=t1, n_splits=4)
