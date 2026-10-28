"""Rand amounts as integer cents, rounded half-up away from zero."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
# Daily interest is kept at 10 decimal rands and rounded to cents only when billed.
INTEREST_QUANTUM = Decimal("0.0000000001")


class RuleError(Exception):
    """A calculation input breaks a locked rule. ``code`` is stable for callers."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def to_cents(rands: Decimal) -> int:
    """Round a rand amount to integer cents, half-up."""
    if rands.is_nan() or rands.is_infinite():
        raise RuleError("money", f"Cannot round {rands} to cents.")
    quantized = rands.quantize(CENT, rounding=ROUND_HALF_UP)
    return int(quantized * 100)


def cents_to_rands(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def quantize_interest(rands: Decimal) -> Decimal:
    return rands.quantize(INTEREST_QUANTUM, rounding=ROUND_HALF_UP)


def split_inclusive(total_cents: int, vat_rate: Decimal) -> tuple[int, int]:
    """Split a VAT-inclusive total so ex-VAT + VAT equals ``total_cents`` exactly."""
    if total_cents < 0:
        raise RuleError("money", "Cannot split a negative total.")
    if vat_rate < 0:
        raise RuleError("money", "VAT rate cannot be negative.")
    if total_cents == 0 or vat_rate == 0:
        return total_cents, 0
    ex_vat = to_cents(cents_to_rands(total_cents) / (Decimal(1) + vat_rate))
    # Half-up extraction can theoretically exceed the total by a cent. Pull it back.
    if ex_vat > total_cents:
        ex_vat = total_cents
    return ex_vat, total_cents - ex_vat


def add_vat(ex_vat_cents: int, vat_rate: Decimal) -> tuple[int, int, int]:
    """Return ``(ex_vat, vat, total)`` with VAT rounded half-up on the ex-VAT amount."""
    if ex_vat_cents < 0:
        raise RuleError("money", "Fee cannot be negative.")
    vat = to_cents(cents_to_rands(ex_vat_cents) * vat_rate)
    return ex_vat_cents, vat, ex_vat_cents + vat
