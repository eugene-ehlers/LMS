"""System recognition instants: 00:00 Africa/Johannesburg on a calendar day."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from lms.errors import ContractError

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")


def to_recognition_instant(value: date | datetime) -> datetime:
    """Return 00:00 Africa/Johannesburg on the calendar day of ``value``.

    A calendar ``date`` is that day. A timezone-aware instant uses the
    calendar day in Africa/Johannesburg. A naive datetime is rejected because
    its calendar day is not fixed.
    """

    if isinstance(value, datetime):
        offset = None if value.tzinfo is None else value.tzinfo.utcoffset(value)
        if offset is None:
            raise ContractError(
                "recognition date must be a calendar date or a timezone-aware instant"
            )
        local_day = value.astimezone(JOHANNESBURG).date()
    elif isinstance(value, date):
        local_day = value
    else:
        raise ContractError(
            "recognition date must be a calendar date or a timezone-aware instant"
        )
    return datetime(
        local_day.year,
        local_day.month,
        local_day.day,
        0,
        0,
        0,
        tzinfo=JOHANNESBURG,
    )
