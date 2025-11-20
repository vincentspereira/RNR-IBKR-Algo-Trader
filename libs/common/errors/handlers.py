"""Error handling utilities."""
import functools
import time
from typing import Callable, Type, Tuple
from .exceptions import TradingSystemException


def retry_on_exception(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0
):
    """
    Decorator to retry function on specific exceptions.
    
    Args:
        exceptions: Tuple of exception types to catch
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Backoff multiplier for delay
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            
            raise last_exception
        
        return wrapper
    return decorator


def retry_async_on_exception(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0
):
    """
    Decorator to retry async function on specific exceptions.
    
    Args:
        exceptions: Tuple of exception types to catch
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Backoff multiplier for delay
        
    Returns:
        Decorated async function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            
            raise last_exception
        
        return wrapper
    return decorator
