"""Restructure path: consent, frozen elections, balance transfer, audit."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from lms.restructure.api import dispatch
from lms.restructure.elections import freeze_elections
from lms.restructure.engine import EngineError, Refusal, SuppliedTerms
from lms.restructure.models import FreezeError
from lms.restructure.recognition import JOHANNESBURG, recognition_instant
from lms.restructure.service import HoldError, RestructureService


ORG = "org-1"
AGREEMENT = "agr-1"
STAFF = "staff-9"
PERSON = "person-1"


def elections(**overrides: object) -> dict:
    row: dict = {
        "vat_on_rand_maxima": "inclusive",
        "late_disbursement": "keep_instalment",
        "partial_prepayment": "shorten_term",
        "interest_on_deferred_initiation": "none",
        "repo_rate_fall": "contract_rate",
        "in_duplum_trigger": "collections_default",
        "residual_write_off_threshold_cents": 10_000,
        "campaign_fall_away_choice": "does_not_fall_away",
        "campaign_fall_away_trigger": None,
    }
    row.update(overrides)
    return row


def identity(**overrides: object) -> dict:
    row = {
        "full_name": "Amina Naidoo",
        "id_number": "8001015009087",
        "service_address": "1 Main Road, Johannesburg",
    }
    row.update(overrides)
    return row


class ScriptedEngine:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def supply(self, facts: object) -> object:
        self.calls += 1
        self.facts = facts
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def terms(**overrides: object) -> SuppliedTerms:
    values: dict = {
        "contractual_periodic_rate_bps": 400,
        "term_count": 18,
        "payment_frequency": "monthly",
        "instalment_cents": 8_000,
        "application_number": "APP-00000002",
    }
    values.update(overrides)
    return SuppliedTerms(**values)


def service_with(result: object | None = None) -> tuple[RestructureService, ScriptedEngine]:
    engine = ScriptedEngine(terms() if result is None else result)
    service = RestructureService(engine)
    service.hold_agreement(
        agreement_id=AGREEMENT,
        organisation_id=ORG,
        person_id=PERSON,
        outstanding_balance_cents=150_000,
        contractual_instalment_cents=10_000,
        term_count=12,
        payment_frequency="monthly",
        contractual_periodic_rate_bps=500,
        application_number="APP-00000001",
        frozen_full_name="Amina Naidoo",
        frozen_id_number="8001015009087",
        frozen_service_address="1 Main Road, Johannesburg",
    )
    return service, engine


def headers(**overrides: str) -> dict[str, str]:
    row = {
        "X-Enigma-Person-Id": STAFF,
        "X-Enigma-Organisation-Id": ORG,
        "X-Enigma-Status": "active",
        "X-Enigma-Roles": "lms.staff",
    }
    row.update(overrides)
    return row


def body(**overrides: object) -> dict:
    row: dict = {
        "recognised_at": "2026-10-28T15:30:00+02:00",
        "client_consent": True,
        "consent_date": "2026-10-28",
        "elections": elections(),
        "identity": identity(),
        "kind": "restructure",
    }
    row.update(overrides)
    return row


def post(service: RestructureService, payload: dict | None = None, **header_overrides: str):
    return dispatch(
        service,
        "POST",
        f"/v1/organisations/{ORG}/agreements/{AGREEMENT}/restructure",
        body() if payload is None else payload,
        headers(**header_overrides),
    )


def test_recognition_instant_is_midnight_johannesburg() -> None:
    afternoon = datetime(2026, 10, 28, 15, 30, tzinfo=JOHANNESBURG)
    instant = recognition_instant(afternoon)
    assert instant == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)
    assert instant.utcoffset() == JOHANNESBURG.utcoffset(instant)
    rolled = recognition_instant(datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc))
    assert rolled == datetime(2026, 10, 29, 0, 0, tzinfo=JOHANNESBURG)
    assert recognition_instant(date(2026, 10, 28)) == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)


def test_restructure_stores_engine_terms_and_transfers_balance() -> None:
    service, engine = service_with(
        terms(instalment_cents=12_345, contractual_periodic_rate_bps=1, term_count=99)
    )
    status, payload = post(service)
    assert status == 200
    assert payload["outcome"] == "success"
    assert "Restructure confirmed" in payload["confirmation"]
    assert payload["contractual_instalment_cents"] == 12_345
    assert payload["contractual_periodic_rate_bps"] == 1
    assert payload["term_count"] == 99
    assert payload["transferred_balance_cents"] == 150_000
    assert payload["recognised_at"] == "2026-10-28T00:00:00+02:00"
    assert payload["recognition_date"] == "2026-10-28"
    assert payload["client_consent"] is True
    assert payload["consent_date"] == "2026-10-28"
    assert payload["application_number"] == "APP-00000002"
    assert isinstance(payload["transferred_balance_cents"], int)
    assert isinstance(payload["contractual_instalment_cents"], int)
    assert engine.calls == 1

    original = service.agreements[AGREEMENT]
    created = service.agreements[payload["new_agreement_id"]]
    assert original.status == "restructured"
    assert original.outstanding_balance_cents == 0
    assert original.restructured_to_agreement_id == created.agreement_id
    assert original.contractual_instalment_cents == 10_000
    assert created.original_agreement_id == AGREEMENT
    assert created.outstanding_balance_cents == 150_000
    assert created.contractual_instalment_cents == 12_345
    assert created.client_consent is True
    assert created.consent_date == date(2026, 10, 28)
    assert created.elections == freeze_elections(elections())
    assert created.status == "active"
    assert created.recognised_at == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)


def test_elections_and_identity_stay_frozen() -> None:
    service, _engine = service_with()
    _status, payload = post(service)
    created = service.agreements[payload["new_agreement_id"]]
    original = service.agreements[AGREEMENT]
    for agreement, field in (
        (created, "frozen_full_name"),
        (created, "frozen_id_number"),
        (created, "frozen_service_address"),
        (created, "elections"),
        (created, "contractual_instalment_cents"),
        (created, "term_count"),
        (created, "client_consent"),
        (original, "frozen_service_address"),
        (original, "contractual_instalment_cents"),
    ):
        with pytest.raises(FreezeError):
            setattr(agreement, field, "rewritten")


def test_utc_evening_uses_the_johannesburg_calendar_day() -> None:
    service, _engine = service_with()
    status, payload = post(service, body(recognised_at="2026-10-28T22:30:00+00:00"))
    assert status == 200
    assert payload["recognition_date"] == "2026-10-29"
    assert payload["recognised_at"] == "2026-10-29T00:00:00+02:00"
    row = service.audit.last_for_agreement(ORG, AGREEMENT)
    assert row is not None
    assert row.occurred_at == datetime(2026, 10, 29, 0, 0, tzinfo=JOHANNESBURG)
    assert row.actor_person_id == STAFF
    assert row.outcome == "success"


def test_missing_consent_fails_closed_and_does_not_call_the_engine() -> None:
    service, engine = service_with()
    payload = body()
    del payload["client_consent"]
    status, response = post(service, payload)
    assert status == 422
    assert response == {
        "outcome": "failure",
        "reason": "missing client consent",
        "recognition_date": "2026-10-28",
        "recognised_at": "2026-10-28T00:00:00+02:00",
    }
    assert engine.calls == 0
    assert service.agreements[AGREEMENT].status == "active"
    assert service.agreements[AGREEMENT].outstanding_balance_cents == 150_000
    assert len(service.agreements) == 1
    row = service.audit.last_for_agreement(ORG, AGREEMENT)
    assert row is not None
    assert row.outcome == "failure"
    assert row.reason == "missing client consent"
    assert row.event_type == "RESTRUCTURE_FAILED"


def test_null_consent_and_refused_consent_and_missing_date() -> None:
    service, engine = service_with()
    status, response = post(service, body(client_consent=None))
    assert (status, response["reason"]) == (422, "missing client consent")
    status, response = post(service, body(client_consent=False))
    assert (status, response["reason"]) == (422, "client consent is required to restructure")
    status, response = post(service, body(client_consent="true"))
    assert (status, response["reason"]) == (422, "client consent must be a boolean")
    payload = body()
    del payload["consent_date"]
    status, response = post(service, payload)
    assert (status, response["reason"]) == (422, "missing client consent date")
    status, response = post(service, body(consent_date="28 October 2026"))
    assert (status, response["reason"]) == (422, "consent date must be YYYY-MM-DD")
    assert engine.calls == 0


@pytest.mark.parametrize(
    "field",
    [
        "vat_on_rand_maxima",
        "late_disbursement",
        "partial_prepayment",
        "interest_on_deferred_initiation",
        "repo_rate_fall",
        "in_duplum_trigger",
        "residual_write_off_threshold_cents",
        "campaign_fall_away_choice",
    ],
)
def test_each_missing_election_fails_closed(field: str) -> None:
    service, engine = service_with()
    row = elections()
    row[field] = None
    status, response = post(service, body(elections=row))
    assert status == 422
    assert response["reason"] == f"missing election: {field}"
    assert engine.calls == 0
    assert service.agreements[AGREEMENT].status == "active"


def test_invalid_election_and_conditional_trigger() -> None:
    service, _engine = service_with()
    status, response = post(
        service, body(elections=elections(vat_on_rand_maxima="sometimes"))
    )
    assert status == 422
    assert response["reason"] == (
        "invalid election: vat_on_rand_maxima. Expected exclusive or inclusive"
    )
    status, response = post(
        service,
        body(
            elections=elections(
                campaign_fall_away_choice="falls_away_on_default",
                campaign_fall_away_trigger=None,
            )
        ),
    )
    assert response["reason"] == "missing election: campaign_fall_away_trigger"
    status, response = post(
        service,
        body(elections=elections(campaign_fall_away_trigger="contractual_breach")),
    )
    assert response["reason"] == (
        "invalid election: campaign_fall_away_trigger. "
        "A choice of does_not_fall_away stores no trigger"
    )
    status, response = post(
        service,
        body(elections=elections(residual_write_off_threshold_cents=10_000.0)),
    )
    assert response["reason"] == "residual_write_off_threshold_cents must be integer cents"


def test_fall_away_choice_freezes_its_trigger() -> None:
    service, _engine = service_with()
    status, payload = post(
        service,
        body(
            elections=elections(
                campaign_fall_away_choice="falls_away_on_default",
                campaign_fall_away_trigger="contractual_breach",
            )
        ),
    )
    assert status == 200
    created = service.agreements[payload["new_agreement_id"]]
    assert created.elections is not None
    assert created.elections.campaign_fall_away_choice == "falls_away_on_default"
    assert created.elections.campaign_fall_away_trigger == "contractual_breach"


def test_missing_and_mismatched_identity() -> None:
    service, engine = service_with()
    status, response = post(service, body(identity={"full_name": "Amina Naidoo"}))
    assert response["reason"] == "missing identity: ID number"
    status, response = post(service, body(identity=identity(service_address="  ")))
    assert response["reason"] == "missing identity: service address"
    status, response = post(service, body(identity=identity(full_name="Other Person")))
    assert response["reason"] == (
        "identity does not match the identity frozen on the original agreement: name"
    )
    assert engine.calls == 0
    assert status == 422


def test_engine_failures_leave_the_agreement_unchanged() -> None:
    service, _engine = service_with(Refusal("timeout"))
    status, response = post(service)
    assert (status, response["reason"]) == (503, "decision engine timeout")
    assert service.agreements[AGREEMENT].status == "active"
    assert service.agreements[AGREEMENT].outstanding_balance_cents == 150_000

    service, _engine = service_with(Refusal("ambiguous"))
    status, response = post(service)
    assert (status, response["reason"]) == (503, "decision engine response is ambiguous")

    service, _engine = service_with(Refusal("unavailable"))
    status, response = post(service)
    assert (status, response["reason"]) == (503, "decision engine unavailable")

    service, _engine = service_with(Refusal("rejected", "affordability"))
    status, response = post(service)
    assert status == 422
    assert response["reason"] == "decision engine rejected the restructure: affordability"

    service, _engine = service_with(EngineError("timeout"))
    status, response = post(service)
    assert response["reason"] == "decision engine timeout"

    service, _engine = service_with(RuntimeError("socket hung up"))
    status, response = post(service)
    assert (status, response["reason"]) == (503, "decision engine response is ambiguous")
    assert service.agreements[AGREEMENT].status == "active"


def test_non_integer_engine_amounts_fail_closed() -> None:
    service, _engine = service_with(terms(instalment_cents=True))  # type: ignore[arg-type]
    status, response = post(service)
    assert status == 422
    assert "integer cents" in response["reason"]
    service, _engine = service_with(terms(instalment_cents=10.5))  # type: ignore[arg-type]
    _status, response = post(service)
    assert "integer cents" in response["reason"]
    service, _engine = service_with(terms(contractual_periodic_rate_bps=-1))
    _status, response = post(service)
    assert response["reason"] == (
        "decision engine did not supply a usable term: contractual rate cannot be negative"
    )


def test_rate_only_change_is_a_collection_campaign() -> None:
    service, _engine = service_with(
        terms(
            contractual_periodic_rate_bps=100,
            term_count=12,
            instalment_cents=10_000,
            payment_frequency="monthly",
        )
    )
    status, response = post(service)
    assert status == 422
    assert response["reason"] == (
        "a rate change that does not change the contractual term or instalment "
        "is a collection campaign"
    )
    assert service.agreements[AGREEMENT].status == "active"
    assert len(service.agreements) == 1


def test_unchanged_terms_and_frequency_only_change() -> None:
    service, _engine = service_with(
        terms(contractual_periodic_rate_bps=500, term_count=12, instalment_cents=10_000)
    )
    status, response = post(service)
    assert response["reason"] == "no change to the contractual term or the contractual instalment"
    service, _engine = service_with(
        terms(
            contractual_periodic_rate_bps=500,
            term_count=12,
            instalment_cents=10_000,
            payment_frequency="weekly",
        )
    )
    status, response = post(service)
    assert status == 422
    assert response["reason"] == (
        "payment frequency changed and the term count and instalment did not. "
        "Whether that change is a restructure is not locked"
    )
    assert service.agreements[AGREEMENT].outstanding_balance_cents == 150_000


def test_instalment_change_stores_the_supplied_rate_and_term() -> None:
    service, _engine = service_with(
        terms(term_count=12, instalment_cents=9_500, payment_frequency="weekly")
    )
    status, payload = post(service)
    assert status == 200
    assert payload["term_count"] == 12
    assert payload["contractual_instalment_cents"] == 9_500
    assert payload["payment_frequency"] == "weekly"
    created = service.agreements[payload["new_agreement_id"]]
    assert created.contractual_periodic_rate_bps == 400


def test_out_of_scope_kinds_do_not_transfer() -> None:
    expectations = {
        "early_settlement": "early settlement is out of scope for the restructure path",
        "collection_campaign": "a collection campaign is out of scope for the restructure path",
        "settlement_readvance": "settlement re-advance is out of scope for the restructure path",
        "top_up": "kind top_up is not a restructure",
    }
    for kind, reason in expectations.items():
        service, engine = service_with()
        status, response = post(service, body(kind=kind))
        assert (status, response["reason"]) == (422, reason)
        assert engine.calls == 0
        assert service.agreements[AGREEMENT].status == "active"


def test_caller_supplied_terms_are_refused() -> None:
    service, engine = service_with()
    payload = body()
    payload["instalment_cents"] = 1
    status, response = post(service, payload)
    assert status == 422
    assert response["reason"] == (
        "the decision engine supplies the rate, term, and instalment. "
        "Do not send them on the restructure request"
    )
    assert engine.calls == 0


def test_enrolment_failures() -> None:
    service, engine = service_with()
    status, response = post(service, **{"X-Enigma-Person-Id": "  "})
    assert (status, response["reason"]) == (403, "missing staff identity")
    assert engine.calls == 0
    row = service.audit.last_for_agreement(ORG, AGREEMENT)
    assert row is not None and row.actor_person_id is None

    status, response = post(service, **{"X-Enigma-Status": "suspended"})
    assert (status, response["reason"]) == (403, "Enigma enrolment is suspended")
    status, response = post(service, **{"X-Enigma-Status": "timeout"})
    assert (status, response["reason"]) == (503, "Enigma timeout")
    status, response = post(service, **{"X-Enigma-Status": "ambiguous"})
    assert (status, response["reason"]) == (503, "Enigma status is ambiguous")
    status, response = post(service, **{"X-Enigma-Organisation-Id": "other-org"})
    assert (status, response["reason"]) == (422, "organisation does not match the request")
    assert service.agreements[AGREEMENT].status == "active"


def test_naive_timestamp_is_reported_and_not_audited() -> None:
    service, engine = service_with()
    status, response = post(service, body(recognised_at="2026-10-28T15:30:00"))
    assert status == 422
    assert response["reason"] == (
        "recognition date must be a calendar date or a timezone-aware instant"
    )
    assert "recognised_at" not in response
    assert engine.calls == 0
    assert service.audit.for_organisation(ORG) == ()


def test_second_restructure_does_not_transfer_again() -> None:
    service, _engine = service_with()
    status, first = post(service)
    assert status == 200
    status, second = post(service)
    assert (status, second["reason"]) == (422, "agreement is already restructured")
    assert service.agreements[AGREEMENT].outstanding_balance_cents == 0
    created = [
        agreement
        for agreement in service.agreements.values()
        if agreement.original_agreement_id == AGREEMENT
    ]
    assert len(created) == 1
    assert created[0].outstanding_balance_cents == 150_000
    assert first["new_agreement_id"] == created[0].agreement_id


def test_zero_balance_zero_rate_and_zero_instalment_are_stored() -> None:
    service, _engine = service_with(
        terms(contractual_periodic_rate_bps=0, instalment_cents=0, term_count=6)
    )
    service.agreements[AGREEMENT].outstanding_balance_cents = 0
    status, payload = post(service)
    assert status == 200
    assert payload["transferred_balance_cents"] == 0
    assert payload["contractual_instalment_cents"] == 0
    assert payload["contractual_periodic_rate_bps"] == 0
    created = service.agreements[payload["new_agreement_id"]]
    assert created.outstanding_balance_cents == 0
    assert created.contractual_instalment_cents == 0


def test_audit_can_be_read_by_account_and_by_organisation() -> None:
    service, _engine = service_with()
    post(service, body(client_consent=False))
    post(service)
    status, org_audit = dispatch(
        service,
        "GET",
        f"/v1/organisations/{ORG}/restructure/audit",
        None,
        headers(),
    )
    assert status == 200
    assert [row["outcome"] for row in org_audit["rows"]] == ["failure", "success"]
    assert org_audit["rows"][0]["actor_person_id"] == STAFF
    assert org_audit["rows"][0]["roles"] == ["lms.staff"]
    assert org_audit["rows"][1]["occurred_at"] == "2026-10-28T00:00:00+02:00"
    assert org_audit["rows"][1]["payload"]["transferred_balance_cents"] == 150_000

    status, account = dispatch(
        service,
        "GET",
        f"/v1/organisations/{ORG}/agreements/{AGREEMENT}/restructure",
        None,
        headers(),
    )
    assert status == 200
    assert account["recorded"] is True
    assert account["outcome"] == "success"
    assert account["confirmation"].startswith("Restructure confirmed")
    new_id = org_audit["rows"][1]["payload"]["new_agreement_id"]
    status, linked = dispatch(
        service,
        "GET",
        f"/v1/organisations/{ORG}/agreements/{new_id}/restructure/audit",
        None,
        headers(),
    )
    assert status == 200
    assert linked["rows"][0]["outcome"] == "success"


def test_status_before_any_restructure() -> None:
    service, _engine = service_with()
    status, payload = dispatch(
        service,
        "GET",
        f"/v1/organisations/{ORG}/agreements/{AGREEMENT}/restructure",
        None,
        headers(),
    )
    assert status == 200
    assert payload["recorded"] is False
    assert payload["reason"] == "no restructure has been recorded for this agreement"


def test_unknown_agreement_and_inactive_status() -> None:
    service, engine = service_with()
    status, response = dispatch(
        service,
        "POST",
        f"/v1/organisations/{ORG}/agreements/missing/restructure",
        body(),
        headers(),
    )
    assert (status, response["reason"]) == (422, "agreement not found")
    assert engine.calls == 0
    service.agreements[AGREEMENT].status = "written_off"
    status, response = post(service)
    assert response["reason"] == "agreement status written_off cannot be restructured"


def test_hold_rejects_non_integer_cents() -> None:
    service, _engine = service_with()
    with pytest.raises(HoldError, match="integer cents"):
        service.hold_agreement(
            agreement_id="agr-2",
            organisation_id=ORG,
            person_id=PERSON,
            outstanding_balance_cents=1.5,  # type: ignore[arg-type]
            contractual_instalment_cents=10,
            term_count=1,
            payment_frequency="monthly",
            contractual_periodic_rate_bps=0,
            application_number="APP-00000009",
            frozen_full_name="Amina Naidoo",
            frozen_id_number="8001015009087",
            frozen_service_address="1 Main Road, Johannesburg",
        )


def test_unknown_route() -> None:
    service, _engine = service_with()
    status, response = dispatch(service, "POST", "/v1/restructure", body(), headers())
    assert (status, response["reason"]) == (404, "route not found")
