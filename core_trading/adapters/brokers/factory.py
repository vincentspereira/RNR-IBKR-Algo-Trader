"""Broker factory -- ROADMAP MARKER (not implemented).

A factory that dispatched to multiple broker adapters was planned here.
While there is only one canonical broker (IBKR), there is nothing to
dispatch and the factory is unnecessary. Calling code should construct
``core_trading.adapters.ibkr_adapter.IBKRAdapter`` directly.

When multiple brokers are added (see project-broker-roadmap memory), this
factory can be revived to provide a unified entry point.
"""

from __future__ import annotations

from enum import Enum


__all__ = ["BrokerType", "AssetClass", "BrokerFactory"]


class BrokerType(Enum):
    """Roadmap-only enumeration of planned broker integrations."""

    INTERACTIVE_BROKERS = "interactive_brokers"
    ALPACA = "alpaca"
    BINANCE = "binance"
    COINBASE = "coinbase"
    OANDA = "oanda"
    FXCM = "fxcm"
    TRADING212 = "trading212"


class AssetClass(Enum):
    """Roadmap-only enumeration of supported asset classes."""

    STOCKS = "stocks"
    ETF = "etf"
    OPTIONS = "options"
    FUTURES = "futures"
    FOREX = "forex"
    CRYPTO = "crypto"
    CFD = "cfd"
    COMMODITIES = "commodities"


class BrokerFactory:
    """Placeholder factory. Construct IBKRAdapter directly instead."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "BrokerFactory is a roadmap marker. Construct "
            "core_trading.adapters.ibkr_adapter.IBKRAdapter directly. "
            "See project-broker-roadmap memory for plans."
        )
