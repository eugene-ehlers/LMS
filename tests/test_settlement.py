"""Early settlement quote and execute. Amounts are integer cents."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.calendar import binding_until
from lms.calc.fees import initiation_fee, opening_service_fraction, service_fee_cents
from lms.calc.models import FeeCapBasis, VatRate
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing
from lms.settlement.api import dispatch
from lms.settlement.errors import SettlementError
from lms.settlement.service import Settlement
from lms.statements.service import Documents
from lms_config.calendar import value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings
from lms_config.statute import SERVICE_FEE_MONTHLY_CENTS
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ADVANCE = date(2026, 3, 1)
DUE = date(2026, 4, 30)
AS_OF = date(2026, 4, 10)
VAT_ZERO = Decimal("0")
VAT_15 = Decimal("0.15")


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


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
        in_duplum_trigger="collections_default",
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def compliance(organisation_id: str = "org-a") -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=organisation_id,
        legal_name="North Credit (Pty) Ltd",
        ncr_registration_number="NCRCP999",
        trading_name="North Credit",
        physical_address="1 Long Street, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0210000000",
        bank_name="Example Bank",
        bank_account_number="123456789",
        branch_code="051001",
        payment_reference="loan-ref",
    )


def statutory_initiation(vat: Decimal) -> int:
    _ex_vat, _vat, total = initiation_fee(
        100_000,
        on=ADVANCE,
        vat_rates=(VatRate(ADVANCE, vat),),
        basis=FeeCapBasis.EXCLUSIVE,
    )
    return total


def world(
    *,
    initiation: int,
    due: date = DUE,
    vat_ready: bool = True,
    trigger: str | None = "collections_default",
    organisation_id: str = "org-a",
    with_compliance: bool = True,
):
    svc = Servicing(enigma=EnigmaStub())
    store = ComplianceStore()
    if with_compliance:
        store.put(compliance(organisation_id))
    record = svc.book(
        organisation_id=organisation_id,
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(in_duplum_trigger=trigger),
        recognised_at=at(ADVANCE, 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((due, 100_000),),
        initiation_fee_cents=initiation,
        idempotency_key=f"book-{organisation_id}-{due.isoformat()}-{initiation}",
    )
    record = svc.disburse(record.agreement_id, recognised_at=at(ADVANCE, 10))
    settlement = Settlement(svc, store, Documents(svc, store))
    return svc, settlement, record


def quote(settlement: Settlement, record, *, as_of: date = AS_OF, delivered_on: date | None = None, holidays=frozenset(), vat: Decimal = VAT_ZERO, recognised_at: datetime | None = None):
    delivered = as_of if delivered_on is None else delivered_on
    return settlement.quote(
        agreement_id=record.agreement_id,
        as_of=as_of,
        delivered_on=delivered,
        request_on=as_of,
        recognised_at=recognised_at or at(as_of, 11),
        holidays=holidays,
        interest_cap_present=True,
        vat_rate=vat,
    )


def kinds(svc: Servicing, record) -> set[str]:
    return {item.kind for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)}


def audit_types(svc: Servicing, record) -> list[str]:
    extract = svc.audit.extract(
        organisation_id=record.organisation_id,
        from_date=ADVANCE,
        to_date=date(2026, 5, 31),
    )
    return [row.event_type for row in extract.rows if row.agreement_id == record.agreement_id]


def test_quote_returns_cents_ncr_and_five_business_days():
    svc, settlement, record = world(initiation=statutory_initiation(VAT_ZERO))
    before = kinds(svc, record)
    quoted = quote(settlement, record)
    assert quoted.success is True
    assert quoted.early_termination_cents == 0
    assert quoted.valid_until == binding_until(AS_OF, frozenset())
    assert quoted.ncr_registration_number == "NCRCP999"
    assert quoted.confirmation == (
        f"Settlement quote issued. Amount owing is {quoted.amount_owing_cents} cents, "
        f"valid until {quoted.valid_until.isoformat()}. NCR number NCRCP999."
    )
    assert type(quoted.amount_owing_cents) is int
    assert type(quoted.early_termination_cents) is int
    assert quoted.amount_owing_cents == 133_667
    assert kinds(svc, record) == before
    assert "SETTLEMENT_QUOTED" in audit_types(svc, record)
    again = quote(settlement, record)
    assert again.quote_id == quoted.quote_id
    assert again.amount_owing_cents == quoted.amount_owing_cents


def test_a_holiday_inside_the_window_moves_valid_until():
    _svc, settlement, record = world(initiation=statutory_initiation(VAT_ZERO))
    holiday = date(2026, 4, 13)
    quoted = quote(settlement, record, holidays=frozenset({holiday}))
    assert quoted.valid_until == binding_until(AS_OF, frozenset({holiday}))
    assert quoted.valid_until == date(2026, 4, 20)
    plain = binding_until(AS_OF, frozenset())
    assert quoted.valid_until > plain


def test_missing_ncr_fails_closed_and_is_audited():
    svc, settlement, record = world(initiation=0, organisation_id="org-missing", with_compliance=False)
    with pytest.raises(SettlementError) as raised:
        quote(settlement, record)
    assert raised.value.code == "ncr-missing"
    assert "missing NCR number" in str(raised.value)
    rejected = [
        row
        for row in svc.audit.extract(
            organisation_id=record.organisation_id,
            from_date=ADVANCE,
            to_date=date(2026, 5, 31),
        ).rows
        if row.event_type == "SETTLEMENT_REJECTED"
    ]
    assert len(rejected) == 1
    assert rejected[0].payload["outcome"] == "failure"
    assert rejected[0].payload["code"] == "ncr-missing"


def test_missing_in_duplum_trigger_fails_closed():
    svc = Servicing(enigma=EnigmaStub())
    with pytest.raises(ServicingError) as raised:
        svc.book(
            organisation_id="org-a",
            person_id="person-a",
            product=micro_short_term(),
            settings=settings(in_duplum_trigger=None),
            recognised_at=at(ADVANCE, 8),
            cash_advanced_cents=100_000,
            frequency="monthly",
            schedule=((DUE, 100_000),),
            initiation_fee_cents=0,
            idempotency_key="book-no-trigger",
        )
    assert raised.value.code == "election-unset"
    assert str(raised.value) == "in_duplum_trigger is not set on the product or the organisation"
    assert svc.agreements == {}


def test_execute_allocates_the_quote_and_marks_the_agreement_settled():
    svc, settlement, record = world(initiation=statutory_initiation(VAT_ZERO))
    quoted = quote(settlement, record)
    paid_on = date(2026, 4, 15)
    done = settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=at(paid_on, 15),
        interest_cap_present=True,
        vat_rate=VAT_ZERO,
        idempotency_key="settle-1",
    )
    assert done.success is True
    assert done.balance_cents == 0
    assert done.amount_cents == quoted.amount_owing_cents
    assert type(done.amount_cents) is int
    assert done.confirmation == (
        f"Agreement settled. Receipt of {quoted.amount_owing_cents} cents allocated in section 126 order. "
        "Balance is 0 cents."
    )
    assert done.ncr_registration_number == "NCRCP999"
    assert record.status == "settled"
    transactions = svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)
    fees = [item for item in transactions if item.kind == "service_fee"]
    assert [(item.value_date, item.amount_cents) for item in fees] == [
        (date(2026, 3, 31), 6_000),
        (AS_OF, 6_000),
    ]
    april = fees[1]
    ten_day = service_fee_cents(
        on=AS_OF,
        period_start=AS_OF,
        period_end=AS_OF,
        monthly_cap_cents=SERVICE_FEE_MONTHLY_CENTS,
        fraction=Decimal(10) / Decimal(30),
        vat_rates=(VatRate(ADVANCE, VAT_ZERO),),
        basis=FeeCapBasis.EXCLUSIVE,
    )[2]
    assert april.amount_cents == 6_000
    assert april.amount_cents != ten_day
    assert opening_service_fraction(ADVANCE, DUE) == Decimal(1)
    bills = [item for item in transactions if item.kind == "interest_bill"]
    assert [(item.value_date, item.amount_cents) for item in bills] == [
        (date(2026, 3, 31), 5_000),
        (AS_OF, 1_667),
    ]
    assert all(item.value_date <= AS_OF for item in transactions if item.kind == "interest_accrual")
    settlement_tx = next(item for item in transactions if item.kind == "settlement")
    assert settlement_tx.recognised_at == value_instant(paid_on)
    assert settlement_tx.recognised_at.hour == 0
    assert settlement_tx.recognised_at.tzinfo == JOHANNESBURG
    assert all(
        item.recognised_at == value_instant(item.value_date)
        for item in transactions
        if item.kind != "booking"
    )
    account = svc.ledger.store.get(record.organisation_id, record.ledger_loan_id)
    assert svc.ledger.bucket_balance(account, "principal") == 0
    events = audit_types(svc, record)
    assert "SETTLEMENT_QUOTED" in events
    assert "SETTLEMENT_APPLIED" in events
    assert events.count("AGREEMENT_STATUS_CHANGED") >= 2
    applied = next(
        row
        for row in svc.audit.extract(
            organisation_id=record.organisation_id,
            from_date=ADVANCE,
            to_date=date(2026, 5, 31),
        ).rows
        if row.event_type == "SETTLEMENT_APPLIED"
    )
    assert applied.amount_cents == quoted.amount_owing_cents
    assert applied.payload["outcome"] == "success"
    replay = settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=at(paid_on, 15),
        interest_cap_present=True,
        vat_rate=VAT_ZERO,
        idempotency_key="settle-1",
    )
    assert replay == done
    assert sum(1 for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id) if item.kind == "settlement") == 1


def test_opening_month_fraction_is_not_shortened_to_the_settlement_day():
    svc, settlement, record = world(
        initiation=statutory_initiation(VAT_ZERO),
        due=date(2026, 3, 20),
    )
    as_of = date(2026, 3, 10)
    quoted = quote(settlement, record, as_of=as_of)
    settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=at(as_of, 16),
        interest_cap_present=True,
        vat_rate=VAT_ZERO,
        idempotency_key="settle-open",
    )
    fraction = opening_service_fraction(ADVANCE, date(2026, 3, 20))
    assert fraction == Decimal(19) / Decimal(31)
    priced = service_fee_cents(
        on=as_of,
        period_start=ADVANCE,
        period_end=ADVANCE,
        monthly_cap_cents=SERVICE_FEE_MONTHLY_CENTS,
        fraction=fraction,
        vat_rates=(VatRate(ADVANCE, VAT_ZERO),),
        basis=FeeCapBasis.EXCLUSIVE,
    )[2]
    shortened = service_fee_cents(
        on=as_of,
        period_start=ADVANCE,
        period_end=ADVANCE,
        monthly_cap_cents=SERVICE_FEE_MONTHLY_CENTS,
        fraction=Decimal(10) / Decimal(31),
        vat_rates=(VatRate(ADVANCE, VAT_ZERO),),
        basis=FeeCapBasis.EXCLUSIVE,
    )[2]
    fees = [
        item
        for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)
        if item.kind == "service_fee"
    ]
    assert len(fees) == 1
    assert fees[0].amount_cents == priced == 3_677
    assert fees[0].amount_cents != shortened
    assert record.status == "settled"


def test_booked_zero_initiation_is_not_added_again():
    svc, settlement, record = world(initiation=0)
    quoted = quote(settlement, record, vat=VAT_15)
    stored = settlement.documents.quotes[(record.agreement_id, AS_OF, AS_OF)]
    service = sum(amount for kind, amount in stored.components if kind == "service")
    initiation = sum(amount for kind, amount in stored.components if kind == "initiation")
    assert service == 13_800
    assert initiation == 0
    assert quoted.early_termination_cents == 0
    assert quoted.amount_owing_cents == 120_467
    done = settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=at(date(2026, 4, 15), 15),
        interest_cap_present=True,
        vat_rate=VAT_15,
        idempotency_key="settle-booked-zero",
    )
    assert done.balance_cents == 0
    assert record.status == "settled"
    assert "charge" not in kinds(svc, record)


def test_non_capitalised_booked_fee_includes_vat_and_settles():
    ex_vat, vat, total = initiation_fee(
        100_000,
        on=ADVANCE,
        vat_rates=(VatRate(ADVANCE, VAT_15),),
        basis=FeeCapBasis.EXCLUSIVE,
    )
    assert (ex_vat, vat, total) == (15_000, 2_250, 17_250)
    svc, settlement, record = world(initiation=ex_vat)
    quoted = quote(settlement, record, vat=VAT_15)
    stored = settlement.documents.quotes[(record.agreement_id, AS_OF, AS_OF)]
    initiation = sum(amount for kind, amount in stored.components if kind == "initiation")
    assert initiation == 17_250
    assert quoted.amount_owing_cents == 137_717
    done = settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=at(AS_OF, 12),
        interest_cap_present=True,
        vat_rate=VAT_15,
        idempotency_key="settle-vat",
    )
    assert done.balance_cents == 0
    assert record.status == "settled"
    charges = [
        item
        for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)
        if item.kind == "charge" and item.amount_cents == vat
    ]
    assert len(charges) == 1


def test_capitalised_booked_fee_is_not_added_again_and_vat_is_included():
    """Day-1 booking keeps the fee non-capitalised. The quote still has the rule."""
    from lms.calc.ledger import quote_settlement
    from lms.calc.models import Agreement, Policy, Product

    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=ADVANCE,
        maturity_date=DUE,
        agreed_monthly_rate=Decimal("0.05"),
        principal_instalments=((DUE, 100_000),),
        initiation_capitalised=True,
        use_booked_initiation=True,
        booked_initiation_ex_vat_cents=15_000,
    )
    policy = Policy(
        leniency_days=1,
        full_payment_threshold_percent=Decimal("100"),
        service_fee_monthly_cents=0,
        interest_on_deferred_initiation=False,
    )
    quoted = quote_settlement(
        agreement,
        as_of=AS_OF,
        policy=policy,
        vat_rates=(VatRate(ADVANCE, VAT_15),),
    )
    components = dict(quoted.components)
    assert components["principal"] == 115_000
    assert components["initiation"] == 2_250
    permitted = quote_settlement(
        agreement,
        as_of=AS_OF,
        policy=Policy(
            leniency_days=1,
            full_payment_threshold_percent=Decimal("100"),
            service_fee_monthly_cents=0,
            interest_on_deferred_initiation=True,
        ),
        vat_rates=(VatRate(ADVANCE, VAT_15),),
    )
    permitted_parts = dict(permitted.components)
    assert permitted_parts["principal"] == 115_000
    assert permitted_parts["initiation"] == 2_250


def test_short_surplus_and_late_receipts_are_not_allocated():
    svc, settlement, record = world(initiation=statutory_initiation(VAT_ZERO))
    quoted = quote(settlement, record)
    with pytest.raises(SettlementError) as short:
        settlement.execute(
            agreement_id=record.agreement_id,
            quote_id=quoted.quote_id,
            cents=quoted.amount_owing_cents - 1,
            recognised_at=at(AS_OF, 12),
            interest_cap_present=True,
            vat_rate=VAT_ZERO,
            idempotency_key="short",
        )
    assert short.value.code == "quote-mismatch"
    with pytest.raises(SettlementError) as surplus:
        settlement.execute(
            agreement_id=record.agreement_id,
            quote_id=quoted.quote_id,
            cents=quoted.amount_owing_cents + 1,
            recognised_at=at(AS_OF, 12),
            interest_cap_present=True,
            vat_rate=VAT_ZERO,
            idempotency_key="surplus",
        )
    assert surplus.value.code == "quote-mismatch"
    late = quoted.valid_until + timedelta(days=1)
    with pytest.raises(SettlementError) as window:
        settlement.execute(
            agreement_id=record.agreement_id,
            quote_id=quoted.quote_id,
            cents=quoted.amount_owing_cents,
            recognised_at=at(late, 9),
            interest_cap_present=True,
            vat_rate=VAT_ZERO,
            idempotency_key="late",
        )
    assert window.value.code == "quote-window"
    assert kinds(svc, record) == {"booking"}
    assert "SETTLEMENT_REJECTED" in audit_types(svc, record)


def test_api_rejects_bad_money_a_naive_timestamp_and_a_missing_calendar():
    svc, settlement, record = world(initiation=statutory_initiation(VAT_ZERO))
    path = f"/v1/agreements/{record.agreement_id}/settlement-quotes"
    naive_status, naive_body = dispatch(
        settlement,
        "POST",
        path,
        {
            "as_of": "2026-04-10",
            "delivered_on": "2026-04-10",
            "request_on": "2026-04-10",
            "recognised_at": "2026-04-10T11:00:00",
            "holidays": [],
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {},
    )
    assert naive_status == 422
    assert naive_body["success"] is False
    assert naive_body["code"] == "timestamp-naive"
    assert "SETTLEMENT_REJECTED" not in audit_types(svc, record)
    missing_status, missing_body = dispatch(
        settlement,
        "POST",
        "/v1/agreements/missing/settlement-quotes",
        {
            "as_of": "2026-04-10",
            "delivered_on": "2026-04-10",
            "request_on": "2026-04-10",
            "recognised_at": "2026-04-10T11:00:00+02:00",
            "holidays": [],
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {},
    )
    assert missing_status == 404
    assert missing_body["code"] == "not-found"
    assert "SETTLEMENT_REJECTED" not in audit_types(svc, record)
    holiday_status, holiday_body = dispatch(
        settlement,
        "POST",
        path,
        {
            "as_of": "2026-04-10",
            "delivered_on": "2026-04-10",
            "request_on": "2026-04-10",
            "recognised_at": "2026-04-10T11:00:00+02:00",
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {},
    )
    assert holiday_status == 422
    assert holiday_body["code"] == "holidays-unset"
    cap_status, cap_body = dispatch(
        settlement,
        "POST",
        path,
        {
            "as_of": "2026-04-10",
            "delivered_on": "2026-04-10",
            "request_on": "2026-04-10",
            "recognised_at": "2026-04-10T11:00:00+02:00",
            "holidays": [],
            "interest_cap_present": False,
            "vat_rate": "0",
        },
        {},
    )
    assert cap_status == 422
    assert cap_body["reason"] == "no interest cap covers the value date"
    status, body = dispatch(
        settlement,
        "POST",
        path,
        {
            "as_of": "2026-04-10",
            "delivered_on": "2026-04-10",
            "request_on": "2026-04-10",
            "recognised_at": "2026-04-10T11:00:00+02:00",
            "holidays": [],
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {},
    )
    assert status == 200
    assert body["success"] is True
    assert body["early_termination_cents"] == 0
    assert body["ncr_registration_number"] == "NCRCP999"
    assert type(body["amount_owing_cents"]) is int
    pay_status, pay_body = dispatch(
        settlement,
        "POST",
        f"/v1/agreements/{record.agreement_id}/settlements",
        {
            "quote_id": body["quote_id"],
            "cents": str(body["amount_owing_cents"]),
            "recognised_at": "2026-04-15T15:00:00+02:00",
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {"Idempotency-Key": "api-1"},
    )
    assert pay_status == 422
    assert pay_body["code"] == "cents"
    assert kinds(svc, record) == {"booking"}
    ok_status, ok_body = dispatch(
        settlement,
        "POST",
        f"/v1/agreements/{record.agreement_id}/settlements",
        {
            "quote_id": body["quote_id"],
            "cents": body["amount_owing_cents"],
            "recognised_at": "2026-04-15T15:00:00+02:00",
            "interest_cap_present": True,
            "vat_rate": "0",
        },
        {"Idempotency-Key": "api-1"},
    )
    assert ok_status == 200
    assert ok_body["success"] is True
    assert ok_body["balance_cents"] == 0
    assert record.status == "settled"
