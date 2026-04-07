"""Unit tests for KafkaProducer.

All external dependencies (confluent_kafka, config, logging, events)
are fully mocked so these tests run without any real infrastructure.

Strategy:
  - confluent_kafka is mocked at sys.modules level so the source module
    can be imported without the real package.
  - After importing, we use patch.object to replace module-level names
    (Producer, JSONSerializer, get_config, logger) for each test.
  - The module-level `logger` variable is patched directly because it is
    bound at import time and never re-read through get_logger.
"""

import sys
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so `libs.*` imports resolve.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# ---------------------------------------------------------------------------
# Pre-install mock for confluent_kafka so the kafka_producer module can be
# imported even when the real package is not installed.
# ---------------------------------------------------------------------------
_mock_confluent = MagicMock()
_mock_confluent_admin = MagicMock()
sys.modules.setdefault("confluent_kafka", _mock_confluent)
sys.modules.setdefault("confluent_kafka.admin", _mock_confluent_admin)

# Now import the module under test
import libs.messaging.producers.kafka_producer as _kp_module


# ---------------------------------------------------------------------------
# Helper: build a lightweight mock config object matching AppConfig shape.
# ---------------------------------------------------------------------------
def _make_mock_config(bootstrap_servers: str = "localhost:9092"):
    kafka_cfg = Mock()
    kafka_cfg.bootstrap_servers = bootstrap_servers
    cfg = Mock()
    cfg.kafka = kafka_cfg
    return cfg


# ===================================================================
# Tests
# ===================================================================


class TestKafkaProducerInitialization:
    """Tests for KafkaProducer.__init__ and configuration."""

    def test_producer_initialization_with_config(self):
        """Producer uses bootstrap_servers from config when none given."""
        mock_producer_cls = MagicMock()
        with patch.object(_kp_module, "Producer", mock_producer_cls), \
             patch.object(_kp_module, "JSONSerializer", MagicMock()), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config("kafka1:9092")), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        assert producer.bootstrap_servers == "kafka1:9092"
        mock_producer_cls.assert_called_once()
        init_cfg = mock_producer_cls.call_args[0][0]
        assert init_cfg["bootstrap.servers"] == "kafka1:9092"
        assert init_cfg["client.id"] == "trading-system-producer"
        assert init_cfg["compression.type"] == "lz4"
        assert init_cfg["linger.ms"] == 10
        assert init_cfg["batch.size"] == 32768

    def test_producer_uses_explicit_bootstrap_servers(self):
        """Explicit bootstrap_servers override config."""
        mock_producer_cls = MagicMock()
        with patch.object(_kp_module, "Producer", mock_producer_cls), \
             patch.object(_kp_module, "JSONSerializer", MagicMock()), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config("cfg:9092")), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer(bootstrap_servers="custom:9093")

        assert producer.bootstrap_servers == "custom:9093"
        init_cfg = mock_producer_cls.call_args[0][0]
        assert init_cfg["bootstrap.servers"] == "custom:9093"

    def test_producer_compression_config(self):
        """Producer config contains lz4 compression."""
        mock_producer_cls = MagicMock()
        with patch.object(_kp_module, "Producer", mock_producer_cls), \
             patch.object(_kp_module, "JSONSerializer", MagicMock()), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            _kp_module.KafkaProducer()

        init_cfg = mock_producer_cls.call_args[0][0]
        assert init_cfg["compression.type"] == "lz4"

    def test_producer_connect_failure_raises(self):
        """If confluent_kafka.Producer() raises, init propagates."""
        with patch.object(_kp_module, "Producer", side_effect=Exception("broker unreachable")), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            with pytest.raises(Exception, match="broker unreachable"):
                _kp_module.KafkaProducer()

    def test_producer_connect_success(self):
        """Successful producer instantiation sets up serializer and logger."""
        mock_ser = MagicMock()
        mock_producer_cls = MagicMock()
        logger = Mock()
        with patch.object(_kp_module, "Producer", mock_producer_cls), \
             patch.object(_kp_module, "JSONSerializer", mock_ser), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", logger):

            producer = _kp_module.KafkaProducer()

        assert producer.producer is mock_producer_cls.return_value
        assert producer.serializer is mock_ser.return_value
        logger.info.assert_called_once()


class TestKafkaProduceEvent:
    """Tests for KafkaProducer.produce_event."""

    def test_produce_message_success(self):
        """produce_event serializes and calls confluent producer.produce."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{"event_type":"test"}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test_event"

        producer.produce_event("my-topic", event)

        mock_ser_inst.serialize.assert_called_once_with(event)
        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["topic"] == "my-topic"
        assert call_kwargs["value"] == b'{"event_type":"test"}'
        assert call_kwargs["callback"] == producer._delivery_callback

    def test_produce_message_with_key(self):
        """produce_event encodes key to bytes."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test_event"
        producer.produce_event("topic", event, key="order-123")

        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["key"] == b"order-123"

    def test_produce_message_no_key_is_none(self):
        """produce_event sends key=None when key is not provided."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test_event"
        producer.produce_event("topic", event)

        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["key"] is None

    def test_produce_message_with_headers(self):
        """produce_event encodes headers to bytes tuples."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test_event"

        producer.produce_event("topic", event, headers={"trace-id": "abc", "source": "api"})

        call_kwargs = mock_producer.produce.call_args[1]
        kafka_headers = call_kwargs["headers"]
        assert len(kafka_headers) == 2
        for k, v in kafka_headers:
            assert isinstance(v, bytes)
        header_dict = {k: v.decode() for k, v in kafka_headers}
        assert header_dict["trace-id"] == "abc"
        assert header_dict["source"] == "api"

    def test_produce_message_without_headers_is_none(self):
        """produce_event sends headers=None when no headers given."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test_event"
        producer.produce_event("topic", event)

        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["headers"] is None

    def test_produce_message_serialization(self):
        """produce_event uses JSONSerializer to serialize event to bytes."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{"serialized":true}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test"
        producer.produce_event("t", event)

        mock_ser_inst.serialize.assert_called_once_with(event)
        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["value"] == b'{"serialized":true}'

    def test_produce_message_triggers_poll(self):
        """produce_event calls producer.poll(0) after produce."""
        mock_producer = MagicMock()
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test"
        producer.produce_event("topic", event)

        mock_producer.poll.assert_called_once_with(0)

    def test_produce_failure_raises_producer_exception(self):
        """produce_event wraps exceptions in ProducerException."""
        mock_producer = MagicMock()
        mock_producer.produce.side_effect = Exception("broker error")
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'
        logger = Mock()

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", logger):

            producer = _kp_module.KafkaProducer()

            event = Mock()
            event.event_type = "test"

            with pytest.raises(_kp_module.ProducerException, match="Failed to produce event"):
                producer.produce_event("topic", event)

            logger.error.assert_called()

    def test_producer_retry_on_broker_error(self):
        """When produce raises a transient broker error, ProducerException is raised."""
        mock_producer = MagicMock()
        mock_producer.produce.side_effect = Exception("Broker: Queue full")
        mock_ser_inst = MagicMock()
        mock_ser_inst.serialize.return_value = b'{}'

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer", return_value=mock_ser_inst), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()

        event = Mock()
        event.event_type = "test"

        with pytest.raises(_kp_module.ProducerException):
            producer.produce_event("topic", event)


class TestKafkaDeliveryCallback:
    """Tests for KafkaProducer._delivery_callback."""

    def test_delivery_report_success(self):
        """Delivery callback logs debug on success."""
        logger = Mock()
        with patch.object(_kp_module, "logger", logger):
            mock_producer = MagicMock()
            mock_producer.topic.return_value = "orders"
            mock_producer.partition.return_value = 3

            # Create a producer instance just to get _delivery_callback
            with patch.object(_kp_module, "Producer"), \
                 patch.object(_kp_module, "JSONSerializer"), \
                 patch.object(_kp_module, "get_config", return_value=_make_mock_config()):
                kp = _kp_module.KafkaProducer()

            kp._delivery_callback(None, mock_producer)

        logger.debug.assert_called_once()
        log_kwargs = logger.debug.call_args[1]
        assert log_kwargs["topic"] == "orders"
        assert log_kwargs["partition"] == 3

    def test_delivery_report_failure(self):
        """Delivery callback logs error when err is present."""
        logger = Mock()
        with patch.object(_kp_module, "logger", logger):
            msg = Mock()
            msg.topic.return_value = "orders"

            with patch.object(_kp_module, "Producer"), \
                 patch.object(_kp_module, "JSONSerializer"), \
                 patch.object(_kp_module, "get_config", return_value=_make_mock_config()):
                kp = _kp_module.KafkaProducer()

            kp._delivery_callback("message timed out", msg)

        logger.error.assert_called_once()
        log_kwargs = logger.error.call_args[1]
        assert "timed out" in str(log_kwargs["error"])
        assert log_kwargs["topic"] == "orders"


class TestKafkaProducerFlushAndClose:
    """Tests for flush and close methods."""

    def test_producer_flush(self):
        """flush delegates to confluent producer.flush with timeout."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0
        logger = Mock()

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer"), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", logger):

            producer = _kp_module.KafkaProducer()
            producer.flush(timeout=5.0)

        mock_producer.flush.assert_called_once_with(5.0)
        logger.warning.assert_not_called()

    def test_producer_flush_incomplete_warns(self):
        """flush logs warning when some messages remain."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 5  # 5 messages remaining
        logger = Mock()

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer"), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", logger):

            producer = _kp_module.KafkaProducer()
            producer.flush(timeout=1.0)

        logger.warning.assert_called_once()
        log_kwargs = logger.warning.call_args[1]
        assert log_kwargs["remaining_messages"] == 5

    def test_producer_close(self):
        """close calls flush then logs closure."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0
        logger = Mock()

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer"), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", logger):

            producer = _kp_module.KafkaProducer()
            producer.close()

        mock_producer.flush.assert_called_once()
        # Find the "closed" info call among the log output
        close_calls = [c for c in logger.info.call_args_list if "closed" in str(c)]
        assert len(close_calls) == 1

    def test_producer_flush_default_timeout(self):
        """flush uses 10.0s timeout by default."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        with patch.object(_kp_module, "Producer", return_value=mock_producer), \
             patch.object(_kp_module, "JSONSerializer"), \
             patch.object(_kp_module, "get_config", return_value=_make_mock_config()), \
             patch.object(_kp_module, "logger", Mock()):

            producer = _kp_module.KafkaProducer()
            producer.flush()

        mock_producer.flush.assert_called_once_with(10.0)


class TestGetKafkaProducerSingleton:
    """Tests for the module-level get_kafka_producer singleton."""

    def test_get_kafka_producer_creates_singleton(self):
        """get_kafka_producer creates instance on first call."""
        with patch.object(_kp_module, "KafkaProducer") as mock_cls:
            _kp_module._kafka_producer = None
            result = _kp_module.get_kafka_producer()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value

    def test_get_kafka_producer_returns_same_instance(self):
        """Subsequent calls return the same singleton."""
        with patch.object(_kp_module, "KafkaProducer") as mock_cls:
            _kp_module._kafka_producer = None
            first = _kp_module.get_kafka_producer()
            second = _kp_module.get_kafka_producer()

        assert first is second
        assert mock_cls.call_count == 1
