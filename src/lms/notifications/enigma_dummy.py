"""Development stand-in for the Enigma registration check.

The real Enigma port has no consumer-registration operation that is separate
from a live-identity read. That read returns email and mobile. This dummy
does not. It also does not hold an NCR number (locked decisions 15 and 21).

It is not an identity store. Tests, or a later adapter, tell it the answer
Enigma would have returned. Unknown people are unregistered. Timeout,
ambiguous status, and a clear suspended enrolment fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.notifications.errors import NotificationError
from lms.notifications.models import STAFF_STATEMENT_ACTION, RegistrationView

_REGISTRATION = frozenset({"registered", "unregistered", "suspended", "ambiguous"})
_SESSION = frozenset({"active", "expired", "revoked", "suspended", "ambiguous"})


@dataclass
class _Session:
    person_id: str
    status: str
    sign_in_clear: bool
    organisation_id: str | None
    allowed_actions: frozenset[str]


class DummyEnigma:
    def __init__(self) -> None:
        self._registration: dict[str, str] = {}
        self._sessions: dict[str, _Session] = {}
        self.registration_failure: str | None = None
        self.actor_failure: str | None = None
        self.calls: list[str] = []

    def set_registration(self, person_id: str, status: str = "registered") -> None:
        if status not in _REGISTRATION:
            raise NotificationError(
                "enigma-ambiguous",
                "The dummy was given a registration status it does not recognise.",
            )
        self._registration[person_id] = status

    def add_session(
        self,
        session_ref: str,
        *,
        person_id: str,
        status: str = "active",
        sign_in_clear: bool = True,
        organisation_id: str | None = None,
        allowed_actions: frozenset[str] = frozenset(),
    ) -> None:
        if status not in _SESSION:
            raise NotificationError(
                "enigma-ambiguous",
                "The dummy was given a session status it does not recognise.",
            )
        self._sessions[session_ref] = _Session(
            person_id=person_id,
            status=status,
            sign_in_clear=sign_in_clear,
            organisation_id=organisation_id,
            allowed_actions=frozenset(allowed_actions),
        )

    def consumer_registration(self, person_id: str, *, request_id: str) -> RegistrationView:
        self.calls.append("consumer_registration")
        self._require_request(request_id)
        failure = self.registration_failure
        if failure == "timeout":
            raise NotificationError(
                "enigma-timeout",
                "LOCKED_DECISIONS §15: Enigma timed out. The push is not sent.",
            )
        if failure == "ambiguous":
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma status is ambiguous. The push is not sent.",
            )
        if not isinstance(person_id, str) or not person_id.strip():
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: a registration check without a person id is ambiguous.",
            )
        status = self._registration.get(person_id, "unregistered")
        if status == "ambiguous":
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma did not return a clear registration.",
            )
        if status == "suspended":
            raise NotificationError(
                "enigma-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The push is not sent.",
            )
        if status not in {"registered", "unregistered"}:
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma did not return a clear registration.",
            )
        return RegistrationView(
            person_id=person_id,
            status=status,
            enigma_request_id=request_id,
        )

    def confirm_actor(self, session_ref: str, *, request_id: str) -> str:
        """Person id on a clear active Enigma session.

        For a push, that person is the audit actor (locked decision 23).
        For a consumer view, that person is the signed-in consumer.
        """

        self.calls.append("confirm_actor")
        session = self._session(session_ref, request_id=request_id, failure=self.actor_failure)
        return session.person_id

    def allow_staff_statement(
        self,
        session_ref: str,
        organisation_id: str,
        *,
        request_id: str,
    ) -> str:
        """Call-centre read. The allow comes from the session Enigma returned.

        There is no local staff list and no local role that can grant this.
        """

        self.calls.append("allow_staff_statement")
        session = self._session(session_ref, request_id=request_id, failure=self.actor_failure)
        if not isinstance(organisation_id, str) or not organisation_id.strip():
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: a staff read without an organisation is ambiguous.",
            )
        if session.organisation_id != organisation_id:
            raise NotificationError(
                "mandate-denied",
                "LOCKED_DECISIONS §27: the staff session is not for this credit-provider organisation.",
            )
        if STAFF_STATEMENT_ACTION not in session.allowed_actions:
            raise NotificationError(
                "mandate-denied",
                "LOCKED_DECISIONS §27: Enigma did not allow this staff member to read the statement. "
                "No local role is substituted.",
            )
        return session.person_id

    def _session(self, session_ref: str, *, request_id: str, failure: str | None) -> _Session:
        self._require_request(request_id)
        if failure == "timeout":
            raise NotificationError(
                "enigma-timeout",
                "LOCKED_DECISIONS §15: Enigma timed out. The call fails closed.",
            )
        if failure == "ambiguous":
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: Enigma status is ambiguous. The call fails closed.",
            )
        if not isinstance(session_ref, str) or not session_ref.strip():
            raise NotificationError(
                "reauthenticate",
                "LOCKED_DECISIONS §15: there is no Enigma session. The LMS does not sign the caller on.",
            )
        session = self._sessions.get(session_ref)
        if session is None or session.status in {"expired", "revoked"}:
            raise NotificationError(
                "reauthenticate",
                "LOCKED_DECISIONS §15: the Enigma session is not active. The LMS does not sign the caller on.",
            )
        if session.status == "suspended":
            raise NotificationError(
                "enigma-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The call fails closed.",
            )
        if (
            session.status != "active"
            or not session.sign_in_clear
            or not session.person_id.strip()
        ):
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: sign-in status is not clear. The call fails closed.",
            )
        return session

    def _require_request(self, request_id: str) -> None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise NotificationError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: an Enigma call without a request id is ambiguous.",
            )
