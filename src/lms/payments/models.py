"""Records the payment rail keeps. Amounts are integer cents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DebtorAccount:
    """The consumer homing account printed on a debit-order transaction.

    The lock does not store this on the agreement. A missing account fails closed.
    """

    branch_code: str
    account_number: str
    account_type: str
    account_name: str


@dataclass(frozen=True)
class CollectionMandate:
    """How this agreement is collected. ``scheme`` is ``eft`` or ``debicheck``.

    DebiCheck needs an explicit mandate reference and tracking indicator.
    Neither is defaulted.
    """

    scheme: str
    debtor: DebtorAccount
    mandate_reference: str | None = None
    tracking_indicator: int | None = None


@dataclass(frozen=True)
class CollectionInstructionRecord:
    """One LMS collection instruction. LOCKED_DECISIONS §4 and §26.

    ``amount_cents`` is the amount of this collection. ``credit_life_premium_cents``
    is the premium the decision engine supplied for this run, on both the loan
    line and the premium line.
    """

    loan_number: str
    amount_cents: int
    due_on: date
    recognition_date: date
    credit_life_premium_cents: int
    purpose: str
    scheme: str
    agreement_id: str
    application_number: str
    mandate_reference: str | None = None
    tracking_indicator: int | None = None


@dataclass(frozen=True)
class DebitOrderFile:
    """A standard Bankserv collections file plus the LMS instructions it was built from."""

    organisation_id: str
    recognition_date: date
    due_on: date
    instructions: tuple[CollectionInstructionRecord, ...]
    body: str
    submission_id: str | None = None


@dataclass(frozen=True)
class InboundReceipt:
    """A receipt the debit-order rail (dummy or a later real rail) hands to the LMS."""

    amount_cents: int
    recognised_at: datetime
    purpose: str | None = None
    loan_number: str | None = None
    id_number: str | None = None
    agreement_id: str | None = None
    attributed_due_on: date | None = None
    idempotency_key: str = ""


@dataclass
class RailReceipt:
    receipt_id: str
    organisation_id: str
    amount_cents: int
    recognised_at: datetime
    value_date: date
    sequence: int
    status: str
    purpose: str | None = None
    loan_number: str | None = None
    id_number: str | None = None
    agreement_id: str | None = None
    attributed_due_on: date | None = None
    ledger_transaction_id: str | None = None
    allocations: tuple[tuple[str, int], ...] = ()
    flag: str | None = None
    servicing_payment_id: str | None = None
