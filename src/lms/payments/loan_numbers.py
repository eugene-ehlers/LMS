"""LMS loan numbers. LOCKED_DECISIONS §25.

The lock requires a sequential number that is not skipped, one number for an
application, and the same core number for a Laybye with another indicator.
It does not fix the character pattern. This series is 12 digits, starting at
1, with no company prefix and no month reset. That pattern is not a locked rule.
A Laybye does not take the next number. It keeps the core number and stores
the indicator ``L``.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.payments.errors import PaymentRailError

_WIDTH = 12
_LAYBYE_INDICATOR = "L"


@dataclass
class LoanNumberRecord:
    organisation_id: str
    application_number: str
    loan_number: str
    agreement_id: str
    ledger_loan_id: str
    laybye_indicator: str | None = None
    laybye_ledger_loan_id: str | None = None


class LoanNumberSeries:
    """One process-wide sequence. A number is issued only for a new application."""

    def __init__(self) -> None:
        self._next = 1
        self._by_application: dict[tuple[str, str], LoanNumberRecord] = {}
        self._by_number: dict[tuple[str, str], LoanNumberRecord] = {}

    def issue(
        self,
        *,
        organisation_id: str,
        application_number: str,
        agreement_id: str,
        ledger_loan_id: str,
        laybye: bool = False,
    ) -> LoanNumberRecord:
        if not organisation_id.strip() or not application_number.strip():
            raise PaymentRailError(
                "application-number-unset",
                "LOCKED_DECISIONS §25: the decision engine supplies an application number. "
                "A blank application number is not given a loan number.",
            )
        if not ledger_loan_id.strip() or not agreement_id.strip():
            raise PaymentRailError("loan-number", "A loan number is linked to a disbursed agreement.")
        key = (organisation_id, application_number)
        existing = self._by_application.get(key)
        if laybye:
            if existing is None:
                raise PaymentRailError(
                    "loan-number",
                    "LOCKED_DECISIONS §25: the Laybye uses the core loan number. The core number has not been issued.",
                )
            if existing.laybye_ledger_loan_id not in {None, ledger_loan_id}:
                raise PaymentRailError(
                    "loan-number",
                    "LOCKED_DECISIONS §25: this application already has a Laybye indicator.",
                )
            existing.laybye_indicator = _LAYBYE_INDICATOR
            existing.laybye_ledger_loan_id = ledger_loan_id
            return existing
        if existing is not None:
            if existing.ledger_loan_id != ledger_loan_id or existing.agreement_id != agreement_id:
                raise PaymentRailError(
                    "loan-number",
                    "LOCKED_DECISIONS §25: there is only one loan number for an application.",
                )
            return existing
        if self._next > 10**_WIDTH - 1:
            raise PaymentRailError(
                "loan-number-exhausted",
                "The 12-digit loan-number series is exhausted. The lock does not name the next pattern.",
            )
        number = f"{self._next:0{_WIDTH}d}"
        self._next += 1
        record = LoanNumberRecord(
            organisation_id=organisation_id,
            application_number=application_number,
            loan_number=number,
            agreement_id=agreement_id,
            ledger_loan_id=ledger_loan_id,
        )
        self._by_application[key] = record
        self._by_number[(organisation_id, number)] = record
        return record

    def find(self, organisation_id: str, loan_number: str) -> LoanNumberRecord | None:
        return self._by_number.get((organisation_id, loan_number))

    def find_application(self, organisation_id: str, application_number: str) -> LoanNumberRecord | None:
        return self._by_application.get((organisation_id, application_number))

    def find_by_agreement(self, organisation_id: str, agreement_id: str) -> LoanNumberRecord | None:
        for record in self._by_application.values():
            if record.organisation_id == organisation_id and record.agreement_id == agreement_id:
                return record
        return None
