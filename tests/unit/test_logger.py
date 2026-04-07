"""Unit tests for the structured logging module.

All structlog and pythonjsonlogger dependencies are mocked so these
tests run without those packages installed.

Strategy:
  - structlog and pythonjsonlogger are mocked at sys.modules level so the
    source module can be imported without the real packages.
  - After importing, we use patch.object to replace module-level names
    (structlog, logging, get_logger, logger) for each test.
  - The source code accesses structlog.processors.X and structlog.dev.X
    as sub-attributes, which MagicMock auto-creates as separate objects.
"""

import sys
import os
import logging as real_logging
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# ---------------------------------------------------------------------------
# Pre-install mocks for structlog and pythonjsonlogger so the logger module
# can be imported even when those packages are not installed.
# ---------------------------------------------------------------------------
_mock_structlog = MagicMock()
sys.modules.setdefault("structlog", _mock_structlog)
sys.modules.setdefault("pythonjsonlogger", MagicMock())
sys.modules.setdefault("pythonjsonlogger.jsonlogger", MagicMock())

# Import the module under test
import libs.common.logging.logger as _logger_module


# ===================================================================
# Tests for configure_logging
# ===================================================================


class TestConfigureLogging:
    """Tests for the configure_logging function."""

    def test_configure_logging_json_renderer(self):
        """JSON format adds JSONRenderer to processors."""
        mock_structlog = MagicMock()
        with patch.object(_logger_module, "structlog", mock_structlog), \
             patch.object(_logger_module, "logging"):

            _logger_module.configure_logging(log_level="INFO", log_format="json")

        mock_structlog.configure.assert_called_once()
        cfg = mock_structlog.configure.call_args[1]
        processors = cfg["processors"]
        # The last processor should be structlog.processors.JSONRenderer()
        assert processors[-1] is mock_structlog.processors.JSONRenderer.return_value

    def test_configure_logging_text_renderer(self):
        """Text format adds ConsoleRenderer to processors."""
        mock_structlog = MagicMock()
        with patch.object(_logger_module, "structlog", mock_structlog), \
             patch.object(_logger_module, "logging"):

            _logger_module.configure_logging(log_level="INFO", log_format="text")

        cfg = mock_structlog.configure.call_args[1]
        processors = cfg["processors"]
        # Source uses structlog.dev.ConsoleRenderer() for text format
        assert processors[-1] is mock_structlog.dev.ConsoleRenderer.return_value

    def test_configure_logging_with_service_name(self):
        """When service_name is provided, CallsiteParameterAdder is inserted."""
        mock_structlog = MagicMock()
        with patch.object(_logger_module, "structlog", mock_structlog), \
             patch.object(_logger_module, "logging"):

            _logger_module.configure_logging(
                log_level="DEBUG", log_format="json", service_name="my_svc"
            )

        mock_structlog.processors.CallsiteParameterAdder.assert_called_once()

    def test_configure_logging_without_service_name(self):
        """When service_name is None, CallsiteParameterAdder is not added."""
        mock_structlog = MagicMock()
        with patch.object(_logger_module, "structlog", mock_structlog), \
             patch.object(_logger_module, "logging"):

            _logger_module.configure_logging(
                log_level="INFO", log_format="json", service_name=None
            )

        mock_structlog.processors.CallsiteParameterAdder.assert_not_called()

    def test_configure_logging_sets_structlog_factory(self):
        """structlog.configure is called with LoggerFactory and dict context."""
        mock_structlog = MagicMock()
        with patch.object(_logger_module, "structlog", mock_structlog), \
             patch.object(_logger_module, "logging"):

            _logger_module.configure_logging()

        cfg = mock_structlog.configure.call_args[1]
        assert cfg["context_class"] is dict
        assert cfg["cache_logger_on_first_use"] is True
        mock_structlog.stdlib.LoggerFactory.assert_called_once()

    def test_configure_logging_sets_log_level(self):
        """logging.basicConfig is called with the correct level."""
        mock_logging = MagicMock()
        # Wire up getattr so the source's getattr(logging, "WARNING") works
        mock_logging.WARNING = real_logging.WARNING
        mock_logging.INFO = real_logging.INFO
        mock_logging.DEBUG = real_logging.DEBUG
        mock_logging.ERROR = real_logging.ERROR
        mock_logging.CRITICAL = real_logging.CRITICAL

        with patch.object(_logger_module, "structlog", MagicMock()), \
             patch.object(_logger_module, "logging", mock_logging):

            _logger_module.configure_logging(log_level="WARNING")

        mock_logging.basicConfig.assert_called_once()
        basic_cfg = mock_logging.basicConfig.call_args[1]
        assert basic_cfg["level"] == real_logging.WARNING


# ===================================================================
# Tests for get_logger
# ===================================================================


class TestGetLogger:
    """Tests for the get_logger function."""

    def test_get_logger_returns_bound_logger(self):
        """get_logger returns a structlog BoundLogger."""
        mock_structlog = MagicMock()
        mock_logger = MagicMock()
        mock_structlog.get_logger.return_value = mock_logger

        with patch.object(_logger_module, "structlog", mock_structlog):
            result = _logger_module.get_logger("test_module")

        mock_structlog.get_logger.assert_called_once_with("test_module")
        assert result is mock_logger

    def test_get_logger_with_context(self):
        """When context kwargs are passed, they are bound to the logger."""
        mock_structlog = MagicMock()
        mock_logger = MagicMock()
        mock_bound = MagicMock()
        mock_logger.bind.return_value = mock_bound
        mock_structlog.get_logger.return_value = mock_logger

        with patch.object(_logger_module, "structlog", mock_structlog):
            result = _logger_module.get_logger("test_module", request_id="abc", user="bob")

        mock_logger.bind.assert_called_once_with(request_id="abc", user="bob")
        assert result is mock_bound

    def test_get_logger_without_context_does_not_bind(self):
        """When no context kwargs, bind is not called."""
        mock_structlog = MagicMock()
        mock_logger = MagicMock()
        mock_structlog.get_logger.return_value = mock_logger

        with patch.object(_logger_module, "structlog", mock_structlog):
            result = _logger_module.get_logger("test_module")

        mock_logger.bind.assert_not_called()
        assert result is mock_logger


# ===================================================================
# Tests for LoggerMixin
# ===================================================================


class TestLoggerMixin:
    """Tests for the LoggerMixin class."""

    def test_logger_mixin_provides_logger_property(self):
        """LoggerMixin classes get a .logger property."""
        mock_logger_inst = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger_inst)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            class MyService(_logger_module.LoggerMixin):
                pass

            svc = MyService()
            logger = svc.logger

        mock_get_logger.assert_called_once_with(
            "MyService", class_name="MyService"
        )
        assert logger is mock_logger_inst

    def test_logger_mixin_caches_logger(self):
        """The logger is cached after first access."""
        mock_logger_inst = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger_inst)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            class MyService(_logger_module.LoggerMixin):
                pass

            svc = MyService()
            first = svc.logger
            second = svc.logger

        assert first is second
        assert mock_get_logger.call_count == 1


# ===================================================================
# Tests for log_function_call decorator
# ===================================================================


class TestLogFunctionCallDecorator:
    """Tests for the log_function_call sync decorator."""

    def test_logs_call_and_completion(self):
        """Decorator logs function_called and function_completed."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_function_call
            def add(a, b):
                return a + b

            result = add(1, 2)

        assert result == 3
        assert mock_logger.info.call_count == 2

        first_call = mock_logger.info.call_args_list[0]
        assert first_call[0][0] == "function_called"
        assert first_call[1]["function"] == "add"

        second_call = mock_logger.info.call_args_list[1]
        assert second_call[0][0] == "function_completed"
        assert second_call[1]["result"] == 3

    def test_logs_exception_and_reraises(self):
        """Decorator logs function_failed and re-raises the exception."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_function_call
            def boom():
                raise RuntimeError("explosion")

            with pytest.raises(RuntimeError, match="explosion"):
                boom()

        mock_logger.error.assert_called_once()
        err_call = mock_logger.error.call_args
        assert err_call[0][0] == "function_failed"
        assert err_call[1]["function"] == "boom"
        assert "explosion" in err_call[1]["error"]
        assert err_call[1]["exc_info"] is True

    def test_passes_args_and_kwargs_to_log(self):
        """Decorator logs the original args and kwargs."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_function_call
            def fn(x, y=10):
                return x + y

            fn(5, y=20)

        first_call = mock_logger.info.call_args_list[0]
        assert first_call[1]["args"] == (5,)
        assert first_call[1]["kwargs"] == {"y": 20}


# ===================================================================
# Tests for log_async_function_call decorator
# ===================================================================


class TestLogAsyncFunctionCallDecorator:
    """Tests for the log_async_function_call async decorator."""

    @pytest.mark.asyncio
    async def test_logs_async_call_and_completion(self):
        """Async decorator logs async_function_called and async_function_completed."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_async_function_call
            async def async_add(a, b):
                return a + b

            result = await async_add(3, 4)

        assert result == 7
        assert mock_logger.info.call_count == 2

        first_call = mock_logger.info.call_args_list[0]
        assert first_call[0][0] == "async_function_called"
        assert first_call[1]["function"] == "async_add"

        second_call = mock_logger.info.call_args_list[1]
        assert second_call[0][0] == "async_function_completed"
        assert second_call[1]["result"] == 7

    @pytest.mark.asyncio
    async def test_logs_async_exception_and_reraises(self):
        """Async decorator logs async_function_failed and re-raises."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_async_function_call
            async def async_boom():
                raise ValueError("async-kaboom")

            with pytest.raises(ValueError, match="async-kaboom"):
                await async_boom()

        mock_logger.error.assert_called_once()
        err_call = mock_logger.error.call_args
        assert err_call[0][0] == "async_function_failed"
        assert err_call[1]["function"] == "async_boom"
        assert "async-kaboom" in err_call[1]["error"]

    @pytest.mark.asyncio
    async def test_passes_async_args_and_kwargs(self):
        """Async decorator logs args and kwargs."""
        mock_logger = MagicMock()
        mock_get_logger = MagicMock(return_value=mock_logger)

        with patch.object(_logger_module, "get_logger", mock_get_logger):
            @_logger_module.log_async_function_call
            async def greet(name, greeting="hello"):
                return f"{greeting} {name}"

            await greet("world", greeting="hi")

        first_call = mock_logger.info.call_args_list[0]
        assert first_call[1]["args"] == ("world",)
        assert first_call[1]["kwargs"] == {"greeting": "hi"}


# ===================================================================
# Tests for logger with context / correlation_id patterns
# ===================================================================


class TestLoggerContextBinding:
    """Tests that verify context binding and structured logging patterns."""

    def test_structured_logging_with_correlation_id(self):
        """Simulate a correlation-id being bound to the logger."""
        mock_structlog = MagicMock()
        mock_logger = MagicMock()
        mock_bound = MagicMock()
        mock_logger.bind.return_value = mock_bound
        mock_structlog.get_logger.return_value = mock_logger

        with patch.object(_logger_module, "structlog", mock_structlog):
            bound = _logger_module.get_logger("svc", correlation_id="corr-123")

        mock_logger.bind.assert_called_once_with(correlation_id="corr-123")
        assert bound is mock_bound

    def test_logger_bind_extra_fields(self):
        """Multiple fields can be bound to the logger."""
        mock_structlog = MagicMock()
        mock_logger = MagicMock()
        mock_bound = MagicMock()
        mock_logger.bind.return_value = mock_bound
        mock_structlog.get_logger.return_value = mock_logger

        with patch.object(_logger_module, "structlog", mock_structlog):
            bound = _logger_module.get_logger(
                "svc",
                environment="production",
                version="2.1.0",
                region="us-east-1",
            )

        mock_logger.bind.assert_called_once_with(
            environment="production",
            version="2.1.0",
            region="us-east-1",
        )
        assert bound is mock_bound
