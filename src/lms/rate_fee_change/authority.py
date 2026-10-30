"""Staff authority for a rate or fee change.

Enigma answers identity and access (LOCKED_DECISIONS §15). This module does
not store roles and does not treat a timeout as success.
"""

from __future__ import annotations

from typing import Protocol

from lms.rate_fee_change.errors import RateFeeChangeError
from lms.rate_fee_change.models import ROLE


class AccessPort(Protocol):
    def check(self, organisation_id: str, actor_id: str, action: str) -> object:
        """Fail closed on timeout, an ambiguous status, or a suspended enrolment."""


def authorise(access: AccessPort, *, organisation_id: str, actor_id: str) -> str:
    """Return the staff actor id when Enigma allows ``lms.rate_fee_change.write``."""
    if not organisation_id or not actor_id or not str(actor_id).strip():
        raise RateFeeChangeError(
            "authority-ambiguous",
            "A rate or fee change needs an organisation and a staff actor. "
            "Enigma did not confirm one, so the change was not applied.",
            status=503,
        )
    try:
        allowed = access.check(organisation_id, actor_id, ROLE)
    except Exception as exc:
        code = getattr(exc, "code", "")
        status = getattr(exc, "status", 422)
        if code == "enigma-timeout" or status == 503:
            raise RateFeeChangeError(
                "authority-unavailable",
                "Enigma timed out. The rate or fee change was not applied.",
                status=503,
            ) from exc
        if code == "enigma-suspended":
            raise RateFeeChangeError(
                "enrolment-suspended",
                "The enrolment is suspended. The rate or fee change was not applied.",
            ) from exc
        raise RateFeeChangeError(
            "authority-ambiguous",
            "Enigma status is ambiguous. The rate or fee change was not applied.",
            status=503,
        ) from exc
    if allowed is False:
        raise RateFeeChangeError(
            "authority-ambiguous",
            "Enigma did not allow this rate or fee change. Nothing was applied.",
            status=503,
        )
    return actor_id
