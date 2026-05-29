"""Reproducibility utilities (master plan Phase 0.5).

Every research run and backtest must be reproducible:

* :func:`set_seeds` fixes the global RNG seed across ``random``, ``numpy``, and
  (if installed) ``torch``, so a notebook or backtest gives identical results
  run-to-run.
* :func:`mlflow_run` is a context manager that opens an MLflow run with the
  configured tracking URI, logs the seed and supplied params, and guarantees the
  run is closed. Experiment tracking is mandatory: every backtest gets a
  hash-tagged MLflow run per the plan.

The MLflow tracking URI defaults to a local ``./mlruns`` directory (no server
needed) and can be overridden via the ``MLFLOW_TRACKING_URI`` env var.
"""
from __future__ import annotations

import contextlib
import os
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

DEFAULT_SEED = 42


def set_seeds(seed: int = DEFAULT_SEED) -> None:
    """Seed all RNGs for reproducibility.

    Seeds ``random`` and ``numpy`` always; seeds ``torch`` (CPU + CUDA) if it is
    importable. Also sets ``PYTHONHASHSEED`` for hash-stability in subprocesses.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    try:  # pragma: no cover - torch optional / heavy
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        # torch is optional for seeding; a missing OR broken install (e.g. a
        # failed CUDA/DLL load on Windows) must never break a research run.
        pass


def tracking_uri() -> str:
    """Return the MLflow tracking URI (env override or local ./mlruns)."""
    return os.environ.get("MLFLOW_TRACKING_URI", "file:./mlruns")


@dataclass(slots=True)
class ExperimentConfig:
    """Configuration for one tracked experiment run."""

    name: str
    seed: int = DEFAULT_SEED
    params: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)


@contextlib.contextmanager
def mlflow_run(config: ExperimentConfig) -> Iterator[Any]:
    """Context manager opening an MLflow run with seeding + param logging.

    Seeds RNGs from ``config.seed`` before yielding. Logs the seed, all
    ``config.params``, and ``config.tags`` to the run. The run is always ended
    on exit. If MLflow is unavailable the context still seeds and yields
    ``None`` so research code is not blocked.

    Usage::

        with mlflow_run(ExperimentConfig("pairs-backtest", params={"z": 2.0})):
            ...
    """
    set_seeds(config.seed)
    try:
        import mlflow
    except ImportError:  # pragma: no cover - mlflow is a pinned dependency
        yield None
        return

    mlflow.set_tracking_uri(tracking_uri())
    mlflow.set_experiment(config.name)
    active = mlflow.start_run()
    try:
        mlflow.log_param("seed", config.seed)
        for key, value in config.params.items():
            mlflow.log_param(key, value)
        for key, value in config.tags.items():
            mlflow.set_tag(key, value)
        yield active
    finally:
        mlflow.end_run()
