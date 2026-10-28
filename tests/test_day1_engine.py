"""Pins for the 28 October 2026 locked decisions that the pure calculator now enforces."""

from datetime import date
from decimal import Decimal

import pytest

from lms.calc.allocation import allocate_payment
from lms.calc.examples import VAT_15
from lms.calc.fees import initiation_fee, opening_service_fraction
from lms.calc.interest import interest_for_dates, nominal_annual_rate, periods_per_year
from lms.calc.ledger import charge_remaining, run
from lms.calc.models import (
    Agreement,
    Charge,
    DayCount,
    FeeCapBasis,
    Payment,
    Policy,
    PrepaymentChoice,
    PrincipalSlice,
    Product,
    RepoFallChoice,
    RepoRate,
    State,
)
from lms.calc.money import RuleError, to_cents

STATED = dict(leniency_days=1, full_payment_threshold_percent=Decimal("100"))


def _micro_due(due: date, **kwargs: object) -> Agreement:
    return Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 3, 1),
        maturity_date=date(2026, 6, 30),
        initiation_paid_upfront=True,
        principal_instalments=((due, 100_000),),
        **kwargs,  # type: ignore[arg-type]
    )


def _fee(on: date) -> int:
    return initiation_fee(100_000, on=on, vat_rates=VAT_15, basis=FeeCapBasis.EXCLUSIVE)[2]


def test_unset_leniency_and_threshold_fail_closed():
    agreement = _micro_due(date(2026, 3, 31))
    with pytest.raises(RuleError) as missing_both:
        run(agreement, until=date(2026, 3, 1), policy=Policy(), vat_rates=VAT_15)
    assert missing_both.value.code == "leniency-unset"
    with pytest.raises(RuleError) as missing_threshold:
        run(
            agreement,
            until=date(2026, 3, 1),
            policy=Policy(leniency_days=1),
            vat_rates=VAT_15,
        )
    assert missing_threshold.value.code == "threshold-unset"


def test_flag_date_payment_is_visible_to_the_morning_check():
    agreement = _micro_due(date(2026, 3, 31))
    opened = (Payment(date(2026, 3, 1), _fee(date(2026, 3, 1)), purpose="initiation_upfront"),)
    march = run(agreement, opened, until=date(2026, 3, 31), policy=Policy(**STATED), vat_rates=VAT_15).state
    bundle = sum(charge.remaining_cents for charge in march.charges) + march.principal_cents
    # The one-cent receipt is recognised after the bundle receipt, even though it
    # appears first in the event tuple. Both are 00:00 on the flag date.
    paid = run(
        agreement,
        opened
        + (
            Payment(date(2026, 4, 1), 1, sequence=2),
            Payment(date(2026, 4, 1), bundle - 1, sequence=1),
        ),
        until=date(2026, 4, 1),
        policy=Policy(**STATED),
        vat_rates=VAT_15,
    ).state
    missed = run(agreement, opened, until=date(2026, 4, 1), policy=Policy(**STATED), vat_rates=VAT_15).state
    assert paid.in_default is False
    assert paid.episodes == ()
    assert paid.unbilled_duplum == 0
    assert missed.in_default is True
    assert missed.episodes[0].started_on == date(2026, 4, 1)
    assert missed.unbilled_duplum > 0
    assert missed.unbilled_ordinary == 0


def test_leniency_counts_the_weekend_and_a_public_holiday():
    # 3 April 2026 is a Friday. Two calendar days of leniency flag on Sunday 5 April.
    friday = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 4, 1),
        maturity_date=date(2026, 6, 30),
        initiation_paid_upfront=True,
        principal_instalments=((date(2026, 4, 3), 100_000),),
    )
    opened = (Payment(date(2026, 4, 1), _fee(date(2026, 4, 1)), purpose="initiation_upfront"),)
    policy = Policy(leniency_days=2, full_payment_threshold_percent=Decimal("100"))
    saturday = run(friday, opened, until=date(2026, 4, 4), policy=policy, vat_rates=VAT_15).state
    sunday = run(friday, opened, until=date(2026, 4, 5), policy=policy, vat_rates=VAT_15).state
    assert saturday.in_default is False
    assert sunday.in_default is True

    # 27 April 2026 is Freedom Day. Leniency does not skip it.
    holiday = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 4, 1),
        maturity_date=date(2026, 6, 30),
        initiation_paid_upfront=True,
        principal_instalments=((date(2026, 4, 26), 100_000),),
    )
    flagged = run(
        holiday,
        opened,
        until=date(2026, 4, 27),
        policy=Policy(**STATED),
        vat_rates=VAT_15,
    ).state
    assert flagged.in_default is True
    assert flagged.episodes[0].started_on == date(2026, 4, 27)


def test_capitalised_initiation_is_inside_the_duplum_ceiling():
    common = dict(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 5, 1),
        maturity_date=date(2026, 10, 31),
    )
    capitalised = Agreement(initiation_capitalised=True, **common)
    deferred = Agreement(**common)
    policy = Policy(**STATED)
    capital_state = run(capitalised, until=date(2026, 6, 1), policy=policy, vat_rates=VAT_15).state
    deferred_state = run(deferred, until=date(2026, 6, 1), policy=policy, vat_rates=VAT_15).state
    fee_total = _fee(date(2026, 5, 1))
    assert fee_total == 17_250
    assert charge_remaining(capital_state, "initiation") == 0
    assert capital_state.principal_cents == 100_000 + fee_total
    assert capital_state.episodes[0].ceiling_cents == 100_000 + fee_total
    assert deferred_state.episodes[0].ceiling_cents == 100_000
    assert charge_remaining(deferred_state, "initiation") == fee_total


def test_actual_and_30_360_day_counts():
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=200_000,
        advance_date=date(2026, 1, 1),
        maturity_date=date(2026, 7, 1),
    )
    actual = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 20),
        end=date(2026, 1, 31),
        day_count=DayCount.ACTUAL,
    )
    thirty = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 20),
        end=date(2026, 1, 31),
        day_count=DayCount.THIRTY_360,
    )
    through_30 = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 20),
        end=date(2026, 1, 30),
        day_count=DayCount.THIRTY_360,
    )
    full_actual = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        day_count=DayCount.ACTUAL,
    )
    full_thirty = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        day_count=DayCount.THIRTY_360,
    )
    assert to_cents(actual) == 3_871
    assert to_cents(thirty) == 3_667
    assert to_cents(through_30) == to_cents(thirty)
    assert to_cents(full_actual) == 10_000
    assert to_cents(full_thirty) == 10_000


def test_repo_choice_fails_closed_and_nominal_rate_is_simple():
    personal = Agreement(
        product=Product.PERSONAL,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=1_000_000,
        advance_date=date(2026, 1, 1),
        maturity_date=date(2027, 1, 1),
        margin_annual=Decimal("0.21"),
    )
    repos = (RepoRate(date(2026, 1, 1), Decimal("0.0725")),)
    with pytest.raises(RuleError) as unset:
        interest_for_dates(
            base_cents=1_000_000,
            agreement=personal,
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
            repos=repos,
        )
    assert unset.value.code == "repo-choice-unset"
    exact = interest_for_dates(
        base_cents=1_000_000,
        agreement=personal,
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        repos=repos,
        day_count=DayCount.THIRTY_360,
        repo_fall=RepoFallChoice.LOWER_OF_CONTRACT_AND_CAP,
    )
    assert to_cents(exact) == 282_500
    assert nominal_annual_rate(Decimal("0.05"), periods_per_year(Product.MICRO)) == Decimal("0.60")
    assert nominal_annual_rate(Decimal("0.2825"), periods_per_year(Product.PERSONAL)) == Decimal("0.2825")
    assert opening_service_fraction(date(2026, 3, 15), date(2026, 9, 15)) == Decimal(1)
    assert opening_service_fraction(date(2026, 3, 1), date(2026, 3, 31)) == Decimal(30) / Decimal(31)


def test_fee_buckets_are_paid_in_the_locked_order():
    def charge(sequence: int, kind: str, due: date, amount: int) -> Charge:
        return Charge(
            f"c{sequence}",
            kind,
            due,
            due,
            amount,
            0,
            amount,
            amount,
            None,
            sequence,
        )

    state = State(
        as_of=None,
        status="open",
        principal_slices=(
            PrincipalSlice(date(2026, 6, 1), 10_000, 10_000, 1),
            PrincipalSlice(date(2026, 7, 1), 10_000, 10_000, 2),
        ),
        charges=(
            charge(1, "service", date(2026, 3, 1), 100),
            charge(2, "collection", date(2026, 3, 15), 100),
            charge(3, "initiation", date(2026, 3, 1), 100),
            charge(4, "default_admin", date(2026, 3, 20), 100),
            charge(5, "insurance", date(2026, 3, 10), 100),
        ),
        unbilled_ordinary=Decimal(0),
        unbilled_duplum=Decimal(0),
        unbilled_duplum_episode=None,
        duplum_interest_counted_cents=0,
        episodes=(),
        in_default=False,
        next_sequence=6,
        next_episode_no=1,
        prior_duplum_accrued_cents=0,
        service_months_levied=(),
        initiation_levied=True,
        suspense_cents=0,
        clips=(),
        waived_cents=0,
        settled_on=None,
    )
    first = allocate_payment(state, 100, as_of=date(2026, 3, 31))
    assert first.fee_cents == 100
    assert charge_remaining(first.state, "collection") == 0
    assert charge_remaining(first.state, "service") == 100
    second = allocate_payment(state, 250, as_of=date(2026, 3, 31))
    assert charge_remaining(second.state, "collection") == 0
    assert charge_remaining(second.state, "default_admin") == 0
    assert charge_remaining(second.state, "insurance") == 50
    assert charge_remaining(second.state, "service") == 100
    assert charge_remaining(second.state, "initiation") == 100
    with pytest.raises(RuleError) as unset:
        allocate_payment(state, 600, as_of=date(2026, 3, 31))
    assert unset.value.code == "prepayment-choice-unset"

    earliest = allocate_payment(
        state, 600, as_of=date(2026, 3, 31), prepayment=PrepaymentChoice.DROP_INSTALMENT
    ).state
    latest = allocate_payment(
        state, 600, as_of=date(2026, 3, 31), prepayment=PrepaymentChoice.SHORTEN_TERM
    ).state
    assert [(slice_.due_on, slice_.remaining_cents) for slice_ in earliest.principal_slices] == [
        (date(2026, 6, 1), 9_900),
        (date(2026, 7, 1), 10_000),
    ]
    assert [(slice_.due_on, slice_.remaining_cents) for slice_ in latest.principal_slices] == [
        (date(2026, 6, 1), 10_000),
        (date(2026, 7, 1), 9_900),
    ]


def test_zero_rate_and_zero_fee_do_not_raise():
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 3, 1),
        maturity_date=date(2026, 9, 1),
        agreed_monthly_rate=Decimal("0"),
        campaign_initiation_discount_cents=15_000,
    )
    exact = interest_for_dates(
        base_cents=100_000,
        agreement=agreement,
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
    )
    assert exact == 0
    state = run(
        agreement,
        until=date(2026, 3, 31),
        policy=Policy(service_fee_monthly_cents=0, **STATED),
        vat_rates=VAT_15,
    ).state
    assert charge_remaining(state, "interest") == 0
    assert charge_remaining(state, "service") == 0
    assert state.status == "open"
