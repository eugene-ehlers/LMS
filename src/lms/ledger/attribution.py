"""How much of a posted receipt counts toward its attributed due date.

LOCKED_DECISIONS §6. The receipt counts only toward that date. A section 126
part that reduced a charge or principal slice already due on an earlier date
does not count toward the later date. That part is not re-attributed. A
reduction of principal that is not yet due is the §13 prepayment, not that
section 126 part.
"""

from __future__ import annotations

from lms.ledger.models import LoanAccount, Transaction


def cents_toward_attributed_due(account: LoanAccount, transaction: Transaction) -> int:
    """Countable cents of one payment toward ``transaction.attributed_due_on``."""
    amount = transaction.amount_cents or 0
    due_on = transaction.attributed_due_on
    if due_on is None or amount <= 0:
        return amount
    charges = {charge.charge_id: charge.due_on for charge in account.charges}
    slices = {slice_.sequence: slice_.due_on for slice_ in account.slices}
    earlier = 0
    for effect in transaction.effects:
        target = None
        if effect.op == "decrease_charge" and effect.charge_id is not None:
            target = charges.get(effect.charge_id)
        elif effect.op == "decrease_slice" and effect.sequence is not None:
            target = slices.get(effect.sequence)
        if target is not None and target < due_on and target <= transaction.value_date:
            earlier += effect.cents
    return amount - earlier
