"""Section 104 rate and fee changes. Amounts are integer cents.

The recognition date is 00:00 Africa/Johannesburg. A missing notice date
or a gap shorter than five business days stores nothing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from lms.calc.interest import daily_interest_rands
from lms.ledger.service import Ledger
from lms.rate_fee_change.api import dispatch
from lms.rate_fee_change.service import RateFeeChanges, earliest_effective_date, notice_holidays
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms_config.calendar import add_business_days
from lms_config.locked import OrganisationSettings
from lms_config.templates import bnpl_zero, micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
YOUTH_DAY = date(2026, 6, 16)


def at(day: date, hour: int = 8, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=JOHANNESBURG)


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
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def book(ledger: Ledger, *, when: date = date(2026, 3, 1), person_id: str = "person-a", organisation_id: str = "org-a", product=None, cash: int = 100_000):
    return ledger.book(
        organisation_id=organisation_id,
        person_id=person_id,
        product=product or micro_short_term(),
        organisation=provider_settings(),
        recognised_at=at(when),
        cash_advanced_cents=cash,
        frequency="monthly",
        schedule=((date(2026, 12, 15), cash),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
    )


def service(ledger: Ledger | None = None, access: EnigmaStub | None = None) -> tuple[RateFeeChanges, Ledger, EnigmaStub]:
    ledger = ledger or Ledger()
    access = access or EnigmaStub()
    return RateFeeChanges(ledger, access), ledger, access


def apply(changes: RateFeeChanges, account, **overrides):
    notice = overrides.pop("notice_date", date(2026, 3, 2))
    if "effective_date" in overrides:
        effective = overrides.pop("effective_date")
    elif isinstance(notice, date):
        effective = earliest_effective_date(notice)
    else:
        effective = None
    payload = dict(
        organisation_id=account.organisation_id,
        actor_id="staff-1",
        recognised_at=at(notice if isinstance(notice, date) else date(2026, 3, 2)),
        notice_date=notice,
        effective_date=effective,
        end_date=None,
        periodic_rate="0",
        fees_cents=None,
        fee_payment_frequency=None,
        fee_payment_time=None,
        selector="loans",
        loan_ids=(account.loan_id,),
        contractual_fees_cents=None,
    )
    payload.update(overrides)
    return changes.apply(**payload)


def instalments(account) -> tuple[tuple[date, int], ...]:
    return tuple((item.due_on, item.amount_cents) for item in sorted(account.slices, key=lambda item: item.sequence))


def test_five_business_days_is_the_earliest_effective_date_and_a_holiday_extends_it():
    notice = date(2026, 6, 12)
    holidays = notice_holidays(notice, frozenset())
    assert YOUTH_DAY in holidays
    earliest = earliest_effective_date(notice)
    without_youth_day = add_business_days(notice, 5, holidays - {YOUTH_DAY})
    assert earliest > without_youth_day
    assert earliest == date(2026, 6, 22)
    assert without_youth_day == date(2026, 6, 19)

    changes, ledger, _access = service()
    account = book(ledger, when=date(2026, 6, 1))
    short = apply(changes, account, notice_date=notice, effective_date=without_youth_day, recognised_at=at(notice))
    assert short.ok is False
    assert short.code == "notice-short"
    assert changes.list_changes(account.organisation_id) == ()
    status = changes.last_status(organisation_id=account.organisation_id, on=notice, loan_id=account.loan_id)
    assert status.outcome == "failure"
    assert status.code == "notice-short"

    done = apply(changes, account, notice_date=notice, effective_date=earliest, recognised_at=at(notice))
    assert done.ok is True
    assert done.code == "applied"
    assert "00:00 Africa/Johannesburg" in done.message
    assert notice.isoformat() in done.message
    assert "staff-1" in done.message


def test_missing_notice_stores_nothing_and_is_audited():
    changes, ledger, _access = service()
    account = book(ledger)
    outcome = apply(changes, account, notice_date=None)
    assert outcome.ok is False
    assert outcome.code == "notice-missing"
    assert "Section 104(2)" in outcome.message
    assert changes.list_changes("org-a") == ()
    report = changes.last_status(organisation_id="org-a", on=date(2026, 3, 2), loan_id=account.loan_id)
    assert report.outcome == "failure"
    assert report.code == "notice-missing"
    assert report.action == "apply"


def test_reduction_is_used_from_the_effective_instant_and_originals_resume_after_the_end_date():
    changes, ledger, _access = service()
    account = book(ledger)
    before = instalments(account)
    end = account.contractual_end
    frequency = account.payment_frequency
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    outcome = apply(
        changes,
        account,
        notice_date=notice,
        effective_date=effective,
        end_date=effective,
        periodic_rate="0",
        fees_cents={"service": 0},
        contractual_fees_cents={account.loan_id: {"service": 6_000}},
    )
    assert outcome.ok is True
    assert instalments(account) == before
    assert account.contractual_end == end
    assert account.payment_frequency == frequency
    stored = changes.account_record("org-a", outcome.change_id, account.loan_id)
    assert stored.contractual_instalments == before
    assert stored.contractual_fees_cents["service"] == 6_000
    assert changes.get("org-a", outcome.change_id).fees_cents["service"] == 0
    assert stored.contractual_periodic_rate > 0

    day_before = effective - timedelta(days=1)
    earlier = changes.accrue(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(day_before, 23),
        interest_cap_present=True,
    )
    assert earlier.periodic_rate == stored.contractual_periodic_rate
    assert earlier.day_rands > 0

    # 22:30 UTC is 00:30 in Johannesburg, so the value date is the effective date.
    on_effective = changes.accrue(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=datetime(
            day_before.year, day_before.month, day_before.day, 22, 30, tzinfo=timezone.utc
        ),
        interest_cap_present=True,
    )
    assert on_effective.value_date == effective
    assert on_effective.periodic_rate == Decimal("0")
    assert on_effective.day_rands == daily_interest_rands(100_000, Decimal("0"), 31, weight=1)

    resumed = changes.accrue(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective + timedelta(days=1)),
        interest_cap_present=True,
    )
    assert resumed.periodic_rate == stored.contractual_periodic_rate
    assert changes.service_fee_for_levy(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective),
        monthly_cents=6_000,
    ) == 0
    assert changes.service_fee_for_levy(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective + timedelta(days=1)),
        monthly_cents=6_000,
    ) == 6_000

    audit = changes.last_status(organisation_id="org-a", on=notice, loan_id=account.loan_id)
    assert audit.outcome == "success"
    assert audit.code == "applied"


def test_open_ended_change_keeps_the_new_rate_until_an_end_date_is_stored():
    changes, ledger, _access = service()
    account = book(ledger)
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    outcome = apply(changes, account, end_date=None, periodic_rate="0")
    assert outcome.ok is True
    assert "until an end date is stored" in outcome.message
    later = effective + timedelta(days=10)
    accrual = changes.accrue(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(later),
        interest_cap_present=True,
    )
    assert accrual.periodic_rate == Decimal("0")
    ended = changes.end(
        organisation_id="org-a",
        change_id=outcome.change_id,
        actor_id="staff-1",
        recognised_at=at(later),
        end_date=effective,
    )
    assert ended.ok is False
    assert ended.code == "accrual-already-posted"
    assert changes.get("org-a", outcome.change_id).end_date is None

    closed = changes.end(
        organisation_id="org-a",
        change_id=outcome.change_id,
        actor_id="staff-1",
        recognised_at=at(later),
        end_date=later,
    )
    assert closed.ok is True
    assert "resume on the next recognition date" in closed.message
    following = changes.accrue(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(later + timedelta(days=1)),
        interest_cap_present=True,
    )
    assert following.periodic_rate > 0


def test_increases_overlaps_and_restructures_store_nothing():
    changes, ledger, _access = service()
    account = book(ledger)
    before = (account.contractual_end, account.payment_frequency, instalments(account))
    increased = apply(changes, account, periodic_rate="0.90")
    assert increased.code == "rate-increase"
    assert "Section 104(1)" in increased.message
    same = apply(changes, account, periodic_rate=None, fees_cents={"service": 6_000}, contractual_fees_cents={account.loan_id: {"service": 6_000}})
    assert same.code == "fee-not-reduced"
    negative = apply(changes, account, periodic_rate=None, fees_cents={"service": -1}, contractual_fees_cents={account.loan_id: {"service": 6_000}})
    assert negative.code == "fee-negative"
    higher_fee = apply(changes, account, periodic_rate=None, fees_cents={"service": 6_001}, contractual_fees_cents={account.loan_id: {"service": 6_000}})
    assert higher_fee.code == "fee-increase"
    assert changes.list_changes("org-a") == ()
    assert (account.contractual_end, account.payment_frequency, instalments(account)) == before

    first = apply(changes, account, periodic_rate="0")
    assert first.ok is True
    second = apply(changes, account, periodic_rate="0")
    assert second.code == "change-overlap"
    assert len(changes.list_changes("org-a")) == 1

    other = book(ledger, person_id="person-b")
    unknown = apply(changes, other, loan_ids=(other.loan_id, "missing-loan"), periodic_rate="0")
    assert unknown.code == "loan-unknown"
    assert len(changes.list_changes("org-a")) == 1


def test_frequency_and_time_do_not_rewrite_the_instalment():
    changes, ledger, _access = service()
    account = book(ledger)
    before = (account.payment_frequency, account.contractual_end, instalments(account))
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    outcome = apply(
        changes,
        account,
        periodic_rate=None,
        fee_payment_frequency="weekly",
        fee_payment_time=effective,
    )
    assert outcome.ok is True
    assert (account.payment_frequency, account.contractual_end, instalments(account)) == before
    assert changes.fee_due_on(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective),
        contractual_due_on=effective,
    ) == effective
    refused = None
    try:
        changes.fee_due_on(
            organisation_id="org-a",
            loan_id=account.loan_id,
            recognised_at=at(effective),
            contractual_due_on=date(2026, 12, 15),
        )
    except Exception as exc:
        refused = exc
    assert refused is not None
    assert refused.code == "payment-time"
    assert changes.fee_due_on(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective + timedelta(days=1)),
        contractual_due_on=effective + timedelta(days=7),
    ) == effective + timedelta(days=7)


def test_posted_accrual_is_not_restated():
    changes, ledger, _access = service()
    account = book(ledger)
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    ledger.accrue_day(
        organisation_id="org-a",
        loan_id=account.loan_id,
        recognised_at=at(effective),
        interest_cap_present=True,
    )
    outcome = apply(changes, account, effective_date=effective, periodic_rate="0")
    assert outcome.code == "accrual-already-posted"
    assert changes.list_changes("org-a") == ()


def test_enigma_timeout_fails_closed():
    access = EnigmaStub()
    access.mode = "timeout"
    changes, ledger, _access = service(access=access)
    account = book(ledger)
    outcome = apply(changes, account)
    assert outcome.ok is False
    assert outcome.code == "authority-unavailable"
    assert outcome.status == 503
    assert changes.list_changes("org-a") == ()
    report = changes.last_status(organisation_id="org-a", on=date(2026, 3, 2))
    assert report.code == "authority-unavailable"


def test_naive_timestamp_is_not_sealed():
    changes, ledger, _access = service()
    account = book(ledger)
    outcome = changes.apply(
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=datetime(2026, 3, 2, 8, 0),
        notice_date=date(2026, 3, 2),
        effective_date=date(2026, 3, 9),
        end_date=None,
        periodic_rate="0",
        fees_cents=None,
        fee_payment_frequency=None,
        fee_payment_time=None,
        selector="loans",
        loan_ids=(account.loan_id,),
    )
    assert outcome.code == "timestamp-naive"
    report = changes.last_status(organisation_id="org-a", on=date(2026, 12, 31))
    assert report.found is False


def test_routes_reject_a_restructure_and_a_campaign_and_accept_a_zero_fee():
    changes, ledger, _access = service()
    account = book(ledger)
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    headers = {"X-Actor-Id": "staff-1"}
    recognised = at(notice).isoformat()
    restructure = dispatch(
        changes,
        "POST",
        f"/v1/organisations/org-a/rate-fee-changes",
        {
            "recognised_at": recognised,
            "notice_date": notice.isoformat(),
            "effective_date": effective.isoformat(),
            "selector": "loans",
            "loan_ids": [account.loan_id],
            "periodic_rate": "0",
            "instalment_cents": 1,
        },
        headers,
    )
    assert restructure[0] == 422
    assert restructure[1]["code"] == "restructure"
    assert restructure[1]["outcome"] == "failure"
    assert changes.last_status(organisation_id="org-a", on=notice).code == "restructure"

    campaign = dispatch(
        changes,
        "POST",
        "/v1/organisations/org-a/rate-fee-changes",
        {
            "recognised_at": recognised,
            "payment_holiday": True,
            "selector": "loans",
            "loan_ids": [account.loan_id],
        },
        headers,
    )
    assert campaign[1]["code"] == "out-of-scope"

    floated = dispatch(
        changes,
        "POST",
        "/v1/organisations/org-a/rate-fee-changes",
        {
            "recognised_at": recognised,
            "notice_date": notice.isoformat(),
            "effective_date": effective.isoformat(),
            "selector": "loans",
            "loan_ids": [account.loan_id],
            "fees_cents": {"service": 0.0},
            "contractual_fees_cents": {account.loan_id: {"service": 6_000}},
        },
        headers,
    )
    assert floated[1]["code"] == "fee-cents"

    product = dispatch(
        changes,
        "POST",
        "/v1/organisations/org-a/rate-fee-changes",
        {
            "recognised_at": recognised,
            "notice_date": notice.isoformat(),
            "effective_date": effective.isoformat(),
            "selector": "product",
            "product_code": "micro",
            "periodic_rate": "0",
        },
        headers,
    )
    assert product[1]["code"] == "product-unsupported"

    applied = dispatch(
        changes,
        "POST",
        "/v1/organisations/org-a/rate-fee-changes",
        {
            "recognised_at": recognised,
            "notice_date": notice.isoformat(),
            "effective_date": effective.isoformat(),
            "selector": "loans",
            "loan_ids": [account.loan_id],
            "fees_cents": {"service": 0},
            "contractual_fees_cents": {account.loan_id: {"service": 6_000}},
        },
        headers,
    )
    assert applied[0] == 200
    assert applied[1]["outcome"] == "success"
    assert applied[1]["confirmation"]
    levy = dispatch(
        changes,
        "POST",
        f"/v1/organisations/org-a/loans/{account.loan_id}/rate-fee-service-fees",
        {
            "recognised_at": at(effective).isoformat(),
            "monthly_cents": 6_000,
            "due_on": effective.isoformat(),
            "interest_cap_present": True,
            "vat_rate": "0.15",
            "opening": False,
        },
        headers,
    )
    assert levy[0] == 200, levy[1]
    assert levy[1]["amount_cents"] == 0


def test_organisation_selector_applies_to_each_loan_and_not_another_organisation():
    changes, ledger, _access = service()
    first = book(ledger, person_id="person-a")
    second = book(ledger, person_id="person-b")
    outsider = book(ledger, person_id="person-c", organisation_id="org-b")
    notice = date(2026, 3, 2)
    outcome = changes.apply(
        organisation_id="org-a",
        actor_id="staff-1",
        recognised_at=at(notice),
        notice_date=notice,
        effective_date=earliest_effective_date(notice),
        end_date=None,
        periodic_rate="0",
        fees_cents=None,
        fee_payment_frequency=None,
        fee_payment_time=None,
        selector="organisation",
        loan_ids=(),
    )
    assert outcome.ok is True
    assert set(outcome.loan_ids) == {first.loan_id, second.loan_id}
    assert outsider.loan_id not in outcome.loan_ids


def test_zero_cost_and_extending_an_end_date_fail_closed():
    changes, ledger, _access = service()
    zero = book(ledger, product=bnpl_zero(), person_id="person-z")
    refused = apply(changes, zero, periodic_rate="0")
    assert refused.code == "zero-cost"

    account = book(ledger)
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)
    outcome = apply(changes, account, end_date=effective, periodic_rate="0")
    assert outcome.ok is True
    extended = changes.end(
        organisation_id="org-a",
        change_id=outcome.change_id,
        actor_id="staff-1",
        recognised_at=at(effective),
        end_date=effective + timedelta(days=1),
    )
    assert extended.code == "end-extends"
    assert changes.get("org-a", outcome.change_id).end_date == effective


def test_statement_accrual_uses_the_new_rate_when_the_service_is_attached():
    notice = date(2026, 3, 2)
    effective = earliest_effective_date(notice)

    def memo(svc: Servicing, loan_id: str) -> Decimal:
        total = Decimal(0)
        for transaction in svc.ledger.store.transactions_for("org-a", loan_id):
            if transaction.kind == "interest_accrual" and transaction.memo_rands is not None:
                total += transaction.memo_rands
        return total

    plain = Servicing(enigma=EnigmaStub())
    record = plain.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=provider_settings(),
        recognised_at=at(date(2026, 3, 1)),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 100_000),),
        idempotency_key="plain",
    )
    plain.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    plain.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=effective,
        period_end=effective,
        vat_rate=Decimal("0.15"),
        interest_cap_present=True,
    )
    assert memo(plain, record.ledger_loan_id) > 0

    changed = Servicing(enigma=EnigmaStub())
    changes = RateFeeChanges(changed.ledger, changed.enigma, changed.audit)
    changed.rate_fee_changes = changes
    booked = changed.book(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=provider_settings(),
        recognised_at=at(date(2026, 3, 1)),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((date(2026, 6, 15), 100_000),),
        idempotency_key="changed",
    )
    changed.disburse(booked.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    account = changed.ledger.store.get("org-a", booked.ledger_loan_id)
    done = apply(changes, account, periodic_rate="0")
    assert done.ok is True
    changed.issue_statement(
        organisation_id="org-a",
        person_id="person-a",
        period_start=effective,
        period_end=effective,
        vat_rate=Decimal("0.15"),
        interest_cap_present=True,
    )
    assert memo(changed, booked.ledger_loan_id) == 0
