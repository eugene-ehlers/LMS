"""Servicing orchestration pins. Amounts come from the ledger, which calls the engine."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.ledger.errors import LedgerError
from lms.servicing.api import dispatch
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing, displayed_loan_number
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
DUE = date(2026, 6, 15)


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 3, day, hour, 0, tzinfo=JOHANNESBURG)


def settings(**overrides) -> OrganisationSettings:
    values = dict(
        leniency_days=1,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def servicing() -> Servicing:
    return Servicing(enigma=EnigmaStub())


def book(
    svc: Servicing,
    *,
    key: str = "book-1",
    person_id: str = "person-a",
    application_number: str | None = None,
    organisation_name: str = "Cape Credit",
    **overrides,
):
    payload = dict(
        organisation_id="org-a",
        person_id=person_id,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(1, 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key=key,
        application_number=key if application_number is None else application_number,
        organisation_name=organisation_name,
    )
    payload.update(overrides)
    return svc.book(**payload)


def disburse(svc: Servicing, record):
    return svc.disburse(record.agreement_id, recognised_at=at(1, 10))


def test_booking_then_disbursement_freezes_identity_and_posts_principal():
    stub = EnigmaStub()
    svc = Servicing(enigma=stub)
    pending = book(svc)
    assert pending.status == "pending_disbursement"
    assert pending.ledger_loan_id is None
    assert pending.booking_value_date == date(2026, 3, 1)
    assert pending.frozen_full_name == "Ada Borrower"
    assert svc.ledger.store.accounts_for("org-a") == ()

    stub.full_name = "Changed After Booking"
    active = disburse(svc, pending)
    assert active.status == "active"
    assert active.frozen_full_name == "Ada Borrower"
    loan = svc.ledger.store.get("org-a", active.ledger_loan_id)
    assert loan.frozen_full_name == "Ada Borrower"
    assert loan.disbursement_value_date == date(2026, 3, 1)
    assert svc.ledger.bucket_balance(loan, "principal") == 100_000
    again = svc.disburse(active.agreement_id, recognised_at=at(2, 10))
    assert again.ledger_loan_id == active.ledger_loan_id
    assert svc.ledger.bucket_balance(loan, "principal") == 100_000


def test_matched_payment_is_allocated_by_the_ledger():
    svc = servicing()
    record = disburse(svc, book(svc))
    payment = svc.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=10_000,
        recognised_at=at(20, 11),
        idempotency_key="pay-1",
        agreement_id=record.agreement_id,
        attributed_due_on=DUE,
    )
    assert payment.status == "allocated"
    assert payment.value_date == date(2026, 3, 20)
    assert payment.allocations == (("principal", 10_000),)
    loan = svc.ledger.store.get("org-a", record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "principal") == 90_000
    assert record.status == "active"


def test_unmatched_payment_stays_out_of_the_ledger_until_applied():
    svc = servicing()
    record = disburse(svc, book(svc))
    suspense = svc.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=4_000,
        recognised_at=at(4, 18),
        idempotency_key="suspense-1",
    )
    assert suspense.status == "unapplied"
    assert suspense.value_date == date(2026, 3, 4)
    assert svc.ledger.store.transactions_for("org-a", record.ledger_loan_id)[0].kind == "booking"

    applied = svc.apply_payment(suspense.payment_id, agreement_id=record.agreement_id, attributed_due_on=DUE)
    assert applied.status == "allocated"
    assert applied.value_date == date(2026, 3, 4)
    stored = svc.ledger.store.get_transaction("org-a", applied.ledger_transaction_id)
    assert stored.value_date == date(2026, 3, 4)
    assert stored.recognised_at == suspense.recognised_at


def test_reversal_uses_the_original_value_date():
    svc = servicing()
    record = disburse(svc, book(svc))
    payment = svc.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=5_000,
        recognised_at=at(1, 15),
        idempotency_key="pay-rev",
        agreement_id=record.agreement_id,
        attributed_due_on=DUE,
    )
    reversed_payment = svc.reverse_payment(payment.payment_id, recognised_at=at(10, 16))
    assert reversed_payment.reversal_value_date == date(2026, 3, 1)
    assert reversed_payment.reversal_recognised_at == at(10, 16)
    reversal = svc.ledger.store.get_transaction("org-a", reversed_payment.reversal_transaction_id)
    assert reversal.value_date == payment.value_date
    loan = svc.ledger.store.get("org-a", record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "principal") == 100_000
    assert all(
        transaction.value_date != date(2026, 3, 10)
        for transaction in svc.ledger.store.transactions_for("org-a", record.ledger_loan_id)
    )


def test_missing_election_fails_closed_and_stores_nothing():
    svc = servicing()
    with pytest.raises(ServicingError) as caught:
        book(svc, settings=settings(repo_rate_fall=None))
    assert caught.value.code == "election-unset"
    assert svc.agreements == {}
    assert svc.ledger.store.accounts_for("org-a") == ()


def test_election_snapshot_ignores_a_later_policy():
    svc = servicing()
    first = book(svc, settings=settings(leniency_days=1), key="first")
    disburse(svc, first)
    second = book(
        svc,
        settings=settings(leniency_days=4),
        key="second",
        person_id="person-b",
    )
    loan = svc.ledger.store.get("org-a", first.ledger_loan_id)
    assert loan.snapshot.leniency_days == 1
    assert first.resolved.leniency_days == 1
    assert second.resolved.leniency_days == 4
    assert second.status == "pending_disbursement"


def test_enigma_timeout_fails_closed():
    stub = EnigmaStub()
    stub.mode = "timeout"
    svc = Servicing(enigma=stub)
    with pytest.raises(ServicingError) as caught:
        book(svc)
    assert caught.value.status == 503
    assert svc.agreements == {}


def test_repeat_booking_key_returns_the_same_agreement():
    svc = servicing()
    first = book(svc, key="same")
    second = book(svc, key="same")
    assert second.agreement_id == first.agreement_id
    with pytest.raises(ServicingError) as caught:
        book(svc, key="same", cash_advanced_cents=50_000, schedule=((DUE, 50_000),))
    assert caught.value.status == 409


def test_state_machine_arrears_cure_and_settlement():
    svc = servicing()
    first_due = date(2026, 6, 15)
    second_due = date(2026, 7, 15)
    record = disburse(
        svc,
        book(
            svc,
            settings=settings(leniency_days=0),
            schedule=((first_due, 50_000), (second_due, 50_000)),
        ),
    )
    flagged = svc.morning_check(
        record.agreement_id,
        due_on=first_due,
        recognised_at=datetime(2026, 6, 15, 8, tzinfo=JOHANNESBURG),
    )
    assert flagged.status == "in_arrears"
    svc.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=50_000,
        recognised_at=datetime(2026, 6, 15, 7, tzinfo=JOHANNESBURG),
        idempotency_key="cure",
        agreement_id=record.agreement_id,
        attributed_due_on=first_due,
    )
    cured = svc.morning_check(
        record.agreement_id,
        due_on=first_due,
        recognised_at=datetime(2026, 6, 15, 9, tzinfo=JOHANNESBURG),
    )
    assert cured.status == "active"
    svc.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=50_000,
        recognised_at=datetime(2026, 7, 15, 8, tzinfo=JOHANNESBURG),
        idempotency_key="settle",
        agreement_id=record.agreement_id,
        attributed_due_on=second_due,
    )
    assert record.status == "settled"


def test_statement_is_one_document_per_client_and_organisation():
    svc = servicing()
    record = disburse(svc, book(svc))
    issued = svc.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 2),
        vat_rate=Decimal("0.15"),
        interest_cap_present=True,
    )
    assert len(issued.loans) == 1
    assert issued.loans[0]["frozen_full_name"] == "Ada Borrower"
    assert issued.pdf_stub
    again = svc.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 2),
        vat_rate=Decimal("0.15"),
        interest_cap_present=True,
    )
    assert again.statement_id == issued.statement_id
    assert again.pdf_sha256 == issued.pdf_sha256
    loan = svc.ledger.store.get("org-a", record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "service") > 0


def test_routes_book_and_reject_a_missing_election():
    svc = servicing()
    body = {
        "organisation_id": "org-a",
        "person_id": "person-a",
        "product_code": "micro_short_term",
        "recognised_at": "2026-03-01T08:00:00+02:00",
        "cash_advanced_cents": 100_000,
        "frequency": "monthly",
        "schedule": [["2026-06-15", 100_000]],
        "settings": {
            "leniency_days": 1,
            "full_payment_threshold_percent": "100",
            "interest_on_deferred_initiation": "none",
            "repo_rate_fall": "contract_rate",
            "day_count_code": "actual_actual",
            "vat_on_rand_maxima": "exclusive",
            "late_disbursement": "keep_instalment",
            "partial_prepayment": "shorten_term",
        },
        "application_number": "APP-1",
        "organisation_name": "Cape Credit",
    }
    status, payload = dispatch(svc, "POST", "/v1/agreements", body, {"Idempotency-Key": "http-1"})
    assert status == 200
    assert payload["status"] == "pending_disbursement"
    assert payload["loan_number"] == "CAPE-202603-1"
    assert payload["application_number"] == "APP-1"
    status, disbursed = dispatch(
        svc,
        "POST",
        f"/v1/agreements/{payload['agreement_id']}/disbursements",
        {"recognised_at": "2026-03-01T10:00:00+02:00"},
        {},
    )
    assert status == 200
    assert disbursed["status"] == "active"
    body["settings"]["repo_rate_fall"] = None
    status, rejected = dispatch(svc, "POST", "/v1/agreements", body, {"Idempotency-Key": "http-2"})
    assert status == 422
    assert rejected["code"] == "election-unset"
    assert [record.loan_number for record in svc.agreements.values()] == ["CAPE-202603-1"]


def test_booking_stores_a_sequential_loan_number():
    svc = servicing()
    with pytest.raises(ServicingError) as missing_application:
        book(svc, key="blank-application", application_number="  ")
    assert missing_application.value.code == "application-number-missing"
    with pytest.raises(ServicingError) as missing_name:
        book(svc, key="blank-name", organisation_name="   ")
    assert missing_name.value.code == "organisation-name-missing"
    assert svc.agreements == {}
    assert svc._loan_sequence == {}

    evening = datetime(2026, 3, 1, 18, 30, tzinfo=JOHANNESBURG)
    first = book(svc, key="one", recognised_at=evening, organisation_name="Cape Credit (Pty) Ltd")
    assert first.loan_number == "CAPE-202603-1"
    assert first.application_number == "one"
    assert isinstance(first.cash_advanced_cents, int)
    assert first.booking_value_date == date(2026, 3, 1)
    assert first.recognised_at == evening
    extract = svc.audit.extract(organisation_id="org-a", from_date=date(2026, 3, 1), to_date=date(2026, 3, 1))
    booked = [row for row in extract.rows if row.event_type == "AGREEMENT_STATUS_CHANGED"]
    assert booked[-1].payload["loan_number"] == "CAPE-202603-1"
    assert booked[-1].payload["application_number"] == "one"

    short = book(svc, key="short-name", person_id="person-short", organisation_name="AB")
    assert short.loan_number == "AB00-202603-2"
    padded = book(svc, key="one-letter", person_id="person-letter", organisation_name="Q")
    assert padded.loan_number == "Q000-202603-3"

    svc.enigma.mode = "timeout"
    with pytest.raises(ServicingError) as timed_out:
        book(svc, key="timed-out", person_id="person-b")
    assert timed_out.value.code == "enigma-timeout"
    assert svc._loan_sequence[("org-a", "202603")] == 4

    svc.enigma.mode = "active"
    second = book(svc, key="two", person_id="person-b")
    assert second.loan_number == "CAPE-202603-4"
    replay = book(svc, key="one", recognised_at=evening, organisation_name="Cape Credit (Pty) Ltd")
    assert replay.agreement_id == first.agreement_id
    assert replay.loan_number == "CAPE-202603-1"
    with pytest.raises(ServicingError) as used:
        book(svc, key="same-application", person_id="person-c", application_number="one")
    assert used.value.code == "application-number-used"
    assert svc._loan_sequence[("org-a", "202603")] == 5

    april = book(
        svc,
        key="april",
        person_id="person-april",
        recognised_at=datetime(2026, 3, 31, 23, 30, tzinfo=timezone.utc),
    )
    assert april.booking_value_date == date(2026, 4, 1)
    assert april.loan_number == "CAPE-202604-1"

    other = book(svc, key="other-org", organisation_id="org-b")
    assert other.loan_number == "CAPE-202603-1"

    svc._loan_sequence[("org-a", "202603")] = 0
    with pytest.raises(ServicingError) as missing:
        book(svc, key="missing-number", person_id="person-d")
    assert missing.value.code == "loan-number-missing"
    assert "person-d" not in {record.person_id for record in svc.agreements.values()}
    assert svc._loan_sequence[("org-a", "202603")] == 0

    wide = servicing()
    wide._loan_sequence[("org-a", "202603")] = 10**40
    stored = book(wide, key="wide")
    assert stored.loan_number == f"CAPE-202603-{10**40}"
    following = book(wide, key="wide-next", person_id="person-b")
    assert following.loan_number == f"CAPE-202603-{10**40 + 1}"

    linked = servicing()
    pair = linked.book_linked_laybye(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(1, 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        idempotency_key="laybye",
        application_number="APP-LAYBYE",
        organisation_name="Cape Credit",
    )
    assert pair.loan_number == "CAPE-202603-1"
    assert pair.application_number == "APP-LAYBYE"
    assert displayed_loan_number(pair.loan_number, laybye=True) == "CAPE-202603-1-L"
    parent = linked.ledger.store.get("org-a", pair.ledger_loan_id)
    child = linked.ledger.store.get("org-a", pair.laybye_loan_id)
    assert parent.instrument_kind == "loan"
    assert child.instrument_kind == "laybye_hold"
    assert child.parent_loan_id == parent.loan_id
    with pytest.raises(ServicingError) as second_laybye:
        linked.book_linked_laybye(
            organisation_id="org-a",
            person_id="person-a",
            product=micro_short_term(),
            settings=settings(),
            recognised_at=at(1, 8),
            cash_advanced_cents=100_000,
            frequency="monthly",
            schedule=((DUE, 100_000),),
            idempotency_key="laybye-again",
            application_number="APP-LAYBYE",
            organisation_name="Cape Credit",
        )
    assert second_laybye.value.code == "application-number-used"
    after = book(linked, key="after-laybye", person_id="person-b")
    assert after.loan_number == "CAPE-202603-2"
    assert sorted(record.loan_number for record in linked.agreements.values()) == ["CAPE-202603-1", "CAPE-202603-2"]


def test_clip_is_not_invoked():
    svc = servicing()
    with pytest.raises(LedgerError) as caught:
        svc.ledger.clip_in_duplum()
    assert caught.value.code == "in-duplum-clip-off"
