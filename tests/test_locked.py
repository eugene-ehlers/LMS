"""Locked decisions in docs/LOCKED_DECISIONS.md.

The numbers 4, 5, and 95 appear here only as the document's examples.
They are not defaults. A missing setting fails closed.
"""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from lms_config.calendar import value_date, value_instant
from lms_config.context import AgreementPin, require_reference_for_posting, resolve_charge
from lms_config.duplum import open_default
from lms_config.exceptions import CalculationInputError
from lms_config.fees import opening_service_fee_cents, subsequent_service_fee_cents
from lms_config.interest import (
    RateCap,
    daily_interest_cents,
    month_divisor,
    post_interest_cents,
    year_divisor,
)
from lms_config.locked import (
    IN_DUPLUM_CLIP_POSTS,
    OrganisationSettings,
    RecognisedReceipt,
    campaign_rate,
    duplum_base_cents,
    interest_bearing_cents,
    is_in_default,
    is_in_default_at_morning_check,
    order_recognised_events,
    resolve_customer_settings,
)
from lms_config.statute import (
    DAY_COUNT_30_360,
    DAY_COUNT_ACTUAL_ACTUAL,
    DAY_COUNT_ACTUAL_MONTH,
    REPO_ANNUAL,
    SHORT_TERM_FIRST_MONTHLY,
    SHORT_TERM_SUBSEQUENT_MONTHLY,
)
from lms_config.templates import bnpl_zero, micro_short_term
from lms_config.validate import ProductTerms, validate_terms

ZERO = UUID(int=0)


def _org(**overrides) -> OrganisationSettings:
    values = dict(
        leniency_days=4,
        full_payment_threshold_percent=Decimal("95"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        vat_on_rand_maxima="exclusive",
        late_disbursement="adjust_instalment",
        partial_prepayment="shorten_term",
        in_duplum_trigger="collections_default",
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def _resolved(product, **overrides):
    return resolve_customer_settings(_org(**overrides), product)


JOHANNESBURG = ZoneInfo("Africa/Johannesburg")


def test_value_date_is_midnight_on_the_johannesburg_calendar_day():
    early = datetime(2026, 10, 27, 0, 1, tzinfo=JOHANNESBURG)
    late = datetime(2026, 10, 27, 23, 59, tzinfo=JOHANNESBURG)
    assert value_date(early) == value_date(late) == date(2026, 10, 27)
    # 22:30 UTC on 26 October is 00:30 SAST on 27 October.
    assert value_date(datetime(2026, 10, 26, 22, 30, tzinfo=timezone.utc)) == date(2026, 10, 27)
    assert value_instant(date(2026, 10, 27)) == datetime(2026, 10, 27, 0, 0, tzinfo=JOHANNESBURG)


def test_default_uses_one_test_and_leniency_does_not_pause_interest():
    due = date(2026, 10, 1)
    common = dict(
        due_on=due,
        leniency_days=4,
        instalment_cents=10_000,
        threshold_percent=Decimal("95"),
    )
    # Due date plus 4 calendar days is 5 October. The 4th is still inside leniency.
    assert is_in_default(value_date=date(2026, 10, 4), received_cents=0, **common) is False
    assert is_in_default(value_date=date(2026, 10, 5), received_cents=0, **common) is True
    # 95% of R100 is R95. Exactly that is full. One cent under is not.
    assert is_in_default(value_date=date(2026, 10, 5), received_cents=9_500, **common) is False
    assert is_in_default(value_date=date(2026, 10, 5), received_cents=9_499, **common) is True
    # Zero leniency flags on the due date, after that day's receipts.
    assert is_in_default(
        due_on=due,
        value_date=due,
        leniency_days=0,
        received_cents=10_000,
        instalment_cents=10_000,
        threshold_percent=Decimal("100"),
    ) is False
    # Interest for a leniency day is the ordinary daily amount on the outstanding balance.
    outstanding = daily_interest_cents(
        100_000,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 10, 4), DAY_COUNT_ACTUAL_MONTH),
    )
    paused = daily_interest_cents(
        0,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 10, 4), DAY_COUNT_ACTUAL_MONTH),
    )
    assert outstanding > paused
    assert is_in_default(value_date=date(2026, 10, 4), received_cents=0, **common) is False


def test_leniency_and_threshold_are_not_invented():
    product = micro_short_term()
    with pytest.raises(CalculationInputError, match="leniency_days"):
        resolve_customer_settings(
            OrganisationSettings(
                leniency_days=None,
                full_payment_threshold_percent=Decimal("95"),
                in_duplum_trigger="collections_default",
            ),
            product,
        )
    with pytest.raises(CalculationInputError, match="full_payment_threshold"):
        resolve_customer_settings(
            OrganisationSettings(
                leniency_days=4,
                full_payment_threshold_percent=None,
                in_duplum_trigger="collections_default",
            ),
            product,
        )
    chosen = _resolved(product)
    assert chosen.leniency_days == 4
    assert chosen.full_payment_threshold_percent == Decimal("95")
    # Decision 10 names none. Decision 19 says an unset election fails closed,
    # so the word none has to be stored. It is not filled in from nothing.
    assert chosen.interest_on_deferred_initiation == "none"
    overridden = resolve_customer_settings(
        _org(),
        replace(product, leniency_days=5, full_payment_threshold_percent=Decimal("100")),
    )
    assert overridden.leniency_days == 5
    assert overridden.full_payment_threshold_percent == Decimal("100")


def test_campaign_discount_falls_away_on_default_and_zero_rate_still_calculates():
    assert campaign_rate(Decimal("0.05"), Decimal("0.02"), in_default=False) == Decimal("0.03")
    assert campaign_rate(Decimal("0.05"), Decimal("0.02"), in_default=True) == Decimal("0.05")
    assert campaign_rate(Decimal("0.05"), Decimal("0.05"), in_default=False) == Decimal("0")
    # A cure does not bring the discount back.
    assert campaign_rate(
        Decimal("0.05"), Decimal("0.02"), in_default=False, discount_fallen_away=True
    ) == Decimal("0.05")
    with pytest.raises(CalculationInputError):
        campaign_rate(Decimal("0.05"), Decimal("0.06"), in_default=False)

    loan = micro_short_term().instruments[0]
    campaign = ProductTerms(
        classification="short_term",
        max_principal_cents=micro_short_term().max_principal_cents,
        instruments=(
            replace(
                loan,
                monthly_rate=Decimal("0"),
                base_rate=Decimal("0.05"),
                discount_rate=Decimal("0.05"),
            ),
        ),
    )
    validate_terms(campaign)
    hidden = ProductTerms(
        classification="short_term",
        max_principal_cents=campaign.max_principal_cents,
        instruments=(replace(loan, monthly_rate=Decimal("0.04"), base_rate=Decimal("0.06"), discount_rate=Decimal("0.02")),),
    )
    with pytest.raises(CalculationInputError, match="base rate"):
        validate_terms(hidden)

    cap = RateCap(
        "short_term",
        monthly_rate=SHORT_TERM_FIRST_MONTHLY,
        subsequent_monthly_rate=SHORT_TERM_SUBSEQUENT_MONTHLY,
    )
    pin = AgreementPin(
        agreement_id=ZERO,
        organisation_id=ZERO,
        enigma_person_id=ZERO,
        terms_version_id=ZERO,
        classification="short_term",
        contractual_monthly_rate=Decimal("0.03"),
        contractual_annual_rate=None,
        contractual_repo_margin=None,
        day_count=DAY_COUNT_ACTUAL_ACTUAL,
        originated_on=date(2026, 10, 1),
        short_term_ordinal=1,
        ncr_registration_number="NCRCP0",
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0.02"),
    )
    # 4 October is inside a 4-day leniency, so the campaign still applies,
    # and interest is still calculated on the outstanding balance.
    assert is_in_default(
        due_on=date(2026, 10, 1),
        value_date=date(2026, 10, 4),
        leniency_days=4,
        received_cents=0,
        instalment_cents=10_000,
        threshold_percent=Decimal("95"),
    ) is False
    performing = resolve_charge(pin, cap, None, date(2026, 10, 4), in_default=False)
    defaulted = resolve_charge(pin, cap, None, date(2026, 10, 5), in_default=True)
    assert performing.rate == Decimal("0.03")
    assert defaulted.rate == Decimal("0.05")
    assert defaulted.rate <= pin.base_rate
    day = daily_interest_cents(100_000, periodic_rate=performing.rate, divisor_days=31)
    assert day > 0
    assert day == daily_interest_cents(100_000, periodic_rate=Decimal("0.03"), divisor_days=31)


def test_opening_service_fee_is_pro_rata_and_settlement_month_is_full():
    # 20 March 2026 to 3 April is 14 days. March has 31. 6000 × 14 / 31 = 2709.67 cents.
    assert opening_service_fee_cents(6_000, date(2026, 3, 20), date(2026, 4, 3)) == 2_709
    # A first due date one calendar month later is one full monthly fee, not more.
    assert opening_service_fee_cents(6_000, date(2026, 3, 20), date(2026, 4, 20)) == 6_000
    # Settlement on the 2nd of a later month is still the full contractual fee.
    assert subsequent_service_fee_cents(6_000) == 6_000
    assert subsequent_service_fee_cents(4_000) == 4_000
    with pytest.raises(CalculationInputError):
        subsequent_service_fee_cents(6_001)


def test_actual_actual_and_30_360_are_both_available():
    assert month_divisor(date(2026, 3, 1), DAY_COUNT_ACTUAL_ACTUAL) == 31
    assert year_divisor(date(2026, 3, 1), DAY_COUNT_ACTUAL_ACTUAL) == 365
    assert year_divisor(date(2028, 2, 15), DAY_COUNT_ACTUAL_ACTUAL) == 366
    assert month_divisor(date(2026, 3, 1), DAY_COUNT_30_360) == 30
    assert year_divisor(date(2026, 3, 1), DAY_COUNT_30_360) == 360
    # The same R1.67 gap as regulation 40's 30-day divisor, over March.
    actual = daily_interest_cents(
        100_000,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 3, 1), DAY_COUNT_ACTUAL_ACTUAL),
    ) * 31
    conventional = daily_interest_cents(
        100_000,
        periodic_rate=SHORT_TERM_FIRST_MONTHLY,
        divisor_days=month_divisor(date(2026, 3, 1), DAY_COUNT_30_360),
    ) * 31
    assert post_interest_cents(actual) == 5_000
    assert post_interest_cents(conventional) == 5_167


def test_duplum_base_includes_capitalised_initiation_and_interest_base_may_not():
    # R850 cash plus R150 capitalised initiation. The in-duplum cap is R1 000.
    # Interest, by the decision 10 default, ignores the R150. A R400 lay-by hold
    # comes off the interest base and not off the in-duplum base.
    base = duplum_base_cents(cash_balance_cents=85_000, capitalised_initiation_cents=15_000)
    assert base == 100_000
    ledger = open_default(base)
    assert ledger.cap_cents == 100_000
    assert ledger.cap_cents != 85_000
    assert interest_bearing_cents(
        principal_cents=100_000,
        capitalised_initiation_cents=15_000,
        deposit_hold_cents=40_000,
        charge_interest_on_initiation=False,
    ) == 45_000
    assert interest_bearing_cents(
        principal_cents=100_000,
        capitalised_initiation_cents=15_000,
        deposit_hold_cents=40_000,
        charge_interest_on_initiation=True,
    ) == 60_000
    # The hold cannot drive the interest base negative.
    assert interest_bearing_cents(
        principal_cents=50_000,
        capitalised_initiation_cents=0,
        deposit_hold_cents=80_000,
        charge_interest_on_initiation=False,
    ) == 0


def test_unset_elections_fail_closed_and_the_product_override_wins():
    product = micro_short_term()
    for field in (
        "interest_on_deferred_initiation",
        "repo_rate_fall",
        "vat_on_rand_maxima",
        "late_disbursement",
        "partial_prepayment",
    ):
        with pytest.raises(CalculationInputError, match=field):
            _resolved(product, **{field: None})
    with pytest.raises(CalculationInputError, match="leniency_days"):
        resolve_customer_settings(_org(leniency_days=-1), product)
    with pytest.raises(CalculationInputError, match="threshold"):
        resolve_customer_settings(_org(full_payment_threshold_percent=Decimal("0")), product)
    with pytest.raises(CalculationInputError, match="threshold"):
        resolve_customer_settings(_org(full_payment_threshold_percent=Decimal("100.001")), product)
    inclusive = resolve_customer_settings(
        _org(vat_on_rand_maxima="exclusive"),
        replace(product, vat_on_rand_maxima="inclusive", late_disbursement="keep_instalment"),
    )
    assert inclusive.vat_on_rand_maxima == "inclusive"
    assert inclusive.late_disbursement == "keep_instalment"
    assert inclusive.partial_prepayment == "shorten_term"
    inherited = replace(
        product,
        instruments=(
            replace(
                product.instruments[0],
                monthly_rate=None,
                base_rate=None,
                discount_rate=Decimal(0),
                day_count=None,
            ),
        ),
    )
    from_org = resolve_customer_settings(
        _org(base_rate=Decimal("0.05"), discount_rate=Decimal("0.05"), day_count_code="thirty_360"),
        inherited,
    )
    assert from_org.base_rate == Decimal("0.05")
    assert from_org.discount_rate == Decimal("0.05")
    assert from_org.day_count_code == "thirty_360"
    with pytest.raises(CalculationInputError, match="campaign"):
        resolve_customer_settings(_org(), inherited)


def test_zero_price_does_not_inherit_a_campaign_or_require_a_divisor():
    chosen = resolve_customer_settings(
        _org(base_rate=Decimal("0.05"), discount_rate=Decimal("0.02")),
        bnpl_zero(),
    )
    assert chosen.base_rate == Decimal(0)
    assert chosen.discount_rate == Decimal(0)
    assert chosen.day_count_code is None


def test_flag_date_payment_is_visible_to_the_morning_check():
    due = date(2026, 10, 1)
    flag = date(2026, 10, 5)
    late_on_flag_day = RecognisedReceipt(
        recognised_at=datetime(2026, 10, 5, 23, 59, tzinfo=JOHANNESBURG),
        sequence=2,
        amount_cents=9_500,
        due_on=due,
    )
    next_morning = RecognisedReceipt(
        recognised_at=datetime(2026, 10, 6, 0, 1, tzinfo=JOHANNESBURG),
        sequence=3,
        amount_cents=9_500,
        due_on=due,
    )
    earlier = RecognisedReceipt(
        recognised_at=datetime(2026, 10, 5, 8, 0, tzinfo=JOHANNESBURG),
        sequence=1,
        amount_cents=0,
        due_on=due,
    )
    assert order_recognised_events((late_on_flag_day, earlier)) == (earlier, late_on_flag_day)
    assert is_in_default_at_morning_check(
        due_on=due,
        check_on=flag,
        leniency_days=4,
        receipts=(late_on_flag_day,),
        instalment_cents=10_000,
        threshold_percent=Decimal("95"),
    ) is False
    assert is_in_default_at_morning_check(
        due_on=due,
        check_on=flag,
        leniency_days=4,
        receipts=(next_morning,),
        instalment_cents=10_000,
        threshold_percent=Decimal("95"),
    ) is True


def test_in_duplum_clip_stays_off():
    assert IN_DUPLUM_CLIP_POSTS is False


def test_missing_reference_data_fails_the_posting():
    with pytest.raises(CalculationInputError, match="interest cap"):
        require_reference_for_posting(
            interest_cap_present=False,
            repo_annual=Decimal("0.0725"),
            repo_required=True,
            tariff_cents=None,
            tariff_required=False,
        )
    with pytest.raises(CalculationInputError, match="repo rate"):
        require_reference_for_posting(
            interest_cap_present=True,
            repo_annual=None,
            repo_required=True,
            tariff_cents=None,
            tariff_required=False,
        )
    with pytest.raises(CalculationInputError, match="tariff"):
        require_reference_for_posting(
            interest_cap_present=True,
            repo_annual=None,
            repo_required=False,
            tariff_cents=None,
            tariff_required=True,
        )
    require_reference_for_posting(
        interest_cap_present=True,
        repo_annual=None,
        repo_required=False,
        tariff_cents=None,
        tariff_required=False,
    )


def test_deposit_instrument_is_not_priced_as_a_second_loan():
    from lms_config.templates import layby_security_short_term

    deposit = layby_security_short_term().instruments[1]
    assert deposit.kind == "security_deposit"
    assert all(fee.charge == "zero" and fee.amount_cents == 0 for fee in deposit.fees)
    validate_terms(layby_security_short_term())


def test_variable_campaign_penalty_is_the_base_margin():
    cap = RateCap("unsecured", annual_margin_over_repo=Decimal("0.21"))
    pin = AgreementPin(
        agreement_id=ZERO,
        organisation_id=ZERO,
        enigma_person_id=ZERO,
        terms_version_id=ZERO,
        classification="unsecured",
        contractual_monthly_rate=None,
        contractual_annual_rate=None,
        contractual_repo_margin=Decimal("0.16"),
        day_count=DAY_COUNT_ACTUAL_ACTUAL,
        originated_on=date(2026, 10, 1),
        short_term_ordinal=None,
        ncr_registration_number="NCRCP0",
        base_rate=Decimal("0.21"),
        discount_rate=Decimal("0.05"),
        repo_rate_fall="contract_rate",
    )
    performing = resolve_charge(pin, cap, REPO_ANNUAL, date(2026, 10, 26), in_default=False)
    defaulted = resolve_charge(pin, cap, REPO_ANNUAL, date(2026, 10, 26), in_default=True)
    assert performing.rate == REPO_ANNUAL + Decimal("0.16")
    assert defaulted.rate == REPO_ANNUAL + Decimal("0.21")
    assert defaulted.agreed <= REPO_ANNUAL + pin.base_rate
