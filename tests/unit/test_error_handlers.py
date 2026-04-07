"""Unit tests for error handler decorators (retry_on_exception, retry_async_on_exception).

These tests exercise the retry logic entirely through mocks of time.sleep
and asyncio.sleep so they run instantly without real infrastructure.
"""

import sys
import os
import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so `libs.*` imports resolve.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ===================================================================
# Tests for retry_on_exception (sync)
# ===================================================================


class TestRetryOnExceptionSucceedsFirstTry:
    """When the decorated function succeeds on the first attempt, no retry occurs."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_succeeds_immediately(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        call_count = 0

        @retry_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.1)
        def good_fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = good_fn()

        assert result == "ok"
        assert call_count == 1
        mock_sleep.assert_not_called()


class TestRetryOnExceptionRetriesOnFailure:
    """When the function fails then succeeds, it retries and eventually returns."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        call_count = 0

        @retry_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.5)
        def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient")
            return "recovered"

        result = flaky_fn()

        assert result == "recovered"
        assert call_count == 2
        assert mock_sleep.call_count == 1


class TestRetryOnExceptionMaxAttemptsExhausted:
    """When all attempts fail, the last exception is re-raised."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_raises_after_max_attempts(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        call_count = 0

        @retry_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.1)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"fail-{call_count}")

        with pytest.raises(ValueError, match="fail-3"):
            always_fails()

        assert call_count == 3
        # Sleep should be called between attempts (not after the last)
        assert mock_sleep.call_count == 2


class TestRetryOnExceptionExponentialBackoff:
    """The delay grows exponentially with the backoff multiplier."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_backoff_doubles_delay(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        @retry_on_exception(
            exceptions=(ValueError,),
            max_attempts=4,
            delay=1.0,
            backoff=3.0,
        )
        def always_fails():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            always_fails()

        # Delays: 1.0, 3.0, 9.0  (3 retries => 3 sleeps)
        assert mock_sleep.call_count == 3
        delays = [c[0][0] for c in mock_sleep.call_args_list]
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(3.0)
        assert delays[2] == pytest.approx(9.0)


class TestRetryOnExceptionOnlyCatchesSpecified:
    """Non-matching exceptions propagate immediately without retries."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_unmatched_exception_propagates(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        call_count = 0

        @retry_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.1)
        def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            raises_type_error()

        assert call_count == 1
        mock_sleep.assert_not_called()


class TestRetryOnExceptionSuccessOnFinalAttempt:
    """Function that succeeds on the very last allowed attempt."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_succeeds_on_last_attempt(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        call_count = 0

        @retry_on_exception(
            exceptions=(RuntimeError,),
            max_attempts=5,
            delay=0.2,
            backoff=1.0,
        )
        def late_success():
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise RuntimeError("not yet")
            return "finally"

        result = late_success()

        assert result == "finally"
        assert call_count == 5
        assert mock_sleep.call_count == 4


class TestRetryPreservesFunctionMetadata:
    """The @functools.wraps call preserves __name__, __doc__, etc."""

    @patch("libs.common.errors.handlers.time.sleep")
    def test_name_preserved(self, mock_sleep):
        from libs.common.errors.handlers import retry_on_exception

        @retry_on_exception(exceptions=(Exception,), max_attempts=1)
        def my_documented_function():
            """A helpful docstring."""
            pass

        assert my_documented_function.__name__ == "my_documented_function"
        assert my_documented_function.__doc__ == "A helpful docstring."


# ===================================================================
# Tests for retry_async_on_exception (async)
# ===================================================================


class TestRetryAsyncOnExceptionSucceedsFirstTry:
    """Async function succeeds on first try without retries."""

    @pytest.mark.asyncio
    async def test_succeeds_immediately(self):
        from libs.common.errors.handlers import retry_async_on_exception

        call_count = 0

        @retry_async_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.1)
        async def good_async_fn():
            nonlocal call_count
            call_count += 1
            return "async-ok"

        result = await good_async_fn()

        assert result == "async-ok"
        assert call_count == 1


class TestRetryAsyncOnExceptionRetriesOnFailure:
    """Async function retries on failure and eventually succeeds."""

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        from libs.common.errors.handlers import retry_async_on_exception

        call_count = 0

        @retry_async_on_exception(exceptions=(ValueError,), max_attempts=3, delay=0.01)
        async def flaky_async():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient-async")
            return "recovered-async"

        result = await flaky_async()

        assert result == "recovered-async"
        assert call_count == 3


class TestRetryAsyncOnExceptionMaxAttemptsExhausted:
    """All async attempts fail: last exception re-raised."""

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        from libs.common.errors.handlers import retry_async_on_exception

        call_count = 0

        @retry_async_on_exception(
            exceptions=(RuntimeError,), max_attempts=3, delay=0.01
        )
        async def always_fails_async():
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"async-fail-{call_count}")

        with pytest.raises(RuntimeError, match="async-fail-3"):
            await always_fails_async()

        assert call_count == 3


class TestRetryAsyncOnExceptionExponentialBackoff:
    """Async retry uses asyncio.sleep with exponential backoff delays."""

    @pytest.mark.asyncio
    async def test_backoff_increases_delay(self):
        from libs.common.errors.handlers import retry_async_on_exception

        sleep_durations = []

        original_sleep = asyncio.sleep

        async def fake_sleep(duration):
            sleep_durations.append(duration)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            @retry_async_on_exception(
                exceptions=(ValueError,),
                max_attempts=4,
                delay=1.0,
                backoff=2.0,
            )
            async def always_fails():
                raise ValueError("backoff-test")

            with pytest.raises(ValueError):
                await always_fails()

        assert sleep_durations == [1.0, 2.0, 4.0]


class TestRetryAsyncOnExceptionOnlyCatchesSpecified:
    """Non-matching async exceptions propagate immediately."""

    @pytest.mark.asyncio
    async def test_unmatched_exception_propagates(self):
        from libs.common.errors.handlers import retry_async_on_exception

        call_count = 0

        @retry_async_on_exception(
            exceptions=(ValueError,), max_attempts=5, delay=0.01
        )
        async def raises_key_error():
            nonlocal call_count
            call_count += 1
            raise KeyError("missing")

        with pytest.raises(KeyError):
            await raises_key_error()

        assert call_count == 1


class TestRetryAsyncOnExceptionSuccessOnFinalAttempt:
    """Async function that succeeds on the very last attempt."""

    @pytest.mark.asyncio
    async def test_succeeds_on_last_attempt(self):
        from libs.common.errors.handlers import retry_async_on_exception

        call_count = 0

        @retry_async_on_exception(
            exceptions=(ConnectionError,),
            max_attempts=5,
            delay=0.01,
            backoff=1.0,
        )
        async def late_async_success():
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise ConnectionError("not connected yet")
            return "connected"

        result = await late_async_success()

        assert result == "connected"
        assert call_count == 5
