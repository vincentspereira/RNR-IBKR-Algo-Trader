"""LSTM directional signal (Phase 5.D.3).

A recurrent neural-network variant of the Phase 5.D directional-signal
family. An LSTM with a single linear--sigmoid head is trained on the triple-
barrier *direction* labels (``{-1, +1}`` from
:func:`core_trading.signals.ml.labeling.get_bins` with flat ``0`` events
dropped). The predicted up-probability is converted to a bet-sized position in
``(-1, 1)`` using the same de Prado transform used in every other 5.D signal.

The LSTM operates on *sliding windows* (sequences) over the feature frame:
the model sees a lookback window of ``sequence_length`` rows and predicts the
direction of the event whose label falls at the *last* row of the window. This
means the first ``sequence_length - 1`` rows of ``x`` do not produce a
prediction (the warmup period). All outputs are indexed to the rows of ``x``
that correspond to the last step of a complete window, i.e.
``x.index[sequence_length - 1:]``.

PyTorch is lazy-imported inside every method that needs it so the module is
importable in environments without torch. The first use raises
:class:`ImportError` with a clear message if torch is absent.

Determinism
-----------
Two independently constructed ``LSTMSignal`` instances with identical
``LSTMConfig.random_state`` and ``LSTMConfig.sequence_length`` and fed the
same training data in the same order will produce predictions that are
identical to floating-point precision (``allclose`` at tolerance ``1e-6``).
This is achieved by:

* seeding ``torch.manual_seed``, ``numpy.random.seed``, and ``random.seed``
  from ``config.random_state`` at the top of :meth:`LSTMSignal.fit` and
  :meth:`LSTMSignal.predict_proba`;
* enabling ``torch.use_deterministic_algorithms(True)`` -- verified to work
  with CPU LSTM on PyTorch >= 2.0;
* using a seeded ``torch.Generator`` in the :class:`~torch.utils.data.DataLoader`
  instead of global state;
* running on CPU only (no non-deterministic GPU kernels).

Mathematical references
-----------------------
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley.
  Chapter 6 and Chapter 10 (bet sizing, snippet 10.2).
* Hochreiter, S., & Schmidhuber, J. (1997). "Long short-term memory."
  Neural Computation, 9(8), 1735-1780.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from core_trading.signals.ml.meta_labelling import bet_size_from_prob

if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    import torch.utils.data as data_utils

__all__ = [
    "LSTMConfig",
    "LSTMSignal",
]


# ---------------------------------------------------------------------------
# Lazy torch import helper
# ---------------------------------------------------------------------------


def _require_torch() -> None:
    """Raise a clear ImportError when torch is not installed."""
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "PyTorch is required for LSTMSignal. "
            "Install it with: pip install torch"
        ) from exc


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LSTMConfig:
    """Hyper-parameters for :class:`LSTMSignal`.

    Attributes
    ----------
    input_size:
        Number of input features per time-step (>= 1). Must match the number
        of columns in the feature frame passed to :meth:`LSTMSignal.fit`.
    hidden_size:
        LSTM hidden-state dimension (>= 1). The linear output head maps from
        this dimension to a single logit.
    num_layers:
        Number of stacked LSTM layers (>= 1).
    dropout:
        Dropout probability applied between LSTM layers when ``num_layers > 1``
        (in ``[0, 1)``). Ignored when ``num_layers == 1`` per PyTorch
        convention.
    sequence_length:
        Lookback window length in rows (>= 1). The LSTM is unrolled over
        ``sequence_length`` consecutive feature rows to produce one prediction.
        The first ``sequence_length - 1`` rows of ``x`` do not yield a
        prediction (warmup).
    learning_rate:
        Adam learning rate (> 0).
    n_epochs:
        Training epochs (>= 1).
    batch_size:
        Mini-batch size (>= 1).
    random_state:
        Master seed for torch, numpy, and python random, ensuring
        reproducibility across independent instantiations.
    device:
        Torch device string. Only ``"cpu"`` is supported and tested. GPU
        non-determinism is outside scope.
    step_size:
        Bet-size discretisation grid in ``[0, 1]`` (0 leaves it continuous),
        passed to :func:`bet_size_from_prob`.
    """

    input_size: int = 1
    hidden_size: int = 32
    num_layers: int = 1
    dropout: float = 0.0
    sequence_length: int = 20
    learning_rate: float = 1e-3
    n_epochs: int = 50
    batch_size: int = 32
    random_state: int = 0
    device: str = "cpu"
    step_size: float = 0.0

    def __post_init__(self) -> None:
        if self.input_size < 1:
            raise ValueError("input_size must be >= 1")
        if self.hidden_size < 1:
            raise ValueError("hidden_size must be >= 1")
        if self.num_layers < 1:
            raise ValueError("num_layers must be >= 1")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.sequence_length < 1:
            raise ValueError("sequence_length must be >= 1")
        if self.learning_rate <= 0.0:
            raise ValueError("learning_rate must be > 0")
        if self.n_epochs < 1:
            raise ValueError("n_epochs must be >= 1")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if self.device != "cpu":
            raise ValueError("only device='cpu' is supported")
        if not 0.0 <= self.step_size <= 1.0:
            raise ValueError("step_size must be in [0, 1]")


# ---------------------------------------------------------------------------
# Internal: LSTM network definition
# ---------------------------------------------------------------------------


def _build_network(cfg: LSTMConfig) -> nn.Module:
    """Construct the LSTM + linear head (lazy torch import)."""
    import torch.nn as nn

    class _LSTMNet(nn.Module):
        def __init__(self, c: LSTMConfig) -> None:
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=c.input_size,
                hidden_size=c.hidden_size,
                num_layers=c.num_layers,
                batch_first=True,
                dropout=c.dropout if c.num_layers > 1 else 0.0,
            )
            self.head = nn.Linear(c.hidden_size, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.lstm(x)
            logits: torch.Tensor = self.head(out[:, -1, :]).squeeze(-1)
            return logits

    return _LSTMNet(cfg)


# ---------------------------------------------------------------------------
# Internal: shared utilities
# ---------------------------------------------------------------------------


def _seed_all(seed: int) -> None:
    """Seed torch, numpy, and python random for full reproducibility."""
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.use_deterministic_algorithms(True)


def _check_binary(y: pd.Series) -> None:
    """Require exactly two label classes: {-1, +1}."""
    unique = np.unique(y.to_numpy())
    if len(unique) != 2:
        raise ValueError(
            "directional signal requires exactly 2 label classes (drop flat/0 labels)"
        )


def _make_sequences(
    x_arr: np.ndarray,
    y_arr: np.ndarray | None,
    sequence_length: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Build sliding-window sequences from flat feature and label arrays.

    Parameters
    ----------
    x_arr:
        Shape ``(n_rows, n_features)`` float64 array.
    y_arr:
        Shape ``(n_rows,)`` label array or None (inference path).
    sequence_length:
        Window length in rows.

    Returns
    -------
    x_seqs:
        Shape ``(n_rows - sequence_length + 1, sequence_length, n_features)``.
    y_seqs:
        Shape ``(n_rows - sequence_length + 1,)`` or None.

    The label at position ``i`` in ``y_seqs`` corresponds to the row at
    position ``i + sequence_length - 1`` in the original frame (last step of
    window ``i``).
    """
    n = x_arr.shape[0]
    n_out = n - sequence_length + 1
    if n_out <= 0:
        raise ValueError(
            f"sequence_length ({sequence_length}) exceeds the number of rows ({n}); "
            "provide more data or reduce sequence_length"
        )
    x_seqs = np.stack(
        [x_arr[i : i + sequence_length] for i in range(n_out)], axis=0
    )
    y_seqs = (
        None
        if y_arr is None
        else y_arr[sequence_length - 1 :]
    )
    return x_seqs, y_seqs


def _labels_to_binary(y: pd.Series) -> np.ndarray:
    """Map direction labels {-1, +1} to binary {0, 1} for BCEWithLogitsLoss."""
    arr: np.ndarray = np.asarray(y.to_numpy(dtype=float), dtype=float)
    return np.asarray((arr + 1.0) / 2.0, dtype=np.float32)


def _positions_from_up_prob(
    p_up: np.ndarray,
    *,
    step_size: float,
) -> np.ndarray:
    """Signed bet sizes from the up-probability (AFML snippet 10.2)."""
    p = np.asarray(p_up, dtype=float)
    direction = np.where(p >= 0.5, 1.0, -1.0)
    prob_predicted = np.where(p >= 0.5, p, 1.0 - p)
    magnitude = bet_size_from_prob(prob_predicted, num_classes=2, step_size=step_size)
    result: np.ndarray = np.asarray(direction * magnitude, dtype=float)
    return result


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------


class LSTMSignal:
    """A recurrent-network directional signal built on an LSTM encoder.

    Trains on triple-barrier direction labels ``{-1, +1}`` and produces a
    bet-sized position in ``(-1, 1)`` via the de Prado probability transform.

    Parameters
    ----------
    config:
        Hyper-parameters; defaults to :class:`LSTMConfig`.

    Notes
    -----
    The ``input_size`` in ``config`` must equal the number of columns in the
    feature frame ``x`` passed to :meth:`fit`. The network is re-initialised
    on every call to :meth:`fit`; there is no warm-start path.

    The first ``sequence_length - 1`` rows of ``x`` cannot produce a
    prediction because they do not form a complete lookback window. Both
    :meth:`predict_proba` and :meth:`signal` return a Series indexed to
    ``x.index[sequence_length - 1:]``.
    """

    def __init__(self, *, config: LSTMConfig | None = None) -> None:
        self._config: LSTMConfig = config if config is not None else LSTMConfig()
        self._net: nn.Module | None = None
        self._feature_names: list[object] = []

    @property
    def config(self) -> LSTMConfig:
        """The model's hyper-parameters."""
        return self._config

    @property
    def fitted(self) -> bool:
        """Whether :meth:`fit` has been called."""
        return self._net is not None

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        *,
        sample_weight: pd.Series | None = None,
    ) -> LSTMSignal:
        """Train the LSTM on features and binary direction labels.

        Parameters
        ----------
        x:
            Feature frame; shape ``(n_events, n_features)``. Must have at
            least ``sequence_length`` rows.
        y:
            Direction labels in ``{-1, +1}``, sharing ``x``'s index.
        sample_weight:
            Optional per-event weights aligned to ``x``'s index. Weights
            apply per-sequence: the weight of sequence ``i`` is the weight of
            the *label* row ``x.index[i + sequence_length - 1]``.

        Returns
        -------
        LSTMSignal
            ``self``, fitted.

        Raises
        ------
        ValueError
            If inputs are empty, mis-aligned, non-finite, not binary, or too
            short for the requested ``sequence_length``.
        ImportError
            If PyTorch is not installed.
        """
        _require_torch()
        import torch
        import torch.nn as nn
        import torch.utils.data as data_utils

        cfg = self._config

        if x.empty:
            raise ValueError("features must be non-empty")
        if not x.index.equals(y.index):
            raise ValueError("features and labels must share the same index")
        x_arr = x.to_numpy(dtype=np.float32)
        if not np.isfinite(x_arr).all():
            raise ValueError("features contain non-finite values")
        _check_binary(y)

        _seed_all(cfg.random_state)

        y_binary = _labels_to_binary(y)
        x_seqs, y_seqs = _make_sequences(x_arr, y_binary, cfg.sequence_length)
        assert y_seqs is not None

        x_t = torch.from_numpy(x_seqs)
        y_t = torch.from_numpy(y_seqs.astype(np.float32))

        if sample_weight is not None:
            w_aligned = sample_weight.reindex(y.index).to_numpy(dtype=np.float32)
            w_seqs = w_aligned[cfg.sequence_length - 1 :]
            w_t = torch.from_numpy(w_seqs)
            dataset: data_utils.Dataset[tuple[torch.Tensor, ...]] = (
                data_utils.TensorDataset(x_t, y_t, w_t)
            )
        else:
            dataset = data_utils.TensorDataset(x_t, y_t)

        g = torch.Generator()
        g.manual_seed(cfg.random_state)
        loader = data_utils.DataLoader(
            dataset,
            batch_size=cfg.batch_size,
            shuffle=True,
            generator=g,
        )

        net = _build_network(cfg)
        net.train()
        optimizer = torch.optim.Adam(net.parameters(), lr=cfg.learning_rate)
        loss_fn = nn.BCEWithLogitsLoss(reduction="none")

        for _ in range(cfg.n_epochs):
            for batch in loader:
                x_b: torch.Tensor = batch[0]
                y_b: torch.Tensor = batch[1]
                w_b: torch.Tensor | None = batch[2] if len(batch) == 3 else None

                optimizer.zero_grad()
                logits = net(x_b)
                per_sample_loss = loss_fn(logits, y_b)
                loss = (per_sample_loss * w_b).mean() if w_b is not None else per_sample_loss.mean()
                loss.backward()
                optimizer.step()

        net.eval()
        self._net = net
        self._feature_names = list(x.columns)
        return self

    def predict_proba(self, x: pd.DataFrame) -> pd.Series:
        """Predicted up-probability ``P(direction = +1)`` per complete window.

        Parameters
        ----------
        x:
            Feature frame with the same columns (and order) as at fit. Must
            have at least ``sequence_length`` rows.

        Returns
        -------
        pd.Series
            Up-probability indexed to ``x.index[sequence_length - 1:]``;
            the first ``sequence_length - 1`` warmup rows are excluded.

        Raises
        ------
        RuntimeError
            If the model is not fitted.
        ValueError
            If ``x`` columns do not match the training columns, ``x`` is too
            short, or ``x`` contains non-finite values.
        ImportError
            If PyTorch is not installed.
        """
        _require_torch()
        import torch

        net = self._require_fitted(x)
        cfg = self._config

        x_arr = x.to_numpy(dtype=np.float32)
        if not np.isfinite(x_arr).all():
            raise ValueError("features contain non-finite values")

        _seed_all(cfg.random_state)

        x_seqs, _ = _make_sequences(x_arr, None, cfg.sequence_length)
        x_t = torch.from_numpy(x_seqs)

        with torch.no_grad():
            logits = net(x_t)
            probs = torch.sigmoid(logits).numpy().astype(float)

        out_index = x.index[cfg.sequence_length - 1 :]
        return pd.Series(probs.ravel(), index=out_index, name="prob_up")

    def signal(self, x: pd.DataFrame) -> pd.Series:
        """Bet-sized directional position in ``[-1, 1]``.

        Applies the de Prado up-probability to signed-size transform (AFML
        snippet 10.2) to :meth:`predict_proba`. The position is near 0 when
        conviction is low (``prob_up`` near 0.5) and approaches +/-1 as
        conviction grows.

        Parameters
        ----------
        x:
            Feature frame (see :meth:`predict_proba`).

        Returns
        -------
        pd.Series
            Signed position indexed to ``x.index[sequence_length - 1:]``.
        """
        proba = self.predict_proba(x)
        positions = _positions_from_up_prob(
            proba.to_numpy(), step_size=self._config.step_size
        )
        return pd.Series(positions, index=proba.index, name="signal")

    def _require_fitted(self, x: pd.DataFrame) -> nn.Module:
        """Return the fitted network, validating feature alignment."""
        if self._net is None:
            raise RuntimeError("LSTMSignal is not fitted")
        if list(x.columns) != self._feature_names:
            raise ValueError(
                "features columns must match the training columns and order"
            )
        return self._net
