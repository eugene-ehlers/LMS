"""Section 126(3) payment allocation.

The Act requires three tiers, credited as of the date of receipt:

1. due or unpaid interest charges
2. due or unpaid fees or charges
3. the principal debt

It does not order one fee ahead of another. The adopted sub-order is
oldest payable date first, and pro rata (largest remainder) across fees
that became payable on the same day. That sub-order does not change how
much of the payment is applied to fees in total.

"Due or unpaid interest" for an ordinary payment means interest the
agreement has already made payable. Regulation 40 adds interest at most
monthly, and section 103(3) forbids debiting a day's interest before the
end of that day. Current-month interest that has not reached its
capitalisation date is not in tier 1. Section 125 settlement is a
different calculation and does include interest up to the settlement date;
do not run this allocator for a settlement quote without first moving
that accrual into the payable interest bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.money import require_non_negative_cents


@dataclass(frozen=True, slots=True)
class PayableFee:
    code: str
    payable_on: date
    amount_cents: int


@dataclass(frozen=True, slots=True)
class FeeSlice:
    code: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class Allocation:
    interest_cents: int
    fees: tuple[FeeSlice, ...]
    principal_cents: int
    unapplied_cents: int

    @property
    def fee_total_cents(self) -> int:
        return sum(item.amount_cents for item in self.fees)


def allocate_payment(
    payment_cents: int,
    *,
    payable_interest_cents: int,
    fees: list[PayableFee],
    principal_cents: int,
) -> Allocation:
    payment = require_non_negative_cents(payment_cents, "payment")
    interest_due = require_non_negative_cents(payable_interest_cents, "interest")
    principal = require_non_negative_cents(principal_cents, "principal")
    for fee in fees:
        require_non_negative_cents(fee.amount_cents, fee.code)
    if len({fee.code for fee in fees}) != len(fees):
        raise CalculationInputError("fee codes in one payment must be unique")

    to_interest = min(interest_due, payment)
    remaining = payment - to_interest

    remaining_fees = [PayableFee(fee.code, fee.payable_on, fee.amount_cents) for fee in fees]
    slices: list[FeeSlice] = []
    dates = sorted({fee.payable_on for fee in remaining_fees})
    for payable_on in dates:
        if remaining == 0:
            break
        group = [fee for fee in remaining_fees if fee.payable_on == payable_on and fee.amount_cents > 0]
        group_total = sum(fee.amount_cents for fee in group)
        if group_total == 0:
            continue
        if remaining >= group_total:
            taken = {fee.code: fee.amount_cents for fee in group}
            remaining -= group_total
        else:
            taken = _largest_remainder(remaining, group)
            remaining = 0
        for fee in group:
            amount = taken[fee.code]
            if amount:
                slices.append(FeeSlice(fee.code, amount))

    to_principal = min(principal, remaining)
    remaining -= to_principal
    return Allocation(to_interest, tuple(slices), to_principal, remaining)


def _largest_remainder(remaining: int, group: list[PayableFee]) -> dict[str, int]:
    total = sum(fee.amount_cents for fee in group)
    if total <= 0:
        raise CalculationInputError("cannot pro-rate an empty fee group")
    raw = [(fee.code, Decimal(remaining) * Decimal(fee.amount_cents) / Decimal(total)) for fee in group]
    floors = {code: int(amount) for code, amount in raw}  # Decimal truncates toward zero via int()
    # int(Decimal) truncates toward zero. Positive values, so this is the floor.
    leftover = remaining - sum(floors.values())
    fractional = sorted(
        ((amount - floors[code], code) for code, amount in raw),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    for _fraction, code in fractional:
        if leftover == 0:
            break
        floors[code] += 1
        leftover -= 1
    if leftover != 0:
        raise CalculationInputError("fee pro-rata did not consume the payment")
    return floors
