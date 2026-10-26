"""Worked examples for the readings the engine actually charges."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from lms_config.allocation import PayableFee, allocate_payment
from lms_config.calendar import add_business_days, business_date, easter_sunday, public_holidays
from lms_config.context import AgreementPin, resolve_charge
from lms_config.duplum import CUMULATIVE, FLOATING, apply_s126_payment, open_default, post_month, run_until_capped
from lms_config.exceptions import CalculationInputError
from lms_config.fees import (
    inception_service_fee_cents,
    initiation_fee_cents,
    layby_penalty_cents,
    split_vat_inclusive,
    vat_on_top_cents,
)
from lms_config.interest import (
    RateCap,
    daily_interest_cents,
    month_divisor,
    post_interest_cents,
    year_divisor,
)
from lms_config.settlement import (
    agreement_size,
    early_termination_ceiling_cents,
    settlement_cents,
)
from lms_config.statute import (
    DAY_COUNT_30,
    DAY_COUNT_365,
    DAY_COUNT_ACTUAL_MONTH,
    REPO_ANNUAL,
    SHORT_TERM_FIRST_MONTHLY,
    SHORT_TERM_SUBSEQUENT_MONTHLY,
    UNSECURED_REPO_MARGIN,
)
from lms_config.templates import (
    bnpl_zero,
    layby_goods,
    layby_security_short_term,
    micro_short_term,
    unsecured_personal,
)
from lms_config.validate import (
    FeeTerms,
    InstrumentTerms,
    capitalized_short_term_fits,
    validate_terms,
)
from uuid import UUID


ZERO = UUID(int=0)


def test_upfront_initiation_on_r1000_is_the_15_percent_test():
    # Table B is R165. Regulation 43(3) is 15% of R1 000 = R150.
    # Paid upfront, the amount deferred is R1 000. Both limbs use that
    # amount. There is no circularity.
    assert initiation_fee_cents(100_000, base="cash_advanced") == 15_000


def test_deferred_initiation_gross_up_is_higher_and_not_charged():
    # R1 000 cash, fee inside the deferred amount. The fixed point of the
    # 15% test is R176.47. Day-1 charges the cash-base figure, R150.
    assert initiation_fee_cents(100_000, base="grossed_principal") == 17_647
    assert initiation_fee_cents(100_000, base="cash_advanced") == 15_000

    # R2 000. Table B on the cash is R265. Grossed fixed point is R294.44.
    assert initiation_fee_cents(200_000, base="cash_advanced") == 26_500
    assert initiation_fee_cents(200_000, base="grossed_principal") == 29_444

    # R8 000. Table B on the cash is R865, under the R1 050 absolute cap.
    assert initiation_fee_cents(800_000, base="cash_advanced") == 86_500
    assert initiation_fee_cents(800_000, base="grossed_principal") == 96_111


def test_safe_initiation_never_exceeds_the_grossed_reading():
    for cash in (0, 50_000, 100_000, 120_000, 130_000, 200_000, 721_364, 800_000, 2_000_000):
        assert initiation_fee_cents(cash, base="cash_advanced") <= initiation_fee_cents(
            cash, base="grossed_principal"
        )


def test_maximum_cash_that_stays_a_short_term_loan_once_the_fee_is_deferred():
    assert capitalized_short_term_fits(721_364)
    assert not capitalized_short_term_fits(721_365)
    fee = initiation_fee_cents(721_364, base="cash_advanced")
    assert fee == 78_636
    assert 721_364 + fee == 800_000


def test_vat_exclusive_reading_charges_more_than_the_gazetted_rand_amount():
    # R265 initiation. Adding 15% VAT on top charges R304.75.
    assert vat_on_top_cents(26_500) == 30_475
    assert vat_on_top_cents(26_500) - 26_500 == 3_975
    exclusive, vat = split_vat_inclusive(26_500)
    assert exclusive + vat == 26_500
    assert (exclusive, vat) == (23_043, 3_457)

    # Maximum capitalized short-term fee under the adopted reading.
    assert vat_on_top_cents(78_636) - 78_636 == 11_795


def test_inception_service_fee_counts_the_conclusion_day_and_does_not_exceed_r60():
    # 20 March 2026 is day 20 of a 31-day month. Inclusive cover is 12 days.
    # 6000 × 12 / 31 = 2322.58 cents, floored to R23.22.
    inclusive = inception_service_fee_cents(6_000, date(2026, 3, 20), include_conclusion_day=True)
    exclusive = inception_service_fee_cents(6_000, date(2026, 3, 20), include_conclusion_day=False)
    assert inclusive == 2_322
    assert exclusive == 2_129
    assert inclusive - exclusive == 193
    # Concluding on the 1st is the whole month, still not above the cap.
    assert inception_service_fee_cents(6_000, date(2026, 3, 1), include_conclusion_day=True) == 6_000


def test_service_fee_above_the_cap_is_refused():
    with pytest.raises(CalculationInputError):
        inception_service_fee_cents(6_001, date(2026, 3, 1), include_conclusion_day=True)


def test_section_126_waterfall_reduces_principal_with_what_is_left():
    result = allocate_payment(
        50_000,
        payable_interest_cents=8_000,
        fees=[
            PayableFee("service", date(2026, 3, 1), 6_000),
            PayableFee("default_admin", date(2026, 3, 15), 4_000),
        ],
        principal_cents=100_000,
    )
    assert result.interest_cents == 8_000
    assert [(item.code, item.amount_cents) for item in result.fees] == [
        ("service", 6_000),
        ("default_admin", 4_000),
    ]
    assert result.principal_cents == 32_000
    assert result.unapplied_cents == 0


def test_same_day_fees_share_a_short_payment_pro_rata():
    result = allocate_payment(
        4_500,
        payable_interest_cents=0,
        fees=[
            PayableFee("service", date(2026, 3, 1), 6_000),
            PayableFee("insurance", date(2026, 3, 1), 3_000),
        ],
        principal_cents=100_000,
    )
    assert [(item.code, item.amount_cents) for item in result.fees] == [
        ("service", 3_000),
        ("insurance", 1_500),
    ]
    assert result.principal_cents == 0


def test_short_term_actual_days_cancel_and_thirty_day_does_not():
    deferred = 100_000  # R1 000
    actual = daily_interest_cents(
        deferred,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 3, 1), DAY_COUNT_ACTUAL_MONTH),
    ) * 31
    thirty = daily_interest_cents(
        deferred,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 3, 1), DAY_COUNT_30),
    ) * 31
    assert post_interest_cents(actual) == 5_000
    assert post_interest_cents(thirty) == 5_167
    # R1.67 in one month, about 3.3% of that month's interest, which is
    # more than the 0.1% annual tolerance. The agreement has to pick one.
    assert post_interest_cents(thirty) - post_interest_cents(actual) == 167


def test_unsecured_cap_on_the_september_2026_repo_rate():
    cap = RateCap("unsecured", annual_margin_over_repo=UNSECURED_REPO_MARGIN)
    pin = AgreementPin(
        agreement_id=ZERO,
        organisation_id=ZERO,
        enigma_person_id=ZERO,
        terms_version_id=ZERO,
        classification="unsecured",
        contractual_monthly_rate=None,
        contractual_annual_rate=None,
        contractual_repo_margin=UNSECURED_REPO_MARGIN,
        day_count=DAY_COUNT_365,
        originated_on=date(2026, 10, 1),
        short_term_ordinal=None,
        ncr_registration_number="NCRCP0",
    )
    resolved = resolve_charge(pin, cap, REPO_ANNUAL, date(2026, 10, 26))
    assert resolved.statutory == Decimal("0.2825")
    assert resolved.rate == Decimal("0.2825")
    assert resolved.cap_reduced is False
    month = daily_interest_cents(
        1_000_000,
        periodic_rate=resolved.rate,
        divisor_days=year_divisor(date(2026, 3, 1), DAY_COUNT_365),
    ) * 31
    assert post_interest_cents(month) == 23_993


def test_fixed_rate_above_a_later_cap_is_reduced():
    cap = RateCap("unsecured", annual_margin_over_repo=UNSECURED_REPO_MARGIN)
    pin = AgreementPin(
        agreement_id=ZERO,
        organisation_id=ZERO,
        enigma_person_id=ZERO,
        terms_version_id=ZERO,
        classification="unsecured",
        contractual_monthly_rate=None,
        contractual_annual_rate=Decimal("0.29"),
        contractual_repo_margin=None,
        day_count=DAY_COUNT_365,
        originated_on=date(2026, 5, 1),
        short_term_ordinal=None,
        ncr_registration_number="NCRCP0",
    )
    resolved = resolve_charge(pin, cap, REPO_ANNUAL, date(2026, 10, 26))
    assert resolved.agreed == Decimal("0.29")
    assert resolved.rate == Decimal("0.2825")
    assert resolved.cap_reduced is True


def test_second_short_term_loan_is_capped_at_3_percent():
    cap = RateCap(
        "short_term",
        monthly_rate=SHORT_TERM_FIRST_MONTHLY,
        subsequent_monthly_rate=SHORT_TERM_SUBSEQUENT_MONTHLY,
    )
    def pin(ordinal: int) -> AgreementPin:
        return AgreementPin(
            agreement_id=ZERO,
            organisation_id=ZERO,
            enigma_person_id=ZERO,
            terms_version_id=ZERO,
            classification="short_term",
            contractual_monthly_rate=SHORT_TERM_FIRST_MONTHLY,
            contractual_annual_rate=None,
            contractual_repo_margin=None,
            day_count=DAY_COUNT_ACTUAL_MONTH,
            originated_on=date(2026, 6, 1),
            short_term_ordinal=ordinal,
            ncr_registration_number="NCRCP0",
        )

    first = resolve_charge(pin(1), cap, None, date(2026, 6, 1))
    second = resolve_charge(pin(2), cap, None, date(2027, 1, 8))
    assert first.rate == Decimal("0.05")
    assert second.rate == Decimal("0.03")
    # One month on R1 000: R50 versus R30.
    assert post_interest_cents(Decimal(100_000) * first.rate) == 5_000
    assert post_interest_cents(Decimal(100_000) * second.rate) == 3_000


def test_in_duplum_payment_does_not_reopen_the_cumulative_cap():
    cumulative, _months = run_until_capped(
        100_000,
        monthly_rate=SHORT_TERM_FIRST_MONTHLY,
        service_fee_cents=6_000,
        mode=CUMULATIVE,
        payment_after_month=2,
        payment_cents=20_000,
    )
    floating, _floating_months = run_until_capped(
        100_000,
        monthly_rate=SHORT_TERM_FIRST_MONTHLY,
        service_fee_cents=6_000,
        mode=FLOATING,
        payment_after_month=2,
        payment_cents=20_000,
    )
    assert cumulative.accrued_cents == 100_000
    assert floating.accrued_cents == 120_000
    assert floating.accrued_cents - cumulative.accrued_cents == 20_000


def test_in_duplum_month_trace_before_any_payment():
    ledger = open_default(100_000)
    first = post_month(ledger, monthly_rate=Decimal("0.05"), service_fee_cents=6_000)
    assert (first.interest_charged_cents, first.fee_charged_cents) == (5_000, 6_000)
    second = post_month(first.ledger, monthly_rate=Decimal("0.05"), service_fee_cents=6_000)
    assert (second.interest_charged_cents, second.fee_charged_cents) == (5_550, 6_000)
    after_payment = apply_s126_payment(second.ledger, 20_000)
    assert after_payment.interest_cents == 0
    assert after_payment.fee_cents == 2_550
    assert after_payment.principal_cents == 100_000
    assert after_payment.accrued_cents == 22_550
    assert after_payment.deferred_cents == 102_550


def test_small_agreement_settlement_has_no_early_termination_charge():
    assert agreement_size(800_000) == "small"
    assert agreement_size(1_500_000) == "small"
    assert agreement_size(1_500_001) == "intermediate"
    assert agreement_size(24_999_999) == "intermediate"
    assert agreement_size(25_000_000) == "large"
    assert settlement_cents(
        unpaid_principal_cents=80_000,
        unpaid_interest_cents=2_500,
        unpaid_fees_cents=6_000,
        size="small",
    ) == 88_500
    with pytest.raises(CalculationInputError):
        settlement_cents(
            unpaid_principal_cents=80_000,
            unpaid_interest_cents=0,
            unpaid_fees_cents=0,
            early_termination_cents=1,
            size="small",
        )


def test_large_agreement_early_termination_ceiling_and_refusal_below_it():
    # Illustrative only. Day-1 templates never board a large agreement.
    # R250 000 at 28% on a 365-day count, no notice, constant balance,
    # from 15 Oct 2026 to 15 Jan 2027 = 92 days.
    ceiling = early_termination_ceiling_cents(
        unpaid_principal_cents=25_000_000,
        annual_rate=Decimal("0.28"),
        settlement_on=date(2026, 10, 15),
        notice_months=0,
        year_divisor=365,
        size="large",
    )
    assert (date(2027, 1, 15) - date(2026, 10, 15)).days == 92
    assert ceiling == 1_764_383
    noticed = early_termination_ceiling_cents(
        unpaid_principal_cents=25_000_000,
        annual_rate=Decimal("0.28"),
        settlement_on=date(2026, 10, 15),
        notice_months=3,
        year_divisor=365,
        size="large",
    )
    assert noticed == 0
    with pytest.raises(CalculationInputError):
        early_termination_ceiling_cents(
            unpaid_principal_cents=800_000,
            annual_rate=Decimal("0.05"),
            settlement_on=date(2026, 10, 15),
            notice_months=0,
            year_divisor=365,
            size="small",
        )


def test_layby_penalty_is_one_percent_and_sometimes_nil():
    assert layby_penalty_cents(200_000, disclosed_before_agreement=True, death_or_hospitalisation=False) == 2_000
    assert layby_penalty_cents(200_000, disclosed_before_agreement=False, death_or_hospitalisation=False) == 0
    assert layby_penalty_cents(200_000, disclosed_before_agreement=True, death_or_hospitalisation=True) == 0


def test_business_days_skip_weekends_and_the_sunday_rule():
    holidays = frozenset(day for day, _name, _source in public_holidays(2026))
    # Friday 2 October 2026 plus five business days lands on Friday 9 October.
    assert add_business_days(date(2026, 10, 2), 5, holidays) == date(2026, 10, 9)
    # Friday 7 August 2026. Sunday 9 August is Women's Day, Monday 10 August
    # is the observed day. The next business day is Tuesday 11 August.
    assert add_business_days(date(2026, 8, 7), 1, holidays) == date(2026, 8, 11)
    assert easter_sunday(2026) == date(2026, 4, 5)
    # 21 March 2026 is a Saturday and is not moved. 9 August is a Sunday
    # and the Monday is added.
    named = {day: source for day, _name, source in public_holidays(2026)}
    assert date(2026, 3, 21) in named
    assert date(2026, 3, 22) not in named
    assert named[date(2026, 8, 10)] == "sunday_rule"


def test_johannesburg_business_date_crosses_midnight_ahead_of_utc():
    instant = datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc)
    assert business_date(instant) == date(2026, 11, 1)


def test_day1_templates_publish():
    for factory in (
        micro_short_term,
        unsecured_personal,
        bnpl_zero,
        layby_goods,
        layby_security_short_term,
    ):
        validate_terms(factory())


def test_zero_cost_rejects_a_late_fee():
    dirty = bnpl_zero()
    plan = dirty.instruments[0]
    charged = type(dirty)(
        classification=dirty.classification,
        instruments=(
            InstrumentTerms(
                code=plan.code,
                kind=plan.kind,
                monthly_rate=plan.monthly_rate,
                annual_rate=plan.annual_rate,
                fees=(FeeTerms("service", amount_cents=2_000, charge="fixed"),),
            ),
        ),
    )
    with pytest.raises(CalculationInputError):
        validate_terms(charged)


def test_missing_repo_rate_fails_closed():
    cap = RateCap("unsecured", annual_margin_over_repo=UNSECURED_REPO_MARGIN)
    pin = AgreementPin(
        agreement_id=ZERO,
        organisation_id=ZERO,
        enigma_person_id=ZERO,
        terms_version_id=ZERO,
        classification="unsecured",
        contractual_monthly_rate=None,
        contractual_annual_rate=Decimal("0.20"),
        contractual_repo_margin=None,
        day_count=DAY_COUNT_365,
        originated_on=date(2026, 10, 1),
        short_term_ordinal=None,
        ncr_registration_number="NCRCP0",
    )
    with pytest.raises(CalculationInputError):
        resolve_charge(pin, cap, None, date(2026, 10, 26))
