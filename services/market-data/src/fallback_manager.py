from typing import List, Dict, Any, Optional
from datetime import datetime
from .feed_handler import FeedHandler
import logging

logger = logging.getLogger(__name__)

class FallbackManager:
    """Manages a chain of FeedHandlers with fallback logic."""
    
    def __init__(self, handlers: List[FeedHandler]):
        self.handlers = handlers

    async def get_historical_data(self, symbol: str, start_date: datetime, end_date: datetime, interval: str = "1d") -> Any:
        errors = []
        for handler in self.handlers:
            try:
                return await handler.get_historical_data(symbol, start_date, end_date, interval)
            except Exception as e:
                logger.warning(f"Handler {handler.__class__.__name__} failed: {e}")
                errors.append(f"{handler.__class__.__name__}: {e}")
        
        raise Exception(f"All handlers failed: {errors}")

    async def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        errors = []
        for handler in self.handlers:
            try:
                return await handler.get_realtime_quote(symbol)
            except Exception as e:
                logger.warning(f"Handler {handler.__class__.__name__} failed: {e}")
                errors.append(f"{handler.__class__.__name__}: {e}")
        
        raise Exception(f"All handlers failed: {errors}")
