import asyncio
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union
"Comprehensive Error Handling and Logging for Broker Adapters"

# This module provides standardized error handling, logging, and retry mechanisms
# for all broker adapters to ensure consistent behavior and robust error recovery.""




# "

class ErrorSeverity(Enum):""
# "Error severity levels
# "
#     LOW = "low"
#     MEDIUM = "medium"
#     HIGH = "high"
#     CRITICAL = "critical"


# "

class ErrorCategory(Enum):""
# "Error categories for classification
# "
#     CONNECTION = "connection"
#     AUTHENTICATION = "authentication"
#     AUTHORIZATION = "authorization"
#     RATE_LIMIT = "rate_limit"
#     VALIDATION = "validation"
#     ORDER_EXECUTION = "order_execution"
#     MARKET_DATA = "market_data"
#     ACCOUNT_ACCESS = "account_access"
#     NETWORK = "network"
# ""API_ERROR = "api_error"
#     TIMEOUT = "timeout"
#     UNKNOWN = "unknown"


# "

# @dataclass
class BrokerError:""
#     "Standardized broker error representation"

#     error_code: str
#     message: str
#     category: ErrorCategory
#     severity: ErrorSeverity
# timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))"
# broker_name: str = "
#     request_id: Optional[str] = None
#     context: Dict[str, Any] = field(default_factory=dict)
#     original_exception: Optional[Exception] = None
#     stack_trace: Optional[str] = None
#     retry_count: int = 0
#     is_retryable: bool = False

#     def to_dict(self):
# "Convert error to dictionary for logging/serialization
#         return {""
# "error_code": self.error_code,"
# "message": self.message,"
# "category": self.category.value,"
# "severity": self.severity.value,"
# "timestamp": self.timestamp.isoformat(),"
# "broker_name": self.broker_name,"
# "request_id": self.request_id,"
# "context": self.context,"
# "retry_count": self.retry_count,"
# "is_retryable": self.is_retryable,"
# "stack_trace": self.stack_trace,
# }

#     def to_json(self):
#         "Convert error to JSON string"
#         return json.dumps(self.to_dict(), indent=2, default=str)


class BrokerErrorHandler:""
#     "Centralized error handling for broker adapters"

#     def __init__(self, broker_name: str, logger: Optional[logging.Logger] = None):
#         self.broker_name = broker_name""
#         self.logger = logger or logging.getLogger(f"broker.{broker_name}")
#         self.error_history: List[BrokerError] = []
#         self.error_callbacks: List[Callable[[BrokerError], None]] = []
#         self.max_history_size = 1000

        # Error mapping for common broker errors
#         self.error_mappings: Dict[str, Dict[str, Any]] = {
            # Connection errors"
# "connection_refused": {
# "category": ErrorCategory.CONNECTION,"
# "severity": ErrorSeverity.HIGH,"
# "is_retryable": True,
# },"
# "timeout": {
# "category": ErrorCategory.TIMEOUT,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": True,
# },"
# "network_error": {
# "category": ErrorCategory.NETWORK,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": True,
# },
            # Authentication/Authorization errors"
# "invalid_credentials": {
# "category": ErrorCategory.AUTHENTICATION,"
# "severity": ErrorSeverity.CRITICAL,"
# "is_retryable": False,
# },"
# "unauthorized": {
# "category": ErrorCategory.AUTHORIZATION,"
# "severity": ErrorSeverity.HIGH,"
# "is_retryable": False,
# },"
# "api_key_invalid": {
# "category": ErrorCategory.AUTHENTICATION,"
# "severity": ErrorSeverity.CRITICAL,"
# "is_retryable": False,
# },
            # Rate limiting"
# "rate_limit_exceeded": {
# "category": ErrorCategory.RATE_LIMIT,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": True,
# },
            # Order execution errors"
# "insufficient_funds": {
# "category": ErrorCategory.ORDER_EXECUTION,"
# "severity": ErrorSeverity.HIGH,"
# "is_retryable": False,
# },"
# "invalid_order": {
# "category": ErrorCategory.VALIDATION,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": False,
# },"
# "market_closed": {
# "category": ErrorCategory.ORDER_EXECUTION,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": True,
# },
            # Market data errors"
# "symbol_not_found": {
# "category": ErrorCategory.MARKET_DATA,"
# "severity": ErrorSeverity.MEDIUM,"
# "is_retryable": False,
# },"
# "data_unavailable": {
# "category": ErrorCategory.MARKET_DATA,"
# "severity": ErrorSeverity.LOW,"
# "is_retryable": True,
# },
# }

#     def create_error(
#         self,
# error_code: str,
# message: str,
#         category: Optional[ErrorCategory] = None,
#         severity: Optional[ErrorSeverity] = None,
#         context: Optional[Dict[str, Any]] = None,
#         original_exception: Optional[Exception] = None,
#         request_id: Optional[str] = None,
#         is_retryable: Optional[bool] = None,
# ) -> BrokerError:"
#         "Create a standardized broker error"

        # Use error mapping if available
#         mapping = self.error_mappings.get(error_code.lower(), {})

# error = BrokerError(
#             error_code=error_code,
# message=message,"
# category=category or mapping.get("category", ErrorCategory.UNKNOWN),"
#             severity=severity or mapping.get("severity", ErrorSeverity.MEDIUM),
#             broker_name=self.broker_name,
#             request_id=request_id,
#             context=context or {},
#             original_exception=original_exception,
#             is_retryable=is_retryable
#             if is_retryable is not None""
# else mapping.get("is_retryable", False),
# )

        # Add stack trace if exception provided
#         if original_exception:
#             error.stack_trace = traceback.format_exc()

#         return error

#     def handle_error(self, error: BrokerError):
#         "Handle and log a broker error"
        # Add to history
#         self.error_history.append(error)
#         if len(self.error_history) > self.max_history_size:
#             self.error_history.pop(0)

        # Log error based on severity"
# log_message = f"[{error.error_code}] {error.message}
#         if error.context:""
#             log_message += f" | Context: {error.context}"

#         if error.severity == ErrorSeverity.CRITICAL:
#             self.logger.critical(log_message, exc_info=error.original_exception)
#         elif error.severity == ErrorSeverity.HIGH:
#             self.logger.error(log_message, exc_info=error.original_exception)
#         elif error.severity == ErrorSeverity.MEDIUM:
#             self.logger.warning(log_message)
#         else:
#             self.logger.info(log_message)

        # Call registered callbacks
#         for callback in self.error_callbacks:
#             try:
#                 callback(error)
#             except Exception as e:""
#                 self.logger.error(f"Error in error callback: {e}")

#     def handle_exception(
#         self,
# exception: Exception,
#         error_code: Optional[str] = None,
#         context: Optional[Dict[str, Any]] = None,
#         request_id: Optional[str] = None,
# ) -> BrokerError:"
#         "Handle a raw exception and convert to BrokerError"

        # Determine error code from exception type if not provided
#         if not error_code:
#             error_code = exception.__class__.__name__.lower()

        # Create error
# error = self.create_error(
#             error_code=error_code,
#             message=str(exception),
#             context=context,
#             original_exception=exception,
#             request_id=request_id,
# )

        # Handle the error
#         self.handle_error(error)

#         return error

#     def register_error_callback(self, callback: Callable[[BrokerError], None]):
#         "Register callback for error notifications"
#         self.error_callbacks.append(callback)

#     def get_error_history(
#         self,
#         category: Optional[ErrorCategory] = None,
#         severity: Optional[ErrorSeverity] = None,
#         limit: Optional[int] = None,
# ) -> List[BrokerError]:"
#         "Get filtered error history"
#         errors = self.error_history

#         if category:
#             errors = [e for e in errors if e.category == category]

#         if severity:
#             errors = [e for e in errors if e.severity == severity]

#         if limit:
#             errors = errors[-limit:]

#         return errors

#     def get_error_stats(self):
#         "Get error statistics"
#         if not self.error_history:
#             return {}

# stats = {
# "total_errors": len(self.error_history),"
# "by_category": {},"
# "by_severity": {},"
# "recent_errors": len(
# [
#                     e
#                     for e in self.error_history
#                     if (datetime.now(timezone.utc) - e.timestamp).total_seconds() < 3600
# ]
# ),
# }

#         for error in self.error_history:
            # Count by category"
# category = error.category.value"
#             stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

            # Count by severity"
# severity = error.severity.value"
#             stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1

#         return stats


class RetryConfig:""
#     "Configuration for retry mechanisms"

#     def __init__(
#         self,
#         max_attempts: int = 3,
#         base_delay: float = 1.0,
#         max_delay: float = 60.0,
#         exponential_backoff: bool = True,
#         jitter: bool = True,
#         retryable_errors: Optional[List[ErrorCategory]] = None,
# ):
#         self.max_attempts = max_attempts
#         self.base_delay = base_delay
#         self.max_delay = max_delay
#         self.exponential_backoff = exponential_backoff
#         self.jitter = jitter
#         self.retryable_errors = retryable_errors or [
#             ErrorCategory.CONNECTION,
#             ErrorCategory.NETWORK,
#             ErrorCategory.TIMEOUT,
#             ErrorCategory.RATE_LIMIT,
# ]


# def with_error_handling(
# error_handler: BrokerErrorHandler, retry_config: Optional[RetryConfig] = None
# ):"
#     "Decorator for adding error handling and retry logic to broker methods"

#     def decorator(func: Callable) -> Callable:
#         @wraps(func)
#         async def async_wrapper(*args, **kwargs):
#             "retry_config_to_use = retry_config or RetryConfig()"
#             last_error = None

#             for attempt in range(retry_config_to_use.max_attempts):
#                 try:
#                     return await func(*args, **kwargs)

#                 except Exception as e:
                    # Create broker error"
# broker_error = error_handler.handle_exception("
#                         e, context={"function": func.__name__, "attempt": attempt + 1}
# )
#                     last_error = broker_error

                    # Check if error is retryable
#                     if (
#                         not broker_error.is_retryable
# or broker_error.category
# not in retry_config_to_use.retryable_errors
# or attempt == retry_config_to_use.max_attempts - 1
# ):
#                         raise e

                    # Calculate delay
#                     delay = retry_config_to_use.base_delay
#                     if retry_config_to_use.exponential_backoff:
#                         delay *= 2**attempt

#                     delay = min(delay, retry_config_to_use.max_delay)

#                     if retry_config_to_use.jitter:
#                         import random

#                         delay *= 0.5 + random.random() * 0.5

# error_handler.logger.info("
#                         f"Retrying {func.__name__} in {delay:.2f}s (attempt {attempt + 1}/{retry_config_to_use.max_attempts})"
# )

#                     await asyncio.sleep(delay)

            # If we get here, all retries failed
#             if last_error and last_error.original_exception:
#                 raise last_error.original_exception
#             else:""
#                 raise RuntimeError(f"All retry attempts failed for {func.__name__}")

#         @wraps(func)
#         def sync_wrapper(*args, **kwargs):
#             try:
#                 return func(*args, **kwargs)
#             except Exception as e:""
#                 error_handler.handle_exception(e, context={"function": func.__name__})
#                 raise

#         return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

#     return decorator


class BrokerLogger:""
# "Enhanced logging for broker adapters
# "
# "

#     def __init__(self, broker_name: str, log_level: str = INFO):
#         self.broker_name = broker_name""
#         self.logger = logging.getLogger(f"broker.{broker_name}")
#         self.logger.setLevel(getattr(logging, log_level.upper()))

        # Create formatter"
# formatter = logging.Formatter("
#             "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# )

        # Add console handler if not already present
#         if not self.logger.handlers:
# "console_handler = logging.StreamHandler()""
#             console_handler.setFormatter(formatter)
#             self.logger.addHandler(console_handler)

#     def log_api_call(
#         self,
# method: str,
# endpoint: str,
#         params: Optional[Dict[str, Any]] = None,
#         response_time: Optional[float] = None,
#         status_code: Optional[int] = None,
# ):"
# "Log API call details""
# ""message = f"API Call: {method} {endpoint}
#         if params:""
# message += f" | Params: {params}
#         if response_time:""
# message += f" | Response Time: {response_time:.3f}s
#         if status_code:""
#             message += f" | Status: {status_code}"

#         self.logger.debug(message)

#     def log_order_event(
#         self,
# event_type: str,
# order_id: str,
# symbol: str,
#         details: Optional[Dict[str, Any]] = None,
# ):"
#         "Log order-related events"
# message = f"Order {event_type}: {order_id} ({symbol})
#         if details:""
#             message += f" | {details}"

#         self.logger.info(message)

#     def log_position_update(
# self, symbol: str, quantity: Decimal, market_value: Optional[Decimal] = None
# ):"
#         "Log position updates"
# message = f"Position Update: {symbol} | Quantity: {quantity}
#         if market_value:""
#             message += f" | Market Value: {market_value}"

#         self.logger.info(message)

#     def log_connection_event(self, event_type: str, details: Optional[str] = None):
#         "Log connection events"
# message = f"Connection {event_type}
#         if details:""
#             message += f": {details}"

#         self.logger.info(message)
# "