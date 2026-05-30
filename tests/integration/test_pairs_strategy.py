"""Unit tests for the Phase 4 pilot strategy adapter (PairsTradingStrategy).

These complement ``test_pairs_pipeline.py`` by exercising the strategy's own
branches in isolation: configuration validation, the formation guard, the
distance-selection path, plain wide-frame input, and market-beta neutralisation.

They live under ``tests/integration`` (not ``tests/strategies``) on purpose: the
``tests/strategies`` conftest replaces ``statsmodels`` with mocks to support the
legacy damaged-strategy suite, which would break the real cointegration path used
here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.pairs_trading import (
    PairsTradingConfig,
    PairsTradingStrategy,
    _pair_id,
)


def _panel(seed: int = 3, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    xa = 50 + np.cumsum(rng.standard_normal(n)) * 0.5
    ya = 2.0 * xa + 10 + rng.standard_normal(n) * 1.0
    xb = 30 + np.cumsum(rng.standard_normal(n)) * 0.4
    yb = 1.5 * xb + 5 + rng.standard_normal(n) * 0.8
    frames = []
    for sym, px in {"YA": ya, "XA": xa, "YB": yb, "XB": xb}.items():
        px = np.maximum(px, 1.0)
        frames.append(
            pd.DataFrame(
                {
                    "open": px,
                    "high": px * 1.001,
                    "low": px * 0.999,
                    "close": px,
                    "volume": rng.uniform(2e6, 4e6, n),
                },
                index=pd.MultiIndex.from_product([[sym], idx], names=["symbol", "timestamp"]),
            )
        )
    return pd.concat(frames).sort_index()


class TestConfigValidation:
    def test_bad_formation_window(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(formation_window=1)

    def test_bad_zscore_window(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(zscore_window=1)

    def test_bad_max_pairs(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(max_pairs=0)

    def test_bad_selection_method(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(selection_method="magic")


class TestFormationGuard:
    def test_panel_shorter_than_formation_is_flat(self) -> None:
        cfg = PairsTradingConfig(formation_window=300, zscore_window=20)
        strat = PairsTradingStrategy(cfg)
        weights = strat.generate_weights(_panel(n=200))
        assert weights.abs().to_numpy().sum() == 0.0
        assert strat.plans == []
        assert strat.gross_budget == 0.0


class TestSelectionMethods:
    def test_distance_method_runs(self) -> None:
        cfg = PairsTradingConfig(
            formation_window=150, zscore_window=20, selection_method="distance", max_pairs=3
        )
        strat = PairsTradingStrategy(cfg)
        weights = strat.generate_weights(_panel())
        assert strat.plans  # distance always returns its top_n pairs
        assert weights.shape[0] == 400

    def test_pair_id_is_stable(self) -> None:
        cfg = PairsTradingConfig(formation_window=150, zscore_window=20)
        strat = PairsTradingStrategy(cfg)
        strat.generate_weights(_panel())
        for plan in strat.plans:
            pid = _pair_id(plan.candidate)
            assert pid == f"{plan.candidate.symbol_y}__{plan.candidate.symbol_x}"


class TestInputForms:
    def test_accepts_wide_close_frame(self) -> None:
        panel = _panel()
        wide = panel["close"].unstack("symbol").sort_index()
        cfg = PairsTradingConfig(formation_window=150, zscore_window=20)
        strat = PairsTradingStrategy(cfg)
        weights = strat.generate_weights(wide)
        assert list(weights.columns) == list(wide.columns)
        assert weights.shape[0] == wide.shape[0]


class TestBetaNeutralisation:
    def test_hedge_symbol_added_when_betas_supplied(self) -> None:
        cfg = PairsTradingConfig(formation_window=150, zscore_window=20)
        betas = {"YA": 1.1, "XA": 1.0, "YB": 0.9, "XB": 1.05, "SPY": 1.0}
        strat = PairsTradingStrategy(cfg, market_betas=betas)
        weights = strat.generate_weights(_panel())
        assert cfg.portfolio.hedge_symbol in weights.columns
        # On at least one active bar the hedge leg is non-zero.
        assert float(weights[cfg.portfolio.hedge_symbol].abs().sum()) > 0.0
