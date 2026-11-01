"""Debit-order file stub. One success or failure receipt per instruction.

A success receipt carries the amount and 00:00 Africa/Johannesburg on the
item's recognition date. A failure receipt carries that same instant and a
fixed reason code. This stub does not call a bank.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from lms.dummies.fixtures import FIXED_FAILURE_REASON
from lms.payments.models import DebitOrderFile
from lms_config.calendar import value_instant


class DebitStubError(Exception):
    """The file cannot be turned into receipts."""


@dataclass(frozen=True)
class SuccessReceipt:
    """The fields ``Servicing.accept_payment`` uses, plus the loan number."""

    amount_cents: int
    recognised_at: datetime
    agreement_id: str
    attributed_due_on: date
    idempotency_key: str
    loan_number: str
    kind: Literal["success"] = "success"


@dataclass(frozen=True)
class FailureReceipt:
    """No amount. ``accept_payment`` is not called for this item."""

    recognised_at: datetime
    reason_code: str
    loan_number: str
    kind: Literal["failure"] = "failure"


Receipt = SuccessReceipt | FailureReceipt


class DebitFileStub:
    """Loan numbers in ``failed_loan_numbers`` fail. Every other item succeeds."""

    def __init__(self, failed_loan_numbers: frozenset[str] = frozenset()) -> None:
        self._failed = frozenset(failed_loan_numbers)

    def acknowledge(self, file: DebitOrderFile) -> tuple[Receipt, ...]:
        if not isinstance(file, DebitOrderFile):
            raise DebitStubError("acknowledge expects a DebitOrderFile")
        receipts: list[Receipt] = []
        for index, item in enumerate(file.instructions, start=1):
            if isinstance(item.amount_cents, bool) or not isinstance(item.amount_cents, int):
                raise DebitStubError("amount_cents must be integer cents")
            if item.amount_cents < 0:
                raise DebitStubError("amount_cents must be zero or a positive number of cents")
            recognised_at = value_instant(item.recognition_date)
            if item.loan_number in self._failed:
                receipts.append(
                    FailureReceipt(
                        recognised_at=recognised_at,
                        reason_code=FIXED_FAILURE_REASON,
                        loan_number=item.loan_number,
                    )
                )
                continue
            receipts.append(
                SuccessReceipt(
                    amount_cents=item.amount_cents,
                    recognised_at=recognised_at,
                    agreement_id=item.agreement_id,
                    attributed_due_on=item.due_on,
                    idempotency_key=f"debit-{index}-{item.loan_number}-{item.purpose}",
                    loan_number=item.loan_number,
                )
            )
        return tuple(receipts)
