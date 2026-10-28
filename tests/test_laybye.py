"""Pins for the Laybye layer. Amounts come from the ledger and the engine."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lms.calc.interest import daily_interest_rands
from lms.laybye import (
    CREDIT_IMPROVEMENT_LOAN_CHILD,
    LaybyeError,
    Section124Authority,
    accrue_parent,
    allocate_receipt,
    apply_credit_life_proceeds,
    apply_on_death,
    day1_treatment,
    grant_loan,
    laybye_name,
    levy_parent_service_fee,
    prepare_pair,
    raise_collections,
    receive_pre_disbursement,
    store_funeral_beneficiary,
    top_up,
)
from lms.ledger.errors import LedgerError
from lms.ledger.service import Ledger
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")


def at(year: int, month: int, day: int, hour: int = 8, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=JOHANNESBURG)


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


def pair(ledger: Ledger, *, cash: int = 100_000, due: date = date(2026, 12, 15)):
    return prepare_pair(
        ledger,
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=at(2026, 3, 1),
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((due, cash),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
        quoted_disbursement=date(2026, 4, 1),
    )


def test_pre_disbursement_receipt_lands_in_the_laybye_as_cash_in():
    ledger = Ledger()
    parent, child = pair(ledger)
    assert parent.disbursement_value_date is None
    assert ledger.bucket_balance(parent, "principal") == 0

    receipt = receive_pre_disbursement(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=40_000,
        recognised_at=at(2026, 3, 10, 11),
    )

    assert receipt.value_date == date(2026, 3, 10)
    assert receipt.kind == "laybye_deposit"
    assert [(entry.account_code, entry.bucket, entry.debit_cents, entry.credit_cents) for entry in receipt.entries] == [
        ("cash", None, 40_000, 0),
        ("laybye_hold", "laybye_hold", 0, 40_000),
    ]
    assert ledger.bucket_balance(child, "laybye_hold") == 40_000
    assert ledger.bucket_balance(parent, "principal") == 0
    assert ledger.store.transactions_for("org-a", parent.loan_id) == ()

    bare = Ledger()
    lone = bare.prepare(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=at(2026, 3, 1),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 12, 15), 100_000),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )
    with pytest.raises(LaybyeError) as missing:
        receive_pre_disbursement(
            bare,
            organisation_id="org-a",
            parent_loan_id=lone.loan_id,
            cents=1_000,
            recognised_at=at(2026, 3, 11),
        )
    assert missing.value.code == "laybye-missing"
    assert bare.bucket_balance(lone, "principal") == 0


def test_payments_go_to_the_loan_first_and_excess_to_the_laybye():
    ledger = Ledger()
    due = date(2026, 6, 15)
    parent, child = pair(ledger, due=due)
    receive_pre_disbursement(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=10_000,
        recognised_at=at(2026, 3, 20),
    )
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((due, 100_000),),
    )
    ledger.levy_charge(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        bucket="interest",
        cents=2_500,
        due_on=date(2026, 4, 2),
        recognised_at=at(2026, 4, 2, 8),
        interest_cap_present=True,
    )

    allocation = allocate_receipt(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=4_000,
        recognised_at=at(2026, 4, 2, 9),
        attributed_due_on=date(2026, 4, 2),
    )

    assert allocation.loan_cents == 2_500
    assert allocation.laybye_cents == 1_500
    assert ledger.bucket_balance(parent, "interest") == 0
    assert ledger.bucket_balance(parent, "principal") == 100_000
    assert parent.slices[0].remaining_cents == 100_000
    assert ledger.bucket_balance(child, "laybye_hold") == 11_500


def test_due_principal_is_paid_before_the_laybye():
    ledger = Ledger()
    due = date(2026, 4, 2)
    parent, child = pair(ledger, cash=10_000, due=due)
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((due, 10_000),),
    )
    allocation = allocate_receipt(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=10_400,
        recognised_at=at(2026, 4, 2, 9),
        attributed_due_on=due,
    )
    assert allocation.loan_cents == 10_000
    assert allocation.laybye_cents == 400
    assert ledger.bucket_balance(parent, "principal") == 0
    assert ledger.bucket_balance(child, "laybye_hold") == 400


def test_net_balance_interest_and_gross_principal():
    ledger = Ledger()
    parent, _child = pair(ledger, cash=100_000)
    receive_pre_disbursement(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=40_000,
        recognised_at=at(2026, 3, 15),
    )
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((date(2026, 12, 15), 100_000),),
    )
    accrual = accrue_parent(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 2),
        interest_cap_present=True,
    )
    assert accrual.principal_cents == 100_000
    assert accrual.hold_cents == 40_000
    assert accrual.base_cents == max(0, accrual.principal_cents - accrual.hold_cents)
    assert accrual.base_cents == 60_000
    assert accrual.day_rands == daily_interest_rands(60_000, Decimal("0.05"), 30, weight=1)
    assert ledger.bucket_balance(parent, "principal") == 100_000

    flagged = ledger.flag_default(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        check_on=date(2026, 4, 2),
        due_on=date(2026, 4, 2),
        instalment_cents=10_000,
        recognised_at=at(2026, 4, 2, 10),
    )
    assert flagged is True
    assert parent.episodes[0].ceiling_cents == 100_000


def test_one_service_fee_on_the_parent():
    ledger = Ledger()
    due = date(2026, 4, 20)
    parent, child = pair(ledger, due=due)
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((due, 100_000),),
    )
    levy_parent_service_fee(
        ledger,
        organisation_id="org-a",
        loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1, 9),
        monthly_cents=2_000,
        due_on=due,
        interest_cap_present=True,
        vat_rate=Decimal(0),
        vat_registered=False,
        opening=True,
        first_due=due,
    )
    assert ledger.bucket_balance(parent, "service") > 0
    assert ledger.bucket_balance(child, "service") == 0
    with pytest.raises(LedgerError) as second:
        levy_parent_service_fee(
            ledger,
            organisation_id="org-a",
            loan_id=parent.loan_id,
            recognised_at=at(2026, 4, 2),
            monthly_cents=2_000,
            due_on=due,
            interest_cap_present=True,
            vat_rate=Decimal(0),
            vat_registered=False,
        )
    assert second.value.code == "service-fee-once"
    with pytest.raises(LedgerError) as child_fee:
        levy_parent_service_fee(
            ledger,
            organisation_id="org-a",
            loan_id=child.loan_id,
            recognised_at=at(2026, 5, 1),
            monthly_cents=2_000,
            due_on=due,
            interest_cap_present=True,
            vat_rate=Decimal(0),
            vat_registered=False,
        )
    assert child_fee.value.code == "service-fee-parent"


def test_credit_life_proceeds_pay_the_loan_and_do_not_fund_the_laybye():
    ledger = Ledger()
    parent, child = pair(ledger, due=date(2026, 6, 15))
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((date(2026, 6, 15), 100_000),),
    )
    receive = 5_000
    # The hold is already zero. Seed it with an ordinary excess so a mistaken
    # allocation into the Laybye would be visible.
    ledger.credit_laybye(
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=receive,
        recognised_at=at(2026, 4, 1, 10),
    )
    ledger.levy_charge(
        organisation_id="org-a",
        loan_id=parent.loan_id,
        bucket="interest",
        cents=2_500,
        due_on=date(2026, 4, 2),
        recognised_at=at(2026, 4, 2, 8),
        interest_cap_present=True,
    )
    proceeds = apply_credit_life_proceeds(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=4_000,
        recognised_at=at(2026, 4, 2, 9),
        attributed_due_on=date(2026, 4, 2),
    )
    assert proceeds.loan_cents == 2_500
    assert proceeds.unposted_cents == 1_500
    assert ledger.bucket_balance(parent, "interest") == 0
    assert ledger.bucket_balance(parent, "principal") == 100_000
    assert ledger.bucket_balance(child, "laybye_hold") == receive


def test_automated_credit_life_collection_is_separate_and_not_an_account():
    ledger = Ledger()
    before = len(ledger.store.transactions_for("org-a"))
    instructions = raise_collections(
        automated=True,
        loan_instalment_cents=10_000,
        credit_life_premium_cents=1_500,
    )
    assert [item.purpose for item in instructions] == ["loan_instalment", "credit_life_premium"]
    assert [item.cents for item in instructions] == [10_000, 1_500]
    assert instructions[0] != instructions[1]
    assert len(ledger.store.transactions_for("org-a")) == before

    zero = raise_collections(
        automated=True,
        loan_instalment_cents=10_000,
        credit_life_premium_cents=0,
    )
    assert zero[1].cents == 0
    assert raise_collections(automated=False, loan_instalment_cents=10_000, credit_life_premium_cents=None) == ()
    with pytest.raises(LaybyeError) as unknown:
        raise_collections(automated=True, loan_instalment_cents=10_000, credit_life_premium_cents=None)
    assert unknown.value.code == "premium-unknown"
    with pytest.raises(LaybyeError) as beneficiary:
        store_funeral_beneficiary("Executor")
    assert beneficiary.value.code == "beneficiary-not-in-lms"


def test_death_application_fails_closed_without_section_124_authority():
    ledger = Ledger()
    parent, child = pair(ledger)
    receive_pre_disbursement(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=25_000,
        recognised_at=at(2026, 3, 12),
    )
    grant_loan(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        recognised_at=at(2026, 4, 1),
        schedule=((date(2026, 12, 15), 100_000),),
    )
    hold = ledger.bucket_balance(child, "laybye_hold")
    principal = ledger.bucket_balance(parent, "principal")

    with pytest.raises(LaybyeError) as missing:
        apply_on_death(
            ledger,
            organisation_id="org-a",
            parent_loan_id=parent.loan_id,
            recognised_at=at(2026, 5, 1),
            requested_cents=25_000,
            authority=None,
            attributed_due_on=date(2026, 5, 1),
        )
    assert missing.value.code == "s124-missing"

    with pytest.raises(LaybyeError) as unsigned:
        apply_on_death(
            ledger,
            organisation_id="org-a",
            parent_loan_id=parent.loan_id,
            recognised_at=at(2026, 5, 1),
            requested_cents=25_000,
            authority=Section124Authority(
                mandate_id="s124-1",
                authorised_cents=25_000,
                authorised_from=date(2026, 3, 1),
                authorised_to=None,
                signed_in_life=False,
            ),
            attributed_due_on=date(2026, 5, 1),
        )
    assert unsigned.value.code == "s124-missing"
    assert ledger.bucket_balance(child, "laybye_hold") == hold
    assert ledger.bucket_balance(parent, "principal") == principal


def test_top_up_does_not_change_the_laybye_and_is_not_invented():
    ledger = Ledger()
    parent, child = pair(ledger)
    receive_pre_disbursement(
        ledger,
        organisation_id="org-a",
        parent_loan_id=parent.loan_id,
        cents=5_000,
        recognised_at=at(2026, 3, 8),
    )
    hold = ledger.bucket_balance(child, "laybye_hold")
    with pytest.raises(LaybyeError) as caught:
        top_up(ledger, organisation_id="org-a", parent_loan_id=parent.loan_id)
    assert caught.value.code == "top-up-undefined"
    assert ledger.bucket_balance(child, "laybye_hold") == hold
    assert ledger.bucket_balance(parent, "principal") == 0


def test_day1_name_is_cash_deposit_until_a_mirror_exists():
    assert laybye_name(mirror_product_name=None) == CREDIT_IMPROVEMENT_LOAN_CHILD
    assert laybye_name(mirror_product_name="Provider Funeral Mirror") == "Provider Funeral Mirror"
    assert day1_treatment(mirror_product_name=None) == "cash-deposit"
    with pytest.raises(LaybyeError) as blank:
        laybye_name(mirror_product_name="  ")
    assert blank.value.code == "mirror-name-blank"
    with pytest.raises(LaybyeError) as mirror:
        day1_treatment(mirror_product_name="Provider Funeral Mirror")
    assert mirror.value.code == "mirror-treatment-unset"
