"""Call the LMS methods that already exist. This module adds no route."""

from __future__ import annotations

from lms.servicing.service import AgreementRecord, PaymentRecord, Servicing
from lms.stubs.debit_file import DebitStubError, FailureReceipt, Receipt, SuccessReceipt
from lms.stubs.decision_quote import QuoteApproval


def book_quoted(servicing: Servicing, approval: QuoteApproval) -> AgreementRecord:
    """Pass the approval through ``Servicing.book`` and keep the application number.

    ``book`` has no application-number argument. The agreement record already
    has the field, so the wire writes it after the existing call.
    """

    record = servicing.book(**approval.book_payload())
    record.application_number = approval.application_number
    return record


def apply_debit_receipts(
    servicing: Servicing, receipts: tuple[Receipt, ...]
) -> tuple[PaymentRecord | FailureReceipt, ...]:
    """Hand each success receipt to ``Servicing.accept_payment``.

    A failure receipt stays a failure receipt. It is not a payment.
    """

    applied: list[PaymentRecord | FailureReceipt] = []
    for receipt in receipts:
        if isinstance(receipt, FailureReceipt):
            applied.append(receipt)
            continue
        if not isinstance(receipt, SuccessReceipt):
            raise DebitStubError("a debit receipt must be a success or a failure")
        agreement = servicing.agreements.get(receipt.agreement_id)
        if agreement is None:
            raise DebitStubError(
                "the receipt names an agreement that has not been booked"
            )
        applied.append(
            servicing.accept_payment(
                organisation_id=agreement.organisation_id,
                person_id=agreement.person_id,
                cents=receipt.amount_cents,
                recognised_at=receipt.recognised_at,
                idempotency_key=receipt.idempotency_key,
                agreement_id=agreement.agreement_id,
                attributed_due_on=receipt.attributed_due_on,
            )
        )
    return tuple(applied)
