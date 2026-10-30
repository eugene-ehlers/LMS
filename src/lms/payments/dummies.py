"""Development stand-ins. A later real rail or decision engine replaces these objects.

Neither dummy opens a socket. The decision-engine dummy returns only a premium
the test stored. A missing key is a missing premium, not zero.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from lms.payments.models import DebitOrderFile, InboundReceipt


class DecisionEnginePort(Protocol):
    def credit_life_premium_cents(
        self,
        *,
        organisation_id: str,
        application_number: str,
        loan_number: str,
        due_on: date,
    ) -> int | None:
        """The premium for this collection run. ``None`` means the engine did not supply one."""


class DebitOrderRailPort(Protocol):
    def submit(self, file: DebitOrderFile) -> str:
        """Accept a file. Return the rail's submission id."""

    def take_receipts(self) -> tuple[InboundReceipt, ...]:
        """Receipts the rail has recognised since the last take."""


class DecisionEngineDummy:
    """Supplies the credit-life premium each time it is asked. LOCKED_DECISIONS §4 and §26."""

    def __init__(self) -> None:
        self.premiums: dict[tuple[str, str, date], int | None] = {}
        self.calls: list[tuple[str, str, str, date]] = []

    def credit_life_premium_cents(
        self,
        *,
        organisation_id: str,
        application_number: str,
        loan_number: str,
        due_on: date,
    ) -> int | None:
        self.calls.append((organisation_id, application_number, loan_number, due_on))
        return self.premiums.get((organisation_id, application_number, due_on))


class DebitOrderRailDummy:
    """Holds submitted files and queued receipts. It does not talk to a bank."""

    def __init__(self) -> None:
        self.submitted: list[DebitOrderFile] = []
        self._inbox: list[InboundReceipt] = []

    def submit(self, file: DebitOrderFile) -> str:
        submission_id = f"dummy-{len(self.submitted) + 1}"
        self.submitted.append(file)
        return submission_id

    def queue_receipt(self, receipt: InboundReceipt) -> None:
        self._inbox.append(receipt)

    def take_receipts(self) -> tuple[InboundReceipt, ...]:
        items = tuple(self._inbox)
        self._inbox.clear()
        return items
