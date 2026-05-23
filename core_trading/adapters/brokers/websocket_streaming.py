"""Broker WebSocket streaming -- ROADMAP MARKER (not implemented).

A shared WebSocket streaming layer for broker market-data feeds was planned
here. The canonical IBKR data feed (``core_trading.data_feeds.ibkr_data_feed``)
uses ``ib_insync`` event streams directly and does not need this abstraction.

When multiple brokers are added (see project-broker-roadmap memory), this
module can be revived as a shared streaming layer.
"""

from __future__ import annotations

__all__ = ["WebSocketStream"]


class WebSocketStream:
    """Placeholder for shared broker WebSocket streaming. Not implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "WebSocketStream is a roadmap marker. Use "
            "core_trading.data_feeds.ibkr_data_feed for the canonical "
            "IBKR data feed."
        )
