"""Enigma port: identity and access only.

The LMS stores opaque ``person_id`` and ``organisation_id``. It freezes name,
ID number and service address at booking and does not read them back from
Enigma onto a concluded agreement.

Fail closed on timeout, ambiguous status, or a clear suspended enrolment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from lms.errors import ContractError
from lms.validation import require_text


@dataclass(frozen=True)
class Session:
    """A signed-in person. Access still depends on enrolment and mandate."""

    person_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))


@dataclass(frozen=True)
class OrganisationContext:
    """What Enigma may say about an organisation.

    Company registration is used by Enigma. NCR number, trading name, address,
    telephone, payment-account details, brand, ceilings and campaigns are not
    on this object.
    """

    organisation_id: str
    company_registration_number: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "organisation_id", require_text(self.organisation_id, "organisation_id")
        )
        object.__setattr__(
            self,
            "company_registration_number",
            require_text(self.company_registration_number, "company_registration_number"),
        )


@dataclass(frozen=True)
class Membership:
    """Roles linking a person to an organisation. Empty roles are a clear answer."""

    person_id: str
    organisation_id: str
    roles: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))
        object.__setattr__(
            self, "organisation_id", require_text(self.organisation_id, "organisation_id")
        )
        if not isinstance(self.roles, tuple) or any(
            not isinstance(role, str) or role.strip() == "" for role in self.roles
        ):
            raise ContractError("roles must be a tuple of non-empty strings")


@dataclass(frozen=True)
class Enrolment:
    """A clear active enrolment. Suspended and ambiguous enrolments are not returned."""

    person_id: str
    organisation_id: str
    status: Literal["active"] = "active"

    def __post_init__(self) -> None:
        if self.status != "active":
            raise ContractError("only an active enrolment is returned")
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))
        object.__setattr__(
            self, "organisation_id", require_text(self.organisation_id, "organisation_id")
        )


@dataclass(frozen=True)
class Mandate:
    """Whether an active enrolment includes a role. A missing role is ``granted=False``."""

    person_id: str
    organisation_id: str
    role: str
    granted: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))
        object.__setattr__(
            self, "organisation_id", require_text(self.organisation_id, "organisation_id")
        )
        object.__setattr__(self, "role", require_text(self.role, "role"))
        if not isinstance(self.granted, bool):
            raise ContractError("granted must be a boolean")


@dataclass(frozen=True)
class EnigmaIdentity:
    """Consumer identity read at booking, before the LMS freezes it.

    Email and telephone are not included. The LMS does not store them.
    """

    person_id: str
    name: str
    id_number: str
    service_address: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(self, "id_number", require_text(self.id_number, "id_number"))
        object.__setattr__(
            self, "service_address", require_text(self.service_address, "service_address")
        )


@dataclass(frozen=True)
class FrozenBookingIdentity:
    """The copy stored on the agreement. Later Enigma changes do not rewrite it."""

    name: str
    id_number: str
    service_address: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(self, "id_number", require_text(self.id_number, "id_number"))
        object.__setattr__(
            self, "service_address", require_text(self.service_address, "service_address")
        )


def freeze_booking_identity(identity: EnigmaIdentity) -> FrozenBookingIdentity:
    """Copy name, ID number and service address. Does not copy ``person_id``."""

    if not isinstance(identity, EnigmaIdentity):
        raise ContractError("identity must be an EnigmaIdentity")
    return FrozenBookingIdentity(
        name=identity.name,
        id_number=identity.id_number,
        service_address=identity.service_address,
    )


@runtime_checkable
class SessionOperations(Protocol):
    def introspect(self, session_token: str) -> Session:
        """Resolve a session token to a person, or fail closed."""


@runtime_checkable
class OrganisationOperations(Protocol):
    def context(self, organisation_id: str) -> OrganisationContext:
        """Return organisation id and company registration, or fail closed."""


@runtime_checkable
class Enigma(Protocol):
    """LMS call sites for Enigma.

    The five access operations are ``session.introspect``,
    ``organisation.context``, ``membership``, ``enrolment`` and
    ``lookup_mandate``. ``identity_for_booking`` is the booking-time read of
    the fields the agreement freezes.
    """

    @property
    def session(self) -> SessionOperations:
        """``enigma.session.introspect(session_token)``."""

    @property
    def organisation(self) -> OrganisationOperations:
        """``enigma.organisation.context(organisation_id)``."""

    def membership(self, person_id: str, organisation_id: str) -> Membership:
        """Return roles for an active enrolment, or fail closed."""

    def enrolment(self, person_id: str, organisation_id: str) -> Enrolment:
        """Return an active enrolment, or fail closed."""

    def lookup_mandate(self, person_id: str, organisation_id: str, role: str) -> Mandate:
        """Return whether an active enrolment has the role, or fail closed."""

    def identity_for_booking(self, person_id: str) -> EnigmaIdentity:
        """Return name, ID number and service address for the booking freeze."""
