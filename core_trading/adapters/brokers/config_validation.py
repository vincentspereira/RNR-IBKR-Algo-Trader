"""Broker configuration validation -- ROADMAP MARKER (not implemented).

A shared configuration-validation layer for broker adapters was planned
here. The canonical IBKR adapter (``core_trading.adapters.ibkr_adapter``)
validates its own configuration.

When multiple brokers are added (see project-broker-roadmap memory), this
module can be revived as a shared validation layer.
"""

from __future__ import annotations

__all__ = ["ValidationSeverity"]


class ValidationSeverity:
    """Placeholder for shared validation severity levels. Not implemented."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
