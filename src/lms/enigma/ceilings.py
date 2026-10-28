"""Operational rand ceilings.

TSDG adjusts the platform ceiling. A company role adjusts that company's ceiling.
Enigma decides whether the actor holds the role. LMS stores the amounts and applies the
tighter of the two. Statutory NCA maxima are outside this module.
"""

from __future__ import annotations

from typing import Protocol

from lms.enigma.errors import AmbiguousAuthority, MandateDenied
from lms.enigma.models import (
    COMPANY_CEILING_ROLE,
    PLATFORM_CEILING_ROLE,
    AppliedCeiling,
    CeilingScope,
    Membership,
    RandCeiling,
)


class CeilingStore(Protocol):
    def platform(self, action: str) -> RandCeiling | None:
        """Solution-wide ceiling for one action. None means TSDG has not set it."""

    def company(self, organisation_id: str, action: str) -> RandCeiling | None:
        """Company ceiling. None means the company has not tightened the platform ceiling."""


def authorize_ceiling_change(
    membership: Membership,
    *,
    scope: CeilingScope,
    actor_organisation_id: str,
    target_organisation_id: str,
    platform_organisation_id: str,
) -> None:
    """Guard for the ceiling screens. The caller has already validated this membership with Enigma."""

    if membership.status != "active" or not membership.roles:
        raise AmbiguousAuthority(
            "membership and role are not both clear",
            enigma_request_id=membership.enigma_request_id,
        )
    if scope == "platform":
        if (
            actor_organisation_id != platform_organisation_id
            or target_organisation_id != platform_organisation_id
            or PLATFORM_CEILING_ROLE not in membership.roles
        ):
            raise MandateDenied(
                "platform ceiling change",
                enigma_request_id=membership.enigma_request_id,
            )
        return
    if scope == "company":
        if (
            actor_organisation_id != target_organisation_id
            or actor_organisation_id == platform_organisation_id
            or COMPANY_CEILING_ROLE not in membership.roles
        ):
            raise MandateDenied(
                "company ceiling change",
                enigma_request_id=membership.enigma_request_id,
            )
        return
    raise AmbiguousAuthority("ceiling scope", enigma_request_id=membership.enigma_request_id)


def enforce_amount(
    *,
    action: str,
    amount_cents: int,
    platform: RandCeiling | None,
    company: RandCeiling | None,
) -> AppliedCeiling:
    """Refuse when the platform ceiling is missing or either row is not a clear ZAR amount.

    The effective limit is the platform ceiling, or the lower of the two when the company
    has set one. A company figure above the platform ceiling does not raise the limit.
    ``amount_cents`` equal to the limit is inside the ceiling.
    """

    limit_platform = _clear_ceiling(platform, action=action, scope="platform")
    if company is None:
        limit = limit_platform
        company_version = None
    else:
        limit = min(limit_platform, _clear_ceiling(company, action=action, scope="company"))
        company_version = company.version
    if amount_cents < 0:
        raise AmbiguousAuthority("amount is not a clear rand value")
    if amount_cents > limit:
        raise MandateDenied("ceiling")
    assert platform is not None
    return AppliedCeiling(
        action=action,
        limit_cents=limit,
        platform_version=platform.version,
        company_version=company_version,
    )


def _clear_ceiling(ceiling: RandCeiling | None, *, action: str, scope: CeilingScope) -> int:
    if (
        ceiling is None
        or ceiling.scope != scope
        or ceiling.action != action
        or ceiling.currency != "ZAR"
        or ceiling.amount_cents < 0
    ):
        raise AmbiguousAuthority(f"{scope} ceiling is not clear")
    return ceiling.amount_cents
