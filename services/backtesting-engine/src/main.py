"""Backtesting-engine service entrypoint (deployment wrapper).

This service is deployment glue, not a backtest implementation. The canonical
backtest engine -- vectorised + event-driven, with the cost/execution/Monte
Carlo/walk-forward stack -- lives in ``core_trading.backtest`` (master plan
Phase 3) and is driven directly by the research tooling and the strategy
runners. This process exists only to keep a long-running container alive so an
orchestrator can route backtest jobs to it; it imports the canonical engine and
idles until a job arrives.

The earlier VectorBT/Nautilus integration sketched here was superseded by the
in-house Phase 3 engine and removed (see master plan section 3).
"""
import asyncio
import logging

from core_trading.backtest.engine import BacktestEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BacktestingEngine")


async def main() -> None:
    logger.info("Starting Backtesting Engine service (delegates to %s)", BacktestEngine.__module__)
    logger.info("Backtesting Engine running. Waiting for jobs...")
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
