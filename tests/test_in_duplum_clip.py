"""Day-1 in-duplum clip. The ceiling calculation is not changed here."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from lms.batch.service import BatchService
from lms.batch.store import BatchStore
from lms.collections.service import Collections
from lms.ledger.service import Ledger
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms_config.calendar import value_date
from lms_config.locked import IN_DUPLUM_CLIP_POSTS, OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"


def at(day: date, hour: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


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
        in_duplum_trigger="collections_default",
    )


def booked_loan(ledger: Ledger, cash: int = 100_000):
    return ledger.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=at(date(2026, 4, 1)),
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((date(2026, 5, 1), cash),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
        initiation_fee_cents=0,
    )


def test_clip_stops_at_the_ceiling_and_a_payment_does_not_restart_charges():
    assert IN_DUPLUM_CLIP_POSTS is True
    ledger = Ledger()
    loan = booked_loan(ledger)
    recognised = at(date(2026, 5, 1))
    assert recognised.hour == 0
    assert recognised.tzinfo == JOHANNESBURG
    assert value_date(recognised) == date(2026, 5, 1)
    ledger.open_in_duplum_episode(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=recognised,
        fall_away=False,
    )
    assert loan.episodes[0].ceiling_cents == 100_000
    assert loan.in_duplum_ceiling_reached is False
    posted = ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=150_000,
        due_on=date(2026, 5, 1),
        recognised_at=recognised,
        interest_cap_present=True,
    )
    assert posted.amount_cents == 100_000
    assert loan.episodes[0].accrued_cents == 100_000
    assert ledger.bucket_balance(loan, "interest") == 100_000
    assert loan.in_duplum_ceiling_reached is True
    assert loan.in_duplum_ceiling_warning is not None
    assert "Ceiling 100000 cents" in loan.in_duplum_ceiling_warning
    assert "Accrued 100000 cents" in loan.in_duplum_ceiling_warning
    status = ledger.in_duplum_clip_status(ORG, loan.loan_id)
    assert status["in_duplum_ceiling_reached"] is True
    assert status["warning"] == loan.in_duplum_ceiling_warning
    assert status["ceiling_cents"] == 100_000
    assert status["accrued_cents"] == 100_000
    warnings = [
        row
        for row in ledger.audit.extract(
            organisation_id=ORG, from_date=date(2026, 5, 1), to_date=date(2026, 5, 1)
        ).rows
        if row.event_type == "IN_DUPLUM_CEILING"
    ]
    assert len(warnings) == 1
    assert warnings[0].occurred_at == recognised
    assert warnings[0].payload["ceiling_cents"] == 100_000
    assert warnings[0].payload["accrued_cents"] == 100_000
    assert warnings[0].payload["warning"] == loan.in_duplum_ceiling_warning
    for bucket in ("credit_insurance", "default_administration", "collection_costs"):
        stopped = ledger.levy_charge(
            organisation_id=ORG,
            loan_id=loan.loan_id,
            bucket=bucket,
            cents=5_000,
            due_on=date(2026, 5, 1),
            recognised_at=recognised,
            interest_cap_present=True,
            tariff_cents=5_000,
        )
        assert stopped.amount_cents == 0
        assert ledger.bucket_balance(loan, bucket) == 0
    fee = ledger.levy_service_fee(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=recognised,
        monthly_cents=6_000,
        due_on=date(2026, 5, 1),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    assert fee.amount_cents == 0
    assert ledger.bucket_balance(loan, "service") == 0
    assert loan.episodes[0].accrued_cents == 100_000
    ledger.post_payment(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        cents=40_000,
        recognised_at=recognised,
        attributed_due_on=date(2026, 5, 1),
    )
    assert ledger.bucket_balance(loan, "interest") == 60_000
    assert loan.episodes[0].accrued_cents == 100_000
    assert loan.in_duplum_ceiling_reached is True
    again = ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=1_000,
        due_on=date(2026, 5, 1),
        recognised_at=recognised,
        interest_cap_present=True,
    )
    assert again.amount_cents == 0
    assert ledger.bucket_balance(loan, "interest") == 60_000
    warnings = [
        row
        for row in ledger.audit.extract(
            organisation_id=ORG, from_date=date(2026, 5, 1), to_date=date(2026, 5, 1)
        ).rows
        if row.event_type == "IN_DUPLUM_CEILING"
    ]
    assert len(warnings) == 1


def test_cure_clears_the_flag_and_a_later_default_opens_a_new_ceiling():
    ledger = Ledger()
    loan = booked_loan(ledger, cash=80_000)
    ledger.open_in_duplum_episode(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=at(date(2026, 5, 1)),
        fall_away=True,
    )
    ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=80_000,
        due_on=date(2026, 5, 1),
        recognised_at=at(date(2026, 5, 1)),
        interest_cap_present=True,
    )
    assert loan.in_duplum_ceiling_reached is True
    ledger.post_payment(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        cents=90_000,
        recognised_at=at(date(2026, 5, 2)),
        attributed_due_on=date(2026, 5, 1),
    )
    closed = ledger.close_in_duplum_episode(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=at(date(2026, 5, 2)),
    )
    assert closed.closed_on == date(2026, 5, 2)
    assert loan.in_duplum_ceiling_reached is False
    assert loan.in_duplum_ceiling_warning is None
    assert ledger.bucket_balance(loan, "interest") == 0
    assert ledger.bucket_balance(loan, "principal") == 70_000
    opened = ledger.open_in_duplum_episode(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        recognised_at=at(date(2026, 6, 1)),
        fall_away=True,
    )
    assert opened.episode_no == 2
    assert opened.ceiling_cents == 70_000
    assert opened.accrued_cents == 0
    assert loan.in_duplum_ceiling_reached is False
    posted = ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="collection_costs",
        cents=10_000,
        due_on=date(2026, 6, 1),
        recognised_at=at(date(2026, 6, 1)),
        interest_cap_present=True,
        tariff_cents=10_000,
    )
    assert posted.amount_cents == 10_000
    assert opened.accrued_cents == 10_000
    assert loan.in_duplum_ceiling_reached is False


def test_collections_default_cure_clears_the_flag_and_contractual_breach_does_not():
    servicing = Servicing(enigma=EnigmaStub())
    record = servicing.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 60_000), (date(2026, 7, 15), 40_000)),
        initiation_fee_cents=0,
        idempotency_key="book-clip",
    )
    record = servicing.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    collections = Collections(servicing)
    collections.bind(record.agreement_id, in_duplum_trigger="collections_default")
    collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16)))
    loan = servicing.ledger.store.get(ORG, record.ledger_loan_id or "")
    assert loan.episodes[0].closed_on is None
    servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=100_000,
        due_on=date(2026, 12, 1),
        recognised_at=at(date(2026, 6, 16)),
        interest_cap_present=True,
    )
    assert loan.in_duplum_ceiling_reached is True
    view = collections.view(record.agreement_id, at(date(2026, 6, 16)))
    assert view.in_duplum_ceiling_reached is True
    assert view.in_duplum_ceiling_warning == loan.in_duplum_ceiling_warning
    servicing.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=60_000,
        recognised_at=at(date(2026, 6, 16), 11),
        idempotency_key="cure",
        agreement_id=record.agreement_id,
        attributed_due_on=date(2026, 6, 15),
    )
    cured = collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 17)))
    assert cured.collections_default is False
    assert loan.episodes[0].closed_on == date(2026, 6, 17)
    assert loan.in_duplum_ceiling_reached is False
    assert cured.in_duplum_ceiling_reached is False
    assert cured.in_duplum_ceiling_warning is None
    warnings = [
        row
        for row in servicing.audit.extract(
            organisation_id=ORG, from_date=date(2026, 6, 16), to_date=date(2026, 6, 16)
        ).rows
        if row.event_type == "IN_DUPLUM_CEILING"
    ]
    assert len(warnings) == 1

    breach_servicing = Servicing(enigma=EnigmaStub())
    breach = breach_servicing.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=50_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 50_000),),
        initiation_fee_cents=0,
        idempotency_key="book-breach",
    )
    breach = breach_servicing.disburse(breach.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    breach_collections = Collections(breach_servicing)
    breach_collections.bind(breach.agreement_id, in_duplum_trigger="contractual_breach")
    breach_collections.observe(breach.agreement_id, recognised_at=at(date(2026, 6, 16)))
    breach_loan = breach_servicing.ledger.store.get(ORG, breach.ledger_loan_id or "")
    breach_servicing.ledger.levy_charge(
        organisation_id=ORG,
        loan_id=breach_loan.loan_id,
        bucket="interest",
        cents=50_000,
        due_on=date(2026, 12, 1),
        recognised_at=at(date(2026, 6, 16)),
        interest_cap_present=True,
    )
    assert breach_loan.in_duplum_ceiling_reached is True
    breach_servicing.accept_payment(
        organisation_id=ORG,
        person_id=PERSON,
        cents=50_000,
        recognised_at=at(date(2026, 6, 16), 11),
        idempotency_key="pay-breach",
        agreement_id=breach.agreement_id,
        attributed_due_on=date(2026, 6, 15),
    )
    held = breach_collections.observe(breach.agreement_id, recognised_at=at(date(2026, 6, 17)))
    assert breach_loan.episodes[0].closed_on is None
    assert breach_loan.in_duplum_ceiling_reached is True
    assert held.in_duplum_ceiling_reached is True
    assert held.in_duplum_ceiling_warning == breach_loan.in_duplum_ceiling_warning


def test_daily_batch_counts_accounts_at_the_ceiling(tmp_path: Path):
    class CeilingCalculation:
        def accrue(self, **kwargs: object) -> None:
            return None

        def capitalise(self, **kwargs: object) -> None:
            return None

        def default_check(self, **kwargs: object) -> None:
            return None

        def account_hit_in_duplum_ceiling(self, *, organisation_id: str, account_id: str) -> bool:
            assert organisation_id == "org-1"
            return account_id == "acc-2"

    store = BatchStore(str(tmp_path / "batch.sqlite"))
    service = BatchService(store, CeilingCalculation())
    try:
        finished = service.run_batch(
            organisation_id="org-1",
            actor_id="person-1",
            recognition_date="2026-10-28",
            account_ids=["acc-1", "acc-2", "acc-3"],
        )
        assert finished.accounts_processed == 3
        assert finished.accounts_failed == 0
        assert finished.accounts_at_ceiling == 1
        assert finished.recognition_at == "2026-10-28T00:00:00.000000+02:00"
        detail = service.audit_entries("org-1")[-1].detail
        assert "accounts_at_ceiling=1" in detail
        assert service.status("org-1").last_status is not None
        assert service.status("org-1").last_status.to_dict()["accounts_at_ceiling"] == 1
    finally:
        store.close()
