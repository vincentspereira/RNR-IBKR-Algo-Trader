"""Base event classes for the trading system."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BaseEvent(BaseModel, ABC):
    """Abstract base class for all events in the trading system."""
    
    event_id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    event_type: str = Field(..., description="Type of event")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    version: str = Field(default="1.0.0", description="Event schema version")
    correlation_id: Optional[UUID] = Field(None, description="Correlation ID for tracking related events")
    causation_id: Optional[UUID] = Field(None, description="ID of the event that caused this event")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }
        use_enum_values = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        """Create event from dictionary."""
        return cls(**data)


class MarketDataEvent(BaseEvent):
    """Base class for market data events."""
    
    symbol: str = Field(..., description="Trading symbol")
    exchange: str = Field(..., description="Exchange name")
    event_type: str = "market_data"


class TradingEvent(BaseEvent):
    """Base class for trading events."""
    
    order_id: UUID = Field(..., description="Order ID")
    user_id: UUID = Field(..., description="User ID")
    strategy_id: Optional[UUID] = Field(None, description="Strategy ID")
    event_type: str = "trading"


class RiskEvent(BaseEvent):
    """Base class for risk events."""
    
    severity: str = Field(..., description="Severity level: LOW, MEDIUM, HIGH, CRITICAL")
    alert_type: str = Field(..., description="Type of risk alert")
    event_type: str = "risk"


class FundamentalEvent(BaseEvent):
    """Base class for fundamental analysis events (NEW - Phase 15.5)."""
    
    symbol: str = Field(..., description="Trading symbol")
    period_end: datetime = Field(..., description="Period end date")
    event_type: str = "fundamental"


class AIEvent(BaseEvent):
    """Base class for AI/ML events."""
    
    agent_id: str = Field(..., description="Agent identifier")
    query_id: UUID = Field(..., description="Query identifier")
    event_type: str = "ai"


class SystemEvent(BaseEvent):
    """Base class for system events."""
    
    service_name: str = Field(..., description="Service name")
    event_category: str = Field(..., description="Event category: HEALTH, ERROR, CONFIG, AUDIT")
    event_type: str = "system"


# Specific event implementations

class OrderCreatedEvent(TradingEvent):
    """Event emitted when an order is created."""
    
    symbol: str
    order_type: str
    side: str
    quantity: float
    price: Optional[float] = None
    event_type: str = "trading.order.created"


class OrderFilledEvent(TradingEvent):
    """Event emitted when an order is filled."""
    
    symbol: str
    filled_quantity: float
    fill_price: float
    commission: float
    event_type: str = "trading.order.filled"


class PositionOpenedEvent(TradingEvent):
    """Event emitted when a position is opened."""
    
    symbol: str
    quantity: float
    entry_price: float
    event_type: str = "trading.position.opened"


class SignalGeneratedEvent(TradingEvent):
    """Event emitted when a trading signal is generated."""
    
    symbol: str
    signal_type: str  # BUY, SELL, HOLD
    strength: float
    reasoning: str
    indicators: Dict[str, Any]
    event_type: str = "trading.signal.generated"


class FundamentalDataUpdatedEvent(FundamentalEvent):
    """Event emitted when fundamental data is updated."""
    
    data_type: str  # STATEMENT, RATIO, SCORE, VALUATION
    data: Dict[str, Any]
    event_type: str = "fundamental.data.updated"


class RiskLimitBreachedEvent(RiskEvent):
    """Event emitted when a risk limit is breached."""
    
    limit_type: str
    current_value: float
    limit_value: float
    event_type: str = "risk.limit.breached"
