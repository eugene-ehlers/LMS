"""Pins for regulatory extracts.

Identity, balances, and the NCR number are read from Layer 0. The extract
does not recompute them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.ledger.service import Ledger
from lms.regulatory.audit import AuditLog, hash_row
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.form39 import NOT_STORED, build_form39_readiness
from lms.regulatory.sacrra import build_sacrra_extract
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings
from lms_config.templates import bnpl_zero, micro_short_term, unsecured_personal

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")


def at(year: int, month: int, day: int, hour: int = 8) -> datetime:
    return datetime(year, month, day, hour, tzinfo=JOHANNESBURG)


def settings() -> OrganisationSettings:
    return OrganisationSettings(
        leniency_days=0,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
    )


def book(
    ledger: Ledger,
    *,
    organisation_id: str = "org-a",
    person_id: str = "person-a",
    when: datetime | None = None,
    cash: int = 100_000,
    product=None,
    name: str = "Thandi Nkosi",
    identity_number: str = "8001015009087",
    address: str = "12 Loop Street, Cape Town",
):
    when = when or at(2026, 3, 1)
    return ledger.book(
        organisation_id=organisation_id,
        person_id=person_id,
        product=product or micro_short_term(),
        organisation=settings(),
        recognised_at=when,
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((date(2026, 4, 1), cash),),
        identity_name=name,
        identity_number=identity_number,
        service_address=address,
    )


def compliance_row(organisation_id: str = "org-a", ncr: str = "NCRCP999") -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=organisation_id,
        legal_name="Cape Credit (Pty) Ltd",
        ncr_registration_number=ncr,
        trading_name="Cape Credit",
        physical_address="1 Adderley Street, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0210000000",
        bank_name="Example Bank",
        bank_account_number="123456789",
        branch_code="051001",
        payment_reference="CC-REF",
    )


def test_identity_fields_come_from_the_frozen_agreement():
    ledger = Ledger()
    loan = book(ledger)
    store = ComplianceStore()
    store.put(compliance_row())
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert len(extract.rows) == 1
    row = extract.rows[0]
    assert row.frozen_full_name == loan.frozen_full_name == "Thandi Nkosi"
    assert row.frozen_id_number == loan.frozen_id_number == "8001015009087"
    assert row.frozen_service_address == loan.frozen_service_address == "12 Loop Street, Cape Town"
    assert row.loan_id == loan.loan_id


def test_balances_come_from_the_ledger_on_the_supplied_value_date():
    ledger = Ledger()
    loan = book(ledger, cash=100_000)
    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=25_000,
        recognised_at=at(2026, 3, 10),
        attributed_due_on=date(2026, 4, 1),
    )
    store = ComplianceStore()
    store.put(compliance_row())
    before_payment = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    on_payment = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 10),
        pure_hosting=False,
    )
    assert before_payment.rows[0].principal_cents == ledger.bucket_balance(
        loan, "principal", as_of=date(2026, 3, 1)
    )
    assert before_payment.rows[0].principal_cents == 100_000
    assert on_payment.rows[0].principal_cents == ledger.bucket_balance(
        loan, "principal", as_of=date(2026, 3, 10)
    )
    assert on_payment.rows[0].principal_cents == 75_000
    assert before_payment.file_bytes is None
    assert on_payment.rows[0].status_code is None
    assert on_payment.rows[0].months_in_arrears is None
    assert on_payment.rows[0].account_type_code is None


def test_unbilled_interest_memo_stays_out_until_billed():
    ledger = Ledger()
    loan = book(ledger)
    ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=True,
    )
    store = ComplianceStore()
    store.put(compliance_row())
    unbilled = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 2),
        pure_hosting=False,
    )
    assert unbilled.rows[0].bucket_cents["interest"] == 0
    ledger.bill_interest(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 3),
    )
    billed = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 3),
        pure_hosting=False,
    )
    assert billed.rows[0].bucket_cents["interest"] == ledger.bucket_balance(
        loan, "interest", as_of=date(2026, 3, 3)
    )
    assert billed.rows[0].bucket_cents["interest"] > 0


def test_linked_laybye_is_one_parent_row_and_hold_is_not_subtracted():
    ledger = Ledger()
    parent = book(ledger, cash=100_000)
    child = ledger.open_laybye(
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 2),
        amount_cents=40_000,
        identity_name=parent.frozen_full_name,
        identity_number=parent.frozen_id_number,
        service_address=parent.frozen_service_address,
    )
    store = ComplianceStore()
    store.put(compliance_row())
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 2),
        pure_hosting=False,
    )
    assert len(extract.rows) == 1
    row = extract.rows[0]
    assert row.loan_id == parent.loan_id
    assert row.loan_id != child.loan_id
    assert row.principal_cents == 100_000
    assert row.laybye_hold_cents == 40_000
    assert row.principal_cents - row.laybye_hold_cents != row.principal_cents
    assert row.bucket_cents["principal"] == 100_000


def test_ncr_number_comes_from_lms_configuration():
    ledger = Ledger()
    book(ledger, product=unsecured_personal(), cash=200_000)
    store = ComplianceStore()
    store.put(compliance_row(ncr="NCRCP12345"))
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert extract.ncr_registration_number == "NCRCP12345"
    readiness = build_form39_readiness(
        ledger,
        store,
        organisation_id="org-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert readiness.ncr_registration_number == "NCRCP12345"
    assert readiness.legal_name == "Cape Credit (Pty) Ltd"


def test_missing_ncr_number_fails_closed_for_micro_and_unsecured():
    ledger = Ledger()
    book(ledger)
    store = ComplianceStore()
    with pytest.raises(RegulatoryError) as micro:
        build_sacrra_extract(
            ledger,
            store,
            organisation_id="org-a",
            as_of=date(2026, 3, 1),
            pure_hosting=False,
        )
    assert micro.value.code == "ncr-number-unset"

    other = Ledger()
    book(other, product=unsecured_personal(), cash=200_000)
    with pytest.raises(RegulatoryError) as personal:
        build_form39_readiness(
            other,
            ComplianceStore(),
            organisation_id="org-a",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            pure_hosting=False,
        )
    assert personal.value.code == "ncr-number-unset"


def test_laybye_bnpl_and_pure_hosting_do_not_require_an_ncr_number():
    ledger = Ledger()
    book(ledger, product=bnpl_zero())
    extract = build_sacrra_extract(
        ledger,
        ComplianceStore(),
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert extract.ncr_registration_number is None
    assert extract.rows[0].classification == "zero_cost"

    hosted = Ledger()
    book(hosted)
    hosted_extract = build_sacrra_extract(
        hosted,
        ComplianceStore(),
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=True,
    )
    assert hosted_extract.ncr_registration_number is None
    assert hosted_extract.rows[0].classification == "short_term"


def test_form39_lists_sourced_balances_and_does_not_invent_missing_elements():
    ledger = Ledger()
    book(ledger, cash=80_000)
    store = ComplianceStore()
    store.put(compliance_row())
    readiness = build_form39_readiness(
        ledger,
        store,
        organisation_id="org-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert readiness.gross_owed_cents == 80_000
    assert readiness.gross_owed_cents_by_classification["short_term"] == 80_000
    assert readiness.agreements_disbursed_in_period == 1
    assert readiness.cash_advanced_cents_disbursed_in_period == 80_000
    assert readiness.not_stored == NOT_STORED
    for name in ("applications", "province", "gender", "income", "provisions", "write_offs", "age_analysis"):
        assert name in readiness.not_stored
        assert not hasattr(readiness, name)


def test_audit_extract_includes_hash_chain_fields_and_verifies():
    log = AuditLog()
    first = log.append(
        organisation_id="org-a",
        occurred_at=at(2026, 3, 1, 9),
        event_type="PRINCIPAL_ADVANCED",
        category="financial",
        amount_cents=100_000,
        balance_code="principal",
        payload={"loan_id": "loan-1"},
    )
    second = log.append(
        organisation_id="org-a",
        occurred_at=at(2026, 3, 2, 9),
        event_type="STATEMENT_ISSUED",
        category="operational",
        payload={"statement_id": "stmt-1"},
    )
    log.append(
        organisation_id="org-b",
        occurred_at=at(2026, 3, 1, 9),
        event_type="PRINCIPAL_ADVANCED",
        category="financial",
        amount_cents=1,
        balance_code="principal",
    )
    extract = log.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 2),
    )
    assert len(extract.rows) == 2
    assert extract.rows[0].previous_hash is None
    assert extract.rows[0].row_hash == first.row_hash
    assert extract.rows[0].recognition_sequence == 1
    assert extract.rows[1].previous_hash == first.row_hash
    assert extract.rows[1].row_hash == second.row_hash
    assert extract.rows[1].recognition_sequence == 2
    assert extract.verified is True
    assert extract.hashes_ok is True
    assert extract.links_ok is True
    assert extract.head_covered is True
    assert extract.chain_head_last_hash == second.row_hash
    assert extract.chain_head_last_sequence == 2

    outside = log.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 2),
        to_date=date(2026, 3, 2),
    )
    assert len(outside.rows) == 1
    assert outside.rows[0].event_id == second.event_id
    assert outside.predecessor_row_hash == first.row_hash
    assert outside.predecessor_recognition_sequence == 1
    assert outside.verified is True
    assert outside.head_covered is True

    tampered = replace(extract.rows[1], amount_cents=1)
    assert hash_row(
        organisation_id=tampered.organisation_id,
        event_id=tampered.event_id,
        previous_hash=tampered.previous_hash,
        event_type=tampered.event_type,
        occurred_at=tampered.occurred_at,
        amount_cents=tampered.amount_cents,
        balance_code=tampered.balance_code,
        recognition_sequence=tampered.recognition_sequence,
        payload=tampered.payload,
    ) != tampered.row_hash
    index = next(i for i, row in enumerate(log._rows) if row.event_id == second.event_id)
    log._rows[index] = replace(log._rows[index], row_hash=b"\x00" * 32)
    broken = log.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 2),
    )
    assert broken.hashes_ok is False
    assert broken.verified is False
    assert broken.rows[0].previous_hash is None
    assert broken.rows[1].recognition_sequence == 2
