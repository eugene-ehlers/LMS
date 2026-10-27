"""Regulation 40 interest. The interest base is unpaid cash principal unless a policy says otherwise."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from lms.calc.models import (
    SHORT_TERM_FIRST_MONTHLY,
    SHORT_TERM_SUBSEQUENT_MONTHLY,
    UNSECURED_MAX_MARGIN,
    Agreement,
    DayCount,
    Product,
    RepoRate,
    micro_cap,
)
from lms.calc.money import RuleError, quantize_interest


def micro_monthly_rate(advance_date: date, prior_inceptions: tuple[date, ...] = ()) -> Decimal:
    """Prescribed maximum monthly rate for a short-term transaction (reg 42 Table A, item 5)."""
    return micro_cap(advance_date, prior_inceptions)


def repo_on(day: date, repos: tuple[RepoRate, ...]) -> Decimal:
    if not repos:
        raise RuleError("repo", "A personal-loan calculation needs a repo schedule.")
    selected: Decimal | None = None
    for row in sorted(repos, key=lambda item: item.effective_from):
        if row.effective_from <= day:
            selected = row.annual_rate
        else:
            break
    if selected is None:
        raise RuleError("repo", f"No repo rate is effective on {day.isoformat()}.")
    return selected


def personal_annual_rate(day: date, margin: Decimal, repos: tuple[RepoRate, ...]) -> Decimal:
    """RR + margin, and never above RR + 21% (reg 42 Table A, item 3)."""
    if margin < 0 or margin > UNSECURED_MAX_MARGIN:
        raise RuleError("unsecured-margin", "Margin must be between 0 and 21 percentage points.")
    return repo_on(day, repos) + margin


def divisor_days(day: date, product: Product, day_count: DayCount) -> int:
    if product == Product.MICRO:
        if day_count == DayCount.FIXED:
            return 30
        return calendar.monthrange(day.year, day.month)[1]
    if product == Product.PERSONAL:
        if day_count == DayCount.FIXED:
            return 365
        return 366 if calendar.isleap(day.year) else 365
    raise RuleError("product", f"{product} does not accrue NCA interest.")


def periodic_rate(agreement: Agreement, day: date, repos: tuple[RepoRate, ...]) -> Decimal:
    """Contractual base rate, before any campaign discount."""
    if agreement.product == Product.MICRO:
        return agreement.monthly_rate
    if agreement.product == Product.PERSONAL:
        return personal_annual_rate(day, agreement.margin_annual, repos)
    raise RuleError("product", f"{agreement.product} does not accrue NCA interest.")


def campaign_terms(
    agreement: Agreement,
    day: date,
    repos: tuple[RepoRate, ...] = (),
    *,
    discount_active: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return ``(base_rate, stored_discount, effective_rate)``.

    The stored discount is always the campaign's y%, including after it has fallen
    away. The effective rate is base minus that discount while the campaign is on,
    and the base rate once it has fallen away. It is never negative and never above
    the contractual base. A discount larger than the base produces an effective 0%.
    """
    base = periodic_rate(agreement, day, repos)
    stored = agreement.campaign_interest_discount
    if stored < 0:
        raise RuleError("campaign", "Campaign interest discount cannot be negative.")
    applied = stored if discount_active else Decimal("0")
    effective = base - applied
    if effective < 0:
        effective = Decimal("0")
    if effective > base:
        raise RuleError(
            "campaign-rate",
            "Effective interest exceeds the contractual rate. Penalty interest may not do that.",
        )
    return base, stored, effective


def daily_interest_rands(
    base_cents: int,
    periodic_rate_value: Decimal,
    divisor: int,
) -> Decimal:
    """Reg 40(2): deferred amount × rate / number of days in the month or year.

    Returned in rands at 10 decimal places. The caller rounds to cents when the
    interest is debited, not on every day, so a full period of a constant balance
    lands on the exact rate aside from a final half-up of less than one cent.
    """
    if base_cents < 0:
        raise RuleError("interest", "Interest base cannot be negative.")
    if divisor <= 0:
        raise RuleError("interest", "Day-count divisor must be positive.")
    if periodic_rate_value < 0:
        raise RuleError("interest", "Interest rate cannot be negative.")
    if base_cents == 0 or periodic_rate_value == 0:
        return Decimal("0")
    raw = (Decimal(base_cents) / Decimal(100)) * periodic_rate_value / Decimal(divisor)
    return quantize_interest(raw)


def interest_for_dates(
    *,
    base_cents: int,
    agreement: Agreement,
    start: date,
    end: date,
    repos: tuple[RepoRate, ...] = (),
    day_count: DayCount = DayCount.ACTUAL,
) -> Decimal:
    """Exact (10 dp) interest from ``start`` through ``end`` inclusive on a constant base."""
    if end < start:
        raise RuleError("interest", "Interest end date precedes the start date.")
    total = Decimal("0")
    day = start
    while day <= end:
        total += daily_interest_rands(
            base_cents,
            periodic_rate(agreement, day, repos),
            divisor_days(day, agreement.product, day_count),
        )
        day = date.fromordinal(day.toordinal() + 1)
    return total


# Re-export the statutory constants used by tests and the rules narrative.
assert SHORT_TERM_FIRST_MONTHLY == Decimal("0.05")
assert SHORT_TERM_SUBSEQUENT_MONTHLY == Decimal("0.03")
