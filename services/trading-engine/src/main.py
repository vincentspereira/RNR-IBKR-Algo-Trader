"""Trading Engine bootstrap.

Wires:
  IBKRAdapter (broker)  <->  ExecutionEngine  <->  EventBus

Run from the project root:
    python services/trading-engine/src/main.py

Required env vars (see .env / .env.example):
    IBKR_HOST                  - default 127.0.0.1
    IBKR_PORT                  - 7497 (TWS paper), 7496 (TWS live)
    IBKR_CLIENT_ID             - default 1; must be unique per TWS connection
    IBKR_ACCOUNT_ID            - required, no fallback
    IBKR_TRADING_MODE          - 'paper' (default) or 'live'

Graceful shutdown on SIGINT / SIGTERM.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent              # .../services/trading-engine/src
_SERVICE_DIR = _THIS_DIR.parent                          # .../services/trading-engine
_REPO_ROOT = _THIS_DIR.parents[2]                        # repo root
for _p in (_REPO_ROOT, _SERVICE_DIR):
    p_str = str(_p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

from core_trading.adapters.ibkr_adapter import IBKRAdapter  # noqa: E402

# Trading-engine internals use relative imports (`from ..core...`), so they
# must be imported as `src.<...>` so the relative parent resolves correctly.
from src.core.event_system import get_event_bus  # noqa: E402
from src.engines.execution_engine import ExecutionEngine  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("TradingEngine")


def _read_env() -> dict:
    """Read and validate IBKR-related env vars."""
    trading_mode = os.getenv("IBKR_TRADING_MODE", "paper").lower()
    if trading_mode not in ("paper", "live"):
        raise ValueError(
            f"IBKR_TRADING_MODE must be 'paper' or 'live', got: {trading_mode!r}"
        )

    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497" if trading_mode == "paper" else "7496"))
    client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
    account_id = os.getenv("IBKR_ACCOUNT_ID")
    if not account_id:
        raise ValueError(
            "IBKR_ACCOUNT_ID is required. Set it in .env or your shell environment."
        )

    # Mode/port consistency guard: paper mode should not target 7496 (live port)
    # and live mode should not target 7497 (paper port). Catches a class of
    # foot-gun where someone flips IBKR_TRADING_MODE but forgets the port.
    if trading_mode == "paper" and port == 7496:
        raise ValueError(
            "IBKR_TRADING_MODE=paper but IBKR_PORT=7496 (TWS live socket). Refusing to start."
        )
    if trading_mode == "live" and port == 7497:
        raise ValueError(
            "IBKR_TRADING_MODE=live but IBKR_PORT=7497 (TWS paper socket). Refusing to start."
        )
    if trading_mode == "live" and os.getenv("FEATURE_LIVE_TRADING_ENABLED", "false").lower() != "true":
        raise ValueError(
            "IBKR_TRADING_MODE=live but FEATURE_LIVE_TRADING_ENABLED is not 'true'. "
            "Live trading is gated; set the feature flag explicitly."
        )

    return {
        "host": host,
        "port": port,
        "client_id": client_id,
        "account_id": account_id,
        "paper_trading": trading_mode == "paper",
    }


async def _run(stop_event: asyncio.Event) -> None:
    cfg = _read_env()
    logger.info(
        "Starting trading engine: host=%s port=%d client_id=%d mode=%s",
        cfg["host"], cfg["port"], cfg["client_id"],
        "paper" if cfg["paper_trading"] else "LIVE",
    )

    event_bus = get_event_bus()

    ibkr = IBKRAdapter(
        host=cfg["host"],
        port=cfg["port"],
        client_id=cfg["client_id"],
        account_id=cfg["account_id"],
        paper_trading=cfg["paper_trading"],
    )

    connected = await ibkr.connect()
    if not connected:
        raise RuntimeError(
            f"IBKR connect() returned False. Verify TWS is running on "
            f"{cfg['host']}:{cfg['port']} with API enabled and 127.0.0.1 trusted."
        )

    engine = ExecutionEngine(broker_adapter=ibkr, event_bus=event_bus)
    if not await engine.initialize():
        raise RuntimeError("ExecutionEngine.initialize() returned False")

    ibkr.on_fill(engine.handle_fill_by_broker_id)
    ibkr.on_order_status(engine.handle_status_by_broker_id)
    logger.info("Fill and order-status callbacks wired to ExecutionEngine")

    await ibkr.start_heartbeat()
    logger.info("Trading engine running. Press Ctrl+C to shut down.")

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down...")
        try:
            await engine.shutdown()
        except Exception as e:
            logger.error("Error shutting down ExecutionEngine: %s", e)
        try:
            await ibkr.disconnect()
        except Exception as e:
            logger.error("Error disconnecting IBKR: %s", e)
        logger.info("Shutdown complete.")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    def _stop(*_args):
        if not stop_event.is_set():
            logger.info("Stop signal received")
            loop.call_soon_threadsafe(stop_event.set)

    # On Windows, loop.add_signal_handler is not supported; fall back to signal.signal.
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGINT, _stop)
            signal.signal(signal.SIGTERM, _stop)
        except (ValueError, AttributeError):
            pass
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except NotImplementedError:
                signal.signal(sig, _stop)


def main() -> int:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()
    _install_signal_handlers(loop, stop_event)
    try:
        loop.run_until_complete(_run(stop_event))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.exception("Trading engine crashed: %s", e)
        return 1
    finally:
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
