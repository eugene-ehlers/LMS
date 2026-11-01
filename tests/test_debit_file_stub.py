"""The debit-file stub returns one receipt per item for Servicing.accept_payment."""

from __future__ import annotations

from datetime import date

import pytest

from lms.dummies.fixtures import FIXED_FAILURE_REASON
from lms.payments.models import CollectionInstructionRecord, DebitOrderFile
from lms.servicing.service import PaymentRecord
from lms.stubs.debit_file import DebitFileStub, DebitStubError, FailureReceipt, SuccessReceipt
from lms.stubs.wire import apply_debit_receipts
from lms_config.calendar import value_instant
from tests.test_servicing import DUE, at, book, disburse, servicing


RECOGNITION = date(2026, 3, 20)


def instruction(agreement_id: str, *, loan_number: str = "LN-1", amount_cents: int = 10_000) -> CollectionInstructionRecord:
    return CollectionInstructionRecord(
        loan_number=loan_number,
        amount_cents=amount_cents,
        due_on=DUE,
        recognition_date=RECOGNITION,
        credit_life_premium_cents=199,
        purpose="loan_instalment",
        scheme="eft",
        agreement_id=agreement_id,
        application_number="APP-00000001",
    )


def debit_file(agreement_id: str, items: tuple[CollectionInstructionRecord, ...]) -> DebitOrderFile:
    return DebitOrderFile(
        organisation_id="org-a",
        recognition_date=RECOGNITION,
        due_on=DUE,
        instructions=items,
        body="",
    )


def booked():
    svc = servicing()
    record = disburse(svc, book(svc, recognised_at=at(1, 8)))
    return svc, record


def test_success_receipt_is_accepted_as_a_payment() -> None:
    svc, record = booked()
    file = debit_file(record.agreement_id, (instruction(record.agreement_id),))

    receipts = DebitFileStub().acknowledge(file)
    applied = apply_debit_receipts(svc, receipts)

    assert len(receipts) == 1
    receipt = receipts[0]
    assert isinstance(receipt, SuccessReceipt)
    assert receipt.amount_cents == 10_000
    assert receipt.recognised_at == value_instant(RECOGNITION)
    assert receipt.recognised_at.hour == 0
    assert receipt.recognised_at.minute == 0
    assert receipt.recognised_at.utcoffset().total_seconds() == 2 * 60 * 60
    assert len(applied) == 1
    payment = applied[0]
    assert isinstance(payment, PaymentRecord)
    assert payment.cents == 10_000
    assert payment.value_date == RECOGNITION
    assert payment.recognised_at == receipt.recognised_at
    assert payment.agreement_id == record.agreement_id
    assert payment.status == "allocated"


def test_failure_receipt_carries_a_reason_and_is_not_a_payment() -> None:
    svc, record = booked()
    file = debit_file(record.agreement_id, (instruction(record.agreement_id),))

    receipts = DebitFileStub(frozenset({"LN-1"})).acknowledge(file)
    applied = apply_debit_receipts(svc, receipts)

    assert len(receipts) == 1
    failure = receipts[0]
    assert isinstance(failure, FailureReceipt)
    assert failure.reason_code == FIXED_FAILURE_REASON
    assert failure.recognised_at == value_instant(RECOGNITION)
    assert not hasattr(failure, "amount_cents")
    assert applied == (failure,)
    assert svc.payments == {}


def test_each_item_gets_its_own_receipt() -> None:
    svc, record = booked()
    items = (
        instruction(record.agreement_id, loan_number="LN-1", amount_cents=4_000),
        instruction(record.agreement_id, loan_number="LN-2", amount_cents=6_000),
    )
    file = debit_file(record.agreement_id, items)

    receipts = DebitFileStub(frozenset({"LN-2"})).acknowledge(file)
    applied = apply_debit_receipts(svc, receipts)

    assert [receipt.kind for receipt in receipts] == ["success", "failure"]
    assert isinstance(receipts[0], SuccessReceipt)
    assert receipts[0].amount_cents == 4_000
    assert isinstance(receipts[1], FailureReceipt)
    assert receipts[1].reason_code == FIXED_FAILURE_REASON
    assert isinstance(applied[0], PaymentRecord)
    assert applied[0].cents == 4_000
    assert applied[1] is receipts[1]
    assert len(svc.payments) == 1


def test_a_fractional_amount_is_rejected() -> None:
    svc, record = booked()
    item = CollectionInstructionRecord(
        loan_number="LN-1",
        amount_cents=10.5,  # type: ignore[arg-type]
        due_on=DUE,
        recognition_date=RECOGNITION,
        credit_life_premium_cents=199,
        purpose="loan_instalment",
        scheme="eft",
        agreement_id=record.agreement_id,
        application_number="APP-00000001",
    )

    with pytest.raises(DebitStubError):
        DebitFileStub().acknowledge(debit_file(record.agreement_id, (item,)))
    assert svc.payments == {}
