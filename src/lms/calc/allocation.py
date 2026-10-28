"""Section 126 allocation of amounts that are already due or unpaid.

LOCKED_DECISIONS §8. Unbilled interest is not allocatable. When several fee
buckets are already due, the order is collection costs, default administration,
credit insurance, service fee, initiation fee, and earliest due date inside
each bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from lms.calc.models import Charge, PrepaymentChoice, PrincipalSlice, State
from lms.calc.money import RuleError

# Within a fee bucket the earliest due date is paid first (§8).
FEE_RANK = {
    "collection": 0,
    "default_admin": 1,
    "insurance": 2,
    "service": 3,
    "initiation": 4,
}


@dataclass(frozen=True)
class Allocation:
    interest_cents: int
    fee_cents: int
    principal_cents: int
    suspense_cents: int
    state: State


def _replace_charge(charges: tuple[Charge, ...], updated: Charge) -> tuple[Charge, ...]:
    return tuple(updated if charge.charge_id == updated.charge_id else charge for charge in charges)


def _with_remaining(charge: Charge, remaining_cents: int) -> Charge:
    return Charge(
        charge.charge_id,
        charge.kind,
        charge.levied_on,
        charge.due_on,
        charge.ex_vat_cents,
        charge.vat_cents,
        charge.amount_cents,
        remaining_cents,
        charge.duplum_episode,
        charge.sequence,
    )


def allocate_payment(
    state: State,
    cents: int,
    *,
    as_of: date,
    prepayment: PrepaymentChoice | None = None,
    apply_prepayment: bool = True,
    settle: bool = False,
) -> Allocation:
    """Apply ``cents`` to amounts that are already due or unpaid.

    Principal with a due date after ``as_of`` is not due. Paying it is the
    §13 prepayment choice. That choice fails closed when it is unset.
    ``apply_prepayment=False`` leaves that surplus unapplied, so a morning
    default check can see the receipt without choosing a prepayment rule.
    ``settle=True`` pays every remaining principal slice. That is section 125,
    not a prepayment.
    """
    if cents < 0:
        raise RuleError("payment", "Cannot allocate a negative amount.")
    remaining = cents
    interest_taken = 0
    fee_taken = 0
    principal_taken = 0
    charges = state.charges

    interest = sorted(
        (c for c in charges if c.kind == "interest" and c.remaining_cents > 0),
        key=lambda c: (c.due_on, c.sequence),
    )
    for charge in interest:
        if remaining == 0:
            break
        take = min(charge.remaining_cents, remaining)
        charges = _replace_charge(charges, _with_remaining(charge, charge.remaining_cents - take))
        remaining -= take
        interest_taken += take

    fees = sorted(
        (c for c in charges if c.kind != "interest" and c.remaining_cents > 0),
        key=lambda c: (FEE_RANK.get(c.kind, 99), c.due_on, c.sequence),
    )
    for charge in fees:
        if remaining == 0:
            break
        take = min(charge.remaining_cents, remaining)
        charges = _replace_charge(charges, _with_remaining(charge, charge.remaining_cents - take))
        remaining -= take
        fee_taken += take

    slices = list(sorted(state.principal_slices, key=lambda s: (s.due_on, s.sequence)))
    due_indexes = [
        index
        for index, slice_ in enumerate(slices)
        if slice_.remaining_cents > 0 and (settle or slice_.due_on <= as_of)
    ]
    for index in due_indexes:
        if remaining == 0:
            break
        take = min(slices[index].remaining_cents, remaining)
        slices[index] = _reduce_slice(slices[index], take)
        remaining -= take
        principal_taken += take

    future = [
        index
        for index, slice_ in enumerate(slices)
        if slice_.remaining_cents > 0 and not settle and slice_.due_on > as_of
    ]
    unapplied = 0
    if remaining and future:
        if not apply_prepayment:
            unapplied = remaining
            remaining = 0
        elif prepayment is None:
            raise RuleError(
                "prepayment-choice-unset",
                "A payment would reduce principal that is not yet due, and the "
                "prepayment choice is unset. LOCKED_DECISIONS §13 and §19 fail closed.",
            )
        else:
            order = (
                list(reversed(future))
                if prepayment == PrepaymentChoice.SHORTEN_TERM
                else list(future)
            )
            for index in order:
                if remaining == 0:
                    break
                take = min(slices[index].remaining_cents, remaining)
                slices[index] = _reduce_slice(slices[index], take)
                remaining -= take
                principal_taken += take

    new_state = replace(
        state,
        principal_slices=tuple(slices),
        charges=charges,
        suspense_cents=state.suspense_cents + remaining,
    )
    return Allocation(
        interest_taken,
        fee_taken,
        principal_taken,
        remaining + unapplied,
        new_state,
    )


def _reduce_slice(slice_: PrincipalSlice, take: int) -> PrincipalSlice:
    return PrincipalSlice(
        slice_.due_on,
        slice_.amount_cents,
        slice_.remaining_cents - take,
        slice_.sequence,
    )
