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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from lms_config.calendar import value_date
from lms_config.exceptions import CalculationInputError
from lms_config.money import require_non_negative_cents
from lms_config.statute import DAY_COUNT_30_360, DAY_COUNT_ACTUAL_ACTUAL
from lms_config.validate import ZERO_COST, CPA_LAYBY, ProductTerms


INTEREST_ON_INITIATION_NONE = "none"
INTEREST_ON_INITIATION_PERMITTED = "permitted"
REPO_FALL_CONTRACT = "contract_rate"
REPO_FALL_LOWER = "lower_of_contract_and_cap"
VAT_EXCLUSIVE = "exclusive"
VAT_INCLUSIVE = "inclusive"
LATE_DISBURSEMENT_ADJUST = "adjust_instalment"
LATE_DISBURSEMENT_KEEP = "keep_instalment"
PREPAY_SHORTEN = "shorten_term"
PREPAY_DROP = "drop_instalment"
PROVIDER_DAY_COUNTS = {DAY_COUNT_ACTUAL_ACTUAL, DAY_COUNT_30_360}

# Decision 7. Three unnamed section 103(5) edges are unsigned. The clip
# stays off. No posting may treat this flag as true until counsel lists
# those edges. The arithmetic in duplum.py is not a posting.
IN_DUPLUM_CLIP_POSTS = False


@dataclass(frozen=True, slots=True)
class OrganisationSettings:
    """Lender-level elections. Null means the organisation has not chosen.

    Decision 19 stores these at organisation level. A product value, when
    set, overrides. Nothing here is filled with an example or with the
    substantive default named in an earlier decision.
    """

    leniency_days: int | None
    full_payment_threshold_percent: Decimal | None
    interest_on_deferred_initiation: str | None = None
    repo_rate_fall: str | None = None
    day_count_code: str | None = None
    base_rate: Decimal | None = None
    discount_rate: Decimal | None = None
    vat_on_rand_maxima: str | None = None
    late_disbursement: str | None = None
    partial_prepayment: str | None = None
    # Decision 19. Null is unset. Booking does not fill either one in.
    in_duplum_trigger: str | None = None
    residual_write_off_threshold_cents: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCreditSettings:
    leniency_days: int
    full_payment_threshold_percent: Decimal
    interest_on_deferred_initiation: str
    repo_rate_fall: str
    day_count_code: str | None
    base_rate: Decimal
    discount_rate: Decimal
    vat_on_rand_maxima: str
    late_disbursement: str
    partial_prepayment: str
    # Copied at origination when the organisation or product stored one.
    # None means the caller has not chosen. Booking and collections fail closed.
    in_duplum_trigger: str | None = None
    # Decision 19. resolve_residual_threshold_cents writes 10 000 cents when both levels are null.
    residual_write_off_threshold_cents: int = 10_000


def resolve_customer_settings(
    organisation: OrganisationSettings,
    product: ProductTerms,
) -> ResolvedCreditSettings:
    """Product override wins. Null at both levels fails closed.

    Decision 19. A zero-cost or CPA lay-by product has an explicit zero
    price, so it does not inherit a campaign rate. Decision 5 does not
    say a product with no accrual must store a day-count divisor, so a
    missing day count is allowed only for those two classifications. A
    credit product still fails closed. Decision 10's ``none`` is stored
    by the provider. It is not written in when the column is null.
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
    day_count = _override(_product_day_count(product), organisation.day_count_code)
    base_rate, discount_rate = _resolve_campaign(organisation, product)
    vat = _override(product.vat_on_rand_maxima, organisation.vat_on_rand_maxima)
    late = _override(product.late_disbursement, organisation.late_disbursement)
    prepay = _override(product.partial_prepayment, organisation.partial_prepayment)
    # Decision 19. An invalid token fails here. A null is left as None so a
    # caller that is not booking can still see it. Servicing.book refuses
    # that null. resolve_in_duplum_trigger fails closed on use.
    trigger = _override(product.in_duplum_trigger, organisation.in_duplum_trigger)
    if trigger is not None and trigger not in IN_DUPLUM_TRIGGERS:
        raise CalculationInputError(
            "in_duplum_trigger is not set on the product or the organisation"
        )
    # Decision 19. An unset organisation or product value fills R100.
    residual = resolve_residual_threshold_cents(
        organisation.residual_write_off_threshold_cents,
        product.residual_write_off_threshold_cents,
    )
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
            "interest_on_deferred_initiation is not set on the product or the organisation"
        )
    if fall not in {REPO_FALL_CONTRACT, REPO_FALL_LOWER}:
        raise CalculationInputError(
            "repo_rate_fall is not set on the product or the organisation"
        )
    if product.classification in {ZERO_COST, CPA_LAYBY}:
        if day_count is not None and day_count not in PROVIDER_DAY_COUNTS:
            raise CalculationInputError(
                "day_count must be actual/actual or 30/360 when a zero-price product sets one"
            )
    elif day_count not in PROVIDER_DAY_COUNTS:
        raise CalculationInputError(
            "day_count is not set to actual/actual or 30/360 on the product or the organisation"
        )
    if vat not in {VAT_EXCLUSIVE, VAT_INCLUSIVE}:
        raise CalculationInputError(
            "vat_on_rand_maxima is not set on the product or the organisation"
        )
    if late not in {LATE_DISBURSEMENT_ADJUST, LATE_DISBURSEMENT_KEEP}:
        raise CalculationInputError(
            "late_disbursement is not set on the product or the organisation"
        )
    if prepay not in {PREPAY_SHORTEN, PREPAY_DROP}:
        raise CalculationInputError(
            "partial_prepayment is not set on the product or the organisation"
        )
    return ResolvedCreditSettings(
        leniency,
        threshold,
        initiation,
        fall,
        day_count,
        base_rate,
        discount_rate,
        vat,
        late,
        prepay,
        trigger,
        residual,
    )


def campaign_rate(
    base_rate: Decimal,
    discount_rate: Decimal,
    *,
    in_default: bool = False,
    discount_fallen_away: bool = False,
) -> Decimal:
    """Contractual rate after decision 3.

    While the discount still applies, the rate is ``base_rate`` minus
    ``discount_rate``. That result may be zero. The discount stays through
    the leniency window. It falls away on the default flag date. A later
    cure does not bring it back: pass ``discount_fallen_away`` once the
    flag date has removed it. The rate is then the base, which is the
    contractual rate, so the penalty does not exceed the contract.
    """
    if base_rate < 0 or discount_rate < 0:
        raise CalculationInputError("rates cannot be negative")
    if discount_rate > base_rate:
        raise CalculationInputError("campaign discount cannot exceed the base rate")
    if in_default or discount_fallen_away:
        return base_rate
    return base_rate - discount_rate


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

    Decision 4: the lay-by hold reduces only this interest base. Principal
    stays gross for in duplum and for settlement. The result is not
    negative. Decision 10: a deferred initiation fee earns interest only
    when the provider stored ``permitted``. The fee can still sit inside
    principal for section 126 and for the in-duplum ceiling.
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


# Decision 6. The client chooses which event opens an in-duplum episode.
# An unset value fails closed. There is no platform default.
TRIGGER_CONTRACTUAL_BREACH = "contractual_breach"
TRIGGER_COLLECTIONS_DEFAULT = "collections_default"
IN_DUPLUM_TRIGGERS = frozenset({TRIGGER_CONTRACTUAL_BREACH, TRIGGER_COLLECTIONS_DEFAULT})

# Decision 19. The residual write-off threshold has a platform default of
# R100. An unset organisation or product value fills R100. Other elections
# still fail closed when unset. R100 is 10 000 cents.
RESIDUAL_WRITE_OFF_DEFAULT_CENTS = 10_000


def resolve_in_duplum_trigger(organisation: str | None, product: str | None = None) -> str:
    """Decision 6 and decision 19. Product override wins. Unset fails closed."""
    chosen = product if product is not None else organisation
    if chosen not in IN_DUPLUM_TRIGGERS:
        raise CalculationInputError(
            "in_duplum_trigger is not set on the product or the organisation"
        )
    return chosen


def resolve_residual_threshold_cents(
    organisation: int | None,
    product: int | None = None,
) -> int:
    """Decision 19. A stored value wins. A null at both levels fills R100.

    The amount is cents. R100 is 10 000 cents. Zero is a stored choice.
    A negative value is refused.
    """
    chosen = product if product is not None else organisation
    if chosen is None:
        return RESIDUAL_WRITE_OFF_DEFAULT_CENTS
    require_non_negative_cents(chosen, "residual write-off threshold")
    return chosen


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


@dataclass(frozen=True, slots=True)
class RecognisedReceipt:
    """One receipt the system has recognised. ``sequence`` is the seal order."""

    recognised_at: datetime
    sequence: int
    amount_cents: int
    due_on: date


def order_recognised_events(receipts: Sequence[RecognisedReceipt]) -> tuple[RecognisedReceipt, ...]:
    """Decision 1. Same value date keeps recognition sequence.

    Python's sort is stable, so two receipts with the same value date and
    the same sequence keep the order they were passed in.
    """
    return tuple(sorted(receipts, key=lambda item: (value_date(item.recognised_at), item.sequence)))


def receipts_visible_at_morning_check(
    receipts: Sequence[RecognisedReceipt],
    *,
    flag_on: date,
    due_on: date,
) -> tuple[RecognisedReceipt, ...]:
    """Receipts for ``due_on`` whose value date is on or before the flag date.

    A payment recognised at any time on the flag date has value date 00:00
    that day and is visible to the morning check. A payment recognised on
    the next calendar day is not.
    """
    ordered = order_recognised_events(receipts)
    return tuple(
        item
        for item in ordered
        if item.due_on == due_on and value_date(item.recognised_at) <= flag_on
    )


def is_in_default_at_morning_check(
    *,
    due_on: date,
    check_on: date,
    leniency_days: int,
    receipts: Sequence[RecognisedReceipt],
    instalment_cents: int,
    threshold_percent: Decimal,
) -> bool:
    """Decision 6, after the flag-date receipts have been taken in.

    ``instalment_cents`` is the original principal slice plus the levied
    charges that share ``due_on``. The caller excludes unbilled interest.
    """
    if leniency_days < 0:
        raise CalculationInputError("leniency_days cannot be negative")
    flag_on = due_on + timedelta(days=leniency_days)
    if check_on < flag_on:
        return False
    visible = receipts_visible_at_morning_check(receipts, flag_on=flag_on, due_on=due_on)
    received = 0
    for item in visible:
        require_non_negative_cents(item.amount_cents, "received")
        received += item.amount_cents
    return not is_full_payment(received, instalment_cents, threshold_percent)


def nominal_annual_rate(periodic_rate: Decimal, periods_per_year: int) -> Decimal:
    """Decision 17. Simple nominal annual rate, not an effective rate.

    ``periods_per_year`` is supplied by the caller. The lock does not say
    whether weekly means 52 or 365/7.
    """
    if periodic_rate < 0:
        raise CalculationInputError("periodic rate cannot be negative")
    if periods_per_year <= 0:
        raise CalculationInputError("periods per year must be positive")
    return periodic_rate * periods_per_year


def _product_day_count(product: ProductTerms) -> str | None:
    counts = {
        instrument.day_count
        for instrument in product.instruments
        if instrument.kind == "credit" and instrument.day_count is not None
    }
    if len(counts) > 1:
        raise CalculationInputError("credit instruments on one product disagree on day count")
    if not counts:
        return None
    return next(iter(counts))


def _resolve_campaign(
    organisation: OrganisationSettings,
    product: ProductTerms,
) -> tuple[Decimal, Decimal]:
    if product.classification in {ZERO_COST, CPA_LAYBY}:
        return Decimal(0), Decimal(0)
    credits = [instrument for instrument in product.instruments if instrument.kind == "credit"]
    bases = {instrument.base_rate for instrument in credits}
    if len(bases) > 1:
        raise CalculationInputError("credit instruments on one product disagree on the base rate")
    product_base = next(iter(bases)) if bases else None
    if product_base is not None:
        discounts = {instrument.discount_rate for instrument in credits}
        if len(discounts) != 1:
            raise CalculationInputError("credit instruments on one product disagree on the discount")
        discount = next(iter(discounts))
        if discount is None:
            raise CalculationInputError("a product base rate requires a campaign discount")
        return product_base, discount
    if organisation.base_rate is None or organisation.discount_rate is None:
        raise CalculationInputError(
            "campaign base_rate and discount_rate are not set on the product or the organisation"
        )
    return organisation.base_rate, organisation.discount_rate


def _override(product_value, organisation_value):
    if product_value is not None:
        return product_value
    return organisation_value


def _check_threshold(threshold_percent: Decimal) -> None:
    if threshold_percent <= 0 or threshold_percent > 100:
        raise CalculationInputError(
            "full payment threshold must be above 0 and at most 100 percent"
        )
