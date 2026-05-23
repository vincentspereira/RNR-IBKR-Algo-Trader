"""Broker adapter package.

The canonical broker adapter is ``core_trading.adapters.ibkr_adapter.IBKRAdapter``
(located at the top of the ``adapters`` package, NOT here). The modules in
this subpackage are roadmap markers for planned multi-broker support and
are not implemented.

Currently importable from this package:
    - ``rate_limiting`` -- real implementation used by the IBKR data feed

All other modules (``alpaca``, ``binance``, ``coinbase``, ``fxcm``,
``interactive_brokers``, ``oanda``, ``trading212``, ``factory``,
``error_handling``, ``config_validation``, ``health_monitoring``,
``security``, ``websocket_streaming``) are placeholders that raise
``NotImplementedError`` when used. See ``README.md`` in this directory for
the multi-broker roadmap.
"""
