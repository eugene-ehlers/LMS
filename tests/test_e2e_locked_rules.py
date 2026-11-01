"""End-to-end checks for the locked rules.

Seven cases. Each one asserts integer cents, a recognition date of 00:00
Africa/Johannesburg, an amount inside the applicable NCA cap, and a missing
election or configuration row that fails closed.

The three smoke failures listed in ``docs/testing/known-open-sequencing-gaps.md``
stay failing. This file does not change a locked calculation, allocation, or
statement rule to make them pass. The statement case posts the receipt on a
later recognition date than the capitalisation, which is the order the lock
already allows when the two events are not the same day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.fees import initiation_cap_ex_vat_cents
from lms.calc.models import SERVICE_FEE_MONTHLY_CAP_CENTS, SHORT_TERM_FIRST_MONTHLY
from lms.collections.authority import RandCeiling
from lms.collections.errors import CollectionsError
from lms.collections.service import Collections
from lms.ledger.errors import LedgerError
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing
from lms.staff.api import dispatch
from lms.staff.authority import ROLE_ELECTIONS_WRITE
from lms.staff.service import StaffOffice
from lms.statements.errors import DocumentsError
from lms.statements.service import Documents
from lms_config.brand import Brand, BrandStore
from lms_config.calendar import value_date, value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import IN_DUPLUM_CLIP_POSTS, OrganisationSettings
from lms_config.statute import SHORT_TERM_DEFERRED_CENTS
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"
FROZEN_ID = "8001015800085"
SERVICE_FEE_WITH_VAT_CENTS = 6_900


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


def settings(**overrides) -> OrganisationSettings:
    values = dict(
        leniency_days=3,
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


def compliance(organisation_id: str = ORG) -> ProviderCompliance:
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


def assert_missing_election_fails_closed() -> None:
    """A required election that is null stores nothing."""
    svc = Servicing(enigma=EnigmaStub())
    with pytest.raises(ServicingError) as caught:
        svc.book(
            organisation_id=ORG,
            person_id=PERSON,
            product=micro_short_term(),
            settings=settings(leniency_days=None),
            recognised_at=at(date(2026, 4, 1), 8),
            cash_advanced_cents=200_000,
            frequency="monthly",
            schedule=((date(2026, 5, 1), 200_000),),
            initiation_fee_cents=0,
            idempotency_key="missing-leniency",
            application_number="APP-MISSING",
        )
    assert caught.value.code == "election-unset"
    assert svc.agreements == {}
    assert svc.ledger.store.accounts_for(ORG) == ()
    assert svc.ledger.store._loan_serial.get(ORG, 0) == 0


def assert_locked_money(servicing: Servicing, *records) -> None:
    assert_missing_election_fails_closed()
    for record in records:
        assert type(record.cash_advanced_cents) is int
        assert type(record.initiation_fee_cents) is int
        assert record.cash_advanced_cents > 0
        assert record.cash_advanced_cents + record.initiation_fee_cents <= SHORT_TERM_DEFERRED_CENTS
        assert record.initiation_fee_cents <= initiation_cap_ex_vat_cents(record.cash_advanced_cents)
        assert record.resolved.base_rate <= SHORT_TERM_FIRST_MONTHLY
        instant = value_instant(record.booking_value_date)
        assert (instant.hour, instant.minute, instant.second) == (0, 0, 0)
        assert instant.tzinfo == JOHANNESBURG
        assert value_date(record.recognised_at) == record.booking_value_date
        if record.ledger_loan_id is None:
            continue
        loan = servicing.ledger.store.get(record.organisation_id, record.ledger_loan_id)
        monthly_interest_cap = (loan.cash_advanced_cents * 5) // 100
        for charge in loan.charges:
            assert type(charge.remaining_cents) is int
            assert type(charge.ex_vat_cents) is int
            assert type(charge.vat_cents) is int
            if charge.bucket == "service":
                assert charge.ex_vat_cents <= SERVICE_FEE_MONTHLY_CAP_CENTS
                assert charge.ex_vat_cents + charge.vat_cents <= SERVICE_FEE_WITH_VAT_CENTS
            if charge.bucket == "interest":
                assert charge.ex_vat_cents <= monthly_interest_cap
        for bucket in ("principal", "interest", "service", "initiation", "laybye_hold"):
            assert type(servicing.ledger.bucket_balance(loan, bucket)) is int


def _book(
    svc: Servicing,
    *,
    key: str,
    application_number: str,
    cash: int = 200_000,
    when: datetime | None = None,
    person_id: str = PERSON,
    **overrides,
):
    recognised_at = when or at(date(2026, 4, 1), 9)
    due = date(2026, 5, 1)
    record = svc.book(
        organisation_id=ORG,
        person_id=person_id,
        product=micro_short_term(),
        settings=settings(**overrides),
        recognised_at=recognised_at,
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((due, cash),),
        initiation_fee_cents=0,
        idempotency_key=key,
        application_number=application_number,
    )
    return record


def test_book_and_disburse_a_short_term_loan():
    svc = Servicing(enigma=EnigmaStub())
    # 22:30 UTC on 31 March is 00:30 on 1 April in Johannesburg.
    recognised_at = datetime(2026, 3, 31, 22, 30, tzinfo=timezone.utc)
    record = _book(svc, key="book-1", application_number="APP-1001", when=recognised_at)
    assert record.application_number == "APP-1001"
    assert record.loan_number is None
    assert record.booking_value_date == date(2026, 4, 1)
    assert value_instant(record.booking_value_date).hour == 0
    assert record.status == "pending_disbursement"
    assert svc.ledger.store.accounts_for(ORG) == ()

    active = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    assert active.loan_number == "000000000000000001"
    loan = svc.ledger.store.get(ORG, active.ledger_loan_id)
    assert loan.loan_number == active.loan_number
    assert loan.application_number == "APP-1001"
    assert loan.instrument_kind == "loan"
    assert type(svc.ledger.bucket_balance(loan, "principal")) is int
    assert svc.ledger.bucket_balance(loan, "principal") == 200_000

    with pytest.raises(ServicingError) as duplicate:
        _book(svc, key="book-dup", application_number="APP-1001")
    assert duplicate.value.code == "application-already-booked"
    assert len(svc.agreements) == 1
    assert svc.ledger.store._loan_serial[ORG] == 1

    with pytest.raises(ServicingError) as missing:
        svc.book(
            organisation_id=ORG,
            person_id=PERSON,
            product=micro_short_term(),
            settings=settings(leniency_days=None),
            recognised_at=at(date(2026, 4, 2), 9),
            cash_advanced_cents=200_000,
            frequency="monthly",
            schedule=((date(2026, 5, 1), 200_000),),
            initiation_fee_cents=0,
            idempotency_key="missing-on-this-book",
            application_number="APP-MISSING",
        )
    assert missing.value.code == "election-unset"
    assert "APP-MISSING" not in {item.application_number for item in svc.agreements.values()}

    second = _book(
        svc, key="book-2", application_number="APP-1002", cash=100_000, person_id="person-b"
    )
    second = svc.disburse(second.agreement_id, recognised_at=at(date(2026, 4, 1), 11))
    assert second.loan_number == "000000000000000002"
    assert int(second.loan_number) == int(active.loan_number) + 1
    assert_locked_money(svc, active, second)


def test_statement_then_payment_uses_section_126_and_chains_the_opening():
    svc = Servicing(enigma=EnigmaStub())
    record = _book(svc, key="stmt", application_number="APP-STMT")
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    store = ComplianceStore()
    store.put(compliance())
    docs = Documents(svc, store)

    april = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    section = next(item for item in april.loans if item.instrument_kind == "loan")
    assert all(type(cents) is int for cents in section.opening.values())
    assert all(type(cents) is int for cents in section.closing.values())
    assert section.closing["principal"] == 200_000
    assert section.closing["interest"] == 10_000
    assert section.closing["service"] == SERVICE_FEE_WITH_VAT_CENTS
    assert value_instant(april.statement_date) == datetime(2026, 4, 30, 0, 0, tzinfo=JOHANNESBURG)

    payment = svc.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=10_000 + SERVICE_FEE_WITH_VAT_CENTS + 5_000,
        recognised_at=at(date(2026, 5, 2), 11),
        idempotency_key="pay-after-statement",
        agreement_id=record.agreement_id,
        attributed_due_on=date(2026, 5, 1),
    )
    assert payment.value_date == date(2026, 5, 2)
    assert value_instant(payment.value_date).tzinfo == JOHANNESBURG
    assert payment.allocations == (
        ("interest", 10_000),
        ("service", SERVICE_FEE_WITH_VAT_CENTS),
        ("principal", 5_000),
    )
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)
    bill = next(
        item
        for item in svc.ledger.store.transactions_for(ORG, loan.loan_id)
        if item.kind == "interest_bill"
    )
    paid = svc.ledger.store.get_transaction(ORG, payment.ledger_transaction_id)
    assert bill.value_date < paid.value_date
    assert bill.recognition_sequence < paid.recognition_sequence

    may = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 2),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    may_section = next(item for item in may.loans if item.loan_id == section.loan_id)
    assert may_section.opening == section.closing
    assert may_section.opening_source == "previous-closing"
    assert may_section.closing["interest"] == 0
    assert may_section.closing["service"] == 0
    assert may_section.closing["principal"] == 195_000
    assert_locked_money(svc, record)


def test_linked_laybye_holds_the_receipt_and_charges_interest_on_the_net_balance():
    svc = Servicing(enigma=EnigmaStub())
    record = svc.book_linked_laybye(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=200_000,
        frequency="monthly",
        schedule=((date(2026, 5, 1), 200_000),),
        initiation_fee_cents=0,
        idempotency_key="laybye",
        application_number="APP-LAYBYE",
        pre_disbursement_cents=20_000,
        pre_disbursement_at=at(date(2026, 4, 1), 8),
    )
    parent = svc.ledger.store.get(ORG, record.ledger_loan_id)
    child = svc.ledger.store.get(ORG, record.laybye_loan_id)
    assert parent.disbursement_value_date is None
    assert svc.ledger.bucket_balance(parent, "principal") == 0
    assert svc.ledger.bucket_balance(child, "laybye_hold") == 20_000
    deposit = next(
        item
        for item in svc.ledger.store.transactions_for(ORG, child.loan_id)
        if item.kind == "laybye_deposit"
    )
    assert deposit.amount_cents == 20_000
    assert deposit.value_date == date(2026, 4, 1)
    assert value_instant(deposit.value_date).hour == 0
    assert child.loan_number == parent.loan_number
    assert child.instrument_kind == "laybye_hold"
    assert parent.instrument_kind == "loan"

    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    assert svc.ledger.bucket_balance(parent, "principal") == 200_000
    assert svc.ledger.bucket_balance(child, "laybye_hold") == 20_000
    store = ComplianceStore()
    store.put(compliance())
    docs = Documents(svc, store)
    issued = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    parent_section = next(item for item in issued.loans if item.loan_id == parent.loan_id)
    child_section = next(item for item in issued.loans if item.loan_id == child.loan_id)
    assert parent_section.closing["interest"] == 9_000
    assert parent_section.closing["principal"] == 200_000
    assert parent_section.closing["service"] == SERVICE_FEE_WITH_VAT_CENTS
    assert child_section.closing["laybye_hold"] == 20_000
    assert child_section.closing["service"] == 0
    assert child_section.closing["interest"] == 0
    assert parent_section.loan_number == child_section.loan_number
    service_fees = [
        item
        for item in svc.ledger.store.transactions_for(ORG, parent.loan_id)
        if item.kind == "service_fee"
    ]
    assert len(service_fees) == 1
    assert not [
        item
        for item in svc.ledger.store.transactions_for(ORG, child.loan_id)
        if item.kind == "service_fee"
    ]
    with pytest.raises(LedgerError) as second_fee:
        svc.ledger.levy_service_fee(
            organisation_id=ORG,
            loan_id=parent.loan_id,
            recognised_at=at(date(2026, 4, 2), 9),
            monthly_cents=6_000,
            due_on=date(2026, 5, 1),
            interest_cap_present=True,
            vat_rate=Decimal("0.15"),
        )
    assert second_fee.value.code == "service-fee-once"
    assert_locked_money(svc, record)


def test_default_leniency_collections_cure_and_in_duplum_clip_stays_off():
    svc = Servicing(enigma=EnigmaStub())
    first_due = date(2026, 6, 15)
    second_due = date(2026, 7, 15)
    record = svc.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((first_due, 60_000), (second_due, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="default",
        application_number="APP-DEFAULT",
    )
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    collections = Collections(svc)
    collections.bind(record.agreement_id, in_duplum_trigger="collections_default", residual_threshold_cents=10_000)
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)

    before = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 17), 8))
    assert before.collections_default is False
    assert before.open_episode_ceiling is None
    assert value_instant(date(2026, 6, 17)).hour == 0

    flagged = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 18), 8))
    assert flagged.collections_default is True
    assert flagged.open_episode_ceiling == 100_000
    assert flagged.episode_count == 1
    accrual = svc.ledger.accrue_day(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=value_instant(date(2026, 6, 19)),
        interest_cap_present=True,
    )
    assert accrual.value_date == date(2026, 6, 19)
    assert type(svc.ledger.bucket_balance(loan, "principal")) is int
    posted = [
        item
        for item in svc.ledger.store.transactions_for(ORG, loan.loan_id)
        if item.kind == "interest_accrual" and item.value_date == date(2026, 6, 19)
    ]
    assert posted
    assert IN_DUPLUM_CLIP_POSTS is False
    with pytest.raises(LedgerError) as clip:
        svc.ledger.clip_in_duplum()
    assert clip.value.code == "in-duplum-clip-off"
    assert all(item.kind != "in_duplum_clip" for item in svc.ledger.store.transactions_for(ORG, loan.loan_id))

    svc.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=60_000,
        recognised_at=at(date(2026, 6, 20), 11),
        idempotency_key="cure",
        agreement_id=record.agreement_id,
        attributed_due_on=first_due,
    )
    cured = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 20), 16))
    assert cured.collections_default is False
    assert cured.open_episode_ceiling is None
    assert cured.episode_count == 1
    assert loan.episodes[0].ceiling_cents == 100_000
    assert loan.episodes[0].closed_on == date(2026, 6, 20)

    restarted = collections.observe(record.agreement_id, recognised_at=at(date(2026, 7, 18), 8))
    assert restarted.collections_default is True
    assert restarted.episode_count == 2
    assert restarted.open_episode_ceiling == 40_000
    assert loan.episodes[0].ceiling_cents == 100_000

    unbound = Collections(svc)
    with pytest.raises(CollectionsError) as missing:
        unbound.bind(record.agreement_id, in_duplum_trigger=None)
    assert missing.value.code == "trigger-unset"
    assert record.agreement_id not in unbound.cases
    assert_locked_money(svc, record)


def test_write_off_allocates_unapplied_receipts_then_checks_the_mandate_and_threshold():
    svc = Servicing(enigma=EnigmaStub())
    first_due = date(2026, 6, 15)
    second_due = date(2026, 7, 15)
    record = svc.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(leniency_days=0),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((first_due, 60_000), (second_due, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="write-off",
        application_number="APP-WRITE",
    )
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    collections = Collections(svc)
    collections.bind(
        record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=10_000,
        prescription_mode="manual",
    )
    collections.open_prescription_review(record.agreement_id, recognised_at=at(date(2026, 4, 1), 8))
    held = collections.receive(
        organisation_id=ORG,
        person_id=PERSON,
        cents=2_500,
        recognised_at=at(date(2026, 4, 2), 10),
        idempotency_key="held",
        agreement_id=record.agreement_id,
        attributed_due_on=first_due,
    )
    assert held.status == "unapplied"
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "principal") == 100_000

    with pytest.raises(CollectionsError) as denied:
        collections.write_off(
            record.agreement_id,
            recognised_at=at(date(2026, 4, 3), 8),
            actor_id="staff-1",
            amount_cents=97_500,
            platform=RandCeiling(97_500),
            mandate_allowed=False,
        )
    assert denied.value.code == "mandate-denied"
    assert held.status == "unapplied"
    assert all(item.kind != "write_off" for item in svc.ledger.store.transactions_for(ORG, loan.loan_id))

    with pytest.raises(CollectionsError) as no_ceiling:
        collections.write_off(
            record.agreement_id,
            recognised_at=at(date(2026, 4, 3), 9),
            actor_id="staff-1",
            amount_cents=97_500,
            platform=None,
            mandate_allowed=True,
        )
    assert no_ceiling.value.code == "authority-ambiguous"
    assert held.status == "unapplied"

    posted = collections.write_off(
        record.agreement_id,
        recognised_at=at(date(2026, 4, 3), 12),
        actor_id="staff-1",
        amount_cents=97_500,
        platform=RandCeiling(97_500),
        mandate_allowed=True,
    )
    assert posted.written_off is True
    assert held.status == "allocated"
    assert held.value_date == date(2026, 4, 2)
    assert value_instant(held.value_date).hour == 0
    assert svc.ledger.bucket_balance(loan, "principal") == 0
    payment_tx = svc.ledger.store.get_transaction(ORG, held.ledger_transaction_id)
    write_off_tx = next(item for item in svc.ledger.store.transactions_for(ORG, loan.loan_id) if item.kind == "write_off")
    assert payment_tx.recognition_sequence < write_off_tx.recognition_sequence
    assert write_off_tx.amount_cents == 97_500
    assert type(write_off_tx.amount_cents) is int

    other = Servicing(enigma=EnigmaStub())
    other_record = other.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(leniency_days=0),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((first_due, 60_000), (second_due, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="residual",
        application_number="APP-RESIDUAL",
    )
    other_record = other.disburse(other_record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    residual = Collections(other)
    residual.bind(
        other_record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=10_000,
        prescription_mode="manual",
    )
    other.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=60_000,
        recognised_at=at(date(2026, 3, 2), 11),
        idempotency_key="exact-1",
        agreement_id=other_record.agreement_id,
        attributed_due_on=first_due,
    )
    other.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=40_000,
        recognised_at=at(date(2026, 3, 2), 12),
        idempotency_key="exact-2",
        agreement_id=other_record.agreement_id,
        attributed_due_on=second_due,
    )
    other_loan = other.ledger.store.get(ORG, other_record.ledger_loan_id)
    assert other.ledger.bucket_balance(other_loan, "principal") == 0
    other.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=other_loan.loan_id,
        bucket="additional_monthly",
        cents=12_000,
        due_on=date(2026, 6, 16),
        recognised_at=at(date(2026, 6, 16), 9),
        interest_cap_present=True,
    )
    residual.open_prescription_review(other_record.agreement_id, recognised_at=at(date(2026, 7, 1), 8))
    extra = residual.receive(
        organisation_id=ORG,
        person_id=PERSON,
        cents=3_000,
        recognised_at=at(date(2026, 7, 16), 9),
        idempotency_key="residual-held",
        agreement_id=other_record.agreement_id,
        attributed_due_on=first_due,
    )
    assert extra.status == "unapplied"
    cleared = residual.propose_residual_write_off(
        other_record.agreement_id, recognised_at=at(date(2026, 7, 16), 12)
    )
    assert extra.status == "allocated"
    assert cleared.written_off is True
    assert other.ledger.bucket_balance(other_loan, "additional_monthly") == 0
    residual_tx = next(item for item in other.ledger.store.transactions_for(ORG, other_loan.loan_id) if item.kind == "write_off")
    assert residual_tx.amount_cents == 9_000
    assert other.ledger.store.get_transaction(ORG, extra.ledger_transaction_id).recognition_sequence < residual_tx.recognition_sequence

    above = Servicing(enigma=EnigmaStub())
    above_record = above.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(leniency_days=0),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((first_due, 60_000), (second_due, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="above",
        application_number="APP-ABOVE",
    )
    above_record = above.disburse(above_record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    above_collections = Collections(above)
    above_collections.bind(
        above_record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=10_000,
        prescription_mode="manual",
    )
    above.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=60_000,
        recognised_at=at(date(2026, 3, 2), 11),
        idempotency_key="above-1",
        agreement_id=above_record.agreement_id,
        attributed_due_on=first_due,
    )
    above.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=40_000,
        recognised_at=at(date(2026, 3, 2), 12),
        idempotency_key="above-2",
        agreement_id=above_record.agreement_id,
        attributed_due_on=second_due,
    )
    above_loan = above.ledger.store.get(ORG, above_record.ledger_loan_id)
    above.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=above_loan.loan_id,
        bucket="additional_monthly",
        cents=14_000,
        due_on=date(2026, 6, 16),
        recognised_at=at(date(2026, 6, 16), 9),
        interest_cap_present=True,
    )
    above_collections.open_prescription_review(above_record.agreement_id, recognised_at=at(date(2026, 7, 1), 8))
    above_held = above_collections.receive(
        organisation_id=ORG,
        person_id=PERSON,
        cents=3_000,
        recognised_at=at(date(2026, 7, 16), 9),
        idempotency_key="above-held",
        agreement_id=above_record.agreement_id,
        attributed_due_on=first_due,
    )
    with pytest.raises(CollectionsError) as too_high:
        above_collections.propose_residual_write_off(
            above_record.agreement_id, recognised_at=at(date(2026, 7, 16), 12)
        )
    assert too_high.value.code == "residual-above-threshold"
    assert above_held.status == "allocated"
    assert above.ledger.bucket_balance(above_loan, "additional_monthly") == 11_000
    assert all(item.kind != "write_off" for item in above.ledger.store.transactions_for(ORG, above_loan.loan_id))
    assert_locked_money(svc, record)
    assert_locked_money(other, other_record)
    assert_locked_money(above, above_record)


def test_statement_pdf_paints_stored_figures_and_the_brand_row():
    svc = Servicing(enigma=EnigmaStub())
    record = _book(svc, key="pdf", application_number="APP-PDF")
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    store = ComplianceStore()
    brands = BrandStore()
    docs = Documents(svc, store, brands)
    with pytest.raises(DocumentsError) as missing_compliance:
        docs.issue_statement(
            organisation_id=ORG,
            person_id=PERSON,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            interest_cap_present=True,
            vat_rate=Decimal("0.15"),
        )
    assert missing_compliance.value.code == "compliance-missing"
    assert docs.statements == {}
    assert not [
        item
        for item in svc.ledger.store.transactions_for(ORG, record.ledger_loan_id)
        if item.kind == "interest_bill"
    ]

    store.put(compliance())
    brands.put(
        Brand(ORG, "primary", "North Credit", statement_footer="Registered credit provider NCRCP999.")
    )
    brands.put(Brand(ORG, "second", "Other look", statement_footer="Do not pick this footer."))
    with pytest.raises(DocumentsError) as ambiguous:
        docs.issue_statement(
            organisation_id=ORG,
            person_id=PERSON,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            interest_cap_present=True,
            vat_rate=Decimal("0.15"),
        )
    assert ambiguous.value.code == "brand-ambiguous"
    assert docs.statements == {}
    assert not [
        item
        for item in svc.ledger.store.transactions_for(ORG, record.ledger_loan_id)
        if item.kind == "interest_bill"
    ]

    single = BrandStore()
    single.put(
        Brand(ORG, "primary", "North Credit", statement_footer="Registered credit provider NCRCP999.")
    )
    docs.brands = single
    issued = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    text = issued.pdf_stub.decode()
    assert text.startswith("LMS-STATEMENT\n")
    assert "header:North Credit\n" in text
    assert "footer:Registered credit provider NCRCP999.\n" in text
    assert "ncr:NCRCP999\n" in text
    section = next(item for item in issued.loans if item.instrument_kind == "loan")
    for bucket, cents in section.opening.items():
        assert type(cents) is int
        assert f"opening:{section.loan_number}:{bucket}:{cents}\n" in text
    for bucket, cents in section.closing.items():
        assert type(cents) is int
        assert f"closing:{section.loan_number}:{bucket}:{cents}\n" in text
    assert issued.brand_display_name == "North Credit"
    assert issued.brand_statement_footer == "Registered credit provider NCRCP999."
    painted = issued.pdf_stub
    single.put(
        Brand(ORG, "primary", "Renamed Credit", statement_footer="A later footer.")
    )
    again = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    assert again.statement_id == issued.statement_id
    assert again.pdf_stub == painted
    assert b"Renamed Credit" not in again.pdf_stub
    svc.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=1_000,  # pays billed interest; principal on the stored statement stays put
        recognised_at=at(date(2026, 5, 2), 11),
        idempotency_key="after-pdf",
        agreement_id=record.agreement_id,
        attributed_due_on=date(2026, 5, 1),
    )
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "interest") == section.closing["interest"] - 1_000
    assert f"closing:{section.loan_number}:interest:{section.closing['interest']}\n" in again.pdf_stub.decode()
    assert_locked_money(svc, record)


def test_staff_search_returns_the_stored_statement_by_loan_number_or_frozen_id():
    svc = Servicing(enigma=EnigmaStub())
    record = _book(svc, key="search", application_number="APP-SEARCH")
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    store = ComplianceStore()
    store.put(compliance())
    docs = Documents(svc, store)
    issued = docs.issue_statement(
        organisation_id=ORG,
        person_id=PERSON,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    section = next(item for item in issued.loans if item.instrument_kind == "loan")
    office = StaffOffice(statements=docs)
    headers = {
        "X-Enigma-Person-Id": "staff-1",
        "X-Enigma-Organisation-Id": ORG,
        "X-Enigma-Roles": ROLE_ELECTIONS_WRITE,
        "X-Enigma-Status": "active",
    }
    by_loan = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/statements",
        {"loan_number": section.loan_number},
        headers,
    )
    assert by_loan[0] == 200
    assert by_loan[1]["statements"][0]["statement_id"] == issued.statement_id
    returned = by_loan[1]["statements"][0]["loans"][0]
    assert returned["loan_number"] == record.loan_number
    assert returned["frozen_id_number"] == FROZEN_ID
    assert returned["closing"] == section.closing
    assert all(type(cents) is int for cents in returned["closing"].values())

    by_id = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/statements",
        {},
        {**headers, "X-Id-Number": FROZEN_ID},
    )
    assert by_id[0] == 200
    assert by_id[1]["statements"][0]["statement_id"] == issued.statement_id

    svc.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=4_000,  # pays billed interest; the stored closing is not rebuilt
        recognised_at=at(date(2026, 5, 2), 11),
        idempotency_key="after-search",
        agreement_id=record.agreement_id,
        attributed_due_on=date(2026, 5, 1),
    )
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)
    assert svc.ledger.bucket_balance(loan, "interest") == section.closing["interest"] - 4_000
    reread = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/statements",
        {"loan_number": record.loan_number},
        headers,
    )
    assert reread[1]["statements"][0]["loans"][0]["closing"]["interest"] == section.closing["interest"]
    assert reread[1]["statements"][0]["statement_id"] == issued.statement_id

    bare = dispatch(
        StaffOffice(),
        "GET",
        f"/v1/staff/organisations/{ORG}/statements",
        {"loan_number": record.loan_number},
        headers,
    )
    assert bare[0] == 422
    assert bare[1]["code"] == "statement-index-missing"
    both = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/statements",
        {"loan_number": record.loan_number, "id_number": FROZEN_ID},
        headers,
    )
    assert both[0] == 422
    assert both[1]["code"] == "search-key-unset"
    assert value_instant(issued.statement_date).hour == 0
    assert value_instant(issued.statement_date).tzinfo == JOHANNESBURG
    assert_locked_money(svc, record)
