"""Comprehensive unit tests for the Immutable Audit Trail.

Tests cover:
- AuditRecord creation, defaults, and hash computation
- AuditTrail hash chaining and integrity verification
- Query filtering by action, actor, time range, symbol, and limit
- AuditStore persistence and retrieval
- AuditFilter defaults
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Load the audit_trail module via importlib so tests work without a package
# installed.  This follows the same pattern used in conftest.py for
# risk-manager and ai-assistant modules.
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_audit_trail_path = os.path.join(
    _project_root, "services", "compliance", "src", "audit_trail.py"
)

_spec = importlib.util.spec_from_file_location("audit_trail", _audit_trail_path)
_audit_trail_mod = importlib.util.module_from_spec(_spec)
sys.modules["audit_trail"] = _audit_trail_mod
_spec.loader.exec_module(_audit_trail_mod)

AuditAction = _audit_trail_mod.AuditAction
AuditRecord = _audit_trail_mod.AuditRecord
AuditFilter = _audit_trail_mod.AuditFilter
IntegrityReport = _audit_trail_mod.IntegrityReport
AuditStore = _audit_trail_mod.AuditStore
AuditTrail = _audit_trail_mod.AuditTrail


# ---------------------------------------------------------------------------
# TestAuditRecord
# ---------------------------------------------------------------------------


class TestAuditRecord:
    """Tests for AuditRecord dataclass and hash computation."""

    def test_audit_record_creation(self):
        rec = AuditRecord(
            action="order_submitted",
            actor="system",
            details={"symbol": "AAPL", "qty": 100},
        )
        assert rec.action == "order_submitted"
        assert rec.actor == "system"
        assert rec.details == {"symbol": "AAPL", "qty": 100}

    def test_audit_record_defaults(self):
        rec = AuditRecord()
        assert rec.record_id != ""
        assert len(rec.record_id) == 32  # uuid4 hex
        assert rec.timestamp.tzinfo is not None  # timezone-aware
        assert rec.action == ""
        assert rec.actor == ""
        assert rec.details == {}
        assert rec.metadata == {}
        assert rec.checksum == ""
        assert rec.previous_hash == ""

    def test_compute_hash_deterministic(self):
        rec = AuditRecord(
            record_id="abc123",
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            action="test",
            actor="system",
            details={"key": "value"},
            previous_hash="0000",
        )
        hash_a = rec.compute_hash()
        hash_b = rec.compute_hash()
        assert hash_a == hash_b

    def test_compute_hash_different_for_different_data(self):
        rec_a = AuditRecord(
            record_id="id1",
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            action="action_a",
            actor="system",
        )
        rec_b = AuditRecord(
            record_id="id2",
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            action="action_b",
            actor="system",
        )
        assert rec_a.compute_hash() != rec_b.compute_hash()

    def test_compute_hash_changes_with_previous_hash(self):
        base = AuditRecord(
            record_id="fixed",
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            action="test",
            actor="system",
        )
        base.previous_hash = "aaa"
        hash_a = base.compute_hash()

        base.previous_hash = "bbb"
        hash_b = base.compute_hash()

        assert hash_a != hash_b


# ---------------------------------------------------------------------------
# TestAuditTrail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """Tests for AuditTrail recording and integrity verification."""

    @pytest.mark.asyncio
    async def test_record_creates_entry(self):
        trail = AuditTrail()
        await trail.record("order_submitted", "system", {"symbol": "AAPL"})
        assert await trail.count() == 1

    @pytest.mark.asyncio
    async def test_record_returns_audit_record(self):
        trail = AuditTrail()
        rec = await trail.record("order_submitted", "system", {"symbol": "AAPL"})
        assert isinstance(rec, AuditRecord)
        assert rec.action == "order_submitted"
        assert rec.actor == "system"

    @pytest.mark.asyncio
    async def test_record_has_checksum(self):
        trail = AuditTrail()
        rec = await trail.record("order_submitted", "system", {})
        assert rec.checksum != ""
        assert len(rec.checksum) == 64  # SHA-256 hex digest

    @pytest.mark.asyncio
    async def test_record_has_previous_hash(self):
        trail = AuditTrail()
        rec = await trail.record("order_submitted", "system", {})
        assert rec.previous_hash != ""

    @pytest.mark.asyncio
    async def test_first_record_has_genesis_hash(self):
        trail = AuditTrail()
        rec = await trail.record("order_submitted", "system", {})
        assert rec.previous_hash == "0" * 64

    @pytest.mark.asyncio
    async def test_chain_links_correctly(self):
        trail = AuditTrail()
        first = await trail.record("action_a", "system", {})
        second = await trail.record("action_b", "system", {})
        assert second.previous_hash == first.checksum

    @pytest.mark.asyncio
    async def test_multiple_records_chain(self):
        trail = AuditTrail()
        records = []
        for i in range(5):
            rec = await trail.record(f"action_{i}", "system", {"i": i})
            records.append(rec)

        for i in range(1, len(records)):
            assert records[i].previous_hash == records[i - 1].checksum

        assert await trail.count() == 5

    @pytest.mark.asyncio
    async def test_verify_integrity_empty_trail(self):
        trail = AuditTrail()
        report = await trail.verify_integrity()
        assert report.is_valid is True
        assert report.total_records == 0
        assert report.verified_records == 0

    @pytest.mark.asyncio
    async def test_verify_integrity_valid_chain(self):
        trail = AuditTrail()
        for i in range(3):
            await trail.record(f"action_{i}", "system", {})

        report = await trail.verify_integrity()
        assert report.is_valid is True
        assert report.total_records == 3
        assert report.verified_records == 3
        assert report.broken_links == []

    @pytest.mark.asyncio
    async def test_verify_integrity_tampered_record(self):
        trail = AuditTrail()
        rec = await trail.record("original", "system", {"val": 1})
        # Tamper with the record's action after it was persisted
        store_records = await trail._store.get_all()
        store_records[0].action = "tampered"

        report = await trail.verify_integrity()
        assert report.is_valid is False
        assert report.first_invalid_index == 0
        assert report.first_invalid_record_id == rec.record_id

    @pytest.mark.asyncio
    async def test_verify_integrity_broken_link(self):
        trail = AuditTrail()
        first = await trail.record("action_a", "system", {})
        await trail.record("action_b", "system", {})

        # Tamper with the chain link of the second record
        store_records = await trail._store.get_all()
        store_records[1].previous_hash = "broken_hash_value"

        report = await trail.verify_integrity()
        assert report.is_valid is False
        assert report.first_invalid_index == 1
        assert len(report.broken_links) > 0


# ---------------------------------------------------------------------------
# TestAuditTrailQuery
# ---------------------------------------------------------------------------


class TestAuditTrailQuery:
    """Tests for AuditTrail query and retrieval operations."""

    @pytest.mark.asyncio
    async def test_query_by_action(self):
        trail = AuditTrail()
        await trail.record("order_submitted", "system", {"symbol": "AAPL"})
        await trail.record("order_filled", "system", {"symbol": "AAPL"})
        await trail.record("order_submitted", "system", {"symbol": "MSFT"})

        results = await trail.query(AuditFilter(action="order_submitted"))
        assert len(results) == 2
        assert all(r.action == "order_submitted" for r in results)

    @pytest.mark.asyncio
    async def test_query_by_actor(self):
        trail = AuditTrail()
        await trail.record("action", "strategy:alpha", {})
        await trail.record("action", "strategy:beta", {})
        await trail.record("action", "strategy:alpha", {})

        results = await trail.query(AuditFilter(actor="strategy:alpha"))
        assert len(results) == 2
        assert all(r.actor == "strategy:alpha" for r in results)

    @pytest.mark.asyncio
    async def test_query_by_time_range(self):
        trail = AuditTrail()
        now = datetime.now(timezone.utc)

        # Manually construct records with specific timestamps
        rec_a = AuditRecord(
            timestamp=now - timedelta(hours=2),
            action="old",
            actor="system",
            details={},
        )
        rec_a.previous_hash = AuditTrail.GENESIS_HASH
        rec_a.checksum = rec_a.compute_hash()
        await trail._store.persist(rec_a)

        rec_b = AuditRecord(
            timestamp=now - timedelta(hours=1),
            action="recent",
            actor="system",
            details={},
        )
        rec_b.previous_hash = rec_a.checksum
        rec_b.checksum = rec_b.compute_hash()
        await trail._store.persist(rec_b)

        rec_c = AuditRecord(
            timestamp=now,
            action="now",
            actor="system",
            details={},
        )
        rec_c.previous_hash = rec_b.checksum
        rec_c.checksum = rec_c.compute_hash()
        await trail._store.persist(rec_c)

        # Query for records in the last 90 minutes
        start = now - timedelta(minutes=90)
        results = await trail.query(AuditFilter(start_time=start))
        assert len(results) == 2
        assert results[0].action == "recent"
        assert results[1].action == "now"

    @pytest.mark.asyncio
    async def test_query_by_symbol(self):
        trail = AuditTrail()
        await trail.record("order_submitted", "system", {"symbol": "AAPL"})
        await trail.record("order_submitted", "system", {"symbol": "MSFT"})
        await trail.record("order_submitted", "system", {"symbol": "AAPL"})

        results = await trail.query(AuditFilter(symbol="AAPL"))
        assert len(results) == 2
        assert all("AAPL" in str(r.details.get("symbol", "")) for r in results)

    @pytest.mark.asyncio
    async def test_query_limit(self):
        trail = AuditTrail()
        for i in range(10):
            await trail.record("action", "system", {"i": i})

        results = await trail.query(AuditFilter(limit=3))
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_query_no_filters(self):
        trail = AuditTrail()
        for i in range(5):
            await trail.record("action", "system", {"i": i})

        results = await trail.query(AuditFilter())
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_get_record_by_id(self):
        trail = AuditTrail()
        rec = await trail.record("order_submitted", "system", {"symbol": "AAPL"})

        found = await trail.get_record(rec.record_id)
        assert found is not None
        assert found.record_id == rec.record_id

    @pytest.mark.asyncio
    async def test_get_record_not_found(self):
        trail = AuditTrail()
        found = await trail.get_record("nonexistent_id")
        assert found is None

    @pytest.mark.asyncio
    async def test_count(self):
        trail = AuditTrail()
        assert await trail.count() == 0

        await trail.record("action", "system", {})
        assert await trail.count() == 1

        await trail.record("action", "system", {})
        assert await trail.count() == 2

    @pytest.mark.asyncio
    async def test_get_recent(self):
        trail = AuditTrail()
        for i in range(20):
            await trail.record(f"action_{i}", "system", {"i": i})

        recent = await trail.get_recent(limit=5)
        assert len(recent) == 5
        # Should be the last 5 records
        assert recent[-1].action == "action_19"
        assert recent[0].action == "action_15"

    @pytest.mark.asyncio
    async def test_get_recent_default_limit(self):
        trail = AuditTrail()
        for i in range(20):
            await trail.record(f"action_{i}", "system", {"i": i})

        recent = await trail.get_recent()
        assert len(recent) == 10  # default limit
        assert recent[-1].action == "action_19"


# ---------------------------------------------------------------------------
# TestAuditStore
# ---------------------------------------------------------------------------


class TestAuditStore:
    """Tests for the in-memory AuditStore."""

    @pytest.mark.asyncio
    async def test_store_persist_and_retrieve(self):
        store = AuditStore()
        rec = AuditRecord(action="test", actor="system", details={})
        await store.persist(rec)

        all_records = await store.get_all()
        assert len(all_records) == 1
        assert all_records[0].action == "test"

    @pytest.mark.asyncio
    async def test_store_get_last_empty(self):
        store = AuditStore()
        result = await store.get_last()
        assert result is None

    @pytest.mark.asyncio
    async def test_store_get_last(self):
        store = AuditStore()
        rec_a = AuditRecord(action="first", actor="system")
        rec_b = AuditRecord(action="second", actor="system")
        await store.persist(rec_a)
        await store.persist(rec_b)

        last = await store.get_last()
        assert last is not None
        assert last.action == "second"

    @pytest.mark.asyncio
    async def test_store_count(self):
        store = AuditStore()
        assert await store.count() == 0

        await store.persist(AuditRecord(action="a", actor="system"))
        assert await store.count() == 1

        await store.persist(AuditRecord(action="b", actor="system"))
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_store_clear(self):
        store = AuditStore()
        await store.persist(AuditRecord(action="a", actor="system"))
        await store.persist(AuditRecord(action="b", actor="system"))
        assert await store.count() == 2

        await store.clear()
        assert await store.count() == 0


# ---------------------------------------------------------------------------
# TestAuditFilter
# ---------------------------------------------------------------------------


class TestAuditFilter:
    """Tests for AuditFilter defaults."""

    def test_audit_filter_defaults(self):
        f = AuditFilter()
        assert f.start_time is None
        assert f.end_time is None
        assert f.action is None
        assert f.actor is None
        assert f.symbol is None
        assert f.limit == 100
