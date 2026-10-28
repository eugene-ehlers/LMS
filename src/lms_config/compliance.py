"""Statement compliance fields stored as LMS configuration.

Locked decisions 15 and 21: the NCR registration number, trading name,
addresses, telephone, payment-account details, and brand assets are LMS
tenant facts. Enigma does not hold or return them. This module does not
call Enigma.

Trading name may be blank: regulation 35(a)(ii) says "if any". Every other
field on this row is required by the statements store. A blank required
field fails closed. No value is invented.

Decision 21 also says a blank NCR number does not block a pure-hosting or
Laybye/BNPL extract. This table still rejects a blank number, because
statements require one. That gap is RX52 in the regulatory implementation
note. Regulatory extracts use ``find``, which can see that no row exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms_config.exceptions import CalculationInputError


REQUIRED_FIELDS = (
    "legal_name",
    "ncr_registration_number",
    "physical_address",
    "postal_address",
    "telephone",
    "bank_name",
    "bank_account_number",
    "branch_code",
    "payment_reference",
)


@dataclass(frozen=True, slots=True)
class ProviderCompliance:
    """Disclosure facts for one credit-provider organisation.

    Keyed by the opaque ``organisation_id``. Consumer name, identity number,
    and service address are not stored here (locked decision 16).
    """

    organisation_id: str
    legal_name: str
    ncr_registration_number: str
    trading_name: str
    physical_address: str
    postal_address: str
    telephone: str
    bank_name: str
    bank_account_number: str
    branch_code: str
    payment_reference: str


class ComplianceStore:
    """In-memory LMS configuration for statement disclosure.

    One row per organisation. A later ``put`` replaces the row. A statement
    copies the row at issue time, so a later edit does not rewrite a stored
    statement.
    """

    def __init__(self) -> None:
        self._rows: dict[str, ProviderCompliance] = {}

    def put(self, record: ProviderCompliance) -> None:
        _require_complete(record)
        self._rows[record.organisation_id] = record

    def find(self, organisation_id: str) -> ProviderCompliance | None:
        """The row, or None when this organisation has no compliance row.

        Unlike ``require``, a missing row is not an error. Regulatory
        extracts need that distinction: decision 21 does not require an
        NCR number for every product.
        """
        return self._rows.get(organisation_id)

    def require(self, organisation_id: str) -> ProviderCompliance:
        record = self.find(organisation_id)
        if record is None:
            raise CalculationInputError(
                f"compliance-missing: no LMS compliance row for organisation {organisation_id}"
            )
        _require_complete(record)
        return record


def _require_complete(record: ProviderCompliance) -> None:
    if not record.organisation_id.strip():
        raise CalculationInputError("compliance-missing: organisation_id is blank")
    for name in REQUIRED_FIELDS:
        value = getattr(record, name)
        if not isinstance(value, str) or not value.strip():
            raise CalculationInputError(f"compliance-missing: {name} is blank")
    if not isinstance(record.trading_name, str):
        raise CalculationInputError("compliance-missing: trading_name is absent")
