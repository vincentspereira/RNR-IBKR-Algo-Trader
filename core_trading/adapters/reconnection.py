"""Reconnection manager with exponential backoff and jitter.

Provides robust reconnection logic for adapter connections with configurable
retry behavior, jitter to prevent thundering herd, and callback hooks.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReconnectionConfig:
    """Configuration for reconnection behavior."""
    initial_delay: float = 1.0
    max_delay: float = 60.0
    max_attempts: Optional[int] = None
    jitter: bool = True
    jitter_factor: float = 0.5


class ReconnectionManager:
    """Exponential backoff reconnection with jitter."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        max_attempts: Optional[int] = None,
        jitter: bool = True,
        on_reconnect: Optional[Callable] = None,
        on_failure: Optional[Callable] = None,
    ):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self.jitter = jitter
        self._on_reconnect = on_reconnect
        self._on_failure = on_failure
        self._attempt = 0

    async def execute_with_retry(
        self,
        connect_fn: Callable[[], Awaitable[bool]],
    ) -> bool:
        """Try connect_fn with exponential backoff.

        Args:
            connect_fn: Async callable that returns True on success.

        Returns:
            True if connection succeeded, False if all attempts exhausted.
        """
        self._attempt = 0

        while self.max_attempts is None or self._attempt < self.max_attempts:
            try:
                result = await connect_fn()
                if result:
                    logger.info(f"Connection succeeded on attempt {self._attempt + 1}")
                    if self._on_reconnect:
                        self._on_reconnect()
                    return True
            except Exception as e:
                logger.warning(
                    f"Connection attempt {self._attempt + 1} failed: {e}"
                )

            # Calculate delay with exponential backoff
            delay = min(self.initial_delay * (2 ** self._attempt), self.max_delay)

            # Add jitter
            if self.jitter:
                delay *= (0.5 + random.random())

            logger.info(f"Reconnecting in {delay:.1f}s (attempt {self._attempt + 1})")
            await asyncio.sleep(delay)
            self._attempt += 1

        logger.error(
            f"All reconnection attempts exhausted ({self._attempt} attempts)"
        )
        if self._on_failure:
            self._on_failure()
        return False

    @property
    def current_attempt(self) -> int:
        return self._attempt

    def reset(self):
        """Reset attempt counter."""
        self._attempt = 0
