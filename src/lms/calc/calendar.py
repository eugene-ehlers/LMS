"""Civil dates and NCA business days. The engine does not convert time zones."""

from __future__ import annotations

from datetime import date, timedelta


def is_business_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def binding_until(delivered_on: date, holidays: frozenset[date] = frozenset()) -> date:
    """Section 113(2)(c): the settlement statement binds for five business days after delivery.

    The delivery date itself is a valid payment date. The fifth business day after
    the delivery date is the last valid payment date. Weekends and the caller's
    public-holiday set are not business days.
    """
    cursor = delivered_on
    left = 5
    while left:
        cursor += timedelta(days=1)
        if is_business_day(cursor, holidays):
            left -= 1
    return cursor


def month_end(day: date) -> date:
    if day.month == 12:
        return date(day.year, 12, 31)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)
