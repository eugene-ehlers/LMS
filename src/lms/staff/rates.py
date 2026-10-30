"""Campaign net rate and fee discount, by calling the existing interfaces.

``lms_config.locked.campaign_rate`` is the configuration interface. It
returns base minus discount, and it refuses a discount above the base.
Decision 3 allows that discount and floors the net at 0 %. This module
does not accrue, and it does not apply a statutory cap.

``lms.calc.fees.apply_ex_vat_discount`` caps a fee discount at R0. A
negative fee or a negative discount is refused before that call.
"""

from __future__ import annotations

from decimal import Decimal

from lms.calc.fees import apply_ex_vat_discount
from lms_config.exceptions import CalculationInputError
from lms_config.locked import campaign_rate
from lms_config.money import require_non_negative_cents


def integer_cents(cents: int, label: str) -> int:
    """Money is integer cents. A boolean is not an amount."""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise CalculationInputError(f"{label} must be integer cents")
    return require_non_negative_cents(cents, label)


def net_rate(base_rate: Decimal, discount_rate: Decimal) -> Decimal:
    """Decision 3. The stored net is base less discount, floored at 0 %."""
    if base_rate < 0 or discount_rate < 0:
        raise CalculationInputError("rates cannot be negative")
    if discount_rate > base_rate:
        try:
            net = campaign_rate(base_rate, discount_rate)
        except CalculationInputError:
            return Decimal(0)
        if net < 0:
            return Decimal(0)
        return net
    return campaign_rate(base_rate, discount_rate)


def fee_after_discount(
    ex_vat_cents: int,
    vat_rate: Decimal,
    discount_cents: int,
) -> tuple[int, int, int]:
    """Ex-VAT, VAT, and total after a campaign fee discount. All three are cents.

    A negative input is refused. ``apply_ex_vat_discount`` returns R0 when
    the discount would otherwise drive the fee below zero.
    """
    integer_cents(ex_vat_cents, "fee")
    integer_cents(discount_cents, "fee discount")
    if vat_rate < 0:
        raise CalculationInputError("VAT rate cannot be negative")
    return apply_ex_vat_discount(ex_vat_cents, vat_rate, discount_cents)
