"""Port protocols. The HTTP adapter behind these is unbound until Enigma's contract is readable."""

from __future__ import annotations

from typing import Protocol

from lms.enigma.errors import WireUnbound
from lms.enigma.models import (
    Enrolment,
    IamCallerProof,
    LiveIdentity,
    MandateDecision,
    MandateQuery,
    Membership,
    OrganisationContext,
    SessionView,
)


class EnigmaPort(Protocol):
    def introspect(self, session_ref: str, *, request_id: str) -> SessionView:
        """session.introspect"""

    def organisation_context(
        self, session_ref: str, organisation_id: str, *, request_id: str
    ) -> OrganisationContext:
        """organisation.context"""

    def validate_membership(
        self, session_ref: str, person_id: str, organisation_id: str, *, request_id: str
    ) -> Membership:
        """membership.validate. ``roles`` is Enigma's answer. LMS does not keep a staff list."""

    def lookup_mandate(self, query: MandateQuery, *, request_id: str) -> MandateDecision:
        """mandate.lookup. Allow or deny for this action. Rand ceilings are applied by LMS afterwards."""

    def check_enrolment(
        self, session_ref: str, organisation_id: str, product_code: str, *, request_id: str
    ) -> Enrolment:
        """enrolment.check"""


class PersonDirectory(Protocol):
    def read_live_identity(self, person_id: str, *, request_id: str) -> LiveIdentity:
        """Booking fields and communication preferences from the current Enigma person."""


class MachineIdentityPort(Protocol):
    def exchange(self, proof: IamCallerProof, *, request_id: str) -> str:
        """Verify the IAM caller with AWS and return an Enigma session reference for that machine member."""


class UnboundEnigmaPort:
    """Placeholder so a caller cannot accidentally treat sketched paths as a live API."""

    def introspect(self, session_ref: str, *, request_id: str) -> SessionView:
        raise WireUnbound("session.introspect wire is unbound")

    def organisation_context(
        self, session_ref: str, organisation_id: str, *, request_id: str
    ) -> OrganisationContext:
        raise WireUnbound("organisation.context wire is unbound")

    def validate_membership(
        self, session_ref: str, person_id: str, organisation_id: str, *, request_id: str
    ) -> Membership:
        raise WireUnbound("membership.validate wire is unbound")

    def lookup_mandate(self, query: MandateQuery, *, request_id: str) -> MandateDecision:
        raise WireUnbound("mandate.lookup wire is unbound")

    def check_enrolment(
        self, session_ref: str, organisation_id: str, product_code: str, *, request_id: str
    ) -> Enrolment:
        raise WireUnbound("enrolment.check wire is unbound")
