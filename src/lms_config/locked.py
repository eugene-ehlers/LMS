"""Behaviour taken from docs/LOCKED_DECISIONS.md.

That document is the source of truth. This module does not choose a value
the document leaves open. Examples in the document (4 or 5 leniency days,
95 percent) are examples, not defaults.

"Customer" in decision 6 is the credit provider: the Enigma organisation,
with a nullable override on the product. It is not a per-consumer setting.
A resolved value is copied onto the agreement at origination. A later edit
of the organisation or the product does not rewrite an existing agreement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.money import require_non_negative_cents
from lms_config.validate import ProductTerms


INTEREST_ON_INITIATION_NONE = "none"
INTEREST_ON_INITIATION_PERMITTED = "permitted"
REPO_FALL_CONTRACT = "contract_rate"
REPO_FALL_LOWER = "lower_of_contract_and_cap"


@dataclass(frozen=True, slots=True)
class OrganisationSettings:
    """Lender-level settings. Null means the organisation has not chosen."""

    leniency_days: int | None
    full_payment_threshold_percent: Decimal | None
    # Decision 10 states the default: no interest on a deferred initiation fee.
    interest_on_deferred_initiation: str = INTEREST_ON_INITIATION_NONE
    # Decision 11 does not pick option A or option B.
    repo_rate_fall: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCreditSettings:
    leniency_days: int
    full_payment_threshold_percent: Decimal
    interest_on_deferred_initiation: str
    repo_rate_fall: str | None


def resolve_customer_settings(
    organisation: OrganisationSettings,
    product: ProductTerms,
) -> ResolvedCreditSettings:
    """Product override wins. Null at both levels fails closed.

    ``repo_rate_fall`` may still be null. Accrual of a repo-linked rate
    then fails closed. This function does not pick option A or option B.
    """
    leniency = _override(product.leniency_days, organisation.leniency_days)
    threshold = _override(
        product.full_payment_threshold_percent,
        organisation.full_payment_threshold_percent,
    )
    initiation = _override(
        product.interest_on_deferred_initiation,
        organisation.interest_on_deferred_initiation,
    )
    fall = _override(product.repo_rate_fall, organisation.repo_rate_fall)
    if leniency is None:
        raise CalculationInputError(
            "leniency_days is not set on the product or the organisation"
        )
    if leniency < 0:
        raise CalculationInputError("leniency_days cannot be negative")
    if threshold is None:
        raise CalculationInputError(
            "full_payment_threshold_percent is not set on the product or the organisation"
        )
    _check_threshold(threshold)
    if initiation not in {INTEREST_ON_INITIATION_NONE, INTEREST_ON_INITIATION_PERMITTED}:
        raise CalculationInputError(
            "interest_on_deferred_initiation must be 'none' or 'permitted'"
        )
    if fall not in {None, REPO_FALL_CONTRACT, REPO_FALL_LOWER}:
        raise CalculationInputError(
            "repo_rate_fall must be 'contract_rate' or 'lower_of_contract_and_cap'"
        )
    return ResolvedCreditSettings(leniency, threshold, initiation, fall)


def campaign_rate(base_rate: Decimal, discount_rate: Decimal, *, in_default: bool) -> Decimal:
    """Contractual rate after decision 3.

    While the agreement is not in default the rate is ``base_rate`` minus
    ``discount_rate``. That result may be zero. Once default is flagged and
    the discount falls away, the rate is the base rate. That rate is the
    contractual rate at that point, so the penalty does not exceed it.
    """
    if base_rate < 0 or discount_rate < 0:
        raise CalculationInputError("rates cannot be negative")
    if discount_rate > base_rate:
        raise CalculationInputError("campaign discount cannot exceed the base rate")
    performing = base_rate - discount_rate
    if in_default:
        return base_rate
    return performing


def is_full_payment(
    received_cents: int,
    instalment_cents: int,
    threshold_percent: Decimal,
) -> bool:
    """True when receipts cover the configured percent of the instalment.

    ``threshold_percent`` is a percent, so 95 means 95 percent, not 0.95.
    Exactly the threshold counts as full. A zero instalment is already full.
    """
    require_non_negative_cents(received_cents, "received")
    require_non_negative_cents(instalment_cents, "instalment")
    _check_threshold(threshold_percent)
    if instalment_cents == 0:
        return True
    return Decimal(received_cents) * Decimal(100) >= Decimal(instalment_cents) * threshold_percent


def is_in_default(
    *,
    due_on: date,
    value_date: date,
    leniency_days: int,
    received_cents: int,
    instalment_cents: int,
    threshold_percent: Decimal,
) -> bool:
    """The one default test, for in duplum and for collections.

    Leniency is a number of calendar days. The flag date is the contractual
    due date plus that many days. Receipts already value-dated on ``value_date``
    count, because a payment that day is treated as 00:00. Before the flag
    date this returns false even when nothing has been received. Interest
    for those days is still calculated on the outstanding balance; this
    function does not reduce it.
    """
    if leniency_days < 0:
        raise CalculationInputError("leniency_days cannot be negative")
    flag_on = due_on + timedelta(days=leniency_days)
    if value_date < flag_on:
        return False
    return not is_full_payment(received_cents, instalment_cents, threshold_percent)


def interest_bearing_cents(
    *,
    principal_cents: int,
    capitalised_initiation_cents: int,
    deposit_hold_cents: int,
    charge_interest_on_initiation: bool,
) -> int:
    """Balance interest accrues on.

    Decision 4: a linked lay-by hold is deducted, and the result is not
    negative. Decision 10: a deferred initiation fee earns interest only
    when the provider chose ``permitted``. The fee can still sit inside
    principal for section 126 and for the in-duplum base.
    """
    require_non_negative_cents(principal_cents, "principal")
    require_non_negative_cents(capitalised_initiation_cents, "capitalised initiation")
    require_non_negative_cents(deposit_hold_cents, "deposit hold")
    if capitalised_initiation_cents > principal_cents:
        raise CalculationInputError("capitalised initiation cannot exceed principal")
    base = principal_cents
    if not charge_interest_on_initiation:
        base -= capitalised_initiation_cents
    base -= deposit_hold_cents
    return max(0, base)


def duplum_base_cents(*, cash_balance_cents: int, capitalised_initiation_cents: int) -> int:
    """Unpaid principal when default is first flagged.

    Decision 7: pre-default capitalised initiation is part of that principal.
    A payment later reduces what is owed and does not reset the counter.
    Post-default interest and fees stay charges even if a statement shows
    them as capitalised.
    """
    require_non_negative_cents(cash_balance_cents, "cash balance")
    require_non_negative_cents(capitalised_initiation_cents, "capitalised initiation")
    return cash_balance_cents + capitalised_initiation_cents


def _override(product_value, organisation_value):
    if product_value is not None:
        return product_value
    return organisation_value


def _check_threshold(threshold_percent: Decimal) -> None:
    if threshold_percent <= 0 or threshold_percent > 100:
        raise CalculationInputError(
            "full payment threshold must be above 0 and at most 100 percent"
        )
