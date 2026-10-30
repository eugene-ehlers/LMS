"""Pins for the ledger. Expected amounts come from the calculation engine's own functions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lms.calc.interest import accrual_weight, daily_interest_rands, divisor_days, personal_annual_rate
from lms.calc.money import to_cents
from lms.calc.models import DayCount, Product, RepoFallChoice, RepoRate
from lms.ledger.errors import LedgerError
from lms.ledger.service import Ledger, next_due_date, nominal_annual
from lms_config.exceptions import CalculationInputError
from lms_config.locked import IN_DUPLUM_CLIP_POSTS, OrganisationSettings
from lms_config.statute import DAY_COUNT_30_360
from lms_config.templates import bnpl_zero, micro_short_term, unsecured_personal

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ROOT = Path(__file__).resolve().parents[1]


def at(year: int, month: int, day: int, hour: int = 8, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=JOHANNESBURG)


def provider_settings(**overrides) -> OrganisationSettings:
    values: dict = dict(
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


def credit(**instrument_overrides):
    product = micro_short_term()
    if instrument_overrides:
        product = replace(product, instruments=(replace(product.instruments[0], **instrument_overrides),))
    return product


def book(
    ledger: Ledger,
    *,
    organisation_id: str = "org-a",
    person_id: str = "person-a",
    when: datetime | None = None,
    cash: int = 100_000,
    product=None,
    settings: OrganisationSettings | None = None,
    schedule: tuple[tuple[date, int], ...] | None = None,
    initiation: int = 0,
    quoted: date | None = None,
    frequency: str = "monthly",
    name: str = "Ada Borrower",
    identity_number: str = "8001015800085",
    address: str = "1 Main Road, Cape Town",
):
    when = when or at(2026, 3, 1)
    return ledger.book(
        organisation_id=organisation_id,
        person_id=person_id,
        product=product or credit(),
        organisation=settings or provider_settings(),
        recognised_at=when,
        cash_advanced_cents=cash,
        frequency=frequency,
        schedule=schedule or ((date(2026, 12, 15), cash + initiation),),
        identity_name=name,
        identity_number=identity_number,
        service_address=address,
        quoted_disbursement=quoted,
        initiation_fee_cents=initiation,
    )


def test_net_balance_interest_with_linked_laybye():
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
    accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 15),
        interest_cap_present=True,
    )
    assert accrual.principal_cents == 100_000
    assert accrual.hold_cents == 40_000
    assert accrual.base_cents == 60_000
    assert accrual.day_rands == daily_interest_rands(60_000, Decimal("0.05"), 31, weight=1)
    assert ledger.bucket_balance(parent, "principal") == 100_000

    bare = book(ledger, person_id="person-b")
    bare_accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=bare.loan_id,
        recognised_at=at(2026, 3, 15),
        interest_cap_present=True,
    )
    assert bare_accrual.day_rands == daily_interest_rands(100_000, Decimal("0.05"), 31, weight=1)
    assert bare_accrual.day_rands > accrual.day_rands

    flagged = ledger.flag_default(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        check_on=date(2026, 3, 15),
        due_on=date(2026, 3, 15),
        instalment_cents=10_000,
        recognised_at=at(2026, 3, 15, 9),
    )
    assert flagged is True
    assert parent.episodes[0].ceiling_cents == 100_000


def test_hold_above_principal_floors_the_interest_base():
    ledger = Ledger()
    parent = book(ledger)
    ledger.open_laybye(
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 2),
        amount_cents=150_000,
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )
    accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 3),
        interest_cap_present=True,
    )
    assert accrual.base_cents == 0
    assert accrual.day_rands == Decimal(0)
    assert ledger.bucket_balance(parent, "principal") == 100_000


def test_in_duplum_fresh_ceiling_on_second_default():
    ledger = Ledger()
    loan = book(
        ledger,
        when=at(2026, 4, 1),
        schedule=((date(2026, 4, 15), 10_000), (date(2026, 5, 15), 90_000)),
    )
    assert ledger.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 4, 15),
        due_on=date(2026, 4, 15),
        instalment_cents=10_000,
        recognised_at=at(2026, 4, 15, 8),
    )
    assert loan.episodes[0].ceiling_cents == 100_000
    ledger.levy_charge(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        bucket="interest",
        cents=10_000,
        due_on=date(2026, 4, 15),
        recognised_at=at(2026, 4, 15, 9),
        interest_cap_present=True,
    )
    assert loan.episodes[0].accrued_cents == 10_000
    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=10_000,
        recognised_at=at(2026, 4, 15, 10),
        attributed_due_on=date(2026, 4, 15),
    )
    assert loan.episodes[0].accrued_cents == 10_000
    assert ledger.bucket_balance(loan, "principal") == 100_000
    assert ledger.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 4, 15),
        due_on=date(2026, 4, 15),
        instalment_cents=10_000,
        recognised_at=at(2026, 4, 15, 11),
    ) is False
    assert loan.episodes[0].closed_on == date(2026, 4, 15)

    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=20_000,
        recognised_at=at(2026, 4, 16),
        attributed_due_on=date(2026, 4, 15),
    )
    assert ledger.bucket_balance(loan, "principal") == 80_000
    assert ledger.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 5, 15),
        due_on=date(2026, 5, 15),
        instalment_cents=10_000,
        recognised_at=at(2026, 5, 15),
    )
    assert loan.episodes[1].ceiling_cents == 80_000
    assert loan.episodes[0].ceiling_cents == 100_000
    assert loan.episodes[0].accrued_cents == 10_000
    ledger.levy_charge(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        bucket="interest",
        cents=90_000,
        due_on=date(2026, 5, 15),
        recognised_at=at(2026, 5, 15, 9),
        interest_cap_present=True,
    )
    assert loan.episodes[1].accrued_cents == 80_000
    assert ledger.bucket_balance(loan, "interest") == 80_000
    assert loan.in_duplum_ceiling_reached is True
    assert IN_DUPLUM_CLIP_POSTS is True
    ledger.clip_in_duplum()


def test_payment_allocation_order():
    ledger = Ledger()
    due = date(2026, 3, 20)
    loan = book(ledger, when=at(2026, 3, 1), schedule=((due, 100_000),))
    common = dict(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        due_on=due,
        interest_cap_present=True,
    )
    ledger.levy_charge(**common, bucket="interest", cents=100, recognised_at=at(2026, 3, 20, 8))
    ledger.levy_charge(
        **common, bucket="collection_costs", cents=50, tariff_cents=50, recognised_at=at(2026, 3, 20, 8, 1)
    )
    ledger.levy_charge(
        **common,
        bucket="default_administration",
        cents=40,
        tariff_cents=40,
        recognised_at=at(2026, 3, 20, 8, 2),
    )
    ledger.levy_charge(**common, bucket="credit_insurance", cents=30, recognised_at=at(2026, 3, 20, 8, 3))
    ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 20, 8, 4),
        monthly_cents=20,
        due_on=due,
        interest_cap_present=True,
        vat_rate=Decimal(0),
        vat_registered=False,
    )
    ledger.levy_charge(**common, bucket="initiation", cents=10, recognised_at=at(2026, 3, 20, 8, 5))

    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=10,
        recognised_at=at(2026, 3, 20, 9),
        attributed_due_on=due,
    )
    assert ledger.bucket_balance(loan, "interest") == 90
    assert ledger.bucket_balance(loan, "collection_costs") == 50
    assert ledger.bucket_balance(loan, "principal") == 100_000

    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=235,
        recognised_at=at(2026, 3, 20, 10),
        attributed_due_on=due,
    )
    assert ledger.bucket_balance(loan, "interest") == 0
    assert ledger.bucket_balance(loan, "collection_costs") == 0
    assert ledger.bucket_balance(loan, "default_administration") == 0
    assert ledger.bucket_balance(loan, "credit_insurance") == 0
    assert ledger.bucket_balance(loan, "service") == 0
    assert ledger.bucket_balance(loan, "initiation") == 5
    assert ledger.bucket_balance(loan, "principal") == 100_000


def test_reversal_uses_original_value_date():
    ledger = Ledger()
    cash = 100_000
    loan = book(ledger, when=at(2026, 3, 1, 9), schedule=((date(2026, 3, 1), cash),))
    payment = ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=5_000,
        recognised_at=at(2026, 3, 1, 11),
        attributed_due_on=date(2026, 3, 1),
    )
    original_entries = payment.entries
    reversal = ledger.reverse(
        organisation_id="org-a",
        transaction_id=payment.transaction_id,
        recognised_at=at(2026, 3, 10, 15),
    )
    assert payment.value_date == date(2026, 3, 1)
    assert reversal.value_date == payment.value_date
    assert reversal.recognised_at != payment.recognised_at
    assert payment.entries == original_entries
    assert ledger.bucket_balance(loan, "principal") == cash
    assert all(
        transaction.value_date != date(2026, 3, 10)
        for transaction in ledger.store.transactions_for("org-a", loan.loan_id)
    )
    period = ledger.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 1),
    )
    assert period.loans[0].closing["principal"] == cash
    later = ledger.statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 10),
        period_end=date(2026, 3, 10),
    )
    assert later.loans[0].opening["principal"] == cash
    assert later.loans[0].closing["principal"] == cash


@pytest.mark.parametrize(
    "field",
    ["partial_prepayment", "late_disbursement", "interest_on_deferred_initiation", "repo_rate_fall"],
)
def test_missing_election_fails_closed(field):
    ledger = Ledger()
    with pytest.raises(CalculationInputError):
        book(ledger, settings=provider_settings(**{field: None}))
    assert ledger.store.accounts_for("org-a") == ()


def test_tenant_isolation():
    ledger = Ledger()
    loan_a = book(ledger, organisation_id="org-a", person_id="person-a")
    loan_b = book(ledger, organisation_id="org-b", person_id="person-b")
    with pytest.raises(LedgerError) as caught:
        ledger.store.get("org-b", loan_a.loan_id)
    assert caught.value.code == "not-found"
    assert [account.loan_id for account in ledger.store.accounts_for("org-a")] == [loan_a.loan_id]
    assert ledger.store.transactions_for("org-b", loan_a.loan_id) == ()
    statement = ledger.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert [line.loan_id for line in statement.loans] == [loan_a.loan_id]
    other = ledger.issue_statement(
        organisation_id="org-b",
        person_id="person-b",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert [line.loan_id for line in other.loans] == [loan_b.loan_id]


def test_value_date_is_johannesburg_recognition_date():
    ledger = Ledger()
    loan = book(ledger, when=datetime(2026, 3, 5, 22, 30, tzinfo=timezone.utc))
    assert loan.disbursement_value_date == date(2026, 3, 6)


def test_same_day_events_follow_recognition_sequence():
    ledger = Ledger()
    loan = book(ledger, when=at(2026, 3, 5, 7), schedule=((date(2026, 3, 5), 100_000),))
    later_clock = ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=1_000,
        recognised_at=at(2026, 3, 5, 18),
        attributed_due_on=date(2026, 3, 5),
    )
    earlier_clock = ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=1_000,
        recognised_at=at(2026, 3, 5, 8),
        attributed_due_on=date(2026, 3, 5),
    )
    ordered = ledger.ordered_receipts("org-a", loan.loan_id)
    assert ordered[0].sequence == later_clock.recognition_sequence
    assert ordered[1].sequence == earlier_clock.recognition_sequence
    assert ordered[0].sequence < ordered[1].sequence
    assert {item.recognised_at.astimezone(JOHANNESBURG).date() for item in ordered} == {date(2026, 3, 5)}


def test_thirty_360_uses_the_calculator_weight():
    ledger = Ledger()
    product = credit(day_count=DAY_COUNT_30_360)
    loan = book(ledger, product=product, when=at(2024, 2, 1), schedule=((date(2024, 12, 15), 100_000),))
    march_31 = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2024, 3, 31),
        interest_cap_present=True,
    )
    assert march_31.weight == accrual_weight(date(2024, 3, 31), DayCount.THIRTY_360) == 0
    assert march_31.day_rands == Decimal(0)
    february = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2024, 2, 29),
        interest_cap_present=True,
    )
    weight = accrual_weight(date(2024, 2, 29), DayCount.THIRTY_360)
    assert february.weight == weight
    assert february.day_rands == daily_interest_rands(100_000, Decimal("0.05"), 30, weight=weight)


def test_zero_rate_and_zero_fee_do_not_fail():
    ledger = Ledger()
    loan = book(
        ledger,
        product=credit(base_rate=Decimal(0), discount_rate=Decimal(0), monthly_rate=Decimal(0)),
    )
    accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=True,
    )
    assert accrual.day_rands == Decimal(0)
    ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2, 9),
        monthly_cents=0,
        due_on=date(2026, 3, 2),
        interest_cap_present=True,
    )
    with pytest.raises(LedgerError) as caught:
        ledger.levy_service_fee(
            organisation_id="org-a",
            loan_id=loan.loan_id,
            recognised_at=at(2026, 3, 2, 10),
            monthly_cents=0,
            due_on=date(2026, 3, 2),
            interest_cap_present=True,
        )
    assert caught.value.code == "service-fee-once"

    zero = book(ledger, person_id="person-z", product=bnpl_zero(), schedule=((date(2026, 12, 15), 100_000),))
    zero_accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=zero.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=False,
    )
    assert zero_accrual.day_rands == Decimal(0)


def test_campaign_discount_falls_away_on_the_flag_date_and_stays_off():
    ledger = Ledger()
    product = credit(discount_rate=Decimal("0.02"))
    settings = provider_settings(leniency_days=5)
    loan = book(ledger, product=product, settings=settings)
    before = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 3),
        interest_cap_present=True,
    )
    assert before.periodic_rate == Decimal("0.03")
    assert before.day_rands == daily_interest_rands(100_000, Decimal("0.03"), 31, weight=1)
    assert ledger.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 3, 6),
        due_on=date(2026, 3, 1),
        instalment_cents=10_000,
        recognised_at=at(2026, 3, 6),
    )
    on_flag = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 6, 9),
        interest_cap_present=True,
    )
    assert on_flag.periodic_rate == Decimal("0.05")
    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=10_000,
        recognised_at=at(2026, 3, 6, 10),
        attributed_due_on=date(2026, 3, 1),
    )
    assert ledger.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 3, 7),
        due_on=date(2026, 3, 1),
        instalment_cents=10_000,
        recognised_at=at(2026, 3, 7, 10),
    ) is False
    after_cure = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 8),
        interest_cap_present=True,
    )
    assert loan.discount_fallen_away is True
    assert after_cure.periodic_rate == Decimal("0.05")
    assert after_cure.base_cents == 90_000


def test_one_service_fee_on_the_parent():
    ledger = Ledger()
    parent = book(ledger)
    child = ledger.open_laybye(
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 2),
        amount_cents=1_000,
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )
    with pytest.raises(LedgerError) as caught:
        ledger.levy_service_fee(
            organisation_id="org-a",
            loan_id=child.loan_id,
            recognised_at=at(2026, 3, 3),
            monthly_cents=6_000,
            due_on=date(2026, 3, 15),
            interest_cap_present=True,
            vat_rate=Decimal(0),
        )
    assert caught.value.code == "service-fee-parent"
    ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 3, 3),
        monthly_cents=6_000,
        due_on=date(2026, 3, 15),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    with pytest.raises(LedgerError) as again:
        ledger.levy_service_fee(
            organisation_id="org-a",
            loan_id=parent.loan_id,
            recognised_at=at(2026, 3, 20),
            monthly_cents=6_000,
            due_on=date(2026, 3, 20),
            interest_cap_present=True,
            vat_rate=Decimal(0),
        )
    assert again.value.code == "service-fee-once"


def test_capitalised_initiation_is_principal_and_separate_is_a_fee():
    ledger = Ledger()
    capitalised = book(
        ledger,
        product=replace(credit(), initiation_capitalised=True),
        initiation=15_000,
        schedule=((date(2026, 12, 15), 115_000),),
    )
    assert ledger.bucket_balance(capitalised, "principal") == 115_000
    assert ledger.bucket_balance(capitalised, "initiation") == 0
    assert capitalised.capitalised_initiation_cents == 15_000

    separate = book(
        ledger,
        person_id="person-b",
        initiation=15_000,
        schedule=((date(2026, 12, 15), 100_000),),
    )
    assert ledger.bucket_balance(separate, "principal") == 100_000
    assert ledger.bucket_balance(separate, "initiation") == 15_000


def test_prepayment_choice_comes_from_configuration():
    first_due = date(2026, 6, 15)
    second_due = date(2026, 7, 15)
    schedule = ((first_due, 50_000), (second_due, 50_000))
    shorten = Ledger()
    shorten_loan = book(shorten, schedule=schedule, settings=provider_settings(partial_prepayment="shorten_term"))
    shorten.post_payment(
        organisation_id="org-a",
        loan_id=shorten_loan.loan_id,
        cents=10_000,
        recognised_at=at(2026, 3, 20),
        attributed_due_on=first_due,
    )
    assert [slice_.remaining_cents for slice_ in shorten_loan.slices] == [50_000, 40_000]

    drop = Ledger()
    drop_loan = book(drop, schedule=schedule, settings=provider_settings(partial_prepayment="drop_instalment"))
    drop.post_payment(
        organisation_id="org-a",
        loan_id=drop_loan.loan_id,
        cents=10_000,
        recognised_at=at(2026, 3, 20),
        attributed_due_on=first_due,
    )
    assert [slice_.remaining_cents for slice_ in drop_loan.slices] == [40_000, 50_000]


def test_late_disbursement_records_the_choice_and_does_not_rewrite_amounts():
    lines = ((date(2026, 6, 15), 100_000),)
    ledger = Ledger()
    kept = book(
        ledger,
        when=at(2026, 3, 5, 9),
        quoted=date(2026, 3, 1),
        schedule=lines,
        settings=provider_settings(late_disbursement="keep_instalment"),
    )
    assert kept.schedule_versions[0].reason == "late_disbursement"
    assert kept.schedule_versions[0].late_disbursement == "keep_instalment"
    assert kept.schedule_versions[0].lines == lines

    adjusted = book(
        Ledger(),
        when=at(2026, 3, 5, 9),
        quoted=date(2026, 3, 1),
        schedule=lines,
        settings=provider_settings(late_disbursement="adjust_instalment"),
    )
    assert adjusted.schedule_versions[0].late_disbursement == "adjust_instalment"
    assert adjusted.schedule_versions[0].lines == lines


def test_unbilled_interest_is_not_allocated():
    ledger = Ledger()
    loan = book(ledger)
    accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 2),
        interest_cap_present=True,
    )
    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=1_000,
        recognised_at=at(2026, 3, 3),
        attributed_due_on=date(2026, 12, 15),
    )
    assert ledger.bucket_balance(loan, "interest") == 0
    assert ledger.bucket_balance(loan, "principal") == 99_000
    stored = ledger.store.get_transaction("org-a", accrual.transaction_id)
    assert stored.memo_rands == accrual.day_rands


def test_billing_rounds_half_up_on_the_accrued_total():
    ledger = Ledger()
    loan = book(ledger)
    total = Decimal(0)
    for day in (2, 3, 4):
        accrual = ledger.accrue_day(
            organisation_id="org-a",
            loan_id=loan.loan_id,
            recognised_at=at(2026, 3, day),
            interest_cap_present=True,
        )
        total += accrual.day_rands
    bill = ledger.bill_interest(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 5),
    )
    assert bill is not None
    assert ledger.bucket_balance(loan, "interest") == to_cents(total)
    assert ledger.bill_interest(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 5, 9),
    ) is None


def test_collection_cost_fails_without_a_tariff_row():
    ledger = Ledger()
    loan = book(ledger)
    with pytest.raises(CalculationInputError):
        ledger.levy_charge(
            organisation_id="org-a",
            loan_id=loan.loan_id,
            bucket="collection_costs",
            cents=100,
            due_on=date(2026, 3, 15),
            recognised_at=at(2026, 3, 15),
            interest_cap_present=True,
            tariff_cents=None,
        )


def test_additional_monthly_fee_is_not_capitalised():
    ledger = Ledger()
    loan = book(ledger)
    ledger.levy_charge(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        bucket="additional_monthly",
        cents=500,
        due_on=date(2026, 3, 15),
        recognised_at=at(2026, 3, 15),
        interest_cap_present=True,
    )
    ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 15, 9),
        monthly_cents=500,
        due_on=date(2026, 3, 15),
        interest_cap_present=True,
        vat_rate=Decimal(0),
        vat_registered=False,
    )
    with pytest.raises(LedgerError) as caught:
        ledger.post_payment(
            organisation_id="org-a",
            loan_id=loan.loan_id,
            cents=100,
            recognised_at=at(2026, 3, 16),
            attributed_due_on=date(2026, 3, 15),
        )
    assert caught.value.code == "additional-fee-order-unset"
    assert ledger.bucket_balance(loan, "principal") == 100_000


def test_frequencies_and_half_up_disclosure():
    assert next_due_date(date(2026, 1, 15), "weekly") == date(2026, 1, 22)
    assert next_due_date(date(2026, 1, 15), "fortnightly") == date(2026, 1, 29)
    assert next_due_date(date(2026, 1, 15), "monthly") == date(2026, 2, 15)
    assert next_due_date(date(2026, 1, 15), "quarterly") == date(2026, 4, 15)
    assert next_due_date(date(2026, 1, 15), "bi_annual") == date(2026, 7, 15)
    assert next_due_date(date(2026, 1, 15), "annual") == date(2027, 1, 15)
    with pytest.raises(LedgerError) as caught:
        next_due_date(date(2026, 1, 31), "monthly")
    assert caught.value.code == "due-date-unspecified"
    assert nominal_annual(Decimal("0.05"), 12) == Decimal("0.60")


def test_blank_identity_is_refused():
    ledger = Ledger()
    with pytest.raises(LedgerError) as caught:
        book(ledger, name=" ")
    assert caught.value.code == "identity-missing"
    assert ledger.store.accounts_for("org-a") == ()


def test_frozen_identity_is_not_rewritten():
    ledger = Ledger()
    loan = book(ledger)
    with pytest.raises(LedgerError) as caught:
        loan.frozen_full_name = "Someone Else"
    assert caught.value.code == "identity-frozen"


def test_one_statement_covers_every_loan_for_the_client():
    ledger = Ledger()
    first = book(ledger, person_id="person-a")
    second = book(ledger, person_id="person-a")
    statement = ledger.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert {line.loan_id for line in statement.loans} == {first.loan_id, second.loan_id}
    with pytest.raises(LedgerError) as caught:
        ledger.issue_statement(
            organisation_id="org-a",
            person_id="person-a",
            period_start=date(2026, 3, 15),
            period_end=date(2026, 4, 15),
        )
    assert caught.value.code == "statement-exists"


def test_unsecured_repo_fall_uses_the_calculator():
    ledger = Ledger()
    repos = (
        RepoRate(date(2026, 1, 1), Decimal("0.08")),
        RepoRate(date(2026, 4, 1), Decimal("0.02")),
    )
    loan = book(
        ledger,
        product=unsecured_personal(),
        settings=provider_settings(repo_rate_fall="lower_of_contract_and_cap"),
        schedule=((date(2026, 12, 15), 100_000),),
    )
    day = date(2026, 4, 2)
    accrual = ledger.accrue_day(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 4, 2),
        interest_cap_present=True,
        repos=repos,
        repo_annual=Decimal("0.02"),
    )
    expected = personal_annual_rate(
        day,
        loan.snapshot.base_rate,
        repos,
        advance_date=loan.disbursement_value_date,
        repo_fall=RepoFallChoice.LOWER_OF_CONTRACT_AND_CAP,
    )
    assert accrual.periodic_rate == expected
    assert accrual.day_rands == daily_interest_rands(
        accrual.base_cents,
        expected,
        divisor_days(day, Product.PERSONAL, DayCount.ACTUAL),
        weight=1,
    )


def test_unattributed_receipt_fails_the_morning_check():
    ledger = Ledger()
    loan = book(ledger)
    ledger.post_payment(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        cents=1_000,
        recognised_at=at(2026, 3, 2),
        attributed_due_on=None,
    )
    with pytest.raises(LedgerError) as caught:
        ledger.flag_default(
            organisation_id="org-a",
            loan_id=loan.loan_id,
            check_on=date(2026, 3, 15),
            due_on=date(2026, 3, 15),
            instalment_cents=1_000,
            recognised_at=at(2026, 3, 15),
        )
    assert caught.value.code == "due-date-attribution-unset"


def test_migration_states_the_locked_shape():
    sql = (ROOT / "db" / "migrations" / "0004_ledger_accounts.sql").read_text()
    for bucket in (
        "principal",
        "interest",
        "initiation",
        "service",
        "credit_insurance",
        "default_administration",
        "collection_costs",
        "additional_monthly",
        "laybye_hold",
    ):
        assert f"'{bucket}'" in sql
    for frequency in ("weekly", "fortnightly", "monthly", "quarterly", "bi_annual", "annual"):
        assert f"'{frequency}'" in sql
    assert "reversal value_date must be the original recognised value date" in sql
    assert "ledger is append-only" in sql
    assert "lms.organisation_id" in sql
    assert "loan_one_laybye_child" in sql
    assert "lms.loan_bucket_balance" in sql
    assert "facts frozen at booking" in sql


def test_postgres_reversal_value_date_append_only_and_tenant():
    import shutil
    import subprocess

    binary = shutil.which("psql")
    if binary is None:
        pytest.skip("psql is not installed")
    probe = subprocess.run(
        ["sudo", "-u", "postgres", binary, "-d", "postgres", "-c", "SELECT 1"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(probe.stderr.strip() or "postgres is not running")
    present = subprocess.run(
        [
            "sudo", "-u", "postgres", binary, "-d", "postgres", "-tAc",
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'lms' AND table_name = 'loan_account'",
        ],
        capture_output=True,
        text=True,
    )
    if present.returncode != 0:
        raise AssertionError(present.stderr)
    if present.stdout.strip() != "1":
        schema = subprocess.run(
            [
                "sudo", "-u", "postgres", binary, "-d", "postgres", "-tAc",
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'lms'",
            ],
            capture_output=True,
            text=True,
        )
        files = []
        if schema.stdout.strip() != "1":
            files.extend(["0001_lms_owned.sql", "0002_locked_decisions.sql", "0003_elections.sql"])
        files.append("0004_ledger_accounts.sql")
        for name in files:
            apply = subprocess.run(
                [
                    "sudo", "-u", "postgres", binary, "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "db" / "migrations" / name),
                ],
                capture_output=True,
                text=True,
            )
            if apply.returncode != 0:
                raise AssertionError(apply.stderr)
    sql = """
BEGIN;
INSERT INTO lms.loan_account (
  organisation_id, loan_id, person_id, instrument_kind,
  frozen_full_name, frozen_id_number, frozen_service_address,
  classification, payment_frequency, disbursement_value_date, contractual_end,
  cash_advanced_cents
) VALUES (
  'org-a', '00000000-0000-4000-8000-0000000000a1', 'person-a', 'loan',
  'Ada Borrower', '8001015800085', '1 Main Road',
  'short_term', 'monthly', DATE '2026-03-01', DATE '2026-12-15',
  100000
);
INSERT INTO lms.election_snapshot (
  organisation_id, loan_id, leniency_days, full_payment_threshold_percent,
  interest_on_deferred_initiation, repo_rate_fall, day_count_code,
  base_rate, discount_rate, vat_on_rand_maxima, late_disbursement, partial_prepayment
) VALUES (
  'org-a', '00000000-0000-4000-8000-0000000000a1', 0, 100,
  'none', 'contract_rate', 'actual_actual',
  0.05000000, 0, 'exclusive', 'keep_instalment', 'shorten_term'
);
INSERT INTO lms.ledger_transaction (
  organisation_id, transaction_id, loan_id, kind, value_date, recognised_at
) VALUES (
  'org-a', '00000000-0000-4000-8000-0000000000b1',
  '00000000-0000-4000-8000-0000000000a1', 'booking',
  DATE '2026-03-01', TIMESTAMPTZ '2026-03-01 07:00:00+00'
);
INSERT INTO lms.ledger_entry (
  organisation_id, transaction_id, loan_id, account_code, bucket, debit_cents, credit_cents
) VALUES
  ('org-a', '00000000-0000-4000-8000-0000000000b1', '00000000-0000-4000-8000-0000000000a1', 'principal', 'principal', 100000, 0),
  ('org-a', '00000000-0000-4000-8000-0000000000b1', '00000000-0000-4000-8000-0000000000a1', 'cash', NULL, 0, 100000);
DO $$
BEGIN
  UPDATE lms.ledger_entry SET debit_cents = debit_cents WHERE organisation_id = 'org-a';
  RAISE EXCEPTION 'update accepted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
END $$;
DO $$
BEGIN
  INSERT INTO lms.ledger_transaction (
    organisation_id, transaction_id, loan_id, kind, value_date, recognised_at, reverses_transaction_id
  ) VALUES (
    'org-a', '00000000-0000-4000-8000-0000000000b2',
    '00000000-0000-4000-8000-0000000000a1', 'reversal',
    DATE '2026-03-10', TIMESTAMPTZ '2026-03-10 07:00:00+00',
    '00000000-0000-4000-8000-0000000000b1'
  );
  RAISE EXCEPTION 'wrong reversal date accepted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM NOT LIKE '%original recognised value date%' THEN RAISE; END IF;
END $$;
DO $$
BEGIN
  UPDATE lms.loan_account SET frozen_full_name = 'Changed' WHERE organisation_id = 'org-a';
  RAISE EXCEPTION 'identity rewrite accepted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM NOT LIKE '%frozen at booking%' THEN RAISE; END IF;
END $$;
SET ROLE lms_app;
SELECT set_config('lms.organisation_id', 'org-b', true);
SELECT format('RESULT other=%s', (SELECT count(*) FROM lms.loan_account));
SELECT set_config('lms.organisation_id', 'org-a', true);
SELECT format(
  'RESULT own=%s seq=%s balance=%s',
  (SELECT count(*) FROM lms.loan_account),
  (SELECT recognition_sequence FROM lms.ledger_transaction),
  lms.loan_bucket_balance(
    'org-a', '00000000-0000-4000-8000-0000000000a1', 'principal', DATE '2026-03-01'
  )
);
RESET ROLE;
ROLLBACK;
"""
    completed = subprocess.run(
        ["sudo", "-u", "postgres", binary, "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    assert "RESULT other=0" in completed.stdout
    assert "RESULT own=1 seq=1 balance=100000" in completed.stdout
