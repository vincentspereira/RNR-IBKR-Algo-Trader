"""Unit tests for MetricsCollector, track_time, and track_async_time.

All prometheus_client types are mocked so these tests run without
a real Prometheus server or any special infrastructure.

Strategy: mock prometheus_client at sys.modules level, then import the
metrics module which will bind those mocks as module-level names.
After that we can use patch.object on the module's own references.
"""

import sys
import os
import time
import asyncio
import importlib
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# ---------------------------------------------------------------------------
# Pre-install mock for prometheus_client so the metrics module can be
# imported even when the real package is not installed.
# ---------------------------------------------------------------------------
_mock_prom = MagicMock()
sys.modules.setdefault("prometheus_client", _mock_prom)

# Import the module under test
import libs.common.monitoring.metrics as _metrics_module


# ===================================================================
# MetricsCollector tests
# ===================================================================


class TestMetricsCollectorInitialization:
    """MetricsCollector.__init__ creates the right set of metrics."""

    def test_initialization_with_service_name(self):
        """Service name is stored and Counter/Gauge/Histogram/Info are called."""
        # Use real constructors (MagicMock) -- just verify they were called
        mock_counter = MagicMock()
        mock_gauge = MagicMock()
        mock_histogram = MagicMock()
        mock_info = MagicMock()

        with patch.object(_metrics_module, "Counter", mock_counter), \
             patch.object(_metrics_module, "Gauge", mock_gauge), \
             patch.object(_metrics_module, "Histogram", mock_histogram), \
             patch.object(_metrics_module, "Info", mock_info):

            collector = _metrics_module.MetricsCollector("my_service")

        assert collector.service_name == "my_service"
        # Counter should be called multiple times (request_count, db_query_count, etc.)
        assert mock_counter.call_count >= 1
        assert mock_gauge.call_count >= 1
        assert mock_histogram.call_count >= 1

    def test_creates_all_metric_families(self):
        """All metric attributes are assigned from prometheus constructors."""
        mock_counter = MagicMock()
        mock_gauge = MagicMock()
        mock_histogram = MagicMock()
        mock_info = MagicMock()

        with patch.object(_metrics_module, "Counter", mock_counter), \
             patch.object(_metrics_module, "Gauge", mock_gauge), \
             patch.object(_metrics_module, "Histogram", mock_histogram), \
             patch.object(_metrics_module, "Info", mock_info):

            collector = _metrics_module.MetricsCollector("svc")

        # Verify each attribute is assigned from the correct constructor
        assert collector.service_info is mock_info.return_value
        assert collector.active_connections is mock_gauge.return_value


class TestMetricsCollectorTrackRequest:
    """Tests for track_request method."""

    def test_track_request_increments_counter_and_observes_duration(self):
        """track_request calls labels().inc() on counter and labels().observe() on histogram."""
        mock_counter_labels = MagicMock()
        mock_histogram_labels = MagicMock()

        # Build a collector with mocked internal metrics
        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        # Override specific metric methods
        collector.request_count = MagicMock()
        collector.request_count.labels = Mock(return_value=mock_counter_labels)
        collector.request_duration = MagicMock()
        collector.request_duration.labels = Mock(return_value=mock_histogram_labels)

        collector.track_request("GET", "/api/orders", 200, 0.42)

        collector.request_count.labels.assert_called_once_with(
            method="GET", endpoint="/api/orders", status=200
        )
        mock_counter_labels.inc.assert_called_once()

        collector.request_duration.labels.assert_called_once_with(
            method="GET", endpoint="/api/orders"
        )
        mock_histogram_labels.observe.assert_called_once_with(0.42)


class TestMetricsCollectorTrackDbQuery:
    """Tests for track_db_query method."""

    def test_track_db_query(self):
        mock_counter_labels = MagicMock()
        mock_histogram_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.db_query_count = MagicMock()
        collector.db_query_count.labels = Mock(return_value=mock_counter_labels)
        collector.db_query_duration = MagicMock()
        collector.db_query_duration.labels = Mock(return_value=mock_histogram_labels)

        collector.track_db_query("postgres", "SELECT", 0.15)

        collector.db_query_count.labels.assert_called_once_with(
            database="postgres", operation="SELECT"
        )
        mock_counter_labels.inc.assert_called_once()
        collector.db_query_duration.labels.assert_called_once_with(
            database="postgres", operation="SELECT"
        )
        mock_histogram_labels.observe.assert_called_once_with(0.15)


class TestMetricsCollectorTrackKafka:
    """Tests for track_kafka_produce and track_kafka_consume."""

    def test_track_kafka_produce(self):
        mock_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.kafka_messages_produced = MagicMock()
        collector.kafka_messages_produced.labels = Mock(return_value=mock_labels)

        collector.track_kafka_produce("orders")

        collector.kafka_messages_produced.labels.assert_called_once_with(topic="orders")
        mock_labels.inc.assert_called_once()

    def test_track_kafka_consume(self):
        mock_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.kafka_messages_consumed = MagicMock()
        collector.kafka_messages_consumed.labels = Mock(return_value=mock_labels)

        collector.track_kafka_consume("signals")

        collector.kafka_messages_consumed.labels.assert_called_once_with(topic="signals")
        mock_labels.inc.assert_called_once()


class TestMetricsCollectorTrackOrders:
    """Tests for track_order_created and track_order_filled."""

    def test_track_order_created(self):
        mock_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.orders_created = MagicMock()
        collector.orders_created.labels = Mock(return_value=mock_labels)

        collector.track_order_created("AAPL", "BUY")

        collector.orders_created.labels.assert_called_once_with(
            symbol="AAPL", side="BUY"
        )
        mock_labels.inc.assert_called_once()

    def test_track_order_filled(self):
        mock_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.orders_filled = MagicMock()
        collector.orders_filled.labels = Mock(return_value=mock_labels)

        collector.track_order_filled("MSFT", "SELL")

        collector.orders_filled.labels.assert_called_once_with(
            symbol="MSFT", side="SELL"
        )
        mock_labels.inc.assert_called_once()


class TestMetricsCollectorTrackError:
    """Tests for track_error method."""

    def test_track_error(self):
        mock_labels = MagicMock()

        with patch.object(_metrics_module, "Counter"), \
             patch.object(_metrics_module, "Gauge"), \
             patch.object(_metrics_module, "Histogram"), \
             patch.object(_metrics_module, "Info"), \
             patch.object(_metrics_module, "Summary", MagicMock()):

            collector = _metrics_module.MetricsCollector("svc")

        collector.errors_total = MagicMock()
        collector.errors_total.labels = Mock(return_value=mock_labels)

        collector.track_error("connection_timeout")

        collector.errors_total.labels.assert_called_once_with(
            error_type="connection_timeout"
        )
        mock_labels.inc.assert_called_once()


# ===================================================================
# track_time decorator tests
# ===================================================================


class TestTrackTimeDecorator:
    """Tests for the track_time synchronous decorator."""

    def test_decorator_calls_observe_with_duration(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_time(mock_histogram)
        def fn():
            return 42

        result = fn()

        assert result == 42
        mock_histogram.observe.assert_called_once()
        observed_duration = mock_histogram.observe.call_args[0][0]
        assert isinstance(observed_duration, float)
        assert observed_duration >= 0

    def test_decorator_still_raises_exceptions(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_time(mock_histogram)
        def failing_fn():
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError, match="oops"):
            failing_fn()

        # observe should still be called even on exception (finally block)
        mock_histogram.observe.assert_called_once()

    def test_decorator_preserves_function_metadata(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_time(mock_histogram)
        def my_function():
            """Docstring here."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "Docstring here."


# ===================================================================
# track_async_time decorator tests
# ===================================================================


class TestTrackAsyncTimeDecorator:
    """Tests for the track_async_time asynchronous decorator."""

    @pytest.mark.asyncio
    async def test_async_decorator_calls_observe(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_async_time(mock_histogram)
        async def async_fn():
            return "done"

        result = await async_fn()

        assert result == "done"
        mock_histogram.observe.assert_called_once()
        observed_duration = mock_histogram.observe.call_args[0][0]
        assert isinstance(observed_duration, float)
        assert observed_duration >= 0

    @pytest.mark.asyncio
    async def test_async_decorator_still_raises_exceptions(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_async_time(mock_histogram)
        async def failing_async():
            raise ValueError("async-oops")

        with pytest.raises(ValueError, match="async-oops"):
            await failing_async()

        mock_histogram.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_decorator_preserves_metadata(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_async_time(mock_histogram)
        async def my_async_fn():
            """Async docstring."""
            pass

        assert my_async_fn.__name__ == "my_async_fn"
        assert my_async_fn.__doc__ == "Async docstring."


# ===================================================================
# Timer integration test
# ===================================================================


class TestTimerIntegration:
    """Verify durations are measured with reasonable accuracy."""

    def test_track_time_measures_real_duration(self):
        mock_histogram = MagicMock()

        @_metrics_module.track_time(mock_histogram)
        def slow_fn():
            time.sleep(0.05)
            return "slow"

        slow_fn()

        observed_duration = mock_histogram.observe.call_args[0][0]
        # Should be at least ~50ms but not wildly over
        assert observed_duration >= 0.04
        assert observed_duration < 2.0
