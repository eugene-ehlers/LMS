"""Collection campaigns call the ledger and the calculators. They do not reprice the contract."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from lms.calc.fees import apply_ex_vat_discount
from lms.calc.interest import daily_interest_rands
from lms.collection_campaigns.api import dispatch
from lms.collection_campaigns.errors import CollectionCampaignError
from lms.collection_campaigns.models import ROLE
from lms.collection_campaigns.service import CollectionCampaigns, earliest_effective
from lms.collections.service import Collections
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.ledger.service import Ledger
from lms_config.locked import OrganisationSettings
from lms_config.statute import SERVICE_FEE_MONTHLY_CENTS
from lms_config.templates import micro_short_term

JOHANNESBURG_OFFSET = "+02:00"
ROOT = Path(__file__).resolve().parents[1]


def at(year: int, month: int, day: int, hour: int = 8) -> datetime:
    return datetime.fromisoformat(f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00{JOHANNESBURG_OFFSET}")


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


def book(ledger: Ledger, *, person_id: str = "person-a", cash: int = 100_000, when: datetime | None = None):
    when = when or at(2026, 3, 1)
    return ledger.book(
        organisation_id="org-a",
        person_id=person_id,
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=when,
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((date(2026, 12, 15), cash),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )


def service(ledger: Ledger | None = None) -> tuple[CollectionCampaigns, Ledger]:
    ledger = ledger or Ledger()
    return CollectionCampaigns(ledger, EnigmaStub()), ledger


def register(campaigns: CollectionCampaigns, loan, *, product: str = "micro_short_term") -> None:
    campaigns.register_account(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        product_code=product,
        contractual_fees_cents={"service": SERVICE_FEE_MONTHLY_CENTS},
        actor_id="staff-1",
    )


def opened_campaign(campaigns: CollectionCampaigns, **overrides):
    values = dict(
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        start_date=date(2026, 3, 9),
        end_date=date(2026, 3, 20),
        rate_reduction=Decimal("0.02"),
        fee_reductions={"service": 1_000},
        payment_holiday=False,
        notice_date=date(2026, 3, 2),
    )
    values.update(overrides)
    if "rate_scope" not in overrides:
        values["rate_scope"] = "campaign_period" if values["rate_reduction"] > 0 else None
    if "fee_scope" not in overrides:
        values["fee_scope"] = (
            "campaign_period" if any(cents > 0 for cents in values["fee_reductions"].values()) else None
        )
    return campaigns.create(**values)


def test_notice_of_five_business_days_is_enforced_and_not_configurable():
    campaigns, _ledger = service()
    earliest = earliest_effective(date(2026, 3, 2))
    assert earliest == date(2026, 3, 9)
    with pytest.raises(CollectionCampaignError) as caught:
        opened_campaign(campaigns, start_date=date(2026, 3, 8))
    assert caught.value.code == "notice-short"
    assert campaigns.campaigns == {}
    created = opened_campaign(campaigns)
    assert created.notice_business_days == 5
    assert created.notice_date == date(2026, 3, 2)


def test_apply_stores_the_contract_and_does_not_rewrite_it():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    before_lines = tuple(loan.schedule_versions[-1].lines)
    before_end = loan.contractual_end
    before_base = loan.snapshot.base_rate
    before_slices = [(item.due_on, item.amount_cents, item.remaining_cents) for item in loan.slices]
    campaign = opened_campaign(campaigns, payment_holiday=True, end_date=date(2026, 12, 31))
    applications = campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    assert loan.schedule_versions[-1].lines == before_lines
    assert loan.contractual_end == before_end
    assert loan.snapshot.base_rate == before_base
    assert [(item.due_on, item.amount_cents, item.remaining_cents) for item in loan.slices] == before_slices
    stored = applications[0]
    assert stored.contractual_end == before_end
    assert stored.contractual_base_rate == before_base
    assert stored.contractual_instalments == before_lines
    assert stored.contractual_fees_cents["service"] == SERVICE_FEE_MONTHLY_CENTS
    assert stored.skipped_due_dates == (date(2026, 12, 15),)
    assert all(isinstance(cents, int) for cents in stored.contractual_fees_cents.values())
    assert all(isinstance(amount, int) for _due, amount in stored.contractual_instalments)


def test_accrual_uses_the_reduced_rate_only_inside_the_period():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, end_date=date(2026, 3, 10), fee_reductions={})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="organisation",
    )
    reduced = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 9, 11),
        interest_cap_present=True,
    )
    assert reduced.periodic_rate == Decimal("0.03")
    assert reduced.day_rands == daily_interest_rands(100_000, Decimal("0.03"), 31)
    resumed = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 11),
        interest_cap_present=True,
    )
    assert resumed.periodic_rate == Decimal("0.05")
    assert resumed.day_rands == daily_interest_rands(100_000, Decimal("0.05"), 31)


def test_recognition_date_is_johannesburg_midnight():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, end_date=None, fee_reductions={}, rate_reduction=Decimal("0.02"))
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="product",
        product_code="micro_short_term",
    )
    # 22:30 UTC on 8 March is 00:30 on 9 March in Johannesburg.
    inside = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=datetime(2026, 3, 8, 22, 30, tzinfo=timezone.utc),
        interest_cap_present=True,
    )
    assert inside.value_date == date(2026, 3, 9)
    assert inside.periodic_rate == Decimal("0.03")
    outside = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=datetime(2026, 3, 8, 21, 0, tzinfo=timezone.utc),
        interest_cap_present=True,
    )
    assert outside.value_date == date(2026, 3, 8)
    assert outside.periodic_rate == Decimal("0.05")


def test_open_ended_campaign_resumes_only_when_staff_end_it():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, end_date=None, fee_reductions={})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    later = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 4, 2),
        interest_cap_present=True,
    )
    assert later.periodic_rate == Decimal("0.03")
    campaigns.end(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 4, 2, 12),
        end_date=date(2026, 4, 2),
    )
    resumed = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 4, 3),
        interest_cap_present=True,
    )
    assert resumed.periodic_rate == Decimal("0.05")


def test_zero_rate_accrues_zero_and_a_holiday_does_not():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(
        campaigns,
        rate_reduction=Decimal("0.05"),
        fee_reductions={},
        payment_holiday=False,
        end_date=date(2026, 3, 31),
    )
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    zero = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 12),
        interest_cap_present=True,
    )
    assert zero.day_rands == Decimal(0)
    assert zero.periodic_rate == Decimal(0)

    other = book(ledger, person_id="person-b")
    register(campaigns, other)
    holiday = opened_campaign(
        campaigns,
        rate_reduction=Decimal(0),
        fee_reductions={},
        payment_holiday=True,
        end_date=date(2026, 12, 31),
    )
    campaigns.apply(
        holiday.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9, 9),
        selector="loans",
        loan_ids=(other.loan_id,),
    )
    still = campaigns.accrue(
        organisation_id="org-a",
        loan_id=other.loan_id,
        recognised_at=at(2026, 3, 12, 9),
        interest_cap_present=True,
    )
    assert still.day_rands == daily_interest_rands(100_000, Decimal("0.05"), 31)
    assert still.periodic_rate == Decimal("0.05")


def test_payment_holiday_does_not_reset_in_duplum_and_interest_still_counts():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(
        campaigns,
        rate_reduction=Decimal(0),
        fee_reductions={},
        payment_holiday=True,
        end_date=date(2026, 12, 31),
    )
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    episode = ledger.open_in_duplum_episode(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 9, 10),
        fall_away=False,
    )
    ceiling = episode.ceiling_cents
    flagged = campaigns.flag_default(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        check_on=date(2026, 12, 16),
        due_on=date(2026, 12, 15),
        instalment_cents=100_000,
        recognised_at=at(2026, 3, 9, 11),
    )
    assert flagged is False
    assert episode.closed_on is None
    assert episode.ceiling_cents == ceiling
    assert episode.accrued_cents == 0
    campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 10),
        interest_cap_present=True,
    )
    billed = ledger.bill_interest(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 10, 9),
    )
    assert billed is not None
    assert billed.amount_cents > 0
    assert episode.accrued_cents == billed.amount_cents
    assert episode.closed_on is None


def test_fee_reduction_uses_the_calculator_and_the_ledger():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, rate_reduction=Decimal(0), fee_reductions={"service": 1_000})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    ex_vat, _vat, _total = apply_ex_vat_discount(SERVICE_FEE_MONTHLY_CENTS, Decimal("0.15"), 1_000)
    assert ex_vat == 5_000
    assert campaigns.service_fee_for_levy(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 9, 10),
        monthly_cents=SERVICE_FEE_MONTHLY_CENTS,
        vat_rate=Decimal("0.15"),
    ) == ex_vat
    posted = campaigns.levy_service_fee(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 9, 10),
        monthly_cents=SERVICE_FEE_MONTHLY_CENTS,
        due_on=date(2026, 4, 1),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    twin = book(ledger, person_id="person-b")
    direct = ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=twin.loan_id,
        recognised_at=at(2026, 3, 9, 10),
        monthly_cents=ex_vat,
        due_on=date(2026, 4, 1),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    full = book(ledger, person_id="person-c")
    unreduced = ledger.levy_service_fee(
        organisation_id="org-a",
        loan_id=full.loan_id,
        recognised_at=at(2026, 3, 9, 10),
        monthly_cents=SERVICE_FEE_MONTHLY_CENTS,
        due_on=date(2026, 4, 1),
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    assert isinstance(posted.amount_cents, int)
    assert posted.amount_cents == direct.amount_cents
    assert posted.amount_cents < unreduced.amount_cents
    assert campaigns.applications[(campaign.campaign_id, "org-a", loan.loan_id)].contractual_fees_cents[
        "service"
    ] == SERVICE_FEE_MONTHLY_CENTS


def test_overlap_unknown_loan_and_rate_above_contract_store_nothing():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    first = opened_campaign(campaigns, end_date=date(2026, 3, 31), fee_reductions={})
    campaigns.apply(
        first.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    second = opened_campaign(
        campaigns,
        start_date=date(2026, 3, 31),
        end_date=date(2026, 4, 30),
        notice_date=date(2026, 3, 20),
        fee_reductions={},
        recognised_at=at(2026, 3, 20),
    )
    with pytest.raises(CollectionCampaignError) as overlap:
        campaigns.apply(
            second.campaign_id,
            organisation_id="org-a",
            actor_id="staff-1",
            recognised_at=at(2026, 3, 20),
            selector="loans",
            loan_ids=(loan.loan_id,),
        )
    assert overlap.value.code == "campaign-overlap"
    assert len(campaigns.applications) == 1
    with pytest.raises(CollectionCampaignError) as unknown:
        campaigns.apply(
            second.campaign_id,
            organisation_id="org-a",
            actor_id="staff-1",
            recognised_at=at(2026, 3, 20),
            selector="loans",
            loan_ids=(loan.loan_id, "missing-loan"),
        )
    assert unknown.value.code == "loan-unknown"
    assert len(campaigns.applications) == 1
    too_high = opened_campaign(
        campaigns,
        rate_reduction=Decimal("0.06"),
        fee_reductions={},
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 20),
        notice_date=date(2026, 4, 24),
        recognised_at=at(2026, 4, 24),
    )
    with pytest.raises(CollectionCampaignError) as above:
        campaigns.apply(
            too_high.campaign_id,
            organisation_id="org-a",
            actor_id="staff-1",
            recognised_at=at(2026, 5, 4),
            selector="organisation",
        )
    assert above.value.code == "rate-above-contract"
    assert all(item.campaign_id != too_high.campaign_id for item in campaigns.applications.values())


def test_an_increase_is_refused_and_selectors_do_not_combine():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    with pytest.raises(CollectionCampaignError) as rate:
        opened_campaign(campaigns, rate_reduction=Decimal("-0.01"))
    assert rate.value.code == "rate-increase"
    with pytest.raises(CollectionCampaignError) as fee:
        opened_campaign(campaigns, fee_reductions={"service": -1})
    assert fee.value.code == "fee-increase"
    campaign = opened_campaign(campaigns, fee_reductions={})
    with pytest.raises(CollectionCampaignError) as selector:
        campaigns.apply(
            campaign.campaign_id,
            organisation_id="org-a",
            actor_id="staff-1",
            recognised_at=at(2026, 3, 9),
            selector="product",
            product_code="micro_short_term",
            loan_ids=(loan.loan_id,),
        )
    assert selector.value.code == "selector"
    assert campaigns.applications == {}


def test_audit_records_actor_recognition_date_accounts_and_before_after():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, fee_reductions={"service": 1_000})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9, 15),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    extract = campaigns.audit.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 31),
    )
    apply_row = [row for row in extract.rows if row.payload["action"] == "apply"][-1]
    assert apply_row.enigma_person_id == "staff-1"
    assert apply_row.event_type == "COLLECTION_CAMPAIGN_CHANGED"
    assert apply_row.payload["actor_id"] == "staff-1"
    assert apply_row.payload["recognition_date"] == "2026-03-09"
    assert apply_row.payload["loan_ids"] == [loan.loan_id]
    before = apply_row.payload["before"]["loans"][0]
    after = apply_row.payload["after"]["loans"][0]
    assert before["instalments"] == after["instalments"]
    assert before["contractual_end"] == after["contractual_end"]
    assert before["fees_cents"] == after["fees_cents"] == {"service": SERVICE_FEE_MONTHLY_CENTS}
    assert before["periodic_rate"] == "0.05"
    assert after["effective_rate"] == "0.03"
    assert after["fee_reductions_cents"] == {"service": 1000}
    assert after["rate_scope"] == "campaign_period"
    assert after["fee_scope"] == "campaign_period"
    assert isinstance(before["fees_cents"]["service"], int)


def test_suspended_staff_cannot_create():
    ledger = Ledger()
    access = EnigmaStub()
    access.mode = "suspended"
    campaigns = CollectionCampaigns(ledger, access)
    with pytest.raises(CollectionCampaignError) as caught:
        opened_campaign(campaigns)
    assert caught.value.code == "enrolment-suspended"
    assert campaigns.campaigns == {}
    assert campaigns.audit.extract(
        organisation_id="org-a",
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 31),
    ).rows == ()


def test_edit_changes_later_accrual_and_leaves_the_posted_day():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(campaigns, end_date=date(2026, 3, 31), fee_reductions={})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    first = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 9, 11),
        interest_cap_present=True,
    )
    campaigns.edit(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 10),
        start_date=date(2026, 3, 9),
        end_date=date(2026, 3, 31),
        rate_reduction=Decimal("0.01"),
        rate_scope="campaign_period",
        fee_reductions={},
        fee_scope=None,
        payment_holiday=False,
        notice_date=date(2026, 3, 2),
    )
    second = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 10, 11),
        interest_cap_present=True,
    )
    assert first.day_rands == daily_interest_rands(100_000, Decimal("0.03"), 31)
    assert second.periodic_rate == Decimal("0.04")
    assert second.day_rands == daily_interest_rands(100_000, Decimal("0.04"), 31)
    assert loan.contractual_end == date(2026, 12, 15)


def test_collections_does_not_open_or_close_in_duplum_for_a_skipped_instalment():
    access = EnigmaStub()
    servicing = Servicing(enigma=access)
    record = servicing.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(2026, 3, 1),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 60_000), (date(2026, 7, 15), 40_000)),
        idempotency_key="book-1",
    )
    record = servicing.disburse(record.agreement_id, recognised_at=at(2026, 3, 1, 10))
    collections = Collections(servicing)
    collections.bind(record.agreement_id, in_duplum_trigger="collections_default")
    campaigns = CollectionCampaigns(servicing.ledger, access)
    campaigns.bind_collections(collections)
    register(campaigns, type("Loan", (), {"loan_id": record.ledger_loan_id})())
    campaign = opened_campaign(
        campaigns,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        notice_date=date(2026, 5, 22),
        recognised_at=at(2026, 5, 22),
        rate_reduction=Decimal(0),
        fee_reductions={},
        payment_holiday=True,
    )
    assert earliest_effective(date(2026, 5, 22)) <= date(2026, 6, 1)
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 6, 1),
        selector="loans",
        loan_ids=(record.ledger_loan_id,),
    )
    servicing.ledger.open_in_duplum_episode(
        organisation_id="org-a",
        loan_id=record.ledger_loan_id,
        recognised_at=at(2026, 6, 1, 9),
        fall_away=False,
    )
    view = collections.observe(record.agreement_id, recognised_at=at(2026, 6, 16))
    assert view.contractual_breaches == ()
    assert view.open_episode_ceiling is not None
    account = servicing.ledger.store.get("org-a", record.ledger_loan_id)
    episode = next(item for item in account.episodes if item.closed_on is None)
    assert episode.closed_on is None
    assert campaigns.instalment_skipped("org-a", record.ledger_loan_id, date(2026, 6, 15))
    assert not campaigns.instalment_skipped("org-a", record.ledger_loan_id, date(2026, 7, 15))


def test_statement_accrual_uses_the_override_when_the_service_is_wired():
    access = EnigmaStub()
    servicing = Servicing(enigma=access)
    campaigns = CollectionCampaigns(servicing.ledger, access)
    servicing.collection_campaigns = campaigns
    record = servicing.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(2026, 3, 1),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 100_000),),
        idempotency_key="book-2",
    )
    record = servicing.disburse(record.agreement_id, recognised_at=at(2026, 3, 1, 10))
    register(campaigns, type("Loan", (), {"loan_id": record.ledger_loan_id})())
    campaign = opened_campaign(campaigns, fee_reductions={"service": 1_000})
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(record.ledger_loan_id,),
    )
    servicing._accrue_and_bill(
        record,
        date(2026, 3, 9),
        date(2026, 3, 9),
        Decimal("0.15"),
        True,
    )
    accrual = next(
        item
        for item in servicing.ledger.store.transactions_for("org-a", record.ledger_loan_id)
        if item.kind == "interest_accrual" and item.value_date == date(2026, 3, 9)
    )
    assert accrual.memo_rands == daily_interest_rands(100_000, Decimal("0.03"), 31)
    assert record.schedule == ((date(2026, 6, 15), 100_000),)


def test_routes_apply_accrue_and_refuse_a_restructure():
    campaigns, ledger = service()
    loan = book(ledger)
    headers = {"X-Actor-Id": "staff-1"}
    status, registered = dispatch(
        campaigns,
        "POST",
        f"/v1/organisations/org-a/loans/{loan.loan_id}/registration",
        {"product_code": "micro_short_term", "contractual_fees_cents": {"service": 6000}},
        headers,
    )
    assert status == 200
    assert registered["loan_id"] == loan.loan_id
    status, created = dispatch(
        campaigns,
        "POST",
        "/v1/collection-campaigns",
        {
            "organisation_id": "org-a",
            "recognised_at": "2026-03-09T08:00:00+02:00",
            "start_date": "2026-03-09",
            "end_date": "2026-03-20",
            "rate_reduction": "0.02",
            "rate_scope": "campaign_period",
            "fee_reductions": {"service": 1000},
            "fee_scope": "campaign_period",
            "payment_holiday": False,
            "notice_date": "2026-03-02",
        },
        headers,
    )
    assert status == 200
    assert created["notice_business_days"] == 5
    assert created["rate_scope"] == "campaign_period"
    assert created["fee_scope"] == "campaign_period"
    campaign_id = created["campaign_id"]
    status, applied = dispatch(
        campaigns,
        "POST",
        f"/v1/organisations/org-a/collection-campaigns/{campaign_id}/applications",
        {
            "recognised_at": "2026-03-09T09:00:00+02:00",
            "selector": "loans",
            "loan_ids": [loan.loan_id],
        },
        headers,
    )
    assert status == 200
    assert applied["count"] == 1
    status, accrual = dispatch(
        campaigns,
        "POST",
        f"/v1/organisations/org-a/loans/{loan.loan_id}/collection-campaign-accruals",
        {"recognised_at": "2026-03-09T10:00:00+02:00", "interest_cap_present": True},
        headers,
    )
    assert status == 200
    assert accrual["value_date"] == "2026-03-09"
    assert accrual["periodic_rate"] == "0.03"
    assert accrual["base_cents"] == 100_000
    status, refused = dispatch(
        campaigns,
        "POST",
        "/v1/collection-campaigns",
        {
            "organisation_id": "org-a",
            "recognised_at": "2026-03-09T08:00:00+02:00",
            "start_date": "2026-03-09",
            "rate_reduction": "0",
            "payment_holiday": False,
            "notice_date": "2026-03-02",
            "contractual_end": "2027-01-01",
            "instalment_cents": 1,
        },
        headers,
    )
    assert status == 422
    assert refused["code"] == "restructure"
    assert ROLE == "lms.collection_campaign.write"


def test_rest_of_term_keeps_the_rate_and_fee_after_the_campaign_ends():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    campaign = opened_campaign(
        campaigns,
        end_date=date(2026, 3, 10),
        rate_scope="rest_of_term",
        fee_scope="rest_of_term",
    )
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    after_campaign = campaigns.accrue(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 3, 11),
        interest_cap_present=True,
    )
    assert after_campaign.periodic_rate == Decimal("0.03")
    on_term_end = campaigns.periodic_rate_override("org-a", loan.loan_id, at(2026, 12, 15))
    assert on_term_end == Decimal("0.03")
    assert campaigns.periodic_rate_override("org-a", loan.loan_id, at(2026, 12, 16)) is None
    ex_vat, _vat, _total = apply_ex_vat_discount(SERVICE_FEE_MONTHLY_CENTS, Decimal("0.15"), 1_000)
    assert campaigns.service_fee_for_levy(
        organisation_id="org-a",
        loan_id=loan.loan_id,
        recognised_at=at(2026, 4, 1),
        monthly_cents=SERVICE_FEE_MONTHLY_CENTS,
        vat_rate=Decimal("0.15"),
    ) == ex_vat
    assert loan.contractual_end == date(2026, 12, 15)
    assert loan.snapshot.base_rate == Decimal("0.05")


def test_payment_holiday_stops_at_the_campaign_end_while_the_rate_runs_on():
    campaigns, ledger = service()
    loan = ledger.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=at(2026, 3, 1),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 3, 15), 40_000), (date(2026, 6, 15), 60_000)),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )
    register(campaigns, loan)
    campaign = opened_campaign(
        campaigns,
        end_date=date(2026, 3, 20),
        fee_reductions={},
        rate_scope="rest_of_term",
        payment_holiday=True,
    )
    applications = campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    assert applications[0].skipped_due_dates == (date(2026, 3, 15),)
    assert applications[0].contractual_instalments == (
        (date(2026, 3, 15), 40_000),
        (date(2026, 6, 15), 60_000),
    )
    assert campaigns.instalment_skipped("org-a", loan.loan_id, date(2026, 6, 15)) is False
    assert campaigns.periodic_rate_override("org-a", loan.loan_id, at(2026, 6, 1)) == Decimal("0.03")
    assert loan.contractual_end == date(2026, 6, 15)


def test_a_reduction_needs_a_duration_and_a_campaign_needs_a_change():
    campaigns, _ledger = service()
    with pytest.raises(CollectionCampaignError) as missing:
        opened_campaign(campaigns, rate_scope=None)
    assert missing.value.code == "scope-unset"
    with pytest.raises(CollectionCampaignError) as missing_fee:
        opened_campaign(campaigns, fee_scope=None)
    assert missing_fee.value.code == "scope-unset"
    with pytest.raises(CollectionCampaignError) as unused:
        opened_campaign(
            campaigns,
            rate_reduction=Decimal(0),
            fee_reductions={},
            payment_holiday=True,
            rate_scope="campaign_period",
        )
    assert unused.value.code == "scope-unused"
    with pytest.raises(CollectionCampaignError) as empty:
        opened_campaign(
            campaigns,
            rate_reduction=Decimal(0),
            fee_reductions={},
            payment_holiday=False,
        )
    assert empty.value.code == "change-unset"
    with pytest.raises(CollectionCampaignError) as bad:
        opened_campaign(campaigns, rate_scope="forever")
    assert bad.value.code == "scope"
    assert campaigns.campaigns == {}
    status, body = dispatch(
        campaigns,
        "POST",
        "/v1/collection-campaigns",
        {
            "organisation_id": "org-a",
            "recognised_at": "2026-03-09T08:00:00+02:00",
            "start_date": "2026-03-09",
            "end_date": "2026-03-20",
            "rate_reduction": "0.02",
            "fee_reductions": {},
            "payment_holiday": False,
            "notice_date": "2026-03-02",
        },
        {"X-Actor-Id": "staff-1"},
    )
    assert status == 422
    assert body["code"] == "scope-unset"


def test_apply_does_not_create_a_credit_agreement():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    before = {item.loan_id for item in ledger.store.accounts_for("org-a")}
    campaign = opened_campaign(campaigns)
    campaigns.apply(
        campaign.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="organisation",
    )
    after = {item.loan_id for item in ledger.store.accounts_for("org-a")}
    assert before == after == {loan.loan_id}


def test_rest_of_term_overlaps_a_later_campaign_on_the_same_loan():
    campaigns, ledger = service()
    loan = book(ledger)
    register(campaigns, loan)
    first = opened_campaign(
        campaigns,
        end_date=date(2026, 3, 20),
        fee_reductions={},
        rate_scope="rest_of_term",
    )
    campaigns.apply(
        first.campaign_id,
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(2026, 3, 9),
        selector="loans",
        loan_ids=(loan.loan_id,),
    )
    later = opened_campaign(
        campaigns,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 10),
        notice_date=date(2026, 3, 25),
        recognised_at=at(2026, 3, 25),
        fee_reductions={},
    )
    with pytest.raises(CollectionCampaignError) as overlap:
        campaigns.apply(
            later.campaign_id,
            organisation_id="org-a",
            actor_id="staff-1",
            recognised_at=at(2026, 4, 1),
            selector="loans",
            loan_ids=(loan.loan_id,),
        )
    assert overlap.value.code == "campaign-overlap"
    assert len(campaigns.applications) == 1


def test_migration_stores_cents_notice_and_the_original_contract():
    sql = (ROOT / "db" / "migrations" / "0009_collection_campaigns.sql").read_text()
    assert "CREATE TABLE lms.collection_campaign" in sql
    assert "notice_business_days integer NOT NULL CHECK (notice_business_days = 5)" in sql
    assert "reduction_cents bigint NOT NULL CHECK (reduction_cents >= 0)" in sql
    assert "principal_cents bigint NOT NULL CHECK (principal_cents > 0)" in sql
    assert "does not update loan_account or schedule_line" in sql
    assert "rate_scope text CHECK (rate_scope IN ('campaign_period', 'rest_of_term'))" in sql
    assert "fee_scope text CHECK (fee_scope IN ('campaign_period', 'rest_of_term'))" in sql
    assert "CHECK ((rate_reduction = 0) = (rate_scope IS NULL))" in sql
    assert "COLLECTION_CAMPAIGN_CHANGED" in sql
    seed = (ROOT / "db" / "seed" / "001_reference.sql").read_text()
    assert "COLLECTION_CAMPAIGN_CHANGED" in seed
