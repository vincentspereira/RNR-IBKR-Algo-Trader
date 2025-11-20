import asyncio
import logging
import os
from .engines.execution_engine import ExecutionEngine
# from .engines.smart_money_engine import SmartMoneyEngine # Commented out in source
# from libs.core.event_bus import EventBus # Assuming this exists or will exist

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingEngine")

async def main():
    logger.info("Starting Trading Engine...")
    
    # Initialize Engines
    execution_engine = ExecutionEngine()
    # smart_money_engine = SmartMoneyEngine() # Initialize with config if needed
    
    logger.info("Engines initialized.")
    
    # TODO: Connect to Kafka
    # event_bus = EventBus()
    # await event_bus.connect()
    
    # TODO: Connect to IBKR
    # await execution_engine.connect_ibkr()

    logger.info("Trading Engine Running. Waiting for commands...")
    
    # Keep alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
