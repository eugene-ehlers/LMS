"""Initiation, service, and lay-by penalty ceilings.

The gazetted initiation formula uses "the amount of the agreement", and the
2006 regulations say that amount is the amount deferred. Regulation 43(3)
caps the fee at 15% of the principal debt. When the fee is itself deferred,
both bases are circular. ``initiation_fee_cents`` implements each reading.
Day-1 charges the cash-advanced reading, which is less than or equal to the
grossed-up reading on every amount tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.money import floor_cents, half_up_cents, require_non_negative_cents
from lms_config.statute import (
    INITIATION_ABSOLUTE_CENTS,
    INITIATION_FLAT_CENTS,
    INITIATION_MARGINAL,
    INITIATION_PRINCIPAL_RATIO,
    INITIATION_THRESHOLD_CENTS,
    LAYBY_PENALTY_RATIO,
    SERVICE_FEE_MONTHLY_CENTS,
)


@dataclass(frozen=True, slots=True)
class InitiationCap:
    flat_cents: int = INITIATION_FLAT_CENTS
    threshold_cents: int = INITIATION_THRESHOLD_CENTS
    marginal_rate: Decimal = INITIATION_MARGINAL
    absolute_cents: int = INITIATION_ABSOLUTE_CENTS
    principal_ratio: Decimal = INITIATION_PRINCIPAL_RATIO


DEFAULT_INITIATION_CAP = InitiationCap()


def table_b_cents(amount_cents: int, cap: InitiationCap = DEFAULT_INITIATION_CAP) -> Decimal:
    """Regulation 42 Table B for an amount already expressed in cents.

    Returns cents as a Decimal. It is not yet combined with regulation 43(3)
    and is not yet floored.
    """
    require_non_negative_cents(amount_cents, "amount")
    extra = max(Decimal(0), Decimal(amount_cents - cap.threshold_cents))
    raw = Decimal(cap.flat_cents) + extra * cap.marginal_rate
    return min(Decimal(cap.absolute_cents), raw)


def _within(fee_cents: int, limit: Decimal) -> bool:
    return Decimal(fee_cents) <= limit


def initiation_fee_cents(
    cash_advanced_cents: int,
    *,
    base: str,
    cap: InitiationCap = DEFAULT_INITIATION_CAP,
) -> int:
    """Maximum initiation fee in cents.

    ``base``:
    - ``cash_advanced``: Table B and the 15% test both use the cash
      advanced, before the fee. Day-1 adopted reading. Upfront fees are
      this case with no circularity, because the fee is not deferred.
    - ``grossed_principal``: the fee is inside the deferred amount and
      inside the principal debt. The result is the largest whole-cent fee
      that satisfies Table B and regulation 43(3) on that grossed amount.
    """
    require_non_negative_cents(cash_advanced_cents, "cash advanced")
    if base == "cash_advanced":
        table = table_b_cents(cash_advanced_cents, cap)
        ratio = Decimal(cash_advanced_cents) * cap.principal_ratio
        return floor_cents(min(table, ratio, Decimal(cap.absolute_cents)))
    if base == "grossed_principal":
        return _grossed_fee(cash_advanced_cents, cap)
    raise CalculationInputError(f"unknown initiation base {base!r}")


def _grossed_fee(cash_advanced_cents: int, cap: InitiationCap) -> int:
    lo = 0
    hi = cap.absolute_cents
    best = 0
    while lo <= hi:
        fee = (lo + hi) // 2
        principal = cash_advanced_cents + fee
        table_ok = _within(fee, table_b_cents(principal, cap))
        ratio_ok = _within(fee, Decimal(principal) * cap.principal_ratio)
        if table_ok and ratio_ok:
            best = fee
            lo = fee + 1
        else:
            hi = fee - 1
    return best


def opening_service_fee_cents(
    monthly_cents: int,
    disbursed_on: date,
    first_due_on: date,
    *,
    monthly_cap_cents: int = SERVICE_FEE_MONTHLY_CENTS,
) -> int:
    """Decision 9. Pro-rata only in the opening month.

    The locked fraction is the inclusive calendar days from the disbursement
    date to the day before the first due date, divided by the actual days
    in the disbursement month. Date subtraction is that count. The result
    is clamped to one monthly fee. Later months, including the settlement
    month, use ``subsequent_service_fee_cents``.
    """
    require_non_negative_cents(monthly_cents, "service fee")
    if monthly_cents > monthly_cap_cents:
        raise CalculationInputError(
            f"service fee {monthly_cents} cents exceeds the monthly cap {monthly_cap_cents}"
        )
    if first_due_on <= disbursed_on:
        raise CalculationInputError(
            "first payment due must be after the disbursement value date"
        )
    covered = (first_due_on - disbursed_on).days
    raw = Decimal(monthly_cents) * Decimal(covered) / Decimal(_days_in_month(disbursed_on))
    return min(floor_cents(raw), monthly_cents)


def subsequent_service_fee_cents(
    monthly_cents: int,
    *,
    monthly_cap_cents: int = SERVICE_FEE_MONTHLY_CENTS,
) -> int:
    """Full monthly service fee, including the settlement month.

    Locked decision 9. Still not above the contractual fee or the R60 cap.
    """
    require_non_negative_cents(monthly_cents, "service fee")
    if monthly_cents > monthly_cap_cents:
        raise CalculationInputError(
            f"service fee {monthly_cents} cents exceeds the monthly cap {monthly_cap_cents}"
        )
    return monthly_cents


def inception_service_fee_cents(
    monthly_cents: int,
    concluded_on: date,
    *,
    include_conclusion_day: bool,
    monthly_cap_cents: int = SERVICE_FEE_MONTHLY_CENTS,
) -> int:
    """Superseded calendar-month reading of regulation 44(4).

    Locked decision 9 replaced this. The charge is
    ``opening_service_fee_cents``. This function remains so the one-day gap
    between including and excluding the conclusion day can still be measured.
    """
    require_non_negative_cents(monthly_cents, "service fee")
    if monthly_cents > monthly_cap_cents:
        raise CalculationInputError(
            f"service fee {monthly_cents} cents exceeds the monthly cap {monthly_cap_cents}"
        )
    days_in_month = _days_in_month(concluded_on)
    if include_conclusion_day:
        covered = days_in_month - concluded_on.day + 1
    else:
        covered = days_in_month - concluded_on.day
    raw = Decimal(monthly_cents) * Decimal(covered) / Decimal(days_in_month)
    return min(floor_cents(raw), monthly_cents)


def vat_on_top_cents(fee_cents: int, vat_rate: Decimal = Decimal("0.15")) -> int:
    """What the consumer pays if the gazetted figure is treated as VAT-exclusive.

    The regulations do not say this. The adopted reading does not call this
    function when charging. It exists to measure the gap.
    """
    require_non_negative_cents(fee_cents, "fee")
    return half_up_cents(Decimal(fee_cents) * (Decimal(1) + vat_rate))


def split_vat_inclusive(total_cents: int, vat_rate: Decimal = Decimal("0.15")) -> tuple[int, int]:
    """Split a VAT-inclusive total so the two parts add back to it.

    Exclusive consideration is the nearest cent of ``total / (1 + rate)``.
    The VAT cents are the remainder, so the consumer still pays exactly the
    gazetted total. The two parts can disagree with ``exclusive × rate`` by
    one cent; that is the split, not a higher charge.
    """
    require_non_negative_cents(total_cents, "total")
    exclusive = half_up_cents(Decimal(total_cents) / (Decimal(1) + vat_rate))
    if exclusive > total_cents:
        exclusive = total_cents
    return exclusive, total_cents - exclusive


def layby_penalty_cents(
    purchase_price_cents: int,
    *,
    disclosed_before_agreement: bool,
    death_or_hospitalisation: bool,
    ratio: Decimal = LAYBY_PENALTY_RATIO,
) -> int:
    """CPA section 62(4)-(5) and regulation 34.

    The penalty is nil if it was not disclosed before the agreement, or if
    the consumer died or was hospitalised. Otherwise it may not exceed
    ``ratio`` of the full purchase price. This is not an NCA charge and
    must not be applied to a cash security deposit.
    """
    require_non_negative_cents(purchase_price_cents, "purchase price")
    if death_or_hospitalisation or not disclosed_before_agreement:
        return 0
    return floor_cents(Decimal(purchase_price_cents) * ratio)


def _days_in_month(day: date) -> int:
    if day.month == 12:
        next_month = date(day.year + 1, 1, 1)
    else:
        next_month = date(day.year, day.month + 1, 1)
    return (next_month - date(day.year, day.month, 1)).days
