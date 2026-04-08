"""Compliance Engine for automated trading compliance checking.

Provides Pattern Day Trader detection, wash sale monitoring, Reg T margin
verification, position concentration limits, and daily compliance reporting.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATION = "violation"


class ViolationType(Enum):
    PDT = "pattern_day_trader"
    WASH_SALE = "wash_sale"
    MARGIN = "margin_violation"
    CONCENTRATION = "concentration_limit"
    POSITION_LIMIT = "position_limit"
    TRADE_LIMIT = "trade_limit"


@dataclass
class TradeRecord:
    """Record of a trade for compliance checking."""
    trade_id: str
    account_id: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    price: float
    timestamp: datetime
    trade_type: str = "day_trade"  # "day_trade", "swing", "position"

    @property
    def notional_value(self) -> float:
        return self.quantity * self.price


@dataclass
class PDTStatus:
    """Pattern Day Trader status."""
    is_pdt: bool
    day_trade_count: int
    rolling_window_days: int = 5
    threshold: int = 4
    details: str = ""
    trades_in_window: List[TradeRecord] = field(default_factory=list)


@dataclass
class WashSaleResult:
    """Wash sale detection result."""
    has_wash_sale: bool
    symbol: str
    loss_amount: float = 0.0
    disallowed_loss: float = 0.0
    replacement_trade: Optional[TradeRecord] = None
    original_loss_trade: Optional[TradeRecord] = None
    wash_period_days: int = 30


@dataclass
class MarginStatus:
    """Reg T margin verification result."""
    compliant: bool
    account_equity: float = 0.0
    margin_used: float = 0.0
    margin_available: float = 0.0
    reg_t_requirement: float = 0.0
    maintenance_requirement: float = 0.0
    details: str = ""


@dataclass
class ConcentrationReport:
    """Position concentration analysis."""
    compliant: bool
    max_single_position_pct: float = 0.0
    max_sector_pct: float = 0.0
    position_concentrations: Dict[str, float] = field(default_factory=dict)
    sector_concentrations: Dict[str, float] = field(default_factory=dict)
    limit_pct: float = 25.0  # max 25% in single position
    sector_limit_pct: float = 40.0  # max 40% in single sector


@dataclass
class AuditRecord:
    """Immutable audit trail entry."""
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = ""
    actor: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    compliance_status: ComplianceStatus = ComplianceStatus.COMPLIANT
    violations: List[ViolationType] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceReport:
    """End-of-day compliance report."""
    account_id: str
    report_date: datetime
    overall_status: ComplianceStatus = ComplianceStatus.COMPLIANT
    pdt_status: Optional[PDTStatus] = None
    wash_sales: List[WashSaleResult] = field(default_factory=list)
    margin_status: Optional[MarginStatus] = None
    concentration_report: Optional[ConcentrationReport] = None
    violations: List[Dict[str, Any]] = field(default_factory=list)
    audit_records: List[AuditRecord] = field(default_factory=list)


class ComplianceEngine:
    """Automated compliance checking for trading activities."""

    # Reg T initial margin requirement
    REG_T_INITIAL_MARGIN = 0.50  # 50%
    REG_T_MAINTENANCE_MARGIN = 0.25  # 25%

    def __init__(self, event_bus=None, config: Optional[Dict] = None):
        self._event_bus = event_bus
        self._config = config or {}
        self._trades: Dict[str, List[TradeRecord]] = {}  # account_id -> trades
        self._audit_records: List[AuditRecord] = []
        self._pdt_threshold: int = self._config.get("pdt_threshold", 4)
        self._pdt_window_days: int = self._config.get("pdt_window_days", 5)
        self._concentration_limit: float = self._config.get("concentration_limit", 25.0)
        self._sector_limit: float = self._config.get("sector_limit", 40.0)
        self._logger = logging.getLogger(__name__)

    def record_trade(self, trade: TradeRecord):
        """Record a trade for compliance tracking."""
        if trade.account_id not in self._trades:
            self._trades[trade.account_id] = []
        self._trades[trade.account_id].append(trade)

    async def check_pattern_day_trader(self, account_id: str) -> PDTStatus:
        """Check Pattern Day Trader status (4+ day trades in 5 business days)."""
        trades = self._trades.get(account_id, [])
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._pdt_window_days)
        recent_trades = [t for t in trades if t.timestamp >= cutoff and t.trade_type == "day_trade"]

        # Group by symbol to find day trades (buy and sell same symbol same day)
        day_trades: List[TradeRecord] = []
        symbols_traded: Dict[str, List[TradeRecord]] = {}
        for t in recent_trades:
            if t.symbol not in symbols_traded:
                symbols_traded[t.symbol] = []
            symbols_traded[t.symbol].append(t)

        for symbol, symbol_trades in symbols_traded.items():
            buys = [t for t in symbol_trades if t.side == "buy"]
            sells = [t for t in symbol_trades if t.side == "sell"]
            if buys and sells:
                # Count as one day trade per buy-sell pair
                pairs = min(len(buys), len(sells))
                for i in range(pairs):
                    day_trades.append(buys[i])

        is_pdt = len(day_trades) >= self._pdt_threshold

        status = PDTStatus(
            is_pdt=is_pdt,
            day_trade_count=len(day_trades),
            rolling_window_days=self._pdt_window_days,
            threshold=self._pdt_threshold,
            details=f"{len(day_trades)} day trades in {self._pdt_window_days}-day window"
                    + (" - PDT STATUS" if is_pdt else ""),
            trades_in_window=day_trades,
        )

        if is_pdt:
            await self._create_audit_record(
                action="pdt_detected",
                actor="compliance_engine",
                details={"account_id": account_id, "day_trade_count": len(day_trades)},
                status=ComplianceStatus.WARNING,
                violations=[ViolationType.PDT],
            )

        return status

    async def check_wash_sale(self, symbol: str, account_id: str) -> WashSaleResult:
        """Detect wash sale violations (buy same/similar within 30 days of loss)."""
        trades = self._trades.get(account_id, [])
        symbol_trades = [t for t in trades if t.symbol == symbol]
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent = [t for t in symbol_trades if t.timestamp >= cutoff]

        # Find loss trades (sell at loss)
        loss_trades = [t for t in recent if t.side == "sell"]
        # Find replacement buys
        buy_trades = [t for t in recent if t.side == "buy"]

        for loss_trade in loss_trades:
            # Check if there's a buy within 30 days before or after
            for buy_trade in buy_trades:
                time_diff = (buy_trade.timestamp - loss_trade.timestamp).days
                if abs(time_diff) <= 30:
                    # Simplified: assume loss if sell price < some reference
                    # In practice, compare against cost basis
                    loss_amount = loss_trade.notional_value * 0.05  # placeholder loss calc
                    return WashSaleResult(
                        has_wash_sale=True,
                        symbol=symbol,
                        loss_amount=loss_amount,
                        disallowed_loss=loss_amount,
                        replacement_trade=buy_trade,
                        original_loss_trade=loss_trade,
                    )

        return WashSaleResult(has_wash_sale=False, symbol=symbol)

    async def check_reg_t_margin(self, account_id: str, account_equity: float,
                                  positions: Dict[str, float]) -> MarginStatus:
        """Verify Reg T margin requirements.

        positions: dict of symbol -> market_value (positive for long, negative for short)
        """
        total_long = sum(v for v in positions.values() if v > 0)
        total_short = sum(abs(v) for v in positions.values() if v < 0)

        initial_requirement = (total_long * self.REG_T_INITIAL_MARGIN
                               + total_short * self.REG_T_INITIAL_MARGIN)
        maintenance_requirement = (total_long * self.REG_T_MAINTENANCE_MARGIN
                                   + total_short * self.REG_T_MAINTENANCE_MARGIN)

        margin_used = initial_requirement
        margin_available = account_equity - margin_used
        compliant = margin_available >= 0 and account_equity >= maintenance_requirement

        status = MarginStatus(
            compliant=compliant,
            account_equity=account_equity,
            margin_used=margin_used,
            margin_available=margin_available,
            reg_t_requirement=initial_requirement,
            maintenance_requirement=maintenance_requirement,
            details="Compliant" if compliant else "Margin call - equity below requirement",
        )

        if not compliant:
            await self._create_audit_record(
                action="margin_violation",
                actor="compliance_engine",
                details={"account_id": account_id, "shortfall": abs(margin_available)},
                status=ComplianceStatus.VIOLATION,
                violations=[ViolationType.MARGIN],
            )

        return status

    async def check_position_concentration(self, account_id: str,
                                            positions: Dict[str, float],
                                            sectors: Optional[Dict[str, str]] = None) -> ConcentrationReport:
        """Check if any single position exceeds concentration limits.

        positions: symbol -> market_value
        sectors: symbol -> sector_name (optional)
        """
        total_value = sum(abs(v) for v in positions.values())
        if total_value == 0:
            return ConcentrationReport(compliant=True)

        position_concentrations = {
            sym: (abs(val) / total_value * 100) for sym, val in positions.items()
        }

        sector_concentrations: Dict[str, float] = {}
        if sectors:
            sector_values: Dict[str, float] = {}
            for sym, val in positions.items():
                sector = sectors.get(sym, "unknown")
                sector_values[sector] = sector_values.get(sector, 0.0) + abs(val)
            sector_concentrations = {
                s: (v / total_value * 100) for s, v in sector_values.items()
            }

        max_position = max(position_concentrations.values()) if position_concentrations else 0.0
        max_sector = max(sector_concentrations.values()) if sector_concentrations else 0.0

        compliant = max_position <= self._concentration_limit and max_sector <= self._sector_limit

        report = ConcentrationReport(
            compliant=compliant,
            max_single_position_pct=max_position,
            max_sector_pct=max_sector,
            position_concentrations=position_concentrations,
            sector_concentrations=sector_concentrations,
            limit_pct=self._concentration_limit,
            sector_limit_pct=self._sector_limit,
        )

        if not compliant:
            await self._create_audit_record(
                action="concentration_violation",
                actor="compliance_engine",
                details={"account_id": account_id, "max_pct": max_position},
                status=ComplianceStatus.WARNING,
                violations=[ViolationType.CONCENTRATION],
            )

        return report

    async def generate_audit_record(self, action: str, details: Dict[str, Any],
                                     actor: str = "system",
                                     status: ComplianceStatus = ComplianceStatus.COMPLIANT,
                                     violations: Optional[List[ViolationType]] = None) -> AuditRecord:
        """Create an audit trail entry."""
        return await self._create_audit_record(action, actor, details, status, violations)

    async def _create_audit_record(self, action: str, actor: str, details: Dict[str, Any],
                                    status: ComplianceStatus = ComplianceStatus.COMPLIANT,
                                    violations: Optional[List[ViolationType]] = None) -> AuditRecord:
        record = AuditRecord(
            action=action,
            actor=actor,
            details=details,
            compliance_status=status,
            violations=violations or [],
        )
        self._audit_records.append(record)
        self._logger.info(f"audit_record: {action} by {actor} - {status.value}")
        return record

    async def generate_daily_report(self, account_id: str,
                                     account_equity: float = 0.0,
                                     positions: Optional[Dict[str, float]] = None,
                                     sectors: Optional[Dict[str, str]] = None) -> ComplianceReport:
        """Generate end-of-day compliance report."""
        pdt = await self.check_pattern_day_trader(account_id)
        margin = await self.check_reg_t_margin(account_id, account_equity, positions or {})
        concentration = await self.check_position_concentration(account_id, positions or {}, sectors)

        violations = []
        overall_status = ComplianceStatus.COMPLIANT

        if pdt.is_pdt:
            violations.append({"type": ViolationType.PDT, "details": pdt.details})
            overall_status = ComplianceStatus.WARNING

        if not margin.compliant:
            violations.append({"type": ViolationType.MARGIN, "details": margin.details})
            overall_status = ComplianceStatus.VIOLATION

        if not concentration.compliant:
            violations.append({"type": ViolationType.CONCENTRATION, "details": "Concentration limit exceeded"})
            if overall_status == ComplianceStatus.COMPLIANT:
                overall_status = ComplianceStatus.WARNING

        return ComplianceReport(
            account_id=account_id,
            report_date=datetime.now(timezone.utc),
            overall_status=overall_status,
            pdt_status=pdt,
            margin_status=margin,
            concentration_report=concentration,
            violations=violations,
            audit_records=list(self._audit_records),
        )

    def get_audit_records(self, limit: int = 100) -> List[AuditRecord]:
        """Get recent audit records."""
        return self._audit_records[-limit:]

    def get_trades(self, account_id: str) -> List[TradeRecord]:
        """Get trades for an account."""
        return self._trades.get(account_id, [])
