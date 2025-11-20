"""Health check utilities."""
from typing import Dict, List, Callable, Any
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class HealthStatus(str, Enum):
    """Health check status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.details is None:
            self.details = {}


class HealthChecker:
    """Health checker for services and dependencies."""
    
    def __init__(self):
        """Initialize health checker."""
        self.checks: Dict[str, Callable] = {}
    
    def register_check(self, name: str, check_func: Callable) -> None:
        """
        Register a health check.
        
        Args:
            name: Name of the check
            check_func: Function that returns HealthCheckResult
        """
        self.checks[name] = check_func
    
    async def run_checks(self) -> Dict[str, HealthCheckResult]:
        """
        Run all registered health checks.
        
        Returns:
            Dictionary of check results
        """
        results = {}
        for name, check_func in self.checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                results[name] = result
            except Exception as e:
                results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}"
                )
        return results
    
    async def get_overall_status(self) -> HealthStatus:
        """
        Get overall system health status.
        
        Returns:
            Overall health status
        """
        results = await self.run_checks()
        
        if not results:
            return HealthStatus.HEALTHY
        
        statuses = [r.status for r in results.values()]
        
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY


# Import asyncio for async checks
import asyncio
