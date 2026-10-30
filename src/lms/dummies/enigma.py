"""Enigma dummy. Fixed people and organisations. No network and no partial grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lms.errors import EnigmaFailClosed, EnigmaFailureReason
from lms.ports.enigma import (
    EnigmaIdentity,
    Enrolment,
    Mandate,
    Membership,
    OrganisationContext,
    Session,
)
from lms.validation import require_text

_RecordStatus = Literal["clear", "ambiguous", "timeout"]
_EnrolmentStatus = Literal["active", "suspended", "ambiguous"]


@dataclass(frozen=True)
class _Person:
    person_id: str
    name: str
    id_number: str
    service_address: str
    record_status: _RecordStatus


@dataclass(frozen=True)
class _Organisation:
    organisation_id: str
    company_registration_number: str
    record_status: _RecordStatus


@dataclass(frozen=True)
class _Link:
    person_id: str
    organisation_id: str
    roles: tuple[str, ...]
    enrolment_status: _EnrolmentStatus


def _people() -> dict[str, _Person]:
    return {
        "person-active": _Person(
            person_id="person-active",
            name="Test Consumer",
            id_number="0000000000000",
            service_address="1 Dummy Street, Johannesburg",
            record_status="clear",
        ),
        "person-no-mandate": _Person(
            person_id="person-no-mandate",
            name="Test Staff Without Mandate",
            id_number="0000000000001",
            service_address="2 Dummy Street, Johannesburg",
            record_status="clear",
        ),
        "person-suspended": _Person(
            person_id="person-suspended",
            name="Suspended Consumer",
            id_number="0000000000002",
            service_address="3 Dummy Street, Johannesburg",
            record_status="clear",
        ),
        "person-ambiguous": _Person(
            person_id="person-ambiguous",
            name="Ambiguous Consumer",
            id_number="0000000000003",
            service_address="4 Dummy Street, Johannesburg",
            record_status="ambiguous",
        ),
        "person-timeout": _Person(
            person_id="person-timeout",
            name="Timeout Consumer",
            id_number="0000000000004",
            service_address="5 Dummy Street, Johannesburg",
            record_status="timeout",
        ),
        "person-unenrolled": _Person(
            person_id="person-unenrolled",
            name="Unenrolled Consumer",
            id_number="0000000000005",
            service_address="6 Dummy Street, Johannesburg",
            record_status="clear",
        ),
        "person-enrolment-ambiguous": _Person(
            person_id="person-enrolment-ambiguous",
            name="Ambiguous Enrolment",
            id_number="0000000000006",
            service_address="7 Dummy Street, Johannesburg",
            record_status="clear",
        ),
    }


def _organisations() -> dict[str, _Organisation]:
    return {
        "org-active": _Organisation(
            organisation_id="org-active",
            company_registration_number="2020/000000/07",
            record_status="clear",
        ),
        "org-other": _Organisation(
            organisation_id="org-other",
            company_registration_number="2021/000000/07",
            record_status="clear",
        ),
        "org-ambiguous": _Organisation(
            organisation_id="org-ambiguous",
            company_registration_number="2022/000000/07",
            record_status="ambiguous",
        ),
        "org-timeout": _Organisation(
            organisation_id="org-timeout",
            company_registration_number="2023/000000/07",
            record_status="timeout",
        ),
    }


def _links() -> tuple[_Link, ...]:
    read_and_write = ("lms.agreements.read", "lms.elections.write")
    return (
        _Link("person-active", "org-active", read_and_write, "active"),
        _Link("person-no-mandate", "org-active", (), "active"),
        _Link("person-suspended", "org-active", ("lms.agreements.read",), "suspended"),
        _Link("person-ambiguous", "org-active", (), "ambiguous"),
        _Link("person-timeout", "org-active", (), "active"),
        _Link("person-enrolment-ambiguous", "org-active", (), "ambiguous"),
    )


_SESSIONS = {
    "session-active": "person-active",
    "session-no-mandate": "person-no-mandate",
    "session-suspended": "person-suspended",
    "session-ambiguous": "person-ambiguous",
    "session-timeout": "person-timeout",
    "session-unenrolled": "person-unenrolled",
    "session-enrolment-ambiguous": "person-enrolment-ambiguous",
}


class _SessionOperations:
    def __init__(self, dummy: EnigmaDummy) -> None:
        self._dummy = dummy

    def introspect(self, session_token: str) -> Session:
        return self._dummy._introspect(session_token)


class _OrganisationOperations:
    def __init__(self, dummy: EnigmaDummy) -> None:
        self._dummy = dummy

    def context(self, organisation_id: str) -> OrganisationContext:
        return self._dummy._organisation_context(organisation_id)


class EnigmaDummy:
    """The fixed directory documented in ``docs/dummies/enigma.md``."""

    def __init__(self) -> None:
        self._people = _people()
        self._organisations = _organisations()
        self._links = _links()
        self._session = _SessionOperations(self)
        self._organisation = _OrganisationOperations(self)

    @property
    def session(self) -> _SessionOperations:
        return self._session

    @property
    def organisation(self) -> _OrganisationOperations:
        return self._organisation

    def membership(self, person_id: str, organisation_id: str) -> Membership:
        link = self._active_link("membership", person_id, organisation_id)
        return Membership(
            person_id=link.person_id,
            organisation_id=link.organisation_id,
            roles=link.roles,
        )

    def enrolment(self, person_id: str, organisation_id: str) -> Enrolment:
        link = self._active_link("enrolment", person_id, organisation_id)
        return Enrolment(person_id=link.person_id, organisation_id=link.organisation_id)

    def lookup_mandate(self, person_id: str, organisation_id: str, role: str) -> Mandate:
        role = require_text(role, "role")
        link = self._active_link("lookup_mandate", person_id, organisation_id)
        return Mandate(
            person_id=link.person_id,
            organisation_id=link.organisation_id,
            role=role,
            granted=role in link.roles,
        )

    def identity_for_booking(self, person_id: str) -> EnigmaIdentity:
        person = self._person("identity_for_booking", person_id)
        self._require_clear_record("identity_for_booking", person.record_status)
        return EnigmaIdentity(
            person_id=person.person_id,
            name=person.name,
            id_number=person.id_number,
            service_address=person.service_address,
        )

    def _introspect(self, session_token: str) -> Session:
        token = require_text(session_token, "session_token")
        person_id = _SESSIONS.get(token)
        if person_id is None:
            raise EnigmaFailClosed("session.introspect", EnigmaFailureReason.UNKNOWN_SESSION)
        person = self._person("session.introspect", person_id)
        self._require_clear_record("session.introspect", person.record_status)
        return Session(person_id=person.person_id)

    def _organisation_context(self, organisation_id: str) -> OrganisationContext:
        organisation = self._organisation_record("organisation.context", organisation_id)
        self._require_clear_record("organisation.context", organisation.record_status)
        return OrganisationContext(
            organisation_id=organisation.organisation_id,
            company_registration_number=organisation.company_registration_number,
        )

    def _active_link(self, operation: str, person_id: str, organisation_id: str) -> _Link:
        person = self._person(operation, person_id)
        self._require_clear_record(operation, person.record_status)
        organisation = self._organisation_record(operation, organisation_id)
        self._require_clear_record(operation, organisation.record_status)
        link = next(
            (
                item
                for item in self._links
                if item.person_id == person.person_id
                and item.organisation_id == organisation.organisation_id
            ),
            None,
        )
        if link is None:
            raise EnigmaFailClosed(operation, EnigmaFailureReason.NOT_ENROLLED)
        if link.enrolment_status == "suspended":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.SUSPENDED_ENROLMENT)
        if link.enrolment_status == "ambiguous":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.AMBIGUOUS_STATUS)
        if link.enrolment_status != "active":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.AMBIGUOUS_STATUS)
        return link

    def _person(self, operation: str, person_id: str) -> _Person:
        key = require_text(person_id, "person_id")
        person = self._people.get(key)
        if person is None:
            raise EnigmaFailClosed(operation, EnigmaFailureReason.UNKNOWN_PERSON)
        return person

    def _organisation_record(self, operation: str, organisation_id: str) -> _Organisation:
        key = require_text(organisation_id, "organisation_id")
        organisation = self._organisations.get(key)
        if organisation is None:
            raise EnigmaFailClosed(operation, EnigmaFailureReason.UNKNOWN_ORGANISATION)
        return organisation

    @staticmethod
    def _require_clear_record(operation: str, status: _RecordStatus) -> None:
        if status == "timeout":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.TIMEOUT)
        if status == "ambiguous":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.AMBIGUOUS_STATUS)
        if status != "clear":
            raise EnigmaFailClosed(operation, EnigmaFailureReason.AMBIGUOUS_STATUS)
