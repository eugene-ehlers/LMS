"""Quote stub. It returns the rate, premium, and application number Servicing.book can store.

The rate is the rate already on the product. This stub does not price, and it
does not decide whether a short-term loan is concurrent or subsequent. A rate
above the statutory maximum already coded in ``lms_config.statute`` is not
returned as an approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from lms.calc.models import RepoRate
from lms.dummies.fixtures import APPLICATION_NUMBER_PREFIX, FIXED_CREDIT_LIFE_PREMIUM_CENTS
from lms_config.calendar import value_date, value_instant
from lms_config.locked import OrganisationSettings
from lms_config.statute import SHORT_TERM_FIRST_MONTHLY, UNSECURED_REPO_MARGIN
from lms_config.validate import SHORT_TERM, UNSECURED, ProductTerms


class QuoteStubError(Exception):
    """The quote cannot become an approval. Servicing.book is not called."""


@dataclass(frozen=True)
class QuoteRequest:
    """The booking facts the caller already has. Amounts are integer cents."""

    organisation_id: str
    person_id: str
    product: ProductTerms
    settings: OrganisationSettings
    recognised_at: datetime
    cash_advanced_cents: int
    frequency: str
    schedule: tuple[tuple[date, int], ...]
    idempotency_key: str
    initiation_fee_cents: int = 0
    quoted_disbursement: date | None = None
    repos: tuple[RepoRate, ...] = ()


@dataclass(frozen=True)
class QuoteApproval:
    """An approval plus the keyword arguments ``Servicing.book`` already accepts."""

    approved: bool
    contractual_rate: Decimal
    credit_life_premium_cents: int
    application_number: str
    short_term_rate_cap: Decimal | None
    organisation_id: str
    person_id: str
    product: ProductTerms
    settings: OrganisationSettings
    recognised_at: datetime
    cash_advanced_cents: int
    frequency: str
    schedule: tuple[tuple[date, int], ...]
    initiation_fee_cents: int
    idempotency_key: str
    quoted_disbursement: date | None
    repos: tuple[RepoRate, ...]

    def book_payload(self) -> dict:
        """Arguments ``Servicing.book`` accepts today. No extra keys."""

        return {
            "organisation_id": self.organisation_id,
            "person_id": self.person_id,
            "product": self.product,
            "settings": self.settings,
            "recognised_at": self.recognised_at,
            "cash_advanced_cents": self.cash_advanced_cents,
            "frequency": self.frequency,
            "schedule": self.schedule,
            "initiation_fee_cents": self.initiation_fee_cents,
            "quoted_disbursement": self.quoted_disbursement,
            "idempotency_key": self.idempotency_key,
            "repos": self.repos,
            "rate_supplied_by_decision_engine": True,
            "short_term_rate_cap": self.short_term_rate_cap,
        }


class DecisionQuoteStub:
    """One engine instance. Application numbers increase inside that instance."""

    def __init__(self, *, credit_life_premium_cents: int = FIXED_CREDIT_LIFE_PREMIUM_CENTS) -> None:
        self._premium_cents = _cents(credit_life_premium_cents, "credit_life_premium_cents")
        self._issued = 0

    def quote(self, request: QuoteRequest) -> QuoteApproval:
        if not isinstance(request, QuoteRequest):
            raise QuoteStubError("quote expects a QuoteRequest")
        _cents(request.cash_advanced_cents, "cash_advanced_cents")
        _cents(request.initiation_fee_cents, "initiation_fee_cents")
        rate, cap = _rate_inside_cap(request.product)
        recognised_at = value_instant(value_date(request.recognised_at))
        self._issued += 1
        return QuoteApproval(
            approved=True,
            contractual_rate=rate,
            credit_life_premium_cents=self._premium_cents,
            application_number=f"{APPLICATION_NUMBER_PREFIX}{self._issued:08d}",
            short_term_rate_cap=cap,
            organisation_id=request.organisation_id,
            person_id=request.person_id,
            product=request.product,
            settings=request.settings,
            recognised_at=recognised_at,
            cash_advanced_cents=request.cash_advanced_cents,
            frequency=request.frequency,
            schedule=request.schedule,
            initiation_fee_cents=request.initiation_fee_cents,
            idempotency_key=request.idempotency_key,
            quoted_disbursement=request.quoted_disbursement,
            repos=request.repos,
        )


def _rate_inside_cap(product: ProductTerms) -> tuple[Decimal, Decimal | None]:
    if not isinstance(product, ProductTerms):
        raise QuoteStubError("product must be ProductTerms")
    credits = tuple(instrument for instrument in product.instruments if instrument.kind == "credit")
    if len(credits) != 1:
        raise QuoteStubError("a quote needs one credit instrument")
    credit = credits[0]
    if product.classification == SHORT_TERM:
        rate = credit.monthly_rate
        cap: Decimal | None = SHORT_TERM_FIRST_MONTHLY
        ceiling = SHORT_TERM_FIRST_MONTHLY
    elif product.classification == UNSECURED:
        rate = credit.base_rate
        cap = None
        ceiling = UNSECURED_REPO_MARGIN
    else:
        raise QuoteStubError(
            "the statutory cap for this classification is not in the Day-1 constants"
        )
    if not isinstance(rate, Decimal):
        raise QuoteStubError("the contractual rate must be a Decimal already on the product")
    if rate < 0:
        raise QuoteStubError("the contractual rate cannot be negative")
    if rate > ceiling:
        raise QuoteStubError(
            "the contractual rate is above the statutory cap, so there is no approval"
        )
    return rate, cap


def _cents(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuoteStubError(f"{name} must be zero or a positive number of integer cents")
    return value
