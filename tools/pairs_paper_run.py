"""Daily pairs paper-trading run (master plan Phase 4.10 -- the 90-day clock).

The Windows Task Scheduler entrypoint for the live paper pilot. Invoked at
20:30 UK time Mon-Fri (about 25 minutes before the US close most of the
year), it:

1. connects to TWS paper (port 7497) with the DU-prefix safety rail,
2. fetches daily close bars for the SP100 universe (paced historical
   requests through the live ib_insync session),
3. hands everything to :class:`core_trading.ops.pairs_live_runner.PairsLiveRunner`,
   which gates, sizes, places market orders into the close, and appends the
   day to the 90-day ledger under ``logs/pairs_paper/``.

If TWS is not running, the day is recorded as SKIPPED and the script exits
cleanly -- a skipped day stretches the calendar but never corrupts the
ledger.

Run manually:
    .venv/Scripts/python.exe tools/pairs_paper_run.py            # live paper run
    .venv/Scripts/python.exe tools/pairs_paper_run.py --dry-run  # no orders, no ledger
    .venv/Scripts/python.exe tools/pairs_paper_run.py --status   # ledger + promotion summary
    .venv/Scripts/python.exe tools/pairs_paper_run.py --reset-halt
    .venv/Scripts/python.exe tools/pairs_paper_run.py --resolve-incidents
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import os
import sys
import traceback
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core_trading.ops.pairs_live_runner import (  # noqa: E402
    US_EASTERN,
    DayResult,
    LedgerStore,
    PairsLiveRunner,
    RunnerConfig,
)

LEDGER_ROOT = REPO_ROOT / "logs" / "pairs_paper"
CLIENT_ID = 47  # distinct from the smoke test (43) and trading engine (1)


def _mask(acct: str) -> str:
    if len(acct) <= 4:
        return "*" * len(acct)
    return acct[:2] + "*" * (len(acct) - 4) + acct[-2:]


def _load_paper_account_from_env_file() -> str:
    """Read IBKR_ACCOUNT_ID_PAPER from .env without printing it."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        raise SystemExit("ERR: .env not found at repo root")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("IBKR_ACCOUNT_ID_PAPER="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise SystemExit("ERR: IBKR_ACCOUNT_ID_PAPER not set in .env")


def _ibkr_symbol(symbol: str) -> str:
    """Canonical -> IBKR ticker (class shares use a space: BRK-B -> 'BRK B')."""
    return symbol.replace("-", " ")


# Symbols whose bare SMART contract is ambiguous at IBKR and needs the
# primary exchange to disambiguate (error 200 otherwise).
_PRIMARY_EXCHANGE: dict[str, str] = {
    "BK": "NYSE",
    "BRK-B": "NYSE",
}


class IBKRBarSource:
    """Daily-close provider over a live ib_insync session.

    Requests are paced (default 0.6 s apart) to stay under IBKR's
    historical-data pacing limits; ~100 SP100 symbols complete in about a
    minute. Symbols with no data are simply absent from the result columns.
    """

    def __init__(self, ib, pacing_s: float = 0.6) -> None:
        self.ib = ib
        self.pacing_s = pacing_s

    async def daily_closes(self, symbols: list[str], duration: str) -> pd.DataFrame:
        from ib_insync import Stock

        series: dict[str, pd.Series] = {}
        for sym in symbols:
            contract = Stock(
                _ibkr_symbol(sym),
                "SMART",
                "USD",
                primaryExchange=_PRIMARY_EXCHANGE.get(sym, ""),
            )
            try:
                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                )
            except Exception as exc:  # pacing / contract errors: log and move on
                print(f"WARN: historical data failed for {sym}: {exc}")
                bars = []
            if bars:
                series[sym] = pd.Series(
                    {pd.Timestamp(b.date): float(b.close) for b in bars}
                )
            await asyncio.sleep(self.pacing_s)
        frame = pd.DataFrame(series).sort_index()
        if frame.empty:
            return frame
        # Drop ragged edge rows: IBKR duration windows start one bar earlier
        # for some symbols, leaving a leading row where almost every column
        # is NaN. Any row missing more than half the universe is calendar
        # noise, not a trading session worth keeping.
        return frame.dropna(thresh=max(1, frame.shape[1] // 2))


class MappedBroker:
    """Order seam that translates canonical symbols to IBKR tickers."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def place_order(self, order_data: dict) -> dict:
        data = dict(order_data)
        data["symbol"] = _ibkr_symbol(data["symbol"])
        return await self._adapter.place_order(data)

    async def get_order_status(self, order_id: str) -> dict:
        return await self._adapter.get_order_status(order_id)


def _build_runner_parts(args: argparse.Namespace):
    """Universe, sectors, strategy, store, config -- everything broker-free."""
    from core_trading.data.reference import build_starter_reference
    from core_trading.data.universe import SP100
    from core_trading.strategies.pairs_trading import (
        PairsTradingConfig,
        PairsTradingStrategy,
    )

    universe = list(SP100.current_symbols())
    ref = build_starter_reference()
    sectors = {s: sec for s in universe if (sec := ref.sector_of(s))}

    # Pilot configuration decided 2026-06-05:
    # * distance selection (Gatev) -- EG cointegration with multiple-testing
    #   correction yields 0-2 economically spurious pairs on SP100/252d;
    # * same-sector pairs only, at most 3 pairs per sector, each symbol in
    #   at most one pair, hedge beta in [1/3, 3] -- so the book is a set of
    #   genuinely distinct, leg-balanced, sector-neutral spreads;
    # * the constructor's relative sector-cap scaling is effectively off
    #   (0.95): on a sparse book it collapses the breaching sector to the
    #   scale of the smallest sleeve; concentration control happens at
    #   selection instead.
    # Walk-forward 2025-06..2026-06 (IBKR 2Y daily, frictionless marks):
    # Sharpe -0.03 +/- 0.07, max DD 1.7%, mean gross 18%, 0 incidents --
    # operationally clean, NO demonstrated edge. The 90-day clock is HELD
    # pending a research pass on longer history (operator decision
    # 2026-06-05); do not register the scheduler until that pass pins a
    # positive-edge config and updates --backtest-sharpe.
    from core_trading.portfolio.pairs_portfolio import PortfolioConfig

    strategy_config = PairsTradingConfig(
        selection_method="distance",
        max_pairs_per_sector=3,
        max_abs_hedge_beta=3.0,
        unique_symbols=True,
        portfolio=PortfolioConfig(sector_cap=0.95),
    )
    strategy = PairsTradingStrategy(
        strategy_config, sectors=sectors, require_same_sector=True
    )
    config = RunnerConfig(
        equity_base=args.equity,
        backtest_sharpe=args.backtest_sharpe,
    )
    store = LedgerStore(LEDGER_ROOT)
    return universe, sectors, strategy, config, store


def _print_result(result: DayResult) -> None:
    print(f"date:           {result.date}")
    print(f"status:         {result.status}" + (" (dry run)" if result.dry_run else ""))
    if result.reason:
        print(f"reason:         {result.reason}")
    print(f"equity:         {result.equity:,.2f}")
    print(f"daily return:   {result.daily_return:+.6f}")
    print(f"gross leverage: {result.gross_leverage:.4f}")
    print(
        f"pairs:          {result.n_pairs_selected} selected, "
        f"{result.n_active_pairs} active "
        f"(gross budget {result.gross_budget:.4f})"
    )
    print(f"orders:         {len(result.orders)}")
    for o in result.orders:
        print(f"  {o['side']:<4} {o['quantity']:>5} {o['symbol']}")
    print(f"fills:          {len(result.fills)}")
    if result.violations:
        print("violations:")
        for v in result.violations:
            print(f"  {v}")
    if result.rounding:
        r = result.rounding
        print(
            "rounding:       target gross "
            f"{r.get('target_gross_notional', 0):,.0f} -> achieved "
            f"{r.get('achieved_gross_notional', 0):,.0f} "
            f"(tracking error {r.get('tracking_error_frac_of_gross', 0):.1%} of gross)"
        )
        if r.get("dropped_legs"):
            print(f"  dropped legs (rounded to 0 shares): {', '.join(r['dropped_legs'])}")
    promo = result.promotion
    if promo:
        verdict = "ELIGIBLE" if promo.get("eligible") else "NOT YET"
        print(
            f"promotion:      {verdict} -- {promo.get('n_days', 0)} active days, "
            f"paper Sharpe {promo.get('paper_sharpe', 0.0)}, "
            f"{promo.get('n_incidents', 0)} incident(s)"
        )
        for reason in promo.get("reasons", []):
            print(f"  {reason}")


def _cmd_status(args: argparse.Namespace) -> int:
    _universe, _sectors, strategy, config, store = _build_runner_parts(args)
    state = store.load_state()
    records = store.ledger_records()
    traded = store.traded_records()
    print(f"ledger:         {store.ledger_path}")
    print(f"records:        {len(records)} total, {len(traded)} traded days")
    print(f"started:        {state.started or '(not started)'}")
    print(f"anchor:         {state.formation_anchor or '(not pinned)'}")
    print(f"halted:         {state.halted}" + (f" ({state.halt_reason})" if state.halted else ""))
    print(f"positions:      {len(state.positions)} symbols, cash {state.cash:,.2f}")
    for sym, qty in sorted(state.positions.items()):
        print(f"  {sym:<6} {qty:+d}")
    if state.incidents:
        print(f"open incidents: {len(state.incidents)}")
        for inc in state.incidents:
            print(f"  {inc}")
    runner = PairsLiveRunner(
        strategy, broker=None, bars=None, store=store, universe=[], config=config
    )
    promo = runner.evaluate_promotion(state)
    verdict = "ELIGIBLE" if promo.eligible else "NOT YET"
    print(
        f"promotion:      {verdict} -- {promo.n_days}/{config.min_paper_days} active days, "
        f"paper Sharpe {promo.paper_sharpe:.3f} (SE {promo.sharpe_standard_error:.3f})"
    )
    for reason in promo.reasons:
        print(f"  {reason}")
    return 0


def _cmd_reset_halt(_args: argparse.Namespace) -> int:
    store = LedgerStore(LEDGER_ROOT)
    state = store.load_state()
    if not state.halted:
        print("OK: not halted; nothing to reset")
        return 0
    print(f"clearing halt: {state.halt_reason}")
    state.halted = False
    state.halt_reason = None
    store.save_state(state)
    print("OK: halt cleared (incidents remain open; use --resolve-incidents after review)")
    return 0


def _cmd_resolve_incidents(_args: argparse.Namespace) -> int:
    store = LedgerStore(LEDGER_ROOT)
    state = store.load_state()
    if not state.incidents:
        print("OK: no open incidents")
        return 0
    for inc in state.incidents:
        print(f"resolving: {inc}")
    state.resolved_incidents.extend(state.incidents)
    state.incidents = []
    store.save_state(state)
    print(f"OK: {len(state.resolved_incidents)} incident(s) archived as resolved")
    return 0


async def _cmd_run(args: argparse.Namespace) -> int:
    now_et = _dt.datetime.now(US_EASTERN)
    today = _dt.date.fromisoformat(args.date) if args.date else now_et.date()
    if not args.date:
        if today.weekday() >= 5:
            print(f"OK: {today.isoformat()} is a weekend (US/Eastern); nothing to do")
            return 0
        # Market orders placed outside regular hours queue silently at IBKR
        # and fill at the NEXT open -- diverging from the ledger's close-price
        # marks. This matters for Task Scheduler catch-up runs: a machine that
        # was off at 20:30 UK may fire the job late in the evening.
        t = now_et.time()
        if not (_dt.time(9, 40) <= t <= _dt.time(15, 55)):
            print(
                f"SKIP: {now_et.isoformat(timespec='minutes')} is outside regular "
                "trading hours (09:40-15:55 ET); market orders would queue for "
                "the next open"
            )
            if not args.dry_run:
                LedgerStore(LEDGER_ROOT).append_ledger(
                    DayResult(
                        date=today.isoformat(),
                        status="SKIPPED",
                        reason="outside regular trading hours at run time",
                    ).to_record()
                )
            return 0

    universe, sectors, strategy, config, store = _build_runner_parts(args)

    paper_account = _load_paper_account_from_env_file()
    os.environ["IBKR_ACCOUNT_ID"] = paper_account
    if not paper_account.startswith("DU"):
        print("ERR: account does not look like a paper account (no DU prefix); aborting")
        return 1

    # The adapter's per-order guards default to single-name-pilot values
    # (1k USD/order, 10 trades/day, 5 positions) that a 10-pair book breaks
    # by construction. Raise them to pairs-book values unless the operator
    # has set explicit overrides in the environment.
    os.environ.setdefault("IBKR_PAPER_MAX_POSITION_SIZE", str(int(config.equity_base)))
    os.environ.setdefault("IBKR_PAPER_MAX_DAILY_TRADES", "100")
    os.environ.setdefault("IBKR_MAX_CONCURRENT_POSITIONS", "60")

    from core_trading.adapters.ibkr_adapter import IBKRAdapter

    adapter = IBKRAdapter(
        host="127.0.0.1",
        port=7497,
        client_id=CLIENT_ID,
        account_id=paper_account,
        paper_trading=True,
    )
    print(f"connecting to TWS paper (127.0.0.1:7497, account {_mask(paper_account)}) ...")
    ok = await adapter.connect()
    if not ok:
        reason = "TWS unreachable (not running, API disabled, or port mismatch)"
        print(f"SKIP: {reason}")
        if not args.dry_run:
            store.append_ledger(
                DayResult(
                    date=today.isoformat(), status="SKIPPED", reason=reason
                ).to_record()
            )
        return 0

    try:
        runner = PairsLiveRunner(
            strategy,
            broker=MappedBroker(adapter),
            bars=IBKRBarSource(adapter.ib),
            store=store,
            universe=universe,
            config=config,
            # Gate-level sector check off: a same-sector long/short book is
            # sector-NEUTRAL by construction (legs cancel within sector), so
            # a relative sector-GROSS cap just trips whenever active pairs
            # cluster. Concentration is controlled structurally at selection
            # (same sector, 3 pairs/sector, unique symbols, beta band).
            sectors=None,
        )
        result = await runner.run_once(today=today, dry_run=args.dry_run)
        _print_result(result)
        if result.status == "ERROR":
            return 1
        if result.status == "HALTED":
            print("WARN: kill switch engaged -- review incidents, then --reset-halt")
            return 3
        return 0
    except Exception:
        msg = traceback.format_exc()
        print("ERR: unhandled exception during run:\n" + msg)
        if not args.dry_run:
            store.append_ledger(
                DayResult(
                    date=today.isoformat(),
                    status="ERROR",
                    reason="unhandled exception: " + msg.strip().splitlines()[-1],
                ).to_record()
            )
        return 1
    finally:
        await adapter.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="compute and print orders; place nothing, persist nothing")
    parser.add_argument("--status", action="store_true", help="print ledger + promotion summary and exit")
    parser.add_argument("--reset-halt", action="store_true", help="clear the kill switch after operator review")
    parser.add_argument("--resolve-incidents", action="store_true", help="archive open incidents as operator-resolved")
    parser.add_argument("--date", default=None, help="override run date (YYYY-MM-DD, testing only)")
    parser.add_argument("--equity", type=float, default=25_000.0, help="strategy equity base (default 25000)")
    parser.add_argument(
        "--backtest-sharpe",
        type=float,
        default=0.0,
        help="validated backtest Sharpe for the promotion gate. 0.0 is the "
        "honest 2025-06..2026-06 walk-forward estimate (-0.03 +/- 0.07); "
        "re-pin from the research pass before relying on the gate",
    )
    args = parser.parse_args(argv)

    if args.status:
        return _cmd_status(args)
    if args.reset_halt:
        return _cmd_reset_halt(args)
    if args.resolve_incidents:
        return _cmd_resolve_incidents(args)
    return asyncio.run(_cmd_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
