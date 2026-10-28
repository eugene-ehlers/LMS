"""Statement-ready push. Figures stay on the issued statement."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from lms.notifications.enigma_dummy import DummyEnigma
from lms.notifications.errors import NotificationError
from lms.notifications.models import (
    PAYLOAD_FIELDS,
    STAFF_STATEMENT_ACTION,
    STATEMENT_READY,
    STATEMENT_READY_MESSAGE,
    EnigmaLocations,
    RegistrationView,
)
from lms.notifications.push_dummy import DummyPush
from lms.notifications.service import StatementReadyNotifications

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
START = date(2026, 3, 1)
END = date(2026, 3, 31)
WHEN = datetime(2026, 4, 1, 8, 15, tzinfo=JOHANNESBURG)
LOCATIONS = EnigmaLocations(
    registration_url="https://enigma.example/register",
    sign_on_url="https://enigma.example/sign-on",
)


class IssuedStore:
    def __init__(self, *statements: object) -> None:
        self.statements = {
            (item.organisation_id, item.person_id, item.period_start, item.period_end): item
            for item in statements
        }
        self.issue_calls = 0

    def issue_statement(self, **kwargs: object) -> object:
        self.issue_calls += 1
        raise AssertionError("the push must not generate a statement")


def loan(loan_id: str = "loan-1") -> SimpleNamespace:
    return SimpleNamespace(
        loan_id=loan_id,
        opening={"principal": 123456, "collection_costs": 654321},
        closing={"principal": 100000, "collection_costs": 654321},
        arrears_cents=654321,
        collection_levied_cents=654321,
        overdue=(("collection_costs", START, 654321),),
    )


def statement(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = dict(
        statement_id="stmt-1",
        organisation_id="org-a",
        person_id="person-a",
        period_start=START,
        period_end=END,
        ncr_registration_number="NCRCP000000",
        legal_name="North Credit (Pty) Ltd",
        loans=(loan(),),
        telephone="0210000000",
        email="secret@example.com",
        mobile="0821234567",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def enigma(*people: str) -> DummyEnigma:
    port = DummyEnigma()
    for person_id in people:
        port.set_registration(person_id, "registered")
    port.add_session("staff-session", person_id="staff-1", organisation_id="org-a")
    port.add_session(
        "call-centre",
        person_id="staff-1",
        organisation_id="org-a",
        allowed_actions=frozenset({STAFF_STATEMENT_ACTION}),
    )
    port.add_session("consumer-session", person_id="person-a")
    return port


def service(store: IssuedStore, port: DummyEnigma, push: DummyPush | None = None) -> StatementReadyNotifications:
    return StatementReadyNotifications(store, port, locations=LOCATIONS, push=push or DummyPush())


def send(notes: StatementReadyNotifications, **overrides: object):
    values: dict[str, object] = dict(
        session_ref="staff-session",
        organisation_id="org-a",
        person_id="person-a",
        period_start=START,
        period_end=END,
        request_id="req-1",
        recognised_at=WHEN,
    )
    values.update(overrides)
    return notes.send_statement_ready(**values)  # type: ignore[arg-type]


def test_push_tells_the_consumer_the_statement_is_available() -> None:
    store = IssuedStore(statement())
    port = enigma("person-a")
    push = DummyPush()
    notes = service(store, port, push)

    receipt = send(notes)

    payload = receipt.payload
    assert payload.kind == STATEMENT_READY
    assert payload.message == STATEMENT_READY_MESSAGE
    assert payload.statement_id == "stmt-1"
    assert payload.organisation_id == "org-a"
    assert payload.person_id == "person-a"
    assert payload.period_start == START
    assert payload.period_end == END
    assert payload.ncr_registration_number == "NCRCP000000"
    assert payload.legal_name == "North Credit (Pty) Ltd"
    assert payload.loan_ids == ("loan-1",)
    assert tuple(payload.as_dict()) == PAYLOAD_FIELDS
    assert push.calls == 1
    assert push.sent["stmt-1"] == payload
    assert store.issue_calls == 0
    assert "consumer_registration" in port.calls
    assert "read_live_identity" not in port.calls


def test_one_push_for_every_loan_on_one_client_statement() -> None:
    issued = statement(loans=(loan("loan-1"), loan("loan-2")))
    notes = service(IssuedStore(issued), enigma("person-a"))

    receipt = send(notes)

    assert receipt.payload.loan_ids == ("loan-1", "loan-2")
    assert notes._push.calls == 1
    encoded = json.dumps(receipt.payload.as_dict())
    assert "123456" not in encoded
    assert "654321" not in encoded
    assert "0210000000" not in encoded
    assert "secret@example.com" not in encoded
    assert "0821234567" not in encoded
    assert "collection" not in encoded
    assert "arrears" not in encoded
    assert "overdue" not in encoded


def test_successive_issued_months_each_get_one_push() -> None:
    april_start = date(2026, 4, 1)
    april_end = date(2026, 4, 30)
    march = statement()
    april = statement(statement_id="stmt-apr", period_start=april_start, period_end=april_end)
    notes = service(IssuedStore(march, april), enigma("person-a"))

    send(notes)
    send(
        notes,
        period_start=april_start,
        period_end=april_end,
        request_id="req-apr",
    )

    assert set(notes._push.sent) == {"stmt-1", "stmt-apr"}
    assert notes._push.calls == 2


def test_each_credit_provider_gets_its_own_push() -> None:
    first = statement()
    second = statement(
        statement_id="stmt-b",
        organisation_id="org-b",
        ncr_registration_number="NCRCP111",
        legal_name="Harbour Credit (Pty) Ltd",
    )
    port = enigma("person-a")
    port.add_session("staff-b", person_id="staff-b", organisation_id="org-b")
    notes = service(IssuedStore(first, second), port)

    send(notes)
    send(notes, session_ref="staff-b", organisation_id="org-b", request_id="req-b")

    assert set(notes._push.sent) == {"stmt-1", "stmt-b"}
    assert notes._push.sent["stmt-b"].ncr_registration_number == "NCRCP111"


def test_missing_statement_does_not_generate_or_push() -> None:
    store = IssuedStore()
    push = DummyPush()
    notes = service(store, enigma("person-a"), push)

    with pytest.raises(NotificationError) as exc:
        send(notes)

    assert exc.value.code == "statement-not-ready"
    assert store.issue_calls == 0
    assert push.calls == 0


def test_blank_ncr_fails_closed_and_all_zero_is_sent() -> None:
    for blank in ("", "   ", None):
        notes = service(IssuedStore(statement(ncr_registration_number=blank)), enigma("person-a"))
        with pytest.raises(NotificationError) as exc:
            send(notes)
        assert exc.value.code == "ncr-blank"
        assert notes._push.calls == 0

    notes = service(IssuedStore(statement(ncr_registration_number="  000000  ")), enigma("person-a"))
    receipt = send(notes)
    assert receipt.payload.ncr_registration_number == "000000"


def test_ncr_comes_from_the_statement_not_from_enigma() -> None:
    port = enigma("person-a")
    port.ncr_registration_number = "FROM-ENIGMA"  # type: ignore[attr-defined]
    notes = service(IssuedStore(statement()), port)

    receipt = send(notes)

    assert receipt.payload.ncr_registration_number == "NCRCP000000"
    assert "FROM-ENIGMA" not in json.dumps(receipt.payload.as_dict())


def test_unregistered_suspended_ambiguous_and_timeout_do_not_send() -> None:
    issued = statement()

    missing = service(IssuedStore(issued), enigma())
    with pytest.raises(NotificationError) as exc:
        send(missing)
    assert exc.value.code == "consumer-unregistered"
    assert missing._push.calls == 0

    suspended = enigma()
    suspended.set_registration("person-a", "suspended")
    notes = service(IssuedStore(issued), suspended)
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "enigma-suspended"

    ambiguous = enigma()
    ambiguous.set_registration("person-a", "ambiguous")
    notes = service(IssuedStore(issued), ambiguous)
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "enigma-ambiguous"

    timed_out = enigma("person-a")
    timed_out.registration_failure = "timeout"
    notes = service(IssuedStore(issued), timed_out)
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "enigma-timeout"
    assert notes._push.calls == 0


def test_actor_timeout_and_missing_session_fail_closed() -> None:
    store = IssuedStore(statement())
    port = enigma("person-a")
    port.actor_failure = "timeout"
    notes = service(store, port)
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "enigma-timeout"
    assert notes._push.calls == 0
    assert notes.audit == []

    notes = service(IssuedStore(statement()), enigma("person-a"))
    with pytest.raises(NotificationError) as exc:
        send(notes, session_ref="")
    assert exc.value.code == "reauthenticate"
    assert notes.audit == []


def test_naive_recognition_time_is_not_moved_to_midnight() -> None:
    notes = service(IssuedStore(statement()), enigma("person-a"))
    with pytest.raises(NotificationError) as exc:
        send(notes, recognised_at=datetime(2026, 4, 1, 8, 15))
    assert exc.value.code == "recognition-unset"

    when = datetime(2026, 3, 31, 22, 0, tzinfo=timezone.utc)
    notes = service(IssuedStore(statement()), enigma("person-a"))
    receipt = send(notes, recognised_at=when)
    assert receipt.recognised_at == when
    assert notes.audit[0].actor_person_id == "staff-1"
    assert notes.audit[0].person_id == "person-a"
    assert notes.audit[0].recognised_at == when


def test_replay_does_not_send_a_second_push() -> None:
    notes = service(IssuedStore(statement()), enigma("person-a"))
    first = send(notes)
    second = send(notes, request_id="req-2")
    assert first.replayed is False
    assert second.replayed is True
    assert second.payload == first.payload
    assert notes._push.calls == 1
    assert len(notes.audit) == 1


def test_live_identity_is_not_used_as_the_registration_check() -> None:
    class ActorOnly:
        def __init__(self) -> None:
            self.read = 0

        def confirm_actor(self, session_ref: str, *, request_id: str) -> str:
            return "staff-1"

        def read_live_identity(self, person_id: str, *, request_id: str) -> SimpleNamespace:
            self.read += 1
            return SimpleNamespace(person_id=person_id, email="secret@example.com", mobile="0821234567")

    port = ActorOnly()
    push = DummyPush()
    notes = StatementReadyNotifications(IssuedStore(statement()), port, push=push)
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "enigma-unbound"
    assert port.read == 0
    assert push.calls == 0
    assert "secret@example.com" not in json.dumps([record.__dict__ for record in notes.audit])


def test_registration_view_has_no_contact_fields() -> None:
    assert {item.name for item in fields(RegistrationView)} == {
        "person_id",
        "status",
        "enigma_request_id",
    }


def test_pages_redirect_to_enigma_and_do_not_collect_a_secret() -> None:
    notes = service(IssuedStore(), enigma())
    registration = notes.registration_page()
    sign_on = notes.sign_on_page()
    assert registration.status_code == 302
    assert registration.location == LOCATIONS.registration_url
    assert sign_on.location == LOCATIONS.sign_on_url
    for page in (registration, sign_on):
        assert "<form" not in page.body
        assert "password" in page.body
        assert "contact number" in page.body

    bare = StatementReadyNotifications(IssuedStore(), enigma())
    with pytest.raises(NotificationError) as exc:
        bare.registration_page()
    assert exc.value.code == "enigma-url-unset"
    with pytest.raises(NotificationError) as exc:
        bare.sign_on_page()
    assert exc.value.code == "enigma-url-unset"


def test_consumer_must_be_registered_and_signed_in() -> None:
    issued = statement()
    store = IssuedStore(issued)
    port = enigma("person-a")
    notes = service(store, port)

    seen = notes.view_as_consumer(
        session_ref="consumer-session",
        organisation_id="org-a",
        period_start=START,
        period_end=END,
        request_id="req-view",
    )
    assert seen is issued
    assert store.issue_calls == 0

    with pytest.raises(NotificationError) as exc:
        notes.view_as_consumer(
            session_ref="",
            organisation_id="org-a",
            period_start=START,
            period_end=END,
            request_id="req-view",
        )
    assert exc.value.code == "reauthenticate"

    unsigned = service(store, enigma())
    with pytest.raises(NotificationError) as exc:
        unsigned.view_as_consumer(
            session_ref="consumer-session",
            organisation_id="org-a",
            period_start=START,
            period_end=END,
            request_id="req-view",
        )
    assert exc.value.code == "consumer-unregistered"

    stranger = enigma("person-b")
    stranger.add_session("other", person_id="person-b")
    notes = service(store, stranger)
    with pytest.raises(NotificationError) as exc:
        notes.view_as_consumer(
            session_ref="other",
            organisation_id="org-a",
            period_start=START,
            period_end=END,
            request_id="req-view",
        )
    assert exc.value.code == "statement-not-ready"


def test_staff_with_the_enigma_allow_can_read_without_consumer_registration() -> None:
    issued = statement()
    store = IssuedStore(issued)
    port = enigma()
    notes = service(store, port)

    seen = notes.view_as_staff(
        session_ref="call-centre",
        organisation_id="org-a",
        person_id="person-a",
        period_start=START,
        period_end=END,
        request_id="req-staff",
    )
    assert seen is issued
    assert "consumer_registration" not in port.calls

    with pytest.raises(NotificationError) as exc:
        notes.view_as_staff(
            session_ref="staff-session",
            organisation_id="org-a",
            person_id="person-a",
            period_start=START,
            period_end=END,
            request_id="req-staff",
        )
    assert exc.value.code == "mandate-denied"

    port.actor_failure = "timeout"
    with pytest.raises(NotificationError) as exc:
        notes.view_as_staff(
            session_ref="call-centre",
            organisation_id="org-a",
            person_id="person-a",
            period_start=START,
            period_end=END,
            request_id="req-staff",
        )
    assert exc.value.code == "enigma-timeout"


def test_a_statement_with_no_loan_is_not_pushed() -> None:
    notes = service(IssuedStore(statement(loans=())), enigma("person-a"))
    with pytest.raises(NotificationError) as exc:
        send(notes)
    assert exc.value.code == "statement-empty"
    assert notes._push.calls == 0
