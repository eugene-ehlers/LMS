"""Client for the five port operations.

The client maps transport failures onto fail-closed errors. An unclear sign-in, membership,
role, or enrolment is ``AmbiguousAuthority`` and does not fall through to a local staff list.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from lms.enigma.errors import (
    AmbiguousAuthority,
    AuthorityUnavailable,
    EnrolmentDenied,
    MandateDenied,
    NotAMember,
    OrganisationUnavailable,
    Reauthenticate,
    TransportHTTPError,
    TransportTimeout,
)
from lms.enigma.models import (
    LMS_AUDIENCE,
    Enrolment,
    MandateDecision,
    MandateQuery,
    Membership,
    OrganisationContext,
    SessionView,
)
from lms.enigma.port import EnigmaPort

T = TypeVar("T")


class EnigmaClient:
    def __init__(self, port: EnigmaPort) -> None:
        self._port = port

    def introspect(self, session_ref: str, *, request_id: str) -> SessionView:
        view = self._call(lambda: self._port.introspect(session_ref, request_id=request_id))
        if view.audience != LMS_AUDIENCE or view.status in {"expired", "revoked"}:
            raise Reauthenticate(
                "session is not an active lms session",
                enigma_request_id=view.enigma_request_id,
            )
        if view.status != "active" or not view.sign_in_clear or not view.person_id:
            raise AmbiguousAuthority(
                "sign-in status is not clear",
                enigma_request_id=view.enigma_request_id,
            )
        return view

    def organisation_context(
        self, session_ref: str, organisation_id: str, *, request_id: str
    ) -> OrganisationContext:
        context = self._call(
            lambda: self._port.organisation_context(
                session_ref, organisation_id, request_id=request_id
            )
        )
        if context.status in {"suspended", "closed"} or context.organisation_id != organisation_id:
            raise OrganisationUnavailable(
                "organisation is not active",
                enigma_request_id=context.enigma_request_id,
            )
        if context.status != "active":
            raise AmbiguousAuthority(
                "organisation status is not clear",
                enigma_request_id=context.enigma_request_id,
            )
        return context

    def validate_membership(
        self, session_ref: str, person_id: str, organisation_id: str, *, request_id: str
    ) -> Membership:
        membership = self._call(
            lambda: self._port.validate_membership(
                session_ref, person_id, organisation_id, request_id=request_id
            )
        )
        if membership.status in {"suspended", "absent"}:
            raise NotAMember(
                "membership is not active",
                enigma_request_id=membership.enigma_request_id,
            )
        if membership.status != "active" or not membership.roles:
            raise AmbiguousAuthority(
                "membership and role are not both clear",
                enigma_request_id=membership.enigma_request_id,
            )
        return membership

    def lookup_mandate(self, query: MandateQuery, *, request_id: str) -> MandateDecision:
        decision = self._call(lambda: self._port.lookup_mandate(query, request_id=request_id))
        if decision.decision == "deny":
            raise MandateDenied(
                decision.reason or "deny",
                enigma_request_id=decision.enigma_request_id,
            )
        if (
            decision.decision != "allow"
            or not decision.mandate_id
            or decision.mandate_version is None
        ):
            raise AmbiguousAuthority(
                "mandate decision is not clear",
                enigma_request_id=decision.enigma_request_id,
            )
        return decision

    def check_enrolment(
        self, session_ref: str, organisation_id: str, product_code: str, *, request_id: str
    ) -> Enrolment:
        enrolment = self._call(
            lambda: self._port.check_enrolment(
                session_ref, organisation_id, product_code, request_id=request_id
            )
        )
        if enrolment.product_code != product_code:
            raise AmbiguousAuthority(
                "enrolment answer is for a different product",
                enigma_request_id=enrolment.enigma_request_id,
            )
        if enrolment.status in {"suspended", "absent"}:
            raise EnrolmentDenied(
                "enrolment is not active",
                enigma_request_id=enrolment.enigma_request_id,
            )
        if enrolment.status != "active" or not enrolment.enrolment_id:
            raise AmbiguousAuthority(
                "enrolment status is not clear",
                enigma_request_id=enrolment.enigma_request_id,
            )
        return enrolment

    def _call(self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except TransportTimeout as exc:
            raise AuthorityUnavailable("enigma timeout") from exc
        except TransportHTTPError as exc:
            if exc.status >= 500:
                raise AuthorityUnavailable(f"enigma http {exc.status}") from exc
            if exc.status in {401, 407}:
                raise Reauthenticate(f"enigma http {exc.status}") from exc
            raise AmbiguousAuthority(f"enigma http {exc.status}") from exc
