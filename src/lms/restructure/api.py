"""HTTP-shaped restructure routes.

Success returns a confirmation. Failure returns a specific reason. Both are
written to the audit log by the service when the recognition date is known.
"""

from __future__ import annotations

from datetime import date, datetime

from lms.restructure.audit import AuditRecord
from lms.restructure.service import RestructureResult, RestructureService, StatusView


def dispatch(
    service: RestructureService,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
) -> tuple[int, dict]:
    body = dict(body or {})
    headers = {
        str(key): "" if value is None else str(value) for key, value in (headers or {}).items()
    }
    parts = [part for part in path.split("/") if part]
    try:
        organisation_id, agreement_id, action = _route(method.upper(), parts)
    except _RouteError as exc:
        return exc.status, {"outcome": "failure", "reason": exc.reason}
    header_org = headers.get("X-Enigma-Organisation-Id", "").strip()
    if action != "restructure":
        if not header_org:
            return 403, {"outcome": "failure", "reason": "missing organisation"}
        if header_org != organisation_id:
            return 422, {"outcome": "failure", "reason": "organisation does not match the request"}
    if action == "audit-organisation":
        rows = service.audit_for_organisation(organisation_id)
        return 200, {"outcome": "success", "rows": [_row(row) for row in rows]}
    if action == "audit-agreement":
        rows = service.audit_for_agreement(organisation_id, agreement_id or "")
        return 200, {
            "outcome": "success",
            "agreement_id": agreement_id,
            "rows": [_row(row) for row in rows],
        }
    if action == "status":
        view = service.last_status(organisation_id, agreement_id or "")
        return view.http_status, _status(view)
    if action == "restructure":
        result = service.restructure(
            organisation_id=organisation_id,
            agreement_id=agreement_id or "",
            actor_person_id=headers.get("X-Enigma-Person-Id"),
            actor_status=headers.get("X-Enigma-Status"),
            actor_roles=_roles(headers.get("X-Enigma-Roles", "")),
            recognised_at=_recognised_at(body),
            client_consent=body.get("client_consent"),
            consent_present="client_consent" in body,
            consent_date=_consent_date(body),
            elections=body.get("elections"),
            identity=body.get("identity"),
            kind=_kind(body),
            caller_term_fields=frozenset(body),
            header_organisation=header_org,
        )
        return result.http_status, _result(result)
    return 404, {"outcome": "failure", "reason": "route not found"}


class _RouteError(Exception):
    def __init__(self, reason: str, status: int) -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


def _route(method: str, parts: list[str]) -> tuple[str, str | None, str]:
    if (
        method == "GET"
        and len(parts) == 5
        and parts[:2] == ["v1", "organisations"]
        and parts[3:] == ["restructure", "audit"]
    ):
        return parts[2], None, "audit-organisation"
    if (
        len(parts) == 7
        and parts[:2] == ["v1", "organisations"]
        and parts[3] == "agreements"
        and parts[5:] == ["restructure", "audit"]
    ):
        if method != "GET":
            raise _RouteError("method not allowed", 405)
        return parts[2], parts[4], "audit-agreement"
    if (
        len(parts) == 6
        and parts[:2] == ["v1", "organisations"]
        and parts[3] == "agreements"
        and parts[5] == "restructure"
    ):
        if method == "POST":
            return parts[2], parts[4], "restructure"
        if method == "GET":
            return parts[2], parts[4], "status"
        raise _RouteError("method not allowed", 405)
    raise _RouteError("route not found", 404)


def _roles(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _kind(body: dict) -> object:
    if "kind" not in body or body["kind"] is None:
        return "restructure"
    return body["kind"]


def _recognised_at(body: dict) -> date | datetime | None:
    if "recognised_at" not in body or body["recognised_at"] is None:
        return None
    raw = body["recognised_at"]
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        return date.fromisoformat(text)
    except ValueError:
        return None


def _consent_date(body: dict) -> object:
    if "consent_date" not in body or body["consent_date"] is None:
        return None
    raw = body["consent_date"]
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw)
        return date.fromisoformat(raw)
    except ValueError:
        return raw


def _result(result: RestructureResult) -> dict:
    body: dict = {"outcome": result.outcome}
    if result.outcome == "success":
        body["confirmation"] = result.confirmation
        body["original_agreement_id"] = result.original_agreement_id
        body["new_agreement_id"] = result.new_agreement_id
        body["transferred_balance_cents"] = result.transferred_balance_cents
        body["contractual_instalment_cents"] = result.contractual_instalment_cents
        body["contractual_periodic_rate_bps"] = result.contractual_periodic_rate_bps
        body["term_count"] = result.term_count
        body["payment_frequency"] = result.payment_frequency
        body["recognition_date"] = _date(result.recognition_date)
        body["recognised_at"] = _instant(result.recognised_at)
        body["client_consent"] = result.client_consent
        body["consent_date"] = _date(result.consent_date)
        body["application_number"] = result.application_number
        return body
    body["reason"] = result.reason
    if result.recognition_date is not None:
        body["recognition_date"] = _date(result.recognition_date)
    if result.recognised_at is not None:
        body["recognised_at"] = _instant(result.recognised_at)
    return body


def _status(view: StatusView) -> dict:
    if not view.recorded:
        return {
            "recorded": False,
            "outcome": "none",
            "reason": view.reason,
            "agreement_id": view.agreement_id,
        }
    return {
        "recorded": True,
        "outcome": view.outcome,
        "reason": view.reason,
        "confirmation": view.confirmation,
        "actor_person_id": view.actor_person_id,
        "occurred_at": _instant(view.occurred_at),
        "recognition_date": _date(view.recognition_date),
        "agreement_id": view.agreement_id,
        "event_type": view.event_type,
        "roles": list(view.roles),
    }


def _row(row: AuditRecord) -> dict:
    return {
        "event_id": row.event_id,
        "sequence": row.sequence,
        "event_type": row.event_type,
        "outcome": row.outcome,
        "reason": row.reason,
        "confirmation": row.confirmation,
        "actor_person_id": row.actor_person_id,
        "occurred_at": _instant(row.occurred_at),
        "recognition_date": _date(row.recognition_date),
        "agreement_id": row.agreement_id,
        "roles": list(row.roles),
        "payload": row.payload,
    }


def _date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
