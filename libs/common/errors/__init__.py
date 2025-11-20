"""Errors module."""
from .exceptions import (
    AuthenticationException,
    BacktestException,
    ConfigurationException,
    ConnectionException,
    ConsumerException,
    DataNotFoundException,
    DatabaseException,
    ExternalAPIException,
    FundamentalAnalysisException,
    InvalidTokenException,
    KafkaException,
    OrderException,
    PermissionDeniedException,
    PositionException,
    ProducerException,
    QueryException,
    RateLimitException,
    RiskException,
    StrategyException,
    TradingException,
    TradingSystemException,
    ValidationException,
)
from .handlers import retry_async_on_exception, retry_on_exception

__all__ = [
    # Base
    "TradingSystemException",
    # Database
    "DatabaseException",
    "ConnectionException",
    "QueryException",
    # Kafka
    "KafkaException",
    "ProducerException",
    "ConsumerException",
    # Auth
    "AuthenticationException",
    "InvalidTokenException",
    "PermissionDeniedException",
    # Validation
    "ValidationException",
    "ConfigurationException",
    "RateLimitException",
    # Trading
    "TradingException",
    "OrderException",
    "PositionException",
    "RiskException",
    # Strategy
    "StrategyException",
    "BacktestException",
    # Fundamental
    "FundamentalAnalysisException",
    # Data
    "DataNotFoundException",
    "ExternalAPIException",
    # Handlers
    "retry_on_exception",
    "retry_async_on_exception",
]
