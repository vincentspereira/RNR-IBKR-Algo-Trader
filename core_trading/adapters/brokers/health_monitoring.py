"""Broker health monitoring -- ROADMAP MARKER (not implemented).

Cross-broker health checks, alerting, and diagnostics were planned here.
The canonical IBKR adapter (``core_trading.adapters.ibkr_adapter``)
implements its own ``health_check()`` and heartbeat loop.

When multiple brokers are added (see project-broker-roadmap memory), this
module can be revived as a shared monitoring layer.
"""

from __future__ import annotations

__all__ = ["HealthStatus"]


class HealthStatus:
    """Placeholder for shared broker health status. Not implemented."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
