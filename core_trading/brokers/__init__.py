# from .alpaca_adapter import ()
# from .binance_adapter import ()
# from .coinbase_adapter import ()
# from .fxcm_adapter import ()
# from .ibkr_adapter import ()
# from .oanda_adapter import ()
# from .sharekhan_adapter import ()
# from .trading212_adapter import ()
# from .zerodha_adapter import ()

# Broker Integration Adapters for NautilusTrader Engine

# Comprehensive broker integration suite supporting institutional-grade trading:
# - Interactive Brokers (IBKR): Full TWS/Gateway integration with advanced order types
# ""- Alpaca: Commission-free API trading with WebSocket streaming"
# ""- Oanda: Advanced forex and CFD trading with REST API"
# ""- FXCM: Professional forex trading with comprehensive API"
# - Trading212: Multi-asset CFD trading platform
# - Zerodha Kite Connect: Indian market trading with WebSocket streaming
# - Sharekhan: Indian broker with multi-asset support
# - Coinbase Pro: Advanced cryptocurrency trading with WebSocket streaming
# - Binance: Multi-asset trading with spot, futures, and margin support
# - Abstract base classes for custom broker implementations
# - Unified interface for order management, market data, and portfolio sync
# - Risk management integration across all brokers
# - Multi-asset class support (equities, options, futures, forex, crypto, commodities)
# - Real-time P&L monitoring and position management
# - Compliance and regulatory reporting features

# All broker adapters include volume-weighting, smart money confirmation,
# multi-timeframe analysis, adaptive confidence scoring, and integrated risk management."


#     AlpacaAdapter,
#     AlpacaConnectionStatus,
#     AlpacaMarketData,
#     AlpacaOrder,
#     AlpacaOrderType,
#     AlpacaPosition,
#     AlpacaSecurityType,
# )
#     BinanceAccount,
#     BinanceAdapter,
#     BinanceConnectionStatus,
#     BinanceMarketData,
#     BinanceOrder,
#     BinanceOrderSide,
#     BinanceOrderStatus,
#     BinanceOrderType,
#     BinancePosition,
# )
#     CoinbaseAccount,
#     CoinbaseAdapter,
#     CoinbaseConnectionStatus,
#     CoinbaseMarketData,
#     CoinbaseOrder,
#     CoinbaseOrderSide,
#     CoinbaseOrderStatus,
#     CoinbaseOrderType,
#     CoinbasePosition,
# )
#     FXCMAccount,
#     FXCMAdapter,
#     FXCMConnectionStatus,
#     FXCMMarketData,
#     FXCMOrder,
#     FXCMOrderStatus,
#     FXCMOrderType,
#     FXCMPosition,
#     FXCMSecurityType,
# )
#     IBKRAdapter,
#     IBKRConnectionStatus,
#     IBKRMarketData,
#     IBKROrder,
#     IBKROrderType,
#     IBKRPosition,
#     IBKRSecurityType,
# )
#     OandaAccount,
#     OandaAdapter,
#     OandaConnectionStatus,
#     OandaMarketData,
#     OandaOrder,
#     OandaOrderType,
#     OandaPosition,
#     OandaSecurityType,
# )
#     SharekhanAccount,
#     SharekhanAdapter,
#     SharekhanConnectionStatus,
#     SharekhanExchange,
#     SharekhanMarketData,
#     SharekhanOrder,
#     SharekhanOrderStatus,
#     SharekhanOrderType,
#     SharekhanPosition,
#     SharekhanSecurityType,
# )
#     Trading212Account,
#     Trading212Adapter,
#     Trading212ConnectionStatus,
#     Trading212MarketData,
#     Trading212Order,
#     Trading212OrderStatus,
#     Trading212OrderType,
#     Trading212Position,
#     Trading212SecurityType,
# )
#     ZerodhaAccount,
#     ZerodhaAdapter,
#     ZerodhaConnectionStatus,
#     ZerodhaExchange,
#     ZerodhaMarketData,
#     ZerodhaOrder,
#     ZerodhaOrderStatus,
#     ZerodhaOrderType,
#     ZerodhaPosition,
#     ZerodhaSecurityType,
# )

# __all__ = [
    # IBKR Integration"
# "IBKRAdapter","
# "IBKRConnectionStatus","
# "IBKROrderType","
# "IBKRSecurityType","
# "IBKRPosition","
# "IBKROrder","
#     "IBKRMarketData",
    # Alpaca Integration"
# "AlpacaAdapter","
# "AlpacaConnectionStatus","
# "AlpacaOrderType","
# "AlpacaSecurityType","
# "AlpacaPosition","
# "AlpacaOrder","
#     "AlpacaMarketData",
    # Oanda Integration"
# "OandaAdapter","
# "OandaConnectionStatus","
# "OandaOrderType","
# "OandaSecurityType","
# "OandaPosition","
# "OandaOrder","
# "OandaMarketData","
#     "OandaAccount",
    # FXCM Integration"
# "FXCMAdapter","
# "FXCMConnectionStatus","
# "FXCMOrderType","
# "FXCMOrderStatus","
# "FXCMSecurityType","
# "FXCMPosition","
# "FXCMOrder","
# "FXCMMarketData","
#     "FXCMAccount",
    # Trading212 Integration"
# "Trading212Adapter","
# "Trading212ConnectionStatus","
# "Trading212OrderType","
# "Trading212OrderStatus","
# "Trading212SecurityType","
# "Trading212Position","
# "Trading212Order","
# "Trading212MarketData","
#     "Trading212Account",
    # Zerodha Integration"
# "ZerodhaAdapter","
# "ZerodhaConnectionStatus","
# "ZerodhaOrderType","
# "ZerodhaOrderStatus","
# "ZerodhaSecurityType","
# "ZerodhaExchange","
# "ZerodhaPosition","
# "ZerodhaOrder","
# "ZerodhaMarketData","
#     "ZerodhaAccount",
    # Sharekhan Integration"
# "SharekhanAdapter","
# "SharekhanConnectionStatus","
# "SharekhanOrderType","
# "SharekhanOrderStatus","
# "SharekhanSecurityType","
# "SharekhanExchange","
# "SharekhanPosition","
# "SharekhanOrder","
# "SharekhanMarketData","
#     "SharekhanAccount",
    # Coinbase Pro Integration"
# "CoinbaseAdapter","
# "CoinbaseConnectionStatus","
# "CoinbaseOrderType","
# "CoinbaseOrderStatus","
# "CoinbaseOrderSide","
# "CoinbasePosition","
# "CoinbaseOrder","
# "CoinbaseMarketData","
#     "CoinbaseAccount",
    # Binance Integration"
# "BinanceAdapter","
# "BinanceConnectionStatus","
# "BinanceOrderType","
# "BinanceOrderStatus","
# "BinanceOrderSide","
# "BinancePosition","
# "BinanceOrder","
# "BinanceMarketData","
#     "BinanceAccount",
# ]
# "