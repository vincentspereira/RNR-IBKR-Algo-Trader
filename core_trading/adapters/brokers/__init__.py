try:
    from .alpaca import AlpacaAdapter
except Exception:
    pass
try:
    from .binance import BinanceAdapter
except Exception:
    pass
try:
    from .coinbase import CoinbaseAdapter
except Exception:
    pass
# from .factory import ()
try:
    from .fxcm import FXCMAdapter
except Exception:
    pass
try:
    from .interactive_brokers import InteractiveBrokersAdapter
except Exception:
    pass
try:
    from .oanda import OandaAdapter
except Exception:
    pass
try:
    from .trading212 import Trading212Adapter
except Exception:
    pass

# Broker Adapters Module

# This module provides concrete implementations of broker adapters for various trading platforms.
# Each adapter implements the BaseBrokerAdapter interface and provides platform-specific
# functionality for order execution, account management, and position tracking.

# Supported Brokers:
# - Interactive Brokers (IBKR) - Primary broker for paper and live trading
# - Alpaca - Commission-free stock trading
# - Trading212 - European broker with stocks, ETFs, and CFDs
# - Binance - Global cryptocurrency exchange with spot and futures
# - FXCM - Forex and CFD trading platform
# - Oanda - Leading forex and CFD broker with competitive spreads
# - Coinbase - Trusted cryptocurrency exchange with advanced trading features

# Architecture:
# - All adapters follow the 5-pillar architecture compliance
# - Event-driven communication via Kafka
# - Comprehensive error handling and retry mechanisms
# - Real-time position and order status updates
# - Support for both paper and live trading modes"


#     AssetClass,
#     BrokerCapabilities,
#     BrokerFactory,
#     BrokerInfo,
#     BrokerRegistry,
#     BrokerType,
#     broker_factory,
#     create_and_connect_broker,
#     create_broker_adapter,
#     get_brokers_for_asset_class,
#     get_brokers_for_region,
#     get_supported_brokers,
# )

# __all__ = ["
# "InteractiveBrokersAdapter","
# "AlpacaAdapter","
# "Trading212Adapter","
# "BinanceAdapter","
# "FXCMAdapter","
# "OandaAdapter","
# "CoinbaseAdapter","
# "BrokerFactory","
# "BrokerRegistry","
# "BrokerType","
# "AssetClass","
# "BrokerCapabilities","
# "BrokerInfo","
# "broker_factory","
# "create_broker_adapter","
# "create_and_connect_broker","
# "get_supported_brokers","
# "get_brokers_for_asset_class","
#     "get_brokers_for_region",
# ]
# "