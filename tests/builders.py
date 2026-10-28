"""Shared payloads for dummy tests."""

from __future__ import annotations

from datetime import date, datetime

from lms.ports.collections_software import CollectionsDefaultFlag
from lms.ports.debit_order_rail import CollectionInstruction
from lms.ports.decision_engine import Application, ConsumerIdentity, PaymentFrequency
from lms.recognition import JOHANNESBURG


def consumer() -> ConsumerIdentity:
    return ConsumerIdentity(
        person_id="person-active",
        name="Test Consumer",
        id_number="0000000000000",
    )


def application(**overrides: object) -> Application:
    values: dict[str, object] = {
        "consumer": consumer(),
        "requested_amount_cents": 150_000,
        "product_type": "short_term",
        "term_count": 6,
        "payment_frequency": PaymentFrequency.MONTHLY,
    }
    values.update(overrides)
    return Application(**values)  # type: ignore[arg-type]


def instruction(**overrides: object) -> CollectionInstruction:
    afternoon = datetime(2026, 10, 28, 15, 45, tzinfo=JOHANNESBURG)
    values: dict[str, object] = {
        "loan_number": "LN-1001",
        "amount_cents": 25_000,
        "due_date": date(2026, 11, 3),
        "recognition_at": afternoon,
        "id_number": "0000000000000",
    }
    values.update(overrides)
    return CollectionInstruction(**values)  # type: ignore[arg-type]


def collections_flag(**overrides: object) -> CollectionsDefaultFlag:
    values: dict[str, object] = {
        "loan_number": "LN-1001",
        "application_number": "APP-00000001",
        "id_number": "0000000000000",
    }
    values.update(overrides)
    return CollectionsDefaultFlag(**values)  # type: ignore[arg-type]
