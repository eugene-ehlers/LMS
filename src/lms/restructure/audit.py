"""Restructure outcome log.

Every reported success or failure is stored with the actor, the Johannesburg
recognition instant, and the outcome. Communication section 4. Decision 23.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4


@dataclass(frozen=True)
class AuditRecord:
    organisation_id: str
    event_id: str
    sequence: int
    occurred_at: datetime
    recognition_date: date
    actor_person_id: str | None
    outcome: str
    event_type: str
    reason: str | None
    confirmation: str | None
    agreement_id: str | None
    roles: tuple[str, ...]
    payload: dict


class AuditLog:
    """Append-only log. Rows are not updated or removed."""

    def __init__(self) -> None:
        self._rows: list[AuditRecord] = []
        self._next: dict[str, int] = {}
        self._by_agreement: dict[tuple[str, str], list[AuditRecord]] = {}

    def append(
        self,
        *,
        organisation_id: str,
        occurred_at: datetime,
        actor_person_id: str | None,
        outcome: str,
        event_type: str,
        reason: str | None,
        confirmation: str | None,
        agreement_ids: tuple[str, ...],
        roles: tuple[str, ...],
        payload: dict,
    ) -> AuditRecord:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("audit occurred_at must be timezone-aware")
        sequence = self._next.get(organisation_id, 1)
        self._next[organisation_id] = sequence + 1
        primary = agreement_ids[0] if agreement_ids else None
        record = AuditRecord(
            organisation_id=organisation_id,
            event_id=str(uuid4()),
            sequence=sequence,
            occurred_at=occurred_at,
            recognition_date=occurred_at.date(),
            actor_person_id=actor_person_id,
            outcome=outcome,
            event_type=event_type,
            reason=reason,
            confirmation=confirmation,
            agreement_id=primary,
            roles=roles,
            payload=dict(payload),
        )
        self._rows.append(record)
        seen: set[str] = set()
        for agreement_id in agreement_ids:
            if not agreement_id or agreement_id in seen:
                continue
            seen.add(agreement_id)
            self._by_agreement.setdefault((organisation_id, agreement_id), []).append(record)
        return record

    def for_organisation(self, organisation_id: str) -> tuple[AuditRecord, ...]:
        return tuple(row for row in self._rows if row.organisation_id == organisation_id)

    def for_agreement(self, organisation_id: str, agreement_id: str) -> tuple[AuditRecord, ...]:
        return tuple(self._by_agreement.get((organisation_id, agreement_id), ()))

    def last_for_agreement(
        self, organisation_id: str, agreement_id: str
    ) -> AuditRecord | None:
        rows = self.for_agreement(organisation_id, agreement_id)
        if not rows:
            return None
        return rows[-1]
