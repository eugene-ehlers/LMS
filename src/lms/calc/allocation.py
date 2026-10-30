"""Section 126(3) allocation. Interest, then fees, then principal."""

from __future__ import annotations

from dataclasses import dataclass, replace

from lms.calc.models import Charge, PrincipalSlice, State
from lms.calc.money import RuleError

# Within the fee class the Act is silent. Same due date: this rank, then posting sequence.
# Interest is not in this table; the whole interest class is allocated first.
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


def allocate_payment(state: State, cents: int) -> Allocation:
    """Apply ``cents`` to a state whose payable charges are already billed.

    Unbilled interest is not payable (s 103(3) until it has been debited).
    Principal slices are reduced earliest due date first, which clears arrears
    before it shortens a future instalment.
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
        charges = _replace_charge(
            charges, _with_remaining(charge, charge.remaining_cents - take)
        )
        remaining -= take
        interest_taken += take

    fees = sorted(
        (
            c
            for c in charges
            if c.kind != "interest" and c.remaining_cents > 0
        ),
        key=lambda c: (c.due_on, FEE_RANK.get(c.kind, 99), c.sequence),
    )
    for charge in fees:
        if remaining == 0:
            break
        take = min(charge.remaining_cents, remaining)
        charges = _replace_charge(
            charges, _with_remaining(charge, charge.remaining_cents - take)
        )
        remaining -= take
        fee_taken += take

    slices = tuple(
        sorted(state.principal_slices, key=lambda s: (s.due_on, s.sequence))
    )
    updated_slices: list[PrincipalSlice] = []
    for slice_ in slices:
        if remaining == 0 or slice_.remaining_cents == 0:
            updated_slices.append(slice_)
            continue
        take = min(slice_.remaining_cents, remaining)
        updated_slices.append(
            PrincipalSlice(
                slice_.due_on,
                slice_.amount_cents,
                slice_.remaining_cents - take,
                slice_.sequence,
            )
        )
        remaining -= take
        principal_taken += take

    new_state = replace(
        state,
        principal_slices=tuple(updated_slices),
        charges=charges,
        suspense_cents=state.suspense_cents + remaining,
    )
    return Allocation(interest_taken, fee_taken, principal_taken, remaining, new_state)


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
