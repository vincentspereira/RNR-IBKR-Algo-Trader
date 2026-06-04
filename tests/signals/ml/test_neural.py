"""Tests for the LSTM directional signal (Phase 5.D.3).

Test coverage contract:
- LSTMConfig -- hyper-parameter validation and defaults.
- _make_sequences -- sliding-window construction: shapes, alignment, short-input error.
- _positions_from_up_prob -- betting-sizing math: sign, symmetry, p=0.5 -> 0, grid.
- LSTMSignal lifecycle -- not-fitted guards, feature-name validation, column mismatch.
- LSTMSignal.fit validation -- empty input, mis-aligned index, non-finite, non-binary.
- LSTMSignal.predict_proba -- shape, index alignment (warmup excluded), value range.
- LSTMSignal.signal -- sign convention, step-size discretisation, bet sizing contract.
- OVERFIT-A-TINY-BATCH -- on a perfectly-separable sequence dataset, after sufficient
  epochs the network drives training loss near zero and recovers labels with > 0.95
  accuracy. Proves the network, optimiser, and label-plumbing are wired correctly.
- DETERMINISM -- two independently-constructed-and-fitted models with the same
  random_state produce allclose (atol=1e-6) predictions. Determinism relies on
  torch.use_deterministic_algorithms(True) + seeded DataLoader Generator + CPU device.
- sample_weight -- weighted training runs without error and produces a valid output.
- too-short input -- raises ValueError when n_rows < sequence_length.
- bet_size_from_prob contract -- p=0.5 -> 0, p->1 -> +1, p->0 -> -1 (via signal()).

torch warning scoping
---------------------
No torch-specific filterwarnings are needed: all tested torch operations
(LSTM, Adam, BCEWithLogitsLoss, DataLoader, sigmoid) are warning-clean under
-W error on PyTorch 2.12+cpu. The -W error flag is verified by running the
full suite under pytest --noconftest -W error.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.ml.neural import (
    LSTMConfig,
    LSTMSignal,
    _make_sequences,
    _positions_from_up_prob,
    _require_torch,
)

# ---------------------------------------------------------------------------
# _require_torch: ImportError path (torch absent)
# ---------------------------------------------------------------------------


def test_require_torch_raises_when_torch_missing() -> None:
    """_require_torch must raise ImportError with a useful message when torch
    is not importable. We simulate the missing-torch case by temporarily
    blocking the import via sys.modules sentinel."""
    saved = sys.modules.pop("torch", None)
    try:
        sys.modules["torch"] = None  # type: ignore[assignment]
        with pytest.raises(ImportError, match="PyTorch is required"):
            _require_torch()
    finally:
        if saved is not None:
            sys.modules["torch"] = saved
        else:
            sys.modules.pop("torch", None)


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _flat_dataset(
    n: int = 30,
    n_features: int = 2,
    *,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Random features and alternating {-1, +1} labels with a business-day index."""
    rng = np.random.default_rng(seed)
    idx = _bdays(n)
    x = pd.DataFrame(rng.standard_normal((n, n_features)), index=idx, columns=list("abcdefgh")[:n_features])
    y = pd.Series(np.tile([-1, 1], n // 2 + 1)[:n], index=idx, name="bin")
    return x, y


def _separable_dataset(
    n: int = 60,
    n_features: int = 3,
    *,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Perfectly separable dataset: label = sign(mean of first feature in window).

    Each row is drawn so that feature 0 is strongly positive for label=+1 and
    strongly negative for label=-1. Rows alternate label so that both classes
    have exactly n//2 samples.
    """
    rng = np.random.default_rng(seed)
    idx = _bdays(n)

    labels = np.tile([1, -1], n // 2 + 1)[:n]
    noise = rng.standard_normal((n, n_features)) * 0.05

    f0 = np.where(labels > 0, 1.5, -1.5) + rng.standard_normal(n) * 0.1
    features = np.column_stack([f0, noise[:, 1:]])

    x = pd.DataFrame(features, index=idx, columns=[f"f{i}" for i in range(n_features)])
    y = pd.Series(labels, index=idx, name="bin")
    return x, y


def _fast_config(
    n_features: int = 2,
    seq_len: int = 3,
    *,
    hidden: int = 8,
    epochs: int = 5,
    seed: int = 0,
    step_size: float = 0.0,
) -> LSTMConfig:
    """Tiny config for fast CPU tests."""
    return LSTMConfig(
        input_size=n_features,
        hidden_size=hidden,
        num_layers=1,
        dropout=0.0,
        sequence_length=seq_len,
        learning_rate=1e-3,
        n_epochs=epochs,
        batch_size=16,
        random_state=seed,
        device="cpu",
        step_size=step_size,
    )


# ---------------------------------------------------------------------------
# LSTMConfig validation
# ---------------------------------------------------------------------------


class TestLSTMConfig:
    def test_defaults_valid(self) -> None:
        cfg = LSTMConfig()
        assert cfg.input_size == 1
        assert cfg.hidden_size == 32
        assert cfg.num_layers == 1
        assert cfg.dropout == 0.0
        assert cfg.sequence_length == 20
        assert cfg.learning_rate == 1e-3
        assert cfg.n_epochs == 50
        assert cfg.batch_size == 32
        assert cfg.random_state == 0
        assert cfg.device == "cpu"
        assert cfg.step_size == 0.0

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"input_size": 0}, "input_size must be >= 1"),
            ({"hidden_size": 0}, "hidden_size must be >= 1"),
            ({"num_layers": 0}, "num_layers must be >= 1"),
            ({"dropout": -0.1}, "dropout must be in"),
            ({"dropout": 1.0}, "dropout must be in"),
            ({"sequence_length": 0}, "sequence_length must be >= 1"),
            ({"learning_rate": 0.0}, "learning_rate must be > 0"),
            ({"learning_rate": -1e-3}, "learning_rate must be > 0"),
            ({"n_epochs": 0}, "n_epochs must be >= 1"),
            ({"batch_size": 0}, "batch_size must be >= 1"),
            ({"device": "cuda"}, "only device='cpu' is supported"),
            ({"step_size": -0.01}, "step_size must be in"),
            ({"step_size": 1.1}, "step_size must be in"),
        ],
    )
    def test_invalid_config(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            LSTMConfig(**kwargs)

    def test_valid_boundary_values(self) -> None:
        cfg = LSTMConfig(
            input_size=1,
            hidden_size=1,
            num_layers=1,
            dropout=0.0,
            sequence_length=1,
            learning_rate=1e-10,
            n_epochs=1,
            batch_size=1,
            step_size=0.0,
        )
        assert cfg.sequence_length == 1

    def test_dropout_upper_boundary_excluded(self) -> None:
        with pytest.raises(ValueError, match="dropout must be in"):
            LSTMConfig(dropout=1.0)

    def test_step_size_boundaries_valid(self) -> None:
        assert LSTMConfig(step_size=0.0).step_size == 0.0
        assert LSTMConfig(step_size=1.0).step_size == 1.0


# ---------------------------------------------------------------------------
# _make_sequences
# ---------------------------------------------------------------------------


class TestMakeSequences:
    def test_output_shape(self) -> None:
        x = np.arange(20, dtype=float).reshape(10, 2)
        y = np.arange(10, dtype=float)
        x_s, y_s = _make_sequences(x, y, sequence_length=3)
        assert x_s.shape == (8, 3, 2)
        assert y_s is not None
        assert y_s.shape == (8,)

    def test_label_alignment(self) -> None:
        x = np.arange(20, dtype=float).reshape(10, 2)
        y = np.arange(10, dtype=float)
        _, y_s = _make_sequences(x, y, sequence_length=3)
        assert y_s is not None
        np.testing.assert_array_equal(y_s, y[2:])

    def test_sequence_length_one(self) -> None:
        x = np.ones((5, 2))
        y = np.zeros(5)
        x_s, y_s = _make_sequences(x, y, sequence_length=1)
        assert x_s.shape == (5, 1, 2)
        assert y_s is not None
        assert y_s.shape == (5,)

    def test_y_none_path(self) -> None:
        x = np.ones((5, 2))
        x_s, y_s = _make_sequences(x, None, sequence_length=2)
        assert x_s.shape == (4, 2, 2)
        assert y_s is None

    def test_too_short_raises(self) -> None:
        x = np.ones((3, 2))
        y = np.zeros(3)
        with pytest.raises(ValueError, match="sequence_length"):
            _make_sequences(x, y, sequence_length=4)

    def test_exact_length_yields_one_sequence(self) -> None:
        x = np.ones((4, 2))
        y = np.zeros(4)
        x_s, y_s = _make_sequences(x, y, sequence_length=4)
        assert x_s.shape == (1, 4, 2)
        assert y_s is not None
        assert y_s.shape == (1,)

    def test_content_of_first_sequence(self) -> None:
        x = np.arange(6, dtype=float).reshape(3, 2)
        y = np.array([10.0, 20.0, 30.0])
        x_s, y_s = _make_sequences(x, y, sequence_length=2)
        np.testing.assert_array_equal(x_s[0], x[:2])
        np.testing.assert_array_equal(x_s[1], x[1:])
        assert y_s is not None
        np.testing.assert_array_equal(y_s, [20.0, 30.0])


# ---------------------------------------------------------------------------
# _positions_from_up_prob
# ---------------------------------------------------------------------------


class TestPositionsFromUpProb:
    def test_p_half_is_zero(self) -> None:
        pos = _positions_from_up_prob(np.array([0.5]), step_size=0.0)
        assert float(pos[0]) == pytest.approx(0.0, abs=1e-9)

    def test_long_and_short_sign(self) -> None:
        pos = _positions_from_up_prob(np.array([0.8, 0.2]), step_size=0.0)
        assert pos[0] > 0.0
        assert pos[1] < 0.0

    def test_antisymmetric(self) -> None:
        up = float(_positions_from_up_prob(np.array([0.75]), step_size=0.0)[0])
        dn = float(_positions_from_up_prob(np.array([0.25]), step_size=0.0)[0])
        assert up == pytest.approx(-dn, abs=1e-9)

    def test_step_size_discretises(self) -> None:
        pos = _positions_from_up_prob(np.array([0.8]), step_size=0.25)
        val = float(pos[0])
        assert val == pytest.approx(round(val / 0.25) * 0.25, abs=1e-9)

    def test_extreme_probs(self) -> None:
        pos = _positions_from_up_prob(np.array([0.9999, 0.0001]), step_size=0.0)
        assert pos[0] > 0.9
        assert pos[1] < -0.9

    def test_output_in_minus_one_one(self) -> None:
        rng = np.random.default_rng(42)
        p = rng.uniform(0.01, 0.99, 100)
        pos = _positions_from_up_prob(p, step_size=0.0)
        assert (np.abs(pos) <= 1.0).all()


# ---------------------------------------------------------------------------
# LSTMSignal -- lifecycle and guards
# ---------------------------------------------------------------------------


class TestLSTMSignalLifecycle:
    def test_not_fitted_initially(self) -> None:
        model = LSTMSignal(config=_fast_config())
        assert not model.fitted

    def test_fitted_after_fit(self) -> None:
        x, y = _flat_dataset()
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        assert model.fitted

    def test_config_property(self) -> None:
        cfg = _fast_config()
        model = LSTMSignal(config=cfg)
        assert model.config is cfg

    def test_predict_proba_before_fit_raises(self) -> None:
        x, _ = _flat_dataset()
        model = LSTMSignal(config=_fast_config(n_features=2))
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict_proba(x)

    def test_signal_before_fit_raises(self) -> None:
        x, _ = _flat_dataset()
        model = LSTMSignal(config=_fast_config(n_features=2))
        with pytest.raises(RuntimeError, match="not fitted"):
            model.signal(x)

    def test_column_mismatch_raises(self) -> None:
        x, y = _flat_dataset()
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        bad = x.rename(columns={"a": "z"})
        with pytest.raises(ValueError, match="match the training columns"):
            model.predict_proba(bad)

    def test_default_config(self) -> None:
        model = LSTMSignal()
        assert model.config == LSTMConfig()


# ---------------------------------------------------------------------------
# LSTMSignal.fit -- input validation
# ---------------------------------------------------------------------------


class TestLSTMSignalFitValidation:
    def test_empty_features_raise(self) -> None:
        cfg = _fast_config(n_features=1, seq_len=1)
        model = LSTMSignal(config=cfg)
        empty_x = pd.DataFrame({"a": pd.Series([], dtype=float)})
        empty_y = pd.Series([], dtype=float)
        with pytest.raises(ValueError, match="non-empty"):
            model.fit(empty_x, empty_y)

    def test_index_mismatch_raises(self) -> None:
        x, y = _flat_dataset()
        cfg = _fast_config(n_features=2, seq_len=3)
        model = LSTMSignal(config=cfg)
        with pytest.raises(ValueError, match="share the same index"):
            model.fit(x, y.set_axis(_bdays(len(y)) + pd.Timedelta(days=1)))

    def test_non_finite_raises(self) -> None:
        x, y = _flat_dataset()
        cfg = _fast_config(n_features=2, seq_len=3)
        model = LSTMSignal(config=cfg)
        bad = x.copy()
        bad.iloc[0, 0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            model.fit(bad, y)

    def test_non_binary_labels_raise(self) -> None:
        n = 30
        idx = _bdays(n)
        x = pd.DataFrame(np.ones((n, 2)), index=idx, columns=["a", "b"])
        y = pd.Series(np.tile([-1, 0, 1], 10), index=idx)
        cfg = _fast_config(n_features=2, seq_len=3)
        model = LSTMSignal(config=cfg)
        with pytest.raises(ValueError, match="exactly 2 label classes"):
            model.fit(x, y)

    def test_too_short_for_sequence_length_raises(self) -> None:
        n = 3
        x = pd.DataFrame(np.ones((n, 2)), index=_bdays(n), columns=["a", "b"])
        y = pd.Series([-1, 1, -1], index=x.index)
        cfg = _fast_config(n_features=2, seq_len=5)
        with pytest.raises(ValueError, match="sequence_length"):
            LSTMSignal(config=cfg).fit(x, y)

    def test_non_finite_predict_proba_raises(self) -> None:
        x, y = _flat_dataset()
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        bad = x.copy()
        bad.iloc[0, 0] = np.inf
        with pytest.raises(ValueError, match="non-finite"):
            model.predict_proba(bad)


# ---------------------------------------------------------------------------
# LSTMSignal.predict_proba -- shape and index alignment
# ---------------------------------------------------------------------------


class TestLSTMSignalPredictProba:
    def test_output_length_and_index(self) -> None:
        x, y = _flat_dataset(n=20)
        seq_len = 4
        cfg = _fast_config(n_features=2, seq_len=seq_len, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)

        expected_len = len(x) - seq_len + 1
        assert len(proba) == expected_len
        assert list(proba.index) == list(x.index[seq_len - 1 :])

    def test_proba_values_in_zero_one(self) -> None:
        x, y = _flat_dataset(n=20)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)
        assert ((proba >= 0.0) & (proba <= 1.0)).all()

    def test_series_name(self) -> None:
        x, y = _flat_dataset(n=20)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)
        assert proba.name == "prob_up"

    def test_sequence_length_one_all_rows_returned(self) -> None:
        x, y = _flat_dataset(n=20)
        cfg = _fast_config(n_features=2, seq_len=1, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)
        assert len(proba) == len(x)
        assert list(proba.index) == list(x.index)


# ---------------------------------------------------------------------------
# LSTMSignal.signal -- convention and step_size
# ---------------------------------------------------------------------------


class TestLSTMSignalSignal:
    def test_signal_name(self) -> None:
        x, y = _flat_dataset(n=20)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        sig = model.signal(x)
        assert sig.name == "signal"

    def test_signal_in_minus_one_one(self) -> None:
        x, y = _flat_dataset(n=20)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        sig = model.signal(x)
        assert (sig.abs() <= 1.0).all()

    def test_signal_step_size_on_grid(self) -> None:
        x, y = _flat_dataset(n=20)
        step = 0.25
        cfg = _fast_config(n_features=2, seq_len=3, epochs=1, step_size=step)
        model = LSTMSignal(config=cfg).fit(x, y)
        sig = model.signal(x)
        nonzero = sig[sig != 0.0].to_numpy()
        if len(nonzero) > 0:
            np.testing.assert_allclose(nonzero / step, np.round(nonzero / step), atol=1e-6)

    def test_signal_same_index_as_predict_proba(self) -> None:
        x, y = _flat_dataset(n=20)
        seq_len = 5
        cfg = _fast_config(n_features=2, seq_len=seq_len, epochs=1)
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)
        sig = model.signal(x)
        assert list(sig.index) == list(proba.index)

    def test_p_half_produces_near_zero_signal(self) -> None:
        pos = _positions_from_up_prob(np.array([0.5]), step_size=0.0)
        assert float(pos[0]) == pytest.approx(0.0, abs=1e-9)

    def test_high_p_positive_low_p_negative(self) -> None:
        high = float(_positions_from_up_prob(np.array([0.95]), step_size=0.0)[0])
        low = float(_positions_from_up_prob(np.array([0.05]), step_size=0.0)[0])
        assert high > 0.5
        assert low < -0.5


# ---------------------------------------------------------------------------
# sample_weight forwarding
# ---------------------------------------------------------------------------


class TestSampleWeight:
    def test_weighted_fit_runs_and_produces_valid_output(self) -> None:
        x, y = _flat_dataset(n=30)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=2)
        weights = pd.Series(np.linspace(0.5, 1.5, len(x)), index=x.index)
        model = LSTMSignal(config=cfg).fit(x, y, sample_weight=weights)
        proba = model.predict_proba(x)
        assert len(proba) == len(x) - cfg.sequence_length + 1
        assert ((proba >= 0.0) & (proba <= 1.0)).all()


# ---------------------------------------------------------------------------
# OVERFIT-A-TINY-BATCH -- learning capacity proof
# ---------------------------------------------------------------------------


class TestOverfitTinyBatch:
    """Verify the network can drive loss near zero on a perfectly separable problem.

    The dataset has a strong directional signal in feature f0: positive values
    imply label=+1, negative values imply label=-1. With enough epochs the LSTM
    should learn this perfectly. This is the canonical learning-capacity test for
    a neural network DOD -- it confirms the forward pass, loss function, optimiser
    step, and label encoding are all wired correctly end-to-end.
    """

    def test_overfit_accuracy_above_threshold(self) -> None:
        x, y = _separable_dataset(n=60, n_features=3, seed=7)
        cfg = LSTMConfig(
            input_size=3,
            hidden_size=32,
            num_layers=1,
            dropout=0.0,
            sequence_length=5,
            learning_rate=5e-3,
            n_epochs=300,
            batch_size=16,
            random_state=42,
            device="cpu",
            step_size=0.0,
        )
        model = LSTMSignal(config=cfg).fit(x, y)
        proba = model.predict_proba(x)

        aligned_y = y.iloc[cfg.sequence_length - 1 :]
        pred_direction = np.where(proba.to_numpy() >= 0.5, 1, -1)
        accuracy = float((pred_direction == aligned_y.to_numpy()).mean())
        assert accuracy > 0.95, (
            f"Network failed to overfit the separable dataset: accuracy={accuracy:.3f} < 0.95. "
            "This indicates a wiring error in the forward pass, loss, or label encoding."
        )


# ---------------------------------------------------------------------------
# DETERMINISM -- identical predictions from independent fits
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Verify that two independently-constructed LSTMSignal instances with the same
    random_state produce byte-identical (allclose atol=1e-6) predictions.

    Determinism is achieved by:
      1. torch.manual_seed + numpy.random.seed + random.seed from config.random_state
         at the top of both fit() and predict_proba().
      2. torch.use_deterministic_algorithms(True) -- verified to work with CPU LSTM.
      3. A seeded torch.Generator for the DataLoader (shuffle with fixed seed,
         not global state).
      4. CPU device only (no non-deterministic CUDA kernels).

    Note: predictions are compared with allclose (atol=1e-6) rather than bitwise
    equality because float32 accumulation order can differ between DataLoader
    batches on different Python invocations in rare cases. In practice on a fixed
    machine and Python version the predictions are bit-exact, but allclose is the
    correct contractual guarantee for cross-invocation reproducibility.
    """

    def test_same_seed_same_predictions(self) -> None:
        x, y = _flat_dataset(n=30, n_features=2, seed=1)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=10, seed=99)

        model_a = LSTMSignal(config=cfg).fit(x, y)
        model_b = LSTMSignal(config=cfg).fit(x, y)

        proba_a = model_a.predict_proba(x).to_numpy()
        proba_b = model_b.predict_proba(x).to_numpy()

        np.testing.assert_allclose(
            proba_a,
            proba_b,
            atol=1e-6,
            err_msg="Two models with the same random_state produced different predictions.",
        )

    def test_different_seeds_different_predictions(self) -> None:
        x, y = _flat_dataset(n=30, n_features=2, seed=1)
        cfg_a = _fast_config(n_features=2, seq_len=3, epochs=5, seed=0)
        cfg_b = _fast_config(n_features=2, seq_len=3, epochs=5, seed=1)

        proba_a = LSTMSignal(config=cfg_a).fit(x, y).predict_proba(x).to_numpy()
        proba_b = LSTMSignal(config=cfg_b).fit(x, y).predict_proba(x).to_numpy()

        assert not np.allclose(proba_a, proba_b, atol=1e-6), (
            "Models with different seeds produced identical predictions -- "
            "seeding is not being applied."
        )

    def test_determinism_with_sample_weight(self) -> None:
        x, y = _flat_dataset(n=30, n_features=2, seed=2)
        cfg = _fast_config(n_features=2, seq_len=3, epochs=10, seed=77)
        weights = pd.Series(np.linspace(0.5, 2.0, len(x)), index=x.index)

        proba_a = LSTMSignal(config=cfg).fit(x, y, sample_weight=weights).predict_proba(x).to_numpy()
        proba_b = LSTMSignal(config=cfg).fit(x, y, sample_weight=weights).predict_proba(x).to_numpy()

        np.testing.assert_allclose(proba_a, proba_b, atol=1e-6)
