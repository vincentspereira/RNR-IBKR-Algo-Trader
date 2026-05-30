"""Tests for the pairs paper-trading harness (master plan Phase 4.9).

Validation strategy: drive the harness over a synthetic universe with two known
cointegrated pairs and assert the operational behaviours the plan requires --
no-look-ahead marking, a working kill switch with incident recording, sane daily
monitoring records, and a promotion gate that enforces minimum history, zero
incidents, and a Sharpe within a standard error of the backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.ops.pairs_paper_trading import (
    DailySnapshot,
    PairsPaperTrader,
    PaperConfig,
    PromotionDecision,
    sharpe_standard_error,
)
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits
from core_trading.strategies.pairs_trading import PairsTradingConfig, PairsTradingStrategy

_FORMATION = 150


def _universe(seed: int = 7, n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-02", periods=n, freq="B", tz="UTC")
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


def _strategy() -> PairsTradingStrategy:
    cfg = PairsTradingConfig(formation_window=_FORMATION, zscore_window=30, max_pairs=4)
    return PairsTradingStrategy(cfg)


def _lenient_manager() -> PairsRiskManager:
    # Per-pair legs can reach per_pair_cap * hedge_ratio; allow headroom so normal
    # operation is not flagged. Gross stays well under 2.0x.
    return PairsRiskManager(RiskLimits(per_pair_cap=0.10, gross_leverage_cap=2.0))


# --------------------------------------------------------- sharpe standard error
class TestSharpeStandardError:
    def test_known_value(self) -> None:
        # SR=0 -> sqrt(1/n); n=100 -> 0.1
        assert sharpe_standard_error(0.0, 100) == pytest.approx(0.1)

    def test_grows_with_sharpe(self) -> None:
        assert sharpe_standard_error(2.0, 100) > sharpe_standard_error(0.0, 100)

    def test_too_few_obs_is_inf(self) -> None:
        assert sharpe_standard_error(1.0, 1) == float("inf")


# --------------------------------------------------------------- config validation
class TestPaperConfig:
    def test_rejects_bad_min_days(self) -> None:
        with pytest.raises(ValueError):
            PaperConfig(min_paper_days=0)

    def test_rejects_negative_se_mult(self) -> None:
        with pytest.raises(ValueError):
            PaperConfig(promotion_se_mult=-1.0)


# ------------------------------------------------------------------------ run loop
class TestRun:
    def test_produces_one_snapshot_per_bar(self) -> None:
        strat = _strategy()
        trader = PairsPaperTrader(strat, risk_manager=_lenient_manager())
        snaps = trader.run(_universe())
        weights = strat.generate_weights(_universe())
        assert len(snaps) == len(weights)
        assert all(isinstance(s, DailySnapshot) for s in snaps)

    def test_no_lookahead_before_first_position(self) -> None:
        # Until the first position is held, paper equity must stay flat.
        trader = PairsPaperTrader(_strategy(), risk_manager=_lenient_manager())
        trader.run(_universe())
        frame = trader.monitoring_frame()
        first_active = (frame["gross_leverage"] > 0).idxmax()
        # All marks strictly before the first held position are unchanged.
        before = frame.loc[: first_active].iloc[:-2]
        assert (before["daily_return"] == 0.0).all()

    def test_monitoring_frame_columns(self) -> None:
        trader = PairsPaperTrader(_strategy(), risk_manager=_lenient_manager())
        trader.run(_universe())
        frame = trader.monitoring_frame()
        for col in ("equity", "daily_return", "gross_leverage", "rolling_sharpe", "drawdown"):
            assert col in frame.columns
        assert np.isfinite(frame["equity"].to_numpy()).all()

    def test_empty_monitoring_frame_before_run(self) -> None:
        trader = PairsPaperTrader(_strategy())
        assert trader.monitoring_frame().empty

    def test_happy_path_not_halted(self) -> None:
        trader = PairsPaperTrader(_strategy(), risk_manager=_lenient_manager())
        trader.run(_universe())
        assert not trader.is_halted
        assert trader.incidents == []


# ---------------------------------------------------------------- kill switch
class TestKillSwitch:
    def test_breach_halts_and_records_incident(self) -> None:
        # A gross-leverage cap below any real position guarantees a pre-trade
        # breach on the first active day, tripping the kill switch.
        tight = PairsRiskManager(RiskLimits(per_pair_cap=1e-6, gross_leverage_cap=1e-6))
        trader = PairsPaperTrader(
            _strategy(), risk_manager=tight, config=PaperConfig(halt_on_breach=True)
        )
        trader.run(_universe())
        assert trader.is_halted
        assert len(trader.incidents) == 1

    def test_halt_freezes_returns(self) -> None:
        tight = PairsRiskManager(RiskLimits(per_pair_cap=1e-6, gross_leverage_cap=1e-6))
        trader = PairsPaperTrader(
            _strategy(), risk_manager=tight, config=PaperConfig(halt_on_breach=True)
        )
        snaps = trader.run(_universe())
        halted_returns = [s.daily_return for s in snaps if s.halted]
        assert all(r == 0.0 for r in halted_returns)

    def test_no_halt_when_disabled(self) -> None:
        tight = PairsRiskManager(RiskLimits(per_pair_cap=1e-6, gross_leverage_cap=1e-6))
        trader = PairsPaperTrader(
            _strategy(), risk_manager=tight, config=PaperConfig(halt_on_breach=False)
        )
        trader.run(_universe())
        assert not trader.is_halted


# ----------------------------------------------------------------- promotion gate
def _snapshot(date: pd.Timestamp, daily_return: float) -> DailySnapshot:
    return DailySnapshot(
        date=date,
        equity=1.0,
        daily_return=daily_return,
        gross_leverage=0.5,
        n_active_pairs=1,
        rolling_sharpe=0.0,
        drawdown=0.0,
        risk_ok=True,
        halted=False,
    )


class TestPromotion:
    def _trader_with_returns(self, returns: np.ndarray, backtest_sharpe: float) -> PairsPaperTrader:
        trader = PairsPaperTrader(
            _strategy(),
            config=PaperConfig(
                backtest_sharpe=backtest_sharpe, min_paper_days=20, promotion_se_mult=1.0
            ),
        )
        dates = pd.date_range("2020-01-01", periods=len(returns), freq="B")
        trader.snapshots = [_snapshot(d, float(r)) for d, r in zip(dates, returns, strict=True)]
        return trader

    def test_insufficient_history_blocks(self) -> None:
        trader = self._trader_with_returns(np.full(5, 0.001), backtest_sharpe=1.0)
        decision = trader.evaluate_promotion()
        assert isinstance(decision, PromotionDecision)
        assert not decision.eligible
        assert any("insufficient" in r for r in decision.reasons)

    def test_incident_blocks(self) -> None:
        rng = np.random.default_rng(0)
        trader = self._trader_with_returns(
            0.001 + rng.standard_normal(60) * 1e-5, backtest_sharpe=0.0
        )
        trader.incidents = ["2020-02-01: drawdown breach"]
        decision = trader.evaluate_promotion()
        assert not decision.eligible
        assert any("incident" in r for r in decision.reasons)

    def test_strong_paper_sharpe_promotes(self) -> None:
        # A steady positive drift with tiny noise -> very high Sharpe, comfortably
        # above a modest backtest floor; enough days; no incidents -> eligible.
        rng = np.random.default_rng(1)
        returns = 0.002 + rng.standard_normal(60) * 1e-4
        trader = self._trader_with_returns(returns, backtest_sharpe=1.0)
        decision = trader.evaluate_promotion()
        assert decision.eligible
        assert decision.reasons == ()
        assert decision.n_days == 60

    def test_collapsed_sharpe_blocks(self) -> None:
        # Paper Sharpe near zero against a high backtest Sharpe -> below the
        # promotion floor.
        rng = np.random.default_rng(2)
        returns = rng.standard_normal(60) * 0.01  # ~zero mean -> Sharpe ~ 0
        trader = self._trader_with_returns(returns, backtest_sharpe=2.0)
        decision = trader.evaluate_promotion()
        assert not decision.eligible
        assert any("below promotion floor" in r for r in decision.reasons)


def test_end_to_end_paper_run_then_promotion() -> None:
    # Full integration: real strategy -> harness -> monitoring -> promotion gate.
    strat = _strategy()
    trader = PairsPaperTrader(
        strat,
        risk_manager=_lenient_manager(),
        config=PaperConfig(backtest_sharpe=0.0, min_paper_days=5),
    )
    trader.run(_universe())
    decision = trader.evaluate_promotion()
    # The gate returns a well-formed decision (eligibility depends on the data).
    assert decision.n_days >= 0
    assert math_isfinite(decision.paper_sharpe)


def math_isfinite(x: float) -> bool:
    return bool(np.isfinite(x))
