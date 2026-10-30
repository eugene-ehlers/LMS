"""Integer-cent checks. These are contract checks, not credit rules."""

from __future__ import annotations


def require_cents(value: object, name: str) -> int:
    """Accept zero or a positive number of cents. Reject bools and floats."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer cents")
    if value < 0:
        raise ValueError(f"{name} must be zero or a positive number of cents")
    return value


def require_basis_points(value: object, name: str) -> int:
    """Accept the integer the decision engine supplied, including zero.

    A negative rate is refused. Decision 3 floors a net rate at 0 %.
    The wire unit is the open point D1. This check does not interpret the
    integer as a recalculated instalment.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be the integer the decision engine supplied")
    if value < 0:
        raise ValueError("contractual rate cannot be negative")
    return value


def require_term_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("term count must be a positive integer")
    return value


FREQUENCIES = (
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    "bi-annual",
    "annual",
)


def require_frequency(value: object) -> str:
    if not isinstance(value, str) or value not in FREQUENCIES:
        allowed = ", ".join(FREQUENCIES)
        raise ValueError(f"payment frequency must be one of {allowed}")
    return value


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{name} must be a non-empty string")
    return value
