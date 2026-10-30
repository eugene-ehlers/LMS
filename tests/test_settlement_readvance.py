"""Settlement re-advance. The decision engine supplies the new price. The LMS stores it."""

from __future__ import annotations

import http.client
import socket
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.fees import opening_service_fraction, service_fee_cents
from lms.calc.interest import daily_interest_rands
from lms.calc.models import FeeCapBasis, VatRate
from lms.calc.money import to_cents
from lms.payments.loan_numbers import LoanNumberSeries
from lms.servicing.api import dispatch as servicing_dispatch
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.settlement.api import dispatch
from lms.settlement.service import SettlementReadvance
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.statute import REPO_ANNUAL

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"
ACTOR = "staff-1"
CASH = 200_000
VAT = Decimal("0.15")
RATE = Decimal("0.05")


def _refuse_http(*_args, **_kwargs):
    raise AssertionError("settlement re-advance opened a socket")


@pytest.fixture(autouse=True)
def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _refuse_http)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _refuse_http)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _refuse_http)


def _compliance(number: str = "NCRCP000000") -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=ORG,
        legal_name="ACME",
        ncr_registration_number=number,
        trading_name="",
        physical_address="1 Main Road, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0100000000",
        bank_name="First National Bank",
        bank_account_number="62011234567",
        branch_code="250655",
        payment_reference="ACME",
    )


def _world(number: str | None = "NCRCP000000"):
    servicing = Servicing(enigma=EnigmaStub())
    compliance = ComplianceStore()
    if number is not None:
        compliance.put(_compliance(number))
    series = LoanNumberSeries()
    command = SettlementReadvance(servicing, compliance, series)
    return command, servicing, series


def _book(servicing: Servicing, *, due: date, booked_at: str, disbursed_at: str, key: str = "book") -> str:
    status, booked = servicing_dispatch(
        servicing,
        "POST",
        "/v1/agreements",
        {
            "organisation_id": ORG,
            "person_id": PERSON,
            "product_code": "micro_short_term",
            "recognised_at": booked_at,
            "cash_advanced_cents": CASH,
            "frequency": "monthly",
            "schedule": [[due.isoformat(), CASH]],
            "initiation_fee_cents": 0,
            "settings": {
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
            },
        },
        {"Idempotency-Key": key},
    )
    assert status == 200, booked
    status, active = servicing_dispatch(
        servicing,
        "POST",
        f"/v1/agreements/{booked['agreement_id']}/disbursements",
        {"recognised_at": disbursed_at},
        {},
    )
    assert status == 200, active
    return booked["agreement_id"]


def _settings(**overrides) -> dict:
    values = {
        "leniency_days": 3,
        "full_payment_threshold_percent": "100",
        "interest_on_deferred_initiation": "none",
        "repo_rate_fall": "contract_rate",
        "day_count_code": "actual_actual",
        "base_rate": "0.99",
        "discount_rate": "0.5",
        "vat_on_rand_maxima": "exclusive",
        "late_disbursement": "keep_instalment",
        "partial_prepayment": "shorten_term",
        "in_duplum_trigger": "contractual_breach",
        "residual_write_off_threshold_cents": 0,
        "campaign_fall_away_choice": "does_not_fall_away",
    }
    values.update(overrides)
    return values


def _new_loan(**overrides) -> dict:
    loan = {
        "product_code": "micro_short_term",
        "application_number": "app-new",
        "rate": "0.05",
        "short_term_rate_flag": "five_percent",
        "term_count": 1,
        "frequency": "monthly",
        "instalment_cents": 210_000,
        "cash_advanced_cents": CASH,
        "schedule": [["2026-06-01", CASH]],
        "initiation_fee_cents": 0,
    }
    loan.update(overrides)
    return loan


def _body(agreement_id: str, receipt: int, recognised_at: str, **overrides) -> dict:
    body = {
        "organisation_id": ORG,
        "agreement_id": agreement_id,
        "actor_id": ACTOR,
        "recognised_at": recognised_at,
        "receipt_cents": receipt,
        "interest_cap_present": True,
        "vat_rate": "0.15",
        "settings": _settings(),
        "new_loan": _new_loan(),
    }
    body.update(overrides)
    return body


def _post(command, body: dict, key: str = "settle-1"):
    return dispatch(command, "POST", "/v1/settlement-readvances", body, {"Idempotency-Key": key})


def _interest(days: list[tuple[int, int]], rate: Decimal = RATE) -> int:
    total = Decimal(0)
    for count, divisor in days:
        total += daily_interest_rands(CASH, rate, divisor) * count
    return to_cents(total)


def _fee(*, fraction: Decimal | None) -> tuple[int, int, int]:
    return service_fee_cents(
        on=date(2026, 4, 1),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 1),
        full_month=fraction is None,
        fraction=fraction,
        vat_rates=(VatRate(date(2026, 1, 1), VAT),),
        basis=FeeCapBasis.EXCLUSIVE,
    )


def _audit(servicing: Servicing, end: date = date(2026, 6, 1)):
    extract = servicing.audit.extract(organisation_id=ORG, from_date=date(2026, 4, 1), to_date=end)
    return [row for row in extract.rows if row.event_type == "SETTLEMENT_READVANCE"]


def _charges(servicing: Servicing, agreement_id: str):
    record = servicing.agreements[agreement_id]
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id or "")
    return account.charges


def test_five_percent_is_stored_when_a_same_year_short_term_loan_is_settled():
    command, servicing, series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    old = servicing.agreements[agreement_id]
    series.issue(
        organisation_id=ORG,
        application_number="app-old",
        agreement_id=agreement_id,
        ledger_loan_id=old.ledger_loan_id or "",
    )
    full_fee = _fee(fraction=None)
    assert full_fee == (6_000, 900, 6_900)
    receipt = _interest([(30, 30), (1, 31)]) + full_fee[2] + full_fee[2] + CASH
    product = {
        "in_duplum_trigger": "collections_default",
        "residual_write_off_threshold_cents": 10_000,
        "campaign_fall_away_choice": "falls_away_on_default",
        "campaign_fall_away_trigger": "collections_default",
    }
    body = _body(
        agreement_id,
        receipt,
        "2026-05-01T08:00:00+02:00",
        product_elections=product,
    )
    status, result = _post(command, body)
    assert status == 200, result
    assert result["outcome"] == "success"
    assert result["balance_cents"] == 0
    assert result["settled_loan_number"] == "000000000001"
    assert result["new_loan_number"] == "000000000002"
    assert result["short_term_rate_flag"] == "five_percent"
    assert result["supplied_rate"] == "0.05"
    assert "000000000002" in result["confirmation"]
    assert "000000000001" in result["confirmation"]
    assert old.status == "settled"
    assert servicing.ledger.settlement_balance_cents(ORG, old.ledger_loan_id or "") == 0
    new = servicing.agreements[result["new_agreement_id"]]
    assert new.status == "active"
    assert new.settled_from_agreement_id == agreement_id
    assert new.resolved.base_rate == Decimal("0.05")
    assert new.resolved.discount_rate == Decimal(0)
    assert new.resolved.in_duplum_trigger == "collections_default"
    assert new.resolved.residual_write_off_threshold_cents == 10_000
    assert new.campaign_fall_away_choice == "falls_away_on_default"
    assert new.campaign_fall_away_trigger == "collections_default"
    assert new.contractual_instalment_cents == 210_000
    assert new.frozen_full_name == "Ada Borrower"
    account = servicing.ledger.store.get(ORG, new.ledger_loan_id or "")
    assert account.snapshot.base_rate == Decimal("0.05")
    servicing.enigma.full_name = "Changed After Booking"
    assert new.frozen_full_name == "Ada Borrower"
    assert old.frozen_full_name == "Ada Borrower"
    rows = _audit(servicing)
    assert len(rows) == 1
    assert rows[0].enigma_person_id == ACTOR
    assert rows[0].payload["outcome"] == "success"
    assert rows[0].amount_cents is None
    again_status, again = _post(command, body)
    assert (again_status, again) == (status, result)
    assert len(servicing.agreements) == 2
    assert len(command.links) == 1
    assert _audit(servicing) == rows
    assert series.find_application(ORG, "app-new").loan_number == "000000000002"


def test_three_percent_flag_rejects_a_five_percent_rate_and_does_not_settle():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    body = _body(
        agreement_id,
        1,
        "2026-05-01T08:00:00+02:00",
        new_loan=_new_loan(rate="0.05", short_term_rate_flag="three_percent"),
    )
    status, result = _post(command, body)
    assert status == 422, result
    assert result["code"] == "short-term-rate"
    assert "does not choose a different flag" in result["message"]
    assert servicing.agreements[agreement_id].status == "active"
    assert _charges(servicing, agreement_id) == []
    assert len(servicing.agreements) == 1


def test_three_percent_rate_is_stored_and_the_settings_rate_is_ignored():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    full_fee = _fee(fraction=None)[2]
    receipt = _interest([(30, 30), (1, 31)]) + full_fee + full_fee + CASH
    body = _body(
        agreement_id,
        receipt,
        "2026-05-01T08:00:00+02:00",
        new_loan=_new_loan(rate="0.03", short_term_rate_flag="three_percent", application_number="app-3"),
    )
    status, result = _post(command, body)
    assert status == 200, result
    new = servicing.agreements[result["new_agreement_id"]]
    assert new.resolved.base_rate == Decimal("0.03")
    assert new.resolved.residual_write_off_threshold_cents == 0
    assert new.short_term_rate_flag == "three_percent"
    assert new.campaign_fall_away_choice == "does_not_fall_away"
    assert new.campaign_fall_away_trigger is None
    account = servicing.ledger.store.get(ORG, new.ledger_loan_id or "")
    assert account.snapshot.base_rate == Decimal("0.03")


def test_missing_election_or_ncr_number_fails_closed():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    recognised = "2026-05-01T08:00:00+02:00"
    missing = _settings()
    del missing["in_duplum_trigger"]
    status, result = _post(command, _body(agreement_id, 1, recognised, settings=missing), key="duplum")
    assert result["code"] == "election-unset"
    assert result["message"] == "missing election: in-duplum trigger"
    residual = _settings()
    del residual["residual_write_off_threshold_cents"]
    status, result = _post(command, _body(agreement_id, 1, recognised, settings=residual), key="residual")
    assert status == 422
    assert result["message"] == "missing election: residual write-off threshold"
    fall = _settings()
    del fall["campaign_fall_away_choice"]
    status, result = _post(command, _body(agreement_id, 1, recognised, settings=fall), key="fall")
    assert result["message"] == "missing election: campaign fall-away choice"
    assert servicing.agreements[agreement_id].status == "active"
    assert _charges(servicing, agreement_id) == []

    bare, bare_servicing, _series = _world(number=None)
    bare_id = _book(
        bare_servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    status, result = _post(bare, _body(bare_id, 1, recognised))
    assert status == 422
    assert result["code"] == "ncr-number-unset"
    assert "missing NCR registration number" in result["message"]
    assert bare_servicing.agreements[bare_id].status == "active"


def test_settlement_month_is_a_full_fee_and_a_short_receipt_is_not_allocated():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 20),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    interest = _interest([(30, 30), (10, 31)])
    full = _fee(fraction=None)
    required = interest + full[2] + full[2] + CASH
    status, result = _post(command, _body(agreement_id, 1, "2026-05-10T10:00:00+02:00"), key="short")
    assert status == 422, result
    assert result["code"] == "settlement-short"
    assert result["required_cents"] == required
    assert servicing.agreements[agreement_id].status == "active"
    assert len(servicing.agreements) == 1
    services = [charge for charge in _charges(servicing, agreement_id) if charge.bucket == "service"]
    assert sorted((charge.levied_on, charge.ex_vat_cents, charge.vat_cents) for charge in services) == [
        (date(2026, 4, 1), 6_000, 900),
        (date(2026, 5, 10), 6_000, 900),
    ]
    interest_charges = [charge for charge in _charges(servicing, agreement_id) if charge.bucket == "interest"]
    assert sum(charge.ex_vat_cents for charge in interest_charges) == interest
    status, result = _post(command, _body(agreement_id, required, "2026-05-10T10:00:00+02:00"), key="exact")
    assert status == 200, result
    assert servicing.agreements[agreement_id].status == "settled"
    assert servicing.ledger.settlement_balance_cents(ORG, servicing.agreements[agreement_id].ledger_loan_id or "") == 0


def test_opening_month_fraction_is_not_shortened_by_an_earlier_settlement():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 10),
        booked_at="2026-04-20T09:15:00+02:00",
        disbursed_at="2026-04-20T11:00:00+02:00",
    )
    fraction = opening_service_fraction(date(2026, 4, 20), date(2026, 5, 10))
    assert fraction == Decimal(20) / Decimal(30)
    fee = _fee(fraction=fraction)
    assert fee == (4_000, 600, 4_600)
    interest = _interest([(6, 30)])
    receipt = interest + fee[2] + CASH
    status, result = _post(command, _body(agreement_id, receipt, "2026-04-25T15:00:00+02:00"))
    assert status == 200, result
    assert result["settled_loan_number"] is None
    assert agreement_id in result["confirmation"]
    services = [charge for charge in _charges(servicing, agreement_id) if charge.bucket == "service"]
    assert len(services) == 1
    assert (services[0].ex_vat_cents, services[0].vat_cents, services[0].levied_on) == (4_000, 600, date(2026, 4, 20))
    interest_charges = [charge for charge in _charges(servicing, agreement_id) if charge.bucket == "interest"]
    assert sum(charge.ex_vat_cents for charge in interest_charges) == interest


def test_missing_new_loan_names_both_out_of_scope_commands_and_uses_johannesburg_date():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    body = _body(agreement_id, CASH, "2026-04-30T22:30:00Z")
    del body["new_loan"]
    status, result = _post(command, body)
    assert status == 422, result
    assert result["code"] == "new-loan-required"
    assert "Early settlement without a new loan" in result["message"]
    assert "restructure" in result["message"]
    assert result["recognition_date"] == "2026-05-01"
    assert servicing.agreements[agreement_id].status == "active"
    assert _charges(servicing, agreement_id) == []


def test_cents_timestamp_flag_and_fall_away_fail_closed():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    recognised = "2026-05-01T08:00:00+02:00"
    status, result = _post(command, _body(agreement_id, True, recognised), key="bool")
    assert status == 422
    assert result["code"] == "amount"
    status, naive = _post(command, _body(agreement_id, 1, "2026-05-01T00:00:00"), key="naive")
    assert naive["code"] == "value-date"
    status, capped = _post(
        command,
        _body(agreement_id, 1, recognised, interest_cap_present=False),
        key="cap",
    )
    assert capped["code"] == "election-unset"
    assert "interest cap" in capped["message"]
    kept = _settings(campaign_fall_away_choice="does_not_fall_away", campaign_fall_away_trigger="contractual_breach")
    status, trigger = _post(command, _body(agreement_id, 1, recognised, settings=kept), key="trigger")
    assert trigger["code"] == "election-unset"
    assert "no trigger" in trigger["message"]
    missing_trigger = _settings(campaign_fall_away_choice="falls_away_on_default")
    status, choice = _post(command, _body(agreement_id, 1, recognised, settings=missing_trigger), key="choice")
    assert choice["message"] == "missing election: campaign fall-away trigger"
    flagged = _new_loan(product_code="unsecured_personal", rate="0.21", short_term_rate_flag="five_percent")
    status, unsecured = _post(command, _body(agreement_id, 1, recognised, new_loan=flagged), key="flag")
    assert unsecured["code"] == "short-term-flag-unset"
    assert servicing.agreements[agreement_id].status == "active"
    assert _charges(servicing, agreement_id) == []
    status, missing_key = dispatch(command, "POST", "/v1/settlement-readvances", _body(agreement_id, 1, recognised), {})
    assert missing_key["code"] == "idempotency-required"
    status, unknown = dispatch(command, "GET", "/v1/settlement-readvances", {}, {})
    assert status == 404


def test_unsecured_re_advance_stores_the_margin_and_needs_a_repo_rate():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    loan = _new_loan(
        product_code="unsecured_personal",
        rate="0.21",
        application_number="app-unsecured",
    )
    del loan["short_term_rate_flag"]
    status, result = _post(command, _body(agreement_id, 1, "2026-05-01T08:00:00+02:00", new_loan=loan), key="no-repo")
    assert result["code"] == "repo-unset"
    assert servicing.agreements[agreement_id].status == "active"
    loan["repos"] = [{"effective_from": "2026-01-01", "annual_rate": str(REPO_ANNUAL)}]
    full = _fee(fraction=None)[2]
    receipt = _interest([(30, 30), (1, 31)]) + full + full + CASH
    status, result = _post(command, _body(agreement_id, receipt, "2026-05-01T08:00:00+02:00", new_loan=loan))
    assert status == 200, result
    assert result["short_term_rate_flag"] is None
    new = servicing.agreements[result["new_agreement_id"]]
    assert new.product.classification == "unsecured"
    assert new.resolved.base_rate == Decimal("0.21")
    assert new.product.instruments[0].repo_margin == Decimal("0.21")


def test_same_key_with_a_different_body_conflicts_and_a_settled_agreement_is_refused():
    command, servicing, _series = _world()
    agreement_id = _book(
        servicing,
        due=date(2026, 5, 1),
        booked_at="2026-04-01T09:15:00+02:00",
        disbursed_at="2026-04-01T11:00:00+02:00",
    )
    full = _fee(fraction=None)[2]
    receipt = _interest([(30, 30), (1, 31)]) + full + full + CASH
    body = _body(agreement_id, receipt, "2026-05-01T08:00:00+02:00")
    status, result = _post(command, body, key="once")
    assert status == 200, result
    status, conflict = _post(command, _body(agreement_id, receipt - 1, "2026-05-01T08:00:00+02:00"), key="once")
    assert status == 409
    assert conflict["code"] == "idempotency-conflict"
    assert len(servicing.agreements) == 2
    status, refused = _post(command, body, key="again")
    assert refused["code"] == "status"
    assert "Restructure" in refused["message"]
