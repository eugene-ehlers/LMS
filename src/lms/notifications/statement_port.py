"""Read a statement Layer 1 has already issued.

``Documents.issue_statement`` on the Layer 1 branch both builds and stores
the statement. This module reads ``Documents.statements`` and does not call
``issue_statement``. Statement generation stays in Layer 1.
"""

from __future__ import annotations

from datetime import date

from lms.notifications.errors import NotificationError
from lms.notifications.models import IssuedStatement


class Layer1StatementReadiness:
    """The Layer 1 store, keyed by organisation, person, and period."""

    def __init__(self, documents: object) -> None:
        self._documents = documents

    def find_issued(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
    ) -> IssuedStatement | None:
        store = getattr(self._documents, "statements", None)
        if not isinstance(store, dict):
            raise NotificationError(
                "statement-unbound",
                "The Layer 1 statement store is not available. "
                "This layer does not generate a statement in its place.",
            )
        stored = store.get((organisation_id, person_id, period_start, period_end))
        if stored is None:
            return None
        return project_issued(stored)

    def raw(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
    ) -> object | None:
        """The object Layer 1 stored, for a consumer or staff member who may see it."""

        store = getattr(self._documents, "statements", None)
        if not isinstance(store, dict):
            raise NotificationError(
                "statement-unbound",
                "The Layer 1 statement store is not available. "
                "This layer does not generate a statement in its place.",
            )
        return store.get((organisation_id, person_id, period_start, period_end))


def project_issued(stored: object) -> IssuedStatement:
    period_start = getattr(stored, "period_start", None)
    period_end = getattr(stored, "period_end", None)
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise NotificationError(
            "statement-period",
            "The issued statement has no period. The push is not sent.",
        )
    if period_end < period_start:
        raise NotificationError(
            "statement-period",
            "The issued statement ends before it starts. The push is not sent.",
        )
    loan_ids = _loan_ids(getattr(stored, "loans", None))
    if not loan_ids:
        raise NotificationError(
            "statement-empty",
            "LOCKED_DECISIONS §12: one statement covers the client's loans. "
            "A statement with no loan is not pushed.",
        )
    return IssuedStatement(
        statement_id=_text(stored, "statement_id"),
        organisation_id=_text(stored, "organisation_id"),
        person_id=_text(stored, "person_id"),
        period_start=period_start,
        period_end=period_end,
        ncr_registration_number=_text(stored, "ncr_registration_number"),
        legal_name=_text(stored, "legal_name"),
        loan_ids=loan_ids,
    )


def _loan_ids(loans: object) -> tuple[str, ...]:
    if isinstance(loans, (str, bytes)) or not isinstance(loans, (tuple, list)) or not loans:
        return ()
    ids: list[str] = []
    for loan in loans:
        loan_id = getattr(loan, "loan_id", None)
        if not isinstance(loan_id, str) or not loan_id.strip():
            raise NotificationError(
                "statement-empty",
                "A loan on the issued statement has no loan id. The push is not sent.",
            )
        ids.append(loan_id.strip())
    return tuple(ids)


def _text(stored: object, name: str) -> str:
    value = getattr(stored, name, "")
    if not isinstance(value, str):
        return ""
    return value.strip()
