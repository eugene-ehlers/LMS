"""Financial and operational audit extract.

``read_lms_audit_event`` reads ``lms.audit_event`` for one organisation and
an inclusive Johannesburg range on ``occurred_at``, ordered by
``recognition_sequence``. The hash check is the migration 0003 seal
expression, executed by the database. This module does not reimplement that
expression in Python and does not open a connection. The caller passes
``execute(sql, params)``.

The in-process hook is ``Servicing.audit``, an ``AuditLog``. Servicing
appends on book (``AGREEMENT_STATUS_CHANGED``), a pre-disbursement Laybye
receipt (``DEPOSIT_RECEIVED``, balance code ``deposit``), grant
(``PRINCIPAL_ADVANCED``, balance code ``principal``), a payment
(``PAYMENT_ALLOCATED`` for the loan portion, and ``DEPOSIT_RECEIVED`` when
excess is credited to the Laybye), and statement issue
(``STATEMENT_ISSUED``). Collections appends ``AGREEMENT_STATUS_CHANGED``
when an in-duplum episode opens or closes. ``AuditLog.extract`` reads
those rows. Direct ``Ledger`` calls are not sealed unless the caller appends.
No Python path inserts ``lms.audit_event`` (gap RX41).

The Python canonical uses a timezone-aware ISO timestamp and JSON with
sorted keys. PostgreSQL ``occurred_at::text`` and ``payload::text`` depend
on session settings that the row does not store (gap RX37). ``AuditLog``
checks rows it sealed. It does not claim to reproduce the trigger's text
cast. Event types are the seeded codes. Financial rows carry
``amount_cents``. Operational rows do not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping
from uuid import uuid4

from lms.regulatory.errors import RegulatoryError
from lms_config.calendar import value_date, value_instant

_FINANCIAL = "financial"
_OPERATIONAL = "operational"


@dataclass(frozen=True)
class AuditRecord:
    organisation_id: str
    event_id: str
    occurred_at: datetime
    event_type: str
    category: str
    recognition_sequence: int | None
    amount_cents: int | None
    balance_code: str | None
    payload: dict
    previous_hash: bytes | None
    row_hash: bytes
    agreement_id: str | None = None
    enigma_person_id: str | None = None


@dataclass(frozen=True)
class AuditChainHead:
    """One ``lms.audit_chain_head`` row. The seal writes this. The extract only reads it."""

    last_event_id: str
    last_occurred_at: datetime
    last_hash: bytes
    last_sequence: int


@dataclass(frozen=True)
class AuditExtract:
    organisation_id: str
    from_date: date
    to_date: date
    rows: tuple[AuditRecord, ...]
    predecessor_event_id: str | None
    predecessor_row_hash: bytes | None
    predecessor_recognition_sequence: int | None
    links_ok: bool
    hashes_ok: bool
    verified: bool
    head_covered: bool
    chain_head_last_event_id: str | None
    chain_head_last_occurred_at: datetime | None
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
        if not organisation_id or not str(organisation_id).strip():
            raise RegulatoryError("organisation-unset", "The audit extract needs an organisation id.")
        _require_range(from_date, to_date)
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
        head_record = None if head is None else AuditChainHead(
            last_event_id=head.event_id,
            last_occurred_at=head.occurred_at,
            last_hash=head.row_hash,
            last_sequence=head.recognition_sequence,
        )
        return _assemble(
            organisation_id=organisation_id,
            from_date=from_date,
            to_date=to_date,
            rows=selected,
            predecessor=predecessor,
            chain_head=head_record,
            links_ok=links_ok,
            hashes_ok=hashes_ok,
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


def _require_range(from_date: date, to_date: date) -> None:
    if type(from_date) is not date or type(to_date) is not date:
        raise RegulatoryError("date-range", "The audit range must be Johannesburg calendar dates.")
    if from_date > to_date:
        raise RegulatoryError("date-range", "The audit date range ends before it starts.")


def audit_range_instants(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Inclusive Johannesburg dates as ``[start, end)`` instants (decision 1)."""

    _require_range(from_date, to_date)
    return value_instant(from_date), value_instant(to_date + timedelta(days=1))


def _assemble(
    *,
    organisation_id: str,
    from_date: date,
    to_date: date,
    rows: tuple[AuditRecord, ...],
    predecessor: AuditRecord | None,
    chain_head: AuditChainHead | None,
    links_ok: bool,
    hashes_ok: bool,
) -> AuditExtract:
    if rows and chain_head is None:
        links_ok = False
    head_covered = chain_head is not None and bool(rows) and rows[-1].recognition_sequence == chain_head.last_sequence
    if not rows and chain_head is None:
        head_covered = True
    return AuditExtract(
        organisation_id=organisation_id,
        from_date=from_date,
        to_date=to_date,
        rows=rows,
        predecessor_event_id=None if predecessor is None else predecessor.event_id,
        predecessor_row_hash=None if predecessor is None else predecessor.row_hash,
        predecessor_recognition_sequence=None if predecessor is None else predecessor.recognition_sequence,
        links_ok=links_ok,
        hashes_ok=hashes_ok,
        verified=links_ok and hashes_ok,
        head_covered=head_covered,
        chain_head_last_event_id=None if chain_head is None else chain_head.last_event_id,
        chain_head_last_occurred_at=None if chain_head is None else chain_head.last_occurred_at,
        chain_head_last_hash=None if chain_head is None else chain_head.last_hash,
        chain_head_last_sequence=None if chain_head is None else chain_head.last_sequence,
    )


# The digest expression is the migration 0003 seal. It is sent to the database.
# It is not evaluated in Python (gap RX37).
_SEAL_MATCH = """
    event.row_hash = public.digest(convert_to(concat_ws('|',
      event.organisation_id::text,
      event.event_id::text,
      coalesce(encode(event.previous_hash, 'hex'), ''),
      event.event_type,
      event.occurred_at::text,
      coalesce(event.amount_cents::text, ''),
      coalesce(event.balance_code, ''),
      event.recognition_sequence::text,
      event.payload::text
    ), 'UTF8'), 'sha256')
"""

AUDIT_EVENT_SQL = f"""
SELECT
  event.event_id::text AS event_id,
  event.organisation_id::text AS organisation_id,
  event.occurred_at,
  event.event_type,
  ref.category AS category,
  event.recognition_sequence,
  event.amount_cents,
  event.balance_code,
  event.payload,
  event.previous_hash,
  event.row_hash,
  event.agreement_id::text AS agreement_id,
  event.enigma_person_id::text AS enigma_person_id,
  ({_SEAL_MATCH}) AS hash_matches
FROM lms.audit_event AS event
JOIN lms.ref_audit_event_type AS ref ON ref.code = event.event_type
WHERE event.organisation_id = %(organisation_id)s
  AND event.occurred_at >= %(from_instant)s
  AND event.occurred_at < %(to_instant)s
ORDER BY event.recognition_sequence
"""

AUDIT_PREDECESSOR_SQL = """
SELECT
  event.event_id::text AS event_id,
  event.organisation_id::text AS organisation_id,
  event.occurred_at,
  event.event_type,
  ref.category AS category,
  event.recognition_sequence,
  event.amount_cents,
  event.balance_code,
  event.payload,
  event.previous_hash,
  event.row_hash,
  event.agreement_id::text AS agreement_id,
  event.enigma_person_id::text AS enigma_person_id
FROM lms.audit_event AS event
JOIN lms.ref_audit_event_type AS ref ON ref.code = event.event_type
WHERE event.organisation_id = %(organisation_id)s
  AND event.recognition_sequence < %(before_sequence)s
ORDER BY event.recognition_sequence DESC
LIMIT 1
"""

AUDIT_CHAIN_HEAD_SQL = """
SELECT
  last_event_id::text AS last_event_id,
  last_occurred_at,
  last_hash,
  last_sequence
FROM lms.audit_chain_head
WHERE organisation_id = %(organisation_id)s
"""


def read_lms_audit_event(execute, *, organisation_id: str, from_date: date, to_date: date) -> AuditExtract:
    """Read ``lms.audit_event`` and ``lms.audit_chain_head``.

    ``execute(sql, params)`` returns a sequence of mappings. Hash matches
    come back on ``hash_matches``. This function does not hash.
    """
    if not organisation_id or not str(organisation_id).strip():
        raise RegulatoryError("organisation-unset", "The audit extract needs an organisation id.")
    start, end = audit_range_instants(from_date, to_date)
    raw_rows = tuple(
        execute(
            AUDIT_EVENT_SQL,
            {
                "organisation_id": organisation_id,
                "from_instant": start,
                "to_instant": end,
            },
        )
    )
    rows = tuple(_record_from_query(item, organisation_id) for item in raw_rows)
    hashes_ok = all(_hash_matches(item) for item in raw_rows) if raw_rows else True
    predecessor = None
    if rows and rows[0].recognition_sequence not in (None, 1):
        found = tuple(
            execute(
                AUDIT_PREDECESSOR_SQL,
                {
                    "organisation_id": organisation_id,
                    "before_sequence": rows[0].recognition_sequence,
                },
            )
        )
        if len(found) > 1:
            raise RegulatoryError("predecessor-ambiguous", "The predecessor query returned more than one row.")
        if len(found) == 1:
            predecessor = _record_from_query(found[0], organisation_id)
    heads = tuple(execute(AUDIT_CHAIN_HEAD_SQL, {"organisation_id": organisation_id}))
    if len(heads) > 1:
        raise RegulatoryError("chain-head-ambiguous", "audit_chain_head returned more than one row.")
    chain_head = None if not heads else _chain_head(heads[0])
    links_ok = _links_ok(rows, predecessor)
    return _assemble(
        organisation_id=organisation_id,
        from_date=from_date,
        to_date=to_date,
        rows=rows,
        predecessor=predecessor,
        chain_head=chain_head,
        links_ok=links_ok,
        hashes_ok=hashes_ok,
    )


def _links_ok(rows: tuple[AuditRecord, ...], predecessor: AuditRecord | None) -> bool:
    previous_hash = None if predecessor is None else predecessor.row_hash
    previous_sequence = 0 if predecessor is None else predecessor.recognition_sequence
    if predecessor is not None and previous_sequence is None:
        return False
    for row in rows:
        if row.recognition_sequence is None or row.recognition_sequence != previous_sequence + 1:
            return False
        if row.previous_hash != previous_hash:
            return False
        previous_hash = row.row_hash
        previous_sequence = row.recognition_sequence
    return True


def _hash_matches(item: Mapping[str, object]) -> bool:
    if "hash_matches" not in item or type(item["hash_matches"]) is not bool:
        raise RegulatoryError(
            "hash-check-missing",
            "The audit query must return hash_matches from the seal expression.",
        )
    return item["hash_matches"]


def _record_from_query(item: Mapping[str, object], organisation_id: str) -> AuditRecord:
    row_org = item.get("organisation_id")
    if row_org is None or str(row_org) != str(organisation_id):
        raise RegulatoryError(
            "organisation-mismatch",
            "An audit row is not for the organisation that was requested.",
        )
    occurred_at = item.get("occurred_at")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise RegulatoryError(
            "timestamp-naive",
            "Decision 1: occurred_at must be timezone-aware so the Johannesburg day is known.",
        )
    sequence = item.get("recognition_sequence")
    if sequence is not None and type(sequence) is not int:
        raise RegulatoryError("sequence-unreadable", "recognition_sequence must be an integer.")
    row_hash = _bytea(item.get("row_hash"))
    if row_hash is None:
        raise RegulatoryError("hash-unreadable", "An audit row needs row_hash.")
    category = item.get("category")
    if not isinstance(category, str) or not category:
        raise RegulatoryError("category-unset", "The audit row has no event-type category.")
    event_id = item.get("event_id")
    event_type = item.get("event_type")
    if not isinstance(event_id, str) or not event_id or not isinstance(event_type, str) or not event_type:
        raise RegulatoryError("event-type-unset", "An audit row needs an event id and an event type.")
    amount = item.get("amount_cents")
    if amount is not None and type(amount) is not int:
        raise RegulatoryError("amount-required", "amount_cents must be an integer when it is present.")
    balance = item.get("balance_code")
    if balance is not None and not isinstance(balance, str):
        raise RegulatoryError("balance-unreadable", "balance_code must be text when it is present.")
    return AuditRecord(
        organisation_id=str(row_org),
        event_id=event_id,
        occurred_at=occurred_at,
        event_type=event_type,
        category=category,
        recognition_sequence=sequence,
        amount_cents=amount,
        balance_code=balance,
        payload=_payload(item.get("payload")),
        previous_hash=_bytea(item.get("previous_hash")),
        row_hash=row_hash,
        agreement_id=_optional_text(item.get("agreement_id")),
        enigma_person_id=_optional_text(item.get("enigma_person_id")),
    )


def _chain_head(item: Mapping[str, object]) -> AuditChainHead:
    event_id = item.get("last_event_id")
    occurred_at = item.get("last_occurred_at")
    sequence = item.get("last_sequence")
    if not isinstance(event_id, str) or not event_id:
        raise RegulatoryError("chain-head-unreadable", "audit_chain_head needs last_event_id.")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise RegulatoryError("chain-head-unreadable", "audit_chain_head needs a timezone-aware last_occurred_at.")
    if type(sequence) is not int:
        raise RegulatoryError("chain-head-unreadable", "audit_chain_head needs last_sequence.")
    digest = _bytea(item.get("last_hash"))
    if digest is None:
        raise RegulatoryError("chain-head-unreadable", "audit_chain_head needs last_hash.")
    return AuditChainHead(
        last_event_id=event_id,
        last_occurred_at=occurred_at,
        last_hash=digest,
        last_sequence=sequence,
    )


def _payload(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise RegulatoryError("payload-unreadable", "Audit payload must be a JSON object.")


def _bytea(value: object) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    raise RegulatoryError("hash-unreadable", "Audit hashes must be bytes.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise RegulatoryError("payload-unreadable", "An optional audit identifier must be text.")
