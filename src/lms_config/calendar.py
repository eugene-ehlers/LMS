"""Business dates for the National Credit Act.

Section 2(5): when a number of business days is provided for between two
events, exclude the day of the first event, include the day of the second,
and exclude any Saturday, Sunday, or public holiday in between.

Public holidays come from the Public Holidays Act, 1994, schedule as
currently in force (fixed dates plus Good Friday and Family Day), and
section 2(1) of that Act: a holiday that falls on a Sunday is observed on
the following Monday. A holiday that falls on a Saturday is not moved.
Presidential one-off declarations are data (``ref_public_holiday``), not
part of this function.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from lms_config.exceptions import CalculationInputError

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")

_FIXED = (
    (1, 1, "New Year's Day"),
    (3, 21, "Human Rights Day"),
    (4, 27, "Freedom Day"),
    (6, 16, "Youth Day"),
    (8, 9, "National Women's Day"),
    (9, 24, "Heritage Day"),
    (12, 16, "Day of Reconciliation"),
    (12, 25, "Christmas Day"),
    (12, 26, "Day of Goodwill"),
)


def business_date(instant: dt.datetime) -> dt.date:
    """Calendar date in Africa/Johannesburg for an aware instant.

    Due dates, holidays, and cap effective-dates are Johannesburg dates.
    South Africa does not observe daylight saving; the zone is still named
    rather than hard-coded as UTC+2.
    """
    if instant.tzinfo is None:
        raise CalculationInputError("timestamps must be timezone-aware")
    return instant.astimezone(JOHANNESBURG).date()


def easter_sunday(year: int) -> dt.date:
    """Anonymous Gregorian computus. Returns the Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def public_holidays(year: int) -> tuple[tuple[dt.date, str, str], ...]:
    """Observed holidays for ``year``.

    Each row is ``(date, name, source)`` where source is ``act`` or
    ``sunday_rule``.
    """
    rows: list[tuple[dt.date, str, str]] = []
    for month, day, name in _FIXED:
        rows.append((dt.date(year, month, day), name, "act"))
    easter = easter_sunday(year)
    rows.append((easter - dt.timedelta(days=2), "Good Friday", "act"))
    rows.append((easter + dt.timedelta(days=1), "Family Day", "act"))
    observed: list[tuple[dt.date, str, str]] = []
    for date, name, _source in rows:
        if date.weekday() == 6:
            observed.append(
                (date + dt.timedelta(days=1), f"{name} (observed)", "sunday_rule")
            )
    rows.extend(observed)
    rows.sort(key=lambda item: item[0])
    return tuple(rows)


def holiday_set(dates: list[dt.date] | set[dt.date]) -> frozenset[dt.date]:
    return frozenset(dates)


def is_business_day(day: dt.date, holidays: frozenset[dt.date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def add_business_days(start: dt.date, days: int, holidays: frozenset[dt.date]) -> dt.date:
    """The date that ends an ``days`` business-day interval under s 2(5).

    ``start`` is the day of the first event and is excluded. The returned
    day is included and is itself a business day.
    """
    if days < 0:
        raise CalculationInputError("business-day count cannot be negative")
    if days == 0:
        return start
    remaining = days
    cursor = start
    while remaining > 0:
        cursor += dt.timedelta(days=1)
        if is_business_day(cursor, holidays):
            remaining -= 1
    return cursor
