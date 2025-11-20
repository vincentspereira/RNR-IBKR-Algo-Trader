import asyncio
import logging
from .providers.yahoo import YahooFinanceProvider
from .fallback_manager import FallbackManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MarketData")

async def main():
    logger.info("Starting Market Data Service...")
    
    # Initialize Providers
    yahoo = YahooFinanceProvider()
    fallback_manager = FallbackManager([yahoo])
    
    logger.info("Providers initialized.")
    
    # Test Fetch
    try:
        quote = await fallback_manager.get_realtime_quote("AAPL")
        logger.info(f"Test Quote: {quote}")
    except Exception as e:
        logger.error(f"Test failed: {e}")

    # Keep alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
