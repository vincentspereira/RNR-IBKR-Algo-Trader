"""Intraday signal-driven paper session -- EXPERIMENTAL lane (delayed data).

Runs the three validated rsi2 configs as an intraday experiment: every
--interval seconds during regular trading hours, delayed quotes (IBKR paper
market data type 3, ~15 minutes behind) are appended to daily history as a
provisional today-bar, signals are recomputed, and signal changes are traded
immediately instead of waiting for the close.

THIS LANE IS NOT THE VALIDATED 90-DAY CLOCK. The research sweep validated
signal-on-close execution; this lane measures, with its own ledgers under
``logs/intraday_paper/<slot>/``, whether intraday execution helps or hurts.
Keep both running and compare the two lanes' ledgers after the clock ends.

Run (any time during US RTH; exits by itself at 15:55 ET):
    .venv/Scripts/python.exe tools/intraday_paper_run.py
    .venv/Scripts/python.exe tools/intraday_paper_run.py --once          # one tick, then exit
    .venv/Scripts/python.exe tools/intraday_paper_run.py --slot rsi2t10_calm75
    .venv/Scripts/python.exe tools/intraday_paper_run.py --status
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import math
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from pairs_paper_run import (  # noqa: E402
    _PRIMARY_EXCHANGE,
    IBKRBarSource,
    MappedBroker,
    _ibkr_symbol,
    _load_paper_account_from_env_file,
    _mask,
)
from taquant_paper_run import SLOTS, SlotSpec, _slot_risk_manager  # noqa: E402

from core_trading.ops.intraday_runner import (  # noqa: E402
    IntradayConfig,
    IntradayRunner,
    TickResult,
)
from core_trading.ops.pairs_live_runner import US_EASTERN, LedgerStore  # noqa: E402
from core_trading.ops.taquant_live_adapter import TAQuantRunnerStrategy  # noqa: E402

LEDGER_ROOT = REPO_ROOT / "logs" / "intraday_paper"
CLIENT_ID = 51  # smoke 43, engine 1, pairs 47, daily taquant 48
SESSION_END_ET = _dt.time(15, 55)
SESSION_START_ET = _dt.time(9, 45)


class IBKRDelayedQuotes:
    """Delayed snapshot quotes over a live ib_insync session.

    Contracts are qualified once; each poll is a single ``reqTickers``
    round-trip. Quote preference: delayed last, then delayed close.
    """

    def __init__(self, ib) -> None:
        self.ib = ib
        self._qualified: dict[str, object] = {}

    async def prime(self, symbols: list[str]) -> None:
        from ib_insync import Stock

        contracts = [
            Stock(
                _ibkr_symbol(s),
                "SMART",
                "USD",
                primaryExchange=_PRIMARY_EXCHANGE.get(s, ""),
            )
            for s in symbols
        ]
        qualified = await self.ib.qualifyContractsAsync(*contracts)
        for sym, contract in zip(symbols, qualified, strict=False):
            if getattr(contract, "conId", 0):
                self._qualified[sym] = contract
        missing = sorted(set(symbols) - set(self._qualified))
        if missing:
            print(f"WARN: {len(missing)} symbol(s) failed qualification: {', '.join(missing[:10])}")

    async def last_prices(self, symbols: list[str]) -> dict[str, float]:
        wanted = [s for s in symbols if s in self._qualified]
        if not wanted:
            return {}
        tickers = await self.ib.reqTickersAsync(
            *[self._qualified[s] for s in wanted]
        )
        out: dict[str, float] = {}
        for sym, ticker in zip(wanted, tickers, strict=False):
            price = ticker.marketPrice()
            if not (isinstance(price, float) and math.isfinite(price) and price > 0):
                price = float(getattr(ticker, "close", float("nan")) or float("nan"))
            if math.isfinite(price) and price > 0:
                out[sym] = float(price)
        return out


def _slot_parts(spec: SlotSpec, args: argparse.Namespace):
    from core_trading.data.universe import BUILTIN_UNIVERSES
    from core_trading.strategies.ta_quant import build_ta_quant_grid

    grid = dict(build_ta_quant_grid())
    strategy = TAQuantRunnerStrategy(grid[spec.name], formation_window=252)
    universe = list(BUILTIN_UNIVERSES[spec.universe_name].current_symbols())
    store = LedgerStore(LEDGER_ROOT / spec.name)
    config = IntradayConfig(
        equity_base=args.equity,
        min_order_notional=args.min_order_notional,
        max_orders_per_day=args.max_orders,
    )
    return strategy, universe, store, config


def _selected_slots(args: argparse.Namespace) -> tuple[SlotSpec, ...]:
    if not args.slot:
        return SLOTS
    by_name = {s.name: s for s in SLOTS}
    if args.slot not in by_name:
        raise SystemExit(f"ERR: unknown slot {args.slot!r}; known: {sorted(by_name)}")
    return (by_name[args.slot],)


def _cmd_status(args: argparse.Namespace) -> int:
    from core_trading.ops.paper_telemetry import book_telemetry

    for spec in _selected_slots(args):
        root = LEDGER_ROOT / spec.name
        t = book_telemetry(root, lane="intraday_paper", name=spec.name)
        print(f"=== intraday slot: {spec.name} ===")
        print(f"root:      {root}")
        print(f"traded:    {t.n_traded} days, equity "
              f"{float(t.equity.iloc[-1]) if not t.equity.empty else 0.0:,.2f}")
        print(f"halted:    {t.state.halted}"
              + (f" ({t.state.halt_reason})" if t.state.halted else ""))
        print(f"positions: {dict(sorted(t.state.positions.items()))}")
        if t.state.incidents:
            for inc in t.state.incidents:
                print(f"  incident: {inc}")
        print()
    return 0


async def _cmd_run(args: argparse.Namespace) -> int:
    now_et = _dt.datetime.now(US_EASTERN)
    today = now_et.date()
    if today.weekday() >= 5:
        print(f"OK: {today.isoformat()} is a weekend; nothing to do")
        return 0
    if not args.once and not (SESSION_START_ET <= now_et.time() <= SESSION_END_ET):
        print(
            f"SKIP: {now_et.isoformat(timespec='minutes')} outside intraday session "
            f"({SESSION_START_ET}-{SESSION_END_ET} ET)"
        )
        return 0

    paper_account = _load_paper_account_from_env_file()
    os.environ["IBKR_ACCOUNT_ID"] = paper_account
    if not paper_account.startswith("DU"):
        print("ERR: account does not look like a paper account (no DU prefix); aborting")
        return 1
    os.environ.setdefault("IBKR_PAPER_MAX_POSITION_SIZE", str(int(args.equity * 2.5)))
    os.environ.setdefault("IBKR_PAPER_MAX_DAILY_TRADES", "500")
    os.environ.setdefault("IBKR_MAX_CONCURRENT_POSITIONS", "200")

    from core_trading.adapters.ibkr_adapter import IBKRAdapter

    adapter = IBKRAdapter(
        host="127.0.0.1",
        port=7497,
        client_id=args.client_id,
        account_id=paper_account,
        paper_trading=True,
    )
    print(f"connecting to TWS paper (127.0.0.1:7497, account {_mask(paper_account)}) ...")
    if not await adapter.connect():
        print("SKIP: TWS unreachable")
        return 0

    try:
        # Delayed market data: free on paper accounts (type 3).
        adapter.ib.reqMarketDataType(3)
        bars = IBKRBarSource(adapter.ib)
        quotes = IBKRDelayedQuotes(adapter.ib)
        broker = MappedBroker(adapter)

        runners: list[tuple[SlotSpec, IntradayRunner]] = []
        primed: set[str] = set()
        for spec in _selected_slots(args):
            strategy, universe, store, config = _slot_parts(spec, args)
            print(f"bootstrapping {spec.name}: {len(universe)} symbols of daily history ...")
            history = await bars.daily_closes(universe, "2 Y")
            if history.empty:
                print(f"ERR: no history for slot {spec.name}; skipping slot")
                continue
            # Drop today's (partial) bar: the provisional bar comes from quotes.
            history = history[history.index.map(lambda ts: pd.Timestamp(ts).date()) < today]
            to_prime = [s for s in history.columns if s not in primed]
            await quotes.prime(to_prime)
            primed.update(to_prime)
            runner = IntradayRunner(
                strategy,
                broker,
                quotes,
                store,
                history,
                risk_manager=_slot_risk_manager(spec),
                config=config,
            )
            runners.append((spec, runner))

        last_ticks: dict[str, TickResult] = {}
        while True:
            now_et = _dt.datetime.now(US_EASTERN)
            if not args.once and now_et.time() >= SESSION_END_ET:
                break
            for spec, runner in runners:
                try:
                    tick = await runner.step(now_et.replace(tzinfo=None))
                    last_ticks[spec.name] = tick
                    note = (
                        f"halted: {'; '.join(tick.violations)}"
                        if tick.status == "HALTED"
                        else f"equity {tick.equity:,.2f} gross {tick.gross_leverage:.2f} "
                        f"active {tick.n_active} orders {len(tick.orders)}"
                    )
                    print(f"[{tick.timestamp}] {spec.name}: {note}", flush=True)
                except Exception as exc:
                    print(f"ERR: tick failed for {spec.name}: {type(exc).__name__}: {exc}")
            if args.once:
                break
            await asyncio.sleep(args.interval)

        for spec, runner in runners:
            if not args.once:
                result = runner.finalize_day(today, last_ticks.get(spec.name))
                print(f"finalized {spec.name}: {result.status} equity {result.equity:,.2f}")
    finally:
        await adapter.disconnect()

    try:
        from paper_report import generate_report

        print(f"report refreshed: {generate_report()}")
    except Exception as exc:
        print(f"WARN: report generation failed: {type(exc).__name__}: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status", action="store_true", help="print intraday ledgers and exit")
    parser.add_argument("--slot", default=None, help="restrict to one slot")
    parser.add_argument("--once", action="store_true", help="single tick then exit (smoke test)")
    parser.add_argument("--interval", type=int, default=300, help="seconds between polls (default 300)")
    parser.add_argument("--equity", type=float, default=10_000.0, help="equity base PER SLOT (default 10000)")
    parser.add_argument("--min-order-notional", type=float, default=200.0)
    parser.add_argument("--max-orders", type=int, default=60, help="per-slot daily order budget")
    parser.add_argument("--client-id", type=int, default=CLIENT_ID)
    args = parser.parse_args(argv)

    if args.status:
        return _cmd_status(args)
    return asyncio.run(_cmd_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
