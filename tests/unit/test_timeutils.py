import datetime as dt

import pytest

from app.timeutils import local_date


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # 22:04 UTC is 00:04 the next day in Warsaw (summer time, UTC+2).
        (dt.datetime(2026, 10, 22, 22, 4, tzinfo=dt.UTC), dt.date(2026, 10, 23)),
        # Winter time (UTC+1): 22:59 UTC is still 23:59 the same day.
        (dt.datetime(2026, 12, 1, 22, 59, tzinfo=dt.UTC), dt.date(2026, 12, 1)),
        (dt.datetime(2026, 12, 1, 23, 0, tzinfo=dt.UTC), dt.date(2026, 12, 2)),
    ],
)
def test_local_date_is_the_polish_calendar_date(moment: dt.datetime, expected: dt.date) -> None:
    assert local_date(moment) == expected
