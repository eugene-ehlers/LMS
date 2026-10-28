"""Operational rand ceilings. Decision 22.

Solution-wide and company-specific amounts are LMS data. The command is
allowed only at or under the tighter of the two. A missing platform ceiling
stops the command. A company amount above the platform amount does not
raise the limit. Zero is a stored ceiling. These are not statutory maxima.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.staff.errors import StaffError
from lms.staff.rates import integer_cents


PLATFORM = "platform"
COMPANY = "company"
CURRENCY = "ZAR"


@dataclass(frozen=True, slots=True)
class RandCeiling:
    scope: str
    action: str
    amount_cents: int
    currency: str
    organisation_id: str
    version: int


@dataclass(frozen=True, slots=True)
class AppliedCeiling:
    action: str
    amount_cents: int
    limit_cents: int
    platform_cents: int
    company_cents: int | None
    platform_version: int
    company_version: int | None
    allowed: bool


class CeilingStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], RandCeiling] = {}

    def put(self, ceiling: RandCeiling) -> RandCeiling:
        _check_row(ceiling)
        self._rows[_key(ceiling.scope, ceiling.action, ceiling.organisation_id)] = ceiling
        return ceiling

    def platform(self, action: str) -> RandCeiling | None:
        return self._rows.get(_key(PLATFORM, action, ""))

    def company(self, organisation_id: str, action: str) -> RandCeiling | None:
        if not organisation_id or not organisation_id.strip():
            raise StaffError("ceiling-organisation", "A company ceiling needs an organisation id.")
        return self._rows.get(_key(COMPANY, action, organisation_id))

    def list_platform(self) -> tuple[RandCeiling, ...]:
        rows = [row for row in self._rows.values() if row.scope == PLATFORM]
        return tuple(sorted(rows, key=lambda row: row.action))

    def list_company(self, organisation_id: str) -> tuple[RandCeiling, ...]:
        rows = [
            row
            for row in self._rows.values()
            if row.scope == COMPANY and row.organisation_id == organisation_id
        ]
        return tuple(sorted(rows, key=lambda row: row.action))


def tighter(action: str, amount_cents: int, platform: RandCeiling | None, company: RandCeiling | None) -> AppliedCeiling:
    """Decision 22. Missing platform ceiling stops the command."""
    integer_cents(amount_cents, "amount")
    if not action or not action.strip():
        raise StaffError("ceiling-action", "A ceiling command needs an action.")
    if platform is None:
        raise StaffError(
            "platform-ceiling-missing",
            "LOCKED_DECISIONS §22: a missing platform ceiling stops the command.",
            status=422,
        )
    _matches(platform, PLATFORM, action, "")
    if company is not None:
        _matches(company, COMPANY, action, company.organisation_id)
        limit = platform.amount_cents if platform.amount_cents < company.amount_cents else company.amount_cents
        company_cents: int | None = company.amount_cents
        company_version: int | None = company.version
    else:
        limit = platform.amount_cents
        company_cents = None
        company_version = None
    return AppliedCeiling(
        action=action,
        amount_cents=amount_cents,
        limit_cents=limit,
        platform_cents=platform.amount_cents,
        company_cents=company_cents,
        platform_version=platform.version,
        company_version=company_version,
        allowed=amount_cents <= limit,
    )


def _check_row(ceiling: RandCeiling) -> None:
    integer_cents(ceiling.amount_cents, "ceiling")
    if ceiling.currency != CURRENCY:
        raise StaffError("ceiling-currency", "Operational ceilings are ZAR.")
    if ceiling.version < 1:
        raise StaffError("ceiling-version", "A ceiling version starts at 1.")
    if not ceiling.action or not ceiling.action.strip():
        raise StaffError("ceiling-action", "A ceiling command needs an action.")
    if ceiling.scope == PLATFORM:
        if ceiling.organisation_id != "":
            raise StaffError("ceiling-scope", "A platform ceiling is not stored on a company.")
        return
    if ceiling.scope == COMPANY:
        if not ceiling.organisation_id or not ceiling.organisation_id.strip():
            raise StaffError("ceiling-organisation", "A company ceiling needs an organisation id.")
        return
    raise StaffError("ceiling-scope", f"Unknown ceiling scope {ceiling.scope!r}.")


def _matches(row: RandCeiling, scope: str, action: str, organisation_id: str) -> None:
    if row.scope != scope or row.action != action or row.organisation_id != organisation_id:
        raise StaffError(
            "ceiling-ambiguous",
            "The ceiling row does not match the command.",
            status=503,
        )
    if row.currency != CURRENCY:
        raise StaffError("ceiling-ambiguous", "The ceiling row is not ZAR.", status=503)


def _key(scope: str, action: str, organisation_id: str) -> tuple[str, str, str]:
    return (scope, action, organisation_id)
