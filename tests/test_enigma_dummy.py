from dataclasses import asdict, fields

import pytest

from lms.dummies.enigma import EnigmaDummy
from lms.errors import ContractError, EnigmaFailClosed, EnigmaFailureReason
from lms.ports.enigma import (
    Enigma,
    EnigmaIdentity,
    Enrolment,
    Mandate,
    Membership,
    OrganisationContext,
    Session,
    freeze_booking_identity,
)


@pytest.fixture
def enigma() -> EnigmaDummy:
    return EnigmaDummy()


def test_five_operations_succeed_for_the_active_fixture(enigma: EnigmaDummy) -> None:
    assert isinstance(enigma, Enigma)

    session = enigma.session.introspect("session-active")
    context = enigma.organisation.context("org-active")
    membership = enigma.membership("person-active", "org-active")
    enrolment = enigma.enrolment("person-active", "org-active")
    mandate = enigma.lookup_mandate("person-active", "org-active", "lms.elections.write")

    assert isinstance(session, Session)
    assert session.person_id == "person-active"
    assert isinstance(context, OrganisationContext)
    assert context.organisation_id == "org-active"
    assert context.company_registration_number == "2020/000000/07"
    assert isinstance(membership, Membership)
    assert membership.roles == ("lms.agreements.read", "lms.elections.write")
    assert isinstance(enrolment, Enrolment)
    assert enrolment.status == "active"
    assert isinstance(mandate, Mandate)
    assert mandate.granted is True


def test_organisation_context_excludes_lms_owned_compliance_data(enigma: EnigmaDummy) -> None:
    context = enigma.organisation.context("org-active")

    assert {field.name for field in fields(context)} == {
        "organisation_id",
        "company_registration_number",
    }
    dumped = asdict(context)
    for forbidden in (
        "ncr_registration_number",
        "trading_name",
        "address",
        "service_address",
        "telephone",
        "email",
        "payment_account",
        "brand",
        "ceiling",
        "campaign",
    ):
        assert forbidden not in dumped


def test_missing_role_is_a_clear_denial(enigma: EnigmaDummy) -> None:
    mandate = enigma.lookup_mandate("person-no-mandate", "org-active", "lms.elections.write")
    other = enigma.lookup_mandate("person-active", "org-active", "lms.campaign.write")

    assert mandate.granted is False
    assert other.granted is False
    assert enigma.membership("person-no-mandate", "org-active").roles == ()


def test_suspended_enrolment_fails_closed_without_leaking_roles(enigma: EnigmaDummy) -> None:
    session = enigma.session.introspect("session-suspended")
    assert session.person_id == "person-suspended"

    for call in (
        lambda: enigma.membership("person-suspended", "org-active"),
        lambda: enigma.enrolment("person-suspended", "org-active"),
        lambda: enigma.lookup_mandate("person-suspended", "org-active", "lms.agreements.read"),
    ):
        with pytest.raises(EnigmaFailClosed) as caught:
            call()
        assert caught.value.reason is EnigmaFailureReason.SUSPENDED_ENROLMENT
        assert "lms.agreements.read" not in str(caught.value)


def test_timeout_and_ambiguous_person_fail_closed_with_no_session(enigma: EnigmaDummy) -> None:
    with pytest.raises(EnigmaFailClosed) as timeout:
        enigma.session.introspect("session-timeout")
    with pytest.raises(EnigmaFailClosed) as ambiguous:
        enigma.session.introspect("session-ambiguous")

    assert timeout.value.reason is EnigmaFailureReason.TIMEOUT
    assert timeout.value.operation == "session.introspect"
    assert ambiguous.value.reason is EnigmaFailureReason.AMBIGUOUS_STATUS
    assert ambiguous.value.operation == "session.introspect"


def test_ambiguous_enrolment_fails_closed_while_the_person_record_stays_readable(
    enigma: EnigmaDummy,
) -> None:
    assert enigma.session.introspect("session-enrolment-ambiguous").person_id == (
        "person-enrolment-ambiguous"
    )
    identity = enigma.identity_for_booking("person-enrolment-ambiguous")
    assert identity.name == "Ambiguous Enrolment"

    with pytest.raises(EnigmaFailClosed) as caught:
        enigma.enrolment("person-enrolment-ambiguous", "org-active")
    assert caught.value.reason is EnigmaFailureReason.AMBIGUOUS_STATUS


def test_timeout_and_ambiguous_records_fail_closed_on_every_direct_read(
    enigma: EnigmaDummy,
) -> None:
    cases = (
        ("person-timeout", "org-timeout", EnigmaFailureReason.TIMEOUT),
        ("person-ambiguous", "org-ambiguous", EnigmaFailureReason.AMBIGUOUS_STATUS),
    )
    for person_id, organisation_id, reason in cases:
        with pytest.raises(EnigmaFailClosed) as identity:
            enigma.identity_for_booking(person_id)
        with pytest.raises(EnigmaFailClosed) as context:
            enigma.organisation.context(organisation_id)
        with pytest.raises(EnigmaFailClosed) as membership:
            enigma.membership(person_id, "org-active")
        assert identity.value.reason is reason
        assert context.value.reason is reason
        assert membership.value.reason is reason
        assert organisation_id not in str(context.value)


def test_unknown_session_person_and_organisation_fail_closed(enigma: EnigmaDummy) -> None:
    with pytest.raises(EnigmaFailClosed) as session:
        enigma.session.introspect("missing")
    with pytest.raises(EnigmaFailClosed) as person:
        enigma.identity_for_booking("missing")
    with pytest.raises(EnigmaFailClosed) as organisation:
        enigma.organisation.context("missing")
    with pytest.raises(ContractError):
        enigma.session.introspect("  ")

    assert session.value.reason is EnigmaFailureReason.UNKNOWN_SESSION
    assert person.value.reason is EnigmaFailureReason.UNKNOWN_PERSON
    assert organisation.value.reason is EnigmaFailureReason.UNKNOWN_ORGANISATION


def test_not_enrolled_is_a_clear_negative(enigma: EnigmaDummy) -> None:
    assert enigma.session.introspect("session-unenrolled").person_id == "person-unenrolled"
    context = enigma.organisation.context("org-other")
    assert context.company_registration_number == "2021/000000/07"

    with pytest.raises(EnigmaFailClosed) as unenrolled:
        enigma.enrolment("person-unenrolled", "org-active")
    with pytest.raises(EnigmaFailClosed) as other_org:
        enigma.membership("person-active", "org-other")

    assert unenrolled.value.reason is EnigmaFailureReason.NOT_ENROLLED
    assert other_org.value.reason is EnigmaFailureReason.NOT_ENROLLED


def test_booking_identity_returns_the_three_frozen_fields(enigma: EnigmaDummy) -> None:
    identity = enigma.identity_for_booking("person-active")
    frozen = freeze_booking_identity(identity)

    assert isinstance(identity, EnigmaIdentity)
    assert set(asdict(identity)) == {
        "person_id",
        "name",
        "id_number",
        "service_address",
    }
    assert identity.name == "Test Consumer"
    assert identity.id_number == "0000000000000"
    assert identity.service_address == "1 Dummy Street, Johannesburg"
    assert set(asdict(frozen)) == {"name", "id_number", "service_address"}
    assert frozen.name == identity.name
    assert frozen.id_number == identity.id_number
    assert frozen.service_address == identity.service_address
    assert not hasattr(frozen, "person_id")


def test_suspended_consumer_identity_can_still_be_read(enigma: EnigmaDummy) -> None:
    identity = enigma.identity_for_booking("person-suspended")

    assert identity.service_address == "3 Dummy Street, Johannesburg"
    with pytest.raises(EnigmaFailClosed) as caught:
        enigma.enrolment("person-suspended", "org-active")
    assert caught.value.reason is EnigmaFailureReason.SUSPENDED_ENROLMENT


def test_freeze_rejects_a_blank_service_address() -> None:
    with pytest.raises(ContractError):
        EnigmaIdentity(
            person_id="person-active",
            name="Test Consumer",
            id_number="0000000000000",
            service_address=" ",
        )


def test_call_site_accepts_another_enigma() -> None:
    class ScriptedSession:
        def introspect(self, session_token: str) -> Session:
            return Session(person_id="person-scripted")

    class ScriptedOrganisation:
        def context(self, organisation_id: str) -> OrganisationContext:
            return OrganisationContext(
                organisation_id=organisation_id,
                company_registration_number="2099/000000/07",
            )

    class ScriptedEnigma:
        def __init__(self) -> None:
            self.session = ScriptedSession()
            self.organisation = ScriptedOrganisation()

        def membership(self, person_id: str, organisation_id: str) -> Membership:
            return Membership(person_id=person_id, organisation_id=organisation_id, roles=())

        def enrolment(self, person_id: str, organisation_id: str) -> Enrolment:
            return Enrolment(person_id=person_id, organisation_id=organisation_id)

        def lookup_mandate(self, person_id: str, organisation_id: str, role: str) -> Mandate:
            return Mandate(
                person_id=person_id,
                organisation_id=organisation_id,
                role=role,
                granted=False,
            )

        def identity_for_booking(self, person_id: str) -> EnigmaIdentity:
            return EnigmaIdentity(
                person_id=person_id,
                name="Scripted",
                id_number="0000000000000",
                service_address="9 Script Street",
            )

    def introspect(port: Enigma, token: str) -> Session:
        return port.session.introspect(token)

    assert introspect(ScriptedEnigma(), "any").person_id == "person-scripted"
    assert introspect(EnigmaDummy(), "session-active").person_id == "person-active"
    frozen = freeze_booking_identity(ScriptedEnigma().identity_for_booking("person-scripted"))
    assert frozen.service_address == "9 Script Street"
