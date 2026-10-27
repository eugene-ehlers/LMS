"""Publish-time checks. A terms version that fails these is not publishable.

Missing fees mean zero. They never fall back to the statutory maximum.
A zero-cost classification rejects any positive charge. A short-term
classification rejects a deferred amount, a term, or a rate the regulations
do not allow.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.fees import DEFAULT_INITIATION_CAP, initiation_fee_cents
from lms_config.statute import (
    DAY_COUNT_30_360,
    DAY_COUNT_ACTUAL_ACTUAL,
    SERVICE_FEE_MONTHLY_CENTS,
    SHORT_TERM_DEFERRED_CENTS,
    SHORT_TERM_FIRST_MONTHLY,
    SHORT_TERM_MAX_MONTHS,
    SHORT_TERM_SUBSEQUENT_MONTHLY,
    UNSECURED_REPO_MARGIN,
)


ZERO_COST = "zero_cost"
SHORT_TERM = "short_term"
UNSECURED = "unsecured"
INCIDENTAL = "incidental"
CPA_LAYBY = "cpa_layby"

# Locked decision 5. New products pin one of these. The regulation 40
# divisor codes remain in reference data for agreements already pinned to them.
PROVIDER_DAY_COUNTS = {DAY_COUNT_ACTUAL_ACTUAL, DAY_COUNT_30_360}


@dataclass(frozen=True, slots=True)
class FeeTerms:
    code: str
    amount_cents: int = 0
    # initiation uses the statutory formula capped by the contractual
    # willingness to charge it. ``charge`` is ``zero``, ``statutory_formula``,
    # or ``fixed``.
    charge: str = "zero"


@dataclass(frozen=True, slots=True)
class InstrumentTerms:
    code: str
    kind: str  # credit, security_deposit, cpa_layby
    annual_rate: Decimal | None = None
    monthly_rate: Decimal | None = None
    repo_margin: Decimal | None = None
    day_count: str | None = None
    max_term_months: int | None = None
    max_deferred_cents: int | None = None
    fees: tuple[FeeTerms, ...] = ()
    setoff_requires_mandate: bool = False
    # Locked decision 3. The performing rate is base minus discount.
    # A discount of zero is still stored. None is only valid on a product
    # that charges no interest.
    base_rate: Decimal | None = None
    discount_rate: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class ProductTerms:
    classification: str
    instruments: tuple[InstrumentTerms, ...]
    # Commercial ceiling chosen so Day-1 unsecured loans stay below the
    # large-agreement line. Not a statutory cap.
    max_principal_cents: int | None = None
    # Null inherits the organisation. It does not mean zero days, 100 percent,
    # or a repo-fall option. See docs/LOCKED_DECISIONS.md.
    leniency_days: int | None = None
    full_payment_threshold_percent: Decimal | None = None
    interest_on_deferred_initiation: str | None = None
    repo_rate_fall: str | None = None


def validate_terms(terms: ProductTerms) -> None:
    if not terms.instruments:
        raise CalculationInputError("a product needs at least one instrument")
    if terms.classification == ZERO_COST:
        _reject_any_charge(terms, "a zero-cost product cannot carry a charge")
        return
    if terms.classification == CPA_LAYBY:
        _validate_layby(terms)
        return
    if terms.classification == SHORT_TERM:
        _validate_short_term(terms)
        return
    if terms.classification == UNSECURED:
        _validate_unsecured(terms)
        return
    if terms.classification == INCIDENTAL:
        _validate_incidental(terms)
        return
    raise CalculationInputError(f"unknown classification {terms.classification!r}")


def _reject_any_charge(terms: ProductTerms, message: str) -> None:
    for instrument in terms.instruments:
        if instrument.monthly_rate not in (None, Decimal(0)):
            raise CalculationInputError(message)
        if instrument.annual_rate not in (None, Decimal(0)):
            raise CalculationInputError(message)
        if instrument.repo_margin not in (None, Decimal(0)):
            raise CalculationInputError(message)
        if instrument.base_rate not in (None, Decimal(0)):
            raise CalculationInputError(message)
        if instrument.discount_rate not in (None, Decimal(0)):
            raise CalculationInputError(message)
        for fee in instrument.fees:
            if fee.charge != "zero" or fee.amount_cents != 0:
                raise CalculationInputError(message)


def _validate_layby(terms: ProductTerms) -> None:
    """A CPA section 62 lay-by of goods is not an NCA interest product.

    The only charge it may carry is the regulation 34 cancellation penalty,
    and only as the statutory formula (at most 1% of the cash price), which
    the engine still drops to nil when the penalty was not disclosed or the
    consumer died or was hospitalised.
    """
    if not terms.instruments:
        raise CalculationInputError("a lay-by product needs an instrument")
    for instrument in terms.instruments:
        if instrument.kind != "cpa_layby":
            raise CalculationInputError("a lay-by product only holds a cpa_layby instrument")
        if instrument.monthly_rate not in (None, Decimal(0)):
            raise CalculationInputError("a lay-by cannot carry interest")
        if instrument.annual_rate not in (None, Decimal(0)):
            raise CalculationInputError("a lay-by cannot carry interest")
        if instrument.repo_margin not in (None, Decimal(0)):
            raise CalculationInputError("a lay-by cannot carry interest")
        if instrument.base_rate not in (None, Decimal(0)) or instrument.discount_rate not in (None, Decimal(0)):
            raise CalculationInputError("a lay-by cannot carry interest")
        for fee in instrument.fees:
            if fee.code == "layby_penalty" and fee.charge in {"zero", "statutory_formula"} and fee.amount_cents == 0:
                continue
            raise CalculationInputError("a lay-by cannot carry NCA fees")


def _validate_short_term(terms: ProductTerms) -> None:
    credit = _single(terms, "credit")
    if credit.day_count not in PROVIDER_DAY_COUNTS:
        raise CalculationInputError("short-term day count must be actual/actual or 30/360")
    if credit.monthly_rate is None:
        raise CalculationInputError("short-term terms need a contractual monthly rate")
    _require_campaign(credit, credit.monthly_rate, "short-term")
    if credit.base_rate > SHORT_TERM_FIRST_MONTHLY:
        raise CalculationInputError(
            "short-term base rate exceeds 5% per month; that base is charged when a campaign discount falls away"
        )
    if credit.monthly_rate > SHORT_TERM_SUBSEQUENT_MONTHLY:
        # Allowed only as the first-loan rate. The origination path must
        # still cap later loans at the subsequent rate. Recorded here so a
        # 5% product is visibly a first-loan rate.
        pass
    if credit.max_term_months is None or credit.max_term_months > SHORT_TERM_MAX_MONTHS:
        raise CalculationInputError("short-term term cannot exceed 6 months")
    if credit.max_deferred_cents is None or credit.max_deferred_cents > SHORT_TERM_DEFERRED_CENTS:
        raise CalculationInputError("short-term deferred amount cannot exceed R8 000")
    _check_fees(credit, allow_service=True, allow_initiation=True)
    for instrument in terms.instruments:
        if instrument.kind == "security_deposit":
            _require_zero_deposit(instrument)


def _validate_unsecured(terms: ProductTerms) -> None:
    credit = _single(terms, "credit")
    if credit.day_count not in PROVIDER_DAY_COUNTS:
        raise CalculationInputError("unsecured day count must be actual/actual or 30/360")
    if credit.repo_margin is not None:
        _require_campaign(credit, credit.repo_margin, "unsecured margin")
        if credit.base_rate > UNSECURED_REPO_MARGIN:
            raise CalculationInputError(
                "unsecured base margin cannot exceed RR + 21%; that base is charged when a campaign discount falls away"
            )
    elif credit.annual_rate is not None:
        _require_campaign(credit, credit.annual_rate, "unsecured")
    else:
        raise CalculationInputError("unsecured terms need a fixed annual rate or a repo margin")
    if terms.max_principal_cents is None or terms.max_principal_cents >= 25_000_000:
        raise CalculationInputError(
            "Day-1 unsecured products stay below R250 000 so the unsettled "
            "section 125(2)(c) charge is not reached"
        )
    _check_fees(credit, allow_service=True, allow_initiation=True)


def _validate_incidental(terms: ProductTerms) -> None:
    credit = _single(terms, "credit")
    if credit.monthly_rate is None:
        raise CalculationInputError("incidental credit needs a contractual monthly rate")
    _require_campaign(credit, credit.monthly_rate, "incidental")
    if credit.base_rate > Decimal("0.02"):
        raise CalculationInputError("incidental credit interest cannot exceed 2% per month")
    for fee in credit.fees:
        if fee.code == "initiation" and fee.charge != "zero":
            raise CalculationInputError("Table B sets the incidental initiation fee at nil")
        if fee.code == "service" and fee.amount_cents > SERVICE_FEE_MONTHLY_CENTS:
            raise CalculationInputError("service fee exceeds R60")


def _check_fees(credit: InstrumentTerms, *, allow_service: bool, allow_initiation: bool) -> None:
    for fee in credit.fees:
        if fee.code == "service":
            if not allow_service:
                raise CalculationInputError("service fee is not allowed on this product")
            if fee.amount_cents > SERVICE_FEE_MONTHLY_CENTS:
                raise CalculationInputError("service fee exceeds R60 a month")
        elif fee.code == "initiation":
            if not allow_initiation:
                raise CalculationInputError("initiation fee is not allowed on this product")
            if fee.charge not in {"zero", "statutory_formula"} or fee.amount_cents != 0:
                raise CalculationInputError(
                    "initiation is published as zero or as the statutory formula; "
                    "the engine caps each agreement, so a fixed rand fee is not stored"
                )
        elif fee.code in {"default_admin", "collection"}:
            if fee.charge == "fixed":
                raise CalculationInputError(
                    f"{fee.code} has no gazetted rand cap loaded; a fixed amount cannot be published"
                )
        elif fee.charge != "zero":
            raise CalculationInputError(f"Day-1 does not publish a {fee.code} charge")


def _require_campaign(instrument: InstrumentTerms, effective: Decimal | None, label: str) -> None:
    """The stored price is a base rate minus a campaign discount.

    Locked decision 3. The performing rate must equal that difference,
    including when the difference is zero. The base is what is charged if
    the discount falls away, so a campaign cannot hide a higher penalty.
    """
    if instrument.base_rate is None:
        raise CalculationInputError(
            f"{label} must store a base rate and a campaign discount; "
            "a discount of zero is a campaign with nothing off"
        )
    if instrument.discount_rate < 0 or instrument.base_rate < instrument.discount_rate:
        raise CalculationInputError("campaign discount must be between zero and the base rate")
    if effective != instrument.base_rate - instrument.discount_rate:
        raise CalculationInputError(
            f"{label} contractual rate must equal the base rate minus the campaign discount"
        )


def _require_zero_deposit(instrument: InstrumentTerms) -> None:
    if instrument.monthly_rate not in (None, Decimal(0)) or instrument.annual_rate not in (None, Decimal(0)):
        raise CalculationInputError("a security deposit accrues no interest")
    if instrument.base_rate not in (None, Decimal(0)) or instrument.discount_rate not in (None, Decimal(0)):
        raise CalculationInputError("a security deposit has no campaign rate")
    for fee in instrument.fees:
        if fee.charge != "zero" or fee.amount_cents != 0:
            raise CalculationInputError("a security deposit is not a lay-by and carries no CPA penalty")
    if not instrument.setoff_requires_mandate:
        raise CalculationInputError("set-off against a deposit requires an Enigma mandate id")


def _single(terms: ProductTerms, kind: str) -> InstrumentTerms:
    matches = [item for item in terms.instruments if item.kind == kind]
    if len(matches) != 1:
        raise CalculationInputError(f"expected one {kind} instrument")
    return matches[0]


def capitalized_short_term_fits(cash_advanced_cents: int) -> bool:
    """True when cash plus the adopted initiation fee does not exceed R8 000."""
    fee = initiation_fee_cents(cash_advanced_cents, base="cash_advanced", cap=DEFAULT_INITIATION_CAP)
    return cash_advanced_cents + fee <= SHORT_TERM_DEFERRED_CENTS
