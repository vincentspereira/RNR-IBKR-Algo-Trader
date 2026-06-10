"""Pairs live paper-trading runner (master plan Phase 4.10 -- the 90-day clock).

Where :class:`~core_trading.ops.pairs_paper_trading.PairsPaperTrader` is a
risk-gated *walk-forward simulator* over historical data, this module is the
*live* daily driver: it runs once per trading day shortly before the US close,
against a real IBKR paper account, and is what starts (and accrues) the
90-calendar-day paper record the promotion gate requires.

One run does, in order:

1.  **Halt guard** -- if a previous run tripped the kill switch, do nothing
    until the operator clears it (``state.halted``).
2.  **Data** -- fetch daily close bars for the universe from the injected
    :class:`BarSource`. If the latest bar is not today's (US/Eastern) session,
    the market is closed or the feed is stale: the day is recorded as SKIPPED
    and no orders are placed.
3.  **Formation anchor** -- on the first run the formation window is pinned:
    ``state.formation_anchor`` is set so that the strategy's
    ``formation_window`` bars end yesterday and trading starts today. Every
    later run slices the price frame from that same anchor, so pair selection
    and the signal state machine are recomputed deterministically over an
    identical, growing window -- formation stays fixed, exactly the backtest
    convention (Gatev formation/trading split), and no signal internals need
    to be persisted.
4.  **Risk gates** -- the day's target weights pass
    :meth:`PairsRiskManager.pre_trade`, and the marked equity series passes
    :meth:`PairsRiskManager.daily_check`. A breach trips the kill switch:
    the book is flattened with market orders, the incident is recorded, and
    ``state.halted`` blocks all future runs until reset.
5.  **Rebalance** -- target weights are converted to whole-share target
    positions at the strategy's compounding equity, deltas against the
    current book become market orders, and fills are polled to completion.
    Whole-share rounding diagnostics (per-leg tracking error, dropped legs)
    are recorded honestly -- at a small equity base they are material.
6.  **Ledger** -- one JSONL record per day (equity mark, return, leverage,
    orders, fills, violations, rounding diagnostics) plus a per-fill record
    stream for downstream TCA / reconciliation. The promotion gate
    (90+ active days, zero incidents, paper Sharpe within one standard error
    of the backtest Sharpe) is re-evaluated from the ledger after every run.

The broker and bar feed are injected behind small protocols so the whole
orchestration is unit-testable with deterministic fakes; the IBKR-facing
implementations live in ``tools/pairs_paper_run.py``.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import math
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from core_trading.backtest.metrics import sharpe_ratio
from core_trading.ops.pairs_paper_trading import (
    PromotionDecision,
    sharpe_standard_error,
)
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits
from core_trading.strategies.pairs_trading import PairsTradingStrategy

__all__ = [
    "RunnerConfig",
    "RunnerState",
    "BrokerLike",
    "BarSource",
    "LedgerStore",
    "DayResult",
    "PairsLiveRunner",
    "execute_market_orders",
]

US_EASTERN = zoneinfo.ZoneInfo("America/New_York")

# Run-day outcome statuses written to the ledger.
STATUS_TRADED = "TRADED"
STATUS_SKIPPED = "SKIPPED"
STATUS_HALTED = "HALTED"
STATUS_ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Configuration / state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Live-runner configuration.

    Attributes
    ----------
    equity_base:
        Strategy equity at the start of the paper run. The strategy sizes
        positions off its *compounding* equity (cash + marked positions),
        seeded with this value -- not the whole paper account.
    backtest_sharpe, promotion_se_mult, min_paper_days, periods_per_year:
        Promotion-gate parameters, mirroring
        :class:`~core_trading.ops.pairs_paper_trading.PaperConfig`. Pin
        ``backtest_sharpe`` to the validated backtest figure before relying
        on the gate's verdict.
    history_duration:
        IBKR duration string requested from the bar source each run. Two
        years of daily bars comfortably covers formation (252 bars) plus a
        90+ day trading window.
    fill_timeout_s, poll_interval_s:
        Per-order fill polling budget. SP100 market orders near the close
        fill in seconds; an order still unfilled at the timeout is recorded
        as an incident.
    min_fraction_for_share:
        Rounding threshold: a leg receives its first share only when the
        target notional is at least this fraction of one share's price.
        0.5 is round-half-away-from-zero.
    halt_on_breach:
        Kill switch on the first risk breach (flatten + block future runs).
    """

    equity_base: float = 25_000.0
    backtest_sharpe: float = 1.0
    promotion_se_mult: float = 1.0
    min_paper_days: int = 90
    periods_per_year: int = 252
    history_duration: str = "2 Y"
    fill_timeout_s: float = 45.0
    poll_interval_s: float = 1.0
    min_fraction_for_share: float = 0.5
    halt_on_breach: bool = True

    def __post_init__(self) -> None:
        if self.equity_base <= 0:
            raise ValueError("equity_base must be positive")
        if self.min_paper_days < 1:
            raise ValueError("min_paper_days must be at least 1")
        if not (0.0 < self.min_fraction_for_share <= 1.0):
            raise ValueError("min_fraction_for_share must be in (0, 1]")
        if self.fill_timeout_s <= 0 or self.poll_interval_s <= 0:
            raise ValueError("fill polling parameters must be positive")


@dataclass(slots=True)
class RunnerState:
    """Mutable cross-run state, persisted as ``state.json``."""

    started: str | None = None
    formation_anchor: str | None = None
    cash: float = 0.0
    positions: dict[str, int] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None
    last_run_date: str | None = None
    incidents: list[str] = field(default_factory=list)
    # Incidents the operator has reviewed and explicitly resolved (via the
    # CLI's --resolve-incidents). Kept for audit; no longer block promotion.
    resolved_incidents: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "formation_anchor": self.formation_anchor,
            "cash": self.cash,
            "positions": dict(self.positions),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "last_run_date": self.last_run_date,
            "incidents": list(self.incidents),
            "resolved_incidents": list(self.resolved_incidents),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RunnerState:
        return cls(
            started=data.get("started"),
            formation_anchor=data.get("formation_anchor"),
            cash=float(data.get("cash", 0.0)),
            positions={str(k): int(v) for k, v in (data.get("positions") or {}).items()},
            halted=bool(data.get("halted", False)),
            halt_reason=data.get("halt_reason"),
            last_run_date=data.get("last_run_date"),
            incidents=[str(s) for s in (data.get("incidents") or [])],
            resolved_incidents=[str(s) for s in (data.get("resolved_incidents") or [])],
        )


# ---------------------------------------------------------------------------
# Injection seams
# ---------------------------------------------------------------------------


class BrokerLike(Protocol):
    """The slice of the IBKR adapter the runner needs (fake-able in tests)."""

    async def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an order; returns at least ``order_id`` and ``status``."""
        ...

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Return at least ``status``, ``filled_quantity``, ``avg_fill_price``."""
        ...


class BarSource(Protocol):
    """Daily-close provider (fake-able in tests)."""

    async def daily_closes(self, symbols: list[str], duration: str) -> pd.DataFrame:
        """Return a (date x symbol) wide close frame, oldest first.

        Symbols with no data may be absent from the columns. The index must
        be tz-naive dates of US/Eastern trading sessions.
        """
        ...


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class LedgerStore:
    """File-backed state + append-only daily ledger and fill stream.

    Layout under ``root``::

        state.json    -- RunnerState (overwritten each run)
        ledger.jsonl  -- one JSON record per run day (append-only)
        fills.jsonl   -- one JSON record per fill (append-only)
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        self.ledger_path = self.root / "ledger.jsonl"
        self.fills_path = self.root / "fills.jsonl"

    def load_state(self) -> RunnerState:
        if not self.state_path.exists():
            return RunnerState()
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return RunnerState.from_json(data)

    def save_state(self, state: RunnerState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def append_ledger(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def append_fills(self, fills: list[dict[str, Any]]) -> None:
        if not fills:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self.fills_path.open("a", encoding="utf-8") as fh:
            for fill in fills:
                fh.write(json.dumps(fill, sort_keys=True) + "\n")

    def ledger_records(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        records = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def traded_records(self) -> list[dict[str, Any]]:
        """TRADED-day records, excluding dry runs (oldest first)."""
        return [
            r
            for r in self.ledger_records()
            if r.get("status") == STATUS_TRADED and not r.get("dry_run")
        ]

    def equity_series(self) -> pd.Series:
        """Equity marks of all TRADED days, oldest first."""
        records = self.traded_records()
        if not records:
            return pd.Series(dtype=float)
        return pd.Series(
            [float(r["equity"]) for r in records],
            index=pd.to_datetime([r["date"] for r in records]),
        )

    def active_returns(self) -> pd.Series:
        """Realised daily returns of TRADED days with nonzero return.

        Mirrors :meth:`PairsPaperTrader.paper_returns`: flat days do not
        count toward the promotion gate's active-day requirement.
        """
        records = self.traded_records()
        if not records:
            return pd.Series(dtype=float)
        returns = pd.Series(
            [float(r["daily_return"]) for r in records],
            index=pd.to_datetime([r["date"] for r in records]),
        )
        return returns[returns != 0.0]


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DayResult:
    """Outcome of one :meth:`PairsLiveRunner.run_once` invocation."""

    date: str
    status: str
    reason: str = ""
    equity: float = 0.0
    daily_return: float = 0.0
    gross_leverage: float = 0.0
    n_active_pairs: int = 0
    n_pairs_selected: int = 0
    gross_budget: float = 0.0
    orders: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    rounding: dict[str, Any] = field(default_factory=dict)
    promotion: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "status": self.status,
            "reason": self.reason,
            "equity": round(self.equity, 2),
            "daily_return": self.daily_return,
            "gross_leverage": round(self.gross_leverage, 6),
            "n_active_pairs": self.n_active_pairs,
            "n_pairs_selected": self.n_pairs_selected,
            "gross_budget": round(self.gross_budget, 6),
            "orders": self.orders,
            "fills": self.fills,
            "violations": self.violations,
            "rounding": self.rounding,
            "promotion": self.promotion,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def execute_market_orders(
    broker: BrokerLike,
    orders: list[dict[str, Any]],
    state: RunnerState,
    run_date: str,
    *,
    fill_timeout_s: float,
    poll_interval_s: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Place market orders, poll fills, apply them to ``state`` cash/positions.

    Shared by the daily and intraday runners. Positions and cash move only
    on *observed* fills, so an unfilled or partially filled order leaves the
    book consistent with the broker. Returns (fill records, incidents).
    """
    fills: list[dict[str, Any]] = []
    incidents: list[str] = []
    for order in orders:
        response = await broker.place_order(dict(order))
        if response.get("status") == "rejected":
            incidents.append(
                f"{run_date}: order rejected {order['side']} "
                f"{order['quantity']} {order['symbol']}: "
                f"{response.get('reason', 'no reason given')}"
            )
            continue
        order_id = str(response.get("order_id"))
        deadline = fill_timeout_s
        filled_qty = 0.0
        avg_price = 0.0
        status = str(response.get("status", ""))
        terminal = {"filled", "cancelled", "canceled", "rejected", "inactive"}
        while deadline > 0:
            st = await broker.get_order_status(order_id)
            status = str(st.get("status", ""))
            filled_qty = float(st.get("filled_quantity") or 0.0)
            avg_price = float(st.get("avg_fill_price") or 0.0)
            if status.lower() in terminal:
                # Filled is success; the other terminal states will never
                # fill, so burning the rest of the poll budget is pointless.
                break
            await asyncio.sleep(poll_interval_s)
            deadline -= poll_interval_s
        if filled_qty > 0:
            sign = 1 if order["side"] == "buy" else -1
            signed_qty = int(round(sign * filled_qty))
            state.positions[order["symbol"]] = (
                state.positions.get(order["symbol"], 0) + signed_qty
            )
            if state.positions[order["symbol"]] == 0:
                del state.positions[order["symbol"]]
            state.cash -= signed_qty * avg_price
            fills.append(
                {
                    "date": run_date,
                    "order_id": order_id,
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "quantity": abs(signed_qty),
                    "avg_price": avg_price,
                    "status": status,
                }
            )
        if status.lower() != "filled":
            incidents.append(
                f"{run_date}: order {order_id} ({order['side']} "
                f"{order['quantity']} {order['symbol']}) not fully filled "
                f"within {fill_timeout_s:.0f}s (status={status}, "
                f"filled={filled_qty})"
            )
    return fills, incidents


def _round_shares(notional: float, price: float, min_fraction: float) -> int:
    """Whole-share count for a signed target notional at ``price``.

    Round-half-away-from-zero with a first-share threshold: no share is
    allocated unless ``|notional| >= min_fraction * price``.
    """
    if price <= 0 or not math.isfinite(price):
        return 0
    raw = notional / price
    if abs(raw) < min_fraction:
        return 0
    return int(math.copysign(math.floor(abs(raw) + (1.0 - min_fraction)), raw))


class PairsLiveRunner:
    """Daily near-close rebalance driver for the live paper pilot.

    Parameters
    ----------
    strategy:
        Configured :class:`PairsTradingStrategy`.
    broker:
        Order-placement seam (the IBKR adapter in production).
    bars:
        Daily-close seam (IBKR historical bars in production).
    store:
        Ledger / state persistence.
    universe:
        Symbols fed to pair selection.
    risk_manager:
        Pre-trade and circuit-breaker gate. The default aligns the gross cap
        with the strategy's own portfolio cap (as the Phase 4 integration
        tests do) and gives the per-symbol check 5x headroom over the
        portfolio per-pair cap: a pair's x-leg is scaled by its hedge ratio
        ``|beta|`` (2-3 is routine for dissimilar price levels), so the
        leg-level check is a gross mis-sizing backstop rather than a second
        copy of the constructor's pair cap. The sector check gets a 0.40 cap
        with a 0.25-gross materiality floor -- relative concentration is
        meaningless while only the first pair or two has entered.
    config:
        Runner configuration.
    sectors:
        Optional symbol -> sector map for the sector-concentration gate.
    """

    def __init__(
        self,
        strategy: PairsTradingStrategy,
        broker: BrokerLike,
        bars: BarSource,
        store: LedgerStore,
        universe: list[str],
        *,
        risk_manager: PairsRiskManager | None = None,
        config: RunnerConfig | None = None,
        sectors: dict[str, str] | None = None,
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.bars = bars
        self.store = store
        self.universe = list(universe)
        self.config = config or RunnerConfig()
        if risk_manager is None:
            # Default limits derive from the pairs portfolio config; callers
            # whose strategy config has no ``portfolio`` (e.g. the TA-quant
            # adapter) must inject an explicit risk manager.
            port = strategy.config.portfolio
            risk_manager = PairsRiskManager(
                RiskLimits(
                    gross_leverage_cap=port.gross_leverage_cap,
                    per_pair_cap=5.0 * port.per_pair_cap,
                    sector_cap=0.40,
                    sector_check_min_gross=0.25,
                )
            )
        self.risk_manager = risk_manager
        self.sectors = sectors

    # ----------------------------------------------------------------- equity
    def _mark_equity(self, state: RunnerState, closes: pd.Series) -> float:
        value = state.cash
        for sym, qty in state.positions.items():
            px = closes.get(sym)
            if px is None or not math.isfinite(float(px)):
                raise ValueError(f"no close price to mark position in {sym}")
            value += qty * float(px)
        return float(value)

    # -------------------------------------------------------------- promotion
    def evaluate_promotion(self, state: RunnerState) -> PromotionDecision:
        """Promotion gate over the ledger's realised paper returns."""
        cfg = self.config
        returns = self.store.active_returns()
        n_days = int(returns.size)
        paper_sharpe = (
            sharpe_ratio(returns.to_numpy(), cfg.periods_per_year) if n_days else 0.0
        )
        se = sharpe_standard_error(paper_sharpe, n_days)
        floor = cfg.backtest_sharpe - cfg.promotion_se_mult * se

        reasons: list[str] = []
        if n_days < cfg.min_paper_days:
            reasons.append(
                f"insufficient paper history: {n_days} < {cfg.min_paper_days} days"
            )
        if state.incidents:
            reasons.append(f"{len(state.incidents)} unresolved risk incident(s)")
        if math.isfinite(se) and paper_sharpe < floor:
            reasons.append(
                f"paper Sharpe {paper_sharpe:.2f} below promotion floor {floor:.2f} "
                f"(backtest {cfg.backtest_sharpe:.2f} - {cfg.promotion_se_mult} SE)"
            )
        return PromotionDecision(
            eligible=not reasons,
            reasons=tuple(reasons),
            paper_sharpe=paper_sharpe,
            backtest_sharpe=cfg.backtest_sharpe,
            sharpe_standard_error=se,
            n_days=n_days,
            n_incidents=len(state.incidents),
        )

    # ------------------------------------------------------------------ frame
    def _prepare_frame(
        self, closes: pd.DataFrame, state: RunnerState, today: _dt.date
    ) -> pd.DataFrame | None:
        """Slice the close frame from the formation anchor through today.

        Pins the anchor on first run. Returns ``None`` when there is not yet
        enough history for one formation window plus today's bar.
        """
        formation = self.strategy.config.formation_window
        closes = closes.sort_index()

        if state.formation_anchor is None:
            if len(closes.index) < formation + 1:
                return None
            anchor_ts = closes.index[-(formation + 1)]
            state.formation_anchor = pd.Timestamp(anchor_ts).date().isoformat()
            state.started = today.isoformat()

        anchor = pd.Timestamp(state.formation_anchor)
        frame = closes.loc[closes.index >= anchor]
        if len(frame.index) < formation + 1:
            return None

        # Symbol hygiene: a column must have a price today and essentially
        # complete history over the window; small gaps are forward-filled.
        last_row = frame.iloc[-1]
        ok_cols = [
            c
            for c in frame.columns
            if math.isfinite(float(last_row[c]))
            and frame[c].isna().mean() <= 0.02
        ]
        # Symbols the book already holds must stay markable even if they fail
        # the history screen.
        held = [s for s in state.positions if state.positions.get(s)]
        for sym in held:
            if sym in frame.columns and sym not in ok_cols:
                ok_cols.append(sym)
        return frame[ok_cols].ffill()

    # ----------------------------------------------------------------- orders
    def _target_shares(
        self, weights: pd.Series, closes: pd.Series, equity: float
    ) -> tuple[dict[str, int], dict[str, Any]]:
        """Convert target weights to whole-share positions with diagnostics."""
        cfg = self.config
        targets: dict[str, int] = {}
        dropped: list[str] = []
        target_gross = 0.0
        achieved_gross = 0.0
        abs_error = 0.0
        for sym, w in weights.items():
            w = float(w)
            if w == 0.0:
                continue
            price = float(closes[sym])
            notional = w * equity
            shares = _round_shares(notional, price, cfg.min_fraction_for_share)
            achieved = shares * price
            target_gross += abs(notional)
            achieved_gross += abs(achieved)
            abs_error += abs(achieved - notional)
            if shares == 0:
                dropped.append(sym)
            else:
                targets[sym] = shares
        diagnostics = {
            "target_gross_notional": round(target_gross, 2),
            "achieved_gross_notional": round(achieved_gross, 2),
            "abs_tracking_error_notional": round(abs_error, 2),
            "tracking_error_frac_of_gross": (
                round(abs_error / target_gross, 4) if target_gross > 0 else 0.0
            ),
            "dropped_legs": sorted(dropped),
        }
        return targets, diagnostics

    @staticmethod
    def _delta_orders(
        current: dict[str, int], target: dict[str, int]
    ) -> list[dict[str, Any]]:
        """Market orders that move the book from ``current`` to ``target``."""
        orders: list[dict[str, Any]] = []
        for sym in sorted(set(current) | set(target)):
            delta = target.get(sym, 0) - current.get(sym, 0)
            if delta == 0:
                continue
            orders.append(
                {
                    "symbol": sym,
                    "side": "buy" if delta > 0 else "sell",
                    "quantity": abs(delta),
                    "order_type": "market",
                }
            )
        return orders

    async def _execute(
        self, orders: list[dict[str, Any]], state: RunnerState, run_date: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Place orders, poll fills, apply them to cash/positions.

        Positions and cash move only on *observed* fills, so an unfilled or
        partially filled order leaves the book consistent with the broker.
        Returns (fill records, incident strings).
        """
        return await execute_market_orders(
            self.broker,
            orders,
            state,
            run_date,
            fill_timeout_s=self.config.fill_timeout_s,
            poll_interval_s=self.config.poll_interval_s,
        )

    # -------------------------------------------------------------------- run
    async def run_once(
        self, *, today: _dt.date | None = None, dry_run: bool = False
    ) -> DayResult:
        """Execute one daily rebalance cycle. See the module docstring."""
        if today is None:
            today = _dt.datetime.now(US_EASTERN).date()
        run_date = today.isoformat()
        state = self.store.load_state()

        if state.halted:
            result = DayResult(
                date=run_date,
                status=STATUS_HALTED,
                reason=f"kill switch engaged: {state.halt_reason}",
                dry_run=dry_run,
            )
            if not dry_run:
                self.store.append_ledger(result.to_record())
            return result

        if state.started is None:
            state.cash = self.config.equity_base

        # ------------------------------------------------------------- data
        closes = await self.bars.daily_closes(self.universe, self.config.history_duration)
        if closes.empty:
            result = DayResult(
                date=run_date,
                status=STATUS_ERROR,
                reason="bar source returned no data",
                dry_run=dry_run,
            )
            if not dry_run:
                self.store.append_ledger(result.to_record())
            return result

        last_bar = pd.Timestamp(closes.index.max()).date()
        if last_bar != today:
            result = DayResult(
                date=run_date,
                status=STATUS_SKIPPED,
                reason=f"no bar for today (latest bar {last_bar.isoformat()}): "
                "market closed or feed stale",
                dry_run=dry_run,
            )
            if not dry_run:
                self.store.append_ledger(result.to_record())
            return result

        frame = self._prepare_frame(closes, state, today)
        if frame is None:
            result = DayResult(
                date=run_date,
                status=STATUS_ERROR,
                reason="insufficient history for formation window",
                dry_run=dry_run,
            )
            if not dry_run:
                self.store.append_ledger(result.to_record())
            return result
        today_closes = frame.iloc[-1]

        # -------------------------------------------- pre-trade equity mark
        equity_pre = self._mark_equity(state, today_closes)
        prior_equity = self.store.equity_series()
        today_point = pd.Series([equity_pre], index=[pd.Timestamp(today)])
        marked = (
            today_point
            if prior_equity.empty
            else pd.concat([prior_equity, today_point])
        )

        violations: list[str] = []
        if len(marked) >= 2:
            daily = self.risk_manager.daily_check(marked.reset_index(drop=True))
            violations.extend(daily.violations)

        # ----------------------------------------------------------- signal
        weights = self.strategy.generate_weights(frame)
        target_row = weights.iloc[-1]
        gross = float(target_row.abs().sum())
        n_active = int((target_row.abs() > 0).sum()) // 2
        # Selection diagnostics (real strategy only; absent on test stubs).
        n_selected = len(getattr(self.strategy, "plans", []))
        gross_budget = float(getattr(self.strategy, "gross_budget", 0.0))

        proposed = {s: float(v) for s, v in target_row.items() if v != 0.0}
        pre = self.risk_manager.pre_trade(proposed, sectors=self.sectors)
        violations.extend(pre.violations)

        halt_now = bool(violations) and self.config.halt_on_breach
        if halt_now:
            # Kill switch: flatten everything, then block future runs.
            target_row = target_row * 0.0
            gross = 0.0
            n_active = 0

        # ---------------------------------------------------------- sizing
        targets, rounding = self._target_shares(target_row, today_closes, equity_pre)
        orders = self._delta_orders(state.positions, targets)

        # -------------------------------------------------------- execution
        fills: list[dict[str, Any]] = []
        incidents: list[str] = []
        if dry_run:
            status = STATUS_TRADED if not halt_now else STATUS_HALTED
        else:
            fills, incidents = await self._execute(orders, state, run_date)
            status = STATUS_TRADED if not halt_now else STATUS_HALTED

        # ------------------------------------------------------ equity mark
        equity_post = self._mark_equity(state, today_closes) if not dry_run else equity_pre
        prev_records = self.store.traded_records()
        prev_equity = (
            float(prev_records[-1]["equity"]) if prev_records else self.config.equity_base
        )
        daily_return = equity_post / prev_equity - 1.0 if prev_equity > 0 else 0.0

        if halt_now:
            reason = "; ".join(violations)
            state.halted = True
            state.halt_reason = reason
            state.incidents.append(f"{run_date}: {reason}")
        for inc in incidents:
            state.incidents.append(inc)

        state.last_run_date = run_date

        promotion = self.evaluate_promotion(state)
        result = DayResult(
            date=run_date,
            status=status,
            reason=state.halt_reason or "",
            equity=equity_post,
            daily_return=float(np.round(daily_return, 10)),
            gross_leverage=gross,
            n_active_pairs=n_active,
            n_pairs_selected=n_selected,
            gross_budget=gross_budget,
            orders=orders,
            fills=fills,
            violations=violations,
            rounding=rounding,
            promotion={
                "eligible": promotion.eligible,
                "reasons": list(promotion.reasons),
                "paper_sharpe": round(promotion.paper_sharpe, 4),
                "n_days": promotion.n_days,
                "n_incidents": promotion.n_incidents,
            },
            dry_run=dry_run,
        )

        if not dry_run:
            # Dry runs leave no trace: no state mutation, no ledger record, so
            # the equity/return series the gates read stays purely realised.
            self.store.save_state(state)
            self.store.append_fills(fills)
            self.store.append_ledger(result.to_record())
        return result
