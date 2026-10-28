"""Errors for port contracts and for Enigma fail-closed results."""

from __future__ import annotations

from enum import StrEnum


class ContractError(ValueError):
    """The payload does not match the port contract.

    This is not a credit decision, a debit-order result, or an Enigma status.
    """


class EnigmaFailureReason(StrEnum):
    """Why an Enigma call returned nothing the LMS can act on."""

    TIMEOUT = "timeout"
    AMBIGUOUS_STATUS = "ambiguous_status"
    SUSPENDED_ENROLMENT = "suspended_enrolment"
    UNKNOWN_SESSION = "unknown_session"
    UNKNOWN_PERSON = "unknown_person"
    UNKNOWN_ORGANISATION = "unknown_organisation"
    NOT_ENROLLED = "not_enrolled"


class EnigmaFailClosed(Exception):
    """Enigma did not return a usable result. The LMS must not continue."""

    def __init__(self, operation: str, reason: EnigmaFailureReason) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(f"Enigma {operation} failed closed: {reason.value}")
