import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AIAssistant")

async def main():
    logger.info("Starting AI Assistant...")
    
    # TODO: Initialize LangGraph and Qdrant connection
    zai_api_key = os.getenv("ZAI_API_KEY")
    logger.info(f"Z.ai API Key present: {bool(zai_api_key)}")

    logger.info("AI Assistant Running. Waiting for tasks...")
    
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
