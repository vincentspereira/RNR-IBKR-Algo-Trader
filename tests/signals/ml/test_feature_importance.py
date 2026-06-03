"""Tests for AFML ch. 8 feature importance (MDI / MDA / SFI).

The recovery target is the same for all three methods: on a panel with one
informative feature (``sig``, a noisy-but-predictive copy of the label) and one
orthogonal noise feature (``noise``, period-4 vs the label's period-2 -> zero
correlation), each method must rank ``sig`` strictly above ``noise``.

``sig`` is made *imperfect* (about one in seven labels is flipped relative to it)
on purpose: a perfect feature drives the model's loss to ~0, which would make the
MDA permutation denominators degenerate and hide the noise feature's ~0
importance behind division artefacts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.feature_importance import (
    mda_feature_importance,
    mdi_feature_importance,
    single_feature_importance,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _panel(n: int = 48) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    cal = _bdays(n + 1)
    starts = cal[:n]
    base = np.tile([0, 1], n // 2)
    flip = np.arange(n) % 7 == 0  # ~1/7 of labels flipped relative to `sig`
    labels = np.where(flip, 1 - base, base)
    sig = base.astype(float)  # informative but imperfect
    noise = np.tile([0.0, 0.0, 1.0, 1.0], n // 4)  # orthogonal to a period-2 label
    x = pd.DataFrame({"sig": sig, "noise": noise}, index=starts)
    y = pd.Series(labels, index=starts, name="bin")
    t1 = pd.Series(cal[1 : n + 1], index=starts, name="t1")  # 1-bar horizon
    return x, y, t1


def _forest(*, max_features: int | None = None) -> object:
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(n_estimators=60, max_features=max_features, random_state=0)


# ---------------------------------------------------------------------------
# MDI
# ---------------------------------------------------------------------------


class TestMDI:
    def test_requires_fitted_ensemble(self) -> None:
        from sklearn.tree import DecisionTreeClassifier

        tree = DecisionTreeClassifier(random_state=0)
        with pytest.raises(ValueError, match="bagged ensemble"):
            mdi_feature_importance(tree, ["sig", "noise"])

    def test_ranks_signal_above_noise(self) -> None:
        x, y, _ = _panel()
        forest = _forest(max_features=1)
        forest.fit(x.to_numpy(), y.to_numpy())  # type: ignore[attr-defined]
        imp = mdi_feature_importance(forest, list(x.columns))
        assert imp.index[0] == "sig"
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]
        # normalised means sum to 1.
        assert imp["mean"].sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# MDA
# ---------------------------------------------------------------------------


class TestMDA:
    def test_ranks_signal_above_noise_neg_log_loss(self) -> None:
        x, y, t1 = _panel()
        imp = mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4)
        assert imp.index[0] == "sig"
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]

    def test_accuracy_scoring_path(self) -> None:
        x, y, t1 = _panel()
        imp = mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4, scoring="accuracy")
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]

    def test_f1_scoring_path(self) -> None:
        x, y, t1 = _panel()
        imp = mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4, scoring="f1")
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]

    def test_reproducible_with_random_state(self) -> None:
        x, y, t1 = _panel()
        a = mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4, random_state=42)
        b = mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4, random_state=42)
        pd.testing.assert_frame_equal(a, b)

    def test_sample_weight_path(self) -> None:
        x, y, t1 = _panel()
        weights = pd.Series(np.linspace(0.5, 1.5, len(x)), index=x.index)
        imp = mda_feature_importance(
            _forest(), x, y, t1=t1, n_splits=4, scoring="accuracy", sample_weight=weights
        )
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]

    def test_unknown_scoring_raises(self) -> None:
        x, y, t1 = _panel()
        with pytest.raises(ValueError, match="unknown scoring"):
            mda_feature_importance(_forest(), x, y, t1=t1, n_splits=4, scoring="bogus")


# ---------------------------------------------------------------------------
# SFI
# ---------------------------------------------------------------------------


class TestSFI:
    def test_ranks_signal_above_noise(self) -> None:
        x, y, t1 = _panel()
        imp = single_feature_importance(_forest(), x, y, t1=t1, n_splits=4)
        assert imp.index[0] == "sig"
        assert imp.loc["sig", "mean"] > imp.loc["noise", "mean"]

    def test_f1_scoring_path(self) -> None:
        x, y, t1 = _panel()
        imp = single_feature_importance(_forest(), x, y, t1=t1, n_splits=4, scoring="f1")
        assert set(imp.index) == {"sig", "noise"}
        assert np.isfinite(imp["mean"].to_numpy()).all()
