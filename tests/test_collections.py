"""Collections and arrears. Amounts come from the ledger. The layer does not recompute them."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lms.collections.authority import RandCeiling
from lms_config.exceptions import CalculationInputError
from lms.collections.errors import CollectionsError
from lms.collections.service import Collections
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms_config.context import CUSTOMER_SETTINGS_SQL
from lms_config.locked import (
    RESIDUAL_WRITE_OFF_DEFAULT_CENTS,
    resolve_in_duplum_trigger,
    resolve_residual_threshold_cents,
)
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
FIRST = date(2026, 6, 15)
SECOND = date(2026, 7, 15)


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


def settings(**overrides):
    from lms_config.locked import OrganisationSettings

    values = dict(
        leniency_days=0,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
        in_duplum_trigger="contractual_breach",
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def opened(trigger: str = "collections_default", **overrides):
    stub = EnigmaStub()
    servicing = Servicing(enigma=stub)
    payload = dict(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(in_duplum_trigger=trigger),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((FIRST, 60_000), (SECOND, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="book-1",
    )
    record = servicing.book(**payload)
    record = servicing.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    collections = Collections(servicing)
    bind = dict(in_duplum_trigger=trigger)
    bind.update(overrides)
    collections.bind(record.agreement_id, **bind)
    return collections, servicing, record, stub


def pay(servicing: Servicing, record, cents: int, on: date, *, key: str, due: date = FIRST):
    return servicing.accept_payment(
        organisation_id="org-a",
        person_id="person-a",
        cents=cents,
        recognised_at=at(on, 11),
        idempotency_key=key,
        agreement_id=record.agreement_id,
        attributed_due_on=due,
    )


def test_contractual_breach_cannot_be_rectified_after_the_day_has_passed():
    collections, servicing, record, _stub = opened("contractual_breach")
    loan_id = record.ledger_loan_id

    before = collections.observe(record.agreement_id, recognised_at=at(FIRST, 18))
    assert before.contractual_breaches == ()

    missed = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    assert missed.contractual_breaches == (FIRST,)
    accrual = servicing.ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan_id,
        recognised_at=at(date(2026, 6, 16), 7),
        interest_cap_present=True,
    )
    assert accrual.value_date == date(2026, 6, 16)

    payment = pay(servicing, record, 60_000, date(2026, 6, 16), key="late")
    assert payment.status == "allocated"
    still = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 17), 8))
    assert still.contractual_breaches == (FIRST,)
    assert servicing.ledger.bucket_balance(
        servicing.ledger.store.get("org-a", loan_id), "principal"
    ) == 40_000

    cleared = collections.correct_system_error(
        record.agreement_id, FIRST, recognised_at=at(date(2026, 6, 18), 8)
    )
    assert cleared.contractual_breaches == ()


def test_a_receipt_on_the_due_date_does_not_become_a_contractual_breach():
    collections, _servicing, record, _stub = opened("contractual_breach")
    pay(_servicing, record, 60_000, FIRST, key="on-the-day")
    viewed = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    assert viewed.contractual_breaches == ()
    assert viewed.open_episode_ceiling is None


def test_collections_default_can_be_cured_by_paying_the_arrears():
    collections, servicing, record, _stub = opened("collections_default")
    flagged = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    assert flagged.collections_default is True
    assert flagged.open_episode_ceiling == 100_000
    assert flagged.contractual_breaches == (FIRST,)

    pay(servicing, record, 60_000, date(2026, 6, 20), key="cure")
    cured = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 20), 16))
    assert cured.collections_default is False
    assert cured.open_episode_ceiling is None
    assert cured.contractual_breaches == (FIRST,)
    assert cured.episode_count == 1


def test_contractual_breach_trigger_fixes_the_ceiling():
    collections, servicing, record, _stub = opened("contractual_breach")
    opened_view = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    assert opened_view.open_episode_ceiling == 100_000
    assert opened_view.episode_count == 1

    pay(servicing, record, 60_000, date(2026, 6, 20), key="pay-down")
    held = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 20), 16))
    assert held.open_episode_ceiling == 100_000
    assert held.episode_count == 1

    later = collections.observe(record.agreement_id, recognised_at=at(date(2026, 7, 16), 8))
    assert later.contractual_breaches == (FIRST, SECOND)
    assert later.open_episode_ceiling == 100_000
    assert later.episode_count == 1


def test_collections_default_trigger_can_stop_and_start_again():
    collections, servicing, record, _stub = opened("collections_default")
    collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    pay(servicing, record, 60_000, date(2026, 6, 20), key="cure")
    cured = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 20), 16))
    assert cured.open_episode_ceiling is None

    restarted = collections.observe(record.agreement_id, recognised_at=at(date(2026, 7, 16), 8))
    assert restarted.collections_default is True
    assert restarted.open_episode_ceiling == 40_000
    assert restarted.episode_count == 2


def test_unset_in_duplum_trigger_fails_closed():
    _collections, servicing, record, _stub = opened("collections_default")
    fresh = Collections(servicing)
    with pytest.raises(CollectionsError) as caught:
        fresh.bind(record.agreement_id, in_duplum_trigger=None)
    assert caught.value.code == "trigger-unset"
    with pytest.raises(CollectionsError) as observed:
        fresh.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    assert observed.value.code == "trigger-unset"
    loan = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    assert loan.episodes == []
    with pytest.raises(CalculationInputError):
        resolve_in_duplum_trigger(None, None)
    assert resolve_in_duplum_trigger("contractual_breach", "collections_default") == "collections_default"


def test_residual_write_off_threshold_defaults_to_r100_and_is_not_automatic():
    assert resolve_residual_threshold_cents(None) == RESIDUAL_WRITE_OFF_DEFAULT_CENTS == 10_000
    assert resolve_residual_threshold_cents(4_000, None) == 4_000
    assert resolve_residual_threshold_cents(None, 2_500) == 2_500
    assert resolve_residual_threshold_cents(None, 0) == 0

    collections, servicing, record, _stub = opened("collections_default", residual_threshold_cents=None)
    assert collections.view(record.agreement_id).residual_threshold_cents == 10_000
    pay(servicing, record, 60_000, date(2026, 3, 2), key="exact-first", due=FIRST)
    pay(servicing, record, 40_000, date(2026, 3, 2), key="exact-second", due=SECOND)
    loan = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    assert servicing.ledger.bucket_balance(loan, "principal") == 0
    servicing.ledger.levy_charge(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        bucket="additional_monthly",
        cents=5_000,
        due_on=date(2026, 6, 16),
        recognised_at=at(date(2026, 6, 16), 9),
        interest_cap_present=True,
    )
    assert servicing.ledger.bucket_balance(loan, "additional_monthly") == 5_000
    assert all(
        item.kind != "write_off"
        for item in servicing.ledger.store.transactions_for("org-a", loan.loan_id)
    )

    posted = collections.propose_residual_write_off(
        record.agreement_id, recognised_at=at(date(2026, 7, 16), 12)
    )
    assert posted.written_off is True
    assert servicing.ledger.bucket_balance(loan, "additional_monthly") == 0
    assert any(
        item.kind == "write_off" and item.amount_cents == 5_000
        for item in servicing.ledger.store.transactions_for("org-a", loan.loan_id)
    )

    other, other_servicing, other_record, _stub = opened(
        "collections_default", residual_threshold_cents=None
    )
    pay(other_servicing, other_record, 60_000, date(2026, 3, 3), key="exact-b-first", due=FIRST)
    pay(other_servicing, other_record, 40_000, date(2026, 3, 3), key="exact-b-second", due=SECOND)
    other_loan = other_servicing.ledger.store.get("org-a", other_record.ledger_loan_id)
    other_servicing.ledger.levy_charge(
        organisation_id="org-a",
        loan_id=other_loan.loan_id,
        bucket="additional_monthly",
        cents=10_001,
        due_on=date(2026, 6, 16),
        recognised_at=at(date(2026, 6, 16), 9),
        interest_cap_present=True,
    )
    with pytest.raises(CollectionsError) as caught:
        other.propose_residual_write_off(other_record.agreement_id, recognised_at=at(date(2026, 7, 16), 12))
    assert caught.value.code == "residual-above-threshold"
    assert all(
        item.kind != "write_off"
        for item in other_servicing.ledger.store.transactions_for("org-a", other_loan.loan_id)
    )


def test_residual_write_off_is_refused_while_an_episode_is_open():
    collections, _servicing, record, _stub = opened("collections_default")
    collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    with pytest.raises(CollectionsError) as caught:
        collections.propose_residual_write_off(
            record.agreement_id, recognised_at=at(date(2026, 7, 16), 8)
        )
    assert caught.value.code == "residual-episode-open"


def test_prescription_review_holds_receipts_unapplied_and_does_not_refund():
    collections, servicing, record, _stub = opened(
        "collections_default", prescription_mode="manual"
    )
    with pytest.raises(CollectionsError) as unset:
        Collections(servicing).open_prescription_review(
            record.agreement_id, recognised_at=at(date(2026, 4, 1), 8)
        )
    assert unset.value.code == "trigger-unset"

    held = collections.open_prescription_review(
        record.agreement_id, recognised_at=at(date(2026, 4, 1), 8)
    )
    assert held.prescription_review is True
    payment = collections.receive(
        organisation_id="org-a",
        person_id="person-a",
        cents=2_500,
        recognised_at=at(date(2026, 4, 2), 10),
        idempotency_key="held",
        agreement_id=record.agreement_id,
        attributed_due_on=FIRST,
    )
    assert payment.status == "unapplied"
    assert payment.ledger_transaction_id is None
    kinds = [
        item.kind
        for item in servicing.ledger.store.transactions_for("org-a", record.ledger_loan_id)
    ]
    assert "payment" not in kinds
    assert "refund" not in kinds
    assert servicing.ledger.bucket_balance(
        servicing.ledger.store.get("org-a", record.ledger_loan_id), "principal"
    ) == 100_000


def test_larger_write_off_requires_a_mandate_and_stays_inside_the_ceiling():
    collections, servicing, record, stub = opened("collections_default")
    loan = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    outstanding = servicing.ledger.bucket_balance(loan, "principal")
    with pytest.raises(CollectionsError) as over:
        collections.write_off(
            record.agreement_id,
            recognised_at=at(date(2026, 4, 1), 8),
            actor_id="staff-1",
            amount_cents=outstanding,
            platform=RandCeiling(outstanding - 1),
            mandate_allowed=True,
        )
    assert over.value.code == "mandate-denied"
    assert all(item.kind != "write_off" for item in servicing.ledger.store.transactions_for("org-a", loan.loan_id))

    with pytest.raises(CollectionsError) as denied:
        collections.write_off(
            record.agreement_id,
            recognised_at=at(date(2026, 4, 1), 8),
            actor_id="staff-1",
            amount_cents=outstanding,
            platform=RandCeiling(outstanding),
            mandate_allowed=False,
        )
    assert denied.value.code == "mandate-denied"

    stub.mode = "timeout"
    with pytest.raises(CollectionsError) as timed_out:
        collections.write_off(
            record.agreement_id,
            recognised_at=at(date(2026, 4, 1), 8),
            actor_id="staff-1",
            amount_cents=outstanding,
            platform=RandCeiling(outstanding),
            mandate_allowed=True,
        )
    assert timed_out.value.code == "authority-unavailable"
    stub.mode = "active"

    posted = collections.write_off(
        record.agreement_id,
        recognised_at=at(date(2026, 4, 1), 8),
        actor_id="staff-1",
        amount_cents=outstanding,
        platform=RandCeiling(outstanding),
        company=RandCeiling(outstanding + 50_000, version=2),
        mandate_allowed=True,
    )
    assert posted.written_off is True
    assert servicing.ledger.bucket_balance(loan, "principal") == 0
    journal = next(
        item for item in servicing.ledger.store.transactions_for("org-a", loan.loan_id) if item.kind == "write_off"
    )
    assert journal.amount_cents == outstanding
    assert sum(entry.debit_cents for entry in journal.entries) == sum(
        entry.credit_cents for entry in journal.entries
    )


def test_provision_and_prescription_have_no_platform_formula():
    collections, _servicing, record, _stub = opened("collections_default")
    with pytest.raises(CollectionsError) as provision:
        collections.record_provision(record.agreement_id, recognised_at=at(date(2026, 4, 1)))
    assert provision.value.code == "provision-mode-unset"
    with pytest.raises(CollectionsError) as prescription:
        collections.open_prescription_review(record.agreement_id, recognised_at=at(date(2026, 4, 1)))
    assert prescription.value.code == "prescription-mode-unset"

    manual, _servicing_b, manual_record, _stub_b = opened(
        "collections_default", provision_mode="manual", prescription_mode="formula"
    )
    stored = manual.record_provision(
        manual_record.agreement_id,
        recognised_at=at(date(2026, 4, 1)),
        amount_cents=1_500,
    )
    assert stored.provision_cents == 1_500
    with pytest.raises(CollectionsError) as missing_formula:
        manual.open_prescription_review(manual_record.agreement_id, recognised_at=at(date(2026, 4, 2)))
    assert missing_formula.value.code == "prescription-formula-unset"


def test_collections_elections_are_in_the_configuration_read():
    migration = (Path(__file__).resolve().parents[1] / "db" / "migrations" / "0007_collections_elections.sql").read_text()
    assert "in_duplum_trigger" in migration
    assert "residual_write_off_threshold_cents" in migration
    assert "contractual_breach" in migration
    assert "collections_default" in migration
    assert "in_duplum_trigger" in CUSTOMER_SETTINGS_SQL
    assert "residual_write_off_threshold_cents" in CUSTOMER_SETTINGS_SQL


def test_bind_before_disbursement_succeeds_and_a_rejected_bind_does_not_freeze():
    servicing = Servicing(enigma=EnigmaStub())
    record = servicing.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(
            in_duplum_trigger="collections_default",
            residual_write_off_threshold_cents=5_000,
        ),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((FIRST, 60_000), (SECOND, 40_000)),
        initiation_fee_cents=0,
        idempotency_key="book-early",
    )
    assert record.ledger_loan_id is None
    assert record.resolved.in_duplum_trigger == "collections_default"
    assert record.resolved.residual_write_off_threshold_cents == 5_000
    collections = Collections(servicing)
    with pytest.raises(CollectionsError) as rejected:
        collections.bind(record.agreement_id, in_duplum_trigger="not-a-trigger")
    assert rejected.value.code == "trigger-unset"
    assert collections.cases == {}
    bound = collections.bind(
        record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=5_000,
    )
    assert bound.trigger == "collections_default"
    assert bound.residual_threshold_cents == 5_000
    assert bound.collections_default is False
    assert bound.open_episode_ceiling is None
    assert bound.episode_count == 0
    with pytest.raises(CollectionsError) as frozen:
        collections.bind(record.agreement_id, in_duplum_trigger="contractual_breach")
    assert frozen.value.code == "elections-frozen"
    with pytest.raises(CollectionsError) as early:
        collections.observe(record.agreement_id, recognised_at=at(date(2026, 3, 2), 8))
    assert early.value.code == "status"
