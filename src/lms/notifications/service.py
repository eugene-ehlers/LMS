"""Send the statement-ready push and direct consumers to Enigma.

Calls the Layer 1 statement store to see whether a statement has already
been issued. Calls Enigma to confirm the consumer is registered. Does not
generate the statement, and does not implement registration or sign-on.
"""

from __future__ import annotations

from datetime import date, datetime

from lms.notifications.errors import NotificationError
from lms.notifications.models import (
    STATEMENT_READY,
    STATEMENT_READY_MESSAGE,
    AuditRecord,
    EnigmaLocations,
    EnigmaRedirect,
    PushReceipt,
    StatementReadyPayload,
)
from lms.notifications.ncr import require_ncr_number
from lms.notifications.push_dummy import DummyPush
from lms.notifications.statement_port import Layer1StatementReadiness

_REGISTER_BODY = (
    "Register with Enigma to see your statement. "
    "This page does not accept a contact number, an email address, or a password."
)
_SIGN_ON_BODY = (
    "Sign in with Enigma to see your statement. "
    "This page does not accept a contact number, an email address, or a password."
)


class StatementReadyNotifications:
    def __init__(
        self,
        documents: object,
        enigma: object,
        *,
        locations: EnigmaLocations | None = None,
        push: DummyPush | None = None,
    ) -> None:
        self._statements = Layer1StatementReadiness(documents)
        self._enigma = enigma
        self._locations = locations or EnigmaLocations()
        self._push = push or DummyPush()
        self._sent: dict[str, PushReceipt] = {}
        self.audit: list[AuditRecord] = []

    def send_statement_ready(
        self,
        *,
        session_ref: str,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
        request_id: str,
        recognised_at: datetime,
    ) -> PushReceipt:
        """One push for one issued statement. Not one push per loan."""

        self._aware(recognised_at)
        issued = self._statements.find_issued(
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
        )
        if issued is None:
            raise NotificationError(
                "statement-not-ready",
                "LOCKED_DECISIONS §27: the monthly statement is not ready. No push is sent.",
            )
        if issued.organisation_id != organisation_id or issued.person_id != person_id:
            raise NotificationError(
                "statement-party",
                "LOCKED_DECISIONS §12: the issued statement is for a different client or organisation.",
            )
        if not issued.statement_id:
            raise NotificationError(
                "statement-not-ready",
                "The issued statement has no id. No push is sent.",
            )
        ncr = require_ncr_number(issued.ncr_registration_number)
        actor = self._actor(session_ref, request_id=request_id)
        prior = self._sent.get(issued.statement_id)
        if prior is not None:
            if prior.payload.ncr_registration_number != ncr or prior.payload.loan_ids != issued.loan_ids:
                raise NotificationError(
                    "push-conflict",
                    "This statement was already pushed with a different payload.",
                )
            return PushReceipt(
                payload=prior.payload,
                actor_person_id=prior.actor_person_id,
                recognised_at=prior.recognised_at,
                request_id=prior.request_id,
                replayed=True,
            )
        self._require_registered(person_id, request_id=request_id)
        payload = StatementReadyPayload(
            kind=STATEMENT_READY,
            statement_id=issued.statement_id,
            organisation_id=issued.organisation_id,
            person_id=issued.person_id,
            period_start=issued.period_start,
            period_end=issued.period_end,
            ncr_registration_number=ncr,
            legal_name=issued.legal_name,
            message=STATEMENT_READY_MESSAGE,
            loan_ids=issued.loan_ids,
        )
        self._push.deliver(payload)
        receipt = PushReceipt(
            payload=payload,
            actor_person_id=actor,
            recognised_at=recognised_at,
            request_id=request_id,
            replayed=False,
        )
        self._sent[issued.statement_id] = receipt
        self.audit.append(
            AuditRecord(
                actor_person_id=actor,
                recognised_at=recognised_at,
                action=STATEMENT_READY,
                statement_id=issued.statement_id,
                organisation_id=issued.organisation_id,
                person_id=issued.person_id,
                request_id=request_id,
            )
        )
        return receipt

    def registration_page(self) -> EnigmaRedirect:
        return self._redirect("register", self._locations.registration_url, _REGISTER_BODY)

    def sign_on_page(self) -> EnigmaRedirect:
        return self._redirect("sign_on", self._locations.sign_on_url, _SIGN_ON_BODY)

    def view_as_consumer(
        self,
        *,
        session_ref: str,
        organisation_id: str,
        period_start: date,
        period_end: date,
        request_id: str,
    ) -> object:
        """The issued statement, after Enigma registration and sign-in.

        The person id comes from the session. The LMS does not collect it
        on this page, and it does not rebuild the statement.
        """

        person_id = self._actor(session_ref, request_id=request_id)
        self._require_registered(person_id, request_id=request_id)
        stored = self._statements.raw(
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
        )
        if stored is None:
            raise NotificationError(
                "statement-not-ready",
                "No issued statement for this client at this organisation.",
            )
        return stored

    def view_as_staff(
        self,
        *,
        session_ref: str,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
        request_id: str,
    ) -> object:
        """Account information for a call-centre consumer. Locked decision 27.

        Enigma must allow the read. This method does not require the consumer
        to be registered, and it does not generate a collection notice.
        """

        self._call(
            "allow_staff_statement",
            session_ref,
            organisation_id,
            request_id=request_id,
        )
        stored = self._statements.raw(
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
        )
        if stored is None:
            raise NotificationError(
                "statement-not-ready",
                "No issued statement for this client at this organisation.",
            )
        return stored

    def _redirect(self, purpose: str, location: str | None, body: str) -> EnigmaRedirect:
        if not isinstance(location, str) or not location.strip():
            raise NotificationError(
                "enigma-url-unset",
                "LOCKED_DECISIONS §15: the LMS page directs the consumer to Enigma. "
                "No Enigma address is configured, and none is invented.",
            )
        return EnigmaRedirect(
            purpose=purpose,
            location=location.strip(),
            status_code=302,
            body=body,
        )

    def _actor(self, session_ref: str, *, request_id: str) -> str:
        actor = self._call("confirm_actor", session_ref, request_id=request_id)
        if not isinstance(actor, str) or not actor.strip():
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15 and §23: Enigma did not return the signed-in person. "
                "No system user is substituted.",
            )
        return actor.strip()

    def _require_registered(self, person_id: str, *, request_id: str) -> None:
        registration = self._call("consumer_registration", person_id, request_id=request_id)
        status = getattr(registration, "status", None)
        answered_for = getattr(registration, "person_id", None)
        if answered_for != person_id:
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: the registration answer is for a different person.",
            )
        if status == "unregistered":
            raise NotificationError(
                "consumer-unregistered",
                "LOCKED_DECISIONS §15 and §27: the consumer is not registered with Enigma. "
                "The statement is not pushed and is not shown.",
            )
        if status != "registered":
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma did not confirm this consumer's registration.",
            )

    def _call(self, name: str, *args: object, **kwargs: object) -> object:
        method = getattr(self._enigma, name, None)
        if method is None:
            raise NotificationError(
                "enigma-unbound",
                f"Enigma has no {name} operation on this port. "
                "Live identity is not read, because that returns contact details.",
            )
        return method(*args, **kwargs)

    def _aware(self, recognised_at: datetime) -> None:
        if not isinstance(recognised_at, datetime) or recognised_at.tzinfo is None:
            raise NotificationError(
                "recognition-unset",
                "The push needs a timezone-aware recognition time for the audit record. "
                "A naive time is not treated as 00:00.",
            )
