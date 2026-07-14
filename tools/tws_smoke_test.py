"""TWS paper-trading smoke test (PRODUCTION_PUNCH_LIST section 4 goal).

Loop: connect -> place 1-share AAPL paper BUY -> watch fill -> close
position with a 1-share SELL -> disconnect.

Safety rails:
* Refuses to run unless the managed account starts with "DU" (paper).
* Hard-coded to 1 share of AAPL, market orders only.
* Reads IBKR_ACCOUNT_ID_PAPER from .env and maps it to IBKR_ACCOUNT_ID
  for the adapter; account IDs are masked in all output.

Run:
    .venv/bin/python tools/tws_smoke_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _mask(acct: str) -> str:
    """Mask an account id for safe logging."""
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


async def main() -> int:
    paper_account = _load_paper_account_from_env_file()
    os.environ["IBKR_ACCOUNT_ID"] = paper_account

    from core_trading.adapters.ibkr_adapter import IBKRAdapter

    adapter = IBKRAdapter(host="127.0.0.1", port=7497, client_id=43,
                          account_id=paper_account, paper_trading=True)

    print("[1/6] Connecting to TWS on 127.0.0.1:7497 ...")
    ok = await adapter.connect()
    if not ok:
        print("ERR: connect() returned False -- check TWS API settings")
        return 1
    print("      Connected. Account:", _mask(paper_account))

    # Safety rail: paper accounts start with DU
    if not paper_account.startswith("DU"):
        print("ERR: account does not look like a paper account (no DU prefix); aborting")
        await adapter.disconnect()
        return 1

    print("[2/6] Account info ...")
    info = await adapter.get_account_info()
    masked = {k: v for k, v in info.items() if "account" not in str(k).lower()}
    print("      NetLiq/buying-power keys:",
          {k: masked[k] for k in list(masked)[:6]})

    print("[3/6] Placing 1-share AAPL MARKET BUY (paper) ...")
    buy = await adapter.place_order({
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 1,
        "order_type": "market",
    })
    print("      Order response:", {k: buy.get(k) for k in ("order_id", "status", "broker_order_id", "reason")})
    if buy.get("status") == "rejected":
        print("ERR: order rejected:", buy.get("reason"))
        await adapter.disconnect()
        return 1

    order_id = buy["order_id"]
    print("[4/6] Waiting for fill ...")
    status = None
    for _ in range(30):
        await asyncio.sleep(1)
        st = await adapter.get_order_status(order_id)
        status = st.get("status")
        if status in ("filled", "Filled"):
            print("      FILLED:", {k: st.get(k) for k in ("status", "filled_quantity", "avg_fill_price")})
            break
        print("      status:", status)
    else:
        print(f"WARN: not filled within 30s (status={status}); attempting cleanup")

    print("[5/6] Positions, then closing with 1-share MARKET SELL ...")
    positions = await adapter.get_positions()
    aapl = [p for p in positions if p.get("symbol") == "AAPL"]
    print("      AAPL position:", aapl)
    if aapl and float(aapl[0].get("quantity", 0)) > 0:
        sell = await adapter.place_order({
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 1,
            "order_type": "market",
        })
        print("      Close response:", {k: sell.get(k) for k in ("order_id", "status", "broker_order_id", "reason")})
        sell_id = sell.get("order_id")
        if sell_id:
            for _ in range(30):
                await asyncio.sleep(1)
                st = await adapter.get_order_status(sell_id)
                if st.get("status") in ("filled", "Filled"):
                    print("      CLOSED:", {k: st.get(k) for k in ("status", "filled_quantity", "avg_fill_price")})
                    break
                print("      status:", st.get("status"))
    else:
        print("      No long AAPL position found to close (buy may not have filled)")

    print("[6/6] Disconnecting ...")
    await adapter.disconnect()
    print("OK: smoke test complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
