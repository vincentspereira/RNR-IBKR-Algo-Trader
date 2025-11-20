"""Custom exceptions for the trading system."""


class TradingSystemException(Exception):
    """Base exception for all trading system errors."""
    
    def __init__(self, message: str, details: dict = None):
        """
        Initialize exception.
        
        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DatabaseException(TradingSystemException):
    """Database-related errors."""
    pass


class ConnectionException(DatabaseException):
    """Database connection errors."""
    pass


class QueryException(DatabaseException):
    """Database query errors."""
    pass


class KafkaException(TradingSystemException):
    """Kafka-related errors."""
    pass


class ProducerException(KafkaException):
    """Kafka producer errors."""
    pass


class ConsumerException(KafkaException):
    """Kafka consumer errors."""
    pass


class AuthenticationException(TradingSystemException):
    """Authentication errors."""
    pass


class InvalidTokenException(AuthenticationException):
    """Invalid or expired token."""
    pass


class PermissionDeniedException(AuthenticationException):
    """Insufficient permissions."""
    pass


class ValidationException(TradingSystemException):
    """Data validation errors."""
    pass


class ConfigurationException(TradingSystemException):
    """Configuration errors."""
    pass


class RateLimitException(TradingSystemException):
    """Rate limit exceeded."""
    pass


class TradingException(TradingSystemException):
    """Trading operation errors."""
    pass


class OrderException(TradingException):
    """Order-related errors."""
    pass


class PositionException(TradingException):
    """Position-related errors."""
    pass


class RiskException(TradingException):
    """Risk management errors."""
    pass


class StrategyException(TradingSystemException):
    """Strategy-related errors."""
    pass


class BacktestException(StrategyException):
    """Backtesting errors."""
    pass


class FundamentalAnalysisException(TradingSystemException):
    """Fundamental analysis errors."""
    pass


class DataNotFoundException(TradingSystemException):
    """Required data not found."""
    pass


class ExternalAPIException(TradingSystemException):
    """External API errors."""
    pass
