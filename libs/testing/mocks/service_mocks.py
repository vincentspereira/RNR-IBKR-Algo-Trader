"""Mock objects for external services."""
from typing import Optional, Dict, Any
from unittest.mock import Mock, AsyncMock


class MockKafkaProducer:
    """Mock Kafka producer for testing."""
    
    def __init__(self):
        self.produced_events = []
    
    def produce_event(self, topic: str, event: Any, key: Optional[str] = None, headers: Optional[Dict] = None):
        """Mock produce event."""
        self.produced_events.append({
            'topic': topic,
            'event': event,
            'key': key,
            'headers': headers
        })
    
    def flush(self, timeout: float = 10.0):
        """Mock flush."""
        pass
    
    def close(self):
        """Mock close."""
        pass


class MockRedisClient:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.data = {}
    
    async def get(self, key: str) -> Optional[str]:
        """Mock get."""
        return self.data.get(key)
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        """Mock set."""
        self.data[key] = value
    
    async def delete(self, key: str):
        """Mock delete."""
        self.data.pop(key, None)
    
    async def exists(self, key: str) -> bool:
        """Mock exists."""
        return key in self.data


class MockExternalAPI:
    """Mock external API for testing."""
    
    def __init__(self):
        self.call_count = 0
        self.responses = []
    
    async def fetch_data(self, symbol: str) -> Dict[str, Any]:
        """Mock API call."""
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return {'symbol': symbol, 'price': 100.0}
    
    def set_response(self, response: Dict[str, Any]):
        """Set mock response."""
        self.responses.append(response)
