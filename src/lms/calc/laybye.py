"""Zero-cost lay-by. CPA s 62 for a goods lay-by; s 124 for a security hold on a loan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lms.calc.models import LAYBYE_MAX_PENALTY_RATE
from lms.calc.money import RuleError, cents_to_rands, to_cents


@dataclass(frozen=True)
class LaybyeCancellation:
    penalty_cents: int
    refund_cents: int
    reason_code: str


def cancel_laybye(
    *,
    purchase_price_cents: int,
    paid_cents: int,
    penalty_disclosed: bool,
    agreed_penalty_rate: Decimal = LAYBYE_MAX_PENALTY_RATE,
    cause: str,
) -> LaybyeCancellation:
    """CPA s 62(4)-(6) and regulation 34.

    ``cause`` is ``consumer`` (cancellation or failure to complete), ``death``,
    or ``hospitalisation``. The penalty is zero unless it was disclosed before
    the agreement and the cause is an ordinary consumer cancellation.
    The penalty may not exceed 1% of the full purchase price, and cannot exceed
    what the consumer has paid.
    """
    if purchase_price_cents <= 0:
        raise RuleError("laybye", "Purchase price must be positive.")
    if paid_cents < 0 or paid_cents > purchase_price_cents:
        raise RuleError("laybye", "Paid amount must be between zero and the purchase price.")
    if cause not in ("consumer", "death", "hospitalisation"):
        raise RuleError("laybye", f"Unknown lay-by cancellation cause {cause}.")
    if agreed_penalty_rate < 0:
        raise RuleError("laybye", "Penalty rate cannot be negative.")
    if cause != "consumer" or not penalty_disclosed:
        return LaybyeCancellation(0, paid_cents, "no-penalty")
    rate = min(agreed_penalty_rate, LAYBYE_MAX_PENALTY_RATE)
    penalty = min(to_cents(cents_to_rands(purchase_price_cents) * rate), paid_cents)
    return LaybyeCancellation(penalty, paid_cents - penalty, "cpa-reg-34")


def guard_s124(
    *,
    mandate_id: str,
    authorised_cents: int,
    requested_cents: int,
    on: date,
    authorised_from: date,
    authorised_to: date | None,
) -> int:
    """Refuse a security application the servicing layer cannot tie to a s 124 authorisation.

    Enigma stores the mandate. This function does not interpret mandate text; the
    caller passes the amount and dates the mandate specifically authorises.
    """
    if not mandate_id:
        raise RuleError(
            "s124-mandate-missing",
            "Applying a lay-by hold to a loan needs a s 124 authorisation id from Enigma.",
        )
    if requested_cents <= 0:
        raise RuleError("s124-amount", "Security application must be positive.")
    if requested_cents > authorised_cents:
        raise RuleError(
            "s124-amount",
            "Requested application exceeds the amount specifically set out in the authorisation.",
        )
    if on < authorised_from or (authorised_to is not None and on > authorised_to):
        raise RuleError("s124-date", "Application date is outside the dates set out in the authorisation.")
    return requested_cents
