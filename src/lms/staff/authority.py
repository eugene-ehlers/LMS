"""Staff gate. Enigma owns the person, the organisation, and the roles.

The LMS stores the opaque ids and the role names it was given. It does not
resolve a person, and it does not invent a role Enigma did not return.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.staff.errors import StaffError


ROLE_CAMPAIGN_WRITE = "lms.campaign.write"
ROLE_ELECTIONS_WRITE = "lms.elections.write"
ROLE_COMPLIANCE_WRITE = "lms.compliance.write"
ROLE_CEILING_PLATFORM_WRITE = "lms.ceiling.platform.write"
ROLE_CEILING_COMPANY_WRITE = "lms.ceiling.company.write"

_ACTIVE = "active"
_TIMEOUT = "timeout"
_AMBIGUOUS = "ambiguous"
_SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class StaffActor:
    person_id: str
    organisation_id: str
    roles: frozenset[str]
    enigma_status: str = _ACTIVE


def require_actor(actor: StaffActor) -> StaffActor:
    """Decision 15. Timeout, an ambiguous status, or a suspended enrolment stops the command."""
    if not actor.person_id or not actor.person_id.strip():
        raise StaffError(
            "enigma-ambiguous",
            "LOCKED_DECISIONS §15: a staff command without an Enigma person id is ambiguous.",
            status=503,
        )
    if not actor.organisation_id or not actor.organisation_id.strip():
        raise StaffError(
            "enigma-ambiguous",
            "LOCKED_DECISIONS §15: a staff command without an Enigma organisation id is ambiguous.",
            status=503,
        )
    if actor.enigma_status == _TIMEOUT:
        raise StaffError(
            "enigma-timeout",
            "LOCKED_DECISIONS §15: Enigma timed out. The call fails closed.",
            status=503,
        )
    if actor.enigma_status == _SUSPENDED:
        raise StaffError(
            "enigma-suspended",
            "LOCKED_DECISIONS §15: the enrolment is suspended. The call fails closed.",
            status=403,
        )
    if actor.enigma_status != _ACTIVE:
        raise StaffError(
            "enigma-ambiguous",
            "LOCKED_DECISIONS §15: Enigma did not return a clear active enrolment.",
            status=503,
        )
    return actor


def require_role(actor: StaffActor, role: str) -> StaffActor:
    require_actor(actor)
    if role not in actor.roles:
        raise StaffError(
            "mandate-denied",
            f"The Enigma enrolment does not include {role}.",
            status=403,
        )
    return actor


_STAFF_ROLES = frozenset(
    {
        ROLE_CAMPAIGN_WRITE,
        ROLE_ELECTIONS_WRITE,
        ROLE_COMPLIANCE_WRITE,
        ROLE_CEILING_PLATFORM_WRITE,
        ROLE_CEILING_COMPANY_WRITE,
    }
)


def require_staff_role(actor: StaffActor) -> StaffActor:
    """A staff read still needs one of the roles this layer writes with.

    Decision 23 does not name a separate read role. An enrolment with none
    of these roles is refused. A new role name is not invented.
    """
    require_actor(actor)
    if not actor.roles & _STAFF_ROLES:
        raise StaffError(
            "mandate-denied",
            "The Enigma enrolment does not include a staff role for this command.",
            status=403,
        )
    return actor
