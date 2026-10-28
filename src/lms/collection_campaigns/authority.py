"""Staff authority for collection campaigns.

Enigma answers identity and access (LOCKED_DECISIONS §15). This module does
not store roles and does not treat a timeout as a denial.
"""

from __future__ import annotations

from typing import Protocol

from lms.collection_campaigns.errors import CollectionCampaignError
from lms.collection_campaigns.models import ROLE


class AccessPort(Protocol):
    def check(self, organisation_id: str, actor_id: str, action: str) -> object:
        """Fail closed on timeout, an ambiguous status, or a suspended enrolment."""


def authorise(access: AccessPort, *, organisation_id: str, actor_id: str) -> str:
    """Return the staff actor id when Enigma allows ``lms.collection_campaign.write``."""
    if not organisation_id or not actor_id or not str(actor_id).strip():
        raise CollectionCampaignError(
            "authority-ambiguous",
            "LOCKED_DECISIONS §15: a collection-campaign change needs an organisation and a staff actor.",
            status=503,
        )
    try:
        access.check(organisation_id, actor_id, ROLE)
    except Exception as exc:
        code = getattr(exc, "code", "")
        status = getattr(exc, "status", 422)
        if code == "enigma-timeout" or status == 503:
            raise CollectionCampaignError(
                "authority-unavailable",
                "LOCKED_DECISIONS §15: Enigma timed out. The collection campaign was not changed.",
                status=503,
            ) from exc
        if code == "enigma-suspended":
            raise CollectionCampaignError(
                "enrolment-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The collection campaign was not changed.",
            ) from exc
        raise CollectionCampaignError(
            "authority-ambiguous",
            "LOCKED_DECISIONS §15: Enigma status is ambiguous. The collection campaign was not changed.",
            status=503,
        ) from exc
    return actor_id
