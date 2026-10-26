"""Interest the engine is allowed to charge.

Regulation 40:
- non-short-term daily interest = deferred amount × annual rate / days in the year
- short-term daily interest = deferred amount × monthly rate / days in the month
- the day's deferred amount is the average for the day, or the balance at a
  time of day the agreement states
- interest is added to the deferred amount at most once a month
- days in the year may be 365 or the actual length of that year
- days in the month, for a short-term loan, may be 30 or the actual length

Section 103(5) is applied by the caller (see ``duplum``) before a charge is
posted. This module only computes the uncapped daily amount and the
contractual-versus-statutory rate.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.money import floor_cents, half_up_cents, require_non_negative_cents
from lms_config.statute import (
    DAY_COUNT_30,
    DAY_COUNT_365,
    DAY_COUNT_ACTUAL_MONTH,
    DAY_COUNT_ACTUAL_YEAR,
)


@dataclass(frozen=True, slots=True)
class RateCap:
    """One classification's ceiling on one date.

    Exactly one of ``annual_margin_over_repo`` or ``monthly_rate`` is set.
    ``subsequent_monthly_rate`` is the Table A "subsequent loan" rate. It is
    None when the gazette states a single rate.
    """

    classification: str
    annual_margin_over_repo: Decimal | None = None
    monthly_rate: Decimal | None = None
    subsequent_monthly_rate: Decimal | None = None

    def __post_init__(self) -> None:
        monthly = self.monthly_rate is not None
        annual = self.annual_margin_over_repo is not None
        if monthly == annual:
            raise CalculationInputError(
                f"{self.classification} cap must be either a monthly rate or a repo margin"
            )
        if self.subsequent_monthly_rate is not None and not monthly:
            raise CalculationInputError("a subsequent rate only exists on a monthly cap")


def cap_annual_rate(cap: RateCap, repo_annual: Decimal) -> Decimal:
    if cap.annual_margin_over_repo is None:
        raise CalculationInputError(f"{cap.classification} is not an annual cap")
    if repo_annual < 0:
        raise CalculationInputError("repo rate cannot be negative")
    return repo_annual + cap.annual_margin_over_repo


def cap_monthly_rate(cap: RateCap, ordinal: int) -> Decimal:
    """Statutory monthly ceiling for a loan with this ordinal.

    ``ordinal`` 1 is the consumer's first short-term loan with this
    organisation. The adopted reading (see the design note on
    ``short_term_ordinal``) passes that lifetime ordinal. The calendar-year
    reading would pass a within-year ordinal instead. This function does
    not decide which count was used.
    """
    if cap.monthly_rate is None:
        raise CalculationInputError(f"{cap.classification} is not a monthly cap")
    if ordinal < 1:
        raise CalculationInputError("loan ordinal starts at 1")
    if ordinal == 1 or cap.subsequent_monthly_rate is None:
        return cap.monthly_rate
    return cap.subsequent_monthly_rate


def chargeable_rate(agreed: Decimal, statutory: Decimal) -> Decimal:
    """min(agreed, statutory cap in force on the accrual date).

    A contractual rate above the cap is reduced. A contractual rate below
    the cap is left alone. The cap is a maximum, not a price.
    """
    if agreed < 0 or statutory < 0:
        raise CalculationInputError("rates cannot be negative")
    return min(agreed, statutory)


def year_divisor(day: date, convention: str) -> int:
    if convention == DAY_COUNT_365:
        return 365
    if convention == DAY_COUNT_ACTUAL_YEAR:
        return 366 if calendar.isleap(day.year) else 365
    raise CalculationInputError(f"{convention!r} is not an annual day-count")


def month_divisor(day: date, convention: str) -> int:
    if convention == DAY_COUNT_30:
        return 30
    if convention == DAY_COUNT_ACTUAL_MONTH:
        return calendar.monthrange(day.year, day.month)[1]
    raise CalculationInputError(f"{convention!r} is not a monthly day-count")


def daily_interest_cents(
    deferred_cents: int,
    *,
    periodic_rate: Decimal,
    divisor_days: int,
) -> Decimal:
    """One day's interest in cents, unrounded.

    ``periodic_rate`` is the annual rate for a non-short-term agreement and
    the monthly rate for a short-term agreement. The caller passes the
    divisor regulation 40 assigns to that kind of agreement. The two are
    not converted into each other.
    """
    require_non_negative_cents(deferred_cents, "deferred amount")
    if periodic_rate < 0:
        raise CalculationInputError("interest rate cannot be negative")
    if divisor_days <= 0:
        raise CalculationInputError("day-count divisor must be positive")
    return Decimal(deferred_cents) * periodic_rate / Decimal(divisor_days)


def post_interest_cents(unrounded_cents: Decimal, ceiling_cents: Decimal | None = None) -> int:
    """Half-up to a cent, then clamp to the ceiling if one is supplied."""
    posted = half_up_cents(unrounded_cents)
    if ceiling_cents is None:
        return posted
    return min(posted, floor_cents(ceiling_cents))
