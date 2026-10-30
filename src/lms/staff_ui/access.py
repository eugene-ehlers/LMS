"""Session answers for the collection-campaign access port.

The collection-campaign route asks this port whether Enigma allows
``lms.collection_campaign.write``. The port does not store roles.
"""

from __future__ import annotations

from lms.servicing.errors import ServicingError


class SessionAccess:
    """The Enigma answer for the staff member who is using the screen.

    ``current`` is set by the screen for the duration of one route call.
    """

    def __init__(self) -> None:
        self.current = None

    def check(self, organisation_id: str, person_id: str, mandate: str):
        session = self.current
        if session is None or not organisation_id or not person_id or not mandate:
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: an Enigma check without an organisation, person, or mandate is ambiguous.",
                status=503,
            )
        if session.enigma_status == "timeout":
            raise ServicingError(
                "enigma-timeout",
                "LOCKED_DECISIONS §15: Enigma timed out. The call fails closed.",
                status=503,
            )
        if session.enigma_status == "suspended":
            raise ServicingError(
                "enigma-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The call fails closed.",
                status=403,
            )
        if session.enigma_status != "active":
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma did not return a clear active enrolment.",
                status=503,
            )
        if person_id != session.person_id or organisation_id != session.organisation_id:
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: the command actor does not match the Enigma session.",
                status=503,
            )
        if mandate not in session.roles:
            raise ServicingError(
                "mandate-denied",
                f"The Enigma enrolment does not include {mandate}.",
                status=403,
            )
        return None
