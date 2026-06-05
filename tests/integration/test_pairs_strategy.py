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

    def test_bad_max_pairs_per_sector(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(max_pairs_per_sector=0)

    def test_max_pairs_per_sector_none_is_default(self) -> None:
        assert PairsTradingConfig().max_pairs_per_sector is None


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


class TestSectorStratification:
    """max_pairs_per_sector caps the ranked candidate list per sector label."""

    @staticmethod
    def _candidate(sym_y: str, sym_x: str, sector: str | None, score: float):
        from core_trading.signals.pairs.selection import PairCandidate

        return PairCandidate(
            symbol_y=sym_y,
            symbol_x=sym_x,
            hedge_ratio=1.0,
            pvalue=float("nan"),
            pvalue_adj=float("nan"),
            half_life=10.0,
            method="distance",
            score=score,
            sector=sector,
        )

    def test_caps_pairs_per_sector_in_rank_order(self) -> None:
        cfg = PairsTradingConfig(
            formation_window=150, zscore_window=20, max_pairs_per_sector=2
        )
        strat = PairsTradingStrategy(cfg)
        ranked = [
            self._candidate("A1", "A2", "FIN", 0.1),
            self._candidate("A3", "A4", "FIN", 0.2),
            self._candidate("A5", "A6", "FIN", 0.3),  # third FIN: dropped
            self._candidate("B1", "B2", "TECH", 0.4),
            self._candidate("B3", "B4", "TECH", 0.5),
        ]
        kept = strat._stratify_by_sector(ranked)
        labels = [(c.symbol_y, c.sector) for c in kept]
        assert labels == [
            ("A1", "FIN"),
            ("A3", "FIN"),
            ("B1", "TECH"),
            ("B3", "TECH"),
        ]

    def test_unlabelled_pairs_share_one_bucket(self) -> None:
        cfg = PairsTradingConfig(
            formation_window=150, zscore_window=20, max_pairs_per_sector=1
        )
        strat = PairsTradingStrategy(cfg)
        ranked = [
            self._candidate("A1", "A2", None, 0.1),
            self._candidate("A3", "A4", None, 0.2),  # second unlabelled: dropped
        ]
        kept = strat._stratify_by_sector(ranked)
        assert len(kept) == 1

    def test_none_cap_keeps_everything(self) -> None:
        cfg = PairsTradingConfig(formation_window=150, zscore_window=20)
        strat = PairsTradingStrategy(cfg)
        ranked = [self._candidate(f"Y{i}", f"X{i}", "FIN", float(i)) for i in range(5)]
        assert strat._stratify_by_sector(ranked) == ranked

    def test_unique_symbols_skips_reused_names(self) -> None:
        cfg = PairsTradingConfig(
            formation_window=150, zscore_window=20, unique_symbols=True
        )
        strat = PairsTradingStrategy(cfg)
        ranked = [
            self._candidate("COF", "WFC", "FIN", 0.1),
            self._candidate("COF", "JPM", "FIN", 0.2),  # reuses COF: dropped
            self._candidate("GS", "JPM", "FIN", 0.3),  # JPM still unused: kept
            self._candidate("HD", "LOW", "DISC", 0.4),
        ]
        kept = strat._stratify_by_sector(ranked)
        assert [(c.symbol_y, c.symbol_x) for c in kept] == [
            ("COF", "WFC"),
            ("GS", "JPM"),
            ("HD", "LOW"),
        ]

    def test_bad_max_abs_hedge_beta(self) -> None:
        with pytest.raises(ValueError):
            PairsTradingConfig(max_abs_hedge_beta=0.5)


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
