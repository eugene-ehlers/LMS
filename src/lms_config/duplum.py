"""Section 103(5): charges that accrue during a default.

The section says the amounts in section 101(1)(b) to (g) that accrue while
the consumer is in default may not, in aggregate, exceed the unpaid balance
of the principal debt at the time the default occurs.

Locked decision 7 treats the ceiling as a cumulative accrual cap for that
default episode. A payment does not reopen it. The episode ends when the
default is purged (no payable amount remains overdue); a later default
snapshots a new principal balance and a new cap. The base is unpaid
principal at the first default and includes initiation capitalised before
that default. ``duplum_base_cents`` is how that principal is assembled.

The floating alternative — unpaid charges of those kinds may not exceed the
snapshot, so a payment of charges creates room to accrue more — is
implemented only so the two readings can be compared. It is not the locked
reading.

Post-default interest and fees stay in their own sub-ledgers for section
103(5) and section 126, even if a statement shows them as capitalised.
Pre-default capitalised initiation is principal, not a charge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from lms_config.exceptions import CalculationInputError
from lms_config.money import floor_cents, half_up_cents, require_non_negative_cents


CUMULATIVE = "cumulative"
FLOATING = "floating"


@dataclass(frozen=True, slots=True)
class DefaultLedger:
    principal_cents: int
    interest_cents: int
    fee_cents: int
    accrued_cents: int
    cap_cents: int

    @property
    def deferred_cents(self) -> int:
        """Regulation 40 interest base: principal plus capitalised interest and fees.

        Sub-ledgers are not merged. This sum is only the next month's base.
        """
        return self.principal_cents + self.interest_cents + self.fee_cents


@dataclass(frozen=True, slots=True)
class MonthPosting:
    interest_charged_cents: int
    fee_charged_cents: int
    interest_suppressed_cents: int
    fee_suppressed_cents: int
    ledger: DefaultLedger


def open_default(principal_cents: int) -> DefaultLedger:
    principal = require_non_negative_cents(principal_cents, "principal")
    return DefaultLedger(principal, 0, 0, 0, principal)


def room_cents(ledger: DefaultLedger, mode: str) -> int:
    if mode == CUMULATIVE:
        return ledger.cap_cents - ledger.accrued_cents
    if mode == FLOATING:
        return ledger.cap_cents - (ledger.interest_cents + ledger.fee_cents)
    raise CalculationInputError(f"unknown in-duplum mode {mode!r}")


def post_month(
    ledger: DefaultLedger,
    *,
    monthly_rate: Decimal,
    service_fee_cents: int,
    mode: str = CUMULATIVE,
) -> MonthPosting:
    """One calendar month of a short-term actual-days accrual.

    With a constant deferred amount through the month, regulation 40's
    actual-days divisor cancels and the month's interest is exactly
    ``deferred × monthly rate`` before rounding. The 30-day divisor does
    not cancel; do not use this helper for that convention.
    """
    if monthly_rate < 0:
        raise CalculationInputError("monthly rate cannot be negative")
    require_non_negative_cents(service_fee_cents, "service fee")
    raw_interest = half_up_cents(Decimal(ledger.deferred_cents) * monthly_rate)
    raw_fee = service_fee_cents
    available = max(0, room_cents(ledger, mode))
    interest = min(raw_interest, available)
    available -= interest
    fee = min(raw_fee, available)
    updated = replace(
        ledger,
        interest_cents=ledger.interest_cents + interest,
        fee_cents=ledger.fee_cents + fee,
        accrued_cents=ledger.accrued_cents + interest + fee,
    )
    return MonthPosting(
        interest_charged_cents=interest,
        fee_charged_cents=fee,
        interest_suppressed_cents=raw_interest - interest,
        fee_suppressed_cents=raw_fee - fee,
        ledger=updated,
    )


def apply_s126_payment(ledger: DefaultLedger, payment_cents: int) -> DefaultLedger:
    """Reduce interest, then fees, then principal. The accrual counter is unchanged."""
    remaining = require_non_negative_cents(payment_cents, "payment")
    to_interest = min(ledger.interest_cents, remaining)
    remaining -= to_interest
    to_fees = min(ledger.fee_cents, remaining)
    remaining -= to_fees
    to_principal = min(ledger.principal_cents, remaining)
    return replace(
        ledger,
        principal_cents=ledger.principal_cents - to_principal,
        interest_cents=ledger.interest_cents - to_interest,
        fee_cents=ledger.fee_cents - to_fees,
    )


def run_until_capped(
    principal_cents: int,
    *,
    monthly_rate: Decimal,
    service_fee_cents: int,
    mode: str,
    payment_after_month: int | None = None,
    payment_cents: int = 0,
    max_months: int = 48,
) -> tuple[DefaultLedger, int]:
    """Run month by month. Returns the ledger and the count of months posted.

    Stops once a month charges nothing, or after ``max_months``.
    ``payment_after_month`` applies one section 126 payment at the end of
    that month (1-based).
    """
    ledger = open_default(principal_cents)
    months = 0
    for index in range(1, max_months + 1):
        posting = post_month(
            ledger,
            monthly_rate=monthly_rate,
            service_fee_cents=service_fee_cents,
            mode=mode,
        )
        if posting.interest_charged_cents == 0 and posting.fee_charged_cents == 0:
            break
        ledger = posting.ledger
        months = index
        if payment_after_month == index:
            ledger = apply_s126_payment(ledger, payment_cents)
        if mode == CUMULATIVE and room_cents(ledger, mode) <= 0:
            break
    return ledger, months


def suppressed_cents(raw_cents: Decimal, cap_room_cents: int) -> int:
    if cap_room_cents < 0:
        raise CalculationInputError("cap room cannot be negative")
    return max(0, floor_cents(raw_cents) - cap_room_cents)
