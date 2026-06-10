"""Intraday signal-driven paper runner -- EXPERIMENTAL execution lane.

Where the daily runner (:mod:`.pairs_live_runner`) trades once near the
close, this runner polls quotes every few minutes during regular trading
hours, recomputes the strategy's signal on a PROVISIONAL today-bar (daily
history through yesterday + the latest delayed price as today's close), and
trades signal changes as they appear.

The honest caveat, stated once and loudly: **this execution mode is not what
the research sweep validated.** The validated convention is signal-on-close,
trade-into-close. Trading the same signal intraday changes entry prices and
can change the signal itself (a dip at 11:00 may not still be a dip at the
close). That is exactly why this lane exists as a separate experiment with
its own ledgers (``logs/intraday_paper/<slot>/``) and never touches the
90-day clock books. After 90 days the two lanes' ledgers answer "does
intraday execution help or hurt?" with data instead of opinion.

Data: designed for IBKR delayed quotes (paper accounts get 15-minute
delayed market data for free via market data type 3). The quote seam is a
protocol, so tests inject deterministic fakes and a different vendor (e.g.
yfinance) could be slotted in later.

Crash safety: ``state.json`` is persisted after every executed tick, so a
killed process resumes with the broker-consistent book. Each poll appends a
record to ``ticks.jsonl``; one DayResult ledger record is written by
:meth:`IntradayRunner.finalize_day`.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from core_trading.ops.pairs_live_runner import (
    STATUS_HALTED,
    STATUS_TRADED,
    BrokerLike,
    DayResult,
    LedgerStore,
    RunnerState,
    _round_shares,
    execute_market_orders,
)
from core_trading.risk.pairs_risk import PairsRiskManager

__all__ = ["IntradayConfig", "QuoteSource", "TickResult", "IntradayRunner"]


class QuoteSource(Protocol):
    """Latest-price provider (delayed is fine; fake-able in tests)."""

    async def last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Return ``symbol -> last price`` for the symbols it can quote."""
        ...


@dataclass(frozen=True, slots=True)
class IntradayConfig:
    """Intraday runner configuration.

    Attributes
    ----------
    equity_base:
        Slot equity seeded into cash on the first ever tick.
    min_order_notional:
        Skip rebalance deltas smaller than this (churn guard): intraday
        polling would otherwise trade one-share dust on every noise tick.
    max_orders_per_day:
        Hard stop on order count per session (runaway-loop guard). Once
        reached, further ticks mark equity but place nothing.
    fill_timeout_s, poll_interval_s:
        Per-order fill polling budget (same semantics as the daily runner).
    min_fraction_for_share:
        First-share rounding threshold (see daily runner).
    halt_on_breach:
        Kill switch on risk violations: flatten and block future ticks.
    """

    equity_base: float = 10_000.0
    min_order_notional: float = 200.0
    max_orders_per_day: int = 60
    fill_timeout_s: float = 45.0
    poll_interval_s: float = 1.0
    min_fraction_for_share: float = 0.5
    halt_on_breach: bool = True

    def __post_init__(self) -> None:
        if self.equity_base <= 0:
            raise ValueError("equity_base must be positive")
        if self.min_order_notional < 0:
            raise ValueError("min_order_notional must be >= 0")
        if self.max_orders_per_day < 1:
            raise ValueError("max_orders_per_day must be >= 1")


@dataclass(slots=True)
class TickResult:
    """Outcome of one intraday poll."""

    timestamp: str
    status: str  # TRADED (tick processed) or HALTED
    equity: float = 0.0
    gross_leverage: float = 0.0
    n_quoted: int = 0
    n_active: int = 0
    orders: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    skipped_small: int = 0

    def to_record(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "equity": round(self.equity, 2),
            "gross_leverage": round(self.gross_leverage, 6),
            "n_quoted": self.n_quoted,
            "n_active": self.n_active,
            "n_orders": len(self.orders),
            "orders": self.orders,
            "n_fills": len(self.fills),
            "violations": self.violations,
            "skipped_small": self.skipped_small,
        }


class IntradayRunner:
    """Signal-flip rebalancer over delayed quotes.

    Parameters
    ----------
    strategy:
        Object with ``generate_weights(wide_close_frame) -> wide weight
        frame`` (e.g. :class:`~core_trading.ops.taquant_live_adapter.TAQuantRunnerStrategy`).
    broker, quotes, store:
        Injection seams (IBKR adapter, delayed quote source, ledger store).
    history_closes:
        Daily close frame through YESTERDAY for the universe, loaded once
        per session by the entry-point tool. Today's provisional bar is
        appended from quotes on every tick.
    risk_manager:
        Pre-trade and drawdown gates (slot-specific backstops).
    config:
        :class:`IntradayConfig`.
    """

    def __init__(
        self,
        strategy: Any,
        broker: BrokerLike,
        quotes: QuoteSource,
        store: LedgerStore,
        history_closes: pd.DataFrame,
        *,
        risk_manager: PairsRiskManager,
        config: IntradayConfig | None = None,
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.quotes = quotes
        self.store = store
        self.history = history_closes.sort_index()
        self.risk_manager = risk_manager
        self.config = config or IntradayConfig()
        self._orders_today = 0
        self.ticks_path = store.root / "ticks.jsonl"

    # ------------------------------------------------------------------ utils
    def _append_tick(self, tick: TickResult) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        with self.ticks_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(tick.to_record(), sort_keys=True) + "\n")

    @staticmethod
    def _mark_equity(state: RunnerState, prices: dict[str, float]) -> float:
        value = state.cash
        for sym, qty in state.positions.items():
            px = prices.get(sym)
            if px is None or not math.isfinite(px) or px <= 0:
                raise ValueError(f"no quote to mark position in {sym}")
            value += qty * px
        return float(value)

    # ------------------------------------------------------------------- tick
    async def step(self, now: _dt.datetime) -> TickResult:
        """One poll: quotes -> provisional bar -> signal -> delta orders."""
        cfg = self.config
        state = self.store.load_state()
        stamp = now.isoformat(timespec="seconds")
        today = now.date()

        if state.halted:
            tick = TickResult(
                timestamp=stamp,
                status=STATUS_HALTED,
                violations=[f"kill switch engaged: {state.halt_reason}"],
            )
            self._append_tick(tick)
            return tick

        if state.started is None:
            state.started = today.isoformat()
            state.cash = cfg.equity_base

        symbols = [str(c) for c in self.history.columns]
        prices = await self.quotes.last_prices(symbols)
        prices = {
            s: float(p)
            for s, p in prices.items()
            if math.isfinite(float(p)) and float(p) > 0
        }
        # Held names MUST be quotable, or the book cannot be marked.
        unmarkable = [s for s in state.positions if s not in prices]
        if unmarkable:
            tick = TickResult(
                timestamp=stamp,
                status=STATUS_TRADED,
                n_quoted=len(prices),
                violations=[f"no quote for held position(s): {', '.join(unmarkable)}"],
            )
            self._append_tick(tick)
            return tick

        quoted = [s for s in symbols if s in prices]
        frame = self.history[quoted].copy()
        provisional = pd.Series({s: prices[s] for s in quoted}, name=pd.Timestamp(today))
        frame = pd.concat([frame, provisional.to_frame().T]).ffill()

        equity = self._mark_equity(state, prices)

        weights = self.strategy.generate_weights(frame)
        target_row = weights.iloc[-1]
        gross = float(target_row.abs().sum())
        n_active = int((target_row.abs() > 0).sum())

        proposed = {s: float(v) for s, v in target_row.items() if v != 0.0}
        check = self.risk_manager.pre_trade(proposed, sectors=None)
        violations = list(check.violations)

        if violations and cfg.halt_on_breach:
            target_row = target_row * 0.0

        # Whole-share targets, with a churn guard on small deltas.
        targets: dict[str, int] = {}
        for sym, w in target_row.items():
            w = float(w)
            if w == 0.0:
                continue
            shares = _round_shares(w * equity, prices[str(sym)], cfg.min_fraction_for_share)
            if shares != 0:
                targets[str(sym)] = shares

        orders: list[dict[str, Any]] = []
        skipped_small = 0
        for sym in sorted(set(state.positions) | set(targets)):
            delta = targets.get(sym, 0) - state.positions.get(sym, 0)
            if delta == 0:
                continue
            notional = abs(delta) * prices[sym]
            # The churn guard never blocks a full exit (target 0).
            if notional < cfg.min_order_notional and targets.get(sym, 0) != 0:
                skipped_small += 1
                continue
            orders.append(
                {
                    "symbol": sym,
                    "side": "buy" if delta > 0 else "sell",
                    "quantity": abs(delta),
                    "order_type": "market",
                }
            )

        budget = cfg.max_orders_per_day - self._orders_today
        if len(orders) > budget:
            violations.append(
                f"order budget exhausted: {len(orders)} wanted, {budget} left today"
            )
            orders = orders[: max(0, budget)]

        fills: list[dict[str, Any]] = []
        incidents: list[str] = []
        if orders:
            fills, incidents = await execute_market_orders(
                self.broker,
                orders,
                state,
                today.isoformat(),
                fill_timeout_s=cfg.fill_timeout_s,
                poll_interval_s=cfg.poll_interval_s,
            )
            self._orders_today += len(orders)

        halt_now = bool(violations) and cfg.halt_on_breach
        if halt_now:
            state.halted = True
            state.halt_reason = "; ".join(violations)
            state.incidents.append(f"{stamp}: {state.halt_reason}")
        for inc in incidents:
            state.incidents.append(inc)

        equity_post = self._mark_equity(state, prices)
        state.last_run_date = today.isoformat()
        self.store.save_state(state)
        self.store.append_fills(fills)

        tick = TickResult(
            timestamp=stamp,
            status=STATUS_HALTED if halt_now else STATUS_TRADED,
            equity=equity_post,
            gross_leverage=gross,
            n_quoted=len(prices),
            n_active=n_active,
            orders=orders,
            fills=fills,
            violations=violations + incidents,
            skipped_small=skipped_small,
        )
        self._append_tick(tick)
        return tick

    # ------------------------------------------------------------------- day
    def finalize_day(self, today: _dt.date, last_tick: TickResult | None) -> DayResult:
        """Write the one-per-day ledger record from the session's last tick."""
        state = self.store.load_state()
        equity = last_tick.equity if last_tick else 0.0
        prev = self.store.traded_records()
        prev_equity = float(prev[-1]["equity"]) if prev else self.config.equity_base
        daily_return = equity / prev_equity - 1.0 if prev_equity > 0 and equity > 0 else 0.0
        result = DayResult(
            date=today.isoformat(),
            status=STATUS_HALTED if state.halted else STATUS_TRADED,
            reason=state.halt_reason or "",
            equity=equity,
            daily_return=daily_return,
            gross_leverage=last_tick.gross_leverage if last_tick else 0.0,
            orders=[],
            fills=[],
            violations=list(last_tick.violations) if last_tick else [],
        )
        self.store.append_ledger(result.to_record())
        return result
