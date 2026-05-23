"""Broker error-handling helpers -- ROADMAP MARKER (not implemented).

Standardized error handling, retry mechanisms, and severity classification
for broker adapters were planned here. The original implementation was
heavily commented and never functional; the canonical IBKR adapter
(``core_trading.adapters.ibkr_adapter``) does its own error handling.

When multiple brokers are added (see project-broker-roadmap memory), this
module can be revived as a shared error-handling layer.
"""

from __future__ import annotations

__all__ = ["ErrorSeverity"]


class ErrorSeverity:
    """Placeholder for shared broker error severity. Not implemented."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
