"""Decision 27. The push says the statement is available.

It does not carry a balance, an arrears figure, or any collection notice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class StatementReady:
    organisation_id: str
    person_id: str
    statement_id: str
    period_start: date
    period_end: date
    message: str


@dataclass
class Notifications:
    pushes: list[StatementReady] = field(default_factory=list)

    def push(
        self,
        *,
        organisation_id: str,
        person_id: str,
        statement_id: str,
        period_start: date,
        period_end: date,
        registered: bool,
    ) -> StatementReady | None:
        """Send the statement-ready push when the consumer is registered."""
        if not registered:
            return None
        note = StatementReady(
            organisation_id=organisation_id,
            person_id=person_id,
            statement_id=statement_id,
            period_start=period_start,
            period_end=period_end,
            message="Your statement is available.",
        )
        self.pushes.append(note)
        return note
