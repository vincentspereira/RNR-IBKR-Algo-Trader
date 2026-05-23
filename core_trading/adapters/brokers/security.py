"""Broker security and authentication helpers -- ROADMAP MARKER (not implemented).

A shared security and credential-management layer for broker adapters was
planned here. The canonical IBKR adapter (``core_trading.adapters.ibkr_adapter``)
relies on TWS-managed sessions and reads credentials from environment
variables.

When multiple brokers are added (see project-broker-roadmap memory), this
module can be revived as a shared auth/credential layer.
"""

from __future__ import annotations

__all__ = ["AuthenticationType"]


class AuthenticationType:
    """Placeholder for shared broker authentication types. Not implemented."""

    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    TOKEN = "token"
