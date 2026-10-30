"""Shared checks for port payloads. These are contract checks, not credit rules."""

from __future__ import annotations

from lms.errors import ContractError


def require_cents(value: object, name: str) -> int:
    """Accept zero or a positive count of cents. Reject floats and booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{name} must be integer cents")
    if value < 0:
        raise ContractError(f"{name} must be zero or a positive number of cents")
    return value


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ContractError(f"{name} must be a non-empty string")
    return value


def require_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return require_text(value, name)


def require_positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{name} must be a positive integer")
    return value


def require_non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{name} must be zero or a positive integer")
    return value
