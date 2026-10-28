"""Pins for regulatory extracts.

Identity, balances, and the NCR number are read from Layer 0. The extract
does not recompute them.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.dummies.decision_engine import DecisionEngineDummy
from lms.dummies.fixtures import FIXED_INSTALMENT_CENTS
from lms.dummies.enigma import EnigmaDummy
from lms.errors import EnigmaFailClosed
from lms.ledger.errors import LedgerError
from lms.ledger.service import Ledger
from lms.ports.decision_engine import Application, Approval, ConsumerIdentity, PaymentFrequency
from lms.ports.enigma import freeze_booking_identity
from lms.regulatory.audit import (
    AUDIT_CHAIN_HEAD_SQL,
    AUDIT_EVENT_SQL,
    AUDIT_PREDECESSOR_SQL,
    AuditLog,
    hash_row,
    read_lms_audit_event,
)
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.form39 import NOT_STORED, REGULATION_64, build_form39_readiness
from lms.regulatory.ncr import require_ncr_for_extract
from lms.regulatory.sacrra import (
    ACCOUNT_TYPE_FIELD_NUMBER,
    AMOUNT_FIELD_NUMBERS,
    L700_MONTHLY_FIELDS,
    MONTHS_IN_ARREARS_FIELD_NUMBER,
    STATUS_FIELD_NUMBER,
    build_sacrra_extract,
    render_l700_file,
)
from lms_config.calendar import value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import IN_DUPLUM_CLIP_POSTS, OrganisationSettings
from lms_config.templates import bnpl_zero, layby_goods, micro_short_term, unsecured_personal

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
    assert readiness.gross_book_cents == 80_000
    assert readiness.gross_book_cents_by_classification["short_term"] == 80_000
    assert readiness.agreements_disbursed_in_period == 1
    assert readiness.cash_advanced_cents_disbursed_in_period == 80_000
    assert readiness.not_stored == NOT_STORED
    for name in ("applications", "province", "gender", "income", "provisions", "write_offs", "age_analysis"):
        assert name in readiness.not_stored
        assert getattr(readiness, name) is None


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
    assert extract.predecessor_event_id is None
    assert extract.chain_head_last_event_id == second.event_id
    assert extract.chain_head_last_occurred_at == second.occurred_at
    assert extract.chain_head_last_hash == second.row_hash
    assert extract.chain_head_last_sequence == 2

    outside = log.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 2),
        to_date=date(2026, 3, 2),
    )
    assert len(outside.rows) == 1
    assert outside.rows[0].event_id == second.event_id
    assert outside.predecessor_event_id == first.event_id
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


def test_l700_layout_is_56_fields_and_no_file_is_emitted():
    ledger = Ledger()
    book(ledger)
    store = ComplianceStore()
    store.put(compliance_row())
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert extract.layout == L700_MONTHLY_FIELDS
    assert len(extract.layout) == 56
    assert extract.layout[0].start == 1
    assert extract.layout[-1].number == 56
    assert extract.layout[-1].end == 700
    assert all(field.value is None for field in extract.layout)
    by_number = {field.number: field for field in extract.layout}
    for number in AMOUNT_FIELD_NUMBERS:
        assert by_number[number].format == "N 9"
        assert by_number[number].value is None
    assert by_number[STATUS_FIELD_NUMBER].value is None
    assert by_number[MONTHS_IN_ARREARS_FIELD_NUMBER].value is None
    assert by_number[ACCOUNT_TYPE_FIELD_NUMBER].value is None
    assert extract.rows[0].principal_cents == 100_000
    assert extract.rows[0].amount_scale is None
    assert extract.file_bytes is None
    with pytest.raises(RegulatoryError) as refused:
        render_l700_file(extract)
    assert refused.value.code == "mandatory-fields-unlocked"


def test_frozen_identity_comes_from_the_enigma_booking_read_not_from_a_later_call():
    enigma = EnigmaDummy()
    identity = enigma.identity_for_booking("person-active")
    frozen = freeze_booking_identity(identity)
    context = enigma.organisation.context("org-active")
    assert not hasattr(context, "ncr_registration_number")
    ledger = Ledger()
    loan = book(
        ledger,
        organisation_id="org-active",
        person_id=identity.person_id,
        name=frozen.name,
        identity_number=frozen.id_number,
        address=frozen.service_address,
    )
    store = ComplianceStore()
    store.put(compliance_row(organisation_id="org-active", ncr="0000000000"))
    before = len(ledger.store.transactions_for("org-active"))
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-active",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert len(ledger.store.transactions_for("org-active")) == before
    row = extract.rows[0]
    assert row.loan_id == loan.loan_id
    assert row.frozen_full_name == frozen.name == "Test Consumer"
    assert row.frozen_id_number == frozen.id_number == "0000000000000"
    assert row.frozen_service_address == frozen.service_address == "1 Dummy Street, Johannesburg"
    assert extract.ncr_registration_number == "0000000000"
    with pytest.raises(EnigmaFailClosed) as failed:
        enigma.identity_for_booking("person-timeout")
    assert failed.value.reason.value == "timeout"
    again = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-active",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert again.rows[0].frozen_full_name == frozen.name


def test_blank_ncr_number_fails_closed_and_zeros_do_not():
    ledger = Ledger()
    book(ledger)

    class BlankCompliance:
        def find(self, organisation_id: str):
            del organisation_id
            return type("Row", (), {"ncr_registration_number": "   "})()

    with pytest.raises(RegulatoryError) as blank:
        require_ncr_for_extract(
            BlankCompliance(),
            organisation_id="org-a",
            classifications=("short_term",),
            pure_hosting=False,
        )
    assert blank.value.code == "ncr-number-unset"

    with pytest.raises(RegulatoryError) as unset:
        build_sacrra_extract(
            ledger,
            ComplianceStore(),
            organisation_id="org-a",
            as_of=date(2026, 3, 1),
            pure_hosting=None,
        )
    assert unset.value.code == "pure-hosting-unset"


def test_layby_goods_does_not_require_an_ncr_number():
    ledger = Ledger()
    book(ledger, product=layby_goods())
    extract = build_sacrra_extract(
        ledger,
        ComplianceStore(),
        organisation_id="org-a",
        as_of=date(2026, 3, 1),
        pure_hosting=False,
    )
    assert extract.ncr_registration_number is None
    assert extract.rows[0].classification == "cpa_layby"


def test_a_prepared_loan_is_not_an_opened_sacrra_account():
    ledger = Ledger()
    when = at(2026, 3, 1)
    ledger.prepare(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=when,
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 4, 1), 100_000),),
        identity_name="Thandi Nkosi",
        identity_number="8001015009087",
        service_address="12 Loop Street, Cape Town",
    )
    extract = build_sacrra_extract(
        ledger,
        ComplianceStore(),
        organisation_id="org-a",
        as_of=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert extract.rows == ()


def test_posted_interest_is_reported_and_the_in_duplum_clip_stays_off():
    ledger = Ledger()
    loan = book(ledger)
    ledger.open_in_duplum_episode(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2),
        fall_away=False,
    )
    ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=True,
    )
    ledger.bill_interest(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 3),
    )
    posted = ledger.bucket_balance(loan, "interest", as_of=date(2026, 3, 3))
    assert posted > 0
    assert IN_DUPLUM_CLIP_POSTS is False
    with pytest.raises(LedgerError) as clipped:
        ledger.clip_in_duplum()
    assert clipped.value.code == "in-duplum-clip-off"
    store = ComplianceStore()
    store.put(compliance_row())
    calls: list[str] = []
    ledger.clip_in_duplum = lambda: calls.append("clip")  # type: ignore[method-assign]
    extract = build_sacrra_extract(
        ledger,
        store,
        organisation_id="org-a",
        as_of=date(2026, 3, 3),
        pure_hosting=False,
    )
    assert calls == []
    assert extract.rows[0].bucket_cents["interest"] == posted
    assert "resolve_charge" not in inspect.getsource(build_sacrra_extract)
    assert "clip_in_duplum" not in inspect.getsource(build_sacrra_extract)


def test_form39_gross_book_uses_billed_buckets_and_leaves_unstored_cells_empty():
    enigma = EnigmaDummy()
    identity = enigma.identity_for_booking("person-active")
    engine = DecisionEngineDummy.fixed_success()
    decision = engine.decide(
        Application(
            consumer=ConsumerIdentity(
                person_id=identity.person_id,
                name=identity.name,
                id_number=identity.id_number,
            ),
            requested_amount_cents=100_000,
            product_type="short_term",
            term_count=1,
            payment_frequency=PaymentFrequency.MONTHLY,
        )
    )
    assert isinstance(decision, Approval)
    ledger = Ledger()
    parent = book(ledger, cash=100_000)
    ledger.open_laybye(
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 2),
        amount_cents=40_000,
        identity_name=parent.frozen_full_name,
        identity_number=parent.frozen_id_number,
        service_address=parent.frozen_service_address,
    )
    ledger.accrue_day(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=True,
    )
    store = ComplianceStore()
    store.put(compliance_row(ncr="0000000000"))
    unbilled = build_form39_readiness(
        ledger,
        store,
        organisation_id="org-a",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert "R15 million" in unbilled.filing_rule
    assert "15 February" in unbilled.filing_rule
    assert unbilled.filing_rule == REGULATION_64
    assert "threshold" not in inspect.signature(build_form39_readiness).parameters
    assert unbilled.gross_book_cents == 100_000
    assert unbilled.laybye_hold_cents == 40_000
    assert unbilled.applications is None
    assert decision.instalment_cents == FIXED_INSTALMENT_CENTS
    ledger.bill_interest(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 3),
    )
    billed = build_form39_readiness(
        ledger,
        store,
        organisation_id="org-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert billed.gross_book_cents == 100_000 + ledger.bucket_balance(parent, "interest", as_of=date(2026, 3, 31))
    assert billed.gross_book_cents > unbilled.gross_book_cents
    ledger.write_off_outstanding(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 20),
    )
    after_write_off = build_form39_readiness(
        ledger,
        store,
        organisation_id="org-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        pure_hosting=False,
    )
    assert after_write_off.gross_book_cents == 0
    assert after_write_off.write_offs is None
    assert after_write_off.laybye_hold_cents == 40_000


def test_audit_range_is_inclusive_on_the_johannesburg_day():
    log = AuditLog()
    inside = log.append(
        organisation_id="org-a",
        occurred_at=at(2026, 3, 2, 23),
        event_type="STATEMENT_ISSUED",
        category="operational",
        payload={},
    )
    outside = log.append(
        organisation_id="org-a",
        occurred_at=datetime(2026, 3, 2, 22, 30, tzinfo=timezone.utc),
        event_type="STATEMENT_ISSUED",
        category="operational",
        payload={},
    )
    window = log.extract(organisation_id="org-a", from_date=date(2026, 3, 2), to_date=date(2026, 3, 2))
    assert [row.event_id for row in window.rows] == [inside.event_id]
    next_day = log.extract(organisation_id="org-a", from_date=date(2026, 3, 3), to_date=date(2026, 3, 3))
    assert [row.event_id for row in next_day.rows] == [outside.event_id]
    assert next_day.predecessor_event_id == inside.event_id
    assert next_day.chain_head_last_event_id == outside.event_id
    assert next_day.head_covered is True
    assert window.head_covered is False
    assert window.chain_head_last_sequence == 2


def test_sql_audit_reader_uses_the_table_and_does_not_hash():
    occurred = at(2026, 3, 1, 9)
    later = at(2026, 3, 2, 9)
    first = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "organisation_id": "org-a",
        "occurred_at": occurred,
        "event_type": "PRINCIPAL_ADVANCED",
        "category": "financial",
        "recognition_sequence": 1,
        "amount_cents": 100_000,
        "balance_code": "principal",
        "payload": {"loan_id": "loan-1"},
        "previous_hash": None,
        "row_hash": b"\x01" * 32,
        "agreement_id": None,
        "enigma_person_id": None,
        "hash_matches": True,
    }
    second = {
        "event_id": "22222222-2222-2222-2222-222222222222",
        "organisation_id": "org-a",
        "occurred_at": later,
        "event_type": "STATEMENT_ISSUED",
        "category": "operational",
        "recognition_sequence": 2,
        "amount_cents": None,
        "balance_code": None,
        "payload": {"statement_id": "stmt-1"},
        "previous_hash": first["row_hash"],
        "row_hash": b"\x02" * 32,
        "agreement_id": None,
        "enigma_person_id": None,
        "hash_matches": True,
    }
    head = {
        "last_event_id": second["event_id"],
        "last_occurred_at": later,
        "last_hash": second["row_hash"],
        "last_sequence": 2,
    }
    calls: list[tuple[str, dict]] = []
    events = (first, second)

    def execute(sql: str, params: dict):
        calls.append((sql, params))
        if "FROM lms.audit_chain_head" in sql:
            return [head]
        if "recognition_sequence <" in sql:
            return [first]
        start = params["from_instant"]
        end = params["to_instant"]
        return [row for row in events if start <= row["occurred_at"] < end]

    extract = read_lms_audit_event(
        execute,
        organisation_id="org-a",
        from_date=date(2026, 3, 2),
        to_date=date(2026, 3, 2),
    )
    assert "lms.audit_event" in AUDIT_EVENT_SQL
    assert "ORDER BY event.recognition_sequence" in AUDIT_EVENT_SQL
    assert "public.digest" in AUDIT_EVENT_SQL
    assert "lms.audit_chain_head" in AUDIT_CHAIN_HEAD_SQL
    assert "recognition_sequence <" in AUDIT_PREDECESSOR_SQL
    assert calls[0][1]["from_instant"] == value_instant(date(2026, 3, 2))
    assert calls[0][1]["to_instant"] == value_instant(date(2026, 3, 3))
    assert extract.rows[0].event_id == second["event_id"]
    assert extract.rows[0].previous_hash == first["row_hash"]
    assert extract.rows[0].recognition_sequence == 2
    assert extract.predecessor_event_id == first["event_id"]
    assert extract.predecessor_row_hash == first["row_hash"]
    assert extract.chain_head_last_event_id == second["event_id"]
    assert extract.chain_head_last_hash == second["row_hash"]
    assert extract.chain_head_last_sequence == 2
    assert extract.verified is True

    broken = dict(second)
    broken["hash_matches"] = False

    def execute_broken(sql: str, params: dict):
        del params
        if "FROM lms.audit_chain_head" in sql:
            return [head]
        if "recognition_sequence <" in sql:
            return [first]
        return [broken]

    failed = read_lms_audit_event(
        execute_broken,
        organisation_id="org-a",
        from_date=date(2026, 3, 2),
        to_date=date(2026, 3, 2),
    )
    assert failed.hashes_ok is False
    assert failed.verified is False
    assert failed.rows[0].row_hash == second["row_hash"]
