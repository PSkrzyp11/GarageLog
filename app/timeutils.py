import datetime as dt
from zoneinfo import ZoneInfo

# Entry dates are calendar dates as the user sees them in Poland, not UTC dates.
APP_TIMEZONE = ZoneInfo("Europe/Warsaw")


def today() -> dt.date:
    return dt.datetime.now(APP_TIMEZONE).date()


def local_date(moment: dt.datetime) -> dt.date:
    """The Polish calendar date of a stored (UTC) timestamp: 22:30 UTC is already the next
    day in Warsaw, so `moment.date()` alone would show yesterday's date."""
    return moment.astimezone(APP_TIMEZONE).date()
