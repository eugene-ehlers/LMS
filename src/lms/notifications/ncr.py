"""NCR number on the statement-ready push.

The number is an LMS tenant attribute already copied onto the issued
statement. Enigma is not asked for it (locked decisions 15 and 21).

A missing or blank number fails closed. The locked file requires the number
on NCA communications and allows an all-zero test number. It does not define
the character pattern, so no pattern is checked here.
"""

from __future__ import annotations

from lms.notifications.errors import NotificationError


def require_ncr_number(value: object) -> str:
    if not isinstance(value, str):
        raise NotificationError(
            "ncr-blank",
            "LOCKED_DECISIONS §21 and §27: an NCA communication needs the NCR registration number. "
            "A missing number fails closed. The number is not read from Enigma.",
        )
    number = value.strip()
    if not number:
        raise NotificationError(
            "ncr-blank",
            "LOCKED_DECISIONS §21 and §27: a blank NCR registration number fails closed on an NCA communication. "
            "An all-zero test number is allowed. A blank is not a test number.",
        )
    return number
