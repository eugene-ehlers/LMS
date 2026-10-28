"""Statement compliance fields stored as LMS configuration.

Locked decision 15 says Enigma owns organisation identity and the LMS stores
only opaque organisation ids. This module does not call Enigma. The statements
task says the provider legal name, NCR number, trading name, addresses,
telephone, and payment-account details are read from LMS configuration.
That conflict is recorded in ``docs/statements/implementation-note.md``.
This module does not change ``docs/LOCKED_DECISIONS.md``.

Trading name may be blank: regulation 35(a)(ii) says "if any". Every other
field is required. A blank required field fails closed. No value is invented.
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

    def require(self, organisation_id: str) -> ProviderCompliance:
        record = self._rows.get(organisation_id)
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
