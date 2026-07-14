"""Daily TA-quant paper-trading run -- the 90-day clock for the rsi2 book.

The cron entrypoint for the validated three-slot paper
book (decision record: ``docs/GO_NO_GO_RSI2_TREND_SURVIVORSHIP_2026-06-10.md``):

| slot                     | universe | net Sharpe (validated) | gross cap |
|--------------------------|----------|------------------------|-----------|
| rsi2t15_trend200         | SP100    | 0.82 (PIT)             | 1.0       |
| rsi2t10_trend200_volt10  | SP100    | 0.77 (PIT)             | 2.0 (vol-targeted) |
| rsi2t10_calm75           | ETF_CORE | 0.88 (ETF sweep)       | 1.0       |

Each slot runs as its own :class:`PairsLiveRunner` book with its own ledger
under ``logs/taquant_paper/<slot>/``, its own kill switch, and its own
promotion gate pinned to the slot's validated backtest Sharpe -- so the
90-day evaluation can promote or retire slots independently. All three
share one TWS session per run (client id 48).

Universe note: the validated stock rule is "PIT S&P 500 members, top-100 by
trailing dollar volume". Going FORWARD the current S&P 100 is that rule's
live equivalent (current membership is point-in-time correct at trade
time); refresh ``core_trading.data.universe.SP100`` when S&P reconstitutes.

Ledger field note: ``n_active_pairs`` is legacy runner naming -- for these
long-only books it is active-position-count // 2. Use ``gross_leverage``
and the order list as the real diagnostics.

Run manually:
    .venv/bin/python tools/taquant_paper_run.py            # live paper run
    .venv/bin/python tools/taquant_paper_run.py --dry-run  # no orders, no ledger
    .venv/bin/python tools/taquant_paper_run.py --status   # ledgers + promotion
    .venv/bin/python tools/taquant_paper_run.py --slot rsi2t10_calm75 --dry-run
    .venv/bin/python tools/taquant_paper_run.py --reset-halt --slot <slot>
    .venv/bin/python tools/taquant_paper_run.py --resolve-incidents --slot <slot>
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from pairs_paper_run import (  # noqa: E402
    IBKRBarSource,
    MappedBroker,
    _load_paper_account_from_env_file,
    _mask,
    _print_result,
)

from core_trading.ops.pairs_live_runner import (  # noqa: E402
    US_EASTERN,
    DayResult,
    LedgerStore,
    PairsLiveRunner,
    RunnerConfig,
)
from core_trading.ops.taquant_live_adapter import TAQuantRunnerStrategy  # noqa: E402
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits  # noqa: E402

LEDGER_ROOT = REPO_ROOT / "logs" / "taquant_paper"
CLIENT_ID = 48  # distinct from smoke (43), engine (1), pairs pilot (47)


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """One paper-book slot: a validated config on a universe."""

    name: str
    universe_name: str  # key into core_trading.data.universe.BUILTIN_UNIVERSES
    backtest_sharpe: float  # validated figure for the promotion gate
    gross_cap_backstop: float  # risk-gate gross cap (mis-sizing backstop)


# The paper book from the 2026-06-10 GO memo. per-symbol cap is 1.0 by
# design: the equal-weight rule puts 100% of slot equity on a lone dipper --
# that IS the validated behaviour, so the risk gate only backstops sizing
# bugs (gross), fat daily losses, and trailing drawdown.
#
# ETF slot PARKED 2026-06-10: the memo's third slot (rsi2t10_calm75 on
# ETF_CORE) is NOT tradeable on this account -- IBKR rejects US-domiciled
# ETFs for UK retail clients under PRIIPs ("No Trading Permission ... no
# KID", error 201; confirmed empirically by live paper rejections on DBC,
# EEM). Restoring it requires a UCITS (LSE-listed) equivalent universe and
# a fresh validation sweep on those tickers. Single stocks are unaffected.
SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec("rsi2t15_trend200", "SP100", 0.82, 1.10),
    SlotSpec("rsi2t10_trend200_volt10", "SP100", 0.77, 2.05),
)


def _slot_risk_manager(spec: SlotSpec) -> PairsRiskManager:
    return PairsRiskManager(
        RiskLimits(
            per_pair_cap=1.0,
            sector_cap=0.99,  # unused (sectors=None) but must be valid
            gross_leverage_cap=spec.gross_cap_backstop,
            daily_drawdown_limit=0.10,
            monthly_drawdown_limit=0.25,
        )
    )


def _build_slot_parts(spec: SlotSpec, args: argparse.Namespace):
    """Strategy, store, config, universe for one slot -- broker-free."""
    from core_trading.data.universe import BUILTIN_UNIVERSES
    from core_trading.strategies.ta_quant import build_ta_quant_grid

    grid = dict(build_ta_quant_grid())
    strategy = TAQuantRunnerStrategy(grid[spec.name], formation_window=252)
    universe = list(BUILTIN_UNIVERSES[spec.universe_name].current_symbols())
    config = RunnerConfig(
        equity_base=args.equity,
        backtest_sharpe=spec.backtest_sharpe,
    )
    store = LedgerStore(LEDGER_ROOT / spec.name)
    return strategy, universe, config, store


def _selected_slots(args: argparse.Namespace) -> tuple[SlotSpec, ...]:
    if not args.slot:
        return SLOTS
    by_name = {s.name: s for s in SLOTS}
    if args.slot not in by_name:
        raise SystemExit(f"ERR: unknown slot {args.slot!r}; known: {sorted(by_name)}")
    return (by_name[args.slot],)


def _cmd_status(args: argparse.Namespace) -> int:
    for spec in _selected_slots(args):
        strategy, _universe, config, store = _build_slot_parts(spec, args)
        state = store.load_state()
        records = store.ledger_records()
        traded = store.traded_records()
        print(f"=== slot: {spec.name} ({spec.universe_name}) ===")
        print(f"ledger:         {store.ledger_path}")
        print(f"records:        {len(records)} total, {len(traded)} traded days")
        print(f"started:        {state.started or '(not started)'}")
        print(f"halted:         {state.halted}" + (f" ({state.halt_reason})" if state.halted else ""))
        print(f"positions:      {len(state.positions)} symbols, cash {state.cash:,.2f}")
        if state.incidents:
            print(f"open incidents: {len(state.incidents)}")
            for inc in state.incidents:
                print(f"  {inc}")
        runner = PairsLiveRunner(
            strategy,
            broker=None,
            bars=None,
            store=store,
            universe=[],
            risk_manager=_slot_risk_manager(spec),
            config=config,
        )
        promo = runner.evaluate_promotion(state)
        verdict = "ELIGIBLE" if promo.eligible else "NOT YET"
        print(
            f"promotion:      {verdict} -- {promo.n_days}/{config.min_paper_days} "
            f"active days, paper Sharpe {promo.paper_sharpe:.3f} "
            f"(target {spec.backtest_sharpe:.2f} - 1 SE)"
        )
        for reason in promo.reasons:
            print(f"  {reason}")
        print()
    return 0


def _cmd_reset_halt(args: argparse.Namespace) -> int:
    if not args.slot:
        raise SystemExit("ERR: --reset-halt requires --slot <name> (per-book kill switch)")
    spec = _selected_slots(args)[0]
    store = LedgerStore(LEDGER_ROOT / spec.name)
    state = store.load_state()
    if not state.halted:
        print(f"OK: slot {spec.name} not halted; nothing to reset")
        return 0
    print(f"clearing halt on {spec.name}: {state.halt_reason}")
    state.halted = False
    state.halt_reason = None
    store.save_state(state)
    print("OK: halt cleared (incidents remain open; use --resolve-incidents after review)")
    return 0


def _cmd_resolve_incidents(args: argparse.Namespace) -> int:
    if not args.slot:
        raise SystemExit("ERR: --resolve-incidents requires --slot <name>")
    spec = _selected_slots(args)[0]
    store = LedgerStore(LEDGER_ROOT / spec.name)
    state = store.load_state()
    if not state.incidents:
        print(f"OK: slot {spec.name} has no open incidents")
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
        t = now_et.time()
        if not (_dt.time(9, 40) <= t <= _dt.time(15, 55)):
            print(
                f"SKIP: {now_et.isoformat(timespec='minutes')} is outside regular "
                "trading hours (09:40-15:55 ET); market orders would queue for "
                "the next open"
            )
            if not args.dry_run:
                for spec in _selected_slots(args):
                    LedgerStore(LEDGER_ROOT / spec.name).append_ledger(
                        DayResult(
                            date=today.isoformat(),
                            status="SKIPPED",
                            reason="outside regular trading hours at run time",
                        ).to_record()
                    )
            return 0

    paper_account = _load_paper_account_from_env_file()
    os.environ["IBKR_ACCOUNT_ID"] = paper_account
    if not paper_account.startswith("DU"):
        print("ERR: account does not look like a paper account (no DU prefix); aborting")
        return 1

    # Adapter per-order guards: a lone-dipper day can put a slot's whole
    # equity (x2 with vol targeting) into one order; three slots share the
    # session's daily-trade budget.
    os.environ.setdefault("IBKR_PAPER_MAX_POSITION_SIZE", str(int(args.equity * 2.5)))
    os.environ.setdefault("IBKR_PAPER_MAX_DAILY_TRADES", "300")
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
    ok = await adapter.connect()
    if not ok:
        reason = "TWS unreachable (not running, API disabled, or port mismatch)"
        print(f"SKIP: {reason}")
        if not args.dry_run:
            for spec in _selected_slots(args):
                LedgerStore(LEDGER_ROOT / spec.name).append_ledger(
                    DayResult(
                        date=today.isoformat(), status="SKIPPED", reason=reason
                    ).to_record()
                )
        return 0

    exit_code = 0
    try:
        for spec in _selected_slots(args):
            print(f"\n=== slot: {spec.name} ({spec.universe_name}) ===")
            strategy, universe, config, store = _build_slot_parts(spec, args)
            try:
                runner = PairsLiveRunner(
                    strategy,
                    broker=MappedBroker(adapter),
                    bars=IBKRBarSource(adapter.ib),
                    store=store,
                    universe=universe,
                    risk_manager=_slot_risk_manager(spec),
                    config=config,
                    sectors=None,
                )
                result = await runner.run_once(today=today, dry_run=args.dry_run)
                _print_result(result)
                if result.status == "ERROR":
                    exit_code = max(exit_code, 1)
                elif result.status == "HALTED":
                    print(
                        f"WARN: kill switch engaged on {spec.name} -- review "
                        f"incidents, then --reset-halt --slot {spec.name}"
                    )
                    exit_code = max(exit_code, 3)
            except Exception:
                msg = traceback.format_exc()
                print(f"ERR: unhandled exception in slot {spec.name}:\n" + msg)
                if not args.dry_run:
                    store.append_ledger(
                        DayResult(
                            date=today.isoformat(),
                            status="ERROR",
                            reason="unhandled exception: "
                            + msg.strip().splitlines()[-1],
                        ).to_record()
                    )
                exit_code = max(exit_code, 1)
    finally:
        await adapter.disconnect()

    if not args.dry_run:
        # Refresh the static HTML report; a report failure must never be
        # allowed to mark a successfully traded day as failed.
        try:
            from paper_report import generate_report

            print(f"report refreshed: {generate_report()}")
        except Exception as exc:
            print(f"WARN: report generation failed: {type(exc).__name__}: {exc}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="compute and print orders; place nothing, persist nothing")
    parser.add_argument("--status", action="store_true", help="print per-slot ledger + promotion summary and exit")
    parser.add_argument("--reset-halt", action="store_true", help="clear one slot's kill switch (requires --slot)")
    parser.add_argument("--resolve-incidents", action="store_true", help="archive one slot's incidents (requires --slot)")
    parser.add_argument("--slot", default=None, help="restrict to one slot by name")
    parser.add_argument("--date", default=None, help="override run date (YYYY-MM-DD, testing only)")
    parser.add_argument(
        "--equity",
        type=float,
        default=25_000.0,
        help="equity base PER SLOT (default 25000; three slots = 75k paper total)",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=CLIENT_ID,
        help="TWS API client id (override when a stale session holds the default)",
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
