"""Debit-order rail port (DebiCheck / bank).

The LMS submits a collection instruction. On success it receives a matched
receipt and capitalises due amounts before it allocates. An unmatched receipt
carries a loan number or an ID number so the LMS can match it later.

This port does not describe a DebiCheck or bank file layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable

from lms.errors import ContractError
from lms.recognition import to_recognition_instant
from lms.validation import require_cents, require_optional_text, require_text


def require_calendar_date(value: object, name: str) -> date:
    # ``datetime`` is a ``date`` subclass and is not a calendar date on its own.
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ContractError(f"{name} must be a calendar date")
    return value


@dataclass(frozen=True)
class CollectionInstruction:
    """One collection the LMS asks the rail to run. Amount is integer cents."""

    loan_number: str
    amount_cents: int
    due_date: date
    recognition_at: date | datetime
    id_number: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "loan_number", require_text(self.loan_number, "loan_number"))
        object.__setattr__(self, "amount_cents", require_cents(self.amount_cents, "amount_cents"))
        object.__setattr__(self, "due_date", require_calendar_date(self.due_date, "due_date"))
        object.__setattr__(self, "id_number", require_optional_text(self.id_number, "id_number"))
        object.__setattr__(
            self, "recognition_at", to_recognition_instant(self.recognition_at)
        )


@dataclass(frozen=True)
class MatchedReceipt:
    """A receipt already tied to the loan. The LMS capitalises, then allocates this amount."""

    receipt_sequence: int
    loan_number: str
    amount_cents: int
    recognition_at: datetime
    kind: Literal["matched"] = "matched"

    def __post_init__(self) -> None:
        if self.kind != "matched":
            raise ContractError("matched receipt kind is fixed")
        _require_receipt_sequence(self.receipt_sequence)
        object.__setattr__(self, "loan_number", require_text(self.loan_number, "loan_number"))
        object.__setattr__(self, "amount_cents", require_cents(self.amount_cents, "amount_cents"))
        object.__setattr__(
            self, "recognition_at", to_recognition_instant(self.recognition_at)
        )


@dataclass(frozen=True)
class UnmatchedReceipt:
    """A receipt the rail did not match. Later matching uses loan number or ID number."""

    receipt_sequence: int
    amount_cents: int
    recognition_at: datetime
    loan_number: str | None = None
    id_number: str | None = None
    kind: Literal["unmatched"] = "unmatched"

    def __post_init__(self) -> None:
        if self.kind != "unmatched":
            raise ContractError("unmatched receipt kind is fixed")
        _require_receipt_sequence(self.receipt_sequence)
        object.__setattr__(self, "amount_cents", require_cents(self.amount_cents, "amount_cents"))
        object.__setattr__(
            self, "recognition_at", to_recognition_instant(self.recognition_at)
        )
        object.__setattr__(
            self, "loan_number", require_optional_text(self.loan_number, "loan_number")
        )
        object.__setattr__(self, "id_number", require_optional_text(self.id_number, "id_number"))
        if self.loan_number is None and self.id_number is None:
            raise ContractError(
                "an unmatched receipt needs a loan number or an ID number for later matching"
            )


@dataclass(frozen=True)
class CollectionSuccess:
    receipt: MatchedReceipt
    kind: Literal["success"] = "success"

    def __post_init__(self) -> None:
        if self.kind != "success":
            raise ContractError("collection success kind is fixed")
        if not isinstance(self.receipt, MatchedReceipt):
            raise ContractError("a successful collection returns a matched receipt")


@dataclass(frozen=True)
class CollectionFailure:
    loan_number: str
    reason: str
    kind: Literal["failure"] = "failure"

    def __post_init__(self) -> None:
        if self.kind != "failure":
            raise ContractError("collection failure kind is fixed")
        object.__setattr__(self, "loan_number", require_text(self.loan_number, "loan_number"))
        object.__setattr__(self, "reason", require_text(self.reason, "reason"))


@dataclass(frozen=True)
class CollectionUnmatched:
    receipt: UnmatchedReceipt
    kind: Literal["unmatched"] = "unmatched"

    def __post_init__(self) -> None:
        if self.kind != "unmatched":
            raise ContractError("collection unmatched kind is fixed")
        if not isinstance(self.receipt, UnmatchedReceipt):
            raise ContractError("an unmatched collection returns an unmatched receipt")


CollectionResult = CollectionSuccess | CollectionFailure | CollectionUnmatched


def _require_receipt_sequence(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError("receipt_sequence must be a positive integer")


@runtime_checkable
class DebitOrderRail(Protocol):
    """LMS call sites for the debit-order rail."""

    def submit_collection(self, instruction: CollectionInstruction) -> CollectionResult:
        """Accept a collection instruction and return success, failure, or unmatched."""

    def pull_unmatched_receipts(self) -> tuple[UnmatchedReceipt, ...]:
        """Return inbound receipts that were not matched to a collection instruction."""
