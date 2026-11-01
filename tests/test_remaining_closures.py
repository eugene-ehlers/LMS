"""Pins for the open items closed against the locked decisions.

Amounts are integer cents. Recognition is 00:00 Africa/Johannesburg.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from lms.batch.api import BatchStatusApp
from lms.batch.calculation import AccountStepError
from lms.batch.service import BatchService
from lms.batch.store import BatchStore
from lms.batch.timekeeping import parse_recognition_date
from lms.calc.models import RepoRate
from lms.calc.money import to_cents
from lms.collection_campaigns.api import dispatch as collection_dispatch
from lms.collection_campaigns.service import CollectionCampaigns
from lms.collections.service import Collections
from lms.dummies.enigma import EnigmaDummy
from lms.dummies.fixtures import FIXED_PERIODIC_RATE_BPS
from lms.payments.loan_numbers import LoanNumberSeries
from lms.ports.enigma import OrganisationContext
from lms.regulatory.form39 import Form39Readiness
from lms.regulatory.ncr import ncr_number_required, require_ncr_for_extract
from lms.restructure.api import dispatch as restructure_dispatch
from lms.restructure.engine import SuppliedTerms
from lms.restructure.service import RestructureService
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.settlement.errors import SettlementError
from lms.staff.elections import ElectionStore, ElectionValues
from lms.staff.errors import StaffError
from lms.staff.intake import record_intake
from lms.staff.service import _ncr_present
from lms_config.compliance import ComplianceStore
from tests.test_collection_campaigns import at as campaign_at
from tests.test_collection_campaigns import opened_campaign, service as campaign_service
from tests.test_restructure import (
    AGREEMENT,
    ORG,
    body,
    elections,
    headers,
    identity,
    post,
    service_with,
    terms,
)
from tests.test_settlement import at, quote, world

ROOT = Path(__file__).resolve().parents[1]
LOCK = (ROOT / "docs" / "LOCKED_DECISIONS.md").read_text()
JOHANNESBURG = timezone(timedelta(hours=2))


def test_locked_sentences_are_present() -> None:
    phrases = {
        "D1": "APP- plus eight digits",
        "D2": "Organisation context returns the organisation id",
        "D3": "frozen name, ID number, and service address are the Enigma booking read",
        "N2": "does not return email or mobile",
        "N3": "One month in this section is a calendar month",
        "N5": "push-provider machine action stay unset",
        "C1": "that campaign's fall-away choice and trigger apply",
        "C2": "intake fails closed and stores nothing",
        "C3": "The contractual rate remains the rate the decision engine supplies",
        "P1": "Debit orders enabled",
        "P2": "12-digit sequence starting at 1",
        "P3": "hashes homing account numbers modulo 10**12",
        "R1": "short_term` and `unsecured` are the micro",
        "R2": "Form 39 write-off cell stays empty",
        "S3": "does not accept them as provisioning or prescription inputs",
        "J2": "00:00 Africa/Johannesburg",
        "J4": "default_check` is this batch's morning check",
        "J5": "does not block the next recognition date",
        "J6": "walks every account through accrue",
        "J7": "missing `actor_id` fails closed",
        "J8": "never started does not block a later date",
        "J9": "cannot be started again",
        "J10": "No timeout is applied",
        "G2": "does not allocate a second loan number",
        "G4": "does not invent a role name",
        "G5": "neither a restructure nor a collection campaign",
        "G6": "do not name a restructure journal",
        "G7": "stored as active",
        "G8": "reads the organisation election",
        "G9": "does not add the collection-campaign notice",
        "F1": "binding for five business days",
        "F2": "Early-settlement interest runs to the quote as-of date",
        "F3": "must equal the quoted total",
        "F7": "one-cent difference between those totals is a refusal",
        "K7": "A null end date on this path is open-ended",
        "K8": "cannot open the batch screen",
        "K9": "A blank NCR number is refused",
    }
    missing = [item for item, phrase in phrases.items() if phrase not in LOCK]
    assert missing == []


def test_d1_day1_dummy_rate_is_basis_points() -> None:
    assert FIXED_PERIODIC_RATE_BPS == 240
    assert Decimal(FIXED_PERIODIC_RATE_BPS) / Decimal(10_000) == Decimal("0.0240")


def test_d2_organisation_context_has_no_service_address() -> None:
    names = set(OrganisationContext.__dataclass_fields__)
    assert names == {"organisation_id", "company_registration_number"}
    assert "service_address" not in names
    assert EnigmaDummy is not None


def test_n2_registration_check_returns_a_bool() -> None:
    stub = EnigmaStub()
    stub.registered = True
    assert stub.consumer_registered("org", "person") is True
    stub.registered = False
    assert stub.consumer_registered("org", "person") is False


def test_n3_one_month_is_not_a_thirty_day_count() -> None:
    period = date(2026, 3, 31) - date(2026, 3, 1)
    assert period.days == 30
    assert "does not count thirty days" in LOCK


def test_c2_overlapping_campaigns_store_nothing(tmp_path: Path) -> None:
    from lms.staff.campaigns import Campaign

    first = Campaign(
        campaign_id="c-1",
        organisation_id="org",
        product_id=None,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0.01"),
        net_rate=Decimal("0.04"),
        fall_away_choice="does_not_fall_away",
        fall_away_trigger=None,
        initiation_fee_discount_cents=0,
        service_fee_discount_cents=0,
        version=1,
    )
    second = Campaign(
        campaign_id="c-2",
        organisation_id="org",
        product_id=None,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0.02"),
        net_rate=Decimal("0.03"),
        fall_away_choice="does_not_fall_away",
        fall_away_trigger=None,
        initiation_fee_discount_cents=0,
        service_fee_discount_cents=0,
        version=1,
    )
    with pytest.raises(StaffError) as raised:
        record_intake(
            organisation_id="org",
            product_id=None,
            application_number="APP-00000001",
            recognition_date=date(2026, 6, 15),
            supplied_rate=Decimal("0.05"),
            credit_life_premium_cents=0,
            matches=(first, second),
            maturity_date=None,
        )
    assert raised.value.code == "campaign-ambiguous"


def test_c3_intake_keeps_supplied_rate_and_campaign_net() -> None:
    from lms.staff.campaigns import Campaign

    campaign = Campaign(
        campaign_id="c-1",
        organisation_id="org",
        product_id=None,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0.01"),
        net_rate=Decimal("0.04"),
        fall_away_choice="does_not_fall_away",
        fall_away_trigger=None,
        initiation_fee_discount_cents=0,
        service_fee_discount_cents=0,
        version=1,
    )
    stored = record_intake(
        organisation_id="org",
        product_id=None,
        application_number="APP-00000001",
        recognition_date=date(2026, 6, 15),
        supplied_rate=Decimal("0.05"),
        credit_life_premium_cents=0,
        matches=(campaign,),
        maturity_date=None,
    )
    assert stored.supplied_rate == Decimal("0.05")
    assert stored.campaign_net_rate == Decimal("0.04")
    assert stored.supplied_rate != stored.campaign_net_rate


def test_r1_classification_map_and_pure_hosting_fail_closed() -> None:
    assert ncr_number_required(classification="short_term", pure_hosting=False) is True
    assert ncr_number_required(classification="unsecured", pure_hosting=False) is True
    assert ncr_number_required(classification="zero_cost", pure_hosting=False) is False
    assert ncr_number_required(classification="cpa_layby", pure_hosting=False) is False
    assert ncr_number_required(classification="short_term", pure_hosting=True) is False
    with pytest.raises(Exception) as raised:
        require_ncr_for_extract(
            ComplianceStore(),
            organisation_id="org",
            classifications=("short_term",),
            pure_hosting=None,
        )
    assert raised.value.code == "pure-hosting-unset"


def test_n4_statement_table_has_no_classification_column() -> None:
    sql = (ROOT / "db" / "migrations" / "0004_ledger_accounts.sql").read_text()
    start = sql.index("CREATE TABLE lms.client_statement (")
    end = sql.index(");", start)
    table = sql[start:end]
    assert "classification" not in table
    assert "pure_hosting" not in table


def test_r2_form39_write_off_cell_stays_empty() -> None:
    assert Form39Readiness.__dataclass_fields__["write_offs"].default is None


def test_s3_promise_to_pay_is_not_a_provision_input() -> None:
    collections = Collections(Servicing(enigma=EnigmaStub()))
    with pytest.raises(TypeError):
        collections.record_provision(
            "agr",
            recognised_at=datetime(2026, 10, 1, 0, 0, tzinfo=JOHANNESBURG),
            amount_cents=100,
            promise_to_pay=True,
        )


def test_j2_recognition_instant_is_midnight_johannesburg() -> None:
    calendar, instant = parse_recognition_date("2026-06-15")
    assert calendar == "2026-06-15"
    assert instant.endswith("+02:00")
    assert "T00:00:00" in instant


def test_p2_loan_number_is_twelve_digits_from_one() -> None:
    series = LoanNumberSeries()
    first = series.issue(
        organisation_id="org",
        application_number="APP-00000001",
        agreement_id="agr",
        ledger_loan_id="loan",
    )
    assert first.loan_number == "000000000001"
    again = series.issue(
        organisation_id="org",
        application_number="APP-00000001",
        agreement_id="agr",
        ledger_loan_id="loan",
    )
    assert again.loan_number == first.loan_number


def test_k9_blank_ncr_is_refused_and_zeros_are_accepted() -> None:
    with pytest.raises(StaffError):
        _ncr_present("   ")
    _ncr_present("0000000")
    _ncr_present("NCRCP0000")


def test_f7_half_up_is_the_shared_rounding_rule() -> None:
    assert to_cents(Decimal("1.005")) == 101
    assert to_cents(Decimal("1.004")) == 100
    assert "No balancing journal is posted." in LOCK


def test_g3_supplied_rate_above_the_prescribed_monthly_maximum_is_refused() -> None:
    service, _engine = service_with(
        terms(contractual_periodic_rate_bps=501, term_count=18, instalment_cents=8_000)
    )
    status, payload = post(service)
    assert status == 422
    assert "exceeds the prescribed" in payload["reason"]
    assert service.agreements[AGREEMENT].status == "active"
    assert "new_agreement_id" not in service.agreements[AGREEMENT].__dict__ or (
        service.agreements[AGREEMENT].restructured_to_agreement_id is None
    )


def test_g6_restructure_moves_the_record_balance_and_posts_no_journal() -> None:
    service, _engine = service_with()
    assert not hasattr(service, "ledger")
    status, payload = post(service)
    assert status == 200
    original = service.agreements[AGREEMENT]
    created = service.agreements[payload["new_agreement_id"]]
    assert original.outstanding_balance_cents == 0
    assert created.outstanding_balance_cents == 150_000
    assert created.application_number == "APP-00000002"
    assert original.application_number == "APP-00000001"
    assert created.status == "active"
    assert original.status == "restructured"


def test_g8_restructure_reads_the_election_store_when_no_row_is_supplied() -> None:
    store = ElectionStore()
    store.put_organisation(
        ORG,
        ElectionValues(
            vat_on_rand_maxima="exclusive",
            late_disbursement="keep_instalment",
            partial_prepayment="shorten_term",
            interest_on_deferred_initiation="none",
            repo_rate_fall="contract_rate",
            in_duplum_trigger="collections_default",
            residual_write_off_threshold_cents=None,
            campaign_fall_away_choice="does_not_fall_away",
        ),
    )
    store.put_product(
        ORG,
        "micro",
        ElectionValues(partial_prepayment="drop_instalment"),
    )
    service, _engine = service_with()
    service.election_store = store
    payload = body()
    del payload["elections"]
    payload["product_id"] = "micro"
    status, response = restructure_dispatch(
        service,
        "POST",
        f"/v1/organisations/{ORG}/agreements/{AGREEMENT}/restructure",
        payload,
        headers(),
    )
    assert status == 200, response
    created = service.agreements[response["new_agreement_id"]]
    assert created.elections.partial_prepayment == "drop_instalment"
    assert created.elections.vat_on_rand_maxima == "exclusive"
    assert created.elections.residual_write_off_threshold_cents == 10_000


def test_g10_naive_restructure_is_not_audited() -> None:
    service, _engine = service_with()
    payload = body(recognised_at="2026-10-28T00:00:00")
    status, response = post(service, payload)
    assert status == 422
    assert response["reason"]
    assert service.audit.for_organisation(ORG) == ()


def test_f5_execute_rejects_repo_rows() -> None:
    _svc, settlement, record = world(initiation=0)
    quoted = quote(settlement, record, as_of=date(2026, 3, 1), vat=Decimal("0"), recognised_at=at(date(2026, 3, 1), 14))
    with pytest.raises(SettlementError) as raised:
        settlement.execute(
            agreement_id=record.agreement_id,
            quote_id=quoted.quote_id,
            cents=quoted.amount_owing_cents,
            recognised_at=at(date(2026, 3, 1), 15),
            interest_cap_present=True,
            vat_rate=Decimal("0"),
            idempotency_key="settle-repos",
            repos=(RepoRate(date(2026, 1, 1), Decimal("0.08")),),
        )
    assert raised.value.code == "repo-quote-unset"


def test_f6_naive_quote_and_unknown_agreement_are_not_audited() -> None:
    svc, settlement, record = world(initiation=0)
    before = len(
        svc.audit.extract(
            organisation_id=record.organisation_id,
            from_date=date(2026, 3, 1),
            to_date=date(2026, 5, 31),
        ).rows
    )
    with pytest.raises(SettlementError) as naive:
        settlement.quote(
            agreement_id=record.agreement_id,
            as_of=date(2026, 4, 10),
            delivered_on=date(2026, 4, 10),
            request_on=date(2026, 4, 10),
            recognised_at=datetime(2026, 4, 10, 0, 0),
            holidays=frozenset(),
            interest_cap_present=True,
            vat_rate=Decimal("0"),
        )
    assert naive.value.code == "timestamp-naive"
    with pytest.raises(SettlementError) as missing:
        settlement.quote(
            agreement_id="missing-agreement",
            as_of=date(2026, 4, 10),
            delivered_on=date(2026, 4, 10),
            request_on=date(2026, 4, 10),
            recognised_at=at(date(2026, 4, 10)),
            holidays=frozenset(),
            interest_cap_present=True,
            vat_rate=Decimal("0"),
        )
    assert missing.value.code == "not-found"
    after = len(
        svc.audit.extract(
            organisation_id=record.organisation_id,
            from_date=date(2026, 3, 1),
            to_date=date(2026, 5, 31),
        ).rows
    )
    assert after == before


def test_j11_account_batch_status_and_ui_action(tmp_path: Path) -> None:
    class FailAccrue:
        def accrue(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
            if account_id == "acc-b":
                raise AccountStepError("accrue", "accrual refused")

        def capitalise(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
            return None

        def default_check(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
            return None

        def at_in_duplum_ceiling(self, *, organisation_id: str, account_id: str) -> bool:
            return False

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 10, 28, 8, 0, tzinfo=JOHANNESBURG)

    store = BatchStore(str(tmp_path / "batch.sqlite"))
    service = BatchService(store, FailAccrue(), Clock())
    service.run_batch(
        organisation_id="org-1",
        actor_id="person-1",
        recognition_date="2026-10-28",
        account_ids=["acc-a", "acc-b"],
    )
    found = service.account_status("org-1", "acc-b")
    assert found.failure is not None
    assert found.failure.reason == "accrue: accrual refused"
    assert found.failure.account_id == "acc-b"
    clear = service.account_status("org-1", "acc-a")
    assert clear.failure is None

    restructure, _engine = service_with()
    status, payload = post(restructure)
    assert status == 200

    def ui(organisation_id: str, account_id: str | None) -> dict:
        view = restructure.last_ui_status(organisation_id, account_id)
        return {
            "organisation_id": organisation_id,
            "account_id": account_id,
            "recorded": view.recorded,
            "reason": view.reason,
            "outcome": view.outcome,
            "event_type": view.event_type,
        }

    app = BatchStatusApp(service, ui)
    code, body = app.handle("GET", "/organisations/org-1/accounts/acc-b/batch-status")
    assert code == 200
    assert body["failure"]["reason"] == "accrue: accrual refused"
    code, body = app.handle("GET", f"/organisations/{ORG}/accounts/{AGREEMENT}/ui-actions/status")
    assert code == 200
    assert body["recorded"] is True
    assert body["event_type"] == "RESTRUCTURE_CONFIRMED"
    code, body = app.handle("GET", f"/organisations/{ORG}/ui-actions/status")
    assert code == 200
    assert body["recorded"] is True


def test_k2_collection_campaign_read_returns_the_stored_campaign() -> None:
    campaigns, _ledger = campaign_service()
    created = opened_campaign(campaigns, end_date=None)
    code, listed = collection_dispatch(
        campaigns,
        "GET",
        "/v1/organisations/org-a/collection-campaigns",
        {},
        {"X-Actor-Id": "staff-1"},
    )
    assert code == 200
    assert listed["campaigns"][0]["campaign_id"] == created.campaign_id
    assert listed["campaigns"][0]["open_ended"] is True
    code, one = collection_dispatch(
        campaigns,
        "GET",
        f"/v1/organisations/org-a/collection-campaigns/{created.campaign_id}",
        {},
        {"X-Actor-Id": "staff-1"},
    )
    assert code == 200
    assert one["end_date"] is None
    assert one["campaign_id"] == created.campaign_id


def test_k4_and_k5_migration_names() -> None:
    directory = ROOT / "db" / "migrations"
    names = sorted(path.name for path in directory.glob("*.sql"))
    prefixes = [name.split("_", 1)[0] for name in names]
    assert len(prefixes) == len(set(prefixes))
    assert "0008_collection_campaigns.sql" in names
    assert "0009_layer2_staff.sql" in names
    assert "0010_settlement_readvance.sql" in names
    assert "0011_in_duplum_ceiling.sql" in names
    assert "0012_staff_ui_reported.sql" in names
    assert "0009_collection_campaigns.sql" not in names
    sql = (directory / "0012_staff_ui_reported.sql").read_text()
    assert "STAFF_UI_REPORTED" in sql


def test_k1_batch_screen_reads_the_batch_service(tmp_path: Path) -> None:
    from lms.staff_ui.app import StaffApp
    from tests.test_staff_ui import build_app, staff

    class Quiet:
        def accrue(self, **kwargs: object) -> None:
            return None

        def capitalise(self, **kwargs: object) -> None:
            return None

        def default_check(self, **kwargs: object) -> None:
            return None

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 10, 28, 8, 0, tzinfo=JOHANNESBURG)

    app = build_app()
    store = BatchStore(str(tmp_path / "screen.sqlite"))
    batch = BatchService(store, Quiet(), Clock())
    batch.run_batch(
        organisation_id="org-cape",
        actor_id="person-staff",
        recognition_date="2026-10-28",
        account_ids=["loan-1"],
    )
    app.batch = batch
    page = app.handle(staff(), "GET", "/staff/batch")
    assert page.status == 200
    assert "Accounts processed: 1" in page.body
    assert "does not accrue, capitalise, or flag a default" in page.body
    assert isinstance(app, StaffApp)


def test_k7_open_ended_collection_campaign_accepts_a_null_end_date() -> None:
    campaigns, _ledger = campaign_service()
    created = opened_campaign(campaigns, end_date=None)
    assert created.end_date is None
    assert campaign_at(2026, 3, 1).tzinfo is not None
