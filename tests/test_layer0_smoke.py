"""Layer 0 integration smoke. No production behaviour is added here.

The path uses the servicing API on top of the calculation engine, the
configuration layer, and the ledger. Identity comes back from
``lms.servicing.enigma.EnigmaStub``. That stub is the success return on
this path. It does not open a socket. Servicing does not call the Enigma
HTTP port from PR #1.

Contract supplied for this run, not taken from a platform default:

- short-term cash R2 000 (200 000 cents)
- value date 2026-04-01, one instalment due 2026-05-01 (30 days later)
- periodic rate 5% per month, campaign discount 0
- day count actual/actual
- initiation fee R0, sent explicitly (a zero fee is allowed)
- frequency ``monthly``, because §14 has no 30-day frequency and servicing
  does not build a schedule

Leniency is 3 calendar days and the full-payment threshold is 100 percent.
Those are this caller's elections. The examples in LOCKED_DECISIONS §6 are
not defaults and are not used here.

The VAT rate 15% and ``interest_cap_present=True`` are statement inputs.
Neither is a stored election. Omitting either fails closed.

The smoke order follows the 28 October allocation update on main
(1435869): capitalise April first, then take the 1 May receipt, then
issue the 1 May statement. Capitalisation and payment are different
days, which that update allows. This file does not change a locked rule.
"""

from __future__ import annotations

import http.client
import socket
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.fees import opening_service_fraction, service_fee_cents
from lms.calc.interest import interest_for_dates
from lms.calc.models import Agreement, DayCount, FeeCapBasis, Product, VatRate
from lms.calc.money import to_cents
from lms.servicing.api import dispatch
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"
CASH_CENTS = 200_000
PRINCIPAL_PART_CENTS = 5_000
ADVANCE = date(2026, 4, 1)
DUE = date(2026, 5, 1)
APRIL_END = date(2026, 4, 30)
VAT_RATE = Decimal("0.15")
BOOKED_AT = "2026-04-01T09:15:00+02:00"
DISBURSED_AT = "2026-04-01T11:00:00+02:00"
PAID_AT = "2026-05-01T10:00:00+02:00"

# Elections this caller sets. Names match OrganisationSettings.
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

# §19 stores these on the organisation. The short-term template does not
# fill them, so a null on the request fails closed.
ORGANISATION_ELECTIONS = (
    "leniency_days",
    "full_payment_threshold_percent",
    "interest_on_deferred_initiation",
    "repo_rate_fall",
    "vat_on_rand_maxima",
    "late_disbursement",
    "partial_prepayment",
    "in_duplum_trigger",
)


class CountingStub(EnigmaStub):
    """Same success stub. Records each check so the test can see that it ran."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, str]] = []

    def check(self, organisation_id: str, person_id: str, mandate: str):
        self.calls.append((organisation_id, person_id, mandate))
        return super().check(organisation_id, person_id, mandate)


def _refuse_http(*_args, **_kwargs):
    raise AssertionError("Layer 0 smoke: an HTTP call was made. The Enigma stub must not call out.")


def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _refuse_http)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _refuse_http)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _refuse_http)


def _rands(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    amount = abs(cents)
    return f"{sign}R{amount // 100}.{amount % 100:02d} ({amount} cents)"


def _engine_april_interest() -> int:
    """Interest on a constant R2 000 for 1–30 April 2026 at 5% actual/actual."""
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id=ORG,
        consumer_party_id=PERSON,
        product_enrolment_id="enr-1",
        cash_advanced_cents=CASH_CENTS,
        advance_date=ADVANCE,
        maturity_date=DUE,
        agreed_monthly_rate=Decimal("0.05"),
    )
    accrued = interest_for_dates(
        base_cents=CASH_CENTS,
        agreement=agreement,
        start=ADVANCE,
        end=APRIL_END,
        day_count=DayCount.ACTUAL,
    )
    return to_cents(accrued)


def _engine_service_fee() -> tuple[int, int, int]:
    """Opening-month service fee. April has 30 days and the window is 30/30."""
    fraction = opening_service_fraction(ADVANCE, DUE)
    return service_fee_cents(
        on=ADVANCE,
        period_start=ADVANCE,
        period_end=ADVANCE,
        monthly_cap_cents=6_000,
        full_month=False,
        fraction=fraction,
        vat_rates=(VatRate(date(2026, 1, 1), VAT_RATE),),
        basis=FeeCapBasis.EXCLUSIVE,
    )


def _body(**overrides) -> dict:
    settings = dict(ELECTIONS)
    settings.update(overrides.pop("settings", {}))
    payload = {
        "organisation_id": ORG,
        "person_id": PERSON,
        "product_code": "micro_short_term",
        "recognised_at": BOOKED_AT,
        "cash_advanced_cents": CASH_CENTS,
        "frequency": "monthly",
        "schedule": [[DUE.isoformat(), CASH_CENTS]],
        "initiation_fee_cents": 0,
        "settings": settings,
    }
    payload.update(overrides)
    return payload


def _ok(status: int, payload: dict, what: str) -> dict:
    if status != 200:
        raise AssertionError(f"{what} returned {status}: {payload}")
    return payload


def _book(svc: Servicing, *, key: str = "book-smoke", **overrides) -> dict:
    status, payload = dispatch(svc, "POST", "/v1/agreements", _body(**overrides), {"Idempotency-Key": key})
    return _ok(status, payload, "booking")


def _disburse(svc: Servicing, agreement_id: str) -> dict:
    status, payload = dispatch(
        svc,
        "POST",
        f"/v1/agreements/{agreement_id}/disbursements",
        {"recognised_at": DISBURSED_AT},
        {},
    )
    return _ok(status, payload, "disbursement")


def _pay(svc: Servicing, agreement_id: str, cents: int, *, key: str) -> dict:
    status, payload = dispatch(
        svc,
        "POST",
        "/v1/payments",
        {
            "organisation_id": ORG,
            "person_id": PERSON,
            "cents": cents,
            "recognised_at": PAID_AT,
            "agreement_id": agreement_id,
            "attributed_due_on": DUE.isoformat(),
        },
        {"Idempotency-Key": key},
    )
    return _ok(status, payload, "payment")


def _statement(svc: Servicing, start: date, end: date, **extra) -> dict:
    body = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "vat_rate": str(VAT_RATE),
        "interest_cap_present": True,
    }
    body.update(extra)
    status, payload = dispatch(
        svc,
        "POST",
        f"/v1/organisations/{ORG}/clients/{PERSON}/statements",
        body,
        {},
    )
    return _ok(status, payload, f"statement {start.isoformat()} to {end.isoformat()}")


def _loan(svc: Servicing, ledger_loan_id: str):
    return svc.ledger.store.get(ORG, ledger_loan_id)


def _assert_integer_cents(svc: Servicing, ledger_loan_id: str, *payloads: dict) -> None:
    loan = _loan(svc, ledger_loan_id)
    for name in ("principal", "interest", "service", "initiation", "laybye_hold"):
        balance = svc.ledger.bucket_balance(loan, name)
        assert type(balance) is int, name
    for transaction in svc.ledger.store.transactions_for(ORG, ledger_loan_id):
        if transaction.amount_cents is not None:
            assert type(transaction.amount_cents) is int
        for entry in transaction.entries:
            assert type(entry.debit_cents) is int
            assert type(entry.credit_cents) is int
    for charge in loan.charges:
        assert type(charge.remaining_cents) is int
        assert type(charge.ex_vat_cents) is int
        assert type(charge.vat_cents) is int
    for payload in payloads:
        for row in payload.get("allocations", ()):
            assert type(row["cents"]) is int
        for line in payload.get("loans", ()):
            for side in ("opening", "closing"):
                for bucket, amount in line[side].items():
                    assert type(amount) is int, (side, bucket)


def _book_disburse(svc: Servicing, stub: CountingStub) -> tuple[dict, dict]:
    booked = _book(svc)
    assert booked["status"] == "pending_disbursement"
    assert booked["ledger_loan_id"] is None
    assert booked["booking_value_date"] == ADVANCE.isoformat()
    assert svc.ledger.store.accounts_for(ORG) == ()
    record = svc.agreements[booked["agreement_id"]]
    assert record.frozen_full_name == "Ada Borrower"
    assert record.frozen_id_number == "8001015800085"
    assert record.frozen_service_address == "1 Main Road, Cape Town"
    resolved = record.resolved
    assert resolved.leniency_days == 3
    assert resolved.full_payment_threshold_percent == Decimal("100")
    assert resolved.interest_on_deferred_initiation == "none"
    assert resolved.repo_rate_fall == "contract_rate"
    assert resolved.day_count_code == "actual_actual"
    assert resolved.base_rate == Decimal("0.05")
    assert resolved.discount_rate == Decimal("0")
    assert resolved.vat_on_rand_maxima == "exclusive"
    assert resolved.late_disbursement == "keep_instalment"
    assert resolved.partial_prepayment == "shorten_term"
    assert booked["annual_equivalent_rate"] == "0.60"
    assert record.initiation_fee_cents == 0
    assert record.product.initiation_capitalised is False

    stub.full_name = "Changed After Booking"
    stub.id_number = "0000000000000"
    stub.service_address = "9 Other Road, Johannesburg"
    active = _disburse(svc, booked["agreement_id"])
    assert active["status"] == "active"
    assert active["disbursement_value_date"] == ADVANCE.isoformat()
    assert active["frozen_full_name"] == "Ada Borrower"
    assert active["frozen_id_number"] == "8001015800085"
    assert active["frozen_service_address"] == "1 Main Road, Cape Town"
    loan = _loan(svc, active["ledger_loan_id"])
    assert loan.frozen_full_name == "Ada Borrower"
    assert loan.frozen_id_number == "8001015800085"
    assert loan.frozen_service_address == "1 Main Road, Cape Town"
    assert svc.ledger.bucket_balance(loan, "principal") == CASH_CENTS
    assert loan.snapshot.base_rate == Decimal("0.05")
    assert loan.snapshot.discount_rate == Decimal("0")
    assert loan.snapshot.day_count_code == "actual_actual"
    assert loan.snapshot.leniency_days == 3
    assert loan.snapshot.initiation_capitalised is False
    assert loan.cash_advanced_cents == CASH_CENTS
    assert loan.contractual_end == DUE
    return booked, active


def test_layer0_smoke_april_statement_then_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Book, disburse, capitalise April, take R219 on 1 May, then state 1 May.

    April interest on a constant R2 000 is R100.00. The opening service fee
    is a full R60 plus R9 VAT because the §9 fraction for 1 April to 1 May
    is 30/30. The receipt is those two amounts plus R50 of principal.
    """
    _block_http(monkeypatch)
    interest = _engine_april_interest()
    ex_vat, vat, fee_total = _engine_service_fee()
    assert opening_service_fraction(ADVANCE, DUE) == Decimal(1)
    assert interest == 10_000
    assert (ex_vat, vat, fee_total) == (6_000, 900, 6_900)
    receipt = interest + fee_total + PRINCIPAL_PART_CENTS
    assert receipt == 21_900

    stub = CountingStub()
    svc = Servicing(enigma=stub)
    booked, active = _book_disburse(svc, stub)
    later = _book(
        svc,
        key="later-policy",
        person_id="person-b",
        settings={"leniency_days": 9},
    )
    assert later["leniency_days"] == 9
    loan = _loan(svc, active["ledger_loan_id"])
    assert loan.snapshot.leniency_days == 3
    assert loan.snapshot.base_rate == Decimal("0.05")
    assert svc.agreements[booked["agreement_id"]].resolved.leniency_days == 3

    april = _statement(svc, ADVANCE, APRIL_END)
    april_line = april["loans"][0]
    assert april_line["opening"] == {"principal": 0, "interest": 0, "laybye_hold": 0}
    assert april_line["closing"] == {"principal": 200_000, "interest": 10_000, "laybye_hold": 0}
    assert svc.ledger.bucket_balance(loan, "principal") == 200_000
    assert svc.ledger.bucket_balance(loan, "interest") == 10_000
    assert svc.ledger.bucket_balance(loan, "service") == 6_900
    april_memos = [
        transaction.memo_rands
        for transaction in svc.ledger.store.transactions_for(ORG, active["ledger_loan_id"])
        if transaction.kind == "interest_accrual"
        and ADVANCE <= transaction.value_date <= APRIL_END
        and transaction.memo_rands is not None
    ]
    assert len(april_memos) == 30
    assert to_cents(sum(april_memos, Decimal(0))) == 10_000
    service_charges = [charge for charge in loan.charges if charge.bucket == "service"]
    interest_charges = [charge for charge in loan.charges if charge.bucket == "interest"]
    assert [(charge.ex_vat_cents, charge.vat_cents, charge.remaining_cents) for charge in service_charges] == [
        (6_000, 900, 6_900)
    ]
    assert [(charge.remaining_cents, charge.due_on) for charge in interest_charges] == [(10_000, APRIL_END)]
    assert all(charge.ex_vat_cents <= 6_000 for charge in service_charges)

    payment = _pay(svc, booked["agreement_id"], receipt, key="pay-smoke")
    assert payment["status"] == "allocated"
    assert payment["value_date"] == DUE.isoformat()
    assert payment["allocations"] == [
        {"bucket": "interest", "cents": 10_000},
        {"bucket": "service", "cents": 6_900},
        {"bucket": "principal", "cents": 5_000},
    ]
    assert svc.ledger.bucket_balance(loan, "interest") == 0
    assert svc.ledger.bucket_balance(loan, "service") == 0
    assert svc.ledger.bucket_balance(loan, "principal") == 195_000

    may = _statement(svc, DUE, DUE)
    may_line = may["loans"][0]
    assert may_line["opening"] == april_line["closing"]
    _assert_integer_cents(svc, active["ledger_loan_id"], payment, april, may)
    assert "lms.enigma.client" not in sys.modules
    assert "lms.enigma" not in sys.modules
    assert [call[2] for call in stub.calls] == [
        "agreement.book",
        "disbursement.confirm",
        "agreement.book",
        "statement.issue",
        "payment.accept",
        "statement.issue",
    ]
    assert all(transaction.kind != "write_off" for transaction in svc.ledger.store.transactions_for(ORG, loan.loan_id))


def test_same_day_capitalisation_is_not_applied_before_the_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise the 28 October same-day order. Do not treat the current posting order as the rule.

    Main 1435869 says that on a calendar day, capitalisation at 00:00 comes
    before payments recognised that day. The same section still says to
    process same-day events in recognition order. The ledger follows
    recognition order. The 1 May statement, posted after the receipt, accrues
    1 May on the reduced principal and levies a second service fee.
    """
    _block_http(monkeypatch)
    stub = CountingStub()
    svc = Servicing(enigma=stub)
    booked, active = _book_disburse(svc, stub)
    _statement(svc, ADVANCE, APRIL_END)
    payment = _pay(svc, booked["agreement_id"], 21_900, key="pay-same-day")
    may = _statement(svc, DUE, DUE)
    loan = _loan(svc, active["ledger_loan_id"])
    payment_tx = svc.ledger.store.get_transaction(ORG, payment["ledger_transaction_id"])
    may_accruals = [
        transaction
        for transaction in svc.ledger.store.transactions_for(ORG, loan.loan_id)
        if transaction.kind == "interest_accrual" and transaction.value_date == DUE
    ]
    assert may["loans"][0]["closing"]["interest"] == 315
    assert svc.ledger.bucket_balance(loan, "service") == 6_900
    assert may_accruals
    assert all(transaction.recognition_sequence > payment_tx.recognition_sequence for transaction in may_accruals)
    pytest.fail(
        "1 May capitalisation is not applied before the 1 May receipt.\n"
        f"  Receipt allocations: {payment['allocations']}.\n"
        f"  1 May statement closing: {may['loans'][0]['closing']}.\n"
        "  Interest of R3.15 (315 cents) is 1 May on R1 950, the balance after the receipt. "
        "A day capitalised first on the R2 000 April balance would be R3.23 (323 cents).\n"
        "  A second service fee of R69.00 is levied for May when the statement runs, after the receipt.\n"
        "  Locked §1 and §8 (main 1435869) tell the engine to capitalise the day's due amounts "
        "at 00:00 and then allocate payments. They also still say same-day events follow "
        "recognition sequence. The code does the second. It does not reorder a payment behind "
        "that day's capitalisation. Whether 1 May interest is due that day, or only at month-end, "
        "is not settled by the two bullets. This test does not choose one."
    )


def test_missing_election_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_http(monkeypatch)
    for name in ORGANISATION_ELECTIONS:
        svc = Servicing(enigma=CountingStub())
        status, payload = dispatch(
            svc,
            "POST",
            "/v1/agreements",
            _body(settings={name: None}),
            {"Idempotency-Key": f"missing-{name}"},
        )
        assert status == 422, name
        assert payload["code"] == "election-unset", name
        assert svc.agreements == {}
        assert svc.ledger.store.accounts_for(ORG) == ()

    svc = Servicing(enigma=CountingStub())
    empty = _body()
    empty["settings"] = {}
    status, payload = dispatch(svc, "POST", "/v1/agreements", empty, {"Idempotency-Key": "empty-settings"})
    assert status == 422
    assert payload["code"] == "election-unset"
    assert svc.agreements == {}

    # The template already stores day count, base 5%, and discount 0. Omitting
    # them on the organisation still books. §19 fails closed only when both
    # levels are null. Both-null is asserted below.
    for name in ("day_count_code", "base_rate", "discount_rate"):
        svc = Servicing(enigma=CountingStub())
        booked = _book(svc, key=f"template-fills-{name}", settings={name: None})
        assert booked["status"] == "pending_disbursement"
        resolved = svc.agreements[booked["agreement_id"]].resolved
        assert resolved.day_count_code == "actual_actual"
        assert resolved.base_rate == Decimal("0.05")
        assert resolved.discount_rate == Decimal("0")

    product = micro_short_term()
    instrument = replace(product.instruments[0], day_count=None)
    no_day_count = replace(product, instruments=(instrument,))
    bare = OrganisationSettings(
        leniency_days=3,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code=None,
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0"),
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
    )
    svc = Servicing(enigma=CountingStub())
    with pytest.raises(ServicingError) as caught:
        svc.book(
            organisation_id=ORG,
            person_id=PERSON,
            product=no_day_count,
            settings=bare,
            recognised_at=datetime(2026, 4, 1, 9, 15, tzinfo=JOHANNESBURG),
            cash_advanced_cents=CASH_CENTS,
            frequency="monthly",
            schedule=((DUE, CASH_CENTS),),
            initiation_fee_cents=0,
            idempotency_key="no-day-count",
        )
    assert caught.value.code == "election-unset"
    assert svc.agreements == {}

    no_rate = replace(
        product,
        instruments=(replace(product.instruments[0], base_rate=None, monthly_rate=None),),
    )
    no_campaign = replace(
        bare,
        base_rate=None,
        discount_rate=None,
        day_count_code="actual_actual",
    )
    svc = Servicing(enigma=CountingStub())
    with pytest.raises(ServicingError) as caught:
        svc.book(
            organisation_id=ORG,
            person_id=PERSON,
            product=no_rate,
            settings=no_campaign,
            recognised_at=datetime(2026, 4, 1, 9, 15, tzinfo=JOHANNESBURG),
            cash_advanced_cents=CASH_CENTS,
            frequency="monthly",
            schedule=((DUE, CASH_CENTS),),
            initiation_fee_cents=0,
            idempotency_key="no-campaign",
        )
    assert caught.value.code == "election-unset"
    assert "base_rate" in str(caught.value)
    assert svc.agreements == {}


def test_statement_inputs_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_http(monkeypatch)
    svc = Servicing(enigma=CountingStub())
    booked, active = _book_disburse(svc, svc.enigma)
    missing_flag = {
        "period_start": ADVANCE.isoformat(),
        "period_end": APRIL_END.isoformat(),
        "vat_rate": str(VAT_RATE),
    }
    status, payload = dispatch(
        svc,
        "POST",
        f"/v1/organisations/{ORG}/clients/{PERSON}/statements",
        missing_flag,
        {},
    )
    assert status == 422
    assert payload["code"] == "election-unset"
    assert _kinds(svc, active["ledger_loan_id"]) == {"booking": 1}

    svc = Servicing(enigma=CountingStub())
    _booked, active = _book_disburse(svc, svc.enigma)
    status, payload = dispatch(
        svc,
        "POST",
        f"/v1/organisations/{ORG}/clients/{PERSON}/statements",
        {**missing_flag, "interest_cap_present": False},
        {},
    )
    assert status == 422
    assert payload["code"] == "election-unset"
    assert "interest cap" in payload["message"]
    assert _kinds(svc, active["ledger_loan_id"]) == {"booking": 1}


def test_rejected_statement_leaves_no_interest_bill(monkeypatch: pytest.MonkeyPatch) -> None:
    """A statement that fails closed must not leave a bill behind.

    Observed: omitting the VAT rate returns 422 after April interest has been billed.
    """
    _block_http(monkeypatch)
    svc = Servicing(enigma=CountingStub())
    _booked, active = _book_disburse(svc, svc.enigma)
    status, payload = dispatch(
        svc,
        "POST",
        f"/v1/organisations/{ORG}/clients/{PERSON}/statements",
        {
            "period_start": ADVANCE.isoformat(),
            "period_end": APRIL_END.isoformat(),
            "interest_cap_present": True,
        },
        {},
    )
    assert status == 422
    assert payload["code"] == "vat-rate-unset"
    kinds = _kinds(svc, active["ledger_loan_id"])
    interest = svc.ledger.bucket_balance(_loan(svc, active["ledger_loan_id"]), "interest")
    assert kinds == {"booking": 1}, (
        "Statement issue with no VAT rate returned 422 and still posted. "
        f"Transactions: {kinds}. Interest bucket: {_rands(interest)}. "
        "No statement row was stored. Locked §9 fails closed on a missing VAT rate, "
        "and that rejection should not debit interest."
    )
    assert svc.statements == {}


def _kinds(svc: Servicing, ledger_loan_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for transaction in svc.ledger.store.transactions_for(ORG, ledger_loan_id):
        counts[transaction.kind] = counts.get(transaction.kind, 0) + 1
    return counts


