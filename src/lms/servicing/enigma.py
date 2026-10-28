"""Enigma boundary. This is a stub. It does not implement identity.

LOCKED_DECISIONS §15: fail closed on timeout, ambiguous status, or a
suspended enrolment. The LMS stores only the opaque ids plus the name,
identity number, and service address frozen at booking (§16).
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.servicing.errors import ServicingError


@dataclass(frozen=True)
class EnigmaIdentity:
    full_name: str
    id_number: str
    service_address: str
    enrolment_id: str


class EnigmaStub:
    """Returns a clear success or a clear failure. It has no session logic."""

    def __init__(self) -> None:
        self.mode = "active"
        self.full_name = "Ada Borrower"
        self.id_number = "8001015800085"
        self.service_address = "1 Main Road, Cape Town"
        self.enrolment_id = "enr-1"

    def check(self, organisation_id: str, person_id: str, mandate: str) -> EnigmaIdentity:
        if not organisation_id or not person_id or not mandate:
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: an Enigma check without an organisation, person, or mandate is ambiguous.",
            )
        if self.mode == "timeout":
            raise ServicingError(
                "enigma-timeout",
                "LOCKED_DECISIONS §15: Enigma timed out. The call fails closed.",
                status=503,
            )
        if self.mode == "ambiguous":
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma status is ambiguous. The call fails closed.",
            )
        if self.mode == "suspended":
            raise ServicingError(
                "enigma-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The call fails closed.",
            )
        if self.mode != "active":
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma did not return a clear active enrolment.",
            )
        if not self.full_name.strip() or not self.id_number.strip() or not self.service_address.strip():
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §16: name, identity number, and service address are required to freeze. A blank field is not frozen.",
            )
        return EnigmaIdentity(
            self.full_name,
            self.id_number,
            self.service_address,
            self.enrolment_id,
        )
