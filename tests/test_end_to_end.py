"""End-to-end short-term path. Amounts are integer cents.

The decision-engine dummy supplies the principal, the periodic rate, the
term, the application number, and the contractual instalment. Booking
freezes the name, identity number, and service address. Each later step
uses the servicing, ledger, statement, and settlement code already locked.
"""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from lms.calc.fees import opening_service_fraction, service_fee_cents
from lms.calc.interest import daily_interest_rands
from lms.calc.models import FeeCapBasis, VatRate
from lms.calc.money import to_cents
from lms.dummies.decision_engine import DecisionEngineDummy
from lms.payments.loan_numbers import LoanNumberSeries
from lms.ports.decision_engine import (
    Application,
    Approval,
    ConsumerIdentity,
    PaymentFrequency,
    ShortTermRateBand,
)
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.settlement.service import Settlement
from lms.statements.errors import DocumentsError
from lms.statements.service import Documents
from lms_config.calendar import value_date, value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings
from lms_config.statute import SERVICE_FEE_MONTHLY_CENTS
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-e2e"
OTHER_ORG = "org-e2e-other"
PERSON = "person-e2e"
OTHER_PERSON = "person-e2e-other"
NCR = "NCRCP999"
OTHER_NCR = "NCRCP998"
CASH_CENTS = 200_000
DUE_PRINCIPAL_CENTS = 40_000
LATER_PRINCIPAL_CENTS = 160_000
INSTALMENT_CENTS = 50_000
CREDIT_LIFE_CENTS = 199
RATE_BPS = 500
LAYBYE_REMAINDER_CENTS = 2_500
ADVANCE = date(2026, 4, 1)
APRIL_END = date(2026, 4, 30)
DUE = date(2026, 5, 1)
LATER_DUE = date(2026, 6, 1)
VAT_RATE = Decimal("0.15")
RATE = Decimal(RATE_BPS) / Decimal(10_000)
RATE_CAP = Decimal("0.05")
NAME = "Ada Borrower"
ID_NUMBER = "8001015800085"
ADDRESS = "1 Main Road, Cape Town"
BOOKED_AT = datetime(2026, 4, 1, 8, 0, tzinfo=JOHANNESBURG)
DISBURSED_AT = datetime(2026, 4, 1, 11, 0, tzinfo=JOHANNESBURG)
PAID_AT = datetime(2026, 5, 1, 10, 0, tzinfo=JOHANNESBURG)
REVERSED_AT = datetime(2026, 5, 3, 16, 0, tzinfo=JOHANNESBURG)
BUCKETS = ("principal", "interest", "service", "initiation", "laybye_hold")
_ORDER = ("book", "disburse", "capitalise", "receipt", "statement", "reverse", "settle")


def _settings() -> OrganisationSettings:
    return OrganisationSettings(
        leniency_days=3,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        base_rate=RATE,
        discount_rate=Decimal("0"),
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
        in_duplum_trigger="collections_default",
        residual_write_off_threshold_cents=10_000,
    )


def _compliance(organisation_id: str, ncr: str) -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=organisation_id,
        legal_name="North Credit (Pty) Ltd",
        ncr_registration_number=ncr,
        trading_name="North Credit",
        physical_address="1 Long Street, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0210000000",
        bank_name="Example Bank",
        bank_account_number="123456789",
        branch_code="051001",
        payment_reference="loan-ref",
    )


def _product():
    template = micro_short_term()
    instrument = replace(
        template.instruments[0],
        monthly_rate=RATE,
        base_rate=RATE,
        discount_rate=Decimal(0),
    )
    return replace(template, instruments=(instrument,))


def _accrued_rands(base_cents: int, start: date, end: date) -> Decimal:
    total = Decimal(0)
    day = start
    while day <= end:
        divisor = calendar.monthrange(day.year, day.month)[1]
        total += daily_interest_rands(base_cents, RATE, divisor)
        day += timedelta(days=1)
    return total


def _service(on: date, *, opening: bool) -> int:
    fraction = opening_service_fraction(ADVANCE, DUE) if opening else None
    _ex_vat, _vat, total = service_fee_cents(
        on=on,
        period_start=on,
        period_end=on,
        monthly_cap_cents=SERVICE_FEE_MONTHLY_CENTS,
        full_month=not opening,
        fraction=fraction,
        vat_rates=(VatRate(date(on.year, 1, 1), VAT_RATE),),
        basis=FeeCapBasis.EXCLUSIVE,
    )
    return total


def _balances(ledger, account) -> dict[str, int]:
    return {bucket: ledger.bucket_balance(account, bucket) for bucket in BUCKETS}


def _integers(mapping: dict[str, int]) -> None:
    for bucket, amount in mapping.items():
        assert type(amount) is int, bucket


def path(until: str) -> SimpleNamespace:
    """Run the locked path and stop after ``until``."""
    stop = _ORDER.index(until)
    stub = EnigmaStub()
    stub.full_name = NAME
    stub.id_number = ID_NUMBER
    stub.service_address = ADDRESS
    servicing = Servicing(enigma=stub)
    compliance = ComplianceStore()
    compliance.put(_compliance(ORG, NCR))
    documents = Documents(servicing, compliance)
    engine = DecisionEngineDummy.fixed_success(
        short_term_rate_band=ShortTermRateBand.FIVE_PERCENT,
        contractual_periodic_rate_bps=RATE_BPS,
        instalment_cents=INSTALMENT_CENTS,
        credit_life_premium_cents=CREDIT_LIFE_CENTS,
    )
    application = Application(
        consumer=ConsumerIdentity(person_id=PERSON, name=NAME, id_number=ID_NUMBER),
        requested_amount_cents=CASH_CENTS,
        product_type="short_term",
        term_count=2,
        payment_frequency=PaymentFrequency.MONTHLY,
    )
    approval = engine.decide(application)
    assert isinstance(approval, Approval)
    schedule = ((DUE, DUE_PRINCIPAL_CENTS), (LATER_DUE, LATER_PRINCIPAL_CENTS))
    record = servicing.book_linked_laybye(
        organisation_id=ORG,
        person_id=PERSON,
        product=_product(),
        settings=_settings(),
        recognised_at=BOOKED_AT,
        cash_advanced_cents=application.requested_amount_cents,
        frequency=approval.payment_frequency.value,
        schedule=schedule,
        initiation_fee_cents=0,
        quoted_disbursement=ADVANCE,
        idempotency_key="e2e-book",
        rate_supplied_by_decision_engine=True,
        short_term_rate_cap=RATE_CAP,
        application_number=approval.application_number,
        contractual_instalment_cents=approval.instalment_cents,
        term_count=approval.term_count,
        short_term_rate_flag=approval.short_term_rate_band,
    )
    stub.full_name = "Changed Name"
    stub.id_number = "9999999999999"
    stub.service_address = "9 Other Road, Johannesburg"
    state = SimpleNamespace(
        servicing=servicing,
        documents=documents,
        compliance=compliance,
        stub=stub,
        application=application,
        approval=approval,
        record=record,
        parent=None,
        child=None,
        april=None,
        may=None,
        payment=None,
        pre_parent=None,
        pre_child=None,
        due_interest=None,
        due_service=None,
        receipt_cents=None,
    )
    if stop <= _ORDER.index("book"):
        return state

    record = servicing.disburse(record.agreement_id, recognised_at=DISBURSED_AT)
    state.record = record
    state.parent = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    state.child = servicing.ledger.store.get(ORG, record.laybye_loan_id)
    if stop <= _ORDER.index("disburse"):
        return state

    state.april = documents.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=ADVANCE,
        period_end=APRIL_END,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    if stop <= _ORDER.index("capitalise"):
        return state

    april_interest = to_cents(_accrued_rands(CASH_CENTS, ADVANCE, APRIL_END))
    may_interest = to_cents(_accrued_rands(CASH_CENTS, ADVANCE, DUE)) - april_interest
    due_interest = april_interest + may_interest
    due_service = _service(ADVANCE, opening=True) + _service(DUE, opening=False)
    receipt_cents = due_interest + due_service + DUE_PRINCIPAL_CENTS + LAYBYE_REMAINDER_CENTS
    state.due_interest = due_interest
    state.due_service = due_service
    state.receipt_cents = receipt_cents
    payment = servicing.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=receipt_cents,
        recognised_at=PAID_AT,
        idempotency_key="e2e-receipt",
        agreement_id=record.agreement_id,
        attributed_due_on=DUE,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    state.payment = payment
    parent_after = _balances(servicing.ledger, state.parent)
    child_after = _balances(servicing.ledger, state.child)
    state.pre_parent = dict(parent_after)
    state.pre_child = dict(child_after)
    for bucket, amount in payment.allocations:
        if bucket == "laybye_hold":
            state.pre_child[bucket] -= amount
        else:
            state.pre_parent[bucket] += amount
    if stop <= _ORDER.index("receipt"):
        return state

    state.may = documents.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=DUE,
        period_end=DUE,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    if stop <= _ORDER.index("statement"):
        return state

    servicing.reverse_payment(payment.payment_id, recognised_at=REVERSED_AT)
    if stop <= _ORDER.index("reverse"):
        return state

    loan = state.parent
    servicing.ledger.open_in_duplum_episode(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=datetime(2026, 5, 3, 17, 0, tzinfo=JOHANNESBURG),
        fall_away=False,
    )
    loan.in_duplum_ceiling_reached = True
    loan.in_duplum_ceiling_warning = "In-duplum ceiling reached."
    settlement = Settlement(servicing, compliance, documents)
    quoted = settlement.quote(
        agreement_id=record.agreement_id,
        as_of=DUE,
        delivered_on=DUE,
        request_on=DUE,
        recognised_at=datetime(2026, 5, 1, 14, 0, tzinfo=JOHANNESBURG),
        holidays=frozenset(),
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    done = settlement.execute(
        agreement_id=record.agreement_id,
        quote_id=quoted.quote_id,
        cents=quoted.amount_owing_cents,
        recognised_at=datetime(2026, 5, 1, 15, 0, tzinfo=JOHANNESBURG),
        interest_cap_present=True,
        vat_rate=VAT_RATE,
        idempotency_key="e2e-settle",
    )
    state.quoted = quoted
    state.done = done
    return state


def test_booking_stores_the_dummy_payload_and_freezes_identity() -> None:
    state = path("book")
    approval = state.approval
    record = state.record
    assert approval.application_number == "APP-00000001"
    assert approval.contractual_periodic_rate_bps == RATE_BPS
    assert approval.term_count == 2
    assert approval.payment_frequency is PaymentFrequency.MONTHLY
    assert approval.instalment_cents == INSTALMENT_CENTS
    assert approval.credit_life_premium_cents == CREDIT_LIFE_CENTS
    assert approval.short_term_rate_band is ShortTermRateBand.FIVE_PERCENT
    assert record.cash_advanced_cents == state.application.requested_amount_cents == CASH_CENTS
    assert record.resolved.base_rate == RATE
    assert record.frequency == "monthly"
    assert record.term_count == approval.term_count
    assert len(record.schedule) == approval.term_count
    assert record.contractual_instalment_cents == approval.instalment_cents
    assert record.application_number == approval.application_number
    assert record.short_term_rate_flag == "five_percent"
    assert record.rate_supplied_by_decision_engine is True
    assert record.short_term_rate_cap == RATE_CAP
    assert record.resolved.in_duplum_trigger == "collections_default"
    assert record.resolved.residual_write_off_threshold_cents == 10_000
    assert record.status == "pending_disbursement"
    assert record.frozen_full_name == NAME
    assert record.frozen_id_number == ID_NUMBER
    assert record.frozen_service_address == ADDRESS
    parent = state.servicing.ledger.store.get(ORG, record.ledger_loan_id)
    assert parent.frozen_full_name == NAME
    assert parent.frozen_id_number == ID_NUMBER
    assert parent.frozen_service_address == ADDRESS
    assert state.servicing.ledger.bucket_balance(parent, "principal") == 0
    assert type(record.cash_advanced_cents) is int
    assert type(record.contractual_instalment_cents) is int


def test_disbursement_posts_principal_at_midnight_johannesburg() -> None:
    state = path("disburse")
    parent = state.parent
    booking = next(
        item
        for item in state.servicing.ledger.store.transactions_for(ORG, parent.loan_id)
        if item.kind == "booking"
    )
    midnight = value_instant(ADVANCE)
    assert state.record.disbursement_value_date == ADVANCE
    assert booking.value_date == ADVANCE == value_date(DISBURSED_AT)
    assert midnight == datetime(2026, 4, 1, 0, 0, tzinfo=JOHANNESBURG)
    assert midnight.utcoffset() == timedelta(hours=2)
    assert state.servicing.ledger.bucket_balance(parent, "principal") == CASH_CENTS
    principal_debit = next(
        entry.debit_cents
        for entry in booking.entries
        if entry.bucket == "principal" and entry.debit_cents
    )
    assert principal_debit == CASH_CENTS
    assert type(principal_debit) is int
    assert state.record.frozen_full_name == NAME
    assert state.record.frozen_id_number == ID_NUMBER
    assert state.record.frozen_service_address == ADDRESS
    assert parent.frozen_full_name == NAME
    assert parent.frozen_id_number == ID_NUMBER
    assert parent.frozen_service_address == ADDRESS
    assert state.servicing.ledger.bucket_balance(state.child, "laybye_hold") == 0
    number = LoanNumberSeries().issue(
        organisation_id=ORG,
        application_number=state.approval.application_number,
        agreement_id=state.record.agreement_id,
        ledger_loan_id=parent.loan_id,
    )
    assert number.loan_number == "000000000001"
    assert number.application_number == "APP-00000001"


def test_interest_and_service_fee_are_billed_before_any_receipt() -> None:
    state = path("capitalise")
    parent = state.parent
    interest = state.servicing.ledger.bucket_balance(parent, "interest")
    service = state.servicing.ledger.bucket_balance(parent, "service")
    assert interest == to_cents(_accrued_rands(CASH_CENTS, ADVANCE, APRIL_END))
    assert service == _service(ADVANCE, opening=True)
    assert interest > 0 and service > 0
    assert type(interest) is int and type(service) is int
    kinds = [
        item.kind
        for item in state.servicing.ledger.store.transactions_for(ORG, parent.loan_id)
    ]
    assert "payment" not in kinds
    assert "interest_bill" in kinds
    assert "service_fee" in kinds


def test_receipt_follows_section_126_and_laybye_takes_only_the_remainder() -> None:
    state = path("receipt")
    parent = state.parent
    payment = state.payment
    loan_tx = state.servicing.ledger.store.get_transaction(ORG, payment.ledger_transaction_id)
    credits = [
        (entry.bucket, entry.credit_cents)
        for entry in loan_tx.entries
        if entry.bucket is not None and entry.credit_cents
    ]
    assert credits == [
        ("interest", state.due_interest),
        ("service", state.due_service),
        ("principal", DUE_PRINCIPAL_CENTS),
    ]
    assert payment.allocations[-1] == ("laybye_hold", LAYBYE_REMAINDER_CENTS)
    assert sum(amount for _bucket, amount in payment.allocations) == state.receipt_cents
    assert all(type(amount) is int for _bucket, amount in payment.allocations)
    bills = [
        item
        for item in state.servicing.ledger.store.transactions_for(ORG, parent.loan_id)
        if item.kind in {"interest_bill", "service_fee"} and item.value_date == DUE
    ]
    assert bills
    assert all(item.recognition_sequence < loan_tx.recognition_sequence for item in bills)
    assert all(item.recognised_at == value_instant(DUE) for item in bills)
    assert payment.value_date == DUE == value_date(PAID_AT)
    due_slice = next(item for item in parent.slices if item.due_on == DUE)
    later_slice = next(item for item in parent.slices if item.due_on == LATER_DUE)
    assert due_slice.remaining_cents == 0
    assert later_slice.remaining_cents == LATER_PRINCIPAL_CENTS
    assert state.servicing.ledger.bucket_balance(state.child, "laybye_hold") == LAYBYE_REMAINDER_CENTS
    assert state.servicing.ledger.bucket_balance(parent, "principal") == LATER_PRINCIPAL_CENTS


def test_statement_opening_matches_previous_closing_and_shows_the_ncr_number() -> None:
    state = path("statement")
    april = state.april
    may = state.may
    assert april.ncr_registration_number == NCR
    assert may.ncr_registration_number == NCR
    assert NCR.encode() in april.pdf_stub
    assert NCR.encode() in may.pdf_stub
    assert april.organisation_id == ORG and april.person_id == PERSON
    for section in may.loans:
        prior = next(item for item in april.loans if item.loan_id == section.loan_id)
        assert section.opening == prior.closing
        assert section.opening_source == "previous-closing"
        _integers(section.opening)
        _integers(section.closing)
    again = state.documents.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=ADVANCE,
        period_end=APRIL_END,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    assert again.statement_id == april.statement_id
    assert state.documents.statement_issued(ORG, PERSON, ADVANCE, APRIL_END) is True
    with pytest.raises(DocumentsError) as raised:
        state.documents.issue_statement(
            organisation_id=ORG,
            person_id=PERSON,
            period_start=date(2026, 4, 15),
            period_end=DUE,
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        )
    assert raised.value.code == "statement-exists"

    other = state.servicing.book(
        organisation_id=ORG,
        person_id=OTHER_PERSON,
        product=_product(),
        settings=_settings(),
        recognised_at=BOOKED_AT,
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key="e2e-other-person",
        rate_supplied_by_decision_engine=True,
        short_term_rate_cap=RATE_CAP,
        application_number="APP-00000002",
        contractual_instalment_cents=INSTALMENT_CENTS,
        term_count=1,
        short_term_rate_flag="five_percent",
    )
    state.servicing.disburse(other.agreement_id, recognised_at=DISBURSED_AT)
    other_statement = state.documents.issue_statement(
        organisation_id=ORG,
        person_id=OTHER_PERSON,
        period_start=ADVANCE,
        period_end=APRIL_END,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    assert other_statement.statement_id != april.statement_id
    assert {section.loan_id for section in other_statement.loans}.isdisjoint(
        {section.loan_id for section in april.loans}
    )

    state.compliance.put(_compliance(OTHER_ORG, OTHER_NCR))
    state.stub.full_name = NAME
    state.stub.id_number = ID_NUMBER
    state.stub.service_address = ADDRESS
    elsewhere = state.servicing.book(
        organisation_id=OTHER_ORG,
        person_id=PERSON,
        product=_product(),
        settings=_settings(),
        recognised_at=BOOKED_AT,
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key="e2e-other-org",
        rate_supplied_by_decision_engine=True,
        short_term_rate_cap=RATE_CAP,
        application_number="APP-00000003",
        contractual_instalment_cents=INSTALMENT_CENTS,
        term_count=1,
        short_term_rate_flag="five_percent",
    )
    state.servicing.disburse(elsewhere.agreement_id, recognised_at=DISBURSED_AT)
    elsewhere_statement = state.documents.issue_statement(
        organisation_id=OTHER_ORG,
        person_id=PERSON,
        period_start=ADVANCE,
        period_end=APRIL_END,
        interest_cap_present=True,
        vat_rate=VAT_RATE,
    )
    assert elsewhere_statement.statement_id != april.statement_id
    assert elsewhere_statement.ncr_registration_number == OTHER_NCR
    assert elsewhere_statement.organisation_id == OTHER_ORG


def test_reversal_restores_the_pre_receipt_balances_on_the_original_value_date() -> None:
    state = path("reverse")
    payment = state.servicing.payments[state.payment.payment_id]
    assert payment.reversal_value_date == payment.value_date == DUE
    assert value_instant(payment.reversal_value_date) == datetime(2026, 5, 1, 0, 0, tzinfo=JOHANNESBURG)
    reversal = state.servicing.ledger.store.get_transaction(ORG, payment.reversal_transaction_id)
    assert reversal.value_date == DUE
    assert reversal.value_date != value_date(REVERSED_AT)
    laybye_reversal = next(
        item
        for item in state.servicing.ledger.store.transactions_for(ORG, state.child.loan_id)
        if item.kind == "reversal"
    )
    assert laybye_reversal.value_date == DUE
    parent_now = _balances(state.servicing.ledger, state.parent)
    child_now = _balances(state.servicing.ledger, state.child)
    _integers(parent_now)
    _integers(child_now)
    assert parent_now == state.pre_parent
    assert child_now == state.pre_child
    assert parent_now["principal"] == CASH_CENTS
    assert parent_now["interest"] == state.due_interest
    assert parent_now["service"] == state.due_service
    assert child_now["laybye_hold"] == 0


def test_settlement_closes_the_open_in_duplum_episode() -> None:
    state = path("settle")
    loan = state.parent
    assert state.done.success is True
    assert state.done.balance_cents == 0
    assert type(state.done.amount_cents) is int
    assert state.record.status == "settled"
    assert loan.episodes[0].closed_on == DUE
    assert state.servicing.ledger._open_episode(loan) is None
    assert loan.in_duplum_ceiling_reached is False
    assert loan.in_duplum_ceiling_warning is None
    assert loan.discount_fallen_away is False
    assert state.servicing.ledger.bucket_balance(loan, "principal") == 0
    assert type(state.servicing.ledger.bucket_balance(loan, "principal")) is int
