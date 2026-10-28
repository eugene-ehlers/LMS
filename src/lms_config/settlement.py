"""Section 125 settlement amount, and the section 9 size test.

Section 125(2): the settlement amount is the unpaid principal, plus unpaid
interest and other fees and charges up to the settlement date, plus — only
for a large agreement — an early-termination charge.

No prescribed early-termination charge was found in the 2006 regulations or
in GN 1080. Section 125(2)(c)(i) then points at the sub-paragraph (ii)
formula: interest that would have been payable for three months, less any
notice given. What "would have been payable" assumes (outstanding balance
held constant, or the contractual instalments) is not stated. Day-1 product
templates keep principal below the large-agreement threshold so this charge
is not reached. ``early_termination_cents`` implements the constant-balance
reading only as a ceiling the engine can apply if a large agreement is ever
boarded, and it refuses to run for any other size.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.interest import daily_interest_cents
from lms_config.money import floor_cents, require_non_negative_cents
from lms_config.statute import AGREEMENT_HIGHER_CENTS, AGREEMENT_LOWER_CENTS


def agreement_size(principal_cents: int, *, lower_cents: int = AGREEMENT_LOWER_CENTS, higher_cents: int = AGREEMENT_HIGHER_CENTS) -> str:
    """Section 9 for a credit transaction that is not a pawn, mortgage, or guarantee.

    Small: principal at or below the lower section 7(1)(b) threshold.
    Large: principal at or above the higher threshold.
    Intermediate: strictly between them.
    """
    require_non_negative_cents(principal_cents, "principal")
    if principal_cents <= lower_cents:
        return "small"
    if principal_cents >= higher_cents:
        return "large"
    return "intermediate"


def settlement_cents(
    *,
    unpaid_principal_cents: int,
    unpaid_interest_cents: int,
    unpaid_fees_cents: int,
    early_termination_cents: int = 0,
    size: str,
) -> int:
    require_non_negative_cents(unpaid_principal_cents, "principal")
    require_non_negative_cents(unpaid_interest_cents, "interest")
    require_non_negative_cents(unpaid_fees_cents, "fees")
    require_non_negative_cents(early_termination_cents, "early termination")
    if size != "large" and early_termination_cents != 0:
        raise CalculationInputError(
            "section 125(2)(c) early-termination charge applies only to a large agreement"
        )
    if size not in {"small", "intermediate", "large"}:
        raise CalculationInputError(f"unknown agreement size {size!r}")
    return unpaid_principal_cents + unpaid_interest_cents + unpaid_fees_cents + early_termination_cents


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day. Used only to measure a three-month notice window.
    last = _last_day(year, month)
    return date(year, month, min(day.day, last))


def early_termination_ceiling_cents(
    *,
    unpaid_principal_cents: int,
    annual_rate: Decimal,
    settlement_on: date,
    notice_months: int,
    year_divisor: int,
    size: str,
) -> int:
    """Constant-balance reading of section 125(2)(c)(ii).

    Interest on the unpaid principal for the days from the settlement date
    to the date three months later, reduced by ``notice_months`` (0, 1, 2,
    or 3). Notice of three months or more yields zero. This is a ceiling
    under one reading, not a settled formula, and it is refused unless the
    agreement is large.
    """
    if size != "large":
        raise CalculationInputError(
            "refusing an early-termination charge on an agreement that is not large"
        )
    if notice_months < 0:
        raise CalculationInputError("notice cannot be negative")
    if notice_months >= 3:
        return 0
    require_non_negative_cents(unpaid_principal_cents, "principal")
    if annual_rate < 0:
        raise CalculationInputError("rate cannot be negative")
    window_end = add_months(settlement_on, 3 - notice_months)
    days = (window_end - settlement_on).days
    if days < 0:
        raise CalculationInputError("settlement window ran backwards")
    raw = daily_interest_cents(
        unpaid_principal_cents,
        periodic_rate=annual_rate,
        divisor_days=year_divisor,
    ) * Decimal(days)
    return floor_cents(raw)


def _last_day(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days
