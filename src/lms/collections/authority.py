"""Write-off authority.

Enigma answers identity and access (LOCKED_DECISIONS §15). The operational
ceiling is an LMS amount. The comparison below is the rule in
``lms.enigma.ceilings.enforce_amount``: the platform ceiling, or the lower
of the platform and company ceilings; a missing platform ceiling is
ambiguous; an amount equal to the limit is inside it.

The action id ``lms.account.write_off`` is the Enigma port sketch. §15 does
not name it. Callers pass the action they asked Enigma about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lms.collections.errors import CollectionsError


@dataclass(frozen=True)
class RandCeiling:
    amount_cents: int
    currency: str = "ZAR"
    version: int = 1


@dataclass(frozen=True)
class AppliedAuthority:
    action: str
    limit_cents: int
    platform_version: int
    company_version: int | None
    enigma_request_id: str


class AccessPort(Protocol):
    def check(self, organisation_id: str, actor_id: str, action: str) -> object:
        """Fail closed on timeout, an ambiguous status, or a suspended enrolment."""


def authorise_write_off(
    access: AccessPort,
    *,
    organisation_id: str,
    actor_id: str,
    action: str,
    amount_cents: int,
    platform: RandCeiling | None,
    company: RandCeiling | None,
    mandate_allowed: bool,
) -> AppliedAuthority:
    """§15 fail-closed access, then the operational ceiling.

    ``mandate_allowed`` is the mandate lookup result. False is a deny.
    The access port is still called first: a timeout never becomes a deny.
    """
    if amount_cents < 0:
        raise CollectionsError(
            "authority-ambiguous",
            "LOCKED_DECISIONS §15: a write-off amount is not a clear rand value.",
            status=503,
        )
    try:
        identity = access.check(organisation_id, actor_id, action)
    except Exception as exc:
        code = getattr(exc, "code", "")
        status = getattr(exc, "status", 422)
        if code == "enigma-timeout" or status == 503:
            raise CollectionsError(
                "authority-unavailable",
                "LOCKED_DECISIONS §15: Enigma timed out. The write-off is not posted.",
                status=503,
            ) from exc
        if code == "enigma-suspended":
            raise CollectionsError(
                "enrolment-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The write-off is not posted.",
            ) from exc
        raise CollectionsError(
            "authority-ambiguous",
            "LOCKED_DECISIONS §15: Enigma status is ambiguous. The write-off is not posted.",
            status=503,
        ) from exc
    if not mandate_allowed:
        raise CollectionsError(
            "mandate-denied",
            "The write-off mandate was denied. The journal is not posted.",
        )
    limit, platform_version, company_version = _ceiling(action, platform, company)
    if amount_cents > limit:
        raise CollectionsError(
            "mandate-denied",
            "The write-off is above the operational ceiling. The journal is not posted.",
        )
    request_id = getattr(identity, "enrolment_id", "") or ""
    return AppliedAuthority(
        action=action,
        limit_cents=limit,
        platform_version=platform_version,
        company_version=company_version,
        enigma_request_id=request_id,
    )


def _ceiling(
    action: str,
    platform: RandCeiling | None,
    company: RandCeiling | None,
) -> tuple[int, int, int | None]:
    if not _clear(platform):
        raise CollectionsError(
            "authority-ambiguous",
            "The platform write-off ceiling is not a clear ZAR amount. The journal is not posted.",
            status=503,
        )
    assert platform is not None
    limit = platform.amount_cents
    company_version = None
    if company is not None:
        if not _clear(company):
            raise CollectionsError(
                "authority-ambiguous",
                "The company write-off ceiling is not a clear ZAR amount. The journal is not posted.",
                status=503,
            )
        limit = min(limit, company.amount_cents)
        company_version = company.version
    if not action:
        raise CollectionsError(
            "authority-ambiguous",
            "The write-off action is blank. The journal is not posted.",
            status=503,
        )
    return limit, platform.version, company_version


def _clear(ceiling: RandCeiling | None) -> bool:
    return (
        ceiling is not None
        and ceiling.currency == "ZAR"
        and ceiling.amount_cents >= 0
    )
