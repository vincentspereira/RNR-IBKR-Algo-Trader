"""Unit tests for the intraday signal-driven runner (deterministic fakes)."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from core_trading.ops.intraday_runner import IntradayConfig, IntradayRunner
from core_trading.ops.pairs_live_runner import LedgerStore
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits

NOW = _dt.datetime(2026, 6, 10, 15, 0, 0)


class FakeQuotes:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    async def last_prices(self, symbols: list[str]) -> dict[str, float]:
        return {s: self.prices[s] for s in symbols if s in self.prices}


class FakeBroker:
    """Fills every order instantly at the quoted price."""

    def __init__(self, prices: dict[str, float], reject: bool = False) -> None:
        self.prices = prices
        self.reject = reject
        self.placed: list[dict[str, Any]] = []
        self._n = 0

    async def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        self.placed.append(order_data)
        if self.reject:
            return {"status": "rejected", "reason": "test reject"}
        self._n += 1
        self._last = order_data
        return {"order_id": str(self._n), "status": "submitted"}

    async def get_order_status(self, order_id: str) -> dict[str, Any]:  # noqa: ARG002
        return {
            "status": "filled",
            "filled_quantity": self._last["quantity"],
            "avg_fill_price": self.prices[self._last["symbol"]],
        }


class WeightStrategy:
    """Emits a fixed weight map on the LAST row of whatever frame it gets."""

    def __init__(self, weight_plan: list[dict[str, float]]) -> None:
        self.plan = weight_plan
        self.calls = 0

    def generate_weights(self, frame: pd.DataFrame) -> pd.DataFrame:
        weights = pd.DataFrame(0.0, index=frame.index, columns=frame.columns)
        plan = self.plan[min(self.calls, len(self.plan) - 1)]
        self.calls += 1
        for sym, w in plan.items():
            if sym in weights.columns:
                weights.iloc[-1, weights.columns.get_loc(sym)] = w
        return weights


def _history(symbols: tuple[str, ...] = ("AAA", "BBB")) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-02", periods=60)
    return pd.DataFrame({s: 100.0 for s in symbols}, index=idx)


def _risk() -> PairsRiskManager:
    return PairsRiskManager(
        RiskLimits(per_pair_cap=1.0, gross_leverage_cap=1.1, sector_cap=0.99)
    )


def _runner(
    tmp_path: Path,
    plan: list[dict[str, float]],
    prices: dict[str, float] | None = None,
    config: IntradayConfig | None = None,
) -> tuple[IntradayRunner, FakeBroker, LedgerStore]:
    prices = prices or {"AAA": 100.0, "BBB": 50.0}
    store = LedgerStore(tmp_path / "slot")
    broker = FakeBroker(prices)
    runner = IntradayRunner(
        WeightStrategy(plan),
        broker,
        FakeQuotes(prices),
        store,
        _history(),
        risk_manager=_risk(),
        config=config or IntradayConfig(equity_base=10_000.0, min_order_notional=200.0),
    )
    return runner, broker, store


class TestStep:
    @pytest.mark.asyncio
    async def test_first_tick_buys_signal(self, tmp_path: Path) -> None:
        runner, broker, store = _runner(tmp_path, [{"AAA": 0.5, "BBB": 0.5}])
        tick = await runner.step(NOW)
        assert tick.status == "TRADED"
        assert {o["symbol"] for o in tick.orders} == {"AAA", "BBB"}
        state = store.load_state()
        assert state.positions == {"AAA": 50, "BBB": 100}  # 5000/100, 5000/50
        assert state.cash == pytest.approx(0.0)
        assert tick.equity == pytest.approx(10_000.0)
        ticks = [json.loads(ln) for ln in runner.ticks_path.read_text().splitlines()]
        assert len(ticks) == 1 and ticks[0]["n_orders"] == 2

    @pytest.mark.asyncio
    async def test_signal_flip_sells(self, tmp_path: Path) -> None:
        runner, broker, _ = _runner(
            tmp_path, [{"AAA": 1.0}, {"BBB": 1.0}]
        )
        await runner.step(NOW)
        tick2 = await runner.step(NOW + _dt.timedelta(minutes=5))
        sides = {(o["symbol"], o["side"]) for o in tick2.orders}
        assert ("AAA", "sell") in sides
        assert ("BBB", "buy") in sides

    @pytest.mark.asyncio
    async def test_churn_guard_skips_small_delta_not_exits(self, tmp_path: Path) -> None:
        # 90 -> 91 shares of AAA = 100 USD delta < 200 min notional: skipped.
        # (weights stay under the 1.0 per-symbol risk cap)
        runner, broker, store = _runner(
            tmp_path, [{"AAA": 0.90}, {"AAA": 0.909}, {}]
        )
        await runner.step(NOW)
        tick2 = await runner.step(NOW + _dt.timedelta(minutes=5))
        assert tick2.orders == []
        assert tick2.skipped_small == 1
        # Full exit must NOT be blocked by the churn guard.
        tick3 = await runner.step(NOW + _dt.timedelta(minutes=10))
        assert [o["side"] for o in tick3.orders] == ["sell"]
        assert store.load_state().positions == {}

    @pytest.mark.asyncio
    async def test_order_budget(self, tmp_path: Path) -> None:
        cfg = IntradayConfig(equity_base=10_000.0, max_orders_per_day=1)
        runner, broker, _ = _runner(tmp_path, [{"AAA": 0.5, "BBB": 0.5}], config=cfg)
        tick = await runner.step(NOW)
        assert len(tick.orders) == 1  # second order dropped by the budget
        assert any("order budget" in v for v in tick.violations)

    @pytest.mark.asyncio
    async def test_risk_breach_flattens_and_halts(self, tmp_path: Path) -> None:
        runner, broker, store = _runner(
            tmp_path, [{"AAA": 1.0}, {"AAA": 0.8, "BBB": 0.8}]  # gross 1.6 > 1.1 cap
        )
        await runner.step(NOW)
        tick2 = await runner.step(NOW + _dt.timedelta(minutes=5))
        assert tick2.status == "HALTED"
        assert store.load_state().halted is True
        assert store.load_state().positions == {}  # flattened
        tick3 = await runner.step(NOW + _dt.timedelta(minutes=10))
        assert tick3.status == "HALTED"
        assert tick3.orders == []

    @pytest.mark.asyncio
    async def test_unmarkable_held_position_no_trade(self, tmp_path: Path) -> None:
        runner, broker, store = _runner(tmp_path, [{"AAA": 1.0}])
        await runner.step(NOW)
        runner.quotes = FakeQuotes({"BBB": 50.0})  # AAA quote disappears
        tick = await runner.step(NOW + _dt.timedelta(minutes=5))
        assert tick.orders == []
        assert any("no quote for held" in v for v in tick.violations)

    @pytest.mark.asyncio
    async def test_rejected_order_records_incident(self, tmp_path: Path) -> None:
        prices = {"AAA": 100.0, "BBB": 50.0}
        store = LedgerStore(tmp_path / "slot")
        broker = FakeBroker(prices, reject=True)
        runner = IntradayRunner(
            WeightStrategy([{"AAA": 1.0}]),
            broker,
            FakeQuotes(prices),
            store,
            _history(),
            risk_manager=_risk(),
            config=IntradayConfig(equity_base=10_000.0),
        )
        await runner.step(NOW)
        assert any("rejected" in s for s in store.load_state().incidents)


class TestFinalize:
    @pytest.mark.asyncio
    async def test_finalize_writes_daily_record(self, tmp_path: Path) -> None:
        runner, broker, store = _runner(tmp_path, [{"AAA": 1.0}])
        tick = await runner.step(NOW)
        result = runner.finalize_day(NOW.date(), tick)
        assert result.status == "TRADED"
        records = store.ledger_records()
        assert len(records) == 1
        assert records[0]["equity"] == pytest.approx(10_000.0)
