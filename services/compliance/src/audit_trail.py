"""Immutable Audit Trail for trading decisions and actions.

Provides append-only, hash-chained audit records with integrity verification,
time-range querying, and tamper detection.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AuditAction(Enum):
    """Enumerated audit event types for trading system actions."""

    ORDER_SUBMITTED = "order_submitted"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    RISK_CHECK = "risk_check"
    KILL_SWITCH = "kill_switch"
    CIRCUIT_BREAKER = "circuit_breaker"
    STRATEGY_SIGNAL = "strategy_signal"
    COMPLIANCE_CHECK = "compliance_check"
    CONFIGURATION_CHANGE = "configuration_change"
    SYSTEM_EVENT = "system_event"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass
class AuditRecord:
    """Immutable audit trail entry with hash chain verification."""

    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = ""
    actor: str = ""  # "system", "strategy:X", "user:Y", "risk_engine"
    details: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    checksum: str = ""
    previous_hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this record.

        The hash covers all mutable fields plus the previous hash link,
        making the record tamper-evident within the chain.
        """
        data = {
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "actor": self.actor,
            "details": self.details,
            "previous_hash": self.previous_hash,
        }
        raw = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class AuditFilter:
    """Filter criteria for querying audit records."""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    action: Optional[str] = None
    actor: Optional[str] = None
    symbol: Optional[str] = None
    limit: int = 100


@dataclass
class IntegrityReport:
    """Result of integrity verification."""

    is_valid: bool
    total_records: int
    verified_records: int
    first_invalid_index: Optional[int] = None
    first_invalid_record_id: Optional[str] = None
    details: str = ""
    broken_links: List[int] = field(default_factory=list)


class AuditStore:
    """In-memory storage for audit records.

    In production, this would be backed by PostgreSQL or similar
    append-only storage with write-once permissions.
    """

    def __init__(self) -> None:
        self._records: List[AuditRecord] = []

    async def persist(self, record: AuditRecord) -> None:
        """Persist an audit record."""
        self._records.append(record)

    async def get_all(self) -> List[AuditRecord]:
        """Get all records."""
        return list(self._records)

    async def get_last(self) -> Optional[AuditRecord]:
        """Get the last record (for hash chain linking)."""
        return self._records[-1] if self._records else None

    async def get_by_id(self, record_id: str) -> Optional[AuditRecord]:
        """Get record by ID."""
        for r in self._records:
            if r.record_id == record_id:
                return r
        return None

    async def count(self) -> int:
        """Return the total number of stored records."""
        return len(self._records)

    async def clear(self) -> None:
        """Clear all records (for testing only)."""
        self._records.clear()


class AuditTrail:
    """Immutable, append-only log of every trading decision and action.

    Each record is linked to the previous one via a SHA-256 hash chain,
    enabling tamper detection and integrity verification.
    """

    GENESIS_HASH = "0" * 64  # SHA-256 length zero hash

    def __init__(self, store: Optional[AuditStore] = None) -> None:
        self._store = store or AuditStore()
        self._logger = logging.getLogger(__name__)

    async def record(
        self,
        action: str,
        actor: str,
        details: Dict[str, Any],
        metadata: Optional[Dict] = None,
    ) -> AuditRecord:
        """Record an immutable audit entry.

        Links the new record to the previous one via the hash chain and
        computes its own checksum before persisting.
        """
        previous_record = await self._store.get_last()
        previous_hash = (
            previous_record.checksum if previous_record else self.GENESIS_HASH
        )

        rec = AuditRecord(
            action=action,
            actor=actor,
            details=details,
            metadata=metadata or {},
            previous_hash=previous_hash,
        )
        rec.checksum = rec.compute_hash()

        await self._store.persist(rec)
        self._logger.info(
            "audit_record: %s by %s [%s]", action, actor, rec.record_id[:8]
        )
        return rec

    async def verify_integrity(self) -> IntegrityReport:
        """Verify the chain of audit records has not been tampered with.

        Walks the hash chain and verifies each record's previous_hash
        links correctly and its checksum is valid.
        """
        records = await self._store.get_all()
        total = len(records)

        if total == 0:
            return IntegrityReport(
                is_valid=True,
                total_records=0,
                verified_records=0,
                details="Empty trail is valid",
            )

        broken_links: List[int] = []
        previous_hash = self.GENESIS_HASH

        for i, rec in enumerate(records):
            # Verify chain link
            if rec.previous_hash != previous_hash:
                broken_links.append(i)
                self._logger.error(
                    "Broken chain at index %d: expected %s... got %s...",
                    i,
                    previous_hash[:8],
                    rec.previous_hash[:8],
                )

            # Verify checksum
            expected_checksum = rec.compute_hash()
            if rec.checksum != expected_checksum:
                broken_links.append(i)

            previous_hash = rec.checksum

        is_valid = len(broken_links) == 0
        first_invalid = broken_links[0] if broken_links else None

        return IntegrityReport(
            is_valid=is_valid,
            total_records=total,
            verified_records=total - len(broken_links),
            first_invalid_index=first_invalid,
            first_invalid_record_id=(
                records[first_invalid].record_id
                if first_invalid is not None
                else None
            ),
            details=(
                "All records valid"
                if is_valid
                else f"{len(broken_links)} broken links found"
            ),
            broken_links=broken_links,
        )

    async def query(self, filters: AuditFilter) -> List[AuditRecord]:
        """Query audit records by time range, action type, actor, or symbol."""
        records = await self._store.get_all()

        if filters.start_time:
            records = [r for r in records if r.timestamp >= filters.start_time]
        if filters.end_time:
            records = [r for r in records if r.timestamp <= filters.end_time]
        if filters.action:
            records = [r for r in records if r.action == filters.action]
        if filters.actor:
            records = [r for r in records if r.actor == filters.actor]
        if filters.symbol:
            records = [
                r
                for r in records
                if filters.symbol in str(r.details.get("symbol", ""))
            ]

        return records[:filters.limit]

    async def get_record(self, record_id: str) -> Optional[AuditRecord]:
        """Get a specific record by ID."""
        return await self._store.get_by_id(record_id)

    async def count(self) -> int:
        """Get total number of records."""
        return await self._store.count()

    async def get_recent(self, limit: int = 10) -> List[AuditRecord]:
        """Get the most recent records."""
        records = await self._store.get_all()
        return records[-limit:]
