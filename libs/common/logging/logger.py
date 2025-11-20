"""Structured logging configuration and utilities."""
import logging
import sys
from typing import Any, Dict, Optional

import structlog
from pythonjsonlogger import jsonlogger


def configure_logging(
    log_level: str = "INFO",
    log_format: str = "json",
    service_name: Optional[str] = None
) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Log format (json or text)
        service_name: Service name to include in logs
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    
    # Configure structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # Add service name if provided
    if service_name:
        processors.insert(0, structlog.processors.CallsiteParameterAdder({
            structlog.processors.CallsiteParameter.FILENAME,
            structlog.processors.CallsiteParameter.FUNC_NAME,
            structlog.processors.CallsiteParameter.LINENO,
        }))
    
    # Add renderer based on format
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **context: Any) -> structlog.BoundLogger:
    """
    Get a structured logger with optional context.
    
    Args:
        name: Logger name
        **context: Additional context to bind to logger
        
    Returns:
        Bound logger instance
    """
    logger = structlog.get_logger(name)
    if context:
        logger = logger.bind(**context)
    return logger


class LoggerMixin:
    """Mixin to add logging capabilities to classes."""
    
    @property
    def logger(self) -> structlog.BoundLogger:
        """Get logger for this class."""
        if not hasattr(self, '_logger'):
            self._logger = get_logger(
                self.__class__.__name__,
                class_name=self.__class__.__name__
            )
        return self._logger


def log_function_call(func):
    """
    Decorator to log function calls with arguments and return values.
    
    Args:
        func: Function to decorate
        
    Returns:
        Decorated function
    """
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__name__)
        logger.info(
            "function_called",
            function=func.__name__,
            args=args,
            kwargs=kwargs
        )
        
        try:
            result = func(*args, **kwargs)
            logger.info(
                "function_completed",
                function=func.__name__,
                result=result
            )
            return result
        except Exception as e:
            logger.error(
                "function_failed",
                function=func.__name__,
                error=str(e),
                exc_info=True
            )
            raise
    
    return wrapper


def log_async_function_call(func):
    """
    Decorator to log async function calls.
    
    Args:
        func: Async function to decorate
        
    Returns:
        Decorated async function
    """
    async def wrapper(*args, **kwargs):
        logger = get_logger(func.__name__)
        logger.info(
            "async_function_called",
            function=func.__name__,
            args=args,
            kwargs=kwargs
        )
        
        try:
            result = await func(*args, **kwargs)
            logger.info(
                "async_function_completed",
                function=func.__name__,
                result=result
            )
            return result
        except Exception as e:
            logger.error(
                "async_function_failed",
                function=func.__name__,
                error=str(e),
                exc_info=True
            )
            raise
    
    return wrapper
