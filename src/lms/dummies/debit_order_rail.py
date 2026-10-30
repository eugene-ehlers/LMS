"""Fixed debit-order dummy. It does not talk to a bank or build a DebiCheck file."""

from __future__ import annotations

from enum import StrEnum

from lms.dummies.fixtures import (
    FIXED_FAILURE_REASON,
    FIXED_UNMATCHED_AMOUNT_CENTS,
    FIXED_UNMATCHED_ID_NUMBER,
    FIXED_UNMATCHED_LOAN_NUMBER,
    FIXED_UNMATCHED_RECOGNITION_DATE,
    RECEIPT_SEQUENCE_WIDTH,
)
from lms.errors import ContractError
from lms.ports.debit_order_rail import (
    CollectionFailure,
    CollectionInstruction,
    CollectionResult,
    CollectionSuccess,
    CollectionUnmatched,
    MatchedReceipt,
    UnmatchedReceipt,
)


class DebitOrderScenario(StrEnum):
    FIXED_SUCCESS = "fixed_success"
    FIXED_FAILURE = "fixed_failure"
    FIXED_UNMATCHED = "fixed_unmatched"


class DebitOrderRailDummy:
    """One scenario for every valid instruction.

    Receipt sequence starts at 1 on each instance and increases only when a
    receipt is emitted. The LMS uses that order when two receipts share a
    recognition instant.
    """

    def __init__(self, scenario: DebitOrderScenario = DebitOrderScenario.FIXED_SUCCESS) -> None:
        if not isinstance(scenario, DebitOrderScenario):
            raise ContractError("scenario must be a DebitOrderScenario")
        self._scenario = scenario
        self._sequence = 0

    @classmethod
    def fixed_success(cls) -> DebitOrderRailDummy:
        return cls(DebitOrderScenario.FIXED_SUCCESS)

    @classmethod
    def fixed_failure(cls) -> DebitOrderRailDummy:
        return cls(DebitOrderScenario.FIXED_FAILURE)

    @classmethod
    def fixed_unmatched(cls) -> DebitOrderRailDummy:
        return cls(DebitOrderScenario.FIXED_UNMATCHED)

    def submit_collection(self, instruction: CollectionInstruction) -> CollectionResult:
        if not isinstance(instruction, CollectionInstruction):
            raise ContractError("instruction must be a CollectionInstruction")
        if self._scenario is DebitOrderScenario.FIXED_FAILURE:
            return CollectionFailure(
                loan_number=instruction.loan_number,
                reason=FIXED_FAILURE_REASON,
            )
        if self._scenario is DebitOrderScenario.FIXED_UNMATCHED:
            return CollectionUnmatched(
                receipt=UnmatchedReceipt(
                    receipt_sequence=self._next_sequence(),
                    amount_cents=instruction.amount_cents,
                    recognition_at=instruction.recognition_at,
                    loan_number=instruction.loan_number,
                    id_number=instruction.id_number,
                )
            )
        return CollectionSuccess(
            receipt=MatchedReceipt(
                receipt_sequence=self._next_sequence(),
                loan_number=instruction.loan_number,
                amount_cents=instruction.amount_cents,
                recognition_at=instruction.recognition_at,
            )
        )

    def pull_unmatched_receipts(self) -> tuple[UnmatchedReceipt, ...]:
        """Return one canned unmatched receipt in the unmatched scenario, else none.

        The canned receipt is independent of ``submit_collection``. Each pull
        emits one new receipt so the sequence stays unique.
        """

        if self._scenario is not DebitOrderScenario.FIXED_UNMATCHED:
            return ()
        return (
            UnmatchedReceipt(
                receipt_sequence=self._next_sequence(),
                amount_cents=FIXED_UNMATCHED_AMOUNT_CENTS,
                recognition_at=FIXED_UNMATCHED_RECOGNITION_DATE,
                loan_number=FIXED_UNMATCHED_LOAN_NUMBER,
                id_number=FIXED_UNMATCHED_ID_NUMBER,
            ),
        )

    def _next_sequence(self) -> int:
        self._sequence += 1
        if self._sequence >= 10**RECEIPT_SEQUENCE_WIDTH:
            raise ContractError("receipt sequence exceeded the dummy width")
        return self._sequence
