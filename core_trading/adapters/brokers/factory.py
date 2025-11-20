import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union
from ..base import AdapterConfig, BaseBrokerAdapter, ConnectionStatus, HealthCheck
from .alpaca import AlpacaAdapter, AlpacaConfig
from .binance import BinanceAdapter, BinanceConfig
from .coinbase import CoinbaseAdapter, CoinbaseConfig
from .fxcm import FXCMAdapter, FXCMConfig
from .interactive_brokers import IBConfig, InteractiveBrokersAdapter
from .oanda import OandaAdapter, OandaConfig
from .trading212 import Trading212Adapter, Trading212Config
"Broker Factory Module"
# "
# This module provides a factory pattern implementation for creating and managing
# broker adapter instances. It supports dynamic broker selection, configuration
# management, and provides a unified interface for all supported brokers.
# "
# Features:
# - Dynamic broker adapter creation
# - Configuration validation and management
# - Broker capability discovery
# - Connection pooling and management
# - Health monitoring across all brokers
# - Failover and redundancy support"





# "

class BrokerType(Enum):""
# "Supported broker types
# "
#     INTERACTIVE_BROKERS = "interactive_brokers"
#     ALPACA = "alpaca"
#     TRADING212 = "trading212"
#     BINANCE = "binance"
#     FXCM = "fxcm"
#     OANDA = "oanda"
#     COINBASE = "coinbase"


# "

class AssetClass(Enum):""
# "Asset classes supported by brokers
# "
#     STOCKS = "stocks"
#     ETF = "etf"
#     OPTIONS = "options"
#     FUTURES = "futures"
#     FOREX = "forex"
#     CRYPTO = "crypto"
#     CFD = "cfd"
#     COMMODITIES = "commodities"


# "

# @dataclass
class BrokerCapabilities:""
#     "Broker capabilities and supported features"

#     asset_classes: List[AssetClass] = field(default_factory=list)
#     order_types: List[str] = field(default_factory=list)
#     paper_trading: bool = False
#     live_trading: bool = False
#     real_time_data: bool = False
#     historical_data: bool = False
#     options_chains: bool = False
#     margin_trading: bool = False
#     short_selling: bool = False
#     fractional_shares: bool = False
#     crypto_staking: bool = False
#     forex_leverage: bool = False
#     api_rate_limit: int = 100  # requests per minute
#     min_deposit: float = 0.0
#     supported_currencies: List[str] = field(default_factory=list)
#     regions: List[str] = field(default_factory=list)


# @dataclass
class BrokerInfo:""
#     "Broker information and metadata"

#     name: str
#     broker_type: BrokerType
#     adapter_class: Type[BaseBrokerAdapter]
#     config_class: Type[AdapterConfig]
# capabilities: BrokerCapabilities"
# description: str = "
# website: str = "
# documentation_url: str = "
# api_documentation: str = "
#     supported_regions: List[str] = field(default_factory=list)
#     regulatory_info: Dict[str, str] = field(default_factory=dict)


# "

class BrokerRegistry:""
#     "Registry of all supported brokers and their capabilities"

# _brokers: Dict[BrokerType, BrokerInfo] = {
# BrokerType.INTERACTIVE_BROKERS: BrokerInfo("
#             name="Interactive Brokers",
#             broker_type=BrokerType.INTERACTIVE_BROKERS,
#             adapter_class=InteractiveBrokersAdapter,
#             config_class=IBConfig,
# capabilities=BrokerCapabilities(
# asset_classes=[
#                     AssetClass.STOCKS,
#                     AssetClass.ETF,
#                     AssetClass.OPTIONS,
#                     AssetClass.FUTURES,
#                     AssetClass.FOREX,
#                     AssetClass.CFD,
# ],
# order_types=["
# "MARKET","
# "LIMIT","
# "STOP","
# "STOP_LIMIT","
# "TRAIL","
#                     "BRACKET",
# ],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 options_chains=True,
#                 margin_trading=True,
#                 short_selling=True,
#                 forex_leverage=True,
#                 api_rate_limit=50,
#                 min_deposit=0.0,  # Paper trading""
# supported_currencies=["USD", "EUR", "GBP", "CAD", "AUD", "JPY"],"
#                 regions=["US", "EU", "ASIA"],
# ),"
# description="Professional trading platform with global market access","
# website="https://www.interactivebrokers.com","
# supported_regions=["Global"],"
#             regulatory_info={"US": "SEC, FINRA", "EU": "FCA, BaFin"},
# ),
# BrokerType.ALPACA: BrokerInfo("
#             name="Alpaca",
#             broker_type=BrokerType.ALPACA,
#             adapter_class=AlpacaAdapter,
#             config_class=AlpacaConfig,
# capabilities=BrokerCapabilities(
# asset_classes=[AssetClass.STOCKS, AssetClass.ETF, AssetClass.CRYPTO],"
#                 order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAIL"],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 fractional_shares=True,
#                 api_rate_limit=200,
# min_deposit=0.0,"
# supported_currencies=["USD"],"
#                 regions=["US"],
# ),"
# description="Commission-free stock and crypto trading","
# website="https://alpaca.markets","
# supported_regions=["US"],"
#             regulatory_info={"US": "SEC, FINRA"},
# ),
# BrokerType.TRADING212: BrokerInfo("
#             name="Trading212",
#             broker_type=BrokerType.TRADING212,
#             adapter_class=Trading212Adapter,
#             config_class=Trading212Config,
# capabilities=BrokerCapabilities(
# asset_classes=[AssetClass.STOCKS, AssetClass.ETF, AssetClass.CFD],"
#                 order_types=["MARKET", "LIMIT", "STOP"],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 fractional_shares=True,
#                 margin_trading=True,
#                 api_rate_limit=60,
# min_deposit=1.0,"
# supported_currencies=["EUR", "GBP", "USD"],"
#                 regions=["EU", "UK"],
# ),"
# description="European broker with stocks, ETFs, and CFDs","
# website="https://www.trading212.com","
# supported_regions=["EU", "UK"],"
#             regulatory_info={"EU": "CySEC", "UK": "FCA"},
# ),
# BrokerType.BINANCE: BrokerInfo("
#             name="Binance",
#             broker_type=BrokerType.BINANCE,
#             adapter_class=BinanceAdapter,
#             config_class=BinanceConfig,
# capabilities=BrokerCapabilities(
#                 asset_classes=[AssetClass.CRYPTO, AssetClass.FUTURES],
# order_types=["
# "MARKET","
# "LIMIT","
# "STOP_LOSS","
# "STOP_LOSS_LIMIT","
#                     "TAKE_PROFIT",
# ],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 margin_trading=True,
#                 crypto_staking=True,
#                 api_rate_limit=1200,
# min_deposit=10.0,"
# supported_currencies=["USDT", "BTC", "ETH", "BNB", "BUSD"],"
#                 regions=["Global"],
# ),"
# description="Global cryptocurrency exchange with spot and futures","
# website="https://www.binance.com","
# supported_regions=["Global"],"
#             regulatory_info={"Global": "Various jurisdictions"},
# ),
# BrokerType.FXCM: BrokerInfo("
#             name="FXCM",
#             broker_type=BrokerType.FXCM,
#             adapter_class=FXCMAdapter,
#             config_class=FXCMConfig,
# capabilities=BrokerCapabilities(
# asset_classes=[
#                     AssetClass.FOREX,
#                     AssetClass.CFD,
#                     AssetClass.COMMODITIES,
# ],"
#                 order_types=["MARKET", "ENTRY", "STOP", "LIMIT"],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 margin_trading=True,
#                 forex_leverage=True,
#                 api_rate_limit=100,
# min_deposit=50.0,"
# supported_currencies=["USD", "EUR", "GBP", "JPY", "AUD", "CAD"],"
#                 regions=["Global"],
# ),"
# description="Forex and CFD trading platform","
# website="https://www.fxcm.com","
# supported_regions=["Global"],"
#             regulatory_info={"US": "CFTC, NFA", "UK": "FCA"},
# ),
# BrokerType.OANDA: BrokerInfo("
#             name="Oanda",
#             broker_type=BrokerType.OANDA,
#             adapter_class=OandaAdapter,
#             config_class=OandaConfig,
# capabilities=BrokerCapabilities(
# asset_classes=[
#                     AssetClass.FOREX,
#                     AssetClass.CFD,
#                     AssetClass.COMMODITIES,
# ],"
#                 order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAIL"],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 margin_trading=True,
#                 forex_leverage=True,
#                 api_rate_limit=120,
# min_deposit=0.0,"
# supported_currencies=["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF"],"
#                 regions=["Global"],
# ),"
# description="Leading forex and CFD broker with competitive spreads","
# website="https://www.oanda.com","
# supported_regions=["Global"],"
#             regulatory_info={"US": "CFTC, NFA", "UK": "FCA", "EU": "ESMA"},
# ),
# BrokerType.COINBASE: BrokerInfo("
#             name="Coinbase",
#             broker_type=BrokerType.COINBASE,
#             adapter_class=CoinbaseAdapter,
#             config_class=CoinbaseConfig,
# capabilities=BrokerCapabilities(
# asset_classes=[AssetClass.CRYPTO],"
#                 order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
#                 paper_trading=True,
#                 live_trading=True,
#                 real_time_data=True,
#                 historical_data=True,
#                 api_rate_limit=10,
# min_deposit=1.0,"
# supported_currencies=["USD", "EUR", "GBP"],"
#                 regions=["US", "EU"],
# ),"
# description="Trusted cryptocurrency exchange with advanced trading features","
# website="https://www.coinbase.com","
# supported_regions=["US", "EU"],"
#             regulatory_info={"US": "SEC, CFTC", "EU": "Various jurisdictions"},
# ),
# }

#     @classmethod
#     def get_broker_info(cls, broker_type: BrokerType):
#         "Get broker information"
#         return cls._brokers.get(broker_type)

#     @classmethod
#     def get_all_brokers(cls):
#         "Get all registered brokers"
#         return cls._brokers.copy()

#     @classmethod
#     def get_brokers_by_asset_class(cls, asset_class: AssetClass):
#         "Get brokers that support a specific asset class"
#         return [
#             broker_info
#             for broker_info in cls._brokers.values()
#             if asset_class in broker_info.capabilities.asset_classes
# ]

#     @classmethod
#     def get_brokers_by_region(cls, region: str):
#         "Get brokers available in a specific region"
#         return [
#             broker_info
#             for broker_info in cls._brokers.values()
#             if region in broker_info.supported_regions""
# or "Global" in broker_info.supported_regions
# ]


class BrokerFactory:""
#     "Factory for creating and managing broker adapters"

#     def __init__(self):
#         self.logger = logging.getLogger(self.__class__.__name__)
#         self._active_adapters: Dict[str, BaseBrokerAdapter] = {}
#         self._adapter_configs: Dict[str, AdapterConfig] = {}

#     async def create_adapter(
#         self,
# broker_type: BrokerType,
# config: AdapterConfig,
#         adapter_id: Optional[str] = None,
# ) -> Optional[BaseBrokerAdapter]:"
#         "Create a broker adapter instance"
#         try:
#             broker_info = BrokerRegistry.get_broker_info(broker_type)
#             if not broker_info:""
#                 self.logger.error(f"Unsupported broker type: {broker_type}")
#                 return None

            # Validate config type
#             if not isinstance(config, broker_info.config_class):
#                 self.logger.error(""
#                     f"Invalid config type for {broker_type}. Expected {broker_info.config_class}"
# )
#                 return None

            # Create adapter instance
#             adapter = broker_info.adapter_class(config)

            # Generate adapter ID if not provided
#             if not adapter_id:
# adapter_id = ("
#                     f"{broker_type.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
# )

            # Store adapter and config
#             self._active_adapters[adapter_id] = adapter
#             self._adapter_configs[adapter_id] = config

#             self.logger.info(""
#                 f"Created {broker_type.value} adapter with ID: {adapter_id}"
# )
#             return adapter

#         except Exception as e:""
#             self.logger.error(f"Failed to create {broker_type.value} adapter: {e}")
#             return None

#     async def connect_adapter(self, adapter_id: str):
#         "Connect a broker adapter"
#         try:
#             adapter = self._active_adapters.get(adapter_id)
#             if not adapter:""
#                 self.logger.error(f"Adapter not found: {adapter_id}")
#                 return False

#             success = await adapter.connect()
#             if success:""
#                 self.logger.info(f"Connected adapter: {adapter_id}")
#             else:""
#                 self.logger.error(f"Failed to connect adapter: {adapter_id}")

#             return success

#         except Exception as e:""
#             self.logger.error(f"Error connecting adapter {adapter_id}: {e}")
#             return False

#     async def disconnect_adapter(self, adapter_id: str):
#         "Disconnect a broker adapter"
#         try:
#             adapter = self._active_adapters.get(adapter_id)
#             if not adapter:""
#                 self.logger.error(f"Adapter not found: {adapter_id}")
#                 return False

#             success = await adapter.disconnect()
#             if success:""
#                 self.logger.info(f"Disconnected adapter: {adapter_id}")

#             return success

#         except Exception as e:""
#             self.logger.error(f"Error disconnecting adapter {adapter_id}: {e}")
#             return False

#     async def remove_adapter(self, adapter_id: str):
#         "Remove a broker adapter"
#         try:
            # Disconnect first
#             await self.disconnect_adapter(adapter_id)

            # Remove from storage
#             if adapter_id in self._active_adapters:
#                 del self._active_adapters[adapter_id]
#             if adapter_id in self._adapter_configs:
#                 del self._adapter_configs[adapter_id]
# "
#             self.logger.info(f"Removed adapter: {adapter_id}")
#             return True

#         except Exception as e:""
#             self.logger.error(f"Error removing adapter {adapter_id}: {e}")
#             return False

#     def get_adapter(self, adapter_id: str):
#         "Get a broker adapter by ID"
#         return self._active_adapters.get(adapter_id)

#     def get_all_adapters(self):
#         "Get all active adapters"
#         return self._active_adapters.copy()

#     async def health_check_all(self):
#         "Perform health check on all adapters"
#         health_results = {}

#         for adapter_id, adapter in self._active_adapters.items():
#             try:
#                 health_check = await adapter.health_check()
#                 health_results[adapter_id] = health_check
#             except Exception as e:
# health_results[adapter_id] = HealthCheck(
#                     status=ConnectionStatus.ERROR,
#                     timestamp=datetime.now(),
#                     error_message=str(e),
# )

#         return health_results

#     async def get_adapters_by_asset_class(
# self, asset_class: AssetClass
# ) -> List[BaseBrokerAdapter]:"
#         "Get connected adapters that support a specific asset class"
#         suitable_adapters = []

#         for adapter_id, adapter in self._active_adapters.items():
            # Get broker type from adapter
#             broker_type = None
#             for bt, broker_info in BrokerRegistry.get_all_brokers().items():
#                 if isinstance(adapter, broker_info.adapter_class):
#                     broker_type = bt
#                     break

#             if broker_type:
#                 broker_info = BrokerRegistry.get_broker_info(broker_type)
#                 if (
#                     broker_info
# and asset_class in broker_info.capabilities.asset_classes
# ):
                    # Check if adapter is connected
#                     health_check = await adapter.health_check()
#                     if health_check.status == ConnectionStatus.CONNECTED:
#                         suitable_adapters.append(adapter)

#         return suitable_adapters

#     def get_broker_capabilities(
# self, broker_type: BrokerType
# ) -> Optional[BrokerCapabilities]:"
#         "Get capabilities for a specific broker type"
#         broker_info = BrokerRegistry.get_broker_info(broker_type)
#         return broker_info.capabilities if broker_info else None

#     async def create_and_connect_adapter(
#         self,
# broker_type: BrokerType,
# config: AdapterConfig,
#         adapter_id: Optional[str] = None,
# ) -> Optional[BaseBrokerAdapter]:"
#         "Create and connect a broker adapter in one step"
#         adapter = await self.create_adapter(broker_type, config, adapter_id)
#         if adapter:
            # Get the actual adapter ID used
#             actual_adapter_id = None
#             for aid, adp in self._active_adapters.items():
#                 if adp is adapter:
#                     actual_adapter_id = aid
#                     break

#             if actual_adapter_id:
#                 success = await self.connect_adapter(actual_adapter_id)
#                 if success:
#                     return adapter
#                 else:
                    # Clean up on connection failure
#                     await self.remove_adapter(actual_adapter_id)

#         return None

#     async def shutdown_all(self):
#         "Shutdown all adapters"
#         self.logger.info("Shutting down all broker adapters")

        # Disconnect all adapters
# disconnect_tasks = [
#             self.disconnect_adapter(adapter_id)
#             for adapter_id in list(self._active_adapters.keys())
# ]

#         if disconnect_tasks:
#             await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        # Clear all adapters
#         self._active_adapters.clear()
#         self._adapter_configs.clear()
# "
#         self.logger.info("All broker adapters shut down")


# Global factory instance
broker_factory = BrokerFactory()


# Convenience functions
# async def create_broker_adapter(
# broker_type: BrokerType, config: AdapterConfig, adapter_id: Optional[str] = None
# ) -> Optional[BaseBrokerAdapter]:"
#     "Create a broker adapter using the global factory"
#     return await broker_factory.create_adapter(broker_type, config, adapter_id)


# async def create_and_connect_broker(
# broker_type: BrokerType, config: AdapterConfig, adapter_id: Optional[str] = None
# ) -> Optional[BaseBrokerAdapter]:"
#     "Create and connect a broker adapter using the global factory"
#     return await broker_factory.create_and_connect_adapter(
#         broker_type, config, adapter_id
# )


# def get_supported_brokers():
#     "Get all supported brokers"
#     return BrokerRegistry.get_all_brokers()


# def get_brokers_for_asset_class(asset_class: AssetClass):
#     "Get brokers that support a specific asset class"
#     return BrokerRegistry.get_brokers_by_asset_class(asset_class)


# def get_brokers_for_region(region: str):
#     "Get brokers available in a specific region"
#     return BrokerRegistry.get_brokers_by_region(region)
# "'"'