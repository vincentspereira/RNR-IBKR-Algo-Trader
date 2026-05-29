"""Tests for core_trading.research.reproducibility."""
from __future__ import annotations

import os
import random

import numpy as np

from core_trading.research.reproducibility import (
    DEFAULT_SEED,
    ExperimentConfig,
    mlflow_run,
    set_seeds,
    tracking_uri,
)


class TestSetSeeds:
    def test_numpy_reproducible(self) -> None:
        set_seeds(123)
        a = np.random.rand(5)
        set_seeds(123)
        b = np.random.rand(5)
        assert np.allclose(a, b)

    def test_random_reproducible(self) -> None:
        set_seeds(7)
        a = [random.random() for _ in range(5)]
        set_seeds(7)
        b = [random.random() for _ in range(5)]
        assert a == b

    def test_sets_pythonhashseed(self) -> None:
        set_seeds(99)
        assert os.environ["PYTHONHASHSEED"] == "99"

    def test_default_seed(self) -> None:
        set_seeds()
        assert os.environ["PYTHONHASHSEED"] == str(DEFAULT_SEED)


class TestTrackingUri:
    def test_default_local(self, monkeypatch) -> None:
        monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
        assert tracking_uri() == "file:./mlruns"

    def test_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
        assert tracking_uri() == "http://mlflow:5000"


class TestExperimentConfig:
    def test_defaults(self) -> None:
        c = ExperimentConfig("exp")
        assert c.seed == DEFAULT_SEED
        assert c.params == {}
        assert c.tags == {}


class TestMlflowRun:
    def test_run_seeds_and_yields(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("MLFLOW_TRACKING_URI", f"file:{tmp_path}/mlruns")
        cfg = ExperimentConfig("unit-test-exp", seed=55, params={"alpha": 1.0}, tags={"k": "v"})
        with mlflow_run(cfg) as run:
            # numpy seeded inside the context
            x = np.random.rand(3)
        set_seeds(55)
        y = np.random.rand(3)
        assert np.allclose(x, y)
        # run object may be an mlflow ActiveRun or None if mlflow missing
        assert run is None or hasattr(run, "info")

    def test_run_without_mlflow(self, monkeypatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "mlflow":
                raise ImportError("simulated missing mlflow")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        cfg = ExperimentConfig("no-mlflow", seed=1)
        with mlflow_run(cfg) as run:
            assert run is None
