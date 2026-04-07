"""Test suite for the Reconnection Manager.

Source: core_trading/adapters/reconnection.py

All tests mock asyncio.sleep to avoid actual delays while verifying that
exponential backoff timing, jitter, and retry behavior are correct.
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from core_trading.adapters.reconnection import ReconnectionConfig, ReconnectionManager


# ===================================================================
# ReconnectionConfig tests
# ===================================================================


class TestReconnectionConfig:
    """Tests for ReconnectionConfig dataclass."""

    def test_default_values(self):
        config = ReconnectionConfig()
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.max_attempts is None
        assert config.jitter is True
        assert config.jitter_factor == 0.5

    def test_custom_values(self):
        config = ReconnectionConfig(
            initial_delay=2.0,
            max_delay=120.0,
            max_attempts=5,
            jitter=False,
        )
        assert config.initial_delay == 2.0
        assert config.max_delay == 120.0
        assert config.max_attempts == 5
        assert config.jitter is False


# ===================================================================
# ReconnectionManager core retry tests
# ===================================================================


class TestReconnectionManager:
    """Tests for ReconnectionManager."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_first_attempt(self):
        connect_fn = AsyncMock(return_value=True)
        mgr = ReconnectionManager(max_attempts=3)
        result = await mgr.execute_with_retry(connect_fn)
        assert result is True
        assert mgr.current_attempt == 0  # succeeded before incrementing

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self):
        connect_fn = AsyncMock(side_effect=[False, False, True])
        mgr = ReconnectionManager(initial_delay=0.01, max_delay=0.01, max_attempts=5, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(connect_fn)

        assert result is True

    @pytest.mark.asyncio
    async def test_retry_max_attempts_exhausted(self):
        connect_fn = AsyncMock(return_value=False)
        mgr = ReconnectionManager(initial_delay=0.01, max_delay=0.01, max_attempts=3, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(connect_fn)

        assert result is False

    @pytest.mark.asyncio
    async def test_retry_exception_treated_as_failure(self):
        connect_fn = AsyncMock(side_effect=[Exception("boom"), True])
        mgr = ReconnectionManager(initial_delay=0.01, max_delay=0.01, max_attempts=3, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(connect_fn)

        assert result is True

    @pytest.mark.asyncio
    async def test_retry_custom_config(self):
        """Custom initial_delay and max_delay should be respected."""
        mgr = ReconnectionManager(initial_delay=0.5, max_delay=10.0, max_attempts=2)
        assert mgr.initial_delay == 0.5
        assert mgr.max_delay == 10.0
        assert mgr.max_attempts == 2

    @pytest.mark.asyncio
    async def test_retry_calls_on_reconnect_callback(self):
        callback = MagicMock()
        connect_fn = AsyncMock(return_value=True)
        mgr = ReconnectionManager(max_attempts=3, on_reconnect=callback)

        result = await mgr.execute_with_retry(connect_fn)
        assert result is True
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_calls_on_failure_callback(self):
        callback = MagicMock()
        connect_fn = AsyncMock(return_value=False)
        mgr = ReconnectionManager(
            initial_delay=0.01, max_delay=0.01, max_attempts=2, jitter=False, on_failure=callback
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(connect_fn)

        assert result is False
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_clears_attempt_counter(self):
        connect_fn = AsyncMock(side_effect=[False, False])
        mgr = ReconnectionManager(initial_delay=0.01, max_delay=0.01, max_attempts=3, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mgr.execute_with_retry(connect_fn)

        mgr.reset()
        assert mgr.current_attempt == 0

    @pytest.mark.asyncio
    async def test_unlimited_attempts_when_none(self):
        """When max_attempts is None, retries should continue until success."""
        call_count = 0

        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        mgr = ReconnectionManager(initial_delay=0.01, max_delay=0.01, max_attempts=None, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(failing_then_success)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_delay_capped_at_max_delay(self):
        """Delay should not exceed max_delay even after many attempts."""
        delays = []

        async def mock_sleep(delay):
            delays.append(delay)

        connect_fn = AsyncMock(side_effect=[False] * 10 + [True])
        mgr = ReconnectionManager(initial_delay=1.0, max_delay=2.0, max_attempts=12, jitter=False)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await mgr.execute_with_retry(connect_fn)

        assert result is True
        for d in delays:
            assert d <= 2.0  # All delays should be <= max_delay


# ===================================================================
# Exponential backoff exact delay tests
# ===================================================================


class TestRetryExponentialBackoffDelays:
    """Tests that exponential backoff delays are computed correctly."""

    @pytest.mark.asyncio
    async def test_backoff_doubles_each_attempt(self):
        """Verify that the sleep delays follow exponential backoff exactly."""
        mgr = ReconnectionManager(
            initial_delay=1.0, max_delay=60.0, jitter=False, max_attempts=4,
        )

        async def always_fail():
            return False

        sleep_delays = []

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await mgr.execute_with_retry(always_fail)

        assert result is False
        # Attempt 0: delay = 1 * 2^0 = 1
        # Attempt 1: delay = 1 * 2^1 = 2
        # Attempt 2: delay = 1 * 2^2 = 4
        # Attempt 3: delay = 1 * 2^3 = 8
        assert len(sleep_delays) == 4
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 4.0
        assert sleep_delays[3] == 8.0

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max_delay_exact(self):
        """Verify that delays are capped at max_delay with exact values."""
        mgr = ReconnectionManager(
            initial_delay=10.0, max_delay=25.0, jitter=False, max_attempts=5,
        )

        async def always_fail():
            return False

        sleep_delays = []

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await mgr.execute_with_retry(always_fail)

        assert result is False
        # Attempt 0: min(10*1, 25) = 10
        # Attempt 1: min(10*2, 25) = 20
        # Attempt 2: min(10*4, 25) = 25  (capped)
        # Attempt 3: min(10*8, 25) = 25  (capped)
        # Attempt 4: min(10*16, 25) = 25 (capped)
        assert sleep_delays[0] == 10.0
        assert sleep_delays[1] == 20.0
        assert sleep_delays[2] == 25.0
        assert sleep_delays[3] == 25.0
        assert sleep_delays[4] == 25.0

    @pytest.mark.asyncio
    async def test_custom_initial_delay_backoff(self):
        """Backoff should use the custom initial_delay."""
        mgr = ReconnectionManager(
            initial_delay=5.0, max_delay=100.0, jitter=False, max_attempts=3,
        )

        async def always_fail():
            return False

        sleep_delays = []

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await mgr.execute_with_retry(always_fail)

        assert sleep_delays[0] == 5.0   # 5 * 2^0
        assert sleep_delays[1] == 10.0  # 5 * 2^1
        assert sleep_delays[2] == 20.0  # 5 * 2^2


# ===================================================================
# Jitter tests
# ===================================================================


class TestRetryJitterApplied:
    """Tests that jitter modifies delays when enabled."""

    @pytest.mark.asyncio
    async def test_jitter_modifies_delay_range(self):
        """With jitter=True, delays should be in range [0.5*base, 1.5*base]."""
        mgr = ReconnectionManager(
            initial_delay=10.0, max_delay=100.0, jitter=True, max_attempts=5,
        )

        async def always_fail():
            return False

        recorded_delays = []

        async def mock_sleep(delay):
            recorded_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await mgr.execute_with_retry(always_fail)

        # With jitter: delay *= (0.5 + random()), range is [0.5, 1.5]
        # First delay base = 10 * 2^0 = 10, range [5, 15]
        assert 5.0 <= recorded_delays[0] <= 15.0

    @pytest.mark.asyncio
    async def test_no_jitter_gives_exact_delays(self):
        """With jitter=False, delays are exact multiples."""
        mgr = ReconnectionManager(
            initial_delay=5.0, max_delay=100.0, jitter=False, max_attempts=2,
        )

        async def always_fail():
            return False

        recorded_delays = []

        async def mock_sleep(delay):
            recorded_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await mgr.execute_with_retry(always_fail)

        assert recorded_delays[0] == 5.0   # 5 * 2^0
        assert recorded_delays[1] == 10.0  # 5 * 2^1


# ===================================================================
# Cancellation tests
# ===================================================================


class TestRetryCancelled:
    """Tests for cancellation handling during retry."""

    @pytest.mark.asyncio
    async def test_cancelled_during_sleep(self):
        """If asyncio.sleep is cancelled, the retry loop should propagate CancelledError."""
        mgr = ReconnectionManager(max_attempts=10)

        async def always_fail():
            return False

        async def cancel_on_sleep(delay):
            raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=cancel_on_sleep):
            with pytest.raises(asyncio.CancelledError):
                await mgr.execute_with_retry(always_fail)

    @pytest.mark.asyncio
    async def test_cancelled_during_connect_fn(self):
        """If connect_fn raises CancelledError, it should propagate."""
        mgr = ReconnectionManager(max_attempts=5)

        async def raise_cancelled():
            raise asyncio.CancelledError()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await mgr.execute_with_retry(raise_cancelled)


# ===================================================================
# Additional coverage tests
# ===================================================================


class TestExecuteWithRetryResetsAttempt:
    """Tests that execute_with_retry resets the attempt counter on entry."""

    @pytest.mark.asyncio
    async def test_resets_prior_attempt_state(self):
        """execute_with_retry resets _attempt to 0 at the start."""
        mgr = ReconnectionManager(max_attempts=5)
        mgr._attempt = 10  # simulate prior failed run

        async def succeed():
            return True

        await mgr.execute_with_retry(succeed)
        assert mgr.current_attempt == 0


class TestAttemptCounterTracking:
    """Tests for current_attempt property during retries."""

    @pytest.mark.asyncio
    async def test_attempt_counter_increments(self):
        """current_attempt should reflect the number of failed attempts."""
        mgr = ReconnectionManager(max_attempts=3, jitter=False)

        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            # Check attempt counter at each call
            if call_count == 1:
                assert mgr.current_attempt == 0
            if call_count == 2:
                assert mgr.current_attempt == 1
            return call_count >= 2

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mgr.execute_with_retry(fail_then_succeed)

    @pytest.mark.asyncio
    async def test_attempt_counter_after_exhaustion(self):
        """After exhausting all attempts, current_attempt equals max_attempts."""
        mgr = ReconnectionManager(max_attempts=3, jitter=False)

        async def always_fail():
            return False

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mgr.execute_with_retry(always_fail)

        assert mgr.current_attempt == 3


class TestMixedFailureModes:
    """Tests for mixed failures and exceptions."""

    @pytest.mark.asyncio
    async def test_mixed_false_returns_and_exceptions(self):
        """Mix of False returns and exceptions should be retried until success."""
        mgr = ReconnectionManager(max_attempts=6, jitter=False)

        call_count = 0

        async def mixed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("err")
            if call_count == 2:
                return False
            if call_count == 3:
                raise TimeoutError("timeout")
            return True

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(mixed)

        assert result is True
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_all_attempts_raise_exceptions(self):
        """All attempts raising exceptions should return False."""
        mgr = ReconnectionManager(max_attempts=3, jitter=False)

        async def always_raise():
            raise ConnectionError("refused")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr.execute_with_retry(always_raise)

        assert result is False
        assert mgr.current_attempt == 3
