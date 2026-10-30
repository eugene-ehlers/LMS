"""Pins for the Layer 1 gaps that remain. Amounts stay in integer cents.

Booking refuses a missing in-duplum trigger. An unset residual threshold fills
R100. A Laybye remainder is not run through the partial-prepayment election.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lms.collections.errors import CollectionsError
from lms.collections.service import Collections
from lms.laybye.service import allocate_receipt
from lms.ledger.service import Ledger
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing
from lms.statements.service import Documents
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.exceptions import CalculationInputError
from lms_config.locked import (
    RESIDUAL_WRITE_OFF_DEFAULT_CENTS,
    OrganisationSettings,
    resolve_customer_settings,
    resolve_in_duplum_trigger,
)
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
DUE = date(2026, 6, 15)


class CountingStub(EnigmaStub):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, str]] = []

    def check(self, organisation_id: str, person_id: str, mandate: str):
        self.calls.append((organisation_id, person_id, mandate))
        return super().check(organisation_id, person_id, mandate)


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


def settings(**overrides) -> OrganisationSettings:
    values = dict(
        leniency_days=0,
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


def test_migration_prefixes_apply_in_one_order():
    directory = Path(__file__).resolve().parents[1] / "db" / "migrations"
    names = sorted(path.name for path in directory.glob("*.sql"))
    prefixes = [name.split("_", 1)[0] for name in names]
    assert len(prefixes) == len(set(prefixes))
    assert prefixes == sorted(prefixes)
    assert "0005_statement_compliance.sql" in names
    assert "0006_laybye_pre_disbursement.sql" in names
    assert "0007_collections_elections.sql" in names
    assert not list(directory.glob("0005_laybye_pre_disbursement.sql"))
    assert not list(directory.glob("0005_collections_elections.sql"))


def test_booking_refuses_a_missing_trigger_and_fills_residual_r100():
    with pytest.raises(CalculationInputError, match="in_duplum_trigger"):
        resolve_customer_settings(settings(in_duplum_trigger=None), micro_short_term())
    resolved = resolve_customer_settings(settings(), micro_short_term())
    assert resolved.in_duplum_trigger == "collections_default"
    assert resolved.residual_write_off_threshold_cents == RESIDUAL_WRITE_OFF_DEFAULT_CENTS == 10_000
    with pytest.raises(CalculationInputError):
        resolve_in_duplum_trigger(None)
    chosen = resolve_customer_settings(
        settings(residual_write_off_threshold_cents=5_000),
        replace(micro_short_term(), in_duplum_trigger="contractual_breach"),
    )
    assert chosen.in_duplum_trigger == "contractual_breach"
    assert chosen.residual_write_off_threshold_cents == 5_000
    servicing = Servicing(enigma=EnigmaStub())
    with pytest.raises(ServicingError) as missing_book:
        servicing.book(
            organisation_id="org-a",
            person_id="person-a",
            product=micro_short_term(),
            settings=settings(in_duplum_trigger=None),
            recognised_at=at(date(2026, 4, 1), 8),
            cash_advanced_cents=100_000,
            frequency="monthly",
            schedule=((DUE, 100_000),),
            initiation_fee_cents=0,
            idempotency_key="book-no-trigger",
        )
    assert missing_book.value.code == "election-unset"
    assert servicing.agreements == {}
    record = servicing.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(residual_write_off_threshold_cents=None),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key="book-residual-default",
    )
    assert record.resolved.in_duplum_trigger == "collections_default"
    assert record.resolved.residual_write_off_threshold_cents == 10_000
    collections_bind = Collections(servicing)
    with pytest.raises(CollectionsError) as missing:
        collections_bind.bind(record.agreement_id, in_duplum_trigger=None)
    assert missing.value.code == "trigger-unset"
    assert collections_bind.cases == {}


def test_book_linked_laybye_keeps_the_receipt_as_cash_in_until_grant():
    stub = CountingStub()
    servicing = Servicing(enigma=stub)
    record = servicing.book_linked_laybye(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(
            in_duplum_trigger="collections_default",
            residual_write_off_threshold_cents=5_000,
        ),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=200_000,
        frequency="monthly",
        schedule=((DUE, 200_000),),
        initiation_fee_cents=0,
        quoted_disbursement=date(2026, 4, 1),
        idempotency_key="book-laybye",
        pre_disbursement_cents=20_000,
        pre_disbursement_at=at(date(2026, 4, 1), 9),
    )
    parent = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    child = servicing.ledger.store.get("org-a", record.laybye_loan_id)
    deposit = next(item for item in servicing.ledger.store.transactions_for("org-a", child.loan_id) if item.kind == "laybye_deposit")
    assert record.status == "pending_disbursement"
    assert record.resolved.in_duplum_trigger == "collections_default"
    assert record.resolved.residual_write_off_threshold_cents == 5_000
    assert parent.disbursement_value_date is None
    assert servicing.ledger.bucket_balance(parent, "principal") == 0
    assert servicing.ledger.bucket_balance(child, "laybye_hold") == 20_000
    assert [(entry.account_code, entry.debit_cents, entry.credit_cents) for entry in deposit.entries] == [
        ("cash", 20_000, 0),
        ("laybye_hold", 0, 20_000),
    ]
    assert servicing.ledger.store.transactions_for("org-a", parent.loan_id) == ()
    assert "disbursement.confirm" not in [call[2] for call in stub.calls]

    granted = servicing.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 11))
    assert granted.status == "active"
    assert servicing.ledger.bucket_balance(parent, "principal") == 200_000
    assert servicing.ledger.bucket_balance(child, "laybye_hold") == 20_000
    assert "disbursement.confirm" in [call[2] for call in stub.calls]

    again = servicing.book_linked_laybye(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=200_000,
        frequency="monthly",
        schedule=((DUE, 200_000),),
        initiation_fee_cents=0,
        quoted_disbursement=date(2026, 4, 1),
        idempotency_key="book-laybye",
        pre_disbursement_cents=20_000,
        pre_disbursement_at=at(date(2026, 4, 1), 9),
        grant_at=at(date(2026, 4, 1), 11),
    )
    assert again.agreement_id == record.agreement_id
    assert servicing.ledger.bucket_balance(child, "laybye_hold") == 20_000
    assert sum(1 for item in servicing.ledger.store.transactions_for("org-a", child.loan_id) if item.kind == "laybye_deposit") == 1


def test_post_payment_and_allocate_receipt_share_the_laybye_split():
    def opened():
        ledger = Ledger()
        from lms.laybye.service import grant_loan, prepare_pair, receive_pre_disbursement

        parent, child = prepare_pair(
            ledger,
            organisation_id="org-a",
            person_id="person-a",
            product=micro_short_term(),
            organisation=settings(),
            recognised_at=at(date(2026, 3, 1), 8),
            cash_advanced_cents=100_000,
            frequency="monthly",
            schedule=((DUE, 100_000),),
            identity_name="Ada Borrower",
            identity_number="8001015800085",
            service_address="1 Main Road, Cape Town",
            quoted_disbursement=date(2026, 4, 1),
        )
        receive_pre_disbursement(
            ledger,
            organisation_id="org-a",
            parent_loan_id=parent.loan_id,
            cents=10_000,
            recognised_at=at(date(2026, 3, 20), 8),
        )
        grant_loan(
            ledger,
            organisation_id="org-a",
            parent_loan_id=parent.loan_id,
            recognised_at=at(date(2026, 4, 1), 8),
            schedule=((DUE, 100_000),),
        )
        ledger.levy_charge(
            organisation_id="org-a",
            loan_id=parent.loan_id,
            bucket="interest",
            cents=2_500,
            due_on=date(2026, 4, 2),
            recognised_at=at(date(2026, 4, 2), 8),
            interest_cap_present=True,
        )
        return ledger, parent, child

    posted, parent, child = opened()
    payment = posted.post_payment(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        cents=4_000,
        recognised_at=at(date(2026, 4, 2), 9),
        attributed_due_on=date(2026, 4, 2),
    )
    assert payment.kind == "payment"
    assert payment.amount_cents == 2_500
    assert posted.bucket_balance(parent, "interest") == 0
    assert posted.bucket_balance(parent, "principal") == 100_000
    assert posted.bucket_balance(child, "laybye_hold") == 11_500

    allocated, other_parent, other_child = opened()
    allocation = allocate_receipt(
        allocated,
        organisation_id="org-a",
        parent_loan_id=other_parent.loan_id,
        cents=4_000,
        recognised_at=at(date(2026, 4, 2), 9),
        attributed_due_on=date(2026, 4, 2),
    )
    assert allocation.loan_cents == 2_500
    assert allocation.laybye_cents == 1_500
    assert allocated.bucket_balance(other_parent, "principal") == posted.bucket_balance(parent, "principal")
    assert allocated.bucket_balance(other_child, "laybye_hold") == posted.bucket_balance(child, "laybye_hold")


def test_a_loan_without_a_laybye_still_rejects_a_true_overpayment():
    servicing = Servicing(enigma=EnigmaStub())
    record = servicing.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        idempotency_key="book-plain",
    )
    servicing.disburse(record.agreement_id, recognised_at=at(date(2026, 4, 1), 10))
    with pytest.raises(ServicingError) as over:
        servicing.accept_payment(
            organisation_id="org-a",
            person_id="person-a",
            cents=100_001,
            recognised_at=at(date(2026, 4, 2), 9),
            idempotency_key="too-much",
            agreement_id=record.agreement_id,
            attributed_due_on=DUE,
        )
    assert over.value.code == "overpayment-unset"
    account = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    assert servicing.ledger.bucket_balance(account, "principal") == 100_000


def test_servicing_audit_extract_sees_the_key_events():
    servicing = Servicing(enigma=EnigmaStub())
    record = servicing.book_linked_laybye(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(in_duplum_trigger="collections_default"),
        recognised_at=at(date(2026, 4, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        initiation_fee_cents=0,
        quoted_disbursement=date(2026, 4, 1),
        idempotency_key="book-audit",
        pre_disbursement_cents=10_000,
        pre_disbursement_at=at(date(2026, 4, 1), 9),
        grant_at=at(date(2026, 4, 1), 11),
    )
    payment = servicing.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=1_000,
        recognised_at=at(date(2026, 4, 2), 10),
        idempotency_key="excess",
        agreement_id=record.agreement_id,
        attributed_due_on=DUE,
    )
    assert payment.allocations == (("laybye_hold", 1_000),)
    compliance = ComplianceStore()
    compliance.put(
        ProviderCompliance(
            organisation_id="org-a",
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
    )
    Documents(servicing, compliance).issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 1),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    extract = servicing.audit.extract(
        organisation_id="org-a",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 2),
    )
    kinds = {row.event_type for row in extract.rows}
    assert {
        "AGREEMENT_STATUS_CHANGED",
        "DEPOSIT_RECEIVED",
        "PRINCIPAL_ADVANCED",
        "STATEMENT_ISSUED",
    } <= kinds
    assert extract.verified and extract.hashes_ok and extract.links_ok
    assert extract.rows[0].previous_hash is None
    assert extract.rows[0].row_hash
    sequences = [row.recognition_sequence for row in extract.rows]
    assert sequences == list(range(1, len(sequences) + 1))
    deposits = [row for row in extract.rows if row.event_type == "DEPOSIT_RECEIVED"]
    assert {row.amount_cents for row in deposits} >= {10_000, 1_000}
    assert all(row.balance_code == "deposit" for row in deposits)
    assert all(isinstance(row.amount_cents, int) for row in extract.rows if row.category == "financial")
