"""What the calculation engine reads, and the order it reads it in.

Identity, organisation, membership, enrolment, role, and mandate live in
Enigma. This module does not query them. ``organisation_id`` and
``enigma_person_id`` arrive as opaque ids. An NCR registration number is
snapshotted onto the agreement at origination from Enigma; the engine
reads the snapshot, not Enigma, during a calculation.

Feature flags and white-label brands are not inputs to a charge. Flags
gate whether a feature runs. Brands change documents. Money rules live on
the pinned terms version and on reference data effective on the business
date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from lms_config.exceptions import CalculationInputError
from lms_config.interest import RateCap, cap_annual_rate, cap_monthly_rate, chargeable_rate


# Ordered. A calculation transaction is REPEATABLE READ and does not call
# Enigma. If a step has no row, the calculation fails closed.
ENGINE_READ_STEPS: tuple[str, ...] = (
    "agreement_pin",
    "published_terms",
    "fee_rules",
    "instruments",
    "interest_cap",
    "initiation_cap",
    "service_fee_cap",
    "reference_rate",
    "interpretation",
    "vat_vendor",
    "post_and_audit",
)

# Not created in this migration. The servicing module owns the agreement.
# The count includes agreements that reached disbursement. A quote, a
# rescission before advance, and a cancellation before advance do not count.
# The gazette does not say whether a later calendar year resets the count;
# this query is the adopted reading (first loan ever with this
# organisation). The calendar-year reading replaces the predicate with
# ``originated_on >= date_trunc('year', :business_date)``.
SHORT_TERM_ORDINAL_SQL = """
SELECT count(*) + 1 AS ordinal
FROM servicing.agreement
WHERE organisation_id = :organisation_id
  AND enigma_person_id = :enigma_person_id
  AND regulatory_classification = 'short_term'
  AND disbursed_on IS NOT NULL
  AND disbursed_on < :business_date
"""

PUBLISHED_TERMS_SQL = """
SELECT id
FROM lms.cfg_product_terms
WHERE product_id = :product_id
  AND status = 'published'
  AND effective_from <= :business_date
ORDER BY effective_from DESC
LIMIT 1
"""

INTEREST_CAP_SQL = """
SELECT classification_code, cap_kind, repo_margin, periodic_rate, subsequent_periodic_rate
FROM lms.ref_interest_cap
WHERE classification_code = :classification
  AND effective_from <= :business_date
  AND (effective_to IS NULL OR effective_to > :business_date)
"""

REFERENCE_RATE_SQL = """
SELECT annual_rate
FROM lms.ref_reference_rate
WHERE code = 'SARB_REPO'
  AND confidence = 'confirmed'
  AND effective_from <= :business_date
  AND (effective_to IS NULL OR effective_to > :business_date)
ORDER BY effective_from DESC
LIMIT 1
"""


@dataclass(frozen=True, slots=True)
class AgreementPin:
    """Immutable facts copied onto the agreement when it is originated.

    Later edits to product terms do not flow into an existing agreement.
    The statutory ceiling is not pinned: it is read again for the accrual
    date, and the charge is min(pinned contractual rate, ceiling on that date).
    """

    agreement_id: UUID
    organisation_id: UUID
    enigma_person_id: UUID
    terms_version_id: UUID
    classification: str
    contractual_monthly_rate: Decimal | None
    contractual_annual_rate: Decimal | None
    contractual_repo_margin: Decimal | None
    day_count: str
    originated_on: date
    short_term_ordinal: int | None
    ncr_registration_number: str


@dataclass(frozen=True, slots=True)
class ResolvedCharge:
    rate: Decimal
    period: str  # "month" or "year"
    agreed: Decimal
    statutory: Decimal
    cap_reduced: bool


def resolve_charge(pin: AgreementPin, cap: RateCap, repo_annual: Decimal | None, on: date) -> ResolvedCharge:
    """The rate used to accrue on ``on``.

    ``on`` is a Johannesburg business date. The caller has already selected
    the cap row and the confirmed repo row effective on that date.
    """
    del on  # the caller selects effective-dated rows; the rate math is pure
    if pin.classification != cap.classification:
        raise CalculationInputError("cap classification does not match the agreement pin")
    if cap.monthly_rate is not None:
        if pin.short_term_ordinal is None or pin.contractual_monthly_rate is None:
            raise CalculationInputError("short-term agreement is missing its ordinal or rate")
        statutory = cap_monthly_rate(cap, pin.short_term_ordinal)
        agreed = pin.contractual_monthly_rate
        rate = chargeable_rate(agreed, statutory)
        return ResolvedCharge(rate, "month", agreed, statutory, rate < agreed)
    if repo_annual is None:
        raise CalculationInputError("annual cap requires a confirmed repo rate on the accrual date")
    if pin.contractual_repo_margin is not None:
        agreed = repo_annual + pin.contractual_repo_margin
    elif pin.contractual_annual_rate is not None:
        agreed = pin.contractual_annual_rate
    else:
        raise CalculationInputError("agreement has no contractual rate")
    statutory = cap_annual_rate(cap, repo_annual)
    rate = chargeable_rate(agreed, statutory)
    return ResolvedCharge(rate, "year", agreed, statutory, rate < agreed)
