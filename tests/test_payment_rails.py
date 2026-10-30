"""Layer 3 payment rails. Calls the ledger, the calculator, and the rail dummy.

No socket is opened. Figures that the smoke test already pinned (April interest
R100, opening service fee R69) are reused. May's one day is taken from the
same daily-interest function the ledger calls.
"""

from __future__ import annotations

import http.client
import socket
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.interest import daily_interest_rands
from lms.calc.money import to_cents
from lms.payments.api import dispatch as rail_dispatch
from lms.payments.dummies import DebitOrderRailDummy, DecisionEngineDummy
from lms.payments.errors import PaymentRailError
from lms.payments.flags import DEBIT_ORDERS_ENABLED, FeatureFlags
from lms.payments.models import CollectionMandate, DebtorAccount, InboundReceipt
from lms.payments.rail import PaymentRail, instalment_outstanding_cents
from lms.servicing.api import dispatch as servicing_dispatch
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms_config.calendar import value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"
ACTOR = "staff-1"
CASH_CENTS = 200_000
ADVANCE = date(2026, 4, 1)
DUE = date(2026, 5, 1)
VAT_RATE = Decimal("0.15")
BOOKED_AT = "2026-04-01T09:15:00+02:00"
DISBURSED_AT = "2026-04-01T11:00:00+02:00"
PREMIUM_CENTS = 2_500

ELECTIONS = {
    "leniency_days": 3,
    "full_payment_threshold_percent": "100",
    "interest_on_deferred_initiation": "none",
    "repo_rate_fall": "contract_rate",
    "day_count_code": "actual_actual",
    "base_rate": "0.05",
    "discount_rate": "0",
    "vat_on_rand_maxima": "exclusive",
    "late_disbursement": "keep_instalment",
    "partial_prepayment": "shorten_term",
    "in_duplum_trigger": "contractual_breach",
}


def _refuse_http(*_args, **_kwargs):
    raise AssertionError("payment rails opened a socket")


@pytest.fixture(autouse=True)
def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _refuse_http)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _refuse_http)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _refuse_http)


def _book_and_disburse(servicing: Servicing, *, person_id: str = PERSON, key: str = "book") -> str:
    status, booked = servicing_dispatch(
        servicing,
        "POST",
        "/v1/agreements",
        {
            "organisation_id": ORG,
            "person_id": person_id,
            "product_code": "micro_short_term",
            "recognised_at": BOOKED_AT,
            "cash_advanced_cents": CASH_CENTS,
            "frequency": "monthly",
            "schedule": [[DUE.isoformat(), CASH_CENTS]],
            "initiation_fee_cents": 0,
            "settings": dict(ELECTIONS),
        },
        {"Idempotency-Key": key},
    )
    assert status == 200, booked
    status, active = servicing_dispatch(
        servicing,
        "POST",
        f"/v1/agreements/{booked['agreement_id']}/disbursements",
        {"recognised_at": DISBURSED_AT},
        {},
    )
    assert status == 200, active
    assert active["status"] == "active"
    return booked["agreement_id"]


def _compliance() -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=ORG,
        legal_name="ACME",
        ncr_registration_number="NCRCP000000",
        trading_name="",
        physical_address="1 Main Road, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0100000000",
        bank_name="First National Bank",
        bank_account_number="62011234567",
        branch_code="250655",
        payment_reference="ACME",
    )


def _debtor() -> DebtorAccount:
    return DebtorAccount("632005", "12345678901", "1", "Ada Borrower")


def _world(*, automated: bool | None = True):
    servicing = Servicing(enigma=EnigmaStub())
    engine = DecisionEngineDummy()
    dummy = DebitOrderRailDummy()
    flags = FeatureFlags()
    compliance = ComplianceStore()
    compliance.put(_compliance())
    if automated is not None:
        flags.put(ORG, DEBIT_ORDERS_ENABLED, automated)
    rail = PaymentRail(
        servicing=servicing,
        rail=dummy,
        decision_engine=engine,
        compliance=compliance,
        flags=flags,
    )
    return rail, servicing, engine, dummy


def _register(rail: PaymentRail, agreement_id: str, application: str) -> str:
    return rail.register_loan_number(
        organisation_id=ORG,
        agreement_id=agreement_id,
        application_number=application,
        recognised_at=datetime(2026, 4, 1, 12, 0, tzinfo=JOHANNESBURG),
        actor_id=ACTOR,
    )


def _mandate(scheme: str = "eft", **overrides) -> CollectionMandate:
    values = dict(scheme=scheme, debtor=_debtor(), mandate_reference=None, tracking_indicator=None)
    values.update(overrides)
    return CollectionMandate(**values)


def _may_interest() -> int:
    april = daily_interest_rands(CASH_CENTS, Decimal("0.05"), 30)
    may = daily_interest_rands(CASH_CENTS, Decimal("0.05"), 31)
    return to_cents(april * 30 + may)


def test_loan_numbers_are_sequential_and_are_not_skipped():
    rail, servicing, _engine, _dummy = _world()
    first = _book_and_disburse(servicing, key="a")
    second = _book_and_disburse(servicing, person_id="person-b", key="b")
    number_a = _register(rail, first, "app-a")
    again = _register(rail, first, "app-a")
    number_b = _register(rail, second, "app-b")
    assert number_a == again == "000000000001"
    assert number_b == "000000000002"
    with pytest.raises(PaymentRailError, match="application number"):
        rail.register_loan_number(
            organisation_id=ORG,
            agreement_id=first,
            application_number="  ",
            recognised_at=datetime(2026, 4, 1, 12, 0, tzinfo=JOHANNESBURG),
            actor_id=ACTOR,
        )


def test_debit_order_file_splits_the_premium_and_uses_bankserv_layout():
    rail, servicing, engine, dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_number = _register(rail, agreement_id, "app-a")
    rail.put_mandate(agreement_id, _mandate())
    engine.premiums[(ORG, "app-a", DUE)] = PREMIUM_CENTS
    status, payload = rail_dispatch(
        rail,
        "POST",
        "/v1/payment-rails/debit-orders",
        {
            "organisation_id": ORG,
            "due_on": DUE.isoformat(),
            "recognised_at": "2026-05-01T08:00:00+02:00",
            "actor_id": ACTOR,
            "agreement_ids": [agreement_id],
            "interest_cap_present": True,
            "vat_rate": str(VAT_RATE),
        },
        {"Idempotency-Key": "file-1"},
    )
    assert status == 200, payload
    assert len(dummy.submitted) == 1
    assert len(engine.calls) == 1
    instructions = payload["instructions"]
    assert [item["purpose"] for item in instructions] == ["loan_instalment", "credit_life_premium"]
    assert all(item["loan_number"] == loan_number for item in instructions)
    assert all(item["due_on"] == "2026-05-01" for item in instructions)
    assert all(item["recognition_date"] == "2026-05-01" for item in instructions)
    assert all(item["credit_life_premium_cents"] == PREMIUM_CENTS for item in instructions)
    assert all(type(item["amount_cents"]) is int for item in instructions)
    loan_line, premium_line = instructions
    assert premium_line["amount_cents"] == PREMIUM_CENTS
    assert loan_line["amount_cents"] == _may_interest() + 6_900 + 6_900 + CASH_CENTS
    assert premium_line["amount_cents"] not in {loan_line["amount_cents"]}

    body = payload["body"]
    lines = body.split("\r\n")
    assert lines[-1] == ""
    records = lines[:-1]
    assert [record[:2] for record in records] == ["02", "04", "50", "50", "52", "92", "94"]
    assert all(len(record) == 180 for record in records)
    loan_txn, premium_txn = records[2], records[3]
    assert loan_txn[47:58] == f"{loan_line['amount_cents']:011d}"
    assert premium_txn[47:58] == f"{PREMIUM_CENTS:011d}"
    assert loan_txn[80:100] == loan_number + "  DO-LN "
    assert premium_txn[80:100] == loan_number + "  DO-CL "
    assert loan_txn[58:70] == "000000000000"
    assert records[4][58:64] == "260501"
    homing = 12345678901
    assert records[5][72:84] == f"{(homing * 2) % 10**12:012d}"

    status, replay = rail_dispatch(
        rail,
        "POST",
        "/v1/payment-rails/debit-orders",
        {
            "organisation_id": ORG,
            "due_on": DUE.isoformat(),
            "recognised_at": "2026-05-01T08:00:00+02:00",
            "actor_id": ACTOR,
            "agreement_ids": [agreement_id],
            "interest_cap_present": True,
            "vat_rate": str(VAT_RATE),
        },
        {"Idempotency-Key": "file-1"},
    )
    assert status == 200, replay
    assert len(dummy.submitted) == 1
    assert len(engine.calls) == 1


def test_debicheck_uses_the_mandate_reference_and_does_not_invent_tracking():
    rail, servicing, engine, dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    _register(rail, agreement_id, "app-a")
    engine.premiums[(ORG, "app-a", DUE)] = PREMIUM_CENTS
    rail.put_mandate(
        agreement_id,
        _mandate(scheme="debicheck", mandate_reference="MANDATE1234567", tracking_indicator=4),
    )
    produced = rail.generate_debit_order_file(
        organisation_id=ORG,
        due_on=DUE,
        recognised_at=datetime(2026, 5, 1, 8, 0, tzinfo=JOHANNESBURG),
        actor_id=ACTOR,
        agreement_ids=(agreement_id,),
        idempotency_key="dc-1",
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    records = [line for line in produced.body.split("\r\n") if line.startswith("50")]
    assert records[0][80:100] == "MANDATE1234567DC-LN "
    assert records[1][80:100] == "MANDATE1234567DC-CL "
    assert produced.instructions[0].tracking_indicator == 4
    assert "55" not in {line[:2] for line in produced.body.split("\r\n") if line}
    rail.put_mandate(agreement_id, _mandate(scheme="debicheck", mandate_reference="MANDATE1234567"))
    with pytest.raises(PaymentRailError, match="tracking"):
        rail.generate_debit_order_file(
            organisation_id=ORG,
            due_on=DUE,
            recognised_at=datetime(2026, 5, 1, 9, 0, tzinfo=JOHANNESBURG),
            actor_id=ACTOR,
            agreement_ids=(agreement_id,),
            idempotency_key="dc-2",
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    assert len(dummy.submitted) == 1


def test_missing_election_or_premium_fails_closed_and_submits_nothing():
    rail, servicing, engine, dummy = _world(automated=None)
    agreement_id = _book_and_disburse(servicing)
    _register(rail, agreement_id, "app-a")
    rail.put_mandate(agreement_id, _mandate())
    with pytest.raises(PaymentRailError, match="debit_orders_enabled") as missing:
        rail.generate_debit_order_file(
            organisation_id=ORG,
            due_on=DUE,
            recognised_at=datetime(2026, 5, 1, 8, 0, tzinfo=JOHANNESBURG),
            actor_id=ACTOR,
            agreement_ids=(agreement_id,),
            idempotency_key="missing-flag",
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    assert missing.value.code == "election-unset"
    assert engine.calls == []
    assert dummy.submitted == []

    rail.flags.put(ORG, DEBIT_ORDERS_ENABLED, False)
    with pytest.raises(PaymentRailError, match="debit_orders_enabled is false") as off:
        rail.generate_debit_order_file(
            organisation_id=ORG,
            due_on=DUE,
            recognised_at=datetime(2026, 5, 1, 8, 0, tzinfo=JOHANNESBURG),
            actor_id=ACTOR,
            agreement_ids=(agreement_id,),
            idempotency_key="flag-off",
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    assert off.value.code == "not-automated"
    assert engine.calls == []

    rail.flags.put(ORG, DEBIT_ORDERS_ENABLED, True)
    with pytest.raises(PaymentRailError, match="premium") as premium:
        rail.generate_debit_order_file(
            organisation_id=ORG,
            due_on=DUE,
            recognised_at=datetime(2026, 5, 1, 8, 0, tzinfo=JOHANNESBURG),
            actor_id=ACTOR,
            agreement_ids=(agreement_id,),
            idempotency_key="no-premium",
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    assert premium.value.code == "premium-unknown"
    assert len(engine.calls) == 1
    assert dummy.submitted == []


def test_capitalise_then_allocate_uses_section_126_and_same_day_order():
    rail, servicing, _engine, _dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_number = _register(rail, agreement_id, "app-a")
    interest = _may_interest()
    assert interest == 10_323
    recognised = datetime(2026, 5, 1, 10, 0, tzinfo=JOHANNESBURG)
    first, second = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=interest,
                recognised_at=recognised,
                loan_number=loan_number,
                attributed_due_on=DUE,
                idempotency_key="interest",
            ),
            InboundReceipt(
                amount_cents=6_900 + 6_900 + 5_000,
                recognised_at=datetime(2026, 5, 1, 10, 5, tzinfo=JOHANNESBURG),
                loan_number=loan_number,
                attributed_due_on=DUE,
                idempotency_key="rest",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    assert first.value_date == DUE
    assert first.allocations == (("interest", interest),)
    assert second.allocations == (("service", 13_800), ("principal", 5_000))
    loan = servicing.ledger.store.get(ORG, servicing.agreements[agreement_id].ledger_loan_id)
    assert servicing.ledger.bucket_balance(loan, "interest") == 0
    assert servicing.ledger.bucket_balance(loan, "service") == 0
    assert servicing.ledger.bucket_balance(loan, "principal") == CASH_CENTS - 5_000
    transactions = servicing.ledger.store.transactions_for(ORG, loan.loan_id)
    may_accrual = next(
        item for item in transactions if item.kind == "interest_accrual" and item.value_date == DUE
    )
    payment = servicing.ledger.store.get_transaction(ORG, first.ledger_transaction_id)
    assert may_accrual.memo_rands == daily_interest_rands(CASH_CENTS, Decimal("0.05"), 31)
    assert may_accrual.recognition_sequence < payment.recognition_sequence
    assert first.sequence < second.sequence
    assert all(type(cents) is int for _bucket, cents in first.allocations + second.allocations)


def test_fee_buckets_keep_the_ledger_order_including_earliest_due_date():
    rail, servicing, _engine, _dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_number = _register(rail, agreement_id, "app-a")
    loan_id = servicing.agreements[agreement_id].ledger_loan_id
    later = date(2026, 4, 12)
    earlier = date(2026, 4, 10)
    servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan_id,
        bucket="collection_costs",
        cents=200,
        due_on=later,
        recognised_at=value_instant(later),
        interest_cap_present=True,
        tariff_cents=200,
    )
    servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan_id,
        bucket="collection_costs",
        cents=100,
        due_on=earlier,
        recognised_at=value_instant(earlier),
        interest_cap_present=True,
        tariff_cents=100,
    )
    servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan_id,
        bucket="default_administration",
        cents=80,
        due_on=earlier,
        recognised_at=value_instant(earlier),
        interest_cap_present=True,
        tariff_cents=80,
    )
    servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan_id,
        bucket="credit_insurance",
        cents=70,
        due_on=earlier,
        recognised_at=value_instant(earlier),
        interest_cap_present=True,
        tariff_cents=None,
    )
    paid = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=150,
                recognised_at=datetime(2026, 4, 15, 9, 0, tzinfo=JOHANNESBURG),
                loan_number=loan_number,
                attributed_due_on=earlier,
                idempotency_key="fees",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    assert paid.allocations == (("collection_costs", 150),)
    loan = servicing.ledger.store.get(ORG, loan_id)
    by_due = {charge.due_on: charge.remaining_cents for charge in loan.charges if charge.bucket == "collection_costs"}
    assert by_due == {earlier: 0, later: 150}
    untouched = {charge.bucket: charge.remaining_cents for charge in loan.charges if charge.bucket != "collection_costs"}
    assert untouched == {"default_administration": 80, "credit_insurance": 70}
    assert servicing.ledger.bucket_balance(loan, "principal") == CASH_CENTS


def test_unmatched_receipt_matches_on_loan_number_or_id_number():
    rail, servicing, _engine, _dummy = _world()
    first = _book_and_disburse(servicing, key="a")
    second = _book_and_disburse(servicing, person_id="person-b", key="b")
    number = _register(rail, first, "app-a")
    _register(rail, second, "app-b")
    held = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=1_000,
                recognised_at=datetime(2026, 4, 30, 22, 30, tzinfo=ZoneInfo("UTC")),
                idempotency_key="held",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    assert held.status == "unapplied"
    assert held.value_date == DUE
    assert held.ledger_transaction_id is None
    still = rail.match_receipt(
        held.receipt_id,
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
        id_number="8001015800085",
        attributed_due_on=DUE,
    )
    assert still.status == "unapplied"
    matched = rail.match_receipt(
        held.receipt_id,
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
        loan_number=number,
        attributed_due_on=DUE,
    )
    assert matched.status == "allocated"
    assert matched.agreement_id == first
    assert matched.value_date == DUE
    servicing.enigma.id_number = "9001015800086"
    third = _book_and_disburse(servicing, person_id="person-c", key="c")
    by_id = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=400,
                recognised_at=datetime(2026, 4, 15, 9, 0, tzinfo=JOHANNESBURG),
                idempotency_key="by-id",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    found = rail.match_receipt(
        by_id.receipt_id,
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
        id_number="9001015800086",
        attributed_due_on=date(2026, 4, 15),
    )
    assert found.status == "allocated"
    assert found.agreement_id == third


def test_returned_unpaid_after_write_off_is_flagged_only():
    rail, servicing, _engine, _dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_number = _register(rail, agreement_id, "app-a")
    loan_id = servicing.agreements[agreement_id].ledger_loan_id
    recognised = datetime(2026, 5, 1, 11, 0, tzinfo=JOHANNESBURG)
    paid = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=_may_interest(),
                recognised_at=recognised,
                agreement_id=agreement_id,
                attributed_due_on=DUE,
                idempotency_key="pay",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    assert paid.status == "allocated"
    before = servicing.ledger.write_off_outstanding(
        organisation_id=ORG,
        loan_id=loan_id,
        recognised_at=datetime(2026, 5, 2, 9, 0, tzinfo=JOHANNESBURG),
    )
    servicing.agreements[agreement_id].status = "written_off"
    loan = servicing.ledger.store.get(ORG, loan_id)
    assert servicing.ledger.bucket_balance(loan, "principal") == 0
    returned = rail.return_unpaid(
        paid.receipt_id,
        recognised_at=datetime(2026, 5, 3, 9, 0, tzinfo=JOHANNESBURG),
        actor_id=ACTOR,
    )
    assert returned.status == "returned_flagged"
    assert returned.flag == "returned_unpaid_after_write_off"
    kinds = [item.kind for item in servicing.ledger.store.transactions_for(ORG, loan_id)]
    assert "reversal" not in kinds
    assert kinds.count("write_off") == 1
    assert before.transaction_id
    assert servicing.ledger.bucket_balance(loan, "principal") == 0
    assert servicing.ledger.bucket_balance(loan, "interest") == 0
    fresh = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=500,
                recognised_at=datetime(2026, 5, 4, 9, 0, tzinfo=JOHANNESBURG),
                loan_number=loan_number,
                attributed_due_on=DUE,
                idempotency_key="after",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    assert fresh.status == "not_posted"
    assert fresh.flag == "recovery_outside_lms"
    assert "reversal" not in [item.kind for item in servicing.ledger.store.transactions_for(ORG, loan_id)]


def test_returned_unpaid_before_write_off_reopens_and_is_flagged():
    rail, servicing, _engine, _dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_id = servicing.agreements[agreement_id].ledger_loan_id
    paid = rail.accept_receipts(
        ORG,
        (
            InboundReceipt(
                amount_cents=_may_interest(),
                recognised_at=datetime(2026, 5, 1, 11, 0, tzinfo=JOHANNESBURG),
                agreement_id=agreement_id,
                attributed_due_on=DUE,
                idempotency_key="pay",
            ),
        ),
        actor_id=ACTOR,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )[0]
    loan = servicing.ledger.store.get(ORG, loan_id)
    assert servicing.ledger.bucket_balance(loan, "interest") == 0
    returned = rail.return_unpaid(
        paid.receipt_id,
        recognised_at=datetime(2026, 5, 2, 9, 0, tzinfo=JOHANNESBURG),
        actor_id=ACTOR,
    )
    assert returned.status == "reversed"
    assert returned.flag == "write_off_approval_required"
    assert servicing.ledger.bucket_balance(loan, "interest") == _may_interest()
    assert any(item.kind == "reversal" for item in servicing.ledger.store.transactions_for(ORG, loan_id))
    assert not any(item.kind == "write_off" for item in servicing.ledger.store.transactions_for(ORG, loan_id))


def test_credit_life_receipt_is_not_posted_to_the_loan():
    rail, servicing, _engine, dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    loan_number = _register(rail, agreement_id, "app-a")
    loan_id = servicing.agreements[agreement_id].ledger_loan_id
    dummy.queue_receipt(
        InboundReceipt(
            amount_cents=PREMIUM_CENTS,
            recognised_at=datetime(2026, 5, 1, 7, 0, tzinfo=JOHANNESBURG),
            purpose="credit_life_premium",
            loan_number=loan_number,
            idempotency_key="premium",
        )
    )
    status, payload = rail_dispatch(
        rail,
        "POST",
        "/v1/payment-rails/receipts/intake",
        {
            "organisation_id": ORG,
            "actor_id": ACTOR,
            "interest_cap_present": True,
            "vat_rate": str(VAT_RATE),
        },
        {},
    )
    assert status == 200, payload
    receipt = payload["receipts"][0]
    assert receipt["status"] == "insurer_accepted"
    assert receipt["ledger_transaction_id"] is None
    assert receipt["amount_cents"] == PREMIUM_CENTS
    loan = servicing.ledger.store.get(ORG, loan_id)
    assert servicing.ledger.bucket_balance(loan, "principal") == CASH_CENTS
    assert not any(item.kind == "payment" for item in servicing.ledger.store.transactions_for(ORG, loan_id))


def test_naive_timestamp_and_missing_due_date_fail_closed():
    rail, servicing, _engine, _dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    with pytest.raises(PaymentRailError, match="timezone-aware"):
        rail.accept_receipts(
            ORG,
            (
                InboundReceipt(
                    amount_cents=100,
                    recognised_at=datetime(2026, 5, 1, 10, 0),
                    agreement_id=agreement_id,
                    attributed_due_on=DUE,
                    idempotency_key="naive",
                ),
            ),
            actor_id=ACTOR,
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    with pytest.raises(PaymentRailError, match="due date"):
        rail.accept_receipts(
            ORG,
            (
                InboundReceipt(
                    amount_cents=100,
                    recognised_at=datetime(2026, 5, 1, 10, 0, tzinfo=JOHANNESBURG),
                    agreement_id=agreement_id,
                    idempotency_key="no-due",
                ),
            ),
            actor_id=ACTOR,
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )


def test_instalment_read_does_not_invent_unbilled_interest():
    rail, servicing, engine, dummy = _world()
    agreement_id = _book_and_disburse(servicing)
    _register(rail, agreement_id, "app-a")
    rail.put_mandate(agreement_id, _mandate())
    engine.premiums[(ORG, "app-a", DUE)] = PREMIUM_CENTS
    produced = rail.generate_debit_order_file(
        organisation_id=ORG,
        due_on=DUE,
        recognised_at=datetime(2026, 4, 20, 8, 0, tzinfo=JOHANNESBURG),
        actor_id=ACTOR,
        agreement_ids=(agreement_id,),
        idempotency_key="early",
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    loan = servicing.ledger.store.get(ORG, servicing.agreements[agreement_id].ledger_loan_id)
    assert instalment_outstanding_cents(loan, DUE) == CASH_CENTS
    assert produced.instructions[0].amount_cents == CASH_CENTS
    assert not any(item.kind == "interest_bill" for item in servicing.ledger.store.transactions_for(ORG, loan.loan_id))
    assert len(dummy.submitted) == 1
