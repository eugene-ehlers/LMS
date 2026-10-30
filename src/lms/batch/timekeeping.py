"""Africa/Johannesburg timestamps for the daily calculation batch.

Recognition date is 00:00 in this zone. South African Standard Time does not
use daylight saving; a converted timestamp that is not UTC+2 is refused.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
RECOGNITION_BOUNDARY = "00:00"
TIMEZONE_NAME = "Africa/Johannesburg"


def format_jhb(value: datetime) -> str:
    """Format an aware timestamp as Africa/Johannesburg with a +02:00 offset."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("naive timestamp")
    local = value.astimezone(JOHANNESBURG)
    text = local.isoformat(timespec="microseconds")
    if not text.endswith("+02:00"):
        raise ValueError(
            f"Africa/Johannesburg offset was not +02:00 ({text})"
        )
    return text


def parse_recognition_date(value: object) -> tuple[str, str]:
    """Return the calendar date and the 00:00 Africa/Johannesburg instant.

    Accepts a calendar date (YYYY-MM-DD) or an aware timestamp that is exactly
    00:00:00.000000 in Africa/Johannesburg. Any other clock time is refused.
    """
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(
            "recognition date must be 00:00 Africa/Johannesburg"
        )
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            day = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                "recognition date must be 00:00 Africa/Johannesburg"
            ) from exc
        instant = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=JOHANNESBURG)
        return day.isoformat(), format_jhb(instant)

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "recognition date must be 00:00 Africa/Johannesburg"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("recognition date must be 00:00 Africa/Johannesburg")
    local = parsed.astimezone(JOHANNESBURG)
    if (
        local.hour != 0
        or local.minute != 0
        or local.second != 0
        or local.microsecond != 0
    ):
        raise ValueError("recognition date must be 00:00 Africa/Johannesburg")
    return local.date().isoformat(), format_jhb(local)
