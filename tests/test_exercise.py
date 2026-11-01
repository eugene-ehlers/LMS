"""The test exercise uses the quote stub and the debit-file stub, and fails closed."""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request

from lms.exercise import Exercise
from lms.objects import MemoryStore
from lms_config.exceptions import CalculationInputError
from lms.runtime import build_front
from lms.staff_ui.app import Session, build_app, make_server


def elections(**overrides) -> dict:
    body = {
        "leniency_days": "1",
        "full_payment_threshold_percent": "100",
        "interest_on_deferred_initiation": "none",
        "repo_rate_fall": "contract_rate",
        "day_count_code": "actual_actual",
        "vat_on_rand_maxima": "exclusive",
        "late_disbursement": "keep_instalment",
        "partial_prepayment": "shorten_term",
        "in_duplum_trigger": "collections_default",
    }
    body.update(overrides)
    return body


def booking(**overrides) -> dict:
    body = {
        "organisation_id": "org-test",
        "person_id": "person-test-001",
        "full_name": "Test Consumer",
        "id_number": "0000000000000",
        "service_address": "1 Dummy Street, Johannesburg",
        "idempotency_key": "book-test-1",
        "product_code": "micro_short_term",
        "frequency": "monthly",
        "cash_advanced_cents": "100000",
        "due_on": "2026-06-15",
        "schedule_amount_cents": "100000",
        "recognised_at": "2026-03-01T08:00:00+02:00",
        "disbursed_at": "2026-03-01T10:00:00+02:00",
        **elections(),
    }
    body.update(overrides)
    return body


def test_a_missing_election_does_not_book() -> None:
    exercise = Exercise()
    form = booking()
    form["in_duplum_trigger"] = ""

    try:
        exercise.book(form)
    except Exception as exc:
        assert exc.code == "election-unset"
    else:
        raise AssertionError("booking continued without the in-duplum trigger")

    assert exercise.servicing.agreements == {}
    assert exercise.quotes._issued == 0


def test_quote_stub_books_and_debit_stub_takes_a_payment() -> None:
    exercise = Exercise()
    booked = exercise.book(booking())

    assert booked["application_number"] == "APP-00000001"
    assert booked["loan_number"] == "000000000001"
    assert booked["status"] == "active"
    assert booked["frozen_full_name"] == "Test Consumer"
    assert booked["frozen_id_number"] == "0000000000000"
    assert booked["credit_life_premium_cents"] == 199

    paid = exercise.pay(
        {
            "agreement_id": booked["agreement_id"],
            "amount_cents": "10000",
            "due_on": "2026-06-15",
            "recognition_date": "2026-03-20",
            "outcome": "success",
        }
    )
    assert paid["kind"] == "success"
    assert paid["payment_status"] == "allocated"
    assert paid["amount_cents"] == 10000
    assert paid["loan_number"] == "000000000001"

    failed = exercise.pay(
        {
            "agreement_id": booked["agreement_id"],
            "amount_cents": "5000",
            "due_on": "2026-06-15",
            "recognition_date": "2026-03-21",
            "outcome": "failure",
        }
    )
    assert failed["kind"] == "failure"
    assert failed["payment_id"] == ""
    assert len(exercise.servicing.payments) == 1


def test_statement_and_brand_assets_go_to_the_object_store() -> None:
    store = MemoryStore()
    exercise = Exercise(objects=store)
    booked = exercise.book(booking(idempotency_key="book-statement"))
    issued = exercise.issue_statement(
        {
            "organisation_id": booked["organisation_id"],
            "person_id": booked["person_id"],
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "interest_cap_present": "true",
            "vat_rate": "0.15",
        }
    )
    content_type, body = store.objects[issued["object_key"]]
    assert issued["object_key"].startswith("statements/org-test/")
    assert content_type == "application/json"
    assert body

    bare = Exercise()
    try:
        bare.store_brand({"organisation_id": "org-test", "asset_name": "logo", "body": "synthetic"})
    except Exception as exc:
        assert exc.code == "object-store-unset"
    else:
        raise AssertionError("a brand asset was stored without a bucket")

    stored = exercise.store_brand(
        {"organisation_id": "org-test", "asset_name": "logo.txt", "body": "synthetic brand"}
    )
    assert stored["object_key"] == "brand/org-test/logo.txt"
    assert store.objects[stored["object_key"]][1] == b"synthetic brand"


def test_interest_cap_must_be_stated() -> None:
    exercise = Exercise(objects=MemoryStore())
    booked = exercise.book(booking(idempotency_key="book-cap"))
    try:
        exercise.issue_statement(
            {
                "organisation_id": booked["organisation_id"],
                "person_id": booked["person_id"],
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "interest_cap_present": "",
            }
        )
    except Exception as exc:
        assert exc.code == "election-unset"
    else:
        raise AssertionError("a statement was issued without the cap election")
    try:
        exercise.issue_statement(
            {
                "organisation_id": booked["organisation_id"],
                "person_id": booked["person_id"],
                "period_start": "2026-04-01",
                "period_end": "2026-04-30",
                "interest_cap_present": "false",
            }
        )
    except CalculationInputError as exc:
        assert "interest cap" in str(exc)
    else:
        raise AssertionError("a statement was issued when the cap row was absent")
    assert store_empty(exercise)


def store_empty(exercise: Exercise) -> bool:
    return exercise.objects.objects == {}


def test_http_health_exercise_and_enigma_pages() -> None:
    exercise = Exercise(objects=MemoryStore())
    server = make_server(build_app(), "127.0.0.1", 0, front=build_front(exercise))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        health = urllib.request.urlopen(f"{base}/health")
        assert health.status == 200
        assert health.read() == b"ok\n"
        assert "Set-Cookie" not in health.headers

        register = urllib.request.urlopen(f"{base}/self/register")
        page = register.read().decode()
        assert "Enigma" in page
        assert 'type="email"' not in page
        assert 'type="password"' not in page
        refused = urllib.request.Request(
            f"{base}/self/register",
            data=urllib.parse.urlencode({"email": "a@example.com"}).encode(),
        )
        try:
            urllib.request.urlopen(refused)
        except urllib.error.HTTPError as exc:
            assert exc.code == 422
            assert b"does not accept" in exc.read()

        try:
            urllib.request.urlopen(f"{base}/self/settlement-quote")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("the settlement quote opened without Enigma sign-on")

        missing = urllib.request.Request(
            f"{base}/exercise/book",
            data=urllib.parse.urlencode(booking(in_duplum_trigger="")).encode(),
        )
        try:
            urllib.request.urlopen(missing)
        except urllib.error.HTTPError as exc:
            assert exc.code == 422
            body = exc.read().decode()
            assert "election-unset" in body

        booked = urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/exercise/book",
                data=urllib.parse.urlencode(booking(idempotency_key="http-book")).encode(),
            )
        )
        assert b"000000000001" in booked.read()
        agreement_id = exercise.agreements()[0]["agreement_id"]
        paid = urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/exercise/pay",
                data=urllib.parse.urlencode(
                    {
                        "agreement_id": agreement_id,
                        "amount_cents": "10000",
                        "due_on": "2026-06-15",
                        "recognition_date": "2026-03-20",
                        "outcome": "success",
                    }
                ).encode(),
            )
        )
        assert b"allocated" in paid.read()

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(
            f"{base}/staff/session",
            urllib.parse.urlencode(
                {
                    "person_id": "person-test-001",
                    "organisation_id": "org-test",
                    "roles": "",
                    "enigma_status": "active",
                }
            ).encode(),
        )
        statement = opener.open(f"{base}/self/statement")
        assert b"No stored statement is held" in statement.read()
    finally:
        server.shutdown()


def test_blank_session_is_not_a_consumer_sign_on() -> None:
    from lms.runtime import route

    exercise = Exercise()
    session = Session()
    status, _content_type, body = route(exercise, session, "GET", "/self/statement", {})
    assert status == 403
    assert b"Enigma sign-on" in body
