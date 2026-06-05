"""Tests for the live pairs paper-trading runner (Phase 4.10).

The runner is exercised end to end with deterministic fakes at its two
seams (broker, bar source) and a stub strategy that emits configured target
weights, so every operational behaviour -- anchor pinning, whole-share
rounding, delta orders, fills, the kill switch, skipped days, ledger resume
and the promotion gate -- is covered without a TWS session.
"""
from __future__ import annotations

import datetime as _dt
import json

import pandas as pd
import pytest

from core_trading.ops.pairs_live_runner import (
    STATUS_ERROR,
    STATUS_HALTED,
    STATUS_SKIPPED,
    STATUS_TRADED,
    LedgerStore,
    PairsLiveRunner,
    RunnerConfig,
    RunnerState,
    _round_shares,
)
from core_trading.strategies.pairs_trading import PairsTradingConfig

TODAY = _dt.date(2026, 6, 5)  # a Friday
FORMATION = 5


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class StubStrategy:
    """Emits zeros everywhere except a configured final-row weight map."""

    def __init__(self, weights_today: dict[str, float] | None = None) -> None:
        self.config = PairsTradingConfig(formation_window=FORMATION, zscore_window=2)
        self.weights_today = weights_today or {}
        self.sectors = None
        self.seen_frames: list[pd.DataFrame] = []

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        self.seen_frames.append(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        for sym, w in self.weights_today.items():
            weights.iloc[-1, weights.columns.get_loc(sym)] = w
        return weights


class FakeBars:
    """Constant-price daily bars ending at a configurable last session."""

    def __init__(
        self,
        prices: dict[str, float],
        *,
        last_day: _dt.date = TODAY,
        n_days: int = 30,
    ) -> None:
        self.prices = prices
        self.last_day = last_day
        self.n_days = n_days

    async def daily_closes(self, symbols: list[str], _duration: str) -> pd.DataFrame:
        index = pd.bdate_range(end=pd.Timestamp(self.last_day), periods=self.n_days)
        data = {s: [self.prices[s]] * len(index) for s in symbols if s in self.prices}
        return pd.DataFrame(data, index=index)


class FakeBroker:
    """Instant-fill broker with optional per-symbol slippage and failures."""

    def __init__(
        self,
        fill_prices: dict[str, float],
        *,
        reject: set[str] | None = None,
        partial: dict[str, float] | None = None,
    ) -> None:
        self.fill_prices = fill_prices
        self.reject = reject or set()
        self.partial = partial or {}
        self.placed: list[dict] = []
        self._orders: dict[str, dict] = {}
        self._next = 1

    async def place_order(self, order_data: dict) -> dict:
        self.placed.append(dict(order_data))
        sym = order_data["symbol"]
        if sym in self.reject:
            return {"order_id": None, "status": "rejected", "reason": "test reject"}
        order_id = f"FAKE-{self._next}"
        self._next += 1
        qty = float(order_data["quantity"])
        filled = self.partial.get(sym, qty)
        self._orders[order_id] = {
            "status": "filled" if filled >= qty else "submitted",
            "filled_quantity": filled,
            "avg_fill_price": self.fill_prices[sym],
        }
        return {"order_id": order_id, "status": "submitted"}

    async def get_order_status(self, order_id: str) -> dict:
        return dict(self._orders[order_id])


def make_runner(
    tmp_path,
    *,
    weights: dict[str, float] | None = None,
    prices: dict[str, float] | None = None,
    fill_prices: dict[str, float] | None = None,
    last_day: _dt.date = TODAY,
    config: RunnerConfig | None = None,
    broker: FakeBroker | None = None,
) -> tuple[PairsLiveRunner, FakeBroker, LedgerStore]:
    prices = prices or {"AAA": 100.0, "BBB": 50.0}
    broker = broker or FakeBroker(fill_prices or dict(prices))
    store = LedgerStore(tmp_path / "pairs_paper")
    runner = PairsLiveRunner(
        StubStrategy(weights or {}),
        broker,
        FakeBars(prices, last_day=last_day),
        store,
        universe=sorted(prices),
        config=config
        or RunnerConfig(equity_base=25_000.0, fill_timeout_s=3.0, poll_interval_s=0.01),
    )
    return runner, broker, store


# ---------------------------------------------------------------------------
# Share rounding
# ---------------------------------------------------------------------------


class TestRoundShares:
    def test_round_half_away_from_zero(self) -> None:
        assert _round_shares(250.0, 100.0, 0.5) == 3  # 2.5 -> 3
        assert _round_shares(-250.0, 100.0, 0.5) == -3
        assert _round_shares(240.0, 100.0, 0.5) == 2
        assert _round_shares(260.0, 100.0, 0.5) == 3

    def test_below_first_share_threshold_drops_to_zero(self) -> None:
        assert _round_shares(49.0, 100.0, 0.5) == 0
        assert _round_shares(-49.0, 100.0, 0.5) == 0
        assert _round_shares(50.0, 100.0, 0.5) == 1

    def test_bad_price_gives_zero(self) -> None:
        assert _round_shares(100.0, 0.0, 0.5) == 0
        assert _round_shares(100.0, float("nan"), 0.5) == 0


# ---------------------------------------------------------------------------
# First run
# ---------------------------------------------------------------------------


class TestFirstRun:
    async def test_trades_and_pins_anchor(self, tmp_path) -> None:
        runner, broker, store = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}
        )
        result = await runner.run_once(today=TODAY)

        assert result.status == STATUS_TRADED
        # 0.02 * 25000 = 500 -> 5 shares at 100; -500 -> -10 shares at 50.
        sides = {(o["symbol"], o["side"], o["quantity"]) for o in result.orders}
        assert sides == {("AAA", "buy", 5), ("BBB", "sell", 10)}
        assert len(result.fills) == 2

        state = store.load_state()
        assert state.positions == {"AAA": 5, "BBB": -10}
        assert state.formation_anchor is not None
        assert state.started == TODAY.isoformat()
        # Fills at the close prices: equity is conserved.
        assert result.equity == pytest.approx(25_000.0)
        assert result.daily_return == pytest.approx(0.0)

    async def test_anchor_gives_formation_plus_today(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        await runner.run_once(today=TODAY)
        frame = runner.strategy.seen_frames[-1]
        assert len(frame) == FORMATION + 1
        anchor = store.load_state().formation_anchor
        assert pd.Timestamp(anchor) == frame.index[0]

    async def test_rounding_diagnostics_report_dropped_legs(self, tmp_path) -> None:
        # 0.001 * 25000 = 25 USD on a 100 USD stock -> rounds to zero.
        runner, broker, _ = make_runner(
            tmp_path, weights={"AAA": 0.001, "BBB": -0.02}
        )
        result = await runner.run_once(today=TODAY)
        assert result.rounding["dropped_legs"] == ["AAA"]
        assert result.rounding["tracking_error_frac_of_gross"] > 0.0
        assert all(o["symbol"] != "AAA" for o in broker.placed)


# ---------------------------------------------------------------------------
# Rebalance deltas and resume
# ---------------------------------------------------------------------------


class TestRebalance:
    async def test_second_run_places_only_deltas(self, tmp_path) -> None:
        runner, broker, store = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}
        )
        await runner.run_once(today=TODAY)
        # Same targets next session: no orders at all.
        runner2, broker2, _ = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}
        )
        next_day = TODAY + _dt.timedelta(days=3)  # Monday
        runner2.bars = FakeBars({"AAA": 100.0, "BBB": 50.0}, last_day=next_day)
        result = await runner2.run_once(today=next_day)
        assert result.status == STATUS_TRADED
        assert result.orders == []
        assert broker2.placed == []

    async def test_target_flip_generates_closing_and_opening_quantity(self, tmp_path) -> None:
        runner, _, _ = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        await runner.run_once(today=TODAY)
        runner2, broker2, _ = make_runner(
            tmp_path, weights={"AAA": -0.02, "BBB": 0.02}
        )
        next_day = TODAY + _dt.timedelta(days=3)
        runner2.bars = FakeBars({"AAA": 100.0, "BBB": 50.0}, last_day=next_day)
        result = await runner2.run_once(today=next_day)
        # +5 -> -5 means selling 10; -10 -> +10 means buying 20.
        sides = {(o["symbol"], o["side"], o["quantity"]) for o in result.orders}
        assert sides == {("AAA", "sell", 10), ("BBB", "buy", 20)}

    async def test_price_move_realises_return_and_accrues_active_day(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        await runner.run_once(today=TODAY)
        # AAA +10%: long 5 shares gains 50 on 25k equity.
        next_day = TODAY + _dt.timedelta(days=3)
        runner2, _, store2 = make_runner(
            tmp_path,
            weights={"AAA": 0.02, "BBB": -0.02},
            prices={"AAA": 110.0, "BBB": 50.0},
            fill_prices={"AAA": 110.0, "BBB": 50.0},
        )
        runner2.bars = FakeBars({"AAA": 110.0, "BBB": 50.0}, last_day=next_day)
        result = await runner2.run_once(today=next_day)
        assert result.equity == pytest.approx(25_050.0)
        assert result.daily_return == pytest.approx(50.0 / 25_000.0)
        returns = store2.active_returns()
        assert len(returns) == 1
        assert float(returns.iloc[0]) == pytest.approx(0.002)


# ---------------------------------------------------------------------------
# Skips, errors, dry runs
# ---------------------------------------------------------------------------


class TestSkipAndDryRun:
    async def test_stale_bar_skips_without_orders(self, tmp_path) -> None:
        yesterday = TODAY - _dt.timedelta(days=1)
        runner, broker, store = make_runner(
            tmp_path, weights={"AAA": 0.02}, last_day=yesterday
        )
        result = await runner.run_once(today=TODAY)
        assert result.status == STATUS_SKIPPED
        assert broker.placed == []
        records = store.ledger_records()
        assert len(records) == 1 and records[0]["status"] == STATUS_SKIPPED

    async def test_empty_bars_is_error(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path, weights={"AAA": 0.02})
        runner.bars = FakeBars({})  # bar source returns no columns at all
        result = await runner.run_once(today=TODAY)
        assert result.status == STATUS_ERROR

    async def test_dry_run_leaves_no_trace(self, tmp_path) -> None:
        runner, broker, store = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}
        )
        result = await runner.run_once(today=TODAY, dry_run=True)
        assert result.status == STATUS_TRADED
        assert result.orders  # orders are computed and reported ...
        assert broker.placed == []  # ... but never placed
        assert not store.state_path.exists()
        assert store.ledger_records() == []


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    async def test_pre_trade_breach_flattens_and_halts(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        await runner.run_once(today=TODAY)
        # Per-symbol cap is 5 * portfolio per_pair_cap = 0.10: breach it.
        next_day = TODAY + _dt.timedelta(days=3)
        runner2, broker2, store2 = make_runner(tmp_path, weights={"AAA": 0.25})
        runner2.bars = FakeBars({"AAA": 100.0, "BBB": 50.0}, last_day=next_day)
        result = await runner2.run_once(today=next_day)

        assert result.status == STATUS_HALTED
        assert result.violations
        # The book (long 5 AAA, short 10 BBB) is flattened, not re-targeted.
        sides = {(o["symbol"], o["side"], o["quantity"]) for o in result.orders}
        assert sides == {("AAA", "sell", 5), ("BBB", "buy", 10)}
        state = store2.load_state()
        assert state.halted
        assert state.positions == {}
        assert state.incidents

    async def test_halted_state_blocks_future_runs(self, tmp_path) -> None:
        store = LedgerStore(tmp_path / "pairs_paper")
        state = RunnerState(halted=True, halt_reason="test halt")
        store.save_state(state)
        runner, broker, _ = make_runner(tmp_path, weights={"AAA": 0.02})
        result = await runner.run_once(today=TODAY)
        assert result.status == STATUS_HALTED
        assert "kill switch engaged" in result.reason
        assert broker.placed == []

    async def test_daily_drawdown_breach_trips_breaker(self, tmp_path) -> None:
        runner, _, _ = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        await runner.run_once(today=TODAY)
        # Crash AAA so the marked equity falls > 5% in one day: 5 shares can't
        # do that at 25k equity, so seed a bigger book via direct state edit.
        store = LedgerStore(tmp_path / "pairs_paper")
        state = store.load_state()
        state.positions = {"AAA": 600}  # 60k long at 100
        state.cash = -35_000.0
        store.save_state(state)
        next_day = TODAY + _dt.timedelta(days=3)
        runner2, _, store2 = make_runner(
            tmp_path,
            weights={"AAA": 0.02, "BBB": -0.02},
            prices={"AAA": 80.0, "BBB": 50.0},  # -20% on a 60k position
            fill_prices={"AAA": 80.0, "BBB": 50.0},
        )
        runner2.bars = FakeBars({"AAA": 80.0, "BBB": 50.0}, last_day=next_day)
        result = await runner2.run_once(today=next_day)
        assert result.status == STATUS_HALTED
        assert any("drawdown" in v.lower() or "loss" in v.lower() for v in result.violations)
        assert store2.load_state().halted


# ---------------------------------------------------------------------------
# Fill handling
# ---------------------------------------------------------------------------


class TestFillHandling:
    async def test_rejected_order_records_incident_without_position(self, tmp_path) -> None:
        broker = FakeBroker({"AAA": 100.0, "BBB": 50.0}, reject={"AAA"})
        runner, _, store = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}, broker=broker
        )
        await runner.run_once(today=TODAY)
        state = store.load_state()
        assert "AAA" not in state.positions
        assert state.positions == {"BBB": -10}
        assert any("rejected" in inc for inc in state.incidents)

    async def test_partial_fill_books_only_filled_quantity(self, tmp_path) -> None:
        broker = FakeBroker({"AAA": 100.0, "BBB": 50.0}, partial={"BBB": 4.0})
        config = RunnerConfig(
            equity_base=25_000.0, fill_timeout_s=0.05, poll_interval_s=0.01
        )
        runner, _, store = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}, broker=broker, config=config
        )
        await runner.run_once(today=TODAY)
        state = store.load_state()
        assert state.positions == {"AAA": 5, "BBB": -4}
        assert any("not fully filled" in inc for inc in state.incidents)
        # Cash reflects only what actually traded.
        assert state.cash == pytest.approx(25_000.0 - 5 * 100.0 + 4 * 50.0)

    async def test_slippage_shows_up_as_negative_return(self, tmp_path) -> None:
        # Fills 1% worse than the close on both legs.
        broker = FakeBroker({"AAA": 101.0, "BBB": 49.5})
        runner, _, _ = make_runner(
            tmp_path, weights={"AAA": 0.02, "BBB": -0.02}, broker=broker
        )
        result = await runner.run_once(today=TODAY)
        # Bought 5 AAA at 101 (marked 100): -5. Sold 10 BBB at 49.5 (marked 50): -5.
        assert result.equity == pytest.approx(24_990.0)
        assert result.daily_return == pytest.approx(-10.0 / 25_000.0)


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------


class TestPromotion:
    async def test_insufficient_history_blocks_promotion(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path, weights={"AAA": 0.02, "BBB": -0.02})
        result = await runner.run_once(today=TODAY)
        assert result.promotion["eligible"] is False
        assert any("insufficient paper history" in r for r in result.promotion["reasons"])

    def test_long_clean_record_promotes(self, tmp_path) -> None:
        store = LedgerStore(tmp_path / "pairs_paper")
        # Synthesise 120 active traded days of steady positive returns.
        day = _dt.date(2026, 1, 5)
        equity = 25_000.0
        for i in range(120):
            # Steady but non-constant: a constant series has zero variance
            # and therefore an undefined (reported 0.0) Sharpe.
            ret = 0.0015 if i % 2 == 0 else 0.0005
            equity *= 1.0 + ret
            store.append_ledger(
                {
                    "date": day.isoformat(),
                    "status": STATUS_TRADED,
                    "equity": equity,
                    "daily_return": ret,
                    "dry_run": False,
                }
            )
            day += _dt.timedelta(days=1)
        runner, _, _ = make_runner(tmp_path)
        runner.store = store
        decision = runner.evaluate_promotion(RunnerState())
        assert decision.n_days == 120
        assert decision.eligible

    def test_open_incident_blocks_promotion(self, tmp_path) -> None:
        runner, _, store = make_runner(tmp_path)
        state = RunnerState(incidents=["2026-06-05: test incident"])
        decision = runner.evaluate_promotion(state)
        assert not decision.eligible
        assert any("incident" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# Store round-trips
# ---------------------------------------------------------------------------


class TestLedgerStore:
    def test_state_round_trip(self, tmp_path) -> None:
        store = LedgerStore(tmp_path / "pairs_paper")
        state = RunnerState(
            started="2026-06-05",
            formation_anchor="2025-06-05",
            cash=12_345.67,
            positions={"AAA": 5, "BBB": -10},
            halted=True,
            halt_reason="why",
            incidents=["a"],
            resolved_incidents=["b"],
        )
        store.save_state(state)
        loaded = store.load_state()
        assert loaded == state

    def test_dry_run_records_excluded_from_series(self, tmp_path) -> None:
        store = LedgerStore(tmp_path / "pairs_paper")
        store.append_ledger(
            {"date": "2026-06-04", "status": STATUS_TRADED, "equity": 100.0,
             "daily_return": 0.01, "dry_run": True}
        )
        store.append_ledger(
            {"date": "2026-06-05", "status": STATUS_TRADED, "equity": 200.0,
             "daily_return": 0.02, "dry_run": False}
        )
        assert len(store.traded_records()) == 1
        assert float(store.equity_series().iloc[0]) == 200.0
        assert len(store.active_returns()) == 1

    def test_fills_appended_as_jsonl(self, tmp_path) -> None:
        store = LedgerStore(tmp_path / "pairs_paper")
        store.append_fills(
            [{"date": "2026-06-05", "symbol": "AAA", "quantity": 5, "avg_price": 100.0}]
        )
        lines = store.fills_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["symbol"] == "AAA"
