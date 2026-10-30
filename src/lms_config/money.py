"""Rand amounts are integer cents. Rates are Decimal fractions (0.05 = 5%)."""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from lms_config.exceptions import CalculationInputError


def require_non_negative_cents(cents: int, label: str) -> int:
    if not isinstance(cents, int):
        raise CalculationInputError(f"{label} must be integer cents, got {type(cents).__name__}")
    if cents < 0:
        raise CalculationInputError(f"{label} cannot be negative")
    return cents


def floor_cents(amount: Decimal) -> int:
    """Largest whole cent that does not exceed ``amount``.

    A prescribed maximum is a ceiling. Half-up rounding can put the
    consumer one cent over that ceiling, so caps round down.
    """
    if amount < 0:
        raise CalculationInputError("cannot floor a negative cap")
    return int(amount.to_integral_value(rounding=ROUND_DOWN))


def half_up_cents(amount_in_cents: Decimal) -> int:
    """Nearest cent, halves away from zero.

    ``amount_in_cents`` is a Decimal count of cents. Used for contractual
    interest after the daily sum, and only where the result is then clamped
    to the statutory ceiling. Regulation 40(4) allows a 0.1% annual
    tolerance; a half-cent rounding sits inside it.
    """
    if amount_in_cents < 0:
        raise CalculationInputError("cannot round a negative charge")
    return int(amount_in_cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
