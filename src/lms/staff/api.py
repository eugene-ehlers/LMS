"""Staff HTTP routes. No consumer registration and no statement generation.

Paths and the election body are documented in ``docs/layer2/``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from lms.regulatory.errors import RegulatoryError
from lms.staff.authority import StaffActor
from lms.staff.elections import ElectionValues
from lms.staff.errors import StaffError
from lms.staff.service import StaffOffice
from lms_config.calendar import value_date
from lms_config.compliance import ProviderCompliance
from lms_config.exceptions import CalculationInputError


_ELECTION_FIELDS = (
    "vat_on_rand_maxima",
    "late_disbursement",
    "partial_prepayment",
    "interest_on_deferred_initiation",
    "repo_rate_fall",
    "in_duplum_trigger",
    "residual_write_off_threshold_cents",
    "campaign_fall_away_choice",
    "campaign_fall_away_trigger",
)


def dispatch(office: StaffOffice, method: str, path: str, body: dict | None, headers: dict | None) -> tuple[int, dict]:
    body = body or {}
    headers = headers or {}
    try:
        return 200, _route(office, method.upper(), path, body, headers)
    except StaffError as exc:
        return exc.status, {"code": exc.code, "message": str(exc)}
    except CalculationInputError as exc:
        return 422, {"code": "invalid", "message": str(exc)}
    except RegulatoryError as exc:
        return 422, {"code": exc.code, "message": str(exc)}


def _route(office: StaffOffice, method: str, path: str, body: dict, headers: dict) -> dict:
    actor = _actor(headers)
    parts = [part for part in path.split("/") if part]
    if parts[:2] != ["v1", "staff"]:
        raise StaffError("not-found", f"No route {method} {path}.", status=404)
    parts = parts[2:]

    if method == "GET" and parts == ["ceilings", "platform"]:
        return {"ceilings": [_ceiling(row) for row in office.list_platform_ceilings(actor)]}
    if method == "PUT" and parts == ["ceilings", "platform"]:
        row = office.put_platform_ceiling(
            actor,
            _instant(body),
            action=_text(body, "action"),
            amount_cents=_cents(body, "amount_cents"),
        )
        return _ceiling(row)
    if method == "POST" and parts == ["ceilings", "apply"]:
        applied = office.apply_ceiling(
            actor,
            action=_text(body, "action"),
            amount_cents=_cents(body, "amount_cents"),
            organisation_id=_text(body, "organisation_id"),
        )
        if not applied.allowed:
            raise StaffError(
                "mandate-denied",
                f"Amount {applied.amount_cents} cents exceeds the operational ceiling of {applied.limit_cents} cents.",
                status=403,
            )
        return {
            "action": applied.action,
            "amount_cents": applied.amount_cents,
            "limit_cents": applied.limit_cents,
            "platform_cents": applied.platform_cents,
            "company_cents": applied.company_cents,
            "platform_version": applied.platform_version,
            "company_version": applied.company_version,
            "allowed": applied.allowed,
        }
    if method == "GET" and parts[:1] == ["organisations"] and len(parts) == 3 and parts[2] == "campaigns":
        rows = office.list_campaigns(actor, parts[1])
        return {"campaigns": [_campaign(row) for row in rows]}
    if method == "POST" and parts[:1] == ["organisations"] and len(parts) == 3 and parts[2] == "campaigns":
        _same(actor, parts[1])
        campaign = office.create_campaign(actor, _instant(body), **_campaign_fields(body))
        return _campaign(campaign)
    if method == "GET" and _campaign_item(parts):
        return _campaign(office.get_campaign(actor, parts[3]))
    if method == "PATCH" and _campaign_item(parts):
        _same(actor, parts[1])
        campaign = office.edit_campaign(actor, parts[3], _instant(body), **_campaign_fields(body))
        return _campaign(campaign)
    if method == "POST" and len(parts) == 5 and parts[0] == "organisations" and parts[2] == "campaigns" and parts[4] == "end":
        _same(actor, parts[1])
        return _campaign(office.end_campaign(actor, parts[3], _instant(body)))
    if method == "POST" and len(parts) == 5 and parts[0] == "organisations" and parts[2] == "campaigns" and parts[4] == "fee-preview":
        _same(actor, parts[1])
        ex_vat, vat, total = office.preview_fee(
            actor,
            parts[3],
            kind=_text(body, "kind"),
            ex_vat_cents=_cents(body, "ex_vat_cents"),
            vat_rate=_rate(body, "vat_rate"),
        )
        return {"ex_vat_cents": ex_vat, "vat_cents": vat, "total_cents": total}
    if method == "GET" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "elections":
        values = office.organisation_elections(actor, parts[1])
        products = office.elections.list_products(parts[1]) if actor.organisation_id == parts[1] else ()
        return {
            "organisation": _elections(values),
            "products": [{"product_id": product_id, **_elections(row)} for product_id, row in products],
        }
    if method == "PUT" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "elections":
        _same(actor, parts[1])
        stored = office.put_organisation_elections(actor, _instant(body), _election_body(body))
        return _elections(stored)
    if method == "GET" and len(parts) == 5 and parts[0] == "organisations" and parts[2] == "products" and parts[4] == "elections":
        return _elections(office.product_elections(actor, parts[1], parts[3]))
    if method == "PUT" and len(parts) == 5 and parts[0] == "organisations" and parts[2] == "products" and parts[4] == "elections":
        _same(actor, parts[1])
        stored = office.put_product_elections(actor, parts[3], _instant(body), _election_body(body))
        return _elections(stored)
    if method == "POST" and len(parts) == 4 and parts[0] == "organisations" and parts[2] == "elections" and parts[3] == "resolve":
        product_id = body.get("product_id")
        if product_id is not None and not isinstance(product_id, str):
            raise StaffError("invalid", "product_id must be a string or null.")
        resolved = office.require_elections(actor, parts[1], product_id)
        return _elections(resolved)
    if method == "GET" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "compliance":
        return _compliance(office.get_compliance(actor, parts[1]))
    if method == "PUT" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "compliance":
        _same(actor, parts[1])
        record = office.put_compliance(actor, _instant(body), _compliance_body(parts[1], body))
        return _compliance(record)
    if method == "GET" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "ceilings":
        return {"ceilings": [_ceiling(row) for row in office.list_company_ceilings(actor, parts[1])]}
    if method == "PUT" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "ceilings":
        _same(actor, parts[1])
        row = office.put_company_ceiling(
            actor,
            _instant(body),
            action=_text(body, "action"),
            amount_cents=_cents(body, "amount_cents"),
        )
        return _ceiling(row)
    if method == "GET" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "audit":
        from lms.staff.authority import require_staff_role

        require_staff_role(actor)
        _same(actor, parts[1])
        extract = office.audit.extract(
            organisation_id=parts[1],
            from_date=_date_value(_text(body, "from") if body.get("from") else headers.get("X-From", "")),
            to_date=_date_value(_text(body, "to") if body.get("to") else headers.get("X-To", "")),
        )
        return {
            "organisation_id": extract.organisation_id,
            "from": extract.from_date.isoformat(),
            "to": extract.to_date.isoformat(),
            "verified": extract.verified,
            "rows": [
                {
                    "event_id": row.event_id,
                    "event_type": row.event_type,
                    "occurred_at": row.occurred_at.isoformat(),
                    "recognition_date": value_date(row.occurred_at).isoformat(),
                    "enigma_person_id": row.enigma_person_id,
                    "payload": row.payload,
                }
                for row in extract.rows
            ],
        }
    if method == "POST" and len(parts) == 3 and parts[0] == "organisations" and parts[2] == "decision-intake":
        _same(actor, parts[1])
        product_id = body.get("product_id")
        if product_id is not None and not isinstance(product_id, str):
            raise StaffError("invalid", "product_id must be a string or null.")
        row = office.record_decision(
            actor,
            _instant(body),
            product_id=product_id,
            application_number=_text(body, "application_number"),
            supplied_rate=_rate(body, "supplied_rate"),
            credit_life_premium_cents=_cents(body, "credit_life_premium_cents"),
            maturity_date=_optional_date(body.get("maturity_date")),
        )
        return _intake(row)
    raise StaffError("not-found", f"No route {method} /v1/staff/{'/'.join(parts)}.", status=404)


def _actor(headers: dict) -> StaffActor:
    roles = headers.get("X-Enigma-Roles", "")
    parsed = frozenset(part.strip() for part in roles.split(",") if part.strip())
    return StaffActor(
        person_id=str(headers.get("X-Enigma-Person-Id", "")),
        organisation_id=str(headers.get("X-Enigma-Organisation-Id", "")),
        roles=parsed,
        enigma_status=str(headers.get("X-Enigma-Status", "active")),
    )


def _same(actor: StaffActor, organisation_id: str) -> None:
    if actor.organisation_id != organisation_id:
        raise StaffError(
            "mandate-denied",
            "The Enigma organisation on the command is not the actor's organisation.",
            status=403,
        )


def _campaign_item(parts: list[str]) -> bool:
    return len(parts) == 4 and parts[0] == "organisations" and parts[2] == "campaigns"


def _campaign_fields(body: dict) -> dict:
    product_id = body.get("product_id")
    if product_id is not None and not isinstance(product_id, str):
        raise StaffError("invalid", "product_id must be a string or null.")
    trigger = body.get("fall_away_trigger")
    if trigger is not None and not isinstance(trigger, str):
        raise StaffError("invalid", "fall_away_trigger must be a string or null.")
    return {
        "product_id": product_id,
        "start_date": _date_value(_text(body, "start_date")),
        "end_date": _date_value(_text(body, "end_date")),
        "base_rate": _rate(body, "base_rate"),
        "discount_rate": _rate(body, "discount_rate"),
        "fall_away_choice": _text(body, "fall_away_choice"),
        "fall_away_trigger": trigger,
        "initiation_fee_discount_cents": _cents(body, "initiation_fee_discount_cents"),
        "service_fee_discount_cents": _cents(body, "service_fee_discount_cents"),
    }


def _election_body(body: dict) -> ElectionValues:
    unknown = set(body) - set(_ELECTION_FIELDS) - {"recognised_at"}
    if unknown:
        raise StaffError("invalid", f"Unknown election field {sorted(unknown)[0]}.")
    cents = body.get("residual_write_off_threshold_cents")
    if cents is not None:
        cents = _cents(body, "residual_write_off_threshold_cents")
    return ElectionValues(
        vat_on_rand_maxima=_optional_text(body, "vat_on_rand_maxima"),
        late_disbursement=_optional_text(body, "late_disbursement"),
        partial_prepayment=_optional_text(body, "partial_prepayment"),
        interest_on_deferred_initiation=_optional_text(body, "interest_on_deferred_initiation"),
        repo_rate_fall=_optional_text(body, "repo_rate_fall"),
        in_duplum_trigger=_optional_text(body, "in_duplum_trigger"),
        residual_write_off_threshold_cents=cents,
        campaign_fall_away_choice=_optional_text(body, "campaign_fall_away_choice"),
        campaign_fall_away_trigger=_optional_text(body, "campaign_fall_away_trigger"),
    )


def _compliance_body(organisation_id: str, body: dict) -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=organisation_id,
        legal_name=_text(body, "legal_name"),
        ncr_registration_number=_text(body, "ncr_registration_number"),
        trading_name="" if body.get("trading_name") is None else str(body.get("trading_name")),
        physical_address=_text(body, "physical_address"),
        postal_address=_text(body, "postal_address"),
        telephone=_text(body, "telephone"),
        bank_name=_text(body, "bank_name"),
        bank_account_number=_text(body, "bank_account_number"),
        branch_code=_text(body, "branch_code"),
        payment_reference=_text(body, "payment_reference"),
    )


def _campaign(row) -> dict:
    return {
        "campaign_id": row.campaign_id,
        "organisation_id": row.organisation_id,
        "product_id": row.product_id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "base_rate": str(row.base_rate),
        "discount_rate": str(row.discount_rate),
        "net_rate": str(row.net_rate),
        "fall_away_choice": row.fall_away_choice,
        "fall_away_trigger": row.fall_away_trigger,
        "initiation_fee_discount_cents": row.initiation_fee_discount_cents,
        "service_fee_discount_cents": row.service_fee_discount_cents,
        "version": row.version,
    }


def _elections(values: ElectionValues) -> dict:
    return {
        "vat_on_rand_maxima": values.vat_on_rand_maxima,
        "late_disbursement": values.late_disbursement,
        "partial_prepayment": values.partial_prepayment,
        "interest_on_deferred_initiation": values.interest_on_deferred_initiation,
        "repo_rate_fall": values.repo_rate_fall,
        "in_duplum_trigger": values.in_duplum_trigger,
        "residual_write_off_threshold_cents": values.residual_write_off_threshold_cents,
        "campaign_fall_away_choice": values.campaign_fall_away_choice,
        "campaign_fall_away_trigger": values.campaign_fall_away_trigger,
    }


def _compliance(record: ProviderCompliance) -> dict:
    return {
        "organisation_id": record.organisation_id,
        "legal_name": record.legal_name,
        "ncr_registration_number": record.ncr_registration_number,
        "trading_name": record.trading_name,
        "physical_address": record.physical_address,
        "postal_address": record.postal_address,
        "telephone": record.telephone,
        "bank_name": record.bank_name,
        "bank_account_number": record.bank_account_number,
        "branch_code": record.branch_code,
        "payment_reference": record.payment_reference,
    }


def _ceiling(row) -> dict:
    return {
        "scope": row.scope,
        "action": row.action,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "organisation_id": row.organisation_id,
        "version": row.version,
    }


def _intake(row) -> dict:
    return {
        "intake_id": row.intake_id,
        "organisation_id": row.organisation_id,
        "product_id": row.product_id,
        "application_number": row.application_number,
        "recognition_date": row.recognition_date.isoformat(),
        "supplied_rate": str(row.supplied_rate),
        "credit_life_premium_cents": row.credit_life_premium_cents,
        "campaign_id": row.campaign_id,
        "campaign_base_rate": None if row.campaign_base_rate is None else str(row.campaign_base_rate),
        "campaign_discount_rate": None if row.campaign_discount_rate is None else str(row.campaign_discount_rate),
        "campaign_net_rate": None if row.campaign_net_rate is None else str(row.campaign_net_rate),
        "campaign_fall_away_choice": row.campaign_fall_away_choice,
        "campaign_fall_away_trigger": row.campaign_fall_away_trigger,
        "maturity_date": None if row.maturity_date is None else row.maturity_date.isoformat(),
    }


def _instant(body: dict) -> datetime:
    raw = body.get("recognised_at")
    if not isinstance(raw, str) or not raw.strip():
        raise StaffError("invalid", "recognised_at is required.")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise StaffError("invalid", "recognised_at is not an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise StaffError("invalid", "recognised_at must carry a timezone.")
    return parsed


def _text(body: dict, name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise StaffError("invalid", f"{name} is required.")
    return value.strip()


def _optional_text(body: dict, name: str) -> str | None:
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        raise StaffError("invalid", f"{name} must be a string or null.")
    return value.strip()


def _cents(body: dict, name: str) -> int:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StaffError("invalid", f"{name} must be integer cents.")
    if value < 0:
        raise StaffError("invalid", f"{name} cannot be negative.")
    return value


def _rate(body: dict, name: str) -> Decimal:
    value = body.get(name)
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, str):
        raise StaffError("invalid", f"{name} must be a decimal string.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise StaffError("invalid", f"{name} must be a decimal string.") from exc
    if not parsed.is_finite():
        raise StaffError("invalid", f"{name} must be a finite decimal.")
    return parsed


def _date_value(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise StaffError("invalid", "A date must be YYYY-MM-DD.") from exc


def _optional_date(raw) -> date | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise StaffError("invalid", "A date must be YYYY-MM-DD.")
    return _date_value(raw)
