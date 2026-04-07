"""Test suite for health monitoring module."""

import sys
import os
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


class TestHealthStatusEnum:
    """Test HealthStatus enum."""

    def test_health_status_enum_values(self):
        from libs.common.monitoring.health import HealthStatus
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_health_status_string_comparison(self):
        from libs.common.monitoring.health import HealthStatus
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"

    def test_health_status_all_members(self):
        from libs.common.monitoring.health import HealthStatus
        members = list(HealthStatus)
        assert len(members) == 3


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_health_check_result_creation(self):
        from libs.common.monitoring.health import HealthCheckResult, HealthStatus
        result = HealthCheckResult(
            name="test_check",
            status=HealthStatus.HEALTHY,
            message="All good"
        )
        assert result.name == "test_check"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All good"
        assert result.details == {}
        assert isinstance(result.timestamp, datetime)

    def test_health_check_result_with_details(self):
        from libs.common.monitoring.health import HealthCheckResult, HealthStatus
        details = {"latency_ms": 50, "uptime_seconds": 3600}
        result = HealthCheckResult(
            name="api_check",
            status=HealthStatus.DEGRADED,
            message="High latency",
            details=details
        )
        assert result.details == details

    def test_health_check_result_with_custom_timestamp(self):
        from libs.common.monitoring.health import HealthCheckResult, HealthStatus
        ts = datetime(2026, 1, 1, 12, 0, 0)
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="ok",
            timestamp=ts
        )
        assert result.timestamp == ts

    def test_health_check_result_post_init_sets_defaults(self):
        from libs.common.monitoring.health import HealthCheckResult, HealthStatus
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="ok"
        )
        assert result.timestamp is not None
        assert result.details == {}

    def test_health_status_response_format(self):
        from libs.common.monitoring.health import HealthCheckResult, HealthStatus
        result = HealthCheckResult(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message="Connection refused",
            details={"host": "localhost", "port": 5432}
        )
        # Verify all fields are accessible and serializable
        assert isinstance(result.name, str)
        assert isinstance(result.status, HealthStatus)
        assert isinstance(result.message, str)
        assert isinstance(result.details, dict)
        assert isinstance(result.timestamp, datetime)


class TestHealthChecker:
    """Test HealthChecker class."""

    def test_health_check_register_component(self):
        from libs.common.monitoring.health import HealthChecker
        checker = HealthChecker()
        check_fn = Mock()
        checker.register_check("database", check_fn)
        assert "database" in checker.checks
        assert checker.checks["database"] is check_fn

    def test_health_check_register_multiple(self):
        from libs.common.monitoring.health import HealthChecker
        checker = HealthChecker()
        checker.register_check("db", Mock())
        checker.register_check("redis", Mock())
        checker.register_check("kafka", Mock())
        assert len(checker.checks) == 3

    @pytest.mark.asyncio
    async def test_run_checks_sync_callback(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        def sync_check():
            return HealthCheckResult(
                name="sync_service",
                status=HealthStatus.HEALTHY,
                message="OK"
            )

        checker.register_check("sync_service", sync_check)
        results = await checker.run_checks()

        assert "sync_service" in results
        assert results["sync_service"].status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_run_checks_async_callback(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        async def async_check():
            return HealthCheckResult(
                name="async_service",
                status=HealthStatus.HEALTHY,
                message="OK"
            )

        checker.register_check("async_service", async_check)
        results = await checker.run_checks()

        assert "async_service" in results
        assert results["async_service"].status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        def check_a():
            return HealthCheckResult(name="a", status=HealthStatus.HEALTHY, message="ok")

        def check_b():
            return HealthCheckResult(name="b", status=HealthStatus.HEALTHY, message="ok")

        checker.register_check("a", check_a)
        checker.register_check("b", check_b)

        status = await checker.get_overall_status()
        assert status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_component_down(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        def healthy_check():
            return HealthCheckResult(name="good", status=HealthStatus.HEALTHY, message="ok")

        def down_check():
            return HealthCheckResult(name="bad", status=HealthStatus.UNHEALTHY, message="down")

        checker.register_check("good", healthy_check)
        checker.register_check("bad", down_check)

        status = await checker.get_overall_status()
        assert status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        from libs.common.monitoring.health import HealthChecker, HealthStatus
        checker = HealthChecker()

        async def slow_check():
            await asyncio.sleep(10)
            from libs.common.monitoring.health import HealthCheckResult
            return HealthCheckResult(name="slow", status=HealthStatus.HEALTHY, message="ok")

        checker.register_check("slow", slow_check)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(checker.run_checks(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_health_check_exception_returns_unhealthy(self):
        from libs.common.monitoring.health import HealthChecker, HealthStatus
        checker = HealthChecker()

        def failing_check():
            raise RuntimeError("Service unavailable")

        checker.register_check("failing", failing_check)
        results = await checker.run_checks()

        assert "failing" in results
        assert results["failing"].status == HealthStatus.UNHEALTHY
        assert "Service unavailable" in results["failing"].message

    @pytest.mark.asyncio
    async def test_health_check_async_exception_returns_unhealthy(self):
        from libs.common.monitoring.health import HealthChecker, HealthStatus
        checker = HealthChecker()

        async def failing_async_check():
            raise ConnectionError("Connection refused")

        checker.register_check("failing_async", failing_async_check)
        results = await checker.run_checks()

        assert "failing_async" in results
        assert results["failing_async"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_get_overall_status_empty_checks(self):
        from libs.common.monitoring.health import HealthChecker, HealthStatus
        checker = HealthChecker()
        status = await checker.get_overall_status()
        assert status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_get_overall_status_degraded(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        def healthy():
            return HealthCheckResult(name="h", status=HealthStatus.HEALTHY, message="ok")

        def degraded():
            return HealthCheckResult(name="d", status=HealthStatus.DEGRADED, message="slow")

        checker.register_check("h", healthy)
        checker.register_check("d", degraded)

        status = await checker.get_overall_status()
        assert status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_get_overall_status_unhealthy_overrides_degraded(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        def degraded():
            return HealthCheckResult(name="d", status=HealthStatus.DEGRADED, message="slow")

        def unhealthy():
            return HealthCheckResult(name="u", status=HealthStatus.UNHEALTHY, message="down")

        checker.register_check("d", degraded)
        checker.register_check("u", unhealthy)

        status = await checker.get_overall_status()
        assert status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_mixed_statuses(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        for i, status in enumerate([HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]):
            s = status
            checker.register_check(f"check_{i}", lambda s=s: HealthCheckResult(
                name=f"check_{i}", status=s, message="msg"
            ))

        results = await checker.run_checks()
        assert len(results) == 3
        assert any(r.status == HealthStatus.HEALTHY for r in results.values())
        assert any(r.status == HealthStatus.DEGRADED for r in results.values())
        assert any(r.status == HealthStatus.UNHEALTHY for r in results.values())

    @pytest.mark.asyncio
    async def test_liveness_with_all_healthy(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()
        checker.register_check("app", lambda: HealthCheckResult(
            name="app", status=HealthStatus.HEALTHY, message="alive"
        ))
        status = await checker.get_overall_status()
        assert status != HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_readiness_with_degraded_is_not_ready(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()
        checker.register_check("db", lambda: HealthCheckResult(
            name="db", status=HealthStatus.DEGRADED, message="slow"
        ))
        status = await checker.get_overall_status()
        # Degraded means not fully ready
        assert status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_run_checks_returns_dict_of_results(self):
        from libs.common.monitoring.health import HealthChecker, HealthCheckResult, HealthStatus
        checker = HealthChecker()

        checker.register_check("svc1", lambda: HealthCheckResult(
            name="svc1", status=HealthStatus.HEALTHY, message="ok"
        ))
        checker.register_check("svc2", lambda: HealthCheckResult(
            name="svc2", status=HealthStatus.HEALTHY, message="ok"
        ))

        results = await checker.run_checks()
        assert isinstance(results, dict)
        assert all(isinstance(r, HealthCheckResult) for r in results.values())
