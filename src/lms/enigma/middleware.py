"""Session edge for human requests.

Every request introspects the Enigma session. A cookie generation that does not match the
server session returns 409 and does not read the loan. Timeout and HTTP 5xx become
``authority_unavailable``. Unclear sign-in, membership, role, or enrolment stops the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from lms.enigma.ceilings import CeilingStore, enforce_amount
from lms.enigma.client import EnigmaClient
from lms.enigma.errors import AmbiguousAuthority, OrganisationContextStale, PortError, Reauthenticate
from lms.enigma.models import MandateQuery


@dataclass
class SessionRecord:
    lms_session_id: str
    session_ref: str
    person_id: str
    active_organisation_id: str
    organisation_generation: int


class SessionStore(Protocol):
    def get(self, lms_session_id: str) -> SessionRecord | None:
        """Return the server session, or None when the cookie names nothing."""

    def save(self, record: SessionRecord) -> None:
        """Persist the session. Production storage encrypts ``session_ref`` at rest."""


@dataclass(frozen=True)
class IncomingRequest:
    lms_session_id: str | None
    organisation_generation: int | None
    action: str
    product_code: str | None = None
    amount_cents: int | None = None
    switch_to_organisation_id: str | None = None


@dataclass(frozen=True)
class HttpResult:
    status: int
    error: str | None
    person_id: str | None = None
    organisation_id: str | None = None
    organisation_generation: int | None = None
    mandate_id: str | None = None
    mandate_version: int | None = None
    enrolment_id: str | None = None
    enrolment_version: int | None = None
    enigma_request_id: str | None = None


class MemorySessionStore:
    def __init__(self) -> None:
        self._rows: dict[str, SessionRecord] = {}

    def get(self, lms_session_id: str) -> SessionRecord | None:
        return self._rows.get(lms_session_id)

    def save(self, record: SessionRecord) -> None:
        self._rows[record.lms_session_id] = record


def establish_session(
    session_ref: str,
    organisation_id: str,
    *,
    sessions: SessionStore,
    client: EnigmaClient,
    request_id: str,
    lms_session_id: str | None = None,
) -> HttpResult:
    """Create the LMS cookie session after Cognito and Enigma have authenticated the person."""

    try:
        view = client.introspect(session_ref, request_id=request_id)
        client.organisation_context(session_ref, organisation_id, request_id=request_id)
        client.validate_membership(
            session_ref, view.person_id, organisation_id, request_id=request_id
        )
        if view.bound_organisation_id not in {None, organisation_id}:
            raise AmbiguousAuthority(
                "session is bound to a different organisation",
                enigma_request_id=view.enigma_request_id,
            )
        record = SessionRecord(
            lms_session_id=lms_session_id or uuid4().hex,
            session_ref=session_ref,
            person_id=view.person_id,
            active_organisation_id=organisation_id,
            organisation_generation=1,
        )
        sessions.save(record)
        return HttpResult(
            status=200,
            error=None,
            person_id=record.person_id,
            organisation_id=record.active_organisation_id,
            organisation_generation=record.organisation_generation,
            enigma_request_id=view.enigma_request_id,
        )
    except PortError as exc:
        return _from_error(exc)


def handle_request(
    incoming: IncomingRequest,
    *,
    sessions: SessionStore,
    client: EnigmaClient,
    ceilings: CeilingStore,
    request_id: str,
) -> HttpResult:
    try:
        return _handle(incoming, sessions=sessions, client=client, ceilings=ceilings, request_id=request_id)
    except PortError as exc:
        return _from_error(exc)


def _handle(
    incoming: IncomingRequest,
    *,
    sessions: SessionStore,
    client: EnigmaClient,
    ceilings: CeilingStore,
    request_id: str,
) -> HttpResult:
    if not incoming.lms_session_id or not incoming.action:
        raise Reauthenticate("session or action is missing")
    record = sessions.get(incoming.lms_session_id)
    if record is None:
        raise Reauthenticate("session is unknown")

    view = client.introspect(record.session_ref, request_id=request_id)
    if view.person_id != record.person_id:
        raise AmbiguousAuthority(
            "session person does not match the LMS session",
            enigma_request_id=view.enigma_request_id,
        )
    if incoming.organisation_generation != record.organisation_generation:
        raise OrganisationContextStale(
            "organisation generation is stale",
            organisation_id=record.active_organisation_id,
            organisation_generation=record.organisation_generation,
            enigma_request_id=view.enigma_request_id,
        )

    if incoming.switch_to_organisation_id:
        return _switch(
            record,
            incoming.switch_to_organisation_id,
            sessions=sessions,
            client=client,
            request_id=request_id,
            enigma_request_id=view.enigma_request_id,
        )

    if view.bound_organisation_id not in {None, record.active_organisation_id}:
        raise AmbiguousAuthority(
            "session is bound to a different organisation",
            enigma_request_id=view.enigma_request_id,
        )

    if not incoming.product_code:
        raise AmbiguousAuthority("product is not clear", enigma_request_id=view.enigma_request_id)
    context = client.organisation_context(
        record.session_ref, record.active_organisation_id, request_id=request_id
    )
    membership = client.validate_membership(
        record.session_ref,
        record.person_id,
        record.active_organisation_id,
        request_id=request_id,
    )
    enrolment = client.check_enrolment(
        record.session_ref,
        record.active_organisation_id,
        incoming.product_code,
        request_id=request_id,
    )
    decision = client.lookup_mandate(
        MandateQuery(
            session_ref=record.session_ref,
            person_id=record.person_id,
            organisation_id=record.active_organisation_id,
            action=incoming.action,
            product_code=incoming.product_code,
        ),
        request_id=request_id,
    )
    if incoming.amount_cents is not None:
        enforce_amount(
            action=incoming.action,
            amount_cents=incoming.amount_cents,
            platform=ceilings.platform(incoming.action),
            company=ceilings.company(record.active_organisation_id, incoming.action),
        )
    return HttpResult(
        status=200,
        error=None,
        person_id=record.person_id,
        organisation_id=context.organisation_id,
        organisation_generation=record.organisation_generation,
        mandate_id=decision.mandate_id,
        mandate_version=decision.mandate_version,
        enrolment_id=enrolment.enrolment_id,
        enrolment_version=enrolment.enrolment_version,
        enigma_request_id=decision.enigma_request_id or membership.enigma_request_id,
    )


def _switch(
    record: SessionRecord,
    organisation_id: str,
    *,
    sessions: SessionStore,
    client: EnigmaClient,
    request_id: str,
    enigma_request_id: str,
) -> HttpResult:
    client.organisation_context(record.session_ref, organisation_id, request_id=request_id)
    client.validate_membership(
        record.session_ref, record.person_id, organisation_id, request_id=request_id
    )
    if organisation_id == record.active_organisation_id:
        return HttpResult(
            status=200,
            error=None,
            person_id=record.person_id,
            organisation_id=organisation_id,
            organisation_generation=record.organisation_generation,
            enigma_request_id=enigma_request_id,
        )
    updated = SessionRecord(
        lms_session_id=record.lms_session_id,
        session_ref=record.session_ref,
        person_id=record.person_id,
        active_organisation_id=organisation_id,
        organisation_generation=record.organisation_generation + 1,
    )
    sessions.save(updated)
    return HttpResult(
        status=200,
        error=None,
        person_id=updated.person_id,
        organisation_id=updated.active_organisation_id,
        organisation_generation=updated.organisation_generation,
        enigma_request_id=enigma_request_id,
    )


def _from_error(exc: PortError) -> HttpResult:
    organisation_id = getattr(exc, "organisation_id", None)
    generation = getattr(exc, "organisation_generation", None)
    return HttpResult(
        status=exc.http_status,
        error=exc.code,
        organisation_id=organisation_id,
        organisation_generation=generation,
        enigma_request_id=exc.enigma_request_id,
    )
