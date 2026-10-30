"""Initiation and service fees. Caps are the prescribed maxima; VAT follows the policy basis."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from lms.calc.models import (
    INITIATION_FLAT_CENTS,
    INITIATION_PERCENT,
    INITIATION_PRINCIPAL_PERCENT,
    INITIATION_RAND_CAP_CENTS,
    INITIATION_THRESHOLD_CENTS,
    SERVICE_FEE_MONTHLY_CAP_CENTS,
    FeeCapBasis,
    VatRate,
)
from lms.calc.money import RuleError, add_vat, cents_to_rands, split_inclusive, to_cents


def initiation_cap_ex_vat_cents(principal_cents: int) -> int:
    """Lesser of Table B and 15% of the principal debt (regs 42(2) and 43(3)).

    The principal used here is the cash advanced. It excludes the initiation fee,
    so the 15% test is not circular. Table B's "amount of the agreement" is the
    same figure: reg 42 says that amount is the amount deferred, and for a
    short-term or unsecured cash loan the deferred cash is the amount disbursed.
    """
    if principal_cents <= 0:
        raise RuleError("initiation", "Initiation cap needs a positive principal.")
    principal = cents_to_rands(principal_cents)
    excess = max(Decimal(0), principal - cents_to_rands(INITIATION_THRESHOLD_CENTS))
    table = cents_to_rands(INITIATION_FLAT_CENTS) + INITIATION_PERCENT * excess
    table_cents = min(to_cents(table), INITIATION_RAND_CAP_CENTS)
    fifteen_cents = to_cents(principal * INITIATION_PRINCIPAL_PERCENT)
    return min(table_cents, fifteen_cents)


def vat_on(day: date, vat_rates: tuple[VatRate, ...]) -> Decimal:
    if not vat_rates:
        raise RuleError("vat", "A VAT schedule is required.")
    selected: Decimal | None = None
    for row in sorted(vat_rates, key=lambda item: item.effective_from):
        if row.effective_from <= day:
            selected = row.rate
        else:
            break
    if selected is None:
        raise RuleError("vat", f"No VAT rate is effective on {day.isoformat()}.")
    return selected


def price_fee(
    cap_cents: int,
    vat_rate: Decimal,
    basis: FeeCapBasis,
    *,
    fraction: Decimal = Decimal(1),
    vat_registered: bool = True,
) -> tuple[int, int, int]:
    """Price a fee at ``fraction`` of its cap.

    Exclusive basis: the cap is ex-VAT, then VAT is added and rounded half-up.
    Inclusive basis: the cap is the consumer total, and VAT is extracted from it.
    A non-vendor charges no VAT, and the exclusive cap is the amount payable.
    """
    if fraction < 0 or fraction > 1:
        raise RuleError("fee", "Fee fraction must be between 0 and 1.")
    rate = vat_rate if vat_registered else Decimal(0)
    if basis == FeeCapBasis.EXCLUSIVE:
        ex_vat = to_cents(cents_to_rands(cap_cents) * fraction)
        ex_vat = min(ex_vat, cap_cents)
        return add_vat(ex_vat, rate)
    total_cap = cap_cents
    total = to_cents(cents_to_rands(total_cap) * fraction)
    total = min(total, total_cap)
    ex_vat, vat = split_inclusive(total, rate)
    return ex_vat, vat, total


def initiation_fee(
    principal_cents: int,
    *,
    on: date,
    vat_rates: tuple[VatRate, ...],
    basis: FeeCapBasis,
    vat_registered: bool = True,
) -> tuple[int, int, int]:
    cap = initiation_cap_ex_vat_cents(principal_cents)
    rate = vat_on(on, vat_rates) if vat_registered else Decimal(0)
    return price_fee(cap, rate, basis, vat_registered=vat_registered)


def service_fee_cents(
    *,
    on: date,
    period_start: date,
    period_end: date,
    monthly_cap_cents: int = SERVICE_FEE_MONTHLY_CAP_CENTS,
    full_month: bool = False,
    vat_rates: tuple[VatRate, ...],
    basis: FeeCapBasis,
    vat_registered: bool = True,
) -> tuple[int, int, int]:
    """Service fee for one calendar month.

    ``period_start`` and ``period_end`` are inclusive civil dates and must fall in
    the same calendar month. Reg 44(4) pro-rates the commencement month by
    inclusive days over the actual days in that month. ``full_month`` charges the
    monthly cap (the terminal-month maximum).
    """
    if period_end < period_start:
        raise RuleError("service-fee", "Service-fee period is empty.")
    if (period_start.year, period_start.month) != (period_end.year, period_end.month):
        raise RuleError("service-fee", "Service fee is levied per calendar month.")
    if monthly_cap_cents > SERVICE_FEE_MONTHLY_CAP_CENTS:
        raise RuleError("service-fee-cap", "Monthly service fee exceeds R60.")
    days_in_month = calendar.monthrange(period_start.year, period_start.month)[1]
    inclusive = (period_end - period_start).days + 1
    if inclusive > days_in_month:
        raise RuleError("service-fee", "Service-fee period exceeds the calendar month.")
    fraction = Decimal(1) if full_month else Decimal(inclusive) / Decimal(days_in_month)
    rate = vat_on(on, vat_rates) if vat_registered else Decimal(0)
    return price_fee(
        monthly_cap_cents,
        rate,
        basis,
        fraction=fraction,
        vat_registered=vat_registered,
    )
