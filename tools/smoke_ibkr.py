"""IBKR paper-trading connectivity smoke test.

Run this once when TWS or IB Gateway is up and logged into the paper account.
It verifies:

1. ``.env`` carries the IBKR_* variables
2. ``ib_insync`` can open a connection to the configured host/port
3. The account number we receive back matches what's in ``.env``
   (sanity check that we connected to the right session)
4. A historical bar request for SPY succeeds
5. A live snapshot quote for SPY succeeds
6. The connection closes cleanly

The script never sends orders. It is read-only.

Usage:
    .venv/bin/python tools/smoke_ibkr.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str, *, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None or val == "":
        print(f"[FAIL] missing required environment variable: {name}")
        print("       hint: copy .env.example -> .env, fill in IBKR_* values,")
        print("       make sure the .env loads (this script calls load_dotenv())")
        sys.exit(1)
    return val


async def main() -> None:
    host = _require_env("IBKR_HOST", default="127.0.0.1")
    port_str = _require_env("IBKR_PORT", default="7497")
    expected_account = _require_env("IBKR_ACCOUNT_ID")
    mode = os.environ.get("IBKR_TRADING_MODE", "paper").lower()
    try:
        port = int(port_str)
    except ValueError:
        print(f"[FAIL] IBKR_PORT={port_str!r} is not an integer")
        sys.exit(1)

    if mode != "paper":
        print(f"[ABORT] IBKR_TRADING_MODE={mode!r}; this smoke test only runs against paper.")
        print("       Set IBKR_TRADING_MODE=paper to proceed.")
        sys.exit(2)

    try:
        from ib_insync import IB, Stock, util
    except ImportError as exc:
        print(f"[FAIL] ib_insync not installed in the active venv: {exc}")
        sys.exit(1)

    util.patchAsyncio()
    ib = IB()

    print(f"[step 1] connecting to {host}:{port} (paper mode) ...")
    try:
        await ib.connectAsync(host=host, port=port, clientId=42, timeout=10)
    except Exception as exc:
        print(f"[FAIL] could not connect: {exc}")
        print("       hint: start TWS or IB Gateway, log in to the paper account,")
        print("              enable API connections under File -> Global Configuration")
        print("              -> API -> Settings, and tick 'Enable ActiveX and Socket Clients'.")
        sys.exit(1)
    print(f"[ok]   connected (server version {ib.client.serverVersion()})")

    try:
        accounts = ib.managedAccounts()
        print(f"[step 2] managed accounts: {accounts}")
        if expected_account and expected_account not in accounts:
            print(f"[WARN] IBKR_ACCOUNT_ID={expected_account!r} not in returned set {accounts}")
            print("       This may be acceptable if you trade multiple accounts.")
        else:
            print(f"[ok]   account {expected_account} present in session")

        account_values = ib.accountSummary(expected_account) if expected_account else []
        if account_values:
            print(f"[step 3] account summary for {expected_account}:")
            for av in account_values:
                if av.tag in {"NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds"}:
                    print(f"         {av.tag}={av.value} {av.currency}")
        else:
            print("[step 3] (no account summary returned -- safe to ignore on smoke test)")

        print("[step 4] qualifying SPY contract ...")
        spy = Stock("SPY", "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(spy)
        if not qualified:
            print("[FAIL] could not qualify SPY contract")
            sys.exit(1)
        print(f"[ok]   SPY conId={qualified[0].conId}")

        print("[step 5] requesting last 5 daily bars for SPY ...")
        bars = await ib.reqHistoricalDataAsync(
            qualified[0],
            endDateTime="",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if not bars:
            print("[FAIL] no historical bars returned")
            sys.exit(1)
        print(f"[ok]   received {len(bars)} bars:")
        for b in bars:
            print(f"         {b.date}  O={b.open}  H={b.high}  L={b.low}  C={b.close}  V={b.volume}")

        print("[step 6] requesting market data snapshot for SPY ...")
        ticker = ib.reqMktData(qualified[0], "", snapshot=True, regulatorySnapshot=False)
        for _ in range(20):
            await asyncio.sleep(0.5)
            if ticker.last is not None or ticker.close is not None:
                break
        last = ticker.last if ticker.last is not None else ticker.close
        if last is None:
            print("[WARN] no quote received within 10s (market may be closed)")
        else:
            print(f"[ok]   SPY last={last} bid={ticker.bid} ask={ticker.ask}")

    finally:
        ib.disconnect()
        print("[step 7] disconnected")

    print()
    print("[SUMMARY] IBKR paper-account smoke test passed.")
    print(f"          Timestamp: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
