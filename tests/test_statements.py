"""Statements and documents. Amounts come from the ledger and the engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.calendar import binding_until, is_business_day
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.statements.errors import DocumentsError
from lms.statements.service import Documents, RecognisedReceipt
from lms_config.calendar import add_business_days
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.exceptions import CalculationInputError
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
DUE = date(2026, 6, 15)


def at(day: int, hour: int = 9, month: int = 3) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=JOHANNESBURG)


def settings() -> OrganisationSettings:
    return OrganisationSettings(
        leniency_days=1,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
    )


def compliance(organisation_id: str = "org-a", **overrides) -> ProviderCompliance:
    values = dict(
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
    values.update(overrides)
    return ProviderCompliance(**values)


def documents(svc: Servicing | None = None) -> tuple[Documents, Servicing, ComplianceStore]:
    svc = svc or Servicing(enigma=EnigmaStub())
    store = ComplianceStore()
    store.put(compliance())
    return Documents(svc, store), svc, store


def book_and_disburse(svc: Servicing, *, key: str = "book-1", person_id: str = "person-a", organisation_id: str = "org-a", product=None):
    record = svc.book(
        organisation_id=organisation_id,
        person_id=person_id,
        product=product or micro_short_term(),
        settings=settings(),
        recognised_at=at(1, 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key=key,
    )
    return svc.disburse(record.agreement_id, recognised_at=at(1, 10))


def issue(docs: Documents, record, **overrides):
    payload = dict(
        organisation_id=record.organisation_id,
        person_id=record.person_id,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    payload.update(overrides)
    return docs.issue_statement(**payload)


def test_missing_vat_rate_posts_nothing():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    with pytest.raises(DocumentsError) as raised:
        issue(docs, record, vat_rate=None)
    assert raised.value.code == "vat-rate-unset"
    kinds = {item.kind for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)}
    assert kinds == {"booking"}
    assert docs.statements == {}


def test_opening_balance_equals_previous_closing():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    march = issue(docs, record)
    april = issue(
        docs,
        record,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    assert len(march.loans) == 1
    assert april.loans[0].loan_id == march.loans[0].loan_id
    assert april.loans[0].opening == march.loans[0].closing
    assert april.loans[0].opening_source == "previous-closing"
    assert april.loans[0].opening["principal"] == march.loans[0].closing["principal"]
    assert april.loans[0].opening["interest"] == march.loans[0].closing["interest"]
    assert april.loans[0].opening["laybye_hold"] == march.loans[0].closing["laybye_hold"]


def test_statement_date_capitalises_before_allocating_the_days_receipt():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    statement_day = date(2026, 3, 31)
    issued = issue(
        docs,
        record,
        receipts=(
            RecognisedReceipt(
                agreement_id=record.agreement_id,
                cents=1,
                recognised_at=at(31, 15),
                attributed_due_on=DUE,
                idempotency_key="pay-statement-day",
            ),
        ),
    )
    loan = svc.ledger.store.get(record.organisation_id, record.ledger_loan_id)
    transactions = svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id)
    bills = [item for item in transactions if item.kind == "interest_bill" and item.value_date == statement_day]
    payments = [item for item in transactions if item.kind == "payment" and item.value_date == statement_day]
    assert len(bills) == 1
    assert len(payments) == 1
    assert bills[0].recognition_sequence < payments[0].recognition_sequence
    matched = next(item for item in svc.payments.values() if item.ledger_transaction_id == payments[0].transaction_id)
    assert matched.allocations == (("interest", 1),)
    assert issued.loans[0].closing["principal"] == 100_000
    assert svc.ledger.bucket_balance(loan, "principal") == 100_000
    assert issued.loans[0].closing["interest"] == svc.ledger.bucket_balance(loan, "interest")
    assert issued.loans[0].closing["interest"] != issued.loans[0].closing["principal"]
    again = issue(docs, record)
    assert again.statement_id == issued.statement_id
    assert again.pdf_sha256 == issued.pdf_sha256
    assert sum(1 for item in svc.ledger.store.transactions_for(record.organisation_id, record.ledger_loan_id) if item.kind == "payment") == 1


def test_one_statement_per_client_per_organisation():
    docs, svc, store = documents()
    store.put(compliance("org-b", legal_name="Other Credit (Pty) Ltd", ncr_registration_number="NCRCP111"))
    first = book_and_disburse(svc, key="a", person_id="person-a", organisation_id="org-a")
    second = book_and_disburse(svc, key="b", person_id="person-b", organisation_id="org-a")
    other_org = book_and_disburse(svc, key="c", person_id="person-a", organisation_id="org-b")
    left = issue(docs, first)
    right = issue(docs, second)
    abroad = issue(docs, other_org)
    assert left.person_id == "person-a"
    assert right.person_id == "person-b"
    assert abroad.organisation_id == "org-b"
    assert {loan.loan_id for loan in left.loans} == {first.ledger_loan_id}
    assert {loan.loan_id for loan in right.loans} == {second.ledger_loan_id}
    assert abroad.ncr_registration_number == "NCRCP111"
    with pytest.raises(DocumentsError) as raised:
        issue(docs, first, period_start=date(2026, 3, 15), period_end=date(2026, 4, 15))
    assert raised.value.code == "statement-exists"


def test_provider_legal_name_and_ncr_number_come_from_lms_configuration():
    stub = EnigmaStub()
    svc = Servicing(enigma=stub)
    docs, svc, _store = documents(svc)
    record = book_and_disburse(svc)
    stub.full_name = "Changed In Enigma"
    issued = issue(docs, record)
    assert issued.legal_name == "North Credit (Pty) Ltd"
    assert issued.ncr_registration_number == "NCRCP999"
    assert issued.trading_name == "North Credit"
    assert issued.physical_address == "1 Long Street, Cape Town"
    assert issued.telephone == "0210000000"
    assert issued.bank_account_number == "123456789"
    assert issued.loans[0].frozen_full_name == "Ada Borrower"
    assert issued.legal_name != stub.full_name


def test_missing_compliance_fields_fail_closed():
    docs, svc, store = documents()
    record = book_and_disburse(svc, organisation_id="org-missing", key="missing")
    with pytest.raises(DocumentsError) as raised:
        issue(docs, record)
    assert raised.value.code == "compliance-missing"
    with pytest.raises(CalculationInputError, match="ncr_registration_number"):
        store.put(compliance(ncr_registration_number=""))
    with pytest.raises(CalculationInputError, match="legal_name"):
        store.put(compliance(legal_name="  "))
    with pytest.raises(CalculationInputError, match="telephone"):
        store.put(compliance(telephone=""))
    with pytest.raises(CalculationInputError, match="bank_name"):
        store.put(compliance(bank_name=""))


def test_balances_keep_principal_interest_fees_and_laybye_hold_apart():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    loan = svc.ledger.store.get(record.organisation_id, record.ledger_loan_id)
    child = svc.ledger.open_laybye(
        organisation_id=record.organisation_id,
        parent_loan_id=loan.loan_id,
        recognised_at=at(2, 9),
        amount_cents=5_000,
        identity_name=loan.frozen_full_name,
        identity_number=loan.frozen_id_number,
        service_address=loan.frozen_service_address,
    )
    issued = issue(docs, record)
    sections = {section.loan_id: section for section in issued.loans}
    parent = sections[loan.loan_id]
    hold = sections[child.loan_id]
    assert parent.closing["principal"] == 100_000
    assert parent.closing["laybye_hold"] == 0
    assert hold.closing["laybye_hold"] == 5_000
    assert parent.closing["principal"] == svc.ledger.bucket_balance(loan, "principal")
    assert parent.closing["interest"] >= 0
    assert "service" in parent.closing
    assert parent.base_rate == Decimal("0.05")
    assert parent.discount_rate == Decimal(0)
    assert parent.nominal_annual_on_base == Decimal("0.05") * 12
    assert parent.annual_rate_cell is None
    assert parent.arrears_cents is None
    assert parent.legal_fees_cents is None
    assert issued.pdf_stub.startswith(b"PDF-STUB\n")


def test_campaign_base_rate_and_discount_are_both_shown():
    product = micro_short_term()
    instrument = product.instruments[0]
    product = replace(
        product,
        instruments=(
            replace(
                instrument,
                base_rate=Decimal("0.05"),
                discount_rate=Decimal("0.02"),
                monthly_rate=Decimal("0.03"),
            ),
        ),
    )
    docs, svc, _store = documents()
    record = book_and_disburse(svc, product=product, key="campaign")
    issued = issue(docs, record)
    section = issued.loans[0]
    assert section.base_rate == Decimal("0.05")
    assert section.discount_rate == Decimal("0.02")
    assert section.periodic_rate_in_force == Decimal("0.03")
    assert section.nominal_annual_on_base == Decimal("0.60")
    assert section.nominal_annual_on_effective == Decimal("0.36")
    assert section.annual_rate_cell is None


def test_enquiry_does_not_move_the_section_109_chain():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    march = issue(docs, record)
    keys_before = svc.ledger.store.statement_keys(record.organisation_id, record.person_id)
    enquiry = docs.enquire(
        organisation_id=record.organisation_id,
        person_id=record.person_id,
        loan_id=record.ledger_loan_id,
        request_on=date(2026, 4, 15),
        holidays=frozenset(),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert svc.ledger.store.statement_keys(record.organisation_id, record.person_id) == keys_before
    assert enquiry.components["principal"] == 100_000
    assert enquiry.components["laybye_hold"] == 0
    april = issue(docs, record, period_start=date(2026, 4, 1), period_end=date(2026, 4, 30))
    assert april.loans[0].opening == march.loans[0].closing
    assert enquiry.deliver_by == add_business_days(date(2026, 4, 15), 10, frozenset())


def test_settlement_quote_is_zero_early_termination_and_binds_for_five_business_days():
    docs, svc, _store = documents()
    record = book_and_disburse(svc)
    delivered = date(2026, 4, 15)
    request = date(2026, 4, 10)
    holidays: frozenset[date] = frozenset()
    quote = docs.settlement_quote(
        agreement_id=record.agreement_id,
        as_of=delivered,
        delivered_on=delivered,
        request_on=request,
        holidays=holidays,
        vat_rate=Decimal("0.15"),
    )
    assert quote.early_termination_cents == 0
    assert quote.valid_until == binding_until(delivered, holidays)
    assert quote.deliver_by == add_business_days(request, 5, holidays)
    assert quote.total_cents == quote.principal_cents + quote.interest_cents + quote.fee_cents
    counted = delivered
    left = 5
    while left:
        counted += timedelta(days=1)
        if is_business_day(counted, holidays):
            left -= 1
    assert quote.valid_until == counted
    assert svc.ledger.store.statement_keys(record.organisation_id, record.person_id) == ()
    again = docs.settlement_quote(
        agreement_id=record.agreement_id,
        as_of=delivered,
        delivered_on=delivered,
        request_on=request,
        holidays=holidays,
        vat_rate=Decimal("0.15"),
    )
    assert again == quote
