"""Development stand-in for a push provider.

Delivers the statement-ready payload to the opaque person id. It does not
store a telephone number or an email address, and it does not call a network.
"""

from __future__ import annotations

from lms.notifications.errors import NotificationError
from lms.notifications.models import PAYLOAD_FIELDS, StatementReadyPayload


class DummyPush:
    def __init__(self) -> None:
        self.sent: dict[str, StatementReadyPayload] = {}
        self.calls = 0

    def deliver(self, payload: StatementReadyPayload) -> None:
        self.calls += 1
        if tuple(payload.as_dict()) != PAYLOAD_FIELDS:
            raise NotificationError(
                "push-payload",
                "The push payload has fields other than the statement-ready notice.",
            )
        existing = self.sent.get(payload.statement_id)
        if existing is not None and existing != payload:
            raise NotificationError(
                "push-conflict",
                "This statement was already pushed with a different payload.",
            )
        self.sent[payload.statement_id] = payload
