import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BacktestingEngine")

async def main():
    logger.info("Starting Backtesting Engine...")
    
    # TODO: Initialize VectorBT and Nautilus
    
    logger.info("Backtesting Engine Running. Waiting for jobs...")
    
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
