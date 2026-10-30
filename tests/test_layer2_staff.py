"""Layer 2 staff commands. Statement generation is not on this path."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from lms.staff.api import dispatch
from lms.staff.authority import (
    ROLE_CAMPAIGN_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_COMPLIANCE_WRITE,
    ROLE_ELECTIONS_WRITE,
    StaffActor,
)
from lms.staff.elections import ElectionValues, resolve_elections
from lms.staff.service import StaffOffice
from lms_config.exceptions import CalculationInputError
from lms_config.locked import campaign_rate, resolve_residual_threshold_cents


ORG = "org-cape"
PERSON = "person-staff"
AT = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
ROLES = ",".join(
    [
        ROLE_CAMPAIGN_WRITE,
        ROLE_ELECTIONS_WRITE,
        ROLE_COMPLIANCE_WRITE,
        ROLE_CEILING_PLATFORM_WRITE,
        ROLE_CEILING_COMPANY_WRITE,
    ]
)


def headers(roles: str = ROLES, status: str = "active", organisation: str = ORG) -> dict:
    return {
        "X-Enigma-Person-Id": PERSON,
        "X-Enigma-Organisation-Id": organisation,
        "X-Enigma-Roles": roles,
        "X-Enigma-Status": status,
    }


def campaign_body(**overrides) -> dict:
    body = {
        "recognised_at": AT.isoformat(),
        "product_id": None,
        "start_date": "2026-10-01",
        "end_date": "2026-10-31",
        "base_rate": "0.05",
        "discount_rate": "0.02",
        "fall_away_choice": "falls_away_on_default",
        "fall_away_trigger": "contractual_breach",
        "initiation_fee_discount_cents": 0,
        "service_fee_discount_cents": 0,
    }
    body.update(overrides)
    return body


def elections(**overrides) -> dict:
    body = {
        "recognised_at": AT.isoformat(),
        "vat_on_rand_maxima": "exclusive",
        "late_disbursement": "keep_instalment",
        "partial_prepayment": "shorten_term",
        "interest_on_deferred_initiation": "none",
        "repo_rate_fall": "contract_rate",
        "in_duplum_trigger": "collections_default",
        "residual_write_off_threshold_cents": 10_000,
        "campaign_fall_away_choice": "does_not_fall_away",
        "campaign_fall_away_trigger": None,
    }
    body.update(overrides)
    return body


def compliance_body(**overrides) -> dict:
    body = {
        "recognised_at": AT.isoformat(),
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


def test_net_rate_calls_campaign_rate_and_floors_when_that_call_refuses():
    assert campaign_rate(Decimal("0.05"), Decimal("0.02")) == Decimal("0.03")
    with pytest.raises(CalculationInputError):
        campaign_rate(Decimal("0.05"), Decimal("0.08"))
    office = StaffOffice()
    created = office.create_campaign(
        _actor(),
        AT,
        product_id=None,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0.08"),
        fall_away_choice="falls_away_on_default",
        fall_away_trigger="collections_default",
        initiation_fee_discount_cents=0,
        service_fee_discount_cents=0,
    )
    assert created.net_rate == Decimal(0)
    assert created.base_rate == Decimal("0.05")
    assert created.discount_rate == Decimal("0.08")


def test_fee_discount_cannot_make_a_fee_negative():
    office = StaffOffice()
    status, created = dispatch(office, "POST", f"/v1/staff/organisations/{ORG}/campaigns", campaign_body(
        initiation_fee_discount_cents=5_000,
        service_fee_discount_cents=0,
    ), headers())
    assert status == 200
    preview = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns/{created['campaign_id']}/fee-preview",
        {"kind": "initiation", "ex_vat_cents": 1_000, "vat_rate": "0.15"},
        headers(),
    )
    assert preview == (200, {"ex_vat_cents": 0, "vat_cents": 0, "total_cents": 0})
    refused = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(service_fee_discount_cents=-1),
        headers(),
    )
    assert refused[0] == 422


def test_campaign_routes_qualify_by_recognition_date_and_do_not_reprice():
    office = StaffOffice()
    status, created = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(end_date="2026-10-28"),
        headers(),
    )
    assert status == 200
    assert created["net_rate"] == "0.03"
    campaign_id = created["campaign_id"]

    # 22:30 UTC on 28 October is 00:30 on 29 October in Johannesburg, after the end date.
    late = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": "2026-10-28T22:30:00+00:00",
            "application_number": "APP-1",
            "supplied_rate": "0.99",
            "credit_life_premium_cents": 12_345,
            "maturity_date": "2027-04-30",
            "product_id": "personal",
        },
        headers(),
    )
    assert late[0] == 200, late[1]
    assert late[1]["recognition_date"] == "2026-10-29"
    assert late[1]["campaign_id"] is None

    extended = dispatch(
        office,
        "PATCH",
        f"/v1/staff/organisations/{ORG}/campaigns/{campaign_id}",
        campaign_body(end_date="2026-10-31"),
        headers(),
    )
    assert extended[0] == 200
    assert office.intakes.get(late[1]["intake_id"]).campaign_id is None

    covered = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": "2026-10-31T21:00:00+00:00",
            "application_number": "APP-2",
            "supplied_rate": "0.99",
            "credit_life_premium_cents": 12_345,
            "maturity_date": "2027-04-30",
        },
        headers(),
    )
    assert covered[0] == 200
    assert covered[1]["recognition_date"] == "2026-10-31"
    assert covered[1]["campaign_id"] == campaign_id
    assert covered[1]["supplied_rate"] == "0.99"
    assert covered[1]["campaign_net_rate"] == "0.03"
    assert covered[1]["credit_life_premium_cents"] == 12_345
    assert covered[1]["maturity_date"] == "2027-04-30"

    edited = dispatch(
        office,
        "PATCH",
        f"/v1/staff/organisations/{ORG}/campaigns/{campaign_id}",
        campaign_body(discount_rate="0.05", end_date="2026-11-15"),
        headers(),
    )
    assert edited[0] == 200
    assert Decimal(edited[1]["net_rate"]) == 0
    assert edited[1]["version"] == 3
    stored = office.intakes.get(covered[1]["intake_id"])
    assert stored.campaign_net_rate == Decimal("0.03")
    assert stored.supplied_rate == Decimal("0.99")
    assert stored.campaign_discount_rate == Decimal("0.02")

    ended = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns/{campaign_id}/end",
        {"recognised_at": "2026-10-20T10:00:00+00:00"},
        headers(),
    )
    assert ended[0] == 200
    assert ended[1]["end_date"] == "2026-10-20"
    assert office.intakes.get(covered[1]["intake_id"]).campaign_id == campaign_id

    on_the_end_date = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": "2026-10-20T06:00:00+00:00",
            "application_number": "APP-END",
            "supplied_rate": "0.04",
            "credit_life_premium_cents": 0,
            "maturity_date": "2027-01-20",
        },
        headers(),
    )
    assert on_the_end_date[1]["recognition_date"] == "2026-10-20"
    assert on_the_end_date[1]["campaign_id"] == campaign_id

    after = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": "2026-10-21T08:00:00+00:00",
            "application_number": "APP-3",
            "supplied_rate": "0.04",
            "credit_life_premium_cents": 0,
        },
        headers(),
    )
    assert after[1]["campaign_id"] is None
    on_end = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": "2026-10-20T23:30:00+00:00",
            "application_number": "APP-4",
            "supplied_rate": "0.04",
            "credit_life_premium_cents": 0,
        },
        headers(),
    )
    assert on_end[1]["recognition_date"] == "2026-10-21"
    assert on_end[1]["campaign_id"] is None


def test_two_campaigns_on_the_same_day_store_nothing():
    office = StaffOffice()
    assert dispatch(office, "POST", f"/v1/staff/organisations/{ORG}/campaigns", campaign_body(), headers())[0] == 200
    assert dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(product_id="personal"),
        headers(),
    )[0] == 200
    status, body = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/decision-intake",
        {
            "recognised_at": AT.isoformat(),
            "application_number": "APP-BOTH",
            "supplied_rate": "0.05",
            "credit_life_premium_cents": 100,
            "product_id": "personal",
        },
        headers(),
    )
    assert status == 422
    assert body["code"] == "campaign-ambiguous"
    assert office.intakes.list(ORG) == ()


def test_elections_fail_closed_and_product_override_wins():
    office = StaffOffice()
    missing = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/elections/resolve",
        {},
        headers(),
    )
    assert missing[0] == 422
    assert resolve_residual_threshold_cents(None, None) == 10_000
    assert resolve_residual_threshold_cents(0, None) == 0
    filled = resolve_elections(
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
        None,
    )
    assert filled.residual_write_off_threshold_cents == 10_000

    assert dispatch(office, "PUT", f"/v1/staff/organisations/{ORG}/elections", elections(), headers())[0] == 200
    resolved = dispatch(office, "POST", f"/v1/staff/organisations/{ORG}/elections/resolve", {}, headers())
    assert resolved[0] == 200
    assert resolved[1]["residual_write_off_threshold_cents"] == 10_000
    assert resolved[1]["vat_on_rand_maxima"] == "exclusive"

    override = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/products/personal/elections",
        elections(vat_on_rand_maxima="inclusive", residual_write_off_threshold_cents=0),
        headers(),
    )
    assert override[0] == 200
    product = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/elections/resolve",
        {"product_id": "personal"},
        headers(),
    )
    assert product[1]["vat_on_rand_maxima"] == "inclusive"
    assert product[1]["residual_write_off_threshold_cents"] == 0
    assert product[1]["repo_rate_fall"] == "contract_rate"

    listed = dispatch(office, "GET", f"/v1/staff/organisations/{ORG}/elections", {}, headers())
    assert listed[1]["organisation"]["vat_on_rand_maxima"] == "exclusive"
    assert listed[1]["products"][0]["product_id"] == "personal"


def test_unset_fall_away_trigger_is_refused():
    office = StaffOffice()
    status, body = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(fall_away_trigger=None),
        headers(),
    )
    assert status == 422
    assert "trigger" in body["message"]
    kept = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(fall_away_choice="does_not_fall_away", fall_away_trigger="contractual_breach"),
        headers(),
    )
    assert kept[0] == 422


def test_compliance_requires_ncr_and_accepts_zeros():
    office = StaffOffice()
    blank = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/compliance",
        compliance_body(ncr_registration_number="   "),
        headers(),
    )
    assert blank[0] == 422
    missing_phone = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/compliance",
        compliance_body(telephone=""),
        headers(),
    )
    assert missing_phone[0] == 422
    zeros = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/compliance",
        compliance_body(ncr_registration_number="0000000"),
        headers(),
    )
    assert zeros[0] == 200
    assert zeros[1]["ncr_registration_number"] == "0000000"
    read = dispatch(office, "GET", f"/v1/staff/organisations/{ORG}/compliance", {}, headers())
    assert read[1]["bank_account_number"] == "1234567890"


def test_ceilings_use_the_tighter_amount_and_stop_without_a_platform_row():
    office = StaffOffice()
    denied = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.write_off", "amount_cents": 1, "organisation_id": ORG},
        headers(),
    )
    assert denied[0] == 422
    assert denied[1]["code"] == "platform-ceiling-missing"

    platform = dispatch(
        office,
        "PUT",
        "/v1/staff/ceilings/platform",
        {"recognised_at": AT.isoformat(), "action": "lms.account.write_off", "amount_cents": 1_000_000},
        headers(),
    )
    assert platform[0] == 200
    assert platform[1]["scope"] == "platform"
    company = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/ceilings",
        {"recognised_at": AT.isoformat(), "action": "lms.account.write_off", "amount_cents": 100_000},
        headers(),
    )
    assert company[1]["amount_cents"] == 100_000
    allowed = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.write_off", "amount_cents": 100_000, "organisation_id": ORG},
        headers(),
    )
    assert allowed[0] == 200
    assert allowed[1]["limit_cents"] == 100_000
    over = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.write_off", "amount_cents": 100_001, "organisation_id": ORG},
        headers(),
    )
    assert over[0] == 403

    higher = dispatch(
        office,
        "PUT",
        f"/v1/staff/organisations/{ORG}/ceilings",
        {"recognised_at": AT.isoformat(), "action": "lms.account.write_off", "amount_cents": 5_000_000},
        headers(),
    )
    assert higher[1]["version"] == 2
    still = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.write_off", "amount_cents": 1_000_000, "organisation_id": ORG},
        headers(),
    )
    assert still[0] == 200
    assert still[1]["limit_cents"] == 1_000_000
    assert still[1]["company_cents"] == 5_000_000

    other = dispatch(
        office,
        "PUT",
        "/v1/staff/ceilings/platform",
        {"recognised_at": AT.isoformat(), "action": "lms.account.settle", "amount_cents": 0},
        headers(),
    )
    assert other[0] == 200
    zero_ok = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.settle", "amount_cents": 0, "organisation_id": ORG},
        headers(),
    )
    assert zero_ok[0] == 200
    zero_over = dispatch(
        office,
        "POST",
        "/v1/staff/ceilings/apply",
        {"action": "lms.account.settle", "amount_cents": 1, "organisation_id": ORG},
        headers(),
    )
    assert zero_over[0] == 403


def test_audit_records_the_enigma_person_and_the_johannesburg_day():
    office = StaffOffice()
    dispatch(office, "POST", f"/v1/staff/organisations/{ORG}/campaigns", campaign_body(
        recognised_at="2026-10-28T22:30:00+00:00",
    ), headers())
    status, body = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/audit",
        {},
        headers() | {"X-From": "2026-10-29", "X-To": "2026-10-29"},
    )
    assert status == 200
    assert body["verified"] is True
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["enigma_person_id"] == PERSON
    assert row["event_type"] == "CAMPAIGN_CREATED"
    assert row["recognition_date"] == "2026-10-29"
    assert row["payload"]["after"]["base_rate"] == "0.05"
    missed = dispatch(
        office,
        "GET",
        f"/v1/staff/organisations/{ORG}/audit",
        {},
        headers() | {"X-From": "2026-10-28", "X-To": "2026-10-28"},
    )
    assert missed[1]["rows"] == []


def test_wrong_role_and_enigma_failures_stop_the_command():
    office = StaffOffice()
    wrong = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(),
        headers(roles=ROLE_ELECTIONS_WRITE),
    )
    assert wrong[0] == 403
    assert office.campaigns.list(ORG) == ()
    suspended = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(),
        headers(status="suspended"),
    )
    assert suspended[0] == 403
    timeout = dispatch(
        office,
        "POST",
        f"/v1/staff/organisations/{ORG}/campaigns",
        campaign_body(),
        headers(status="timeout"),
    )
    assert timeout[0] == 503
    other_org = dispatch(
        office,
        "POST",
        "/v1/staff/organisations/org-other/campaigns",
        campaign_body(),
        headers(),
    )
    assert other_org[0] == 403


def test_staff_package_does_not_import_statements():
    root = Path(__file__).resolve().parents[1] / "src" / "lms" / "staff"
    for path in root.glob("*.py"):
        assert "lms.statements" not in path.read_text()


def test_company_ceiling_role_cannot_write_the_platform_row():
    office = StaffOffice()
    status, _body = dispatch(
        office,
        "PUT",
        "/v1/staff/ceilings/platform",
        {"recognised_at": AT.isoformat(), "action": "lms.account.write_off", "amount_cents": 1},
        headers(roles=ROLE_CEILING_COMPANY_WRITE),
    )
    assert status == 403
    assert office.ceilings.platform("lms.account.write_off") is None


def _actor() -> StaffActor:
    return StaffActor(PERSON, ORG, frozenset(ROLES.split(",")), "active")


def test_election_values_reject_an_unknown_code():
    office = StaffOffice()
    with pytest.raises(CalculationInputError):
        office.elections.put_organisation(
            ORG,
            ElectionValues(vat_on_rand_maxima="sometimes"),
        )
