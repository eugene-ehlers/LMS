from datetime import date, datetime, timezone

import pytest

from lms.errors import ContractError
from lms.recognition import JOHANNESBURG, to_recognition_instant


def test_calendar_date_is_midnight_johannesburg() -> None:
    instant = to_recognition_instant(date(2026, 10, 28))

    assert instant == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)
    assert instant.utcoffset().total_seconds() == 2 * 60 * 60
    assert instant.isoformat() == "2026-10-28T00:00:00+02:00"


def test_afternoon_on_the_same_johannesburg_day_collapses_to_midnight() -> None:
    instant = to_recognition_instant(datetime(2026, 10, 28, 15, 45, tzinfo=JOHANNESBURG))

    assert instant == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)


def test_utc_instant_uses_the_johannesburg_calendar_day() -> None:
    still_the_28th = to_recognition_instant(datetime(2026, 10, 28, 21, 30, tzinfo=timezone.utc))
    already_the_29th = to_recognition_instant(datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc))

    assert still_the_28th == datetime(2026, 10, 28, 0, 0, tzinfo=JOHANNESBURG)
    assert already_the_29th == datetime(2026, 10, 29, 0, 0, tzinfo=JOHANNESBURG)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ContractError):
        to_recognition_instant(datetime(2026, 10, 28, 0, 0))


def test_non_date_is_rejected() -> None:
    with pytest.raises(ContractError):
        to_recognition_instant("2026-10-28")  # type: ignore[arg-type]
