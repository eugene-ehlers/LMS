"""Restructure an agreement.

The path stores client consent, freezes elections and identity on a new
agreement, marks the original restructured, and transfers the outstanding
balance in integer cents. The decision engine supplies the rate, term, and
instalment. This module does not calculate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4

from lms.restructure.audit import AuditLog, AuditRecord
from lms.restructure.elections import ElectionError, FrozenElections, freeze_elections
from lms.restructure.engine import (
    DecisionEngine,
    EngineError,
    Refusal,
    RestructureFacts,
    SuppliedTerms,
)
from lms.restructure.models import Agreement
from lms.restructure.money import (
    require_basis_points,
    require_cents,
    require_frequency,
    require_term_count,
    require_text,
)
from lms.restructure.recognition import JOHANNESBURG, RecognitionError, recognition_instant


CALLER_TERM_FIELDS = frozenset(
    {
        "application_number",
        "contractual_instalment_cents",
        "contractual_periodic_rate_bps",
        "instalment_cents",
        "payment_frequency",
        "rate",
        "term",
        "term_count",
    }
)

_ACTIVE = "active"
_RESTRUCTURED = "restructured"

_ENGINE_FAILURES = {
    "timeout": (503, "decision engine timeout"),
    "ambiguous": (503, "decision engine response is ambiguous"),
    "unavailable": (503, "decision engine unavailable"),
    "rejected": (422, "decision engine rejected the restructure"),
    "incomplete": (422, "decision engine did not supply the rate, term, and instalment"),
}


class HoldError(ValueError):
    """The agreement presented for holding does not match the contract."""


class Failed(Exception):
    def __init__(self, reason: str, status: int = 422) -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True)
class RestructureResult:
    outcome: str
    http_status: int
    reason: str | None = None
    confirmation: str | None = None
    original_agreement_id: str | None = None
    new_agreement_id: str | None = None
    transferred_balance_cents: int | None = None
    contractual_instalment_cents: int | None = None
    contractual_periodic_rate_bps: int | None = None
    term_count: int | None = None
    payment_frequency: str | None = None
    recognition_date: date | None = None
    recognised_at: datetime | None = None
    client_consent: bool | None = None
    consent_date: date | None = None
    application_number: str | None = None


@dataclass(frozen=True)
class StatusView:
    recorded: bool
    http_status: int
    reason: str | None = None
    outcome: str | None = None
    confirmation: str | None = None
    actor_person_id: str | None = None
    occurred_at: datetime | None = None
    recognition_date: date | None = None
    agreement_id: str | None = None
    event_type: str | None = None
    roles: tuple[str, ...] = ()
    payload: dict | None = None


class RestructureService:
    def __init__(self, engine: DecisionEngine) -> None:
        self.engine = engine
        self.agreements: dict[str, Agreement] = {}
        self.audit = AuditLog()

    def hold_agreement(
        self,
        *,
        agreement_id: str,
        organisation_id: str,
        person_id: str,
        outstanding_balance_cents: int,
        contractual_instalment_cents: int,
        term_count: int,
        payment_frequency: str,
        contractual_periodic_rate_bps: int,
        application_number: str,
        frozen_full_name: str,
        frozen_id_number: str,
        frozen_service_address: str,
        status: str = _ACTIVE,
    ) -> Agreement:
        """Record an agreement the LMS already holds. This is not origination."""

        try:
            agreement_id = require_text(agreement_id, "agreement_id")
            organisation_id = require_text(organisation_id, "organisation_id")
            person_id = require_text(person_id, "person_id")
            balance = require_cents(outstanding_balance_cents, "outstanding_balance_cents")
            instalment = require_cents(contractual_instalment_cents, "contractual_instalment_cents")
            term = require_term_count(term_count)
            frequency = require_frequency(payment_frequency)
            rate = require_basis_points(
                contractual_periodic_rate_bps, "contractual_periodic_rate_bps"
            )
            application_number = require_text(application_number, "application_number")
            frozen_full_name = require_text(frozen_full_name, "name")
            frozen_id_number = require_text(frozen_id_number, "ID number")
            frozen_service_address = require_text(frozen_service_address, "service address")
        except ValueError as exc:
            raise HoldError(str(exc)) from exc
        if status != _ACTIVE:
            raise HoldError(f"agreement status {status} cannot be restructured")
        if agreement_id in self.agreements:
            raise HoldError("agreement is already held")
        agreement = Agreement(
            agreement_id=agreement_id,
            organisation_id=organisation_id,
            person_id=person_id,
            outstanding_balance_cents=balance,
            contractual_instalment_cents=instalment,
            term_count=term,
            payment_frequency=frequency,
            contractual_periodic_rate_bps=rate,
            application_number=application_number,
            frozen_full_name=frozen_full_name,
            frozen_id_number=frozen_id_number,
            frozen_service_address=frozen_service_address,
            status=status,
        )
        self.agreements[agreement_id] = agreement
        return agreement

    def restructure(
        self,
        *,
        organisation_id: str,
        agreement_id: str,
        actor_person_id: str | None,
        actor_status: str | None,
        actor_roles: tuple[str, ...] = (),
        recognised_at: date | datetime | None,
        client_consent: object = None,
        consent_present: bool = False,
        consent_date: object = None,
        elections: object = None,
        identity: object = None,
        kind: object = "restructure",
        caller_term_fields: frozenset[str] = frozenset(),
        header_organisation: str | None = None,
    ) -> RestructureResult:
        instant: datetime | None
        try:
            if recognised_at is None:
                raise RecognitionError(
                    "recognition date must be a calendar date or a timezone-aware instant"
                )
            instant = recognition_instant(recognised_at)
        except RecognitionError:
            instant = None
        try:
            if instant is None:
                raise Failed(
                    "recognition date must be a calendar date or a timezone-aware instant"
                )
            return self._perform(
                organisation_id=organisation_id,
                agreement_id=agreement_id,
                actor_person_id=actor_person_id,
                actor_status=actor_status,
                actor_roles=actor_roles,
                recognised_at=instant,
                client_consent=client_consent,
                consent_present=consent_present,
                consent_date=consent_date,
                elections=elections,
                identity=identity,
                kind=kind,
                caller_term_fields=caller_term_fields,
                header_organisation=header_organisation,
            )
        except Failed as exc:
            result = RestructureResult(
                outcome="failure",
                http_status=exc.status,
                reason=exc.reason,
                original_agreement_id=agreement_id or None,
                recognition_date=None if instant is None else instant.date(),
                recognised_at=instant,
            )
            if instant is not None and organisation_id and str(organisation_id).strip():
                self._audit(
                    organisation_id=str(organisation_id).strip(),
                    occurred_at=instant,
                    actor_person_id=_blank_to_none(actor_person_id),
                    outcome="failure",
                    event_type="RESTRUCTURE_FAILED",
                    reason=exc.reason,
                    confirmation=None,
                    agreement_ids=(agreement_id,) if agreement_id else (),
                    roles=actor_roles,
                    payload={
                        "reason": exc.reason,
                        "kind": kind if isinstance(kind, str) else None,
                    },
                )
            return result

    def last_status(self, organisation_id: str, agreement_id: str) -> StatusView:
        if not _matches(organisation_id, agreement_id):
            return StatusView(
                recorded=False,
                http_status=422,
                reason="agreement not found",
            )
        row = self.audit.last_for_agreement(organisation_id, agreement_id)
        if row is None:
            return StatusView(
                recorded=False,
                http_status=200,
                reason="no restructure has been recorded for this agreement",
                agreement_id=agreement_id,
            )
        return _view(row)

    def audit_for_organisation(self, organisation_id: str) -> tuple[AuditRecord, ...]:
        return self.audit.for_organisation(organisation_id)

    def audit_for_agreement(
        self, organisation_id: str, agreement_id: str
    ) -> tuple[AuditRecord, ...]:
        return self.audit.for_agreement(organisation_id, agreement_id)

    def _perform(
        self,
        *,
        organisation_id: str,
        agreement_id: str,
        actor_person_id: str | None,
        actor_status: str | None,
        actor_roles: tuple[str, ...],
        recognised_at: datetime,
        client_consent: object,
        consent_present: bool,
        consent_date: object,
        elections: object,
        identity: object,
        kind: object,
        caller_term_fields: frozenset[str],
        header_organisation: str | None,
    ) -> RestructureResult:
        actor = self._actor(actor_person_id, actor_status)
        self._header_organisation(header_organisation, organisation_id)
        self._kind(kind)
        if caller_term_fields & CALLER_TERM_FIELDS:
            raise Failed(
                "the decision engine supplies the rate, term, and instalment. "
                "Do not send them on the restructure request"
            )
        organisation_id = _text(organisation_id, "organisation_id")
        agreement_id = _text(agreement_id, "agreement_id")
        agreement = self.agreements.get(agreement_id)
        if agreement is None or agreement.organisation_id != organisation_id:
            raise Failed("agreement not found")
        if agreement.status == _RESTRUCTURED:
            raise Failed("agreement is already restructured")
        if agreement.status != _ACTIVE:
            raise Failed(f"agreement status {agreement.status} cannot be restructured")
        consent, consented_on = _consent(client_consent, consent_present, consent_date)
        frozen = _elections(elections)
        name, id_number, service_address = _identity(identity, agreement)
        supplied = self._supplied(agreement)
        _require_contractual_change(agreement, supplied)
        new_id = self._new_id()
        try:
            balance = require_cents(
                agreement.outstanding_balance_cents, "outstanding_balance_cents"
            )
        except ValueError as exc:
            raise Failed(str(exc)) from exc
        created = Agreement(
            agreement_id=new_id,
            organisation_id=agreement.organisation_id,
            person_id=agreement.person_id,
            outstanding_balance_cents=balance,
            contractual_instalment_cents=supplied.instalment_cents,
            term_count=supplied.term_count,
            payment_frequency=supplied.payment_frequency,
            contractual_periodic_rate_bps=supplied.contractual_periodic_rate_bps,
            application_number=supplied.application_number,
            frozen_full_name=name,
            frozen_id_number=id_number,
            frozen_service_address=service_address,
            status=_ACTIVE,
            elections=frozen,
            original_agreement_id=agreement.agreement_id,
            client_consent=consent,
            consent_date=consented_on,
            recognised_at=recognised_at,
        )
        agreement.outstanding_balance_cents = 0
        agreement.status = _RESTRUCTURED
        agreement.restructured_to_agreement_id = new_id
        self.agreements[new_id] = created
        confirmation = _confirmation(agreement, created, balance)
        self._audit(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            actor_person_id=actor,
            outcome="success",
            event_type="RESTRUCTURE_CONFIRMED",
            reason=None,
            confirmation=confirmation,
            agreement_ids=(agreement.agreement_id, new_id),
            roles=actor_roles,
            payload={
                "original_agreement_id": agreement.agreement_id,
                "new_agreement_id": new_id,
                "transferred_balance_cents": balance,
                "original_balance_after_cents": 0,
                "new_balance_cents": balance,
                "contractual_instalment_cents": supplied.instalment_cents,
                "contractual_periodic_rate_bps": supplied.contractual_periodic_rate_bps,
                "term_count": supplied.term_count,
                "payment_frequency": supplied.payment_frequency,
                "client_consent": True,
                "consent_date": consented_on.isoformat(),
                "application_number": supplied.application_number,
                "roles": list(actor_roles),
            },
        )
        return RestructureResult(
            outcome="success",
            http_status=200,
            confirmation=confirmation,
            original_agreement_id=agreement.agreement_id,
            new_agreement_id=new_id,
            transferred_balance_cents=balance,
            contractual_instalment_cents=supplied.instalment_cents,
            contractual_periodic_rate_bps=supplied.contractual_periodic_rate_bps,
            term_count=supplied.term_count,
            payment_frequency=supplied.payment_frequency,
            recognition_date=recognised_at.date(),
            recognised_at=recognised_at,
            client_consent=True,
            consent_date=consented_on,
            application_number=supplied.application_number,
        )

    def _actor(self, person_id: str | None, status: str | None) -> str:
        if person_id is None or not str(person_id).strip():
            raise Failed("missing staff identity", 403)
        if status is None or not str(status).strip():
            raise Failed("missing Enigma status", 403)
        token = str(status).strip().lower()
        if token == "active":
            return str(person_id).strip()
        if token == "timeout":
            raise Failed("Enigma timeout", 503)
        if token in {"ambiguous", "ambiguous_status"}:
            raise Failed("Enigma status is ambiguous", 503)
        if token in {"suspended", "suspended_enrolment"}:
            raise Failed("Enigma enrolment is suspended", 403)
        raise Failed("Enigma status is not active", 503)

    def _header_organisation(self, header: str | None, organisation_id: str) -> None:
        if header is None or not str(header).strip():
            raise Failed("missing organisation", 403)
        if str(header).strip() != organisation_id:
            raise Failed("organisation does not match the request")

    def _kind(self, kind: object) -> None:
        if kind == "restructure":
            return
        if kind == "early_settlement":
            raise Failed("early settlement is out of scope for the restructure path")
        if kind == "collection_campaign":
            raise Failed("a collection campaign is out of scope for the restructure path")
        if kind == "settlement_readvance":
            raise Failed("settlement re-advance is out of scope for the restructure path")
        if isinstance(kind, str) and kind.strip():
            raise Failed(f"kind {kind.strip()} is not a restructure")
        raise Failed("kind is not a restructure")

    def _supplied(self, agreement: Agreement) -> SuppliedTerms:
        facts = RestructureFacts(
            organisation_id=agreement.organisation_id,
            agreement_id=agreement.agreement_id,
            person_id=agreement.person_id,
            outstanding_balance_cents=agreement.outstanding_balance_cents,
            contractual_instalment_cents=agreement.contractual_instalment_cents,
            term_count=agreement.term_count,
            payment_frequency=agreement.payment_frequency,
            contractual_periodic_rate_bps=agreement.contractual_periodic_rate_bps,
        )
        try:
            supplied = self.engine.supply(facts)
        except EngineError as exc:
            supplied = Refusal(exc.code, exc.detail)
        except Exception as exc:
            raise Failed("decision engine response is ambiguous", 503) from exc
        if isinstance(supplied, Refusal):
            status, reason = _ENGINE_FAILURES.get(
                supplied.code,
                (503, "decision engine response is ambiguous"),
            )
            if supplied.code == "rejected" and supplied.detail.strip():
                reason = f"{reason}: {supplied.detail.strip()}"
            if supplied.code == "incomplete" and supplied.detail.strip():
                reason = supplied.detail.strip()
            raise Failed(reason, status)
        if not isinstance(supplied, SuppliedTerms):
            raise Failed("decision engine response is ambiguous", 503)
        return _terms(supplied)

    def _new_id(self) -> str:
        new_id = str(uuid4())
        while new_id in self.agreements:
            new_id = str(uuid4())
        return new_id

    def _audit(
        self,
        *,
        organisation_id: str,
        occurred_at: datetime,
        actor_person_id: str | None,
        outcome: str,
        event_type: str,
        reason: str | None,
        confirmation: str | None,
        agreement_ids: tuple[str, ...],
        roles: tuple[str, ...],
        payload: dict,
    ) -> None:
        if occurred_at.tzinfo is not JOHANNESBURG:
            occurred_at = recognition_instant(occurred_at)
        self.audit.append(
            organisation_id=organisation_id,
            occurred_at=occurred_at,
            actor_person_id=actor_person_id,
            outcome=outcome,
            event_type=event_type,
            reason=reason,
            confirmation=confirmation,
            agreement_ids=agreement_ids,
            roles=roles,
            payload=payload,
        )


def _text(value: object, name: str) -> str:
    try:
        return require_text(value, name)
    except ValueError as exc:
        raise Failed(str(exc)) from exc


def _matches(organisation_id: str, agreement_id: str) -> bool:
    return bool(str(organisation_id).strip()) and bool(str(agreement_id).strip())


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _consent(
    client_consent: object, consent_present: bool, consent_date: object
) -> tuple[bool, date]:
    if not consent_present or client_consent is None:
        raise Failed("missing client consent")
    if client_consent is False:
        raise Failed("client consent is required to restructure")
    if client_consent is not True:
        raise Failed("client consent must be a boolean")
    if consent_date is None:
        raise Failed("missing client consent date")
    if not isinstance(consent_date, date) or isinstance(consent_date, datetime):
        raise Failed("consent date must be YYYY-MM-DD")
    return True, consent_date


def _elections(raw: object) -> FrozenElections:
    try:
        return freeze_elections(raw)
    except ElectionError as exc:
        raise Failed(exc.reason) from exc


def _identity(raw: object, agreement: Agreement) -> tuple[str, str, str]:
    if not isinstance(raw, dict):
        raise Failed("missing identity: name")
    fields = (
        ("full_name", "name", agreement.frozen_full_name),
        ("id_number", "ID number", agreement.frozen_id_number),
        ("service_address", "service address", agreement.frozen_service_address),
    )
    stored: list[str] = []
    for key, label, frozen in fields:
        if key not in raw or raw[key] is None:
            raise Failed(f"missing identity: {label}")
        try:
            value = require_text(raw[key], label)
        except ValueError as exc:
            raise Failed(f"missing identity: {label}") from exc
        if value != frozen:
            raise Failed(
                "identity does not match the identity frozen on the original agreement: "
                f"{label}"
            )
        stored.append(value)
    return stored[0], stored[1], stored[2]


def _terms(supplied: SuppliedTerms) -> SuppliedTerms:
    try:
        rate = require_basis_points(
            supplied.contractual_periodic_rate_bps, "contractual_periodic_rate_bps"
        )
        term = require_term_count(supplied.term_count)
        frequency = require_frequency(supplied.payment_frequency)
        instalment = require_cents(supplied.instalment_cents, "instalment_cents")
        application_number = require_text(supplied.application_number, "application_number")
    except ValueError as exc:
        message = str(exc)
        if message.startswith("application_number"):
            raise Failed("decision engine did not supply application_number") from exc
        raise Failed(f"decision engine did not supply a usable term: {message}") from exc
    return SuppliedTerms(
        contractual_periodic_rate_bps=rate,
        term_count=term,
        payment_frequency=frequency,
        instalment_cents=instalment,
        application_number=application_number,
    )


def _require_contractual_change(agreement: Agreement, supplied: SuppliedTerms) -> None:
    term_changed = supplied.term_count != agreement.term_count
    instalment_changed = supplied.instalment_cents != agreement.contractual_instalment_cents
    if term_changed or instalment_changed:
        return
    if supplied.payment_frequency != agreement.payment_frequency:
        raise Failed(
            "payment frequency changed and the term count and instalment did not. "
            "Whether that change is a restructure is not locked"
        )
    if supplied.contractual_periodic_rate_bps != agreement.contractual_periodic_rate_bps:
        raise Failed(
            "a rate change that does not change the contractual term or instalment "
            "is a collection campaign"
        )
    raise Failed("no change to the contractual term or the contractual instalment")


def _confirmation(original: Agreement, created: Agreement, balance: int) -> str:
    return (
        f"Restructure confirmed. New agreement {created.agreement_id} is linked to "
        f"original agreement {original.agreement_id}. The original agreement is marked "
        f"restructured. {balance} cents transferred. Contractual instalment "
        f"{created.contractual_instalment_cents} cents stored for term "
        f"{created.term_count} {created.payment_frequency}."
    )


def _view(row: AuditRecord) -> StatusView:
    return StatusView(
        recorded=True,
        http_status=200,
        reason=row.reason,
        outcome=row.outcome,
        confirmation=row.confirmation,
        actor_person_id=row.actor_person_id,
        occurred_at=row.occurred_at,
        recognition_date=row.recognition_date,
        agreement_id=row.agreement_id,
        event_type=row.event_type,
        roles=row.roles,
        payload=dict(row.payload),
    )
