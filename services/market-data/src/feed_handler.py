from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

class FeedHandler(ABC):
    """Abstract base class for market data feed handlers."""
    
    @abstractmethod
    async def get_historical_data(self, symbol: str, start_date: datetime, end_date: datetime, interval: str = "1d") -> Any:
        """Fetch historical data."""
        pass

    @abstractmethod
    async def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch real-time quote."""
        pass
