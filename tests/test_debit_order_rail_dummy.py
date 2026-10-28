from datetime import date, datetime, timedelta, timezone

import pytest

from lms.dummies.debit_order_rail import DebitOrderRailDummy
from lms.dummies.fixtures import (
    FIXED_FAILURE_REASON,
    FIXED_UNMATCHED_AMOUNT_CENTS,
    FIXED_UNMATCHED_ID_NUMBER,
    FIXED_UNMATCHED_LOAN_NUMBER,
)
from lms.errors import ContractError
from lms.ports.debit_order_rail import (
    CollectionFailure,
    CollectionInstruction,
    CollectionSuccess,
    CollectionUnmatched,
    DebitOrderRail,
    MatchedReceipt,
    UnmatchedReceipt,
)
from lms.recognition import JOHANNESBURG
from tests.builders import instruction


def test_fixed_success_returns_a_matched_receipt_at_midnight() -> None:
    rail = DebitOrderRailDummy.fixed_success()

    result = rail.submit_collection(instruction())

    assert isinstance(rail, DebitOrderRail)
    assert isinstance(result, CollectionSuccess)
    receipt = result.receipt
    assert isinstance(receipt, MatchedReceipt)
    assert receipt.kind == "matched"
    assert receipt.receipt_sequence == 1
    assert receipt.loan_number == "LN-1001"
    assert receipt.amount_cents == 25_000
    assert receipt.recognition_at == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)
    assert not hasattr(receipt, "due_date")
    assert rail.pull_unmatched_receipts() == ()


def test_amount_is_echoed_and_not_combined_with_any_other_charge() -> None:
    rail = DebitOrderRailDummy.fixed_success()

    one_cent = rail.submit_collection(instruction(amount_cents=1))
    zero = rail.submit_collection(instruction(amount_cents=0))

    assert one_cent.receipt.amount_cents == 1
    assert zero.receipt.amount_cents == 0


def test_same_day_receipts_keep_recognition_order() -> None:
    rail = DebitOrderRailDummy.fixed_success()
    moment = date(2026, 10, 28)

    first = rail.submit_collection(instruction(recognition_at=moment))
    second = rail.submit_collection(
        instruction(loan_number="LN-1002", recognition_at=datetime(2026, 10, 28, 23, 59, tzinfo=JOHANNESBURG))
    )

    assert first.receipt.recognition_at == second.receipt.recognition_at
    assert [first.receipt.receipt_sequence, second.receipt.receipt_sequence] == [1, 2]


def test_utc_recognition_instant_uses_the_johannesburg_day() -> None:
    rail = DebitOrderRailDummy.fixed_success()

    result = rail.submit_collection(
        instruction(recognition_at=datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc))
    )

    assert result.receipt.recognition_at == datetime(2026, 10, 29, 0, 0, tzinfo=JOHANNESBURG)
    assert result.receipt.recognition_at.utcoffset() == timedelta(hours=2)


def test_due_date_stays_a_calendar_date_on_the_instruction() -> None:
    submitted = instruction()

    assert submitted.due_date == date(2026, 11, 3)
    assert isinstance(submitted.due_date, date)
    assert not isinstance(submitted.due_date, datetime)


def test_fixed_failure_returns_no_receipt() -> None:
    rail = DebitOrderRailDummy.fixed_failure()

    result = rail.submit_collection(instruction())

    assert isinstance(result, CollectionFailure)
    assert result.kind == "failure"
    assert result.loan_number == "LN-1001"
    assert result.reason == FIXED_FAILURE_REASON
    assert not hasattr(result, "receipt")
    assert rail.pull_unmatched_receipts() == ()


def test_fixed_unmatched_from_the_instruction_keeps_both_match_keys() -> None:
    rail = DebitOrderRailDummy.fixed_unmatched()

    result = rail.submit_collection(instruction())

    assert isinstance(result, CollectionUnmatched)
    receipt = result.receipt
    assert receipt.kind == "unmatched"
    assert receipt.loan_number == "LN-1001"
    assert receipt.id_number == "0000000000000"
    assert receipt.amount_cents == 25_000
    assert receipt.recognition_at == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)
    assert receipt.receipt_sequence == 1


def test_unmatched_instruction_without_an_id_number_still_carries_the_loan_number() -> None:
    rail = DebitOrderRailDummy.fixed_unmatched()

    result = rail.submit_collection(instruction(id_number=None))

    assert result.receipt.loan_number == "LN-1001"
    assert result.receipt.id_number is None


def test_id_number_alone_is_enough_on_an_unmatched_receipt() -> None:
    receipt = UnmatchedReceipt(
        receipt_sequence=1,
        amount_cents=10,
        recognition_at=date(2026, 1, 15),
        id_number="0000000000000",
    )

    assert receipt.loan_number is None
    assert receipt.id_number == "0000000000000"


def test_unmatched_receipt_without_either_match_key_is_rejected() -> None:
    with pytest.raises(ContractError):
        UnmatchedReceipt(
            receipt_sequence=1,
            amount_cents=10,
            recognition_at=date(2026, 1, 15),
        )


def test_pull_returns_the_canned_unmatched_receipt_only_in_that_scenario() -> None:
    rail = DebitOrderRailDummy.fixed_unmatched()
    rail.submit_collection(instruction())

    pulled = rail.pull_unmatched_receipts()

    assert len(pulled) == 1
    receipt = pulled[0]
    assert receipt.receipt_sequence == 2
    assert receipt.loan_number == FIXED_UNMATCHED_LOAN_NUMBER
    assert receipt.id_number == FIXED_UNMATCHED_ID_NUMBER
    assert receipt.amount_cents == FIXED_UNMATCHED_AMOUNT_CENTS
    assert receipt.recognition_at == datetime(2026, 1, 15, 0, 0, tzinfo=JOHANNESBURG)
    assert DebitOrderRailDummy.fixed_success().pull_unmatched_receipts() == ()
    assert DebitOrderRailDummy.fixed_failure().pull_unmatched_receipts() == ()


def test_invalid_instruction_is_rejected_before_a_fixed_failure() -> None:
    with pytest.raises(ContractError):
        instruction(amount_cents=25.0)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        instruction(amount_cents=-5)
    with pytest.raises(ContractError):
        instruction(due_date=datetime(2026, 11, 3, 0, 0, tzinfo=JOHANNESBURG))
    with pytest.raises(ContractError):
        instruction(recognition_at=datetime(2026, 10, 28, 0, 0))
    with pytest.raises(ContractError):
        DebitOrderRailDummy.fixed_failure().submit_collection(object())  # type: ignore[arg-type]


def test_call_site_accepts_another_rail() -> None:
    class ScriptedRail:
        def submit_collection(self, instruction: CollectionInstruction) -> CollectionFailure:
            return CollectionFailure(loan_number=instruction.loan_number, reason="scripted")

        def pull_unmatched_receipts(self) -> tuple[UnmatchedReceipt, ...]:
            return ()

    def submit(rail: DebitOrderRail, payload: CollectionInstruction) -> CollectionFailure:
        result = rail.submit_collection(payload)
        assert isinstance(result, CollectionFailure)
        return result

    assert submit(ScriptedRail(), instruction()).reason == "scripted"
    assert submit(DebitOrderRailDummy.fixed_failure(), instruction()).reason == FIXED_FAILURE_REASON
