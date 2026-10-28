"""Push payload and the registration answer.

The payload tells the consumer that a statement is available. It does not
carry balances, arrears, or collection wording. Locked decision 27.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


STATEMENT_READY = "statement_ready"
STATEMENT_READY_MESSAGE = "Your statement is available."

# Staff statement read already named on the Enigma port catalogue.
# Locked decision 27 does not name this role. A missing allow fails closed.
STAFF_STATEMENT_ACTION = "lms.account.statement.read"

PAYLOAD_FIELDS = (
    "kind",
    "statement_id",
    "organisation_id",
    "person_id",
    "period_start",
    "period_end",
    "ncr_registration_number",
    "legal_name",
    "message",
    "loan_ids",
)


@dataclass(frozen=True)
class IssuedStatement:
    """Fields copied from a statement Layer 1 has already issued.

    Opening and closing balances stay on the statement. They are not copied
    here. Loan ids are kept so one push can name every loan on that one
    client statement (locked decision 12) without repeating each balance.
    """

    statement_id: str
    organisation_id: str
    person_id: str
    period_start: date
    period_end: date
    ncr_registration_number: str
    legal_name: str
    loan_ids: tuple[str, ...]


@dataclass(frozen=True)
class StatementReadyPayload:
    kind: str
    statement_id: str
    organisation_id: str
    person_id: str
    period_start: date
    period_end: date
    ncr_registration_number: str
    legal_name: str
    message: str
    loan_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "statement_id": self.statement_id,
            "organisation_id": self.organisation_id,
            "person_id": self.person_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "ncr_registration_number": self.ncr_registration_number,
            "legal_name": self.legal_name,
            "message": self.message,
            "loan_ids": list(self.loan_ids),
        }


@dataclass(frozen=True)
class RegistrationView:
    """Enigma's registration answer. Contact details are not a field."""

    person_id: str
    status: str
    enigma_request_id: str


@dataclass(frozen=True)
class EnigmaLocations:
    """Where LMS pages send the consumer. The LMS does not sign them on."""

    registration_url: str | None = None
    sign_on_url: str | None = None


@dataclass(frozen=True)
class EnigmaRedirect:
    purpose: str
    location: str
    status_code: int
    body: str


@dataclass(frozen=True)
class PushReceipt:
    payload: StatementReadyPayload
    actor_person_id: str
    recognised_at: datetime
    request_id: str
    replayed: bool


@dataclass(frozen=True)
class AuditRecord:
    """Who, when, and what. Locked decision 23. No contact details."""

    actor_person_id: str
    recognised_at: datetime
    action: str
    statement_id: str
    organisation_id: str
    person_id: str
    request_id: str
