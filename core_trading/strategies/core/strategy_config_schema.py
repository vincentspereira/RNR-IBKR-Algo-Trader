"""Strategy configuration schema with validation."""

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class AssetClass(Enum):
    EQUITY = "EQUITY"
    FOREX = "FOREX"
    COMMODITY = "COMMODITY"
    CRYPTO = "CRYPTO"
    BOND = "BOND"
    OPTION = "OPTION"
    FUTURE = "FUTURE"
    ETF = "ETF"


class TimeFrame(Enum):
    TICK = "TICK"
    SECOND_1 = "1S"
    SECOND_5 = "5S"
    SECOND_15 = "15S"
    SECOND_30 = "30S"
    MINUTE_1 = "1M"
    MINUTE_5 = "5M"
    MINUTE_15 = "15M"
    MINUTE_30 = "30M"
    HOUR_1 = "1H"
    HOUR_4 = "4H"
    DAILY = "1D"
    WEEKLY = "1W"
    MONTHLY = "1MO"


class StrategyCategory(Enum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    VOLATILITY_BREAKOUT = "VOLATILITY_BREAKOUT"
    PAIRS_TRADING = "PAIRS_TRADING"
    ARBITRAGE = "ARBITRAGE"
    ADVANCED_TECHNICAL = "ADVANCED_TECHNICAL"
    ML_BASED = "ML_BASED"
    SEASONAL = "SEASONAL"
    NEWS_SENTIMENT = "NEWS_SENTIMENT"
    MULTI_FACTOR = "MULTI_FACTOR"


class PositionSizingMethod(Enum):
    FIXED_FRACTIONAL = "FIXED_FRACTIONAL"
    KELLY = "KELLY"
    VOLATILITY_ADJUSTED = "VOLATILITY_ADJUSTED"


class ExecutionAlgorithm(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"


class ExecutionUrgency(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TimeInForce(Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    DAY = "DAY"


@dataclass
class IndicatorConfig:
    """Configuration for technical indicators."""
    name: str
    parameters: Dict[str, Any]
    volume_weighted: bool = False
    smoothing_factor: Optional[float] = None
    lookback_period: Optional[int] = None


@dataclass
class SignalConfig:
    """Configuration for signal generation."""
    primary_indicators: List[IndicatorConfig]
    secondary_indicators: Optional[List[IndicatorConfig]] = None
    candlestick_patterns: Optional[List[str]] = None
    signal_threshold: float = 0.6
    confirmation_required: bool = True
    volume_confirmation: bool = False
    regime_filter: bool = True
    lookback_bars: int = 20


@dataclass
class RiskConfig:
    """Configuration for risk management."""
    position_sizing_method: PositionSizingMethod = PositionSizingMethod.FIXED_FRACTIONAL
    base_position_size: float = 0.02
    max_position_size: float = 0.1
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    max_drawdown_pct: float = 0.15
    var_confidence: float = 0.95
    correlation_threshold: float = 0.7
    leverage_limit: float = 1.0
    risk_free_rate: float = 0.02


@dataclass
class RegimeConfig:
    """Configuration for market regime detection."""
    enabled: bool = True
    detection_method: str = "VOLATILITY_REGIME"
    lookback_period: int = 252
    regime_threshold: float = 0.5
    adaptation_speed: float = 0.1
    regime_filters: Optional[Dict[str, bool]] = None

    def __post_init__(self):
        if self.regime_filters is None:
            self.regime_filters = {
                "BULL_MARKET": True,
                "BEAR_MARKET": True,
                "SIDEWAYS_MARKET": True,
                "HIGH_VOLATILITY": True,
                "LOW_VOLATILITY": True,
            }


@dataclass
class ExecutionConfig:
    """Configuration for execution logic."""
    default_algorithm: ExecutionAlgorithm = ExecutionAlgorithm.LIMIT
    default_urgency: ExecutionUrgency = ExecutionUrgency.MEDIUM
    default_time_in_force: TimeInForce = TimeInForce.GTC
    max_participation_rate: float = 0.1
    price_improvement_threshold: float = 0.0001
    slippage_tolerance: float = 0.001
    allow_partial_fills: bool = True
    min_fill_size: Optional[float] = None
    execution_delay_ms: int = 100
    smart_routing: bool = True
    dark_pool_preference: float = 0.3


@dataclass
class PerformanceConfig:
    """Configuration for performance tracking."""
    benchmark_symbol: Optional[str] = "SPY"
    track_intraday: bool = True
    calculate_attribution: bool = True
    risk_metrics_enabled: bool = True
    performance_frequency: str = "DAILY"
    rolling_window_days: int = 30
    save_trades: bool = True
    save_signals: bool = True
    export_format: str = "JSON"


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100000.0
    commission_per_trade: float = 1.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.001
    market_impact_model: str = "SQUARE_ROOT"
    transaction_cost_model: str = "FIXED_PLUS_PERCENTAGE"
    benchmark_comparison: bool = True
    monte_carlo_runs: int = 1000
    confidence_intervals: Optional[List[float]] = None

    def __post_init__(self):
        if self.confidence_intervals is None:
            self.confidence_intervals = [0.95, 0.99]


@dataclass
class StrategyConfig:
    """Complete strategy configuration."""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    category: StrategyCategory = StrategyCategory.MOMENTUM
    author: str = ""
    created_date: str = ""
    last_modified: str = ""

    asset_classes: List[AssetClass] = field(default_factory=lambda: [AssetClass.EQUITY])
    symbols: List[str] = field(default_factory=list)
    timeframes: List[TimeFrame] = field(default_factory=lambda: [TimeFrame.DAILY])
    primary_timeframe: TimeFrame = TimeFrame.DAILY

    signal_config: Optional[SignalConfig] = None
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    regime_config: RegimeConfig = field(default_factory=RegimeConfig)
    execution_config: ExecutionConfig = field(default_factory=ExecutionConfig)
    performance_config: PerformanceConfig = field(default_factory=PerformanceConfig)
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)
    strategy_parameters: Dict[str, Any] = field(default_factory=dict)

    enabled: bool = True
    live_trading_enabled: bool = False
    paper_trading_enabled: bool = True
    max_concurrent_positions: int = 10
    position_timeout_hours: Optional[int] = None

    log_level: str = "INFO"
    alert_conditions: Optional[Dict[str, Any]] = None
    notification_settings: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.alert_conditions is None:
            self.alert_conditions = {
                "max_drawdown_breach": True,
                "position_size_breach": True,
                "correlation_breach": True,
                "execution_failure": True,
            }
        if self.notification_settings is None:
            self.notification_settings = {
                "email_enabled": False,
                "sms_enabled": False,
                "webhook_enabled": False,
            }


class StrategyConfigValidator:
    """Validator for strategy configurations."""

    @staticmethod
    def get_json_schema() -> Dict[str, Any]:
        """Get JSON schema for strategy configuration validation."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "symbols": {"type": "array", "items": {"type": "string"}},
                "enabled": {"type": "boolean"},
                "signal_config": {"type": "object"},
                "risk_config": {"type": "object"},
                "backtest_config": {"type": "object"},
                "strategy_parameters": {"type": "object"},
            },
            "required": ["name", "version"],
        }

    @staticmethod
    def validate_config(config: Union[StrategyConfig, Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """Validate strategy configuration."""
        errors: List[str] = []

        if isinstance(config, StrategyConfig):
            config_dict = asdict(config)
        else:
            config_dict = config

        # Basic field validation
        if not config_dict.get("name"):
            errors.append("Strategy name is required")
        if not config_dict.get("version"):
            errors.append("Strategy version is required")

        # Risk parameter validation
        risk_cfg = config_dict.get("risk_config", {})
        if isinstance(risk_cfg, dict):
            base_size = risk_cfg.get("base_position_size", 0)
            max_size = risk_cfg.get("max_position_size", 1)
            if base_size > max_size:
                errors.append("Base position size cannot exceed maximum position size")

        return len(errors) == 0, errors

    @staticmethod
    def create_template_config(
        strategy_name: str,
        category: StrategyCategory = StrategyCategory.MOMENTUM,
    ) -> StrategyConfig:
        """Create a template configuration for a new strategy."""
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        return StrategyConfig(
            name=strategy_name,
            version="1.0.0",
            description=f"Template configuration for {strategy_name} strategy",
            category=category,
            author="Strategy Developer",
            created_date=today,
            last_modified=today,
            asset_classes=[AssetClass.EQUITY],
            symbols=["SPY", "QQQ", "IWM"],
            timeframes=[TimeFrame.DAILY, TimeFrame.HOUR_1],
            primary_timeframe=TimeFrame.DAILY,
            signal_config=SignalConfig(
                primary_indicators=[
                    IndicatorConfig(name="SMA", parameters={"period": 20}),
                    IndicatorConfig(name="RSI", parameters={"period": 14}, volume_weighted=True),
                ],
                signal_threshold=0.6,
            ),
            risk_config=RiskConfig(),
            regime_config=RegimeConfig(),
            execution_config=ExecutionConfig(),
            performance_config=PerformanceConfig(),
            backtest_config=BacktestConfig(start_date=start_date, end_date=today),
            strategy_parameters={"example_parameter": 1.0},
        )


def save_config_to_file(config: StrategyConfig, filepath: str) -> bool:
    """Save strategy configuration to JSON file."""
    try:
        config_dict = asdict(config)

        def convert_enums(obj):
            if isinstance(obj, dict):
                return {k: convert_enums(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_enums(item) for item in obj]
            elif isinstance(obj, Enum):
                return obj.value
            return obj

        config_dict = convert_enums(config_dict)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving configuration: {e}")
        return False


def load_config_from_file(filepath: str) -> Optional[StrategyConfig]:
    """Load strategy configuration from JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
        is_valid, errors = StrategyConfigValidator.validate_config(config_dict)
        if not is_valid:
            print(f"Configuration validation failed: {errors}")
            return None
        return StrategyConfig(**config_dict)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return None
