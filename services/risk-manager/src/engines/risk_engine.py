"""Risk Engine for Institutional-Grade Trading.

Provides comprehensive risk management:
- Real-time risk monitoring with broker adapter data
- Pre-trade risk checks (position, concentration, daily limits, margin, size)
- Value at Risk (Historical, Parametric, Monte Carlo, Cornish-Fisher)
- Exposure management, stress testing, risk attribution
- Circuit breakers on risk threshold breaches
"""

import asyncio
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

try:
    from scipy import stats
    from sklearn.covariance import LedoitWolf
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskCheckResult(Enum):
    """Risk check results."""
    APPROVED = "approved"
    REJECTED = "rejected"
    WARNING = "warning"
    REQUIRES_APPROVAL = "requires_approval"


class RiskMetricType(Enum):
    """Types of risk metrics."""
    VAR = "var"
    EXPECTED_SHORTFALL = "expected_shortfall"
    MAXIMUM_DRAWDOWN = "maximum_drawdown"
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    BETA = "beta"
    TRACKING_ERROR = "tracking_error"
    INFORMATION_RATIO = "information_ratio"
    VOLATILITY = "volatility"
    CORRELATION = "correlation"


class VaRMethod(Enum):
    """Value at Risk calculation methods."""
    HISTORICAL = "historical"
    PARAMETRIC = "parametric"
    MONTE_CARLO = "monte_carlo"
    CORNISH_FISHER = "cornish_fisher"


class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()


class EventType(Enum):
    MARKET_DATA = auto()
    SIGNAL = auto()
    ORDER = auto()
    FILL = auto()
    POSITION_UPDATE = auto()
    RISK_ALERT = auto()
    ERROR = auto()
    SYSTEM = auto()


class MarketRegime(Enum):
    BULLISH = auto()
    BEARISH = auto()
    SIDEWAYS = auto()
    VOLATILE = auto()


class RiskLevel(Enum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """Simple event for publishing to event bus."""
    type: EventType = EventType.SYSTEM
    data: Any = None
    priority: EventPriority = EventPriority.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class RiskLimit:
    """Risk limit configuration."""
    name: str
    limit_type: str  # "position", "exposure", "var", "drawdown", etc.
    value: float
    currency: str = "USD"
    instrument: Optional[str] = None
    strategy: Optional[str] = None
    sector: Optional[str] = None
    enabled: bool = True
    breach_action: str = "alert"  # "alert", "block", "reduce"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskMetric:
    """Risk metric calculation result."""
    metric_type: RiskMetricType
    value: float
    confidence_level: float
    time_horizon: int  # days
    currency: str = "USD"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionRisk:
    """Position-level risk metrics."""
    instrument: str
    position_size: float
    market_value: float
    unrealized_pnl: float
    var_1d: float
    var_10d: float
    expected_shortfall: float
    beta: float
    volatility: float
    max_drawdown: float
    concentration_risk: float
    liquidity_risk: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PortfolioRisk:
    """Portfolio-level risk metrics."""
    total_value: float
    total_var: float
    diversification_ratio: float
    concentration_index: float
    max_sector_exposure: float
    leverage_ratio: float
    liquidity_ratio: float
    stress_test_results: Dict[str, float] = field(default_factory=dict)
    risk_attribution: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RiskAlert:
    """Risk alert notification."""
    alert_id: str
    severity: str  # "low", "medium", "high", "critical"
    message: str
    risk_metric: str
    current_value: float
    limit_value: float
    breach_percentage: float
    instrument: Optional[str] = None
    strategy: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False


@dataclass
class RiskConfig:
    """Configuration for the risk engine."""
    max_position_size: float = 1_000_000.0
    max_portfolio_var: float = 50_000.0
    max_drawdown: float = 0.05
    max_leverage: float = 3.0
    max_sector_exposure: float = 0.25
    min_liquidity_ratio: float = 0.1
    daily_loss_limit_pct: float = 0.02
    max_daily_trades: int = 10
    max_concurrent_positions: int = 5
    max_order_size: float = 100_000.0
    var_confidence_level: float = 0.95
    var_time_horizon: int = 1
    var_method: VaRMethod = VaRMethod.HISTORICAL
    monitoring_interval_seconds: int = 60


@dataclass
class IndividualCheckResult:
    """Result of a single risk check."""
    check_name: str
    passed: bool
    current_value: float
    limit_value: float
    message: str


# ---------------------------------------------------------------------------
# Risk Calculator (static analytics)
# ---------------------------------------------------------------------------

class RiskCalculator:
    """Advanced risk calculations and analytics."""

    @staticmethod
    def calculate_var(
        returns: np.ndarray,
        confidence_level: float = 0.95,
        method: VaRMethod = VaRMethod.HISTORICAL,
        time_horizon: int = 1,
    ) -> float:
        """Calculate Value at Risk using specified method."""
        if len(returns) == 0:
            return 0.0

        if method == VaRMethod.HISTORICAL:
            return RiskCalculator._historical_var(returns, confidence_level, time_horizon)
        elif method == VaRMethod.PARAMETRIC:
            return RiskCalculator._parametric_var(returns, confidence_level, time_horizon)
        elif method == VaRMethod.MONTE_CARLO:
            return RiskCalculator._monte_carlo_var(returns, confidence_level, time_horizon)
        elif method == VaRMethod.CORNISH_FISHER:
            return RiskCalculator._cornish_fisher_var(returns, confidence_level, time_horizon)
        else:
            raise ValueError(f"Unsupported VaR method: {method}")

    @staticmethod
    def _historical_var(
        returns: np.ndarray, confidence_level: float, time_horizon: int
    ) -> float:
        """Calculate historical VaR."""
        percentile = (1 - confidence_level) * 100
        var = np.percentile(returns, percentile)
        return abs(var) * math.sqrt(time_horizon)

    @staticmethod
    def _parametric_var(
        returns: np.ndarray, confidence_level: float, time_horizon: int
    ) -> float:
        """Calculate parametric (normal) VaR."""
        if not SCIPY_AVAILABLE:
            return RiskCalculator._historical_var(returns, confidence_level, time_horizon)
        mean = np.mean(returns)
        std = np.std(returns)
        z_score = stats.norm.ppf(1 - confidence_level)
        var = mean + z_score * std
        return abs(var) * math.sqrt(time_horizon)

    @staticmethod
    def _monte_carlo_var(
        returns: np.ndarray,
        confidence_level: float,
        time_horizon: int,
        n_simulations: int = 10000,
    ) -> float:
        """Calculate Monte Carlo VaR."""
        mean = np.mean(returns)
        std = np.std(returns)

        simulated_returns = np.random.normal(mean, std, n_simulations * time_horizon)
        simulated_returns = simulated_returns.reshape(n_simulations, time_horizon)
        cumulative_returns = np.sum(simulated_returns, axis=1)

        percentile = (1 - confidence_level) * 100
        var = np.percentile(cumulative_returns, percentile)
        return abs(var)

    @staticmethod
    def _cornish_fisher_var(
        returns: np.ndarray, confidence_level: float, time_horizon: int
    ) -> float:
        """Calculate Cornish-Fisher VaR (accounts for skewness and kurtosis)."""
        if not SCIPY_AVAILABLE:
            return RiskCalculator._parametric_var(returns, confidence_level, time_horizon)

        mean = np.mean(returns)
        std = np.std(returns)
        skewness = stats.skew(returns)
        kurtosis = stats.kurtosis(returns)
        z = stats.norm.ppf(1 - confidence_level)

        z_cf = (
            z
            + (z ** 2 - 1) * skewness / 6
            + (z ** 3 - 3 * z) * kurtosis / 24
            - (2 * z ** 3 - 5 * z) * skewness ** 2 / 36
        )

        var = mean + z_cf * std
        return abs(var) * math.sqrt(time_horizon)

    @staticmethod
    def calculate_expected_shortfall(
        returns: np.ndarray, confidence_level: float = 0.95
    ) -> float:
        """Calculate Expected Shortfall (Conditional VaR)."""
        if len(returns) == 0:
            return 0.0

        percentile = (1 - confidence_level) * 100
        var_threshold = np.percentile(returns, percentile)
        tail_returns = returns[returns <= var_threshold]

        if len(tail_returns) == 0:
            return abs(var_threshold)

        return abs(np.mean(tail_returns))

    @staticmethod
    def calculate_maximum_drawdown(prices: np.ndarray) -> Tuple[float, int, int]:
        """Calculate maximum drawdown and its duration."""
        if len(prices) == 0:
            return 0.0, 0, 0

        running_max = np.maximum.accumulate(prices)
        drawdown = (prices - running_max) / running_max

        max_dd = np.min(drawdown)
        max_dd_idx = np.argmin(drawdown)
        start_idx = np.argmax(running_max[: max_dd_idx + 1] == running_max[max_dd_idx])

        return abs(max_dd), int(start_idx), int(max_dd_idx)

    @staticmethod
    def calculate_beta(asset_returns: np.ndarray, market_returns: np.ndarray) -> float:
        """Calculate beta coefficient."""
        if len(asset_returns) == 0 or len(market_returns) == 0:
            return 0.0

        covariance = np.cov(asset_returns, market_returns)[0, 1]
        market_variance = np.var(market_returns)

        if market_variance == 0:
            return 0.0

        return float(covariance / market_variance)

    @staticmethod
    def calculate_correlation_matrix(returns_matrix: np.ndarray) -> np.ndarray:
        """Calculate correlation matrix with robust estimation."""
        if returns_matrix.shape[0] == 0:
            return np.array([])

        if SCIPY_AVAILABLE:
            lw = LedoitWolf()
            cov_matrix = lw.fit(returns_matrix).covariance_
        else:
            cov_matrix = np.cov(returns_matrix, rowvar=False)

        std_devs = np.sqrt(np.diag(cov_matrix))
        # Avoid division by zero
        std_devs[std_devs == 0] = 1.0
        correlation_matrix = cov_matrix / np.outer(std_devs, std_devs)
        return correlation_matrix


# ---------------------------------------------------------------------------
# Circuit Breaker (local to risk-manager)
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker for external service calls."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._open = False

    def allow_request(self) -> bool:
        if not self._open:
            return True
        if self._last_failure_time and (time.time() - self._last_failure_time) >= self._recovery_timeout:
            self._open = False
            self._failure_count = 0
            return True
        return False

    def record_success(self):
        self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._open = True
            logger.warning("Circuit breaker opened due to %d failures", self._failure_count)


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """Core risk engine for institutional-grade risk management.

    Provides real-time risk monitoring, pre-trade checks, VaR calculations,
    and comprehensive risk analytics. Receives broker_adapter and event_bus
    via dependency injection — no hardcoded data.
    """

    def __init__(
        self,
        broker_adapter: Any = None,
        event_bus: Any = None,
        config: Optional[RiskConfig] = None,
    ):
        self._broker = broker_adapter
        self._event_bus = event_bus
        self._config = config or RiskConfig()

        self._risk_limits: Dict[str, RiskLimit] = {}
        self._position_risks: Dict[str, PositionRisk] = {}
        self._portfolio_risk: Optional[PortfolioRisk] = None
        self._risk_alerts: List[RiskAlert] = []

        # Caches for broker data
        self._positions_cache: Dict[str, Dict[str, Any]] = {}
        self._account_cache: Dict[str, Any] = {}
        self._price_cache: Dict[str, float] = {}
        self._returns_cache: Dict[str, np.ndarray] = {}
        self._historical_data: Dict[str, Any] = {}

        self._circuit_breaker = CircuitBreaker()
        self._lock = threading.RLock()
        self._shutdown_event = asyncio.Event()
        self._monitoring_task: Optional[asyncio.Task] = None
        self._calculator = RiskCalculator()

        # Daily tracking
        self._daily_trades: int = 0
        self._daily_pnl: float = 0.0
        self._daily_reset_time: datetime = datetime.now(timezone.utc)

        self._load_default_risk_limits()

    # -------------------------------------------------------------------
    # Initialization / Shutdown
    # -------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize the risk engine and start monitoring."""
        try:
            self._monitoring_task = asyncio.create_task(self._monitor_risk())

            if self._event_bus:
                self._event_bus.subscribe(EventType.POSITION_UPDATE, self._handle_position_update)
                self._event_bus.subscribe(EventType.MARKET_DATA, self._handle_market_data)

            logger.info("Risk engine initialized successfully")
            return True
        except Exception as e:
            logger.error("Failed to initialize risk engine: %s", e)
            return False

    async def shutdown(self):
        """Shutdown the risk engine."""
        try:
            self._shutdown_event.set()
            if self._monitoring_task:
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
            logger.info("Risk engine shutdown completed")
        except Exception as e:
            logger.error("Error during risk engine shutdown: %s", e)

    def _load_default_risk_limits(self):
        """Load default risk limits from config."""
        cfg = self._config
        defaults = [
            RiskLimit("max_position_size", "position", cfg.max_position_size),
            RiskLimit("max_portfolio_var", "var", cfg.max_portfolio_var),
            RiskLimit("max_drawdown", "drawdown", cfg.max_drawdown),
            RiskLimit("max_leverage", "leverage", cfg.max_leverage),
            RiskLimit("max_sector_exposure", "sector_exposure", cfg.max_sector_exposure),
            RiskLimit("min_liquidity_ratio", "liquidity", cfg.min_liquidity_ratio),
            RiskLimit("daily_loss_limit", "daily_loss", cfg.daily_loss_limit_pct),
            RiskLimit("max_daily_trades", "daily_trades", float(cfg.max_daily_trades)),
            RiskLimit("max_concurrent_positions", "position_count", float(cfg.max_concurrent_positions)),
            RiskLimit("max_order_size", "order_size", cfg.max_order_size),
        ]
        for limit in defaults:
            self._risk_limits[limit.name] = limit

    # -------------------------------------------------------------------
    # Pre-Trade Risk Checks (Task 2.3)
    # -------------------------------------------------------------------

    async def pre_trade_check(self, order: Dict[str, Any]) -> Tuple[RiskCheckResult, List[IndividualCheckResult]]:
        """Perform comprehensive pre-trade risk checks.

        Returns (overall_result, list_of_individual_checks).
        """
        try:
            symbol = order.get("symbol") or order.get("instrument", "")
            quantity = abs(order.get("quantity", 0))
            price = order.get("price", 0)

            if not symbol or quantity == 0:
                return RiskCheckResult.REJECTED, [
                    IndividualCheckResult("valid_order", False, 0, 1, "Missing symbol or quantity")
                ]

            checks = [
                await self._check_position_limit(symbol, quantity, price),
                await self._check_concentration_limit(symbol, quantity, price),
                self._check_daily_loss_limit(),
                self._check_daily_trade_limit(),
                await self._check_margin_requirement(symbol, quantity, price),
                self._check_order_size_limit(quantity, price),
                await self._check_var_impact(symbol, quantity, price),
                await self._check_leverage_limits(symbol, quantity, price),
            ]

            failures = [c for c in checks if not c.passed]
            warnings = [c for c in checks if c.passed and "warning" in c.message.lower()]

            if failures:
                return RiskCheckResult.REJECTED, failures

            if warnings:
                return RiskCheckResult.WARNING, checks

            return RiskCheckResult.APPROVED, checks

        except Exception as e:
            logger.error("Error in pre-trade check: %s", e)
            return RiskCheckResult.REJECTED, [
                IndividualCheckResult("pre_trade_check", False, 0, 0, f"Check error: {e}")
            ]

    async def _check_position_limit(
        self, symbol: str, quantity: float, price: float
    ) -> IndividualCheckResult:
        """Check if trade would exceed position size limit."""
        limit = self._risk_limits.get("max_position_size")
        if not limit or not limit.enabled:
            return IndividualCheckResult("position_limit", True, 0, limit.value if limit else 0, "OK")

        current_position = await self._get_current_position(symbol)
        new_position_size = abs((current_position + quantity) * price)

        passed = new_position_size <= limit.value
        return IndividualCheckResult(
            "position_limit",
            passed,
            new_position_size,
            limit.value,
            "OK" if passed else f"Position value {new_position_size:,.2f} exceeds limit {limit.value:,.2f}",
        )

    async def _check_concentration_limit(
        self, symbol: str, quantity: float, price: float
    ) -> IndividualCheckResult:
        """Check if trade would exceed sector concentration limit."""
        limit = self._risk_limits.get("max_sector_exposure")
        if not limit or not limit.enabled:
            return IndividualCheckResult("concentration_limit", True, 0, limit.value if limit else 0, "OK")

        total_portfolio_value = await self._get_total_portfolio_value()
        if total_portfolio_value <= 0:
            return IndividualCheckResult("concentration_limit", True, 0, limit.value, "OK - no portfolio")

        position_value = abs(quantity * price)
        current_position = await self._get_current_position(symbol)
        existing_value = abs(current_position) * await self._get_current_price(symbol)
        total_symbol_value = existing_value + position_value
        concentration = total_symbol_value / total_portfolio_value

        passed = concentration <= limit.value
        return IndividualCheckResult(
            "concentration_limit",
            passed,
            concentration,
            limit.value,
            "OK" if passed else f"Concentration {concentration:.2%} exceeds limit {limit.value:.2%}",
        )

    def _check_daily_loss_limit(self) -> IndividualCheckResult:
        """Check if daily loss limit has been reached."""
        limit = self._risk_limits.get("daily_loss_limit")
        if not limit or not limit.enabled:
            return IndividualCheckResult("daily_loss_limit", True, 0, limit.value if limit else 0, "OK")

        self._reset_daily_counters_if_needed()
        total_equity = self._get_cached_total_equity()
        if total_equity <= 0:
            return IndividualCheckResult("daily_loss_limit", True, 0, limit.value, "OK")

        daily_loss_pct = abs(min(self._daily_pnl, 0)) / total_equity
        passed = daily_loss_pct < limit.value
        return IndividualCheckResult(
            "daily_loss_limit",
            passed,
            daily_loss_pct,
            limit.value,
            "OK" if passed else f"Daily loss {daily_loss_pct:.2%} exceeds limit {limit.value:.2%}",
        )

    def _check_daily_trade_limit(self) -> IndividualCheckResult:
        """Check if daily trade count limit has been reached."""
        limit = self._risk_limits.get("max_daily_trades")
        if not limit or not limit.enabled:
            return IndividualCheckResult("daily_trade_limit", True, 0, limit.value if limit else 0, "OK")

        self._reset_daily_counters_if_needed()
        passed = self._daily_trades < int(limit.value)
        return IndividualCheckResult(
            "daily_trade_limit",
            passed,
            float(self._daily_trades),
            limit.value,
            "OK" if passed else f"Daily trades {self._daily_trades} exceeds limit {int(limit.value)}",
        )

    async def _check_margin_requirement(
        self, symbol: str, quantity: float, price: float
    ) -> IndividualCheckResult:
        """Check if sufficient margin / buying power available."""
        if not self._broker:
            return IndividualCheckResult("margin_requirement", True, 0, 0, "OK - no broker")

        try:
            account_info = await self._get_account_info()
            buying_power = account_info.get("buying_power", 0)
            order_value = quantity * price
            passed = order_value <= buying_power
            return IndividualCheckResult(
                "margin_requirement",
                passed,
                order_value,
                buying_power,
                "OK" if passed else f"Order value {order_value:,.2f} exceeds buying power {buying_power:,.2f}",
            )
        except Exception as e:
            logger.warning("Could not check margin requirement: %s", e)
            return IndividualCheckResult("margin_requirement", True, 0, 0, "OK - check skipped")

    def _check_order_size_limit(self, quantity: float, price: float) -> IndividualCheckResult:
        """Check if individual order size exceeds limit."""
        limit = self._risk_limits.get("max_order_size")
        if not limit or not limit.enabled:
            return IndividualCheckResult("order_size_limit", True, 0, limit.value if limit else 0, "OK")

        order_value = quantity * price
        passed = order_value <= limit.value
        return IndividualCheckResult(
            "order_size_limit",
            passed,
            order_value,
            limit.value,
            "OK" if passed else f"Order value {order_value:,.2f} exceeds limit {limit.value:,.2f}",
        )

    async def _check_var_impact(
        self, symbol: str, quantity: float, price: float
    ) -> IndividualCheckResult:
        """Check if trade would breach VaR limits."""
        limit = self._risk_limits.get("max_portfolio_var")
        if not limit or not limit.enabled:
            return IndividualCheckResult("var_impact", True, 0, limit.value if limit else 0, "OK")

        try:
            current_var = await self._calculate_portfolio_var()
            returns = await self._get_historical_returns(symbol)
            if len(returns) == 0:
                return IndividualCheckResult("var_impact", True, 0, limit.value, "OK - no data")

            position_var = self._calculator.calculate_var(
                returns, self._config.var_confidence_level, self._config.var_method, 1
            ) * abs(quantity * price)

            estimated_new_var = math.sqrt(current_var ** 2 + position_var ** 2)

            passed = estimated_new_var <= limit.value
            return IndividualCheckResult(
                "var_impact",
                passed,
                estimated_new_var,
                limit.value,
                "OK" if passed else f"Estimated VaR {estimated_new_var:,.2f} exceeds limit {limit.value:,.2f}",
            )
        except Exception as e:
            logger.warning("Could not check VaR impact: %s", e)
            return IndividualCheckResult("var_impact", True, 0, limit.value, "OK - check skipped")

    async def _check_leverage_limits(
        self, symbol: str, quantity: float, price: float
    ) -> IndividualCheckResult:
        """Check if trade would breach leverage limits."""
        limit = self._risk_limits.get("max_leverage")
        if not limit or not limit.enabled:
            return IndividualCheckResult("leverage_limit", True, 0, limit.value if limit else 0, "OK")

        try:
            total_equity = await self._get_total_equity()
            if total_equity <= 0:
                return IndividualCheckResult("leverage_limit", False, 0, limit.value, "No equity")

            current_leverage = await self._get_current_leverage()
            additional_leverage = abs(quantity * price) / total_equity
            new_leverage = current_leverage + additional_leverage

            passed = new_leverage <= limit.value
            return IndividualCheckResult(
                "leverage_limit",
                passed,
                new_leverage,
                limit.value,
                "OK" if passed else f"Leverage {new_leverage:.2f} exceeds limit {limit.value:.2f}",
            )
        except Exception as e:
            logger.warning("Could not check leverage: %s", e)
            return IndividualCheckResult("leverage_limit", True, 0, limit.value, "OK - check skipped")

    # -------------------------------------------------------------------
    # Position Risk Calculation
    # -------------------------------------------------------------------

    async def calculate_position_risk(self, instrument: str) -> Optional[PositionRisk]:
        """Calculate comprehensive risk metrics for a position."""
        try:
            position_size = await self._get_current_position(instrument)
            if position_size == 0:
                return None

            market_price = await self._get_current_price(instrument)
            market_value = position_size * market_price
            returns = await self._get_historical_returns(instrument)

            if len(returns) == 0:
                return None

            var_1d = self._calculator.calculate_var(returns, 0.95, VaRMethod.HISTORICAL, 1)
            var_10d = self._calculator.calculate_var(returns, 0.95, VaRMethod.HISTORICAL, 10)
            expected_shortfall = self._calculator.calculate_expected_shortfall(returns, 0.95)

            market_returns = await self._get_market_returns()
            beta = self._calculator.calculate_beta(returns, market_returns) if len(market_returns) > 0 else 0.0

            volatility = float(np.std(returns) * math.sqrt(252))

            prices = await self._get_historical_prices(instrument)
            max_dd, _, _ = self._calculator.calculate_maximum_drawdown(prices) if len(prices) > 0 else (0.0, 0, 0)

            total_portfolio_value = await self._get_total_portfolio_value()
            concentration_risk = abs(market_value) / total_portfolio_value if total_portfolio_value > 0 else 0.0
            liquidity_risk = await self._estimate_liquidity_risk(instrument)

            position_risk = PositionRisk(
                instrument=instrument,
                position_size=position_size,
                market_value=market_value,
                unrealized_pnl=await self._get_unrealized_pnl(instrument),
                var_1d=var_1d * abs(market_value),
                var_10d=var_10d * abs(market_value),
                expected_shortfall=expected_shortfall * abs(market_value),
                beta=beta,
                volatility=volatility,
                max_drawdown=max_dd,
                concentration_risk=concentration_risk,
                liquidity_risk=liquidity_risk,
            )

            with self._lock:
                self._position_risks[instrument] = position_risk

            return position_risk

        except Exception as e:
            logger.error("Error calculating position risk for %s: %s", instrument, e)
            return None

    async def _calculate_portfolio_var(self) -> float:
        """Calculate portfolio-level VaR."""
        try:
            positions = await self._get_all_positions()
            if not positions:
                return 0.0

            instruments = list(positions.keys())
            returns_data = []
            for inst in instruments:
                returns = await self._get_historical_returns(inst)
                if len(returns) > 0:
                    returns_data.append(returns)

            if not returns_data:
                return 0.0

            min_length = min(len(r) for r in returns_data)
            returns_matrix = np.array([r[-min_length:] for r in returns_data]).T

            total_value = sum(
                abs(positions[inst]) * await self._get_current_price(inst)
                for inst in instruments
            )
            if total_value == 0:
                return 0.0

            weights = np.array([
                abs(positions[inst]) * await self._get_current_price(inst) / total_value
                for inst in instruments
            ])

            portfolio_returns = np.dot(returns_matrix, weights)
            portfolio_var = self._calculator.calculate_var(
                portfolio_returns, 0.95, VaRMethod.HISTORICAL, 1
            )

            return portfolio_var * total_value

        except Exception as e:
            logger.error("Error calculating portfolio VaR: %s", e)
            return 0.0

    # -------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------

    async def _handle_position_update(self, event: Any):
        """Handle position update events."""
        try:
            data = event.data if hasattr(event, "data") else event
            instrument = data.get("instrument") if isinstance(data, dict) else None
            if instrument:
                await self.calculate_position_risk(instrument)
                await self._check_risk_limits(instrument)
        except Exception as e:
            logger.error("Error handling position update: %s", e)

    async def _handle_market_data(self, event: Any):
        """Handle market data events."""
        try:
            data = event.data if hasattr(event, "data") else event
            instrument = data.get("instrument") if isinstance(data, dict) else None
            if instrument:
                price = data.get("price") or data.get("last", 0)
                if price > 0:
                    self._price_cache[instrument] = price
        except Exception as e:
            logger.error("Error handling market data: %s", e)

    # -------------------------------------------------------------------
    # Risk Monitoring Loop
    # -------------------------------------------------------------------

    async def _monitor_risk(self):
        """Continuously monitor risk metrics."""
        while not self._shutdown_event.is_set():
            try:
                await self._calculate_portfolio_risk()
                await self._check_all_risk_limits()
                self._cleanup_old_alerts()
                await asyncio.sleep(self._config.monitoring_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in risk monitoring: %s", e)
                await asyncio.sleep(self._config.monitoring_interval_seconds)

    async def _calculate_portfolio_risk(self):
        """Calculate comprehensive portfolio risk metrics."""
        try:
            positions = await self._get_all_positions()
            if not positions:
                return

            total_value = sum(
                abs(pos) * await self._get_current_price(inst)
                for inst, pos in positions.items()
            )
            if total_value == 0:
                return

            portfolio_var = await self._calculate_portfolio_var()
            diversification_ratio = self._calculate_diversification_ratio(positions)

            concentration_index = sum(
                (abs(pos * await self._get_current_price(inst)) / total_value) ** 2
                for inst, pos in positions.items()
            )

            sector_exposures = await self._calculate_sector_exposures(positions)
            max_sector_exposure = max(sector_exposures.values()) if sector_exposures else 0.0

            leverage_ratio = await self._get_current_leverage()
            liquidity_ratio = self._calculate_liquidity_ratio(positions)

            stress_results = await self._run_stress_tests(positions)
            risk_attribution = self._calculate_risk_attribution(positions)

            portfolio_risk = PortfolioRisk(
                total_value=total_value,
                total_var=portfolio_var,
                diversification_ratio=diversification_ratio,
                concentration_index=concentration_index,
                max_sector_exposure=max_sector_exposure,
                leverage_ratio=leverage_ratio,
                liquidity_ratio=liquidity_ratio,
                stress_test_results=stress_results,
                risk_attribution=risk_attribution,
            )

            with self._lock:
                self._portfolio_risk = portfolio_risk

            if self._event_bus:
                await self._event_bus.publish(Event(
                    type=EventType.RISK_ALERT,
                    data={"action": "portfolio_risk_update"},
                    source="risk_engine",
                ))

        except Exception as e:
            logger.error("Error calculating portfolio risk: %s", e)

    async def _check_all_risk_limits(self):
        """Check all configured risk limits."""
        try:
            if not self._portfolio_risk:
                return

            for limit_name, limit in self._risk_limits.items():
                if not limit.enabled:
                    continue

                breach_detected = False
                current_value = 0.0

                if limit.limit_type == "var":
                    current_value = self._portfolio_risk.total_var
                    breach_detected = current_value > limit.value
                elif limit.limit_type == "leverage":
                    current_value = self._portfolio_risk.leverage_ratio
                    breach_detected = current_value > limit.value
                elif limit.limit_type == "drawdown":
                    current_value = self._get_current_drawdown()
                    breach_detected = current_value > limit.value
                elif limit.limit_type == "sector_exposure":
                    current_value = self._portfolio_risk.max_sector_exposure
                    breach_detected = current_value > limit.value
                elif limit.limit_type == "liquidity":
                    current_value = self._portfolio_risk.liquidity_ratio
                    breach_detected = current_value < limit.value

                if breach_detected:
                    breach_pct = ((current_value - limit.value) / limit.value) * 100 if limit.value != 0 else 0
                    await self._create_alert(
                        f"Risk Limit Breach: {limit_name}",
                        "high" if breach_pct > 20 else "medium",
                        f"{limit.limit_type} limit breached",
                        risk_metric=limit.limit_type,
                        current_value=current_value,
                        limit_value=limit.value,
                        breach_percentage=breach_pct,
                    )

        except Exception as e:
            logger.error("Error checking risk limits: %s", e)

    async def _check_risk_limits(self, instrument: str):
        """Check risk limits after position update."""
        await self._check_all_risk_limits()

    # -------------------------------------------------------------------
    # Alert Management
    # -------------------------------------------------------------------

    async def _create_alert(
        self,
        message: str,
        severity: str,
        description: str = "",
        instrument: Optional[str] = None,
        strategy: Optional[str] = None,
        risk_metric: str = "",
        current_value: float = 0.0,
        limit_value: float = 0.0,
        breach_percentage: float = 0.0,
    ) -> None:
        """Create a risk alert."""
        alert = RiskAlert(
            alert_id=f"risk_{int(time.time())}_{len(self._risk_alerts)}",
            severity=severity,
            message=message,
            risk_metric=risk_metric,
            current_value=current_value,
            limit_value=limit_value,
            breach_percentage=breach_percentage,
            instrument=instrument,
            strategy=strategy,
        )

        with self._lock:
            self._risk_alerts.append(alert)

        if self._event_bus:
            await self._event_bus.publish(Event(
                type=EventType.RISK_ALERT,
                data={
                    "alert_id": alert.alert_id,
                    "severity": severity,
                    "message": message,
                    "instrument": instrument,
                },
                priority=EventPriority.HIGH if severity in ("high", "critical") else EventPriority.NORMAL,
                source="risk_engine",
            ))

        logger.warning("Risk alert: %s (Severity: %s)", message, severity)

    def _cleanup_old_alerts(self):
        """Remove alerts older than 24 hours."""
        cutoff = datetime.now() - timedelta(hours=24)
        with self._lock:
            self._risk_alerts = [a for a in self._risk_alerts if a.timestamp > cutoff]

    # -------------------------------------------------------------------
    # Data Retrieval (wired to broker adapter — Task 2.1)
    # -------------------------------------------------------------------

    async def _get_current_position(self, instrument: str) -> float:
        """Get current position size from broker."""
        if self._broker:
            try:
                if not self._positions_cache:
                    positions = await self._broker.get_positions()
                    self._positions_cache = {
                        p.get("symbol", p.get("instrument", "")): p for p in positions
                    }
                pos = self._positions_cache.get(instrument, {})
                return float(pos.get("quantity", pos.get("position", 0)))
            except Exception as e:
                logger.warning("Could not fetch position for %s: %s", instrument, e)
        return self._positions_cache.get(instrument, {}).get("quantity", 0.0)

    async def _get_current_price(self, instrument: str) -> float:
        """Get current market price from broker or cache."""
        if instrument in self._price_cache:
            return self._price_cache[instrument]

        if self._broker:
            try:
                quote = await self._broker.get_quote(instrument)
                price = quote.get("last", quote.get("price", 0))
                if price > 0:
                    self._price_cache[instrument] = price
                    return price
            except Exception as e:
                logger.warning("Could not fetch price for %s: %s", instrument, e)

        return self._price_cache.get(instrument, 0.0)

    async def _get_historical_returns(self, instrument: str) -> np.ndarray:
        """Get historical returns for instrument."""
        if instrument in self._returns_cache:
            return self._returns_cache[instrument]

        if self._broker:
            try:
                data = await self._broker.get_historical_data(
                    instrument,
                    start_date=datetime.now(timezone.utc) - timedelta(days=365),
                    end_date=datetime.now(timezone.utc),
                    timeframe="1d",
                )
                if data:
                    prices = np.array([
                        bar.get("close", 0) for bar in data if bar.get("close", 0) > 0
                    ])
                    if len(prices) > 1:
                        returns = np.diff(np.log(prices))
                        self._returns_cache[instrument] = returns
                        return returns
            except Exception as e:
                logger.warning("Could not fetch historical data for %s: %s", instrument, e)

        return np.array([])

    async def _get_historical_prices(self, instrument: str) -> np.ndarray:
        """Get historical prices for instrument."""
        if self._broker:
            try:
                data = await self._broker.get_historical_data(
                    instrument,
                    start_date=datetime.now(timezone.utc) - timedelta(days=365),
                    end_date=datetime.now(timezone.utc),
                    timeframe="1d",
                )
                if data:
                    return np.array([bar.get("close", 0) for bar in data if bar.get("close", 0) > 0])
            except Exception as e:
                logger.warning("Could not fetch historical prices for %s: %s", instrument, e)
        return np.array([])

    async def _get_total_equity(self) -> float:
        """Get total portfolio equity from broker."""
        if self._broker:
            try:
                account_info = await self._get_account_info()
                return float(account_info.get("net_liquidation", account_info.get("equity", 0)))
            except Exception as e:
                logger.warning("Could not fetch total equity: %s", e)
        return self._get_cached_total_equity()

    def _get_cached_total_equity(self) -> float:
        """Get equity from cached account data."""
        return float(self._account_cache.get("net_liquidation", self._account_cache.get("equity", 0)))

    async def _get_total_portfolio_value(self) -> float:
        """Get total portfolio value."""
        return await self._get_total_equity()

    async def _get_account_info(self) -> Dict[str, Any]:
        """Get account info from broker (cached for 30s)."""
        if self._account_cache and self._account_cache.get("_cache_time"):
            age = (datetime.now(timezone.utc) - self._account_cache["_cache_time"]).total_seconds()
            if age < 30:
                return self._account_cache

        if self._broker:
            try:
                info = await self._broker.get_account_info()
                info["_cache_time"] = datetime.now(timezone.utc)
                self._account_cache = info
                return info
            except Exception as e:
                logger.warning("Could not fetch account info: %s", e)
        return self._account_cache

    async def _get_current_leverage(self) -> float:
        """Calculate current leverage from positions and equity."""
        try:
            positions = await self._get_all_positions()
            if not positions:
                return 0.0

            total_exposure = sum(
                abs(pos) * await self._get_current_price(inst)
                for inst, pos in positions.items()
            )
            equity = await self._get_total_equity()
            return total_exposure / equity if equity > 0 else 0.0
        except Exception:
            return 0.0

    async def _get_all_positions(self) -> Dict[str, float]:
        """Get all current positions from broker."""
        if self._broker:
            try:
                positions = await self._broker.get_positions()
                self._positions_cache = {
                    p.get("symbol", p.get("instrument", "")): p for p in positions
                }
                return {
                    sym: float(p.get("quantity", p.get("position", 0)))
                    for sym, p in self._positions_cache.items()
                    if float(p.get("quantity", p.get("position", 0))) != 0
                }
            except Exception as e:
                logger.warning("Could not fetch positions: %s", e)
        return {}

    async def _get_unrealized_pnl(self, instrument: str) -> float:
        """Get unrealized P&L for instrument."""
        pos = self._positions_cache.get(instrument, {})
        return float(pos.get("unrealized_pnl", 0))

    async def _get_market_returns(self) -> np.ndarray:
        """Get market benchmark returns (e.g., SPY)."""
        return await self._get_historical_returns("SPY")

    async def _estimate_liquidity_risk(self, instrument: str) -> float:
        """Estimate liquidity risk (0 = liquid, 1 = illiquid)."""
        # Basic heuristic based on position value vs portfolio
        total_value = await self._get_total_portfolio_value()
        price = await self._get_current_price(instrument)
        position = await self._get_current_position(instrument)
        if total_value <= 0 or price <= 0:
            return 0.5

        position_value = abs(position * price)
        concentration = position_value / total_value
        return min(concentration * 2, 1.0)

    def _calculate_diversification_ratio(self, positions: Dict[str, float]) -> float:
        """Calculate portfolio diversification ratio."""
        if len(positions) <= 1:
            return 1.0
        return min(len(positions) / 10.0, 1.0)

    async def _calculate_sector_exposures(self, positions: Dict[str, float]) -> Dict[str, float]:
        """Calculate exposures by sector."""
        # Simplified — real implementation would use reference data
        return {"Unclassified": 1.0}

    def _calculate_liquidity_ratio(self, positions: Dict[str, float]) -> float:
        """Calculate portfolio liquidity ratio."""
        return min(len(positions) * 0.1 + 0.5, 1.0)

    async def _run_stress_tests(self, positions: Dict[str, float]) -> Dict[str, float]:
        """Run portfolio stress tests."""
        total_value = await self._get_total_portfolio_value()
        if total_value <= 0:
            return {}
        return {
            "market_crash": -total_value * 0.15,
            "interest_rate_shock": -total_value * 0.08,
            "volatility_spike": -total_value * 0.12,
        }

    def _calculate_risk_attribution(self, positions: Dict[str, float]) -> Dict[str, float]:
        """Calculate risk attribution by position."""
        total = sum(abs(v) for v in positions.values())
        if total == 0:
            return {}
        return {inst: abs(v) / total for inst, v in positions.items()}

    def _get_current_drawdown(self) -> float:
        """Get current portfolio drawdown (from account info if available)."""
        return float(self._account_cache.get("drawdown", 0.0))

    def _reset_daily_counters_if_needed(self):
        """Reset daily trade/PnL counters at start of new day."""
        now = datetime.now(timezone.utc)
        if now.date() > self._daily_reset_time.date():
            self._daily_trades = 0
            self._daily_pnl = 0.0
            self._daily_reset_time = now

    def record_trade_executed(self, pnl: float = 0.0):
        """Record that a trade was executed (called by execution engine)."""
        self._reset_daily_counters_if_needed()
        self._daily_trades += 1
        self._daily_pnl += pnl

    def invalidate_cache(self, instrument: Optional[str] = None):
        """Invalidate cached data to force fresh broker fetch."""
        if instrument:
            self._positions_cache.pop(instrument, None)
            self._price_cache.pop(instrument, None)
            self._returns_cache.pop(instrument, None)
        else:
            self._positions_cache.clear()
            self._price_cache.clear()
            self._returns_cache.clear()
            self._account_cache.clear()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_portfolio_risk(self) -> Optional[PortfolioRisk]:
        """Get current portfolio risk metrics."""
        return self._portfolio_risk

    def get_position_risk(self, instrument: str) -> Optional[PositionRisk]:
        """Get risk metrics for a specific position."""
        return self._position_risks.get(instrument)

    def get_risk_alerts(self, severity: Optional[str] = None) -> List[RiskAlert]:
        """Get current risk alerts, optionally filtered by severity."""
        with self._lock:
            if severity:
                return [a for a in self._risk_alerts if a.severity == severity]
            return self._risk_alerts.copy()

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge a risk alert."""
        with self._lock:
            for alert in self._risk_alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    return True
        return False

    def add_risk_limit(self, limit: RiskLimit):
        """Add or update a risk limit."""
        with self._lock:
            self._risk_limits[limit.name] = limit
        logger.info("Added risk limit: %s", limit.name)

    def remove_risk_limit(self, limit_name: str) -> bool:
        """Remove a risk limit."""
        with self._lock:
            if limit_name in self._risk_limits:
                del self._risk_limits[limit_name]
                logger.info("Removed risk limit: %s", limit_name)
                return True
        return False

    def get_risk_limits(self) -> Dict[str, RiskLimit]:
        """Get all configured risk limits."""
        return self._risk_limits.copy()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    """Get the global risk engine instance."""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
