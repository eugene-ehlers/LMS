"""Staff and self-service screens called against the existing interfaces."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from lms.collections.service import WRITE_OFF_ACTION
from lms.servicing.service import PaymentRecord
from lms.staff.authority import (
    ROLE_CAMPAIGN_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_ELECTIONS_WRITE,
)
from lms.staff_ui.app import Session, build_app
from lms.statements.models import LoanSection, StoredQuote, StoredStatement
from lms_config.brand import Brand
from lms_config.calendar import value_date
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-screen"
PERSON = "person-staff"
BORROWER = "person-borrower"
FIRST = date(2026, 6, 15)
AT = "2026-10-15T10:00:00+02:00"
ROOT = Path(__file__).resolve().parents[1]
BUCKETS = (
    "principal",
    "interest",
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
)


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=JOHANNESBURG)


def session(*extra: str) -> Session:
    held = Session()
    held.person_id = PERSON
    held.organisation_id = ORG
    held.roles = frozenset(
        {
            ROLE_CAMPAIGN_WRITE,
            ROLE_ELECTIONS_WRITE,
            ROLE_CEILING_PLATFORM_WRITE,
            ROLE_CEILING_COMPANY_WRITE,
            WRITE_OFF_ACTION,
            *extra,
        }
    )
    held.enigma_status = "active"
    return held


def settings():
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


def book(app):
    record = app.servicing.book(
        organisation_id=ORG,
        person_id=BORROWER,
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(date(2026, 3, 1), 8),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((FIRST, 60_000), (date(2026, 7, 15), 40_000)),
        initiation_fee_cents=0,
        idempotency_key="book-screen",
    )
    record = app.servicing.disburse(record.agreement_id, recognised_at=at(date(2026, 3, 1), 10))
    app.collections.bind(record.agreement_id, in_duplum_trigger="collections_default")
    return record


def outstanding(app, loan_id: str) -> int:
    loan = app.servicing.ledger.store.get(ORG, loan_id)
    return sum(app.servicing.ledger.bucket_balance(loan, bucket) for bucket in BUCKETS)


def stored_statement() -> StoredStatement:
    loan = LoanSection(
        loan_id="loan-88",
        instrument_kind="credit",
        parent_loan_id=None,
        frozen_full_name="Ada Borrower",
        frozen_id_number="8001015800085",
        frozen_service_address="1 Main Road",
        payment_frequency="monthly",
        principal_debt_cents=100_000,
        opening={"principal": 100_000},
        closing={"principal": 12_345},
        opening_source="no-previous-statement",
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0"),
        discount_fallen_away=False,
        periodic_rate_in_force=Decimal("0.05"),
        nominal_annual_on_base=Decimal("0.60"),
        nominal_annual_on_effective=Decimal("0.60"),
        annual_rate_cell=None,
        instalment_cents=60_000,
        instalment_due_on=FIRST,
        payments_received_cents=0,
        fees_levied_cents=0,
        interest_billed_cents=250,
        interest_memo_rands=Decimal("0"),
        insurance_levied_cents=0,
        collection_levied_cents=0,
        default_administration_levied_cents=0,
        legal_fees_cents=None,
        arrears_cents=None,
        overdue=(),
        open_default_episode=False,
        transactions=(),
    )
    return StoredStatement(
        statement_id="stmt-1",
        organisation_id=ORG,
        person_id=BORROWER,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        statement_date=date(2026, 6, 30),
        legal_name="Cape Credit",
        ncr_registration_number="NCRCP0000",
        trading_name="",
        physical_address="1 Main Road",
        postal_address="PO Box 1",
        telephone="0210000000",
        bank_name="Example Bank",
        bank_account_number="1234567890",
        branch_code="051001",
        payment_reference="CAPE",
        loans=(loan,),
        pdf_sha256="abc",
        pdf_stub=b"stored",
    )


def stored_quote() -> StoredQuote:
    return StoredQuote(
        agreement_id="agr-1",
        organisation_id=ORG,
        person_id=BORROWER,
        as_of=date(2026, 6, 30),
        delivered_on=date(2026, 6, 30),
        valid_until=date(2026, 7, 7),
        deliver_by=date(2026, 7, 7),
        principal_cents=40_000,
        interest_cents=1_500,
        fee_cents=200,
        early_termination_cents=0,
        total_cents=41_700,
        agreement_size="small",
        components=(("principal", 40_000), ("interest", 1_500), ("service", 200)),
    )


def keep_stored(app):
    statement = stored_statement()
    app.documents.statements[(ORG, BORROWER, statement.period_start, statement.period_end)] = statement
    quote = stored_quote()
    app.documents.quotes[(quote.agreement_id, quote.as_of, quote.delivered_on)] = quote
    app.documents.issue_statement = _refuse_issue
    app.documents.settlement_quote = _refuse_quote
    return statement, quote


def _refuse_issue(*_args, **_kwargs):
    raise AssertionError("A screen issued a statement.")


def _refuse_quote(*_args, **_kwargs):
    raise AssertionError("A screen recalculated a settlement quote.")


def test_screens_do_not_issue_or_reprice():
    text = "\n".join(path.read_text() for path in (ROOT / "src" / "lms" / "staff_ui").rglob("*.py"))
    for banned in ("settlement_quote", "quote_settlement", "issue_statement", "write_off_outstanding"):
        assert banned not in text


def test_election_screen_marks_null_organisation_unset_and_null_product_inherits():
    app = build_app()
    held = session()
    listed = app.handle(held, "GET", "/staff/elections")
    assert 'data-null-label="unset"' in listed.body
    assert "vat_on_rand_maxima: unset" in listed.body
    assert 'data-state="inherits"' not in listed.body
    saved = app.handle(held, "POST", "/staff/products/micro/elections", {
        "recognised_at": AT,
        "in_duplum_trigger": "contractual_breach",
    })
    assert saved.status == 200
    product = app.handle(held, "GET", "/staff/products/micro/elections")
    assert "in_duplum_trigger: contractual_breach" in product.body
    assert "vat_on_rand_maxima: inherits" in product.body
    assert 'data-null-label="inherits"' in product.body
    assert "resolve" not in product.body


def test_ceiling_screen_shows_the_tighter_limit_and_saves_through_the_route():
    app = build_app()
    held = session()
    platform = app.handle(held, "POST", "/staff/ceilings/platform", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "20000",
    })
    assert platform.status == 200
    company = app.handle(held, "POST", "/staff/ceilings/company", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "15000",
    })
    assert company.status == 200
    page = app.handle(held, "GET", "/staff/ceilings/company")
    assert 'data-limit="15000"' in page.body
    assert app.office.ceilings.company(ORG, "lms.account.write_off").amount_cents == 15_000
    assert app.office.ceilings.platform("lms.account.write_off").amount_cents == 20_000


def test_campaign_screen_shows_start_and_end_and_saves_through_the_route():
    app = build_app()
    held = session()
    created = app.handle(held, "POST", "/staff/campaigns", {
        "recognised_at": AT,
        "product_id": "",
        "start_date": "2026-10-01",
        "end_date": "2026-10-31",
        "base_rate": "0.05",
        "discount_rate": "0.02",
        "fall_away_choice": "falls_away_on_default",
        "fall_away_trigger": "contractual_breach",
        "initiation_fee_discount_cents": "0",
        "service_fee_discount_cents": "0",
    })
    assert created.status == 200
    listed = app.handle(held, "GET", "/staff/campaigns")
    assert "2026-10-01" in listed.body
    assert "2026-10-31" in listed.body
    assert len(app.office.campaigns._rows) == 1


def test_collections_screen_shows_breach_and_default_and_allocates_before_write_off():
    app = build_app()
    held = session()
    record = book(app)
    blind = app.handle(held, "POST", "/staff/collections", {
        "agreement_id": record.agreement_id,
        "recognised_at": "2026-06-16T18:30:00+02:00",
    })
    assert "None recorded." in blind.body
    assert 'data-collections-default="true"' in blind.body
    assert "2026-06-16T00:00:00+02:00" in blind.body
    assert app.collections.cases[record.agreement_id].breaches == set()

    app.collections.observe(record.agreement_id, recognised_at=at(date(2026, 6, 16), 8))
    shown = app.handle(held, "POST", "/staff/collections", {
        "agreement_id": record.agreement_id,
        "recognised_at": "2026-06-16T18:30:00+02:00",
    })
    assert "2026-06-15" in shown.body
    assert 'data-collections-default="true"' in shown.body

    payment = PaymentRecord(
        payment_id="pay-unapplied",
        organisation_id=ORG,
        person_id=BORROWER,
        cents=1_000,
        recognised_at=at(date(2026, 6, 16), 11),
        value_date=value_date(at(date(2026, 6, 16), 11)),
        status="unapplied",
        agreement_id=record.agreement_id,
        attributed_due_on=FIRST,
    )
    app.servicing.payments[payment.payment_id] = payment
    held.roles = frozenset(role for role in held.roles if role != WRITE_OFF_ACTION)
    denied = app.handle(held, "POST", "/staff/collections/write-off", {
        "agreement_id": record.agreement_id,
        "recognised_at": "2026-06-16T18:30:00+02:00",
        "amount_cents": "1",
    })
    assert denied.status == 422
    assert payment.status == "unapplied"
    assert "lms.account.write_off" in denied.body
    kinds = [item.kind for item in app.servicing.ledger.store.transactions_for(ORG, record.ledger_loan_id)]
    assert "write_off" not in kinds

    app.handle(held, "POST", "/staff/acknowledge", {"nonce": _nonce(denied.body)})
    held.roles = held.roles | frozenset({WRITE_OFF_ACTION})
    before = outstanding(app, record.ledger_loan_id)
    refused = app.handle(held, "POST", "/staff/collections/write-off", {
        "agreement_id": record.agreement_id,
        "recognised_at": "2026-06-16T18:30:00+02:00",
        "amount_cents": str(before),
    })
    assert payment.status == "allocated"
    assert "write_off" not in [
        item.kind for item in app.servicing.ledger.store.transactions_for(ORG, record.ledger_loan_id)
    ]
    assert refused.status == 422
    app.handle(held, "POST", "/staff/acknowledge", {"nonce": _nonce(refused.body)})

    after = outstanding(app, record.ledger_loan_id)
    assert after < before
    ceiling = app.handle(held, "POST", "/staff/ceilings/platform", {
        "recognised_at": AT,
        "action": WRITE_OFF_ACTION,
        "amount_cents": str(after),
    })
    assert ceiling.status == 200
    posted = app.handle(held, "POST", "/staff/collections/write-off", {
        "agreement_id": record.agreement_id,
        "recognised_at": "2026-06-16T18:30:00+02:00",
        "amount_cents": str(after),
    })
    assert posted.status == 200, posted.body
    assert "written off" in posted.body
    assert "2026-06-16T00:00:00+02:00" in posted.body
    assert app.collections.view(record.agreement_id).written_off is True
    assert outstanding(app, record.ledger_loan_id) == 0


def test_staff_statement_screen_paints_stored_figures_for_loan_or_id():
    app = build_app()
    held = session()
    statement, _quote = keep_stored(app)
    before = len(app.documents.statements)
    by_id = app.handle(held, "POST", "/staff/statements", {"loan_or_id": "8001015800085"})
    by_loan = app.handle(held, "POST", "/staff/statements", {"loan_or_id": "loan-88"})
    missed = app.handle(held, "POST", "/staff/statements", {"loan_or_id": "missing"})
    for page in (by_id, by_loan):
        assert "12345" in page.body
        assert "stmt-1" in page.body
        assert statement.statement_id in page.body
    assert "No stored statement matches" in missed.body
    assert len(app.documents.statements) == before


def test_registration_and_sign_on_direct_the_consumer_to_enigma():
    app = build_app()
    held = session()
    for path in ("/self/register", "/self/sign-on"):
        page = app.handle(held, "GET", path)
        assert page.status == 200
        assert 'data-redirect="closed"' in page.body
        assert 'type="password"' not in page.body
        assert 'name="email"' not in page.body
        assert "http://" not in page.body
        assert "https://" not in page.body
    posted = app.handle(held, "POST", "/self/register", {"email": "a@b.c", "password": "secret"})
    assert posted.status == 422
    assert "Enigma" in posted.body
    assert len(app.servicing.agreements) == 0


def test_self_service_paints_the_stored_statement_and_quote():
    app = build_app()
    held = session()
    held.person_id = BORROWER
    _statement, quote = keep_stored(app)
    unsigned = Session()
    unsigned.enigma_status = "active"
    blocked = app.handle(unsigned, "GET", "/self/statement")
    assert "Enigma" in blocked.body
    assert "12345" not in blocked.body
    statement_page = app.handle(held, "GET", "/self/statement")
    quote_page = app.handle(held, "GET", "/self/settlement-quote")
    assert "12345" in statement_page.body
    assert 'data-total-cents="41700"' in quote_page.body
    assert quote.total_cents == 41_700
    other = session()
    other.person_id = "person-else"
    hidden = app.handle(other, "GET", "/self/statement")
    assert "No stored statement is held" in hidden.body
    assert "12345" not in hidden.body


def test_one_brand_change_updates_every_screen():
    app = build_app()
    held = session()
    keep_stored(app)
    held.person_id = BORROWER
    app.brand.put(Brand(
        organisation_id=ORG,
        brand_code="primary",
        display_name="Cape",
        logo_object_key="logo-a",
        statement_footer="Footer A",
    ))
    first_pages = (
        app.handle(held, "GET", "/staff/"),
        app.handle(held, "GET", "/self/register"),
        app.handle(held, "GET", "/self/statement"),
    )
    for page in first_pages:
        assert 'data-logo-key="logo-a"' in page.body
        assert "Footer A" in page.body
    app.brand.put(Brand(
        organisation_id=ORG,
        brand_code="primary",
        display_name="Cape",
        logo_object_key="logo-b",
        statement_footer="Footer B",
    ))
    second_pages = (
        app.handle(held, "GET", "/staff/campaigns"),
        app.handle(held, "GET", "/self/sign-on"),
        app.handle(held, "GET", "/self/settlement-quote"),
    )
    for page in second_pages:
        assert 'data-logo-key="logo-b"' in page.body
        assert "Footer B" in page.body
        assert "logo-a" not in page.body
        assert "Footer A" not in page.body
    app.brand.put(Brand(
        organisation_id=ORG,
        brand_code="second",
        display_name="Other",
        logo_object_key="logo-c",
        statement_footer="Footer C",
    ))
    blocked = app.handle(held, "GET", "/staff/elections")
    assert 'data-brand="many"' in blocked.body
    assert "logo-b" not in blocked.body
    assert "logo-c" not in blocked.body
    assert "Footer B" not in blocked.body
    assert "Footer C" not in blocked.body


def _nonce(body: str) -> str:
    import re
    found = re.search(r'name="nonce" value="([^"]+)"', body)
    assert found is not None
    return found.group(1)
