"""Financial and operational audit extract.

The SQL seal is ``lms.seal_audit_event`` (migration 0003). Nothing in
``src/lms`` inserts ``lms.audit_event`` (gap RX41). This log keeps the same
columns the seal hashes, assigns ``recognition_sequence`` per organisation
(decision 1), and verifies the chain on read.

The Python canonical uses a timezone-aware ISO timestamp and JSON with
sorted keys. PostgreSQL ``occurred_at::text`` and ``payload::text`` depend
on session settings that the row does not store (gap RX37). This verifier
checks rows sealed here. It does not claim to reproduce the trigger's text
cast.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping
from uuid import uuid4

from lms.regulatory.errors import RegulatoryError
from lms_config.calendar import value_date

_FINANCIAL = "financial"
_OPERATIONAL = "operational"


@dataclass(frozen=True)
class AuditRecord:
    organisation_id: str
    event_id: str
    occurred_at: datetime
    event_type: str
    category: str
    recognition_sequence: int
    amount_cents: int | None
    balance_code: str | None
    payload: dict
    previous_hash: bytes | None
    row_hash: bytes
    agreement_id: str | None = None
    enigma_person_id: str | None = None


@dataclass(frozen=True)
class AuditExtract:
    organisation_id: str
    from_date: date
    to_date: date
    rows: tuple[AuditRecord, ...]
    predecessor_row_hash: bytes | None
    predecessor_recognition_sequence: int | None
    links_ok: bool
    hashes_ok: bool
    verified: bool
    head_covered: bool
    chain_head_last_hash: bytes | None
    chain_head_last_sequence: int | None


class AuditLog:
    """Append-only log. Callers do not choose ``recognition_sequence`` or the hashes."""

    def __init__(self) -> None:
        self._rows: list[AuditRecord] = []
        self._next: dict[str, int] = {}

    def append(
        self,
        *,
        organisation_id: str,
        occurred_at: datetime,
        event_type: str,
        category: str,
        amount_cents: int | None = None,
        balance_code: str | None = None,
        payload: Mapping[str, object] | None = None,
        agreement_id: str | None = None,
        enigma_person_id: str | None = None,
    ) -> AuditRecord:
        if not organisation_id:
            raise RegulatoryError("organisation-unset", "An audit row needs an organisation id.")
        if occurred_at.tzinfo is None:
            raise RegulatoryError(
                "timestamp-naive",
                "Decision 1: occurred_at must be timezone-aware so the Johannesburg day is known.",
            )
        if category == _FINANCIAL and amount_cents is None:
            raise RegulatoryError(
                "amount-required",
                "A financial audit event requires amount_cents.",
            )
        if category == _OPERATIONAL and amount_cents is not None:
            raise RegulatoryError(
                "amount-forbidden",
                "An operational audit event must not carry amount_cents.",
            )
        if category not in {_FINANCIAL, _OPERATIONAL}:
            raise RegulatoryError("category-unset", f"Unknown audit category {category!r}.")
        if not event_type:
            raise RegulatoryError("event-type-unset", "An audit row needs an event type.")
        body = dict(payload or {})
        sequence = self._next.get(organisation_id, 1)
        previous = self._last(organisation_id)
        previous_hash = None if previous is None else previous.row_hash
        event_id = str(uuid4())
        row_hash = hash_row(
            organisation_id=organisation_id,
            event_id=event_id,
            previous_hash=previous_hash,
            event_type=event_type,
            occurred_at=occurred_at,
            amount_cents=amount_cents,
            balance_code=balance_code,
            recognition_sequence=sequence,
            payload=body,
        )
        record = AuditRecord(
            organisation_id=organisation_id,
            event_id=event_id,
            occurred_at=occurred_at,
            event_type=event_type,
            category=category,
            recognition_sequence=sequence,
            amount_cents=amount_cents,
            balance_code=balance_code,
            payload=body,
            previous_hash=previous_hash,
            row_hash=row_hash,
            agreement_id=agreement_id,
            enigma_person_id=enigma_person_id,
        )
        self._rows.append(record)
        self._next[organisation_id] = sequence + 1
        return record

    def extract(
        self,
        *,
        organisation_id: str,
        from_date: date,
        to_date: date,
    ) -> AuditExtract:
        """Rows for one organisation whose Johannesburg day is inside the inclusive range."""
        if not organisation_id:
            raise RegulatoryError("organisation-unset", "The audit extract needs an organisation id.")
        if from_date > to_date:
            raise RegulatoryError("date-range", "The audit date range ends before it starts.")
        chain = self._chain(organisation_id)
        selected = tuple(
            row
            for row in chain
            if from_date <= value_date(row.occurred_at) <= to_date
        )
        predecessor = None
        if selected:
            first = selected[0].recognition_sequence
            if first > 1:
                predecessor = chain[first - 2]
        elif chain:
            predecessor = None
        links_ok, hashes_ok = _verify(selected, predecessor)
        head = chain[-1] if chain else None
        head_covered = (not chain) or (bool(selected) and selected[-1].recognition_sequence == chain[-1].recognition_sequence)
        return AuditExtract(
            organisation_id=organisation_id,
            from_date=from_date,
            to_date=to_date,
            rows=selected,
            predecessor_row_hash=None if predecessor is None else predecessor.row_hash,
            predecessor_recognition_sequence=None if predecessor is None else predecessor.recognition_sequence,
            links_ok=links_ok,
            hashes_ok=hashes_ok,
            verified=links_ok and hashes_ok,
            head_covered=head_covered,
            chain_head_last_hash=None if head is None else head.row_hash,
            chain_head_last_sequence=None if head is None else head.recognition_sequence,
        )

    def _chain(self, organisation_id: str) -> tuple[AuditRecord, ...]:
        return tuple(
            row for row in self._rows if row.organisation_id == organisation_id
        )

    def _last(self, organisation_id: str) -> AuditRecord | None:
        chain = self._chain(organisation_id)
        if not chain:
            return None
        return chain[-1]


def hash_row(
    *,
    organisation_id: str,
    event_id: str,
    previous_hash: bytes | None,
    event_type: str,
    occurred_at: datetime,
    amount_cents: int | None,
    balance_code: str | None,
    recognition_sequence: int,
    payload: Mapping[str, object],
) -> bytes:
    """SHA-256 over the seal fields. See the module note for gap RX37."""
    previous = "" if previous_hash is None else previous_hash.hex()
    amount = "" if amount_cents is None else str(amount_cents)
    balance = "" if balance_code is None else balance_code
    payload_text = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    canonical = "|".join(
        (
            organisation_id,
            event_id,
            previous,
            event_type,
            occurred_at.isoformat(),
            amount,
            balance,
            str(recognition_sequence),
            payload_text,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _verify(
    rows: tuple[AuditRecord, ...],
    predecessor: AuditRecord | None,
) -> tuple[bool, bool]:
    links_ok = True
    hashes_ok = True
    previous_hash = None if predecessor is None else predecessor.row_hash
    previous_sequence = 0 if predecessor is None else predecessor.recognition_sequence
    for row in rows:
        if row.recognition_sequence != previous_sequence + 1:
            links_ok = False
        if row.previous_hash != previous_hash:
            links_ok = False
        recomputed = hash_row(
            organisation_id=row.organisation_id,
            event_id=row.event_id,
            previous_hash=row.previous_hash,
            event_type=row.event_type,
            occurred_at=row.occurred_at,
            amount_cents=row.amount_cents,
            balance_code=row.balance_code,
            recognition_sequence=row.recognition_sequence,
            payload=row.payload,
        )
        if recomputed != row.row_hash:
            hashes_ok = False
        previous_hash = row.row_hash
        previous_sequence = row.recognition_sequence
    return links_ok, hashes_ok
