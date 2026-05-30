"""End-to-end integration + robustness tests for the Phase 4 pairs vertical.

This is the master-plan Phase 4.8 deliverable: it proves the entire statistical
arbitrage stack composes and behaves correctly when driven through the Phase 3
backtest engine -- selection -> spread -> signals -> sizing -> portfolio ->
engine -> robustness (CPCV, Deflated Sharpe) -> risk -> execution.

The universe is synthetic but has *known* structure: two genuinely cointegrated
pairs embedded among independent random walks. Tests assert structural truths
(the right pairs are found, no look-ahead, the two engine modes agree, the
robustness machinery runs, risk limits hold, execution is atomic) rather than
fragile exact returns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest.engine import BacktestConfig, BacktestEngine
from core_trading.backtest.metrics import sharpe_ratio
from core_trading.backtest.report import BacktestReport
from core_trading.backtest.walkforward import cpcv_sharpe_distribution
from core_trading.execution.pairs_execution import (
    DeterministicFillModel,
    Leg,
    PairExecutor,
    PairOrder,
)
from core_trading.research.overfitting import deflated_sharpe_ratio
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits
from core_trading.strategies.pairs_trading import PairsTradingConfig, PairsTradingStrategy

_FORMATION = 150
_N = 800


def _make_universe(seed: int = 7, n: int = _N) -> pd.DataFrame:
    """A (symbol, timestamp) OHLCV panel with two cointegrated pairs + noise.

    * (YA, XA): YA = 2.0*XA + 10 + noise   -> cointegrated, hedge ~ 2.0
    * (YB, XB): YB = 1.5*XB + 5  + noise    -> cointegrated, hedge ~ 1.5
    * ZZ, WW : independent random walks      -> must NOT be paired
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-02", periods=n, freq="B", tz="UTC")

    xa = 50 + np.cumsum(rng.standard_normal(n)) * 0.5
    ya = 2.0 * xa + 10 + rng.standard_normal(n) * 1.0
    xb = 30 + np.cumsum(rng.standard_normal(n)) * 0.4
    yb = 1.5 * xb + 5 + rng.standard_normal(n) * 0.8
    zz = 80 + np.cumsum(rng.standard_normal(n)) * 0.6
    ww = 120 + np.cumsum(rng.standard_normal(n)) * 0.7
    series = {"YA": ya, "XA": xa, "YB": yb, "XB": xb, "ZZ": zz, "WW": ww}

    frames = []
    for sym, px in series.items():
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


@pytest.fixture
def universe() -> pd.DataFrame:
    return _make_universe()


@pytest.fixture
def strategy() -> PairsTradingStrategy:
    cfg = PairsTradingConfig(formation_window=_FORMATION, zscore_window=30, max_pairs=5)
    return PairsTradingStrategy(cfg)


# --------------------------------------------------------------------- selection
class TestSelection:
    def test_finds_both_cointegrated_pairs(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        strategy.generate_weights(universe)
        found = {frozenset((p.candidate.symbol_y, p.candidate.symbol_x)) for p in strategy.plans}
        assert frozenset(("YA", "XA")) in found
        assert frozenset(("YB", "XB")) in found

    def test_genuine_cointegration_dominates_spurious(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        # Over a finite formation window Engle-Granger CAN flag a spurious pair
        # involving an independent walk (ZZ/WW) -- that false-positive risk is
        # precisely why the robustness layer (CPCV, Deflated Sharpe) exists. The
        # meaningful, reliable property is that genuine cointegration *dominates*:
        # the two true pairs must hold the best (lowest) selection scores, ahead
        # of any spurious pair that survives the multiple-testing correction.
        strategy.generate_weights(universe)
        ranked = sorted(strategy.plans, key=lambda p: p.candidate.score)
        top_two = {
            frozenset((p.candidate.symbol_y, p.candidate.symbol_x)) for p in ranked[:2]
        }
        assert top_two == {frozenset(("YA", "XA")), frozenset(("YB", "XB"))}

    def test_recovers_hedge_ratio(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        strategy.generate_weights(universe)
        by_pair = {
            frozenset((p.candidate.symbol_y, p.candidate.symbol_x)): p for p in strategy.plans
        }
        ya_xa = by_pair[frozenset(("YA", "XA"))]
        # Orientation may be (YA,XA) hedge ~2.0 or (XA,YA) hedge ~0.5; either is correct.
        beta = ya_xa.hedge.beta
        assert beta == pytest.approx(2.0, abs=0.3) or beta == pytest.approx(0.5, abs=0.1)


# ------------------------------------------------------------------- look-ahead
class TestLookAhead:
    def test_no_trades_before_formation(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        w = strategy.generate_weights(universe)
        assert w.iloc[:_FORMATION].abs().to_numpy().sum() == 0.0

    def test_future_bars_do_not_change_past_weights(
        self, universe: pd.DataFrame
    ) -> None:
        # Truncating the panel after bar K must not alter any weight at bar < K:
        # a weight that depends on future data would change.
        cfg = PairsTradingConfig(formation_window=_FORMATION, zscore_window=30, max_pairs=5)
        full = PairsTradingStrategy(cfg).generate_weights(universe)

        timeline = universe.index.get_level_values("timestamp").unique().sort_values()
        cut = timeline[400]
        truncated_panel = universe[universe.index.get_level_values("timestamp") <= cut]
        truncated = PairsTradingStrategy(cfg).generate_weights(truncated_panel)

        common_cols = full.columns.intersection(truncated.columns)
        aligned_full = full.loc[full.index <= cut, common_cols]
        aligned_trunc = truncated.loc[truncated.index <= cut, common_cols]
        # Drop the final couple of bars of the truncated run (boundary of the
        # rolling window) and compare the rest exactly.
        compare_idx = aligned_trunc.index[:-2]
        pd.testing.assert_frame_equal(
            aligned_full.loc[compare_idx], aligned_trunc.loc[compare_idx]
        )


# ------------------------------------------------------------------ engine run
class TestEngine:
    def test_modes_agree_frictionless(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        vec = engine.run(universe, strategy, mode="vectorised")
        evt = engine.run(universe, strategy, mode="event_driven")
        # Both rebalance to the same target weights each bar -> identical returns
        # well inside the master plan's 1bp/day tolerance.
        diff = (vec.equity - evt.equity).abs() / vec.initial_cash
        assert float(diff.max()) < 1e-4

    def test_report_generates(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        result = engine.run(universe, strategy, mode="vectorised")
        report = BacktestReport.from_result(result)
        payload = report.to_dict()
        assert "metrics" in payload
        assert np.isfinite(payload["metrics"]["sharpe"])

    def test_costs_reduce_return(self, universe: pd.DataFrame) -> None:
        cfg = PairsTradingConfig(formation_window=_FORMATION, zscore_window=30, max_pairs=5)
        strat = PairsTradingStrategy(cfg)
        free = BacktestEngine(BacktestConfig(cost_model_name="zero")).run(
            universe, strat, mode="vectorised"
        )
        costed = BacktestEngine(BacktestConfig(cost_model_name="ibkr")).run(
            universe, strat, mode="vectorised"
        )
        # Costs can only subtract from the frictionless return.
        assert float(costed.equity.iloc[-1]) <= float(free.equity.iloc[-1]) + 1e-6


# ------------------------------------------------------------------- robustness
class TestRobustness:
    def test_cpcv_distribution(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        sharpes = cpcv_sharpe_distribution(
            universe,
            strategy,
            n_groups=6,
            n_test_groups=2,
            config=BacktestConfig(cost_model_name="zero"),
            mode="vectorised",
        )
        from math import comb

        assert sharpes.shape == (comb(6, 2),)
        assert np.isfinite(sharpes).all()

    def test_deflated_sharpe_against_cpcv_trials(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        result = engine.run(universe, strategy, mode="vectorised")
        trial_sharpes = cpcv_sharpe_distribution(
            universe, strategy, n_groups=6, n_test_groups=2,
            config=BacktestConfig(cost_model_name="zero"), mode="vectorised",
        )
        active = result.returns[result.returns != 0.0]
        dsr = deflated_sharpe_ratio(
            active, n_trials=len(trial_sharpes), trial_sharpes=trial_sharpes
        )
        # The DSR is a probability in [0, 1]; it must be well-defined.
        assert 0.0 <= dsr.deflated_sharpe <= 1.0
        assert dsr.n_trials == len(trial_sharpes)

    def test_stress_regime_runs(self, strategy: PairsTradingStrategy) -> None:
        # A higher-volatility "crisis" regime must not break the pipeline.
        stressed = _make_universe(seed=99)
        rng = np.random.default_rng(1)
        shock = stressed.copy()
        # Inject a vol shock into the last 60 bars across all symbols.
        ts = stressed.index.get_level_values("timestamp").unique().sort_values()
        crisis = set(ts[-60:])
        mask = shock.index.get_level_values("timestamp").isin(crisis)
        shock.loc[mask, ["open", "high", "low", "close"]] *= 1 + rng.normal(
            0, 0.05, (int(mask.sum()), 4)
        )
        w = strategy.generate_weights(shock)
        assert np.isfinite(w.to_numpy()).all()


# ------------------------------------------------------------------------ risk
class TestRiskIntegration:
    def test_gross_leverage_within_cap(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        w = strategy.generate_weights(universe)
        gross = w.abs().sum(axis=1)
        cap = strategy.config.portfolio.gross_leverage_cap
        assert float(gross.max()) <= cap + 1e-9

    def test_circuit_breaker_catches_crash(self) -> None:
        manager = PairsRiskManager(RiskLimits())
        # A 12% single-day drop must trip the daily circuit breaker.
        equity = pd.Series(
            [1.0, 1.01, 1.02, 1.015, 0.90],
            index=pd.date_range("2024-01-01", periods=5, freq="B"),
        )
        check = manager.daily_check(equity)
        assert not check.passed
        assert check.violations

    def test_pretrade_passes_on_constructed_weights(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        w = strategy.generate_weights(universe)
        active = w.loc[w.abs().sum(axis=1) > 0]
        manager = PairsRiskManager(
            RiskLimits(gross_leverage_cap=strategy.config.portfolio.gross_leverage_cap)
        )
        # Gross-leverage limit must hold on every active bar.
        for ts in active.index[:25]:
            row = {s: float(v) for s, v in active.loc[ts].items() if v != 0.0}
            check = manager.pre_trade(row)
            gross_violations = [v for v in check.violations if "leverage" in v.lower()]
            assert not gross_violations


# ------------------------------------------------------------------- execution
class TestExecutionIntegration:
    def test_atomic_pair_fill_with_shortfall(
        self, universe: pd.DataFrame, strategy: PairsTradingStrategy
    ) -> None:
        strategy.generate_weights(universe)
        plan = strategy.plans[0]
        pid = f"{plan.candidate.symbol_y}__{plan.candidate.symbol_x}"
        order = PairOrder(
            pair_id=pid,
            leg_y=Leg(symbol=plan.candidate.symbol_y, quantity=100.0, decision_price=50.0),
            leg_x=Leg(
                symbol=plan.candidate.symbol_x,
                quantity=-100.0 * plan.hedge.beta,
                decision_price=40.0,
            ),
        )
        executor = PairExecutor(DeterministicFillModel(slippage_bps=8.0))
        result = executor.execute(order)
        assert result.filled
        assert len(result.fills) == 2
        assert result.shortfall_bps == pytest.approx(8.0, abs=0.5)

    def test_one_leg_rejection_cancels_both(self) -> None:
        order = PairOrder(
            pair_id="x",
            leg_y=Leg(symbol="A", quantity=100.0, decision_price=10.0),
            leg_x=Leg(symbol="B", quantity=-50.0, decision_price=20.0),
        )
        executor = PairExecutor(DeterministicFillModel(reject_symbols=frozenset({"B"})))
        result = executor.execute(order)
        assert not result.filled
        assert result.fills == ()


def test_sharpe_is_finite_helper(universe: pd.DataFrame, strategy: PairsTradingStrategy) -> None:
    # Sanity: the engine's returns feed the metric layer cleanly.
    result = BacktestEngine(BacktestConfig(cost_model_name="zero")).run(
        universe, strategy, mode="vectorised"
    )
    assert np.isfinite(sharpe_ratio(result.returns))
