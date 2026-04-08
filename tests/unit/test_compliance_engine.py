"""Unit tests for the Compliance Engine.

Tests cover Pattern Day Trader detection, wash sale monitoring, Reg T margin
verification, position concentration limits, audit trail generation, and
daily compliance reporting.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from compliance_engine import (
    AuditRecord,
    ComplianceEngine,
    ComplianceReport,
    ComplianceStatus,
    ConcentrationReport,
    MarginStatus,
    PDTStatus,
    TradeRecord,
    ViolationType,
    WashSaleResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trade(
    account_id="ACCT1",
    symbol="AAPL",
    side="buy",
    quantity=100,
    price=150.0,
    trade_type="day_trade",
    days_ago=0,
):
    """Create a TradeRecord with sensible defaults for testing."""
    return TradeRecord(
        trade_id=uuid.uuid4().hex[:8],
        account_id=account_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        trade_type=trade_type,
    )


# ===================================================================
# TestTradeRecord
# ===================================================================


class TestTradeRecord:
    """Tests for the TradeRecord dataclass."""

    def test_trade_record_creation(self):
        """TradeRecord stores all fields correctly."""
        now = datetime.now(timezone.utc)
        trade = TradeRecord(
            trade_id="T001",
            account_id="ACCT1",
            symbol="AAPL",
            side="buy",
            quantity=100,
            price=150.0,
            timestamp=now,
        )
        assert trade.trade_id == "T001"
        assert trade.account_id == "ACCT1"
        assert trade.symbol == "AAPL"
        assert trade.side == "buy"
        assert trade.quantity == 100
        assert trade.price == 150.0
        assert trade.timestamp == now
        assert trade.trade_type == "day_trade"  # default

    def test_trade_record_notional_value(self):
        """notional_value is quantity * price."""
        trade = TradeRecord(
            trade_id="T002",
            account_id="ACCT1",
            symbol="MSFT",
            side="sell",
            quantity=50,
            price=200.0,
            timestamp=datetime.now(timezone.utc),
        )
        assert trade.notional_value == 50 * 200.0


# ===================================================================
# TestPDTStatus
# ===================================================================


class TestPDTStatus:
    """Tests for the PDTStatus dataclass."""

    def test_pdt_status_creation(self):
        """PDTStatus stores fields with defaults."""
        status = PDTStatus(is_pdt=False, day_trade_count=2)
        assert status.is_pdt is False
        assert status.day_trade_count == 2
        assert status.rolling_window_days == 5
        assert status.threshold == 4
        assert status.details == ""
        assert status.trades_in_window == []

    def test_pdt_not_pdt(self):
        """Below threshold is not PDT."""
        status = PDTStatus(is_pdt=False, day_trade_count=3, threshold=4)
        assert not status.is_pdt

    def test_pdt_is_pdt(self):
        """At or above threshold triggers PDT."""
        status = PDTStatus(is_pdt=True, day_trade_count=5, threshold=4)
        assert status.is_pdt is True


# ===================================================================
# TestComplianceEngine
# ===================================================================


class TestComplianceEngine:
    """Tests for the ComplianceEngine class."""

    # -- Initialization --------------------------------------------------

    def test_initialization(self):
        """Default engine has sensible defaults."""
        engine = ComplianceEngine()
        assert engine._pdt_threshold == 4
        assert engine._pdt_window_days == 5
        assert engine._concentration_limit == 25.0
        assert engine._sector_limit == 40.0
        assert engine._trades == {}
        assert engine._audit_records == []

    def test_initialization_with_config(self):
        """Config overrides are respected."""
        config = {
            "pdt_threshold": 3,
            "pdt_window_days": 7,
            "concentration_limit": 20.0,
            "sector_limit": 35.0,
        }
        engine = ComplianceEngine(config=config)
        assert engine._pdt_threshold == 3
        assert engine._pdt_window_days == 7
        assert engine._concentration_limit == 20.0
        assert engine._sector_limit == 35.0

    # -- record_trade / get_trades ---------------------------------------

    def test_record_trade(self):
        """record_trade stores trades keyed by account_id."""
        engine = ComplianceEngine()
        trade = make_trade(account_id="ACCT1", symbol="AAPL")
        engine.record_trade(trade)
        assert len(engine.get_trades("ACCT1")) == 1
        assert engine.get_trades("ACCT1")[0].symbol == "AAPL"

    def test_get_trades(self):
        """get_trades returns all trades for an account."""
        engine = ComplianceEngine()
        engine.record_trade(make_trade(account_id="A", symbol="AAPL"))
        engine.record_trade(make_trade(account_id="A", symbol="MSFT"))
        engine.record_trade(make_trade(account_id="B", symbol="GOOG"))
        assert len(engine.get_trades("A")) == 2
        assert len(engine.get_trades("B")) == 1

    def test_get_trades_unknown_account(self):
        """Unknown account returns empty list."""
        engine = ComplianceEngine()
        assert engine.get_trades("NONEXISTENT") == []

    # -- Pattern Day Trader ----------------------------------------------

    @pytest.mark.asyncio
    async def test_check_pattern_day_trader_compliant(self):
        """Fewer than threshold day trades is compliant."""
        engine = ComplianceEngine()
        # 3 round-trip day trades (6 individual trades)
        for symbol in ["AAPL", "MSFT", "GOOG"]:
            engine.record_trade(make_trade(symbol=symbol, side="buy"))
            engine.record_trade(make_trade(symbol=symbol, side="sell"))

        status = await engine.check_pattern_day_trader("ACCT1")
        assert not status.is_pdt
        assert status.day_trade_count == 3

    @pytest.mark.asyncio
    async def test_check_pattern_day_trader_pdt(self):
        """4+ round-trip day trips triggers PDT status."""
        engine = ComplianceEngine()
        # 4 round-trip day trades
        for symbol in ["AAPL", "MSFT", "GOOG", "TSLA"]:
            engine.record_trade(make_trade(symbol=symbol, side="buy"))
            engine.record_trade(make_trade(symbol=symbol, side="sell"))

        status = await engine.check_pattern_day_trader("ACCT1")
        assert status.is_pdt is True
        assert status.day_trade_count == 4
        assert "PDT STATUS" in status.details

    @pytest.mark.asyncio
    async def test_check_pattern_day_trader_no_trades(self):
        """No trades means zero day-trade count."""
        engine = ComplianceEngine()
        status = await engine.check_pattern_day_trader("ACCT1")
        assert not status.is_pdt
        assert status.day_trade_count == 0

    @pytest.mark.asyncio
    async def test_check_pattern_day_trader_ignores_old_trades(self):
        """Trades outside the rolling window are excluded."""
        engine = ComplianceEngine(config={"pdt_window_days": 5})
        # 4 day trades that are 10 days old (outside window)
        for symbol in ["AAPL", "MSFT", "GOOG", "TSLA"]:
            engine.record_trade(make_trade(symbol=symbol, side="buy", days_ago=10))
            engine.record_trade(make_trade(symbol=symbol, side="sell", days_ago=10))
        # 1 recent day trade
        engine.record_trade(make_trade(symbol="AMZN", side="buy", days_ago=0))
        engine.record_trade(make_trade(symbol="AMZN", side="sell", days_ago=0))

        status = await engine.check_pattern_day_trader("ACCT1")
        assert not status.is_pdt
        assert status.day_trade_count == 1

    # -- Wash Sale -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_check_wash_sale_detected(self):
        """Buy within 30 days of a sell triggers wash sale flag."""
        engine = ComplianceEngine()
        sell_trade = make_trade(side="sell", days_ago=5)
        buy_trade = make_trade(side="buy", days_ago=0)
        engine.record_trade(sell_trade)
        engine.record_trade(buy_trade)

        result = await engine.check_wash_sale("AAPL", "ACCT1")
        assert result.has_wash_sale is True
        assert result.symbol == "AAPL"
        assert result.loss_amount > 0
        assert result.replacement_trade is buy_trade

    @pytest.mark.asyncio
    async def test_check_wash_sale_not_detected(self):
        """No buy near a sell means no wash sale."""
        engine = ComplianceEngine()
        # Only buys, no sells -> no wash sale
        engine.record_trade(make_trade(side="buy", days_ago=0))
        engine.record_trade(make_trade(side="buy", days_ago=5))

        result = await engine.check_wash_sale("AAPL", "ACCT1")
        assert result.has_wash_sale is False

    @pytest.mark.asyncio
    async def test_check_wash_sale_no_trades(self):
        """No trades at all returns no wash sale."""
        engine = ComplianceEngine()
        result = await engine.check_wash_sale("AAPL", "ACCT1")
        assert result.has_wash_sale is False

    @pytest.mark.asyncio
    async def test_check_wash_sale_different_symbol(self):
        """Trades in a different symbol do not trigger wash sale."""
        engine = ComplianceEngine()
        engine.record_trade(make_trade(symbol="AAPL", side="sell", days_ago=5))
        engine.record_trade(make_trade(symbol="AAPL", side="buy", days_ago=0))

        result = await engine.check_wash_sale("MSFT", "ACCT1")
        assert result.has_wash_sale is False

    # -- Reg T Margin ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_check_reg_t_margin_compliant(self):
        """Sufficient equity is compliant."""
        engine = ComplianceEngine()
        positions = {"AAPL": 10000.0, "MSFT": 10000.0}
        status = await engine.check_reg_t_margin("ACCT1", account_equity=100000.0, positions=positions)
        assert status.compliant is True
        assert status.margin_available > 0

    @pytest.mark.asyncio
    async def test_check_reg_t_margin_violation(self):
        """Insufficient equity triggers margin violation."""
        engine = ComplianceEngine()
        positions = {"AAPL": 60000.0}
        status = await engine.check_reg_t_margin("ACCT1", account_equity=20000.0, positions=positions)
        assert status.compliant is False
        assert "Margin call" in status.details

    @pytest.mark.asyncio
    async def test_check_reg_t_margin_short_positions(self):
        """Short positions contribute to margin requirement."""
        engine = ComplianceEngine()
        positions = {"AAPL": 50000.0, "TSLA": -30000.0}
        status = await engine.check_reg_t_margin("ACCT1", account_equity=100000.0, positions=positions)
        # Long 50k + Short 30k = 80k total; initial 50% = 40k requirement
        assert status.compliant is True
        assert status.reg_t_requirement == 80000.0 * 0.50

    @pytest.mark.asyncio
    async def test_check_reg_t_margin_empty_positions(self):
        """No positions means zero margin used."""
        engine = ComplianceEngine()
        status = await engine.check_reg_t_margin("ACCT1", account_equity=50000.0, positions={})
        assert status.compliant is True
        assert status.margin_used == 0.0
        assert status.margin_available == 50000.0

    # -- Position Concentration ------------------------------------------

    @pytest.mark.asyncio
    async def test_check_position_concentration_compliant(self):
        """Well-diversified positions pass concentration check."""
        engine = ComplianceEngine()
        positions = {"AAPL": 25000.0, "MSFT": 25000.0, "GOOG": 25000.0, "TSLA": 25000.0}
        report = await engine.check_position_concentration("ACCT1", positions)
        assert report.compliant is True
        assert report.max_single_position_pct == 25.0

    @pytest.mark.asyncio
    async def test_check_position_concentration_violation(self):
        """One position exceeding limit triggers violation."""
        engine = ComplianceEngine()
        positions = {"AAPL": 80000.0, "MSFT": 10000.0, "GOOG": 10000.0}
        report = await engine.check_position_concentration("ACCT1", positions)
        assert report.compliant is False
        assert report.max_single_position_pct == 80.0

    @pytest.mark.asyncio
    async def test_check_position_concentration_with_sectors(self):
        """Sector concentration is checked when sector mapping provided."""
        engine = ComplianceEngine(config={"sector_limit": 50.0})
        positions = {"AAPL": 30000.0, "MSFT": 30000.0, "XOM": 20000.0, "JPM": 20000.0}
        sectors = {"AAPL": "tech", "MSFT": "tech", "XOM": "energy", "JPM": "finance"}
        report = await engine.check_position_concentration("ACCT1", positions, sectors)
        assert report.sector_concentrations["tech"] == 60.0
        assert report.sector_concentrations["energy"] == 20.0
        assert report.sector_concentrations["finance"] == 20.0
        # tech at 60% > 50% sector limit -> violation
        assert report.compliant is False

    @pytest.mark.asyncio
    async def test_check_position_concentration_empty(self):
        """No positions returns compliant report."""
        engine = ComplianceEngine()
        report = await engine.check_position_concentration("ACCT1", {})
        assert report.compliant is True

    # -- Audit Records ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_generate_audit_record(self):
        """generate_audit_record creates and stores an AuditRecord."""
        engine = ComplianceEngine()
        record = await engine.generate_audit_record(
            action="manual_review",
            details={"reason": "suspicious_activity"},
            actor="compliance_officer",
            status=ComplianceStatus.WARNING,
            violations=[ViolationType.TRADE_LIMIT],
        )
        assert record.action == "manual_review"
        assert record.actor == "compliance_officer"
        assert record.compliance_status == ComplianceStatus.WARNING
        assert ViolationType.TRADE_LIMIT in record.violations
        assert record in engine.get_audit_records()

    def test_get_audit_records(self):
        """get_audit_records returns stored records."""
        engine = ComplianceEngine()
        # Manually append records (bypassing async helper)
        engine._audit_records.append(
            AuditRecord(action="test1", actor="system", details={})
        )
        engine._audit_records.append(
            AuditRecord(action="test2", actor="system", details={})
        )
        records = engine.get_audit_records()
        assert len(records) == 2

    def test_get_audit_records_limit(self):
        """get_audit_records respects the limit parameter."""
        engine = ComplianceEngine()
        for i in range(10):
            engine._audit_records.append(
                AuditRecord(action=f"action_{i}", actor="system", details={})
            )
        records = engine.get_audit_records(limit=3)
        assert len(records) == 3
        # Should return the last 3
        assert records[0].action == "action_7"
        assert records[1].action == "action_8"
        assert records[2].action == "action_9"

    # -- Daily Report ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_generate_daily_report_compliant(self):
        """Clean account produces a compliant daily report."""
        engine = ComplianceEngine()
        report = await engine.generate_daily_report(
            account_id="ACCT1",
            account_equity=100000.0,
            positions={
                "AAPL": 20000.0, "MSFT": 20000.0, "GOOG": 20000.0,
                "TSLA": 20000.0, "AMZN": 20000.0,
            },
        )
        assert report.overall_status == ComplianceStatus.COMPLIANT
        assert report.account_id == "ACCT1"
        assert report.pdt_status is not None
        assert report.margin_status is not None
        assert report.concentration_report is not None
        assert len(report.violations) == 0

    @pytest.mark.asyncio
    async def test_generate_daily_report_with_violations(self):
        """Account with violations produces a report with issues."""
        engine = ComplianceEngine()
        # Create PDT condition (4+ day-trade round trips)
        for symbol in ["AAPL", "MSFT", "GOOG", "TSLA"]:
            engine.record_trade(make_trade(symbol=symbol, side="buy"))
            engine.record_trade(make_trade(symbol=symbol, side="sell"))

        # Create concentration violation (AAPL is 80% of portfolio)
        report = await engine.generate_daily_report(
            account_id="ACCT1",
            account_equity=20000.0,
            positions={"AAPL": 80000.0, "MSFT": 20000.0},
        )
        assert report.overall_status in (ComplianceStatus.WARNING, ComplianceStatus.VIOLATION)
        assert len(report.violations) >= 1

    @pytest.mark.asyncio
    async def test_generate_daily_report_margin_violation(self):
        """Margin violation sets overall status to VIOLATION."""
        engine = ComplianceEngine()
        report = await engine.generate_daily_report(
            account_id="ACCT1",
            account_equity=10000.0,
            positions={"AAPL": 60000.0},
        )
        assert report.overall_status == ComplianceStatus.VIOLATION
        assert any(v["type"] == ViolationType.MARGIN for v in report.violations)

    # -- Dataclass defaults / enums --------------------------------------

    def test_margin_status_dataclass(self):
        """MarginStatus stores all fields correctly."""
        ms = MarginStatus(
            compliant=True,
            account_equity=100000.0,
            margin_used=25000.0,
            margin_available=75000.0,
            reg_t_requirement=25000.0,
            maintenance_requirement=12500.0,
            details="Compliant",
        )
        assert ms.compliant is True
        assert ms.account_equity == 100000.0
        assert ms.margin_available == 75000.0

    def test_concentration_report_dataclass(self):
        """ConcentrationReport stores all fields correctly."""
        cr = ConcentrationReport(
            compliant=False,
            max_single_position_pct=30.0,
            max_sector_pct=50.0,
            position_concentrations={"AAPL": 30.0, "MSFT": 20.0},
            sector_concentrations={"tech": 50.0},
        )
        assert cr.compliant is False
        assert cr.max_single_position_pct == 30.0
        assert "AAPL" in cr.position_concentrations

    def test_compliance_report_dataclass(self):
        """ComplianceReport stores all fields correctly."""
        report = ComplianceReport(
            account_id="ACCT1",
            report_date=datetime.now(timezone.utc),
            overall_status=ComplianceStatus.WARNING,
            violations=[{"type": ViolationType.PDT, "details": "test"}],
        )
        assert report.account_id == "ACCT1"
        assert report.overall_status == ComplianceStatus.WARNING
        assert len(report.violations) == 1

    def test_violation_type_enum(self):
        """ViolationType enum has all expected members."""
        assert ViolationType.PDT.value == "pattern_day_trader"
        assert ViolationType.WASH_SALE.value == "wash_sale"
        assert ViolationType.MARGIN.value == "margin_violation"
        assert ViolationType.CONCENTRATION.value == "concentration_limit"
        assert ViolationType.POSITION_LIMIT.value == "position_limit"
        assert ViolationType.TRADE_LIMIT.value == "trade_limit"

    def test_compliance_status_enum(self):
        """ComplianceStatus enum has all expected members."""
        assert ComplianceStatus.COMPLIANT.value == "compliant"
        assert ComplianceStatus.WARNING.value == "warning"
        assert ComplianceStatus.VIOLATION.value == "violation"

    def test_audit_record_defaults(self):
        """AuditRecord auto-generates id and timestamp."""
        record = AuditRecord(action="test", actor="unit_test", details={"key": "value"})
        assert record.record_id  # non-empty hex string
        assert record.timestamp is not None
        assert record.compliance_status == ComplianceStatus.COMPLIANT

    def test_wash_sale_result_defaults(self):
        """WashSaleResult has sensible defaults."""
        result = WashSaleResult(has_wash_sale=False, symbol="AAPL")
        assert result.loss_amount == 0.0
        assert result.disallowed_loss == 0.0
        assert result.replacement_trade is None
        assert result.original_loss_trade is None
        assert result.wash_period_days == 30
