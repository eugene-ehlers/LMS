"""Staff screens call the existing routes and stop on a reported failure."""

from __future__ import annotations

import re
import threading
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from lms.collection_campaigns.models import ROLE as COLLECTION_ROLE
from lms.staff.authority import (
    ROLE_CAMPAIGN_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_COMPLIANCE_WRITE,
    ROLE_ELECTIONS_WRITE,
)
from lms.staff_ui.app import Session, build_app, make_server

ORG = "org-cape"
PERSON = "person-staff"
AT = "2026-10-15T10:00:00+02:00"
ROOT = Path(__file__).resolve().parents[1]


def staff(*extra: str) -> Session:
    session = Session()
    session.person_id = PERSON
    session.organisation_id = ORG
    session.roles = frozenset(
        {
            ROLE_CAMPAIGN_WRITE,
            ROLE_ELECTIONS_WRITE,
            ROLE_COMPLIANCE_WRITE,
            ROLE_CEILING_PLATFORM_WRITE,
            ROLE_CEILING_COMPANY_WRITE,
            COLLECTION_ROLE,
            *extra,
        }
    )
    session.enigma_status = "active"
    return session


def campaign_form(**overrides) -> dict:
    body = {
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
    }
    body.update(overrides)
    return body


def election_form(**overrides) -> dict:
    body = {
        "recognised_at": AT,
        "vat_on_rand_maxima": "exclusive",
        "late_disbursement": "keep_instalment",
        "partial_prepayment": "shorten_term",
        "interest_on_deferred_initiation": "none",
        "repo_rate_fall": "contract_rate",
        "in_duplum_trigger": "collections_default",
        "residual_write_off_threshold_cents": "10000",
        "campaign_fall_away_choice": "does_not_fall_away",
        "campaign_fall_away_trigger": "",
    }
    body.update(overrides)
    return body


def compliance_form(**overrides) -> dict:
    body = {
        "recognised_at": AT,
        "legal_name": "Cape Credit (Pty) Ltd",
        "ncr_registration_number": "NCRCP999",
        "trading_name": "Cape Credit",
        "physical_address": "1 Main Road, Cape Town",
        "postal_address": "PO Box 1, Cape Town",
        "telephone": "0210000000",
        "bank_name": "Example Bank",
        "bank_account_number": "1234567890",
        "branch_code": "051001",
        "payment_reference": "CAPE",
    }
    body.update(overrides)
    return body


def collection_form(**overrides) -> dict:
    body = {
        "recognised_at": AT,
        "start_date": "2026-10-15",
        "end_date": "2026-11-30",
        "rate_reduction": "0.01",
        "rate_scope": "campaign_period",
        "notice_date": "2026-10-01",
        "fee_service": "1000",
        "fee_scope": "campaign_period",
    }
    body.update(overrides)
    return body


def outcomes(app, organisation=ORG):
    extract = app.office.audit.extract(
        organisation_id=organisation,
        from_date=date(2020, 1, 1),
        to_date=date(2030, 1, 1),
    )
    return [row for row in extract.rows if row.event_type == "STAFF_UI_REPORTED"]


def nonce(body: str) -> str:
    found = re.search(r'name="nonce" value="([^"]+)"', body)
    assert found is not None
    return found.group(1)


def app_continue(body: str) -> str:
    return re.search(r'class="continue" href="([^"]+)"', body).group(1)


def _types(app) -> list[str]:
    return [
        row.event_type
        for row in app.office.audit.extract(
            organisation_id=ORG,
            from_date=date(2020, 1, 1),
            to_date=date(2030, 1, 1),
        ).rows
    ]


def test_screens_call_routes_and_do_not_reimplement_them():
    text = "\n".join(path.read_text() for path in (ROOT / "src" / "lms" / "staff_ui").rglob("*.py"))
    for banned in ("campaign_rate", "issue_statement", "accrue_day", "write_off_outstanding"):
        assert banned not in text


def test_campaign_create_confirms_and_lists_the_route_result():
    app = build_app()
    session = staff()
    created = app.handle(session, "POST", "/staff/campaigns", campaign_form(discount_rate="0.08"))
    assert created.status == 200
    assert 'data-outcome="success"' in created.body
    assert "Net rate is 0." in created.body
    assert "You can continue." in created.body
    assert 'name="base_rate"' not in created.body
    assert "<form" not in created.body
    assert "The outcome was written to the audit log." in created.body
    listed = app.handle(session, "GET", app_continue(created.body))
    assert "Campaigns" in listed.body
    assert listed.body.count("0.08") >= 1
    kinds = _types(app)
    assert "CAMPAIGN_CREATED" in kinds
    assert "STAFF_UI_REPORTED" in kinds
    assert outcomes(app)[-1].payload["outcome"] == "success"
    assert outcomes(app)[-1].enigma_person_id == PERSON


def test_campaign_edit_and_end_use_the_route():
    app = build_app()
    session = staff()
    created = app.handle(session, "POST", "/staff/campaigns", campaign_form())
    campaign_id = re.search(r"Campaign ([0-9a-f-]+) was stored", created.body).group(1)
    edited = app.handle(session, "POST", f"/staff/campaigns/{campaign_id}", campaign_form(discount_rate="0.01"))
    assert "Version is 2." in edited.body
    ended = app.handle(session, "POST", f"/staff/campaigns/{campaign_id}/end", {"recognised_at": AT})
    assert "now ends on 2026-10-15" in ended.body
    assert 'name="end_date"' not in ended.body


def test_failure_blocks_the_next_step_until_acknowledged():
    app = build_app()
    session = staff()
    session.roles = frozenset({ROLE_ELECTIONS_WRITE})
    failed = app.handle(session, "POST", "/staff/campaigns", campaign_form())
    assert failed.status == 422
    assert "lms.campaign.write" in failed.body
    assert 'data-outcome="failure"' in failed.body
    assert 'name="base_rate"' not in failed.body
    blocked = app.handle(session, "POST", "/staff/campaigns", campaign_form())
    assert "lms.campaign.write" in blocked.body
    assert len(app.office.campaigns._rows) == 0
    assert any(row.payload["outcome"] == "blocked" for row in outcomes(app))
    home = app.handle(session, "GET", "/staff/campaigns/new")
    assert 'data-outcome="failure"' in home.body
    assert 'name="start_date"' not in home.body
    app.handle(session, "POST", "/staff/acknowledge", {"nonce": "wrong"})
    assert session.pending is not None
    acknowledged = app.handle(session, "POST", "/staff/acknowledge", {"nonce": nonce(failed.body)})
    assert 'data-outcome="acknowledged"' in acknowledged.body
    assert session.pending is None
    form = app.handle(session, "GET", "/staff/campaigns/new")
    assert 'name="base_rate"' in form.body
    session.roles = frozenset({ROLE_CAMPAIGN_WRITE})
    created = app.handle(session, "POST", "/staff/campaigns", campaign_form())
    assert created.status == 200
    assert len(app.office.campaigns._rows) == 1


def test_enigma_timeout_is_the_route_reason():
    app = build_app()
    session = staff()
    session.enigma_status = "timeout"
    failed = app.handle(session, "POST", "/staff/campaigns", campaign_form())
    assert "timed out" in failed.body
    assert len(app.office.campaigns._rows) == 0
    reported = outcomes(app)[-1]
    assert reported.payload["outcome"] == "failure"
    assert "timed out" in reported.payload["message"]


def test_elections_at_organisation_and_product():
    app = build_app()
    session = staff()
    saved = app.handle(session, "POST", "/staff/elections", election_form())
    assert "organisation elections were stored" in saved.body
    listed = app.handle(session, "GET", "/staff/elections")
    assert "collections_default" in listed.body
    assert 'value="collections_default" selected' in listed.body
    opened = app.handle(session, "GET", "/staff/products/open", query={"product_id": "micro"})
    assert 'name="in_duplum_trigger"' in opened.body
    product = app.handle(
        session,
        "POST",
        "/staff/products/micro/elections",
        {"recognised_at": AT, "in_duplum_trigger": "contractual_breach"},
    )
    assert "product elections for micro were stored" in product.body
    again = app.handle(session, "GET", "/staff/products/micro/elections")
    assert 'value="contractual_breach" selected' in again.body
    assert "ELECTION_CHANGED" in _types(app)


def test_compliance_requires_ncr_and_accepts_zeros():
    app = build_app()
    session = staff()
    blank = app.handle(session, "POST", "/staff/compliance", compliance_form(ncr_registration_number=""))
    assert "ncr_registration_number is required" in blank.body
    assert session.pending is not None
    app.handle(session, "POST", "/staff/acknowledge", {"nonce": nonce(blank.body)})
    zeros = app.handle(session, "POST", "/staff/compliance", compliance_form(
        ncr_registration_number="0000000", trading_name="",
    ))
    assert zeros.status == 200
    assert "0000000" in zeros.body
    assert "You can continue." in zeros.body
    stored = app.office.compliance.require(ORG)
    assert stored.ncr_registration_number == "0000000"
    assert stored.trading_name == ""
    assert stored.bank_account_number == "1234567890"
    test_number = app.handle(session, "POST", "/staff/compliance", compliance_form(
        ncr_registration_number="NCRCP0000",
    ))
    assert test_number.status == 200
    assert app.office.compliance.require(ORG).ncr_registration_number == "NCRCP0000"


def test_ceilings_store_both_scopes_and_apply_the_tighter_limit():
    app = build_app()
    session = staff()
    missing = app.handle(session, "POST", "/staff/ceilings/check", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "1000",
        "organisation_id": ORG,
    })
    assert "missing platform ceiling" in missing.body
    app.handle(session, "POST", "/staff/acknowledge", {"nonce": nonce(missing.body)})
    platform = app.handle(session, "POST", "/staff/ceilings/platform", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "10000",
    })
    assert "platform ceiling" in platform.body
    assert "100.00 rand" in platform.body
    company = app.handle(session, "POST", "/staff/ceilings/company", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "50000",
    })
    assert company.status == 200
    allowed = app.handle(session, "POST", "/staff/ceilings/check", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "10000",
        "organisation_id": ORG,
    })
    assert "within the tighter ceiling of 10000 cents" in allowed.body
    assert "Nothing was posted." in allowed.body
    over = app.handle(session, "POST", "/staff/ceilings/check", {
        "recognised_at": AT,
        "action": "lms.account.write_off",
        "amount_cents": "10001",
        "organisation_id": ORG,
    })
    assert "exceeds the operational ceiling" in over.body
    assert session.pending is not None


def test_collection_campaign_create_edit_end_and_apply():
    app = build_app()
    session = staff()
    created = app.handle(session, "POST", "/staff/collection-campaigns", collection_form(end_date=""))
    assert created.status == 200, created.body
    assert "open-ended" in created.body
    campaign_id = re.search(r"Collection campaign ([0-9a-f-]+) was stored", created.body).group(1)
    listed = app.handle(session, "GET", "/staff/collection-campaigns")
    assert campaign_id in listed.body
    assert "no list method" in listed.body
    edited = app.handle(
        session, "POST", f"/staff/collection-campaigns/{campaign_id}", collection_form(rate_reduction="0.02"),
    )
    assert edited.status == 200, edited.body
    ended = app.handle(session, "POST", f"/staff/collection-campaigns/{campaign_id}/end", {
        "recognised_at": AT,
        "end_date": "2026-10-20",
    })
    assert "now ends on 2026-10-20" in ended.body
    applied = app.handle(session, "POST", f"/staff/collection-campaigns/{campaign_id}/apply", {
        "recognised_at": AT,
        "selector": "organisation",
        "product_code": "micro",
        "loan_ids": "loan-1",
    })
    assert "matched no accounts" in applied.body
    assert "Nothing was applied." in applied.body
    kinds = _types(app)
    assert "COLLECTION_CAMPAIGN_CHANGED" in kinds
    assert "STAFF_UI_REPORTED" in kinds
    denied = staff()
    denied.roles = frozenset({ROLE_CAMPAIGN_WRITE})
    refused = app.handle(denied, "POST", "/staff/collection-campaigns", collection_form())
    assert f"does not include {COLLECTION_ROLE}" in refused.body
    assert len(app.campaigns.campaigns) == 1


def test_batch_status_reads_the_audit_route_and_reports_no_run():
    app = build_app()
    session = staff()
    app.handle(session, "POST", "/staff/campaigns", campaign_form())
    page = app.handle(session, "GET", "/staff/batch")
    assert page.status == 200
    assert "No daily-calculation batch route is registered." in page.body
    assert "Last successful run" in page.body
    assert "None recorded." in page.body
    assert "You can continue." not in page.body
    assert "accrue, capitalise, or flag a default" in page.body
    limited = staff()
    limited.roles = frozenset({COLLECTION_ROLE})
    denied = app.handle(limited, "GET", "/staff/batch")
    assert "does not include a staff role" in denied.body


def test_consumer_registration_and_notices_are_not_screens():
    app = build_app()
    session = staff()
    page = app.handle(session, "GET", "/staff/register")
    assert page.status == 404
    assert "Enigma" in page.body
    assert 'type="email"' not in page.body
    assert "password" not in page.body.lower()
    notices = app.handle(session, "GET", "/staff/collection-notices")
    assert "does not generate collection notices" in notices.body
    push = app.handle(session, "POST", "/staff/push", {})
    assert "push-provider" in push.body
    assert session.pending is not None


def test_http_session_and_campaign_confirmation():
    app = build_app()
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        home = opener.open(f"http://127.0.0.1:{port}/staff/")
        assert b"Person id" in home.read()
        roles = ",".join([
            ROLE_CAMPAIGN_WRITE,
            ROLE_ELECTIONS_WRITE,
            ROLE_COMPLIANCE_WRITE,
            ROLE_CEILING_PLATFORM_WRITE,
            ROLE_CEILING_COMPANY_WRITE,
            COLLECTION_ROLE,
        ])
        saved = opener.open(
            f"http://127.0.0.1:{port}/staff/session",
            urllib.parse.urlencode({
                "person_id": PERSON,
                "organisation_id": ORG,
                "roles": roles,
                "enigma_status": "active",
            }).encode(),
        )
        assert b"You can continue." in saved.read()
        created = opener.open(
            f"http://127.0.0.1:{port}/staff/campaigns",
            urllib.parse.urlencode(campaign_form()).encode(),
        )
        body = created.read()
        assert b'data-outcome="success"' in body
        assert b"You can continue." in body
        assert b'name="base_rate"' not in body
        continue_href = re.search(br'class="continue" href="([^"]+)"', body).group(1).decode()
        listed = opener.open(f"http://127.0.0.1:{port}{continue_href}")
        assert b"0.05" in listed.read()
    finally:
        server.shutdown()
        server.server_close()
