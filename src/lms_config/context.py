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
from lms_config.locked import (
    REPO_FALL_CONTRACT,
    REPO_FALL_LOWER,
    campaign_rate,
)


# Ordered. A calculation transaction is REPEATABLE READ and does not call
# Enigma. If a step has no row, the calculation fails closed.
ENGINE_READ_STEPS: tuple[str, ...] = (
    "agreement_pin",
    "customer_settings",
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

# Product null inherits the organisation. A null result is not a number:
# leniency and the threshold fail closed, and repo_rate_fall fails closed
# when a later accrual has to apply locked decision 11.
CUSTOMER_SETTINGS_SQL = """
SELECT
  COALESCE(terms.leniency_days, settings.leniency_days) AS leniency_days,
  COALESCE(
    terms.full_payment_threshold_percent,
    settings.full_payment_threshold_percent
  ) AS full_payment_threshold_percent,
  COALESCE(
    terms.interest_on_deferred_initiation,
    settings.interest_on_deferred_initiation
  ) AS interest_on_deferred_initiation,
  COALESCE(terms.repo_rate_fall, settings.repo_rate_fall) AS repo_rate_fall,
  terms.base_rate,
  terms.discount_rate
FROM lms.cfg_product_terms AS terms
JOIN lms.cfg_product AS product ON product.id = terms.product_id
JOIN lms.cfg_organisation_settings AS settings
  ON settings.organisation_id = product.organisation_id
WHERE terms.id = :terms_version_id
  AND terms.status = 'published'
  AND product.organisation_id = :organisation_id
"""


@dataclass(frozen=True, slots=True)
class AgreementPin:
    """Immutable facts copied onto the agreement when it is originated.

    Later edits to product terms or organisation settings do not flow into
    an existing agreement. The statutory ceiling is not pinned. On a
    short-term agreement the ordinal cap applies on every accrual. On an
    annual agreement, locked decision 11 decides whether a later fall in
    the cap reduces the rate. That choice is copied here. Null fails closed
    on a later accrual.
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
    base_rate: Decimal | None = None
    discount_rate: Decimal = Decimal(0)
    repo_rate_fall: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCharge:
    rate: Decimal
    period: str  # "month" or "year"
    agreed: Decimal
    statutory: Decimal
    cap_reduced: bool


def resolve_charge(
    pin: AgreementPin,
    cap: RateCap,
    repo_annual: Decimal | None,
    on: date,
    *,
    in_default: bool = False,
) -> ResolvedCharge:
    """The rate used to accrue on ``on``.

    ``on`` is a Johannesburg business date. The caller has already selected
    the cap row and the confirmed repo row effective on that date, and has
    already applied ``is_in_default``. Leniency alone is not ``in_default``.

    A campaign uses ``base_rate`` minus ``discount_rate`` until default is
    flagged. After that the discount falls away and the rate is the base.
    That base is not above the contractual rate, because it is the
    contractual rate once the discount is gone.

    A short-term monthly cap is applied on every accrual. It is the cap for
    that loan's ordinal, not a later movement of the repo rate. An annual
    cap is applied in full on the origination date, so an unlawful rate
    cannot be booked. On a later date, locked decision 11 applies and a
    missing ``repo_rate_fall`` fails closed.
    """
    if on < pin.originated_on:
        raise CalculationInputError("accrual date is before origination")
    if pin.classification != cap.classification:
        raise CalculationInputError("cap classification does not match the agreement pin")
    if cap.monthly_rate is not None:
        if pin.short_term_ordinal is None:
            raise CalculationInputError("short-term agreement is missing its ordinal")
        statutory = cap_monthly_rate(cap, pin.short_term_ordinal)
        agreed = _component(pin, pin.contractual_monthly_rate, in_default=in_default)
        _guard_origination(pin, pin.contractual_monthly_rate, statutory, on)
        rate = chargeable_rate(agreed, statutory)
        return ResolvedCharge(rate, "month", agreed, statutory, rate < agreed)
    if repo_annual is None:
        raise CalculationInputError("annual cap requires a confirmed repo rate on the accrual date")
    if pin.contractual_repo_margin is not None:
        agreed = repo_annual + _component(pin, pin.contractual_repo_margin, in_default=in_default)
        penalty = repo_annual + _component(pin, pin.contractual_repo_margin, in_default=True)
    elif pin.contractual_annual_rate is not None:
        agreed = _component(pin, pin.contractual_annual_rate, in_default=in_default)
        penalty = _component(pin, pin.contractual_annual_rate, in_default=True)
    else:
        raise CalculationInputError("agreement has no contractual rate")
    statutory = cap_annual_rate(cap, repo_annual)
    if on == pin.originated_on and penalty > statutory:
        raise CalculationInputError(
            "base rate exceeds the statutory maximum on the origination date"
        )
    return _annual_after_origination(pin, agreed, statutory, on)


def _component(pin: AgreementPin, contractual: Decimal | None, *, in_default: bool) -> Decimal:
    if pin.base_rate is None:
        if pin.discount_rate != 0:
            raise CalculationInputError("a campaign discount requires a base rate")
        if contractual is None:
            raise CalculationInputError("agreement has no contractual rate")
        return contractual
    performing = campaign_rate(pin.base_rate, pin.discount_rate, in_default=False)
    if contractual is not None and contractual != performing:
        raise CalculationInputError(
            "pinned contractual rate must equal base rate minus campaign discount"
        )
    return campaign_rate(pin.base_rate, pin.discount_rate, in_default=in_default)


def _guard_origination(
    pin: AgreementPin,
    contractual: Decimal | None,
    statutory: Decimal,
    on: date,
) -> None:
    """The base rate is charged when a campaign discount falls away.

    On the origination date that base has to be within the statutory
    maximum. Checking only the discounted rate would let a campaign hide
    an unlawful penalty.
    """
    if on != pin.originated_on:
        return
    penalty = _component(pin, contractual, in_default=True)
    if penalty > statutory:
        raise CalculationInputError(
            "base rate exceeds the statutory maximum on the origination date"
        )


def _annual_after_origination(
    pin: AgreementPin,
    agreed: Decimal,
    statutory: Decimal,
    on: date,
) -> ResolvedCharge:
    if on == pin.originated_on:
        return ResolvedCharge(agreed, "year", agreed, statutory, False)
    if pin.repo_rate_fall is None:
        raise CalculationInputError(
            "repo_rate_fall is not set on the organisation or the product"
        )
    if pin.repo_rate_fall == REPO_FALL_CONTRACT:
        return ResolvedCharge(agreed, "year", agreed, statutory, False)
    if pin.repo_rate_fall == REPO_FALL_LOWER:
        rate = chargeable_rate(agreed, statutory)
        return ResolvedCharge(rate, "year", agreed, statutory, rate < agreed)
    raise CalculationInputError(f"unknown repo_rate_fall {pin.repo_rate_fall!r}")
