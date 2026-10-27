"""Value types for the LMS port. Field names are the port, not Enigma's JSON."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

LMS_AUDIENCE = "lms"

SessionStatus = Literal["active", "expired", "revoked"]
OrganisationStatus = Literal["active", "suspended", "closed"]
MembershipStatus = Literal["active", "suspended", "absent"]
EnrolmentStatus = Literal["active", "suspended", "absent"]
MandateOutcome = Literal["allow", "deny"]
CeilingScope = Literal["platform", "company"]

# Role identifiers the LMS asks Enigma about. The adapter maps them onto Enigma's real role ids.
STAFF_ADMIN_ROLE = "lms.staff.admin"
PLATFORM_CEILING_ROLE = "lms.ceiling.platform.write"
COMPANY_CEILING_ROLE = "lms.ceiling.company.write"

PRODUCT_MICRO = "lms.micro_short_term"
PRODUCT_UNSECURED = "lms.unsecured_personal"
PRODUCT_BNPL_LAYBYE = "lms.bnpl_laybye"
PRODUCT_LAYBYE_SECURITY = "lms.laybye_security"

# Laybye/BNPL does not require an NCR number. The other two day-1 credit products do, once reporting is on.
NCA_PRODUCTS = frozenset({PRODUCT_MICRO, PRODUCT_UNSECURED})
LAYBYE_PRODUCTS = frozenset({PRODUCT_BNPL_LAYBYE, PRODUCT_LAYBYE_SECURITY})


@dataclass(frozen=True)
class OrganisationMembershipSummary:
    organisation_id: str
    status: MembershipStatus


@dataclass(frozen=True)
class SessionView:
    status: SessionStatus
    person_id: str
    audience: str
    expires_at: datetime
    bound_organisation_id: str | None
    organisations: tuple[OrganisationMembershipSummary, ...]
    sign_in_clear: bool
    enigma_request_id: str


@dataclass(frozen=True)
class OrganisationContext:
    organisation_id: str
    status: str
    legal_name: str
    trading_name: str
    enigma_request_id: str


@dataclass(frozen=True)
class Membership:
    status: str
    membership_id: str
    membership_version: int
    roles: tuple[str, ...]
    enigma_request_id: str


@dataclass(frozen=True)
class MandateQuery:
    session_ref: str
    person_id: str
    organisation_id: str
    action: str
    product_code: str | None


@dataclass(frozen=True)
class MandateDecision:
    decision: str
    reason: str
    mandate_id: str | None
    mandate_version: int | None
    enigma_request_id: str


@dataclass(frozen=True)
class Enrolment:
    status: str
    enrolment_id: str | None
    enrolment_version: int | None
    product_code: str
    enigma_request_id: str


@dataclass(frozen=True)
class LiveIdentity:
    """Current Enigma person. Used at booking and, separately, for communication preferences."""

    person_id: str
    name: str
    id_number: str
    service_address: str
    email: str | None
    mobile: str | None
    preferred_channel: str | None
    enigma_request_id: str


@dataclass(frozen=True)
class AgreementIdentity:
    """Frozen at booking. Later Enigma edits do not write this object."""

    person_id: str
    name: str
    id_number: str
    service_address: str
    frozen_at: datetime
    source_request_id: str


@dataclass(frozen=True)
class CommunicationPreferences:
    person_id: str
    email: str | None
    mobile: str | None
    preferred_channel: str | None
    enigma_request_id: str


@dataclass(frozen=True)
class RandCeiling:
    scope: CeilingScope
    action: str
    amount_cents: int
    currency: str
    organisation_id: str | None
    version: int


@dataclass(frozen=True)
class AppliedCeiling:
    action: str
    limit_cents: int
    platform_version: int
    company_version: int | None


@dataclass(frozen=True)
class IamCallerProof:
    """Presigned STS GetCallerIdentity produced by the task role. LMS does not mint access keys."""

    presigned_url: str
    organisation_id: str


@dataclass(frozen=True)
class MachineRegistration:
    """Held by Enigma, amended by the same admin role that amends the staff list. LMS does not store it."""

    machine_id: str
    organisation_id: str
    iam_role_arn: str
    allowed_actions: frozenset[str]
