"""Port errors. The HTTP edge maps ``code`` and ``http_status`` and does not pass Enigma bodies through."""

from __future__ import annotations


class PortError(Exception):
    """Base class for a decision the LMS can explain without Enigma's payload."""

    code: str = "authority_unavailable"
    http_status: int = 503

    def __init__(self, message: str, *, enigma_request_id: str | None = None) -> None:
        super().__init__(message)
        self.enigma_request_id = enigma_request_id


class Reauthenticate(PortError):
    code = "reauthenticate"
    http_status = 401


class NotAMember(PortError):
    code = "not_a_member"
    http_status = 403


class OrganisationUnavailable(PortError):
    code = "organisation_unavailable"
    http_status = 403


class EnrolmentDenied(PortError):
    code = "enrolment_denied"
    http_status = 403


class MandateDenied(PortError):
    code = "mandate_denied"
    http_status = 403


class OrganisationContextStale(PortError):
    """Cookie generation does not match the server session. The loan is not read."""

    code = "organisation_context_stale"
    http_status = 409

    def __init__(
        self,
        message: str,
        *,
        organisation_id: str,
        organisation_generation: int,
        enigma_request_id: str | None = None,
    ) -> None:
        super().__init__(message, enigma_request_id=enigma_request_id)
        self.organisation_id = organisation_id
        self.organisation_generation = organisation_generation


class AuthorityUnavailable(PortError):
    """Timeout, HTTP 5xx, or a broken connection. The command is not committed."""

    code = "authority_unavailable"
    http_status = 503


class AmbiguousAuthority(PortError):
    """Sign-in, membership, role, enrolment, or ceiling is not a clear answer."""

    code = "authority_ambiguous"
    http_status = 503


class AttributesUnavailable(PortError):
    code = "attributes_unavailable"
    http_status = 409


class UnboundEnigmaPort(PortError):
    """Raised when a call has no HTTP path. The URL is not invented."""

    code = "unbound_enigma_port"
    http_status = 503


class TransportError(Exception):
    """Raised by a port adapter before the client maps it onto a PortError."""


class TransportTimeout(TransportError):
    pass


class TransportHTTPError(TransportError):
    def __init__(self, status: int) -> None:
        super().__init__(f"enigma http {status}")
        self.status = status
