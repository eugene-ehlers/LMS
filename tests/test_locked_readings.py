"""Pins for the five readings locked in pull request 54.

Amounts are integer cents. Recognition instants are Africa/Johannesburg,
and the value date is that calendar day at 00:00.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from lms.ledger.attribution import cents_toward_attributed_due
from lms.ledger.service import Ledger
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing, _threshold_instalment
from lms.statements.service import Documents, RecognisedReceipt
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-a"
PERSON = "person-a"
DUE = date(2026, 5, 1)
EARLIER = date(2026, 4, 30)


def at(day: date, hour: int = 8) -> datetime:
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


def test_a_section_126_part_applied_earlier_does_not_count_toward_the_later_due_date():
    ledger = Ledger()
    loan = ledger.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        organisation=settings(),
        recognised_at=at(date(2026, 4, 1)),
        cash_advanced_cents=10_000,
        frequency="monthly",
        schedule=((DUE, 10_000),),
        identity_name="Ada Borrower",
        identity_number="8001015800085",
        service_address="1 Main Road, Cape Town",
        initiation_fee_cents=0,
    )
    ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=1_000,
        due_on=EARLIER,
        recognised_at=at(EARLIER),
        interest_cap_present=True,
    )
    ledger.levy_charge(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        bucket="interest",
        cents=1_000,
        due_on=DUE,
        recognised_at=at(DUE),
        interest_cap_present=True,
    )
    payment = ledger.post_payment(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        cents=11_000,
        recognised_at=at(DUE, 10),
        attributed_due_on=DUE,
    )
    assert payment.value_date == DUE
    assert cents_toward_attributed_due(loan, payment) == 10_000
    april = next(charge for charge in loan.charges if charge.due_on == EARLIER)
    assert april.remaining_cents == 0
    flagged = ledger.flag_default(
        organisation_id=ORG,
        loan_id=loan.loan_id,
        check_on=DUE,
        due_on=DUE,
        instalment_cents=11_000,
        recognised_at=at(DUE, 11),
    )
    assert flagged is True


def test_morning_check_sees_a_receipt_allocated_on_the_flag_date():
    svc = Servicing(enigma=EnigmaStub())
    due = date(2026, 3, 31)
    later = date(2026, 4, 30)
    schedule = ((due, 50_000), (later, 50_000))
    record = svc.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1)),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=schedule,
        initiation_fee_cents=0,
        idempotency_key="book-flag",
    )
    record = svc.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    svc._capitalise_due_amounts(
        record,
        due,
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    loan = svc.ledger.store.get(ORG, record.ledger_loan_id)
    instalment = _threshold_instalment(loan, due)
    missed = svc.morning_check(
        record.agreement_id,
        due_on=due,
        recognised_at=at(due, 9),
    )
    assert missed.status == "in_arrears"
    assert svc.ledger._open_episode(loan) is not None

    paid = svc.book(
        organisation_id=ORG,
        person_id="person-b",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1)),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=schedule,
        initiation_fee_cents=0,
        idempotency_key="book-paid",
    )
    paid = svc.disburse(paid.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    svc._capitalise_due_amounts(
        paid,
        due,
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    paid_loan = svc.ledger.store.get(ORG, paid.ledger_loan_id)
    paid_instalment = _threshold_instalment(paid_loan, due)
    assert paid_instalment == instalment
    svc.accept_payment(
        organisation_id=ORG,
        person_id="person-b",
        cents=paid_instalment,
        recognised_at=at(due, 10),
        idempotency_key="pay-flag",
        agreement_id=paid.agreement_id,
        attributed_due_on=due,
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
        capitalise=False,
    )
    checked = svc.morning_check(
        paid.agreement_id,
        due_on=due,
        recognised_at=at(due, 11),
    )
    assert checked.status == "active"
    assert svc.ledger._open_episode(paid_loan) is None

    store = ComplianceStore()
    store.put(
        ProviderCompliance(
            organisation_id=ORG,
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
    folded = svc.book(
        organisation_id=ORG,
        person_id="person-c",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1)),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=schedule,
        initiation_fee_cents=0,
        idempotency_key="book-fold",
    )
    folded = svc.disburse(folded.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    svc._capitalise_due_amounts(
        folded,
        due,
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
    )
    folded_loan = svc.ledger.store.get(ORG, folded.ledger_loan_id)
    documents = Documents(svc, store)
    documents.issue_statement(
        organisation_id=ORG,
        person_id="person-c",
        period_start=date(2026, 3, 1),
        period_end=due,
        interest_cap_present=True,
        vat_rate=Decimal("0.15"),
        receipts=(
            RecognisedReceipt(
                agreement_id=folded.agreement_id,
                cents=_threshold_instalment(folded_loan, due),
                recognised_at=at(due, 10),
                attributed_due_on=due,
                idempotency_key="pay-inside-statement",
            ),
        ),
    )
    assert svc.ledger._open_episode(folded_loan) is None
    assert folded.status == "active"
